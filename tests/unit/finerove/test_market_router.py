"""Authenticated business endpoints never accept an alternate account identity."""

from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from finerove.finance.router import install_finance
from octop.api.deps import current_user, get_server
from octop.infra.db.migrate import run_migrations
from octop.infra.db.pool import SqlitePool
from octop.infra.db.services import RepoBundle
from octop.infra.users.identity import User


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setenv("FINEROVE_MARKET_BASE_URL", "http://unconfigured.invalid")
    pool = SqlitePool(tmp_path / "control.db")
    run_migrations(pool)
    app = FastAPI()
    install_finance(app)
    who = [1]
    app.dependency_overrides[current_user] = lambda: User(who[0], "test", "user", None, "en")
    app.dependency_overrides[get_server] = lambda: SimpleNamespace(
        services=SimpleNamespace(repos=RepoBundle.from_pool(pool))
    )
    with TestClient(app) as client:
        yield client, who, app


def test_missing_service_and_localized_error(api):
    client, _, _ = api
    assert client.get("/api/finance/market/status").json() == {"configured": False}
    response = client.get("/api/finance/market/kline", params={"symbol": "600519.SH"})
    assert response.status_code == 503
    assert response.json()["detail"] == "Market data service is not configured"


def test_watchlist_actual_user_and_conflicts(api):
    client, who, _ = api
    original = client.get("/api/finance/watchlist").json()
    saved = client.put("/api/finance/watchlist", json=original)
    assert saved.status_code == 200
    assert client.put("/api/finance/watchlist", json=original).status_code == 409
    who[0] = 2
    assert client.get("/api/finance/watchlist").json()["revision"] == "0"
    assert client.put("/api/finance/watchlist", json=original | {"user_id": 1}).status_code == 422


def test_auth_and_no_arbitrary_forwarding(api):
    client, _, app = api
    assert (
        client.get("/api/finance/market/kline", params={"symbol": "../data/init"}).status_code
        == 422
    )
    assert (
        client.get(
            "/api/finance/market/kline", params={"symbol": "600519.SH", "with": "vip"}
        ).status_code
        == 422
    )
    assert client.post("/api/finance/market/data/update").status_code in (404, 405)

    async def denied():
        raise HTTPException(401)

    app.dependency_overrides[current_user] = denied
    for path in ("market/status", "market/search?q=test", "watchlist"):
        assert client.get("/api/finance/" + path).status_code == 401


def test_openapi_typed_business_responses(api):
    client, _, _ = api
    schema = client.get("/openapi.json").json()
    for path in ("/api/finance/market/kline", "/api/finance/watchlist"):
        operation = schema["paths"][path]["get"]
        assert operation["summary"]
        response_schema = operation["responses"]["200"]["content"]["application/json"]["schema"]
        assert "$ref" in response_schema or all("$ref" in item for item in response_schema["anyOf"])


def test_default_market_is_integrated_without_yuchao_daemon(monkeypatch):
    monkeypatch.delenv("FINEROVE_MARKET_BASE_URL", raising=False)
    app = FastAPI()
    install_finance(app)
    app.dependency_overrides[current_user] = lambda: User(1, "test", "user", None, "zh")
    with TestClient(app) as client:
        assert client.get("/api/finance/market/status").json() == {"configured": True}
        assert type(app.state.market_service).__name__ == "NativeMarketService"


@pytest.mark.asyncio
async def test_disconnected_browser_cancels_upstream_work():
    import asyncio

    from finerove.finance.market_router import read_market

    cancelled = asyncio.Event()
    entered = asyncio.Event()

    async def upstream():
        try:
            entered.set()
            await asyncio.sleep(30)
        finally:
            cancelled.set()

    async def receive():
        await entered.wait()
        return {"type": "http.disconnect"}

    with pytest.raises(HTTPException) as error:
        await asyncio.wait_for(
            read_market(
                SimpleNamespace(receive=receive), upstream(), User(1, "test", "user", None)
            ),
            1,
        )
    assert error.value.status_code == 499
    assert cancelled.is_set()
