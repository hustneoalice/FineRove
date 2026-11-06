import json

import httpx
import pytest
from fastapi import HTTPException

from finerove.finance.native_market import NativeMarketService


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["kline", "minute"])
async def test_malformed_quote_metadata_is_sanitized(method):
    payload = {
        "data": {
            "sh600519": {
                "qt": [],
                "qfqday": [["2026-11-05", 10, 10, 10, 10, 1]],
                "data": {"date": "20261105", "data": []},
            }
        }
    }
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
    ) as client:
        with pytest.raises(HTTPException) as error:
            await getattr(NativeMarketService(client), method)("600519.SH")
        assert error.value.status_code == 502


@pytest.mark.asyncio
async def test_kline_native_cache_units_and_adjustment():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(
            200,
            json={"data": {"sh600519": {"qfqday": [["2026-11-05", "10", "11", "12", "9", "20"]]}}},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = NativeMarketService(client)
        result = await service.kline("600519.SH")
        assert result.bars[0].volume == 2000
        assert result.adjust == "qfq"
        assert await service.kline("600519.SH") == result
        assert len(requests) == 1
        assert requests[0].url.scheme == "https"
        assert "8031" not in str(requests[0].url)


@pytest.mark.asyncio
async def test_search_and_minute():
    def handler(request):
        if "smartbox" in request.url.host:
            return httpx.Response(
                200,
                content="v_hint='sh~000001~上证指数~sz~ZS^sz~000001~平安银行~payh~GP';".encode(
                    "gbk"
                ),
            )
        return httpx.Response(
            200,
            json={
                "data": {
                    "sz000001": {
                        "qt": {"sz000001": ["", "", "", "", "10"]},
                        "data": {
                            "date": "20261105",
                            "data": ["0930 10 10 10000", "0931 11 20 21000"],
                        },
                    }
                }
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = NativeMarketService(client)
        found = await service.search("000001")
        assert found.items[0].symbol == "000001.SH"
        assert found.items[0].kind == "index"
        minute = await service.minute("000001.SZ")
        assert minute.bars[1].volume == 1000
        assert minute.bars[1].amount == 11000
        assert minute.bars[1].avg == 10.5


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {"data": {}},
        {"data": {"sh600519": {"day": [["2026-02-30", 1, 1, 1, 1, 1]]}}},
        {
            "data": {
                "sh600519": {
                    "qfqday": [["2026-11-05", 1, 1, 1, 1, 1], ["2026-11-04", 1, 1, 1, 1, 1]]
                }
            }
        },
    ],
)
async def test_reject_bad_or_wrong_adjustment(payload):
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, content=json.dumps(payload))
        )
    ) as client:
        with pytest.raises(HTTPException) as error:
            await NativeMarketService(client).kline("600519.SH")
        assert error.value.status_code == 502


@pytest.mark.asyncio
async def test_invalid_symbol_and_busy():
    service = NativeMarketService()
    try:
        with pytest.raises(HTTPException) as error:
            await service.quote("localhost")
        assert error.value.status_code == 422
        service._active = 8
        with pytest.raises(HTTPException) as error:
            await service.quote("600519.SH")
        assert error.value.status_code == 429
    finally:
        await service.close()


@pytest.mark.asyncio
async def test_quote_gbk_units_and_no_client_credentials():
    fields = [""] * 47
    for index, value in {
        1: "贵州茅台",
        2: "600519",
        3: "1500",
        4: "1490",
        5: "1495",
        30: "20261106113000",
        32: "0.67",
        33: "1510",
        34: "1490",
        36: "200",
        37: "3000",
        39: "20",
        46: "8",
    }.items():
        fields[index] = value

    def handler(request):
        assert "authorization" not in request.headers
        assert "cookie" not in request.headers
        return httpx.Response(200, content=('v_sh600519="' + "~".join(fields) + '";').encode("gbk"))

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        auth=("user", "password"),
        cookies={"session": "secret"},
    ) as client:
        quote = await NativeMarketService(client).quote("600519.SH")
        assert quote.name == "贵州茅台"
        assert quote.volume == 20000
        assert quote.amount == 30000000
        assert quote.valuation.pe_ttm == 20


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["timeout", "oversize", "malformed"])
async def test_upstream_failure_is_bounded_and_sanitized(mode):
    def handler(request):
        if mode == "timeout":
            raise httpx.ReadTimeout("secret provider error")
        return httpx.Response(
            200, content=b"x" * (2 * 1024 * 1024 + 1) if mode == "oversize" else b"not-json"
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = NativeMarketService(client)
        with pytest.raises(HTTPException) as error:
            await service.kline("600519.SH")
        assert error.value.status_code == 502
        assert error.value.detail == "finance.market.errors.upstream"
        assert service._active == 0
        assert not service._cache


@pytest.mark.asyncio
async def test_cache_limit_and_copy_isolation():
    def handler(request):
        return httpx.Response(
            200, content=b"v_hint='sh~600519~\\u8d35\\u5dde\\u8305\\u53f0~gzmt~GP';"
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = NativeMarketService(client)
        first = await service.search("test")
        assert first.items[0].name == "贵州茅台"
        first.items.clear()
        assert len((await service.search("test")).items) == 1
        for index in range(130):
            await service.search(str(index))
        assert len(service._cache) == 128


@pytest.mark.asyncio
async def test_native60_raw_and_sparks():
    def handler(request):
        if "mkline" in request.url.path:
            return httpx.Response(
                200,
                json={
                    "data": {"sz000001": {"m60": [["202611061030", "10", "11", "12", "9", "200"]]}}
                },
            )
        return httpx.Response(
            200,
            json={"data": {"sz000001": {"data": {"date": "20261106", "data": ["0930 10 2 2000"]}}}},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        service = NativeMarketService(client)
        kline = await service.kline60("000001.SZ")
        assert kline.period == "60" and kline.adjust == "raw"
        assert kline.bars[0].volume == 20000
        sparks = await service.sparks(["000001.SZ"])
        assert sparks.items[0].points == [10]
        with pytest.raises(HTTPException) as error:
            await service.sparks(["000001.SZ"] * 21)
        assert error.value.status_code == 422


@pytest.mark.asyncio
async def test_batch_quotes_partial_missing():
    fields = [""] * 47
    fields[1], fields[2], fields[3], fields[30] = "平安银行", "000001", "10", "20261106113000"
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(
            200, content=('v_sz000001="' + "~".join(fields) + '";v_sh600519="";').encode("gbk")
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await NativeMarketService(client).quotes(["000001.SZ", "600519.SH"])
        assert [q.symbol for q in result.items] == ["000001.SZ"]
        assert result.missing == ["600519.SH"]
        assert len(calls) == 1
        assert calls[0].url.params["q"] == "sz000001,sh600519"
