"""Authenticated, stateless read-only NEO MCP transport."""

import asyncio
import json
import logging
from importlib.metadata import PackageNotFoundError, version
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from mcp.shared.version import SUPPORTED_PROTOCOL_VERSIONS
from pydantic import BaseModel, ConfigDict, ValidationError
from starlette.requests import ClientDisconnect

from finerove.finance.contracts import Catalog, EvaluationRequest, EvaluationResult
from finerove.finance.service import NeoService
from octop.api.deps import current_user
from octop.i18n import normalize_locale, tr
from octop.infra.users.identity import User


async def transport_guard(request: Request) -> None:
    locale = normalize_locale(request.headers.get("Accept-Language", "en"))
    if "origin" in request.headers:
        raise HTTPException(403, tr("finance.mcp.origin_denied", locale))
    authorization = request.headers.get("authorization", "").split()
    if (
        "access_token" in request.query_params
        or len(authorization) != 2
        or authorization[0].lower() != "bearer"
    ):
        raise HTTPException(401, tr("finance.mcp.bearer_required", locale))
    protocol = request.headers.get("mcp-protocol-version")
    if protocol is not None and protocol not in SUPPORTED_PROTOCOL_VERSIONS:
        raise HTTPException(400, tr("finance.mcp.unsupported_version", locale))


router = APIRouter(
    prefix="/api/mcp/finance", tags=["Finance"], dependencies=[Depends(transport_guard)]
)


class FinanceAccessFilter(logging.Filter):
    """Remove credentials in legacy finance MCP query targets from access logs."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, tuple) and len(record.args) == 5:
            target = record.args[2]
            if isinstance(target, str) and target.split("?", 1)[0] in (
                "/api/mcp/finance",
                "/api/mcp/finance/",
            ):
                record.args = (*record.args[:2], target.split("?", 1)[0], *record.args[3:])
        return True


def install_mcp(app: FastAPI) -> None:
    logger = logging.getLogger("uvicorn.access")
    if not any(isinstance(item, FinanceAccessFilter) for item in logger.filters):
        logger.addFilter(FinanceAccessFilter())
    app.include_router(router)


MAX_BODY = 64 * 1024
BODY_DEADLINE = 10.0
try:
    SERVER_VERSION = version("octop")
except PackageNotFoundError:
    SERVER_VERSION = "development"


class EmptyArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")


def error(request_id: Any, code: int, message: str, status: int = 200) -> JSONResponse:
    return JSONResponse(
        {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}},
        status_code=status,
    )


def tool_result(data: dict[str, Any], failed: bool = False) -> dict[str, Any]:
    return {
        "content": [{"type": "text", "text": json.dumps(data, ensure_ascii=False)}],
        "structuredContent": data,
        "isError": failed,
    }


async def connected_evaluation(
    request: Request, service: NeoService, user: User, body: EvaluationRequest
) -> EvaluationResult:
    async def disconnected() -> None:
        while True:
            if (await request.receive())["type"] == "http.disconnect":
                return

    computation = asyncio.create_task(service.evaluate(user.id, body))
    connection = asyncio.create_task(disconnected())
    try:
        done, _ = await asyncio.wait((computation, connection), return_when=asyncio.FIRST_COMPLETED)
        if computation not in done:
            raise HTTPException(499, "finance.errors.cancelled")
        return await computation
    finally:
        computation.cancel()
        connection.cancel()
        await asyncio.gather(computation, connection, return_exceptions=True)


@router.api_route("", methods=["GET", "DELETE"], summary="NEO MCP unsupported transport methods")
async def unsupported(user: Annotated[User, Depends(current_user)]) -> Response:
    return Response(status_code=405, headers={"Allow": "POST"})


class RpcError(BaseModel):
    code: int
    message: str


class RpcResponse(BaseModel):
    jsonrpc: Literal["2.0"]
    id: str | int | None
    result: dict[str, Any] | None = None
    error: RpcError | None = None


@router.post(
    "",
    response_model=RpcResponse,
    summary="Authenticated stateless NEO MCP",
    description=(
        "Use Authorization: Bearer with a FineRove login token. Browser Origin and URL tokens "
        "are rejected. Tools list typed input/output schemas; calculations use the authenticated "
        "account and the same NEO grants as the dashboard. Omit id for a notification."
    ),
    responses={202: {"description": "Notification acknowledged without a response body"}},
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": {
                        "type": "object",
                        "required": ["jsonrpc", "method"],
                        "properties": {
                            "jsonrpc": {"type": "string", "enum": ["2.0"]},
                            "id": {"oneOf": [{"type": "string"}, {"type": "integer"}]},
                            "method": {"type": "string", "examples": ["tools/list"]},
                            "params": {"type": "object"},
                        },
                        "additionalProperties": False,
                    }
                }
            },
        }
    },
)
async def endpoint(request: Request, user: Annotated[User, Depends(current_user)]) -> Response:
    locale = normalize_locale(user.locale)
    raw = bytearray()
    try:
        async with asyncio.timeout(BODY_DEADLINE):
            async for chunk in request.stream():
                if len(raw) + len(chunk) > MAX_BODY:
                    return error(None, -32600, tr("finance.mcp.too_large", locale), 413)
                raw.extend(chunk)
        message = json.loads(raw)
    except (ValueError, UnicodeDecodeError, RecursionError):
        return error(None, -32700, tr("finance.mcp.parse_error", locale))
    except TimeoutError:
        return error(None, -32600, tr("finance.mcp.timeout", locale), 408)
    except ClientDisconnect:
        return Response(status_code=499)
    if not isinstance(message, dict):
        return error(None, -32600, tr("finance.mcp.invalid_request", locale))
    request_id = message.get("id")
    if (
        message.get("jsonrpc") != "2.0"
        or not isinstance(message.get("method"), str)
        or not isinstance(message.get("params", {}), dict)
        or (
            "id" in message
            and (isinstance(request_id, bool) or not isinstance(request_id, (str, int)))
        )
        or set(message) - {"jsonrpc", "id", "method", "params"}
    ):
        return error(None, -32600, tr("finance.mcp.invalid_request", locale))
    if "id" not in message:
        return Response(status_code=202)
    params = message.get("params", {})
    method = message["method"]
    locale = normalize_locale(user.locale)
    service: NeoService = request.app.state.neo_service
    if method == "initialize":
        if (
            set(params) - {"protocolVersion", "capabilities", "clientInfo", "_meta"}
            or not isinstance(params.get("protocolVersion"), str)
            or not isinstance(params.get("capabilities"), dict)
            or not isinstance(params.get("clientInfo"), dict)
            or not isinstance(params["clientInfo"].get("name"), str)
            or not isinstance(params["clientInfo"].get("version"), str)
        ):
            return error(request_id, -32602, tr("finance.mcp.invalid_params", locale))
        version = params["protocolVersion"]
        result = {
            "protocolVersion": version
            if version in SUPPORTED_PROTOCOL_VERSIONS
            else SUPPORTED_PROTOCOL_VERSIONS[-1],
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "FinRove NEO", "version": SERVER_VERSION},
        }
    elif method == "ping":
        if set(params) - {"_meta"}:
            return error(request_id, -32602, tr("finance.mcp.invalid_params", locale))
        result = {}
    elif method == "tools/list":
        if set(params) - {"_meta"}:
            return error(request_id, -32602, tr("finance.mcp.invalid_params", locale))
        result = {
            "tools": [
                {
                    "name": "list_neo_capabilities",
                    "description": tr("finance.mcp.list_description", locale),
                    "annotations": {
                        "readOnlyHint": True,
                        "destructiveHint": False,
                        "idempotentHint": True,
                    },
                    "inputSchema": EmptyArguments.model_json_schema(),
                    "outputSchema": Catalog.model_json_schema(),
                },
                {
                    "name": "evaluate_neo_indicator",
                    "description": tr("finance.mcp.evaluate_description", locale),
                    "annotations": {
                        "readOnlyHint": True,
                        "destructiveHint": False,
                        "idempotentHint": True,
                    },
                    "inputSchema": EvaluationRequest.model_json_schema(),
                    "outputSchema": EvaluationResult.model_json_schema(),
                },
            ]
        }
    elif method == "tools/call":
        if (
            set(params) - {"name", "arguments", "_meta"}
            or not isinstance(params.get("name"), str)
            or not isinstance(params.get("arguments", {}), dict)
        ):
            return error(request_id, -32602, tr("finance.mcp.invalid_params", locale))
        name, arguments = params["name"], params.get("arguments", {})
        try:
            if name == "list_neo_capabilities":
                EmptyArguments.model_validate(arguments)
                data = service.catalog()
                for item in data["items"]:
                    item["name"] = tr(item["name"], locale)
                result = tool_result(Catalog.model_validate(data).model_dump(mode="json"))
            elif name == "evaluate_neo_indicator":
                body = EvaluationRequest.model_validate(arguments)
                evaluated = await connected_evaluation(request, service, user, body)
                result = tool_result(evaluated.model_dump(mode="json"))
            else:
                result = tool_result({"error": tr("finance.mcp.unknown_tool", locale)}, True)
        except ValidationError:
            result = tool_result({"error": tr("finance.mcp.invalid_arguments", locale)}, True)
        except HTTPException as exc:
            key = (
                exc.detail
                if isinstance(exc.detail, str)
                and exc.detail
                in {
                    "finance.errors.unconfigured",
                    "finance.errors.busy",
                    "finance.errors.denied",
                    "finance.errors.authentication_failed",
                    "finance.errors.upstream_failed",
                    "finance.errors.cancelled",
                }
                else "finance.errors.upstream_failed"
            )
            result = tool_result({"error": tr(key, locale)}, True)
        except Exception:
            result = tool_result({"error": tr("finance.errors.upstream_failed", locale)}, True)
    else:
        return error(request_id, -32601, tr("finance.mcp.unknown_method", locale))
    return JSONResponse({"jsonrpc": "2.0", "id": request_id, "result": result})
