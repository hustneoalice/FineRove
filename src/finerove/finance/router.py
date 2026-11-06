"""Authenticated finance HTTP adapters and app lifecycle integration."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Any

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request

from octop.api.deps import current_user
from octop.i18n import normalize_locale, tr
from octop.infra.users.identity import User

from .contracts import Catalog, EvaluationRequest, EvaluationResult
from .service import NeoService

router = APIRouter(prefix="/api/finance/neo", tags=["Finance"])


@router.get("/catalog", response_model=Catalog, summary="NEO 能力目录")
async def catalog(request: Request, user: Annotated[User, Depends(current_user)]) -> dict[str, Any]:
    result: dict[str, Any] = request.app.state.neo_service.catalog()
    for item in result["items"]:
        item["name"] = tr(item["name"], normalize_locale(user.locale))
    return result


@router.post("/evaluate", response_model=EvaluationResult, summary="计算受保护的 NEO 趋势柱线")
async def evaluate(
    body: EvaluationRequest, request: Request, user: Annotated[User, Depends(current_user)]
) -> EvaluationResult:
    service: NeoService = request.app.state.neo_service

    async def disconnected() -> None:
        while True:
            message = await request.receive()
            if message["type"] == "http.disconnect":
                return

    computation = asyncio.create_task(service.evaluate(user.id, body))
    connection = asyncio.create_task(disconnected())
    try:
        done, _ = await asyncio.wait((computation, connection), return_when=asyncio.FIRST_COMPLETED)
        if computation not in done:
            raise HTTPException(499, "finance.errors.cancelled")
        return await computation
    except HTTPException as exc:
        if isinstance(exc.detail, str) and exc.detail.startswith("finance.errors."):
            raise HTTPException(
                exc.status_code, tr(exc.detail, normalize_locale(user.locale))
            ) from None
        raise
    finally:
        computation.cancel()
        connection.cancel()
        await asyncio.gather(computation, connection, return_exceptions=True)


def install_finance(app: FastAPI) -> None:
    previous = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        async with previous(application):
            service = NeoService()
            application.state.neo_service = service
            try:
                yield
            finally:
                await service.close()

    app.router.lifespan_context = lifespan
    app.include_router(router)
