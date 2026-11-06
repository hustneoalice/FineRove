import pytest
from pydantic import ValidationError

from finerove.finance.contracts import EvaluationRequest
from finerove.finance.service import NeoService


def test_closed_date_and_canonical_identity():
    with pytest.raises(ValidationError):
        EvaluationRequest(
            capability="neo.trend_histogram", instrument_id="600519", end="2020-01-01", bars=[]
        )
    with pytest.raises(ValidationError):
        EvaluationRequest(
            capability="neo.trend_histogram", instrument_id="CN:SH:stock:600519", end="2099-01-01"
        )


def test_missing_configuration_is_closed(monkeypatch):
    for key in ("BASE_URL", "SIGNING_KEY", "ISSUER"):
        monkeypatch.delenv("FINEROVE_NEO_" + key, raising=False)
    assert NeoService().configured is False


@pytest.mark.asyncio
async def test_singleflight_is_per_user_and_survives_waiter_cancel(monkeypatch):
    import asyncio

    import httpx
    import jwt
    from fastapi import HTTPException

    for key, value in {
        "BASE_URL": "http://127.0.0.1:9000",
        "SIGNING_KEY": "x" * 32,
        "ISSUER": "instance",
    }.items():
        monkeypatch.setenv("FINEROVE_NEO_" + key, value)
    entered = asyncio.Event()
    release = asyncio.Event()
    subjects = []

    async def upstream(request):
        claims = jwt.decode(
            request.headers["Authorization"][7:],
            "x" * 32,
            algorithms=["HS256"],
            audience="neo-compute",
        )
        subjects.append(claims["sub"])
        entered.set()
        await release.wait()
        return httpx.Response(403, json={"secret": "must not leak"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(upstream))
    service = NeoService(client)
    body = EvaluationRequest(
        capability="neo.trend_histogram",
        instrument_id="CN:SH:stock:600519",
        end="2020-01-01",
        bars=[],
    )
    one = asyncio.create_task(service.evaluate(1, body))
    await entered.wait()
    two = asyncio.create_task(service.evaluate(1, body))
    three = asyncio.create_task(service.evaluate(2, body))
    await asyncio.sleep(0.01)
    assert sorted(subjects) == ["1", "2"]
    assert service.catalog()["configured"]
    one.cancel()
    with pytest.raises(asyncio.CancelledError):
        await one
    release.set()
    results = await asyncio.gather(two, three, return_exceptions=True)
    assert all(isinstance(r, HTTPException) and r.status_code == 403 for r in results)
    assert not service.inflight
    await service.close()


@pytest.mark.asyncio
async def test_redirect_malformed_and_transport_errors_do_not_leak(monkeypatch):
    import httpx
    from fastapi import HTTPException

    for key, value in {
        "BASE_URL": "https://private.invalid",
        "SIGNING_KEY": "x" * 32,
        "ISSUER": "instance",
    }.items():
        monkeypatch.setenv("FINEROVE_NEO_" + key, value)
    body = EvaluationRequest(
        capability="neo.trend_histogram",
        instrument_id="CN:SH:stock:600519",
        end="2020-01-01",
        bars=[],
    )
    for status in [302, 200]:

        async def upstream(request, response_status=status):
            return httpx.Response(
                response_status,
                json={"secret": "private.invalid"},
                headers={"Location": "https://other.invalid"},
            )

        service = NeoService(httpx.AsyncClient(transport=httpx.MockTransport(upstream)))
        with pytest.raises(HTTPException) as err:
            await service.evaluate(1, body)
        assert err.value.status_code == 502
        assert "private.invalid" not in str(err.value.detail)
        await service.close()


@pytest.mark.asyncio
async def test_upstream_401_preserves_local_login(monkeypatch):
    import httpx
    from fastapi import HTTPException

    monkeypatch.setenv("FINEROVE_NEO_BASE_URL", "https://private.invalid")
    monkeypatch.setenv("FINEROVE_NEO_SIGNING_KEY", "x" * 32)
    monkeypatch.setenv("FINEROVE_NEO_ISSUER", "instance")
    service = NeoService(
        httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(401)))
    )
    body = EvaluationRequest(
        capability="neo.trend_histogram",
        instrument_id="CN:SH:stock:600519",
        end="2020-01-01",
        bars=[],
    )
    with pytest.raises(HTTPException) as err:
        await service.evaluate(1, body)
    assert err.value.status_code == 502
    await service.close()


@pytest.mark.asyncio
async def test_total_deadline_releases_capacity(monkeypatch):
    import asyncio

    import httpx
    from fastapi import HTTPException

    import finerove.finance.service as module

    monkeypatch.setenv("FINEROVE_NEO_BASE_URL", "https://private.invalid")
    monkeypatch.setenv("FINEROVE_NEO_SIGNING_KEY", "x" * 32)
    monkeypatch.setenv("FINEROVE_NEO_ISSUER", "instance")
    monkeypatch.setattr(module, "REQUEST_DEADLINE", 0.02, raising=False)

    async def upstream(request):
        await asyncio.sleep(10)
        return httpx.Response(200)

    service = NeoService(httpx.AsyncClient(transport=httpx.MockTransport(upstream)))
    body = EvaluationRequest(
        capability="neo.trend_histogram",
        instrument_id="CN:SH:stock:600519",
        end="2020-01-01",
        bars=[],
    )
    with pytest.raises(HTTPException) as err:
        await asyncio.wait_for(service.evaluate(1, body), 0.5)
    assert err.value.status_code == 502
    assert not service.inflight
    await service.close()


@pytest.mark.parametrize("end", [0, "2020-01-01T00:00:00", "2020-1-1"])
def test_end_is_strict_calendar_date(end):
    with pytest.raises(ValidationError):
        EvaluationRequest(
            capability="neo.trend_histogram", instrument_id="CN:SH:stock:600519", end=end
        )


@pytest.mark.asyncio
async def test_capacity_is_bounded_and_last_waiter_cancels(monkeypatch):
    import asyncio

    import httpx
    from fastapi import HTTPException

    monkeypatch.setenv("FINEROVE_NEO_BASE_URL", "https://private.invalid")
    monkeypatch.setenv("FINEROVE_NEO_SIGNING_KEY", "x" * 32)
    monkeypatch.setenv("FINEROVE_NEO_ISSUER", "instance")

    async def upstream(request):
        await asyncio.Event().wait()

    service = NeoService(httpx.AsyncClient(transport=httpx.MockTransport(upstream)))
    body = EvaluationRequest(
        capability="neo.trend_histogram",
        instrument_id="CN:SH:stock:600519",
        end="2020-01-01",
        bars=[],
    )
    tasks = [asyncio.create_task(service.evaluate(i, body)) for i in range(8)]
    await asyncio.sleep(0)
    with pytest.raises(HTTPException) as err:
        await service.evaluate(9, body)
    assert err.value.status_code == 429
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    assert not service.inflight
    await service.close()


def test_local_auth_dependency_and_lifecycle():
    from fastapi import FastAPI, HTTPException
    from fastapi.testclient import TestClient

    from finerove.finance.router import install_finance
    from octop.api.deps import current_user

    app = FastAPI()
    install_finance(app)

    async def denied():
        raise HTTPException(401, "login required")

    app.dependency_overrides[current_user] = denied
    with TestClient(app) as client:
        assert client.get("/api/finance/neo/catalog").status_code == 401
        assert client.post("/api/finance/neo/evaluate", json={}).status_code == 401


def test_http_catalog_and_service_errors_follow_user_locale(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from finerove.finance.router import install_finance
    from octop.api.deps import current_user
    from octop.infra.users.identity import User

    monkeypatch.delenv("FINEROVE_NEO_BASE_URL", raising=False)
    app = FastAPI()
    install_finance(app)

    async def english_user():
        return User(id=1, username="test", role="user", display_name=None, locale="en")

    app.dependency_overrides[current_user] = english_user
    with TestClient(app) as client:
        catalog = client.get("/api/finance/neo/catalog").json()
        assert catalog["items"][3]["name"] == "NEO trend histogram"
        response = client.post(
            "/api/finance/neo/evaluate",
            json={
                "capability": "neo.trend_histogram",
                "instrument_id": "CN:SH:stock:600519",
                "end": "2020-01-01",
            },
        )
        assert response.status_code == 503
        assert response.json()["detail"] == "NEO service is not configured"


@pytest.mark.asyncio
async def test_http_disconnect_releases_last_computation_waiter(monkeypatch):
    import asyncio
    from types import SimpleNamespace

    import httpx
    from fastapi import HTTPException, Request

    from finerove.finance.router import evaluate
    from octop.infra.users.identity import User

    for name, value in {
        "BASE_URL": "https://private.invalid",
        "SIGNING_KEY": "x" * 32,
        "ISSUER": "instance",
    }.items():
        monkeypatch.setenv("FINEROVE_NEO_" + name, value)
    entered = asyncio.Event()
    cancelled = asyncio.Event()

    async def upstream(request):
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    service = NeoService(httpx.AsyncClient(transport=httpx.MockTransport(upstream)))
    messages = asyncio.Queue()
    request = Request(
        {"type": "http", "app": SimpleNamespace(state=SimpleNamespace(neo_service=service))},
        receive=messages.get,
    )
    body = EvaluationRequest(
        capability="neo.trend_histogram",
        instrument_id="CN:SH:stock:600519",
        end="2020-01-01",
        bars=[],
    )
    task = asyncio.create_task(evaluate(body, request, User(1, "test", "user", None)))
    await entered.wait()
    await messages.put({"type": "http.disconnect"})
    try:
        with pytest.raises(HTTPException) as err:
            await asyncio.wait_for(task, 0.3)
        assert err.value.status_code == 499
        assert not service.inflight
        await asyncio.wait_for(cancelled.wait(), 0.3)
    finally:
        await service.close()
