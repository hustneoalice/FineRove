"""Bounded, read-only market facts from the separately deployed YuChao service."""

from __future__ import annotations

import asyncio
import json
import os
import re
from datetime import date
from typing import Annotated, Literal, TypeVar
from urllib.parse import urlsplit

import httpx
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, ValidationError

Symbol = Annotated[str, Field(pattern=r"^[0-9]{6}\.(SH|SZ|BJ)$")]
Adjust = Literal["raw", "qfq", "hfq"]
REQUEST_DEADLINE = 10.0
MAX_RESPONSE_BYTES = 2 * 1024 * 1024


class MarketModel(BaseModel):
    model_config = ConfigDict(extra="ignore", allow_inf_nan=False)


class SearchRequest(MarketModel):
    q: str = Field(min_length=1, max_length=20)
    limit: int = Field(default=20, ge=1, le=50)


class SymbolRequest(MarketModel):
    symbol: Symbol


class KlineRequest(SymbolRequest):
    adjust: Adjust = "qfq"
    limit: int = Field(default=500, ge=1, le=1000)


class SearchHit(MarketModel):
    symbol: Symbol
    name: str | None = None
    market: str | None = None
    industry: str | None = None
    status: str | None = None
    kind: Literal["stock", "fund", "index"] = "stock"


class SearchResults(MarketModel):
    items: list[SearchHit] = Field(max_length=50)
    total: int = Field(ge=0)


class MarketBar(MarketModel):
    date: str
    open: float
    high: float
    low: float
    close: float
    volume: float | None = None
    amount: float | None = None
    pct_chg: float | None = None
    turnover_rate: float | None = None
    live: bool | None = None


class MarketKline(MarketModel):
    symbol: Symbol
    name: str | None = None
    period: Literal["day"] = "day"
    adjust: Adjust
    bars: list[MarketBar] = Field(max_length=1000)


class Valuation(MarketModel):
    date: str
    pe_ttm: float | None = None
    pb: float | None = None
    ps_ttm: float | None = None
    total_mv: float | None = None
    circ_mv: float | None = None


class CapitalFlowDay(MarketModel):
    date: str
    net_main: float | None = None
    net_super: float | None = None
    net_large: float | None = None
    net_medium: float | None = None
    net_small: float | None = None


class MarketQuote(MarketModel):
    symbol: Symbol
    name: str | None = None
    market: str | None = None
    industry: str | None = None
    concept: str | None = None
    status: str | None = None
    date: str | None = None
    open: float | None = None
    high: float | None = None
    low: float | None = None
    close: float | None = None
    pct_chg: float | None = None
    volume: float | None = None
    amount: float | None = None
    turnover_rate: float | None = None
    valuation: Valuation | None = None
    capital_flow: CapitalFlowDay | None = None
    rt_price: float | None = None
    rt_time: str | None = None
    rt_date: str | None = None
    rt_live: bool | None = None
    rt_prev_close: float | None = None


Model = TypeVar("Model", bound=MarketModel)


def _error(status: int, key: str) -> HTTPException:
    return HTTPException(status_code=status, detail=f"finance.market.errors.{key}")


def _origin(value: str) -> str:
    try:
        url = urlsplit(value)
        if (
            not url.hostname
            or url.username is not None
            or url.password is not None
            or "?" in value
            or "#" in value
            or url.query
            or url.fragment
            or url.path not in ("", "/")
            or any(c.isspace() or ord(c) < 32 for c in value)
            or "\\" in value
            or not (
                url.scheme == "https"
                or (url.scheme == "http" and url.hostname in ("127.0.0.1", "::1", "localhost"))
            )
        ):
            return ""
        _ = url.port
        return value.rstrip("/")
    except ValueError:
        return ""


class MarketService:
    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self.base = _origin(os.getenv("FINEROVE_MARKET_BASE_URL", ""))
        self.configured = bool(self.base)
        self.client = client or httpx.AsyncClient(
            trust_env=False,
            follow_redirects=False,
            timeout=REQUEST_DEADLINE,
            limits=httpx.Limits(max_connections=8, max_keepalive_connections=8),
        )
        self._owns_client = client is None
        self._active = 0

    async def close(self) -> None:
        if self._owns_client:
            await self.client.aclose()

    async def _get(
        self,
        endpoint: Literal["search", "kline", "quote"],
        params: MarketModel,
        output: type[Model],
    ) -> Model:
        if not self.configured:
            raise _error(503, "unavailable")
        if self._active >= 8:
            raise _error(429, "busy")
        self._active += 1
        try:
            async with asyncio.timeout(REQUEST_DEADLINE):
                # Construct directly so injected client defaults cannot attach credentials/cookies.
                request = httpx.Request(
                    "GET",
                    f"{self.base}/api/v1/market/{endpoint}",
                    params={
                        **params.model_dump(),
                        **({"kinds": "stock,fund,index"} if endpoint == "search" else {}),
                    },
                )
                response = await self.client.send(
                    request, stream=True, follow_redirects=False, auth=None
                )
                try:
                    if response.status_code != 200:
                        raise _error(502, "upstream")
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        if len(body) + len(chunk) > MAX_RESPONSE_BYTES:
                            raise _error(502, "upstream")
                        body.extend(chunk)
                    data = json.loads(body)
                    if not isinstance(data, dict):
                        raise ValueError("invalid envelope")
                    rows = data.get("items", []) if endpoint == "search" else [data]
                    if not isinstance(rows, list):
                        raise ValueError("invalid items")
                    for row in rows:
                        if not isinstance(row, dict):
                            raise ValueError("invalid item")
                        symbol = row.get("symbol")
                        if isinstance(symbol, str) and re.fullmatch(r"[0-9]{6}", symbol):
                            market = row.get("market")
                            if market not in ("SH", "SZ", "BJ"):
                                market = (
                                    "BJ"
                                    if symbol.startswith(("43", "83", "87", "92"))
                                    else "SH"
                                    if symbol.startswith(("5", "6", "9"))
                                    else "SZ"
                                )
                            row["symbol"] = f"{symbol}.{market}"
                    if endpoint == "kline":
                        bars = data.get("bars")
                        if not isinstance(params, KlineRequest) or not isinstance(bars, list):
                            raise ValueError("invalid bars")
                        previous = ""
                        for bar in bars:
                            day = bar.get("date") if isinstance(bar, dict) else None
                            if not isinstance(day, str) or not re.fullmatch(
                                r"[0-9]{4}-[0-9]{2}-[0-9]{2}", day
                            ):
                                raise ValueError("invalid date")
                            date.fromisoformat(day)
                            if day <= previous:
                                raise ValueError("unordered dates")
                            previous = day
                        if len(bars) > params.limit:
                            if len(bars) != params.limit + 1 or bars[-1].get("live") is not True:
                                raise ValueError("excess bars")
                            data["bars"] = bars[1:]
                    return output.model_validate(data)
                finally:
                    await response.aclose()
        except (httpx.HTTPError, TimeoutError, ValidationError, ValueError, RecursionError):
            raise _error(502, "upstream") from None
        finally:
            self._active -= 1

    async def search(self, q: str, limit: int = 20) -> SearchResults:
        try:
            params = SearchRequest(q=q, limit=limit)
        except ValidationError:
            raise _error(422, "invalidRequest") from None
        return await self._get("search", params, SearchResults)

    async def kline(self, symbol: str, adjust: Adjust = "qfq", limit: int = 500) -> MarketKline:
        try:
            params = KlineRequest(symbol=symbol, adjust=adjust, limit=limit)
        except ValidationError:
            raise _error(422, "invalidRequest") from None
        result = await self._get("kline", params, MarketKline)
        if result.symbol != symbol or result.adjust != adjust or len(result.bars) > limit:
            raise _error(502, "upstream")
        return result

    async def quote(self, symbol: str) -> MarketQuote:
        try:
            params = SymbolRequest(symbol=symbol)
        except ValidationError:
            raise _error(422, "invalidRequest") from None
        result = await self._get("quote", params, MarketQuote)
        if result.symbol != symbol:
            raise _error(502, "upstream")
        return result
