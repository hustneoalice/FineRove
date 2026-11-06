"""Public Tencent market facts; no YuChao runtime or local database required."""

from __future__ import annotations

import asyncio
import json
import re
import time
from collections import OrderedDict
from collections.abc import Callable
from datetime import date, datetime
from typing import Literal, TypeVar, cast

import httpx
from fastapi import HTTPException
from pydantic import Field, ValidationError

from finerove.finance.market import (
    MAX_RESPONSE_BYTES,
    REQUEST_DEADLINE,
    Adjust,
    KlineRequest,
    MarketBar,
    MarketKline,
    MarketModel,
    MarketQuote,
    SearchHit,
    SearchRequest,
    SearchResults,
    SymbolRequest,
    Valuation,
    _error,
)

Result = TypeVar("Result", bound=MarketModel)


class MinuteBar(MarketBar):
    avg: float | None = None


class MinuteResult(SymbolRequest):
    date: str
    prev_close: float | None = None
    bars: list[MinuteBar] = Field(max_length=300)


class NativeIntradayKline(SymbolRequest):
    period: Literal["60"] = "60"
    adjust: Literal["raw"] = "raw"
    bars: list[MarketBar] = Field(max_length=640)


class QuotesResult(MarketModel):
    items: list[MarketQuote] = Field(max_length=50)
    missing: list[str] = Field(max_length=50)


class IndexItem(MarketModel):
    symbol: str
    name: str | None = None
    price: float | None = None
    chg: float | None = None
    pct: float | None = None
    amount: float | None = None


class IndicesResult(MarketModel):
    items: list[IndexItem]
    total_amount: float | None = None


class SparkItem(SymbolRequest):
    prev_close: float | None = None
    points: list[float] = Field(max_length=300)


class SparksResult(MarketModel):
    items: list[SparkItem] = Field(max_length=20)
    missing: list[str] = Field(max_length=20)


def _tx(symbol: str) -> str:
    code, market = symbol.split(".")
    return market.lower() + code


def _index(symbol: str) -> bool:
    return (
        (symbol.endswith(".SH") and symbol.startswith("000"))
        or (symbol.endswith(".SZ") and symbol.startswith("399"))
        or symbol == "899050.BJ"
    )


def _volume_factor(symbol: str) -> int:
    return 1 if symbol.startswith(("688", "689")) and symbol.endswith(".SH") else 100


class NativeMarketService:
    configured = True

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self.client = client or httpx.AsyncClient(
            trust_env=False,
            follow_redirects=False,
            timeout=REQUEST_DEADLINE,
            limits=httpx.Limits(max_connections=8, max_keepalive_connections=8),
        )
        self._owns_client = client is None
        self._active = 0
        self._cache: OrderedDict[str, tuple[float, MarketModel]] = OrderedDict()

    async def close(self) -> None:
        if self._owns_client:
            await self.client.aclose()

    async def _read(self, urls: tuple[str, ...], params: dict[str, str]) -> bytes:
        for url in urls:
            try:
                request = httpx.Request(
                    "GET",
                    url,
                    params=params,
                    headers={
                        "Referer": "https://gu.qq.com/",
                        "User-Agent": "FinRove/1.0",
                    },
                )
                response = await self.client.send(
                    request, stream=True, auth=None, follow_redirects=False
                )
                try:
                    if response.status_code != 200:
                        raise ValueError("upstream status")
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        if len(body) + len(chunk) > MAX_RESPONSE_BYTES:
                            raise ValueError("oversized response")
                        body.extend(chunk)
                    return bytes(body)
                finally:
                    await response.aclose()
            except (httpx.HTTPError, ValueError):
                continue
        raise ValueError("upstream unavailable")

    async def _request(
        self,
        key: str,
        ttl: int,
        urls: tuple[str, ...],
        params: dict[str, str],
        parse: Callable[[bytes], Result],
    ) -> Result:
        cached = self._cache.get(key)
        if cached and cached[0] > time.monotonic():
            self._cache.move_to_end(key)
            return cast(Result, cached[1].model_copy(deep=True))
        if self._active >= 8:
            raise _error(429, "busy")
        self._active += 1
        try:
            async with asyncio.timeout(REQUEST_DEADLINE):
                result = parse(await self._read(urls, params))
            self._cache[key] = (time.monotonic() + ttl, result)
            self._cache.move_to_end(key)
            while len(self._cache) > 128:
                self._cache.popitem(last=False)
            return result.model_copy(deep=True)
        except (
            httpx.HTTPError,
            TimeoutError,
            ValueError,
            KeyError,
            TypeError,
            IndexError,
            RecursionError,
        ):
            raise _error(502, "upstream") from None
        finally:
            self._active -= 1

    async def search(self, q: str, limit: int = 20) -> SearchResults:
        try:
            request = SearchRequest(q=q.strip(), limit=limit)
        except ValidationError:
            raise _error(422, "invalidRequest") from None

        def parse(raw: bytes) -> SearchResults:
            match = re.fullmatch(
                r"\s*(?:var\s+)?v_hint\s*=\s*['\"](.*?)['\"];?\s*", raw.decode("gbk"), re.S
            )
            if not match:
                raise ValueError("invalid search")
            hits = []
            for entry in match[1].split("^"):
                if not entry:
                    continue
                parts = entry.split("~")
                if len(parts) < 5:
                    raise ValueError("invalid hit")
                market, code, name = parts[:3]
                name = re.sub(r"\\u([0-9a-fA-F]{4})", lambda m: chr(int(m[1], 16)), name)
                if market not in ("sh", "sz", "bj"):
                    continue
                symbol = f"{code}.{market.upper()}"
                kind: Literal["stock", "fund", "index"] = (
                    "index"
                    if _index(symbol) or parts[4] == "ZS"
                    else "fund"
                    if parts[4] in ("JJ", "ETF", "LOF")
                    else "stock"
                )
                hits.append(SearchHit(symbol=symbol, market=market.upper(), name=name, kind=kind))
            return SearchResults(items=hits[: request.limit], total=len(hits))

        return await self._request(
            f"search:{request.q}:{limit}",
            60,
            ("https://smartbox.gtimg.cn/s3/",),
            {"t": "all", "q": request.q},
            parse,
        )

    async def kline(self, symbol: str, adjust: Adjust = "qfq", limit: int = 500) -> MarketKline:
        try:
            request = KlineRequest(symbol=symbol, adjust=adjust, limit=limit)
        except ValidationError:
            raise _error(422, "invalidRequest") from None
        tx = _tx(symbol)
        adjustment = "" if adjust == "raw" else adjust

        def parse(raw: bytes) -> MarketKline:
            data = json.loads(raw)["data"][tx]
            # Index prices have no corporate actions; Tencent returns only day.
            key = "day" if _index(symbol) else adjustment + "day"
            rows = data[key]
            if not isinstance(rows, list) or not rows:
                raise ValueError("missing bars")
            bars = []
            previous = ""
            for row in rows:
                day = row[0]
                if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day) or day <= previous:
                    raise ValueError("invalid date order")
                date.fromisoformat(day)
                previous = day
                bar = MarketBar(
                    date=day,
                    open=row[1],
                    close=row[2],
                    high=row[3],
                    low=row[4],
                    volume=float(row[5]) * _volume_factor(symbol),
                )
                if (
                    bar.low > min(bar.open, bar.close)
                    or bar.high < max(bar.open, bar.close)
                    or bar.low < 0
                    or (bar.volume or 0) < 0
                ):
                    raise ValueError("invalid OHLC")
                bars.append(bar)
            metadata = data.get("qt", {})
            if not isinstance(metadata, dict):
                raise ValueError("invalid quote metadata")
            qt = metadata.get(tx, [])
            if not isinstance(qt, list):
                raise ValueError("invalid quote fields")
            return MarketKline(
                symbol=symbol,
                name=qt[1] if len(qt) > 1 else None,
                adjust=adjust,
                bars=bars[-request.limit :],
            )

        return await self._request(
            f"kline:{symbol}:{adjust}:{limit}",
            30,
            (
                "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get",
                "https://ifzq.gtimg.cn/appstock/app/fqkline/get",
            ),
            {"param": f"{tx},day,,,{min(limit, 640)},{adjustment}"},
            parse,
        )

    def _parse_quote(self, raw: bytes, symbol: str) -> MarketQuote:
        tx = _tx(symbol)
        match = re.search(rf'(?:^|;)\s*v_{tx}="([^"\r\n]*)";?\s*', raw.decode("gbk"))
        if not match:
            raise ValueError("invalid quote")
        fields = match[1].split("~")
        if len(fields) < 38 or fields[2] != symbol[:6]:
            raise ValueError("mismatched quote")
        timestamp = datetime.strptime(fields[30], "%Y%m%d%H%M%S")
        day = timestamp.date().isoformat()

        def number(index: int) -> float | None:
            return float(fields[index]) if len(fields) > index and fields[index] else None

        volume, amount = number(36), number(37)
        total_mv, circ_mv = number(45), number(44)
        return MarketQuote(
            symbol=symbol,
            name=fields[1],
            market=symbol[-2:],
            date=day,
            open=number(5),
            high=number(33),
            low=number(34),
            close=number(3),
            pct_chg=number(32),
            volume=volume * _volume_factor(symbol) if volume is not None else None,
            amount=amount * 10000 if amount is not None else None,
            turnover_rate=number(38),
            valuation=None
            if _index(symbol)
            else Valuation(
                date=day,
                pe_ttm=number(39),
                pb=number(46),
                total_mv=total_mv * 1e8 if total_mv is not None else None,
                circ_mv=circ_mv * 1e8 if circ_mv is not None else None,
            ),
            rt_price=number(3),
            rt_prev_close=number(4),
            rt_date=day,
            rt_time=timestamp.strftime("%H:%M:%S"),
        )

    async def quote(self, symbol: str) -> MarketQuote:
        try:
            SymbolRequest(symbol=symbol)
        except ValidationError:
            raise _error(422, "invalidRequest") from None
        tx = _tx(symbol)

        return await self._request(
            f"quote:{symbol}",
            5,
            ("https://qt.gtimg.cn/",),
            {"q": tx},
            lambda raw: self._parse_quote(raw, symbol),
        )

    def _symbols(self, symbols: list[str], limit: int) -> list[str]:
        if not symbols or len(symbols) > limit:
            raise _error(422, "invalidRequest")
        try:
            for symbol in symbols:
                SymbolRequest(symbol=symbol)
        except ValidationError:
            raise _error(422, "invalidRequest") from None
        return list(dict.fromkeys(symbols))

    async def quotes(self, symbols: list[str]) -> QuotesResult:
        symbols = self._symbols(symbols, 50)

        def parse(raw: bytes) -> QuotesResult:
            items, missing = [], []
            for symbol in symbols:
                try:
                    items.append(self._parse_quote(raw, symbol))
                except (ValueError, IndexError):
                    missing.append(symbol)
            if not items:
                raise ValueError("missing batch quotes")
            return QuotesResult(items=items, missing=missing)

        return await self._request(
            "quotes:" + ",".join(symbols),
            5,
            ("https://qt.gtimg.cn/",),
            {"q": ",".join(_tx(symbol) for symbol in symbols)},
            parse,
        )

    async def indices(self) -> IndicesResult:
        result = await self.quotes(
            ["000001.SH", "399001.SZ", "399006.SZ", "000688.SH", "899050.BJ"]
        )
        return IndicesResult(
            items=[
                IndexItem(
                    symbol=q.symbol,
                    name=q.name,
                    price=q.rt_price,
                    pct=q.pct_chg,
                    amount=q.amount,
                    chg=q.rt_price - q.rt_prev_close
                    if q.rt_price is not None and q.rt_prev_close is not None
                    else None,
                )
                for q in result.items
            ]
        )

    async def sparks(self, symbols: list[str]) -> SparksResult:
        symbols = self._symbols(symbols, 20)
        items, missing = [], []
        # Sequential bounded reads avoid exhausting the service's eight slots.
        try:
            async with asyncio.timeout(REQUEST_DEADLINE):
                for symbol in symbols:
                    try:
                        minute = await self.minute(symbol)
                        items.append(
                            SparkItem(
                                symbol=symbol,
                                prev_close=minute.prev_close,
                                points=[bar.close for bar in minute.bars],
                            )
                        )
                    except HTTPException as error:
                        if error.status_code != 502:
                            raise
                        missing.append(symbol)
        except TimeoutError:
            raise _error(502, "upstream") from None
        return SparksResult(items=items, missing=missing)

    async def kline60(self, symbol: str, limit: int = 320) -> NativeIntradayKline:
        try:
            KlineRequest(symbol=symbol, adjust="raw", limit=limit)
        except ValidationError:
            raise _error(422, "invalidRequest") from None
        tx = _tx(symbol)

        def parse(raw: bytes) -> NativeIntradayKline:
            rows = json.loads(raw)["data"][tx]["m60"]
            if not isinstance(rows, list) or not rows or len(rows) > 640:
                raise ValueError("invalid hourly bars")
            bars, previous = [], ""
            for row in rows:
                stamp = datetime.strptime(row[0], "%Y%m%d%H%M").strftime("%Y-%m-%d %H:%M")
                if stamp <= previous:
                    raise ValueError("unordered hourly bars")
                previous = stamp
                bar = MarketBar(
                    date=stamp,
                    open=row[1],
                    close=row[2],
                    high=row[3],
                    low=row[4],
                    volume=float(row[5]) * _volume_factor(symbol),
                )
                if (
                    bar.low < 0
                    or bar.low > min(bar.open, bar.close)
                    or bar.high < max(bar.open, bar.close)
                    or (bar.volume or 0) < 0
                ):
                    raise ValueError("invalid hourly OHLC")
                bars.append(bar)
            return NativeIntradayKline(symbol=symbol, bars=bars[-limit:])

        return await self._request(
            f"kline60:{symbol}:{limit}",
            30,
            ("https://ifzq.gtimg.cn/appstock/app/kline/mkline",),
            {"param": f"{tx},m60,,{min(limit, 640)}"},
            parse,
        )

    async def minute(self, symbol: str) -> MinuteResult:
        try:
            SymbolRequest(symbol=symbol)
        except ValidationError:
            raise _error(422, "invalidRequest") from None
        tx = _tx(symbol)

        def parse(raw: bytes) -> MinuteResult:
            data = json.loads(raw)["data"][tx]
            body = data["data"]
            day = datetime.strptime(body["date"], "%Y%m%d").date().isoformat()
            rows = body["data"]
            if not isinstance(rows, list) or len(rows) > 300:
                raise ValueError("invalid minute bars")
            metadata = data.get("qt", {})
            if not isinstance(metadata, dict):
                raise ValueError("invalid quote metadata")
            qt = metadata.get(tx, [])
            if not isinstance(qt, list):
                raise ValueError("invalid quote fields")
            previous, previous_volume, previous_amount = "", 0.0, 0.0
            bars = []
            for row in rows:
                if not isinstance(row, str):
                    raise ValueError("invalid minute row")
                parts = row.split()
                stamp = datetime.strptime(parts[0], "%H%M").strftime("%H:%M")
                if stamp <= previous:
                    raise ValueError("unordered minutes")
                previous = stamp
                price, cumulative_volume = float(parts[1]), float(parts[2])
                cumulative_amount = float(parts[3]) if len(parts) >= 4 else None
                # Missing amount remains unknown; never fabricate traded money.
                factor = _volume_factor(symbol)
                if cumulative_amount is not None and cumulative_volume > 0 and not _index(symbol):
                    factor = 100 if cumulative_amount / cumulative_volume > price * 1.6 else 1
                volume = max(0.0, cumulative_volume - previous_volume) * factor
                amount = (
                    max(0.0, cumulative_amount - previous_amount)
                    if cumulative_amount is not None
                    else None
                )
                avg = (
                    cumulative_amount / (cumulative_volume * factor)
                    if cumulative_amount is not None
                    and cumulative_volume > 0
                    and not _index(symbol)
                    else None
                )
                if avg is not None and not price * 0.4 <= avg <= price * 1.6:
                    avg = None
                if (
                    price < 0
                    or cumulative_volume < 0
                    or (cumulative_amount is not None and cumulative_amount < 0)
                ):
                    raise ValueError("invalid minute values")
                bars.append(
                    MinuteBar(
                        date=f"{day} {stamp}",
                        open=price,
                        high=price,
                        low=price,
                        close=price,
                        volume=volume,
                        amount=amount,
                        avg=avg,
                    )
                )
                previous_volume = cumulative_volume
                previous_amount = cumulative_amount or 0.0
            if len(bars) == 1 and not bars[0].volume and not bars[0].amount:
                bars = []
            return MinuteResult(
                symbol=symbol,
                date=day,
                prev_close=float(qt[4]) if len(qt) > 4 and qt[4] else None,
                bars=bars,
            )

        return await self._request(
            f"minute:{symbol}",
            5,
            (
                "https://ifzq.gtimg.cn/appstock/app/minute/query",
                "https://proxy.finance.qq.com/ifzqgtimg/appstock/app/minute/query",
            ),
            {"code": tx},
            parse,
        )
