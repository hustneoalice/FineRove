import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI, HTTPException, Request
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from finerove.finance.service import NeoService
from octop.api.deps import current_user
from octop.infra.users.identity import User

BODY = {
    "capability": "neo.trend_histogram",
    "instrument_id": "CN:SH:stock:600519",
    "end": "2020-01-01",
    "bars": [],
}
USER = User(37, "test", "admin", None, locale="en")


def setup(service=None, denied=False):
    from finerove.finance import mcp as finance_mcp

    app = FastAPI()
    app.include_router(finance_mcp.router)
    app.state.neo_service = service or NeoService()

    async def identity():
        if denied:
            raise HTTPException(401, "login required")
        return USER

    app.dependency_overrides[current_user] = identity
    return app


async def rpc(client, method, params=None, **extra):
    return await client.post(
        "/api/mcp/finance",
        json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}, **extra},
    )


@pytest.mark.asyncio
async def test_auth_and_methods():
    app = setup(denied=True)
    async with httpx.AsyncClient(
        headers={"Authorization": "Bearer local"},
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as c:
        for method in ["GET", "DELETE", "POST"]:
            assert (await c.request(method, "/api/mcp/finance")).status_code == 401
    app = setup()
    async with httpx.AsyncClient(
        headers={"Authorization": "Bearer local"},
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as c:
        assert (await c.get("/api/mcp/finance")).status_code == 405
        assert (await c.delete("/api/mcp/finance")).status_code == 405


@pytest.mark.asyncio
async def test_sdk_interoperability_and_trusted_identity():
    calls = []

    class Service:
        catalog = NeoService.catalog
        configured = False

        async def evaluate(self, uid, body):
            calls.append((uid, body))
            raise HTTPException(503, "finance.errors.unconfigured")

    app = setup(Service())
    async with (
        httpx.AsyncClient(
            headers={"Authorization": "Bearer local"}, transport=httpx.ASGITransport(app=app)
        ) as http,
        streamable_http_client("http://test/api/mcp/finance", http_client=http) as (
            read,
            write,
            session_id,
        ),
        ClientSession(read, write) as session,
    ):
        initialized = await session.initialize()
        assert initialized.serverInfo.name == "FinRove NEO"
        tools = await session.list_tools()
        assert {t.name for t in tools.tools} == {
            "list_neo_capabilities",
            "evaluate_neo_indicator",
        }
        assert all(t.outputSchema for t in tools.tools)
        catalog = await session.call_tool("list_neo_capabilities", {})
        assert catalog.structuredContent["items"][3]["name"] == "NEO trend histogram"
        result = await session.call_tool("evaluate_neo_indicator", BODY)
        assert result.isError and "not configured" in result.content[0].text
        assert calls[0][0] == 37
        assert session_id() is None
        assert not (await session.call_tool("list_neo_capabilities", {})).isError


@pytest.mark.asyncio
@pytest.mark.parametrize("extra", ["user_id", "token", "base_url"])
async def test_forged_fields_rejected(extra):
    app = setup()
    async with httpx.AsyncClient(
        headers={"Authorization": "Bearer local"},
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as c:
        response = await rpc(
            c,
            "tools/call",
            {"name": "evaluate_neo_indicator", "arguments": {**BODY, extra: "private"}},
        )
        assert response.json()["result"]["isError"]
        assert "private" not in response.text


@pytest.mark.asyncio
async def test_invalid_protocol_and_size():
    app = setup()
    async with httpx.AsyncClient(
        headers={"Authorization": "Bearer local"},
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as c:
        for raw in [
            "{",
            "[]",
            "null",
            '{"jsonrpc":"1.0","id":1,"method":"ping"}',
            '{"jsonrpc":"2.0","id":1,"method":"ping","params":[]}',
        ]:
            r = await c.post("/api/mcp/finance", content=raw)
            assert "error" in r.json()
        assert (await rpc(c, "absent")).json()["error"]["code"] == -32601
        assert (await rpc(c, "ping")).json()["result"] == {}
        r = await c.post(
            "/api/mcp/finance", json={"jsonrpc": "2.0", "method": "notifications/initialized"}
        )
        assert r.status_code == 202

        async def chunks():
            yield b" " * 40000
            yield b" " * 40000

        r = await c.post("/api/mcp/finance", content=chunks(), headers={"content-length": "1"})
        assert r.status_code == 413
        r = await rpc(
            c,
            "initialize",
            {
                "protocolVersion": "unsupported",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "1"},
            },
        )
        from mcp.shared.version import SUPPORTED_PROTOCOL_VERSIONS

        assert r.json()["result"]["protocolVersion"] in SUPPORTED_PROTOCOL_VERSIONS


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error",
    [
        HTTPException(403, "finance.errors.denied"),
        RuntimeError("https://private.invalid token"),
        HTTPException(502, {"private": "secret"}),
    ],
)
async def test_errors_are_safe_tool_results(error):
    class Service:
        async def evaluate(self, uid, body):
            raise error

    app = setup(Service())
    async with httpx.AsyncClient(
        headers={"Authorization": "Bearer local"},
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as c:
        r = await rpc(c, "tools/call", {"name": "evaluate_neo_indicator", "arguments": BODY})
        assert r.status_code == 200 and r.json()["result"]["isError"]
        assert "private.invalid" not in r.text and "token" not in r.text


@pytest.mark.asyncio
async def test_disconnect_cleans_service_capacity(monkeypatch):
    from finerove.finance import mcp as finance_mcp

    for key, value in {
        "BASE_URL": "https://private.invalid",
        "SIGNING_KEY": "x" * 32,
        "ISSUER": "test",
    }.items():
        monkeypatch.setenv("FINEROVE_NEO_" + key, value)
    entered = asyncio.Event()
    cancelled = asyncio.Event()

    async def upstream(request):
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    service = NeoService(httpx.AsyncClient(transport=httpx.MockTransport(upstream)))
    queue = asyncio.Queue()
    await queue.put(
        {
            "type": "http.request",
            "body": json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {"name": "evaluate_neo_indicator", "arguments": BODY},
                }
            ).encode(),
            "more_body": False,
        }
    )
    request = Request(
        {"type": "http", "app": SimpleNamespace(state=SimpleNamespace(neo_service=service))},
        receive=queue.get,
    )
    task = asyncio.create_task(finance_mcp.endpoint(request, USER))
    await asyncio.wait_for(entered.wait(), 1)
    await queue.put({"type": "http.disconnect"})
    await asyncio.wait_for(task, 1)
    await asyncio.wait_for(cancelled.wait(), 1)
    assert not service.inflight
    await service.close()


@pytest.mark.asyncio
async def test_success_result_is_typed_and_json_text():
    from finerove.finance.contracts import EvaluationResult

    payload = {
        "schema_version": 2,
        "status": "empty",
        **BODY,
        "period": "day",
        "adjust": "qfq",
        "as_of": None,
        "generated_at": "2020-01-02T00:00:00Z",
        "bar_state": "closed",
        "rule_version": "v1",
        "origin": "formula_migration",
        "verification_status": "not_pointwise_validated",
        "snapshot_id": "snapshot",
        "input_snapshot_id": "a" * 64,
        "points": [],
        "latest": None,
        "warnings": [],
        "coverage": {"bars": 0, "warmup_limit": 2000},
    }
    payload.pop("end")

    class Service:
        async def evaluate(self, uid, body):
            assert uid == 37
            return EvaluationResult.model_validate(payload)

    app = setup(Service())
    async with httpx.AsyncClient(
        headers={"Authorization": "Bearer local"},
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as c:
        r = await rpc(c, "tools/call", {"name": "evaluate_neo_indicator", "arguments": BODY})
        result = r.json()["result"]
        assert result["isError"] is False
        assert json.loads(result["content"][0]["text"]) == result["structuredContent"]
        EvaluationResult.model_validate(result["structuredContent"])


@pytest.mark.asyncio
async def test_deep_json_and_slow_body_are_bounded(monkeypatch):
    from finerove.finance import mcp as finance_mcp

    app = setup()
    async with httpx.AsyncClient(
        headers={"Authorization": "Bearer local"},
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as c:
        r = await c.post("/api/mcp/finance", content="[" * 20000 + "0" + "]" * 20000)
        assert r.json()["error"]["code"] == -32700
        monkeypatch.setattr(finance_mcp, "BODY_DEADLINE", 0.01)

        async def slow():
            yield b"{"
            await asyncio.sleep(1)

        r = await c.post("/api/mcp/finance", content=slow())
        assert r.status_code == 408
        r = await rpc(c, "tools/list")
        assert all(t["annotations"]["readOnlyHint"] for t in r.json()["result"]["tools"])


@pytest.mark.asyncio
async def test_transport_guards_precede_user_and_service():
    app = setup()
    async with httpx.AsyncClient(
        headers={"Authorization": "Bearer local"},
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as c:
        c.headers.pop("authorization")
        assert (await rpc(c, "ping")).status_code == 401
        for headers in [
            {"Authorization": "Basic abc"},
            {"Authorization": "Bearer "},
            {"Authorization": "Bearer local", "Origin": "null"},
            {"Authorization": "Bearer local", "Origin": "https://evil.invalid"},
        ]:
            r = await c.post(
                "/api/mcp/finance",
                headers=headers,
                json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
            )
            assert r.status_code in (401, 403)
        r = await c.post(
            "/api/mcp/finance?access_token=secret", headers={"Authorization": "Bearer local"}
        )
        assert r.status_code == 401
        r = await c.post(
            "/api/mcp/finance",
            headers={"Authorization": "Bearer local", "MCP-Protocol-Version": "unsupported"},
        )
        assert r.status_code == 400


def test_access_logs_redact_only_finance_queries_and_install_once():
    import logging

    from finerove.finance import mcp as finance_mcp

    logger = logging.getLogger("uvicorn.access")
    previous = list(logger.filters)
    try:
        finance_mcp.install_mcp(FastAPI())
        finance_mcp.install_mcp(FastAPI())
        filters = [f for f in logger.filters if isinstance(f, finance_mcp.FinanceAccessFilter)]
        assert len(filters) == 1
        for path in [
            "/api/mcp/finance?access_token=secret",
            "/api/mcp/finance/?access_token=secret",
        ]:
            record = logging.LogRecord(
                "uvicorn.access",
                20,
                "",
                0,
                '%s - "%s %s HTTP/%s" %d',
                ("client", "POST", path, "1.1", 401),
                None,
            )
            assert filters[0].filter(record)
            assert "secret" not in record.getMessage()
        path = "/other?keep=yes"
        record = logging.LogRecord(
            "uvicorn.access",
            20,
            "",
            0,
            '%s - "%s %s HTTP/%s" %d',
            ("client", "GET", path, "1.1", 200),
            None,
        )
        filters[0].filter(record)
        assert path in record.getMessage()
    finally:
        logger.filters[:] = previous


def test_finance_lifecycle_installs_mcp_and_closes_client(monkeypatch):
    from fastapi.testclient import TestClient

    from finerove.finance.router import install_finance

    monkeypatch.delenv("FINEROVE_NEO_BASE_URL", raising=False)
    app = FastAPI()
    install_finance(app)

    async def identity():
        return USER

    app.dependency_overrides[current_user] = identity
    with TestClient(app) as client:
        service = app.state.neo_service
        assert not service.client.is_closed
        assert client.post("/api/mcp/finance", json={}).status_code == 401
        response = client.post(
            "/api/mcp/finance",
            headers={"Authorization": "Bearer local"},
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        )
        assert response.status_code == 200
        assert len(response.json()["result"]["tools"]) == 2
    assert service.client.is_closed
