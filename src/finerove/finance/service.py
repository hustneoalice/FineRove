"""Bounded asynchronous delegation; no local calculation or result cache."""

from __future__ import annotations

import asyncio
import os
import time
import uuid
from typing import Any
from urllib.parse import urlsplit

import httpx
import jwt
from fastapi import HTTPException
from pydantic import ValidationError

from .contracts import EvaluationRequest, EvaluationResult, InputBar
from .market import MarketService
from .native_market import NativeMarketService

REQUEST_DEADLINE = 15.0

CAPABILITIES = (
    "short_trend",
    "mid_trend",
    "money_bag",
    "trend_histogram",
    "mainforce_accumulation",
    "mainforce_cost",
    "core_targets",
    "six_segment",
)


class NeoService:
    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        market: MarketService | NativeMarketService | None = None,
    ) -> None:
        self.base = os.getenv("FINEROVE_NEO_BASE_URL", "").rstrip("/")
        self.key = os.getenv("FINEROVE_NEO_SIGNING_KEY", "")
        self.issuer = os.getenv("FINEROVE_NEO_ISSUER", "")
        url = urlsplit(self.base)
        self.configured = bool(
            len(self.key) >= 32
            and self.issuer
            and url.hostname
            and not url.username
            and not url.password
            and not url.query
            and not url.fragment
            and url.path in ("", "/")
            and (
                url.scheme == "https"
                or (url.scheme == "http" and url.hostname in ("127.0.0.1", "::1"))
            )
        )
        self.client = client or httpx.AsyncClient(
            timeout=15,
            follow_redirects=False,
            limits=httpx.Limits(max_connections=8, max_keepalive_connections=8),
        )
        self.inflight: dict[str, tuple[asyncio.Task[EvaluationResult], int]] = {}
        self.market = market or NativeMarketService()
        self._owns_market = market is None

    def catalog(self) -> dict[str, Any]:
        return {
            "configured": self.configured,
            "expert_tool_available": False,
            "items": [
                {
                    "id": "neo." + key,
                    "name": "finance.capabilities." + key,
                    "connected": self.configured and key == "trend_histogram",
                    "origin": "formula_migration" if key == "trend_histogram" else "not_connected",
                    "verification_status": "not_pointwise_validated"
                    if key == "trend_histogram"
                    else "unavailable",
                }
                for key in CAPABILITIES
            ],
        }

    async def close(self) -> None:
        for task, _ in self.inflight.values():
            task.cancel()
        if self.inflight:
            await asyncio.gather(
                *(task for task, _ in self.inflight.values()), return_exceptions=True
            )
        await self.client.aclose()
        if self._owns_market:
            await self.market.close()

    async def evaluate(self, user_id: int, body: EvaluationRequest) -> EvaluationResult:
        if not self.configured:
            raise HTTPException(503, "finance.errors.unconfigured")
        key = str(user_id) + ":" + body.model_dump_json()
        entry = self.inflight.get(key)
        if entry is None:
            if len(self.inflight) >= 8:
                raise HTTPException(429, "finance.errors.busy")
            entry = (asyncio.create_task(self._request(user_id, body)), 0)
        task, count = entry
        if count >= 32:
            raise HTTPException(429, "finance.errors.busy")
        self.inflight[key] = (task, count + 1)
        try:
            return await asyncio.shield(task)
        finally:
            current = self.inflight.get(key)
            if current and current[0] is task:
                if current[1] == 1:
                    self.inflight.pop(key)
                    if not task.done():
                        task.cancel()
                else:
                    self.inflight[key] = (task, current[1] - 1)

    async def _request(self, user_id: int, body: EvaluationRequest) -> EvaluationResult:
        try:
            async with asyncio.timeout(REQUEST_DEADLINE):
                return await self._compute(user_id, body)
        except (httpx.HTTPError, ValidationError, ValueError, TimeoutError):
            raise HTTPException(502, "finance.errors.upstream_failed") from None

    async def _compute(self, user_id: int, body: EvaluationRequest) -> EvaluationResult:
        if body.bars is None:
            _, market, _, symbol = body.instrument_id.split(":")
            history = await self.market.kline(f"{symbol}.{market}", adjust=body.adjust, limit=1000)
            body = body.model_copy(
                update={
                    "bars": [
                        InputBar.model_validate(
                            {
                                key: value
                                for key, value in bar.model_dump().items()
                                if key in InputBar.model_fields
                            }
                        )
                        for bar in history.bars
                        if bar.date <= body.end.isoformat()
                    ]
                }
            )
        digest = body.input_snapshot_id()
        now = int(time.time())
        token = jwt.encode(
            {
                "iss": self.issuer,
                "aud": "neo-compute",
                "sub": str(user_id),
                "scope": body.capability,
                "input_snapshot_id": digest,
                "iat": now,
                "exp": now + 30,
                "jti": uuid.uuid4().hex,
            },
            self.key,
            algorithm="HS256",
        )
        try:
            async with asyncio.timeout(REQUEST_DEADLINE):
                response = await self.client.post(
                    self.base + "/api/v1/neo/evaluate",
                    json=body.model_dump(mode="json") | {"input_snapshot_id": digest},
                    headers={"Authorization": "Bearer " + token},
                )
            if response.status_code == 401:
                raise HTTPException(502, "finance.errors.authentication_failed")
            if response.status_code in (403, 429, 503):
                raise HTTPException(response.status_code, "finance.errors.denied")
            response.raise_for_status()
            result = EvaluationResult.model_validate(response.json())
            if (
                result.instrument_id != body.instrument_id
                or result.capability != body.capability
                or result.period != body.period
                or result.adjust != body.adjust
                or result.input_snapshot_id != digest
                or result.coverage.bars != len(body.bars or [])
                or [p.date for p in result.points]
                != [b.date for b in (body.bars or [])[-body.limit :]]
                or result.as_of != (body.bars[-1].date if body.bars else None)
                or result.status != ("ok" if body.bars else "empty")
            ):
                raise ValueError("invalid result")
            return result
        except (httpx.HTTPError, ValidationError, ValueError, TimeoutError):
            raise HTTPException(502, "finance.errors.upstream_failed") from None
