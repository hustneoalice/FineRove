"""Thin, authenticated market and account-watchlist HTTP adapters."""

import asyncio
from collections.abc import Awaitable, Coroutine
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from octop.api.deps import current_user, get_server
from octop.i18n import tr
from octop.infra.server import OctopServer
from octop.infra.users.identity import User
from octop.infra.utils.locale import resolve_locale, resolve_request_locale

from .market import (
    KlineRequest,
    MarketKline,
    MarketQuote,
    MarketService,
    SearchRequest,
    SearchResults,
    SymbolRequest,
)
from .native_market import (
    IndicesResult,
    MinuteResult,
    NativeIntradayKline,
    NativeMarketService,
    QuotesResult,
    SparksResult,
)
from .preferences import Preferences, PreferencesManager, PreferencesUpdate
from .watchlist import Watchlist, WatchlistManager, WatchlistUpdate

router = APIRouter(prefix="/api/finance", tags=["Finance"])
Account = Annotated[User, Depends(current_user)]


class MarketStatus(BaseModel):
    configured: bool


class SearchParams(SearchRequest):
    model_config = ConfigDict(extra="forbid")


class KlineParams(KlineRequest):
    model_config = ConfigDict(extra="forbid")
    freq: Literal["60"] | None = None


class SymbolParams(SymbolRequest):
    model_config = ConfigDict(extra="forbid")


class BatchParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    symbols: str = Field(
        min_length=1, max_length=499, pattern=r"^[0-9]{6}\.(SH|SZ|BJ)(,[0-9]{6}\.(SH|SZ|BJ))*$"
    )


def native_service(request: Request, user: User) -> NativeMarketService:
    service = request.app.state.market_service
    if not isinstance(service, NativeMarketService):
        raise HTTPException(
            503,
            tr(
                "finance.market.errors.unsupported",
                resolve_locale(user_locale=user.locale, explicit=resolve_request_locale(request)),
            ),
        )
    return service


async def localized[T](operation: Awaitable[T], user: User, request: Request | None = None) -> T:
    try:
        return await operation
    except HTTPException as exc:
        if isinstance(exc.detail, str) and exc.detail.startswith("finance.market.errors."):
            raise HTTPException(
                exc.status_code,
                tr(
                    exc.detail,
                    resolve_locale(
                        user_locale=user.locale, explicit=resolve_request_locale(request)
                    ),
                ),
            ) from None
        raise


async def read_market[T](request: Request, operation: Coroutine[None, None, T], user: User) -> T:
    """Release upstream capacity when a browser abandons the current symbol."""

    async def disconnected() -> None:
        while True:
            if (await request.receive())["type"] == "http.disconnect":
                return

    computation = asyncio.create_task(operation)
    connection = asyncio.create_task(disconnected())
    try:
        done, _ = await asyncio.wait((computation, connection), return_when=asyncio.FIRST_COMPLETED)
        if computation not in done:
            raise HTTPException(499, "finance.errors.cancelled")
        return await localized(computation, user, request)
    finally:
        computation.cancel()
        connection.cancel()
        await asyncio.gather(computation, connection, return_exceptions=True)


@router.get("/market/status", response_model=MarketStatus, summary="行情服务配置状态")
async def status(request: Request, user: Account) -> MarketStatus:
    return MarketStatus(configured=request.app.state.market_service.configured)


@router.get("/market/search", response_model=SearchResults, summary="搜索股票、基金和指数")
async def search(
    request: Request, user: Account, params: Annotated[SearchParams, Query()]
) -> SearchResults:
    service: MarketService = request.app.state.market_service
    return await read_market(request, service.search(params.q, params.limit), user)


@router.get(
    "/market/kline",
    response_model=MarketKline | NativeIntradayKline,
    summary="只读日线或60分钟行情",
)
async def kline(
    request: Request, user: Account, params: Annotated[KlineParams, Query()]
) -> MarketKline | NativeIntradayKline:
    if params.freq == "60":
        return await read_market(
            request,
            native_service(request, user).kline60(params.symbol, min(params.limit, 640)),
            user,
        )
    service: MarketService | NativeMarketService = request.app.state.market_service
    return await read_market(
        request, service.kline(params.symbol, params.adjust, params.limit), user
    )


@router.get("/market/quote", response_model=MarketQuote, summary="只读证券快照")
async def quote(
    request: Request, user: Account, params: Annotated[SymbolParams, Query()]
) -> MarketQuote:
    service: MarketService = request.app.state.market_service
    return await read_market(request, service.quote(params.symbol), user)


@router.get("/market/minute", response_model=MinuteResult, summary="读取证券当日分时")
async def minute(
    request: Request, user: Account, params: Annotated[SymbolParams, Query()]
) -> MinuteResult:
    return await read_market(request, native_service(request, user).minute(params.symbol), user)


@router.get("/market/quotes", response_model=QuotesResult, summary="批量读取证券快照")
async def quotes(
    request: Request, user: Account, params: Annotated[BatchParams, Query()]
) -> QuotesResult:
    return await read_market(
        request, native_service(request, user).quotes(params.symbols.split(",")), user
    )


@router.get("/market/indices", response_model=IndicesResult, summary="读取主要指数快照")
async def indices(request: Request, user: Account) -> IndicesResult:
    return await read_market(request, native_service(request, user).indices(), user)


@router.get("/market/sparks", response_model=SparksResult, summary="读取自选证券当日迷你走势")
async def sparks(
    request: Request, user: Account, params: Annotated[BatchParams, Query()]
) -> SparksResult:
    return await read_market(
        request, native_service(request, user).sparks(params.symbols.split(",")), user
    )


@router.get("/watchlist", response_model=Watchlist, summary="读取当前账户的自选和分组")
async def watchlist(
    user: Account, server: Annotated[OctopServer, Depends(get_server)]
) -> Watchlist:
    assert server.services is not None
    manager = WatchlistManager(server.services.repos)
    return await asyncio.get_running_loop().run_in_executor(None, manager.load, user.id)


@router.put(
    "/watchlist",
    response_model=Watchlist,
    summary="保存当前账户的自选和分组",
    description="使用读取时的 revision；发生并发修改返回 409，客户端须重新读取。空列表为有效保存。",
)
async def save_watchlist(
    body: WatchlistUpdate,
    request: Request,
    user: Account,
    server: Annotated[OctopServer, Depends(get_server)],
) -> Watchlist:
    assert server.services is not None
    manager = WatchlistManager(server.services.repos)
    return await localized(
        asyncio.get_running_loop().run_in_executor(None, manager.save, user.id, body), user, request
    )


@router.get("/preferences", response_model=Preferences, summary="读取当前账户的看盘偏好")
async def preferences(
    user: Account, server: Annotated[OctopServer, Depends(get_server)]
) -> Preferences:
    assert server.services is not None
    manager = PreferencesManager(server.services.repos)
    return await asyncio.get_running_loop().run_in_executor(None, manager.load, user.id)


@router.put(
    "/preferences",
    response_model=Preferences,
    summary="保存当前账户的看盘偏好",
    description="使用 GET 返回的 revision；并发变更返回409。最多64KiB偏好数据。",
)
async def save_preferences(
    body: PreferencesUpdate,
    request: Request,
    user: Account,
    server: Annotated[OctopServer, Depends(get_server)],
) -> Preferences:
    assert server.services is not None
    manager = PreferencesManager(server.services.repos)
    return await localized(
        asyncio.get_running_loop().run_in_executor(None, manager.save, user.id, body), user, request
    )
