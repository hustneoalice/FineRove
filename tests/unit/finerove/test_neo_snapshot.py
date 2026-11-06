import pytest
from pydantic import ValidationError

from finerove.finance.contracts import EvaluationRequest

BASE = {
    "capability": "neo.trend_histogram",
    "instrument_id": "CN:SH:stock:600519",
    "end": "2020-01-03",
}
BAR = {"date": "2020-01-02", "open": 10, "high": 12, "low": 9, "close": 11}


@pytest.mark.parametrize(
    "bars",
    [
        [BAR, BAR],
        [BAR, BAR | {"date": "2020-01-01"}],
        [BAR | {"date": "2020-01-04"}],
        [BAR | {"close": float("nan")}],
        [BAR | {"low": 11}],
        [BAR | {"volume": -1}],
    ],
)
def test_invalid_chart_snapshots_are_rejected(bars):
    with pytest.raises(ValidationError):
        EvaluationRequest(**BASE, bars=bars)


def test_snapshot_is_stable_and_binds_prices_dates_and_adjustment():
    request = EvaluationRequest(**BASE, bars=[BAR])
    assert len(request.input_snapshot_id()) == 64
    assert (
        request.input_snapshot_id()
        == EvaluationRequest.model_validate_json(request.model_dump_json()).input_snapshot_id()
    )
    for change in ({"bars": [BAR | {"close": 10}]}, {"adjust": "raw"}):
        assert (
            EvaluationRequest(**(BASE | {"bars": [BAR]} | change)).input_snapshot_id()
            != request.input_snapshot_id()
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("corrupt", ["input_snapshot_id", "date", "as_of", "coverage", None])
async def test_service_binds_results_to_exact_chart_input(monkeypatch, corrupt):
    import json

    import httpx
    import jwt
    from fastapi import HTTPException

    from finerove.finance.service import NeoService

    monkeypatch.setenv("FINEROVE_NEO_BASE_URL", "http://127.0.0.1:8031")
    monkeypatch.setenv("FINEROVE_NEO_SIGNING_KEY", "k" * 32)
    monkeypatch.setenv("FINEROVE_NEO_ISSUER", "chart-test")
    body = EvaluationRequest(**BASE, bars=[BAR])

    async def upstream(request):
        sent = json.loads(request.content)
        claims = jwt.decode(
            request.headers["Authorization"][7:],
            "k" * 32,
            algorithms=["HS256"],
            audience="neo-compute",
        )
        assert claims["input_snapshot_id"] == sent["input_snapshot_id"] == body.input_snapshot_id()
        assert sent["bars"][0]["close"] == BAR["close"]
        result = {
            "schema_version": 2,
            "status": "ok",
            "capability": body.capability,
            "instrument_id": body.instrument_id,
            "period": "day",
            "adjust": "qfq",
            "as_of": BAR["date"],
            "generated_at": "2020-01-04T00:00:00Z",
            "bar_state": "closed",
            "rule_version": "test",
            "origin": "formula_migration",
            "verification_status": "not_pointwise_validated",
            "snapshot_id": "result",
            "input_snapshot_id": sent["input_snapshot_id"],
            "points": [{"date": BAR["date"], "value": 1.5}],
            "latest": None,
            "warnings": [],
            "coverage": {"bars": 1, "warmup_limit": 2000},
        }
        if corrupt == "input_snapshot_id":
            result[corrupt] = "0" * 64
        if corrupt == "date":
            result["points"][0]["date"] = "2020-01-01"
        if corrupt == "as_of":
            result[corrupt] = "2020-01-01"
        if corrupt == "coverage":
            result[corrupt]["bars"] = 2
        return httpx.Response(200, json=result)

    service = NeoService(httpx.AsyncClient(transport=httpx.MockTransport(upstream)))
    try:
        if corrupt:
            with pytest.raises(HTTPException) as error:
                await service.evaluate(1, body)
            assert error.value.status_code == 502
        else:
            assert (await service.evaluate(1, body)).points[0].value == 1.5
    finally:
        await service.close()
