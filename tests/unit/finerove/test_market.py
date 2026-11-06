import asyncio

import httpx
import pytest
from fastapi import HTTPException

from finerove.finance.market import MarketService


@pytest.fixture(autouse=True)
def configured(monkeypatch):
    monkeypatch.setenv("FINEROVE_MARKET_BASE_URL", "http://127.0.0.1:8001")


@pytest.mark.parametrize(
    "base",
    [
        "",
        "http://evil.test",
        "https://u:p@host",
        "https://host/api",
        "https://host?x=1",
        "https://host#x",
        "https://host:bad",
        "file:///tmp/data",
    ],
)
async def test_unavailable(monkeypatch, base):
    monkeypatch.setenv("FINEROVE_MARKET_BASE_URL", base)
    service = MarketService()
    assert not service.configured
    with pytest.raises(HTTPException) as err:
        await service.quote("600519.SH")
    assert err.value.status_code == 503
    await service.close()


async def test_whitelist_and_fixed_request():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "symbol": "600519.SH",
                "adjust": "qfq",
                "formula": "secret",
                "bars": [
                    {
                        "date": "2026-11-05",
                        "open": 1,
                        "high": 2,
                        "low": 1,
                        "close": 2,
                        "indicators": {"secret": 5},
                    }
                ],
            },
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        headers={"Authorization": "secret"},
        cookies={"session": "secret"},
    ) as client:
        service = MarketService(client)
        result = await service.kline("600519.SH")
        assert "formula" not in result.model_dump()
        assert "indicators" not in result.bars[0].model_dump()
        assert seen[0].url.path == "/api/v1/market/kline"
        assert "with" not in seen[0].url.params
        assert "authorization" not in seen[0].headers
        assert "cookie" not in seen[0].headers


@pytest.mark.parametrize("symbol", ["600519", "sh.600519", "600519.sh", "600519.SH/x", "600519.HK"])
async def test_symbol_validation(symbol):
    service = MarketService()
    with pytest.raises(HTTPException) as err:
        await service.quote(symbol)
    assert err.value.status_code == 422
    await service.close()


@pytest.mark.parametrize("status", [301, 401, 403, 500])
async def test_upstream_failure_sanitized(status):
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(status, text="secret"))
    ) as client:
        with pytest.raises(HTTPException) as err:
            await MarketService(client).quote("600519.SH")
        assert err.value.status_code == 502
        assert "secret" not in err.value.detail


async def test_search_and_quote_filters():
    def handler(request):
        if request.url.path.endswith("search"):
            return httpx.Response(
                200,
                json={
                    "items": [{"symbol": "600519.SH", "name": "茅台", "factor": 3}],
                    "total": 1,
                    "formula": "secret",
                },
            )
        return httpx.Response(
            200,
            json={
                "symbol": "600519.SH",
                "close": 12,
                "indicators": {"secret": 3},
                "valuation": {"date": "2026-11-05", "pe_ttm": 20, "formula": "secret"},
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = MarketService(client)
        result = await service.search("茅台")
        assert result.total == 1
        assert "factor" not in result.items[0].model_dump()
        quote = await service.quote("600519.SH")
        assert quote.close == 12
        assert "formula" not in quote.valuation.model_dump()
        for q, limit in [("x" * 81, 20), ("", 20), ("x", 51)]:
            with pytest.raises(HTTPException) as err:
                await service.search(q, limit)
            assert err.value.status_code == 422
        with pytest.raises(HTTPException):
            await service.kline("600519.SH", limit=1001)


class LargeStream(httpx.AsyncByteStream):
    async def __aiter__(self):
        for _ in range(40):
            yield b"x" * 65536


async def test_bounded_stream():
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, stream=LargeStream()))
    ) as client:
        with pytest.raises(HTTPException) as err:
            await MarketService(client).quote("600519.SH")
        assert err.value.status_code == 502


async def test_capacity_released_on_cancellation():
    entered = 0
    ready = asyncio.Event()
    release = asyncio.Event()

    async def handler(request):
        nonlocal entered
        entered += 1
        if entered == 8:
            ready.set()
        await release.wait()
        return httpx.Response(200, json={"symbol": "600519.SH"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = MarketService(client)
        tasks = [asyncio.create_task(service.quote("600519.SH")) for _ in range(8)]
        await asyncio.wait_for(ready.wait(), 2)
        with pytest.raises(HTTPException) as err:
            await service.quote("600519.SH")
        assert err.value.status_code == 429
        tasks[0].cancel()
        with pytest.raises(asyncio.CancelledError):
            await tasks[0]
        release.set()
        await asyncio.gather(*tasks[1:])
        assert (await service.quote("600519.SH")).symbol == "600519.SH"


async def test_actual_upstream_bare_symbols():
    def handler(request):
        if request.url.path.endswith("search"):
            return httpx.Response(
                200,
                json={
                    "items": [
                        {"symbol": "600519", "market": "SH"},
                        {"symbol": "000001", "market": "SZ"},
                    ],
                    "total": 2,
                },
            )
        return httpx.Response(200, json={"symbol": "600519", "adjust": "qfq", "bars": []})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = MarketService(client)
        assert [h.symbol for h in (await service.search("x")).items] == ["600519.SH", "000001.SZ"]
        assert (await service.kline("600519.SH")).symbol == "600519.SH"
        assert (await service.quote("600519.SH")).symbol == "600519.SH"


async def test_deadline_and_bad_json(monkeypatch):
    import finerove.finance.market as market

    monkeypatch.setattr(market, "REQUEST_DEADLINE", 0.01)

    async def slow(request):
        await asyncio.Event().wait()

    async with httpx.AsyncClient(transport=httpx.MockTransport(slow)) as client:
        service = MarketService(client)
        with pytest.raises(HTTPException) as err:
            await service.quote("600519.SH")
        assert err.value.status_code == 502
        assert service._active == 0
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, text="not json"))
    ) as client:
        with pytest.raises(HTTPException) as err:
            await MarketService(client).quote("600519.SH")
        assert err.value.status_code == 502


async def test_excess_bars_rejected():
    bar = {"date": "2026-11-05", "open": 1, "high": 1, "low": 1, "close": 1}
    payload = {"symbol": "600519.SH", "adjust": "qfq", "bars": [bar] * 1001}
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json=payload))
    ) as client:
        with pytest.raises(HTTPException) as err:
            await MarketService(client).kline("600519.SH")
        assert err.value.status_code == 502


@pytest.mark.parametrize("limit", [500, 1000])
async def test_live_bar_extra_trims_oldest(limit):
    from datetime import date, timedelta

    bars = [
        {
            "date": str(date(2020, 1, 1) + timedelta(days=i)),
            "open": 1,
            "high": 1,
            "low": 1,
            "close": 1,
        }
        for i in range(limit + 1)
    ]
    bars[-1]["live"] = True
    payload = {"symbol": "600519.SH", "adjust": "qfq", "bars": bars}
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json=payload))
    ) as client:
        result = await MarketService(client).kline("600519.SH", limit=limit)
        assert len(result.bars) == limit
        assert result.bars[0].date == bars[1]["date"]
        assert result.bars[-1].live is True


@pytest.mark.parametrize(
    "dates",
    [["2026-02-30"], ["2026-1-01"], ["2026-01-02", "2026-01-01"], ["2026-01-01", "2026-01-01"]],
)
async def test_invalid_kline_dates(dates):
    payload = {
        "symbol": "600519.SH",
        "adjust": "qfq",
        "bars": [{"date": day, "open": 1, "high": 1, "low": 1, "close": 1} for day in dates],
    }
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json=payload))
    ) as client:
        with pytest.raises(HTTPException) as err:
            await MarketService(client).kline("600519.SH")
        assert err.value.status_code == 502


@pytest.mark.parametrize("count,live", [(501, False), (502, True)])
async def test_excess_bars_without_single_live_extension(count, live):
    from datetime import date, timedelta

    bars = [
        {
            "date": str(date(2020, 1, 1) + timedelta(days=i)),
            "open": 1,
            "high": 1,
            "low": 1,
            "close": 1,
        }
        for i in range(count)
    ]
    bars[-1]["live"] = live
    payload = {"symbol": "600519.SH", "adjust": "qfq", "bars": bars}
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json=payload))
    ) as client:
        with pytest.raises(HTTPException) as err:
            await MarketService(client).kline("600519.SH", limit=500)
        assert err.value.status_code == 502
