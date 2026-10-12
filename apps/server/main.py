"""FastAPI ingestion and lab dashboard API."""

from __future__ import annotations

import hmac
import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from pymongo.errors import PyMongoError
from starlette.concurrency import run_in_threadpool

from domain.event_contract import EventValidationError, MAX_EVENT_BYTES, validate_event
from apps.server.config import load_server_config
from apps.server.store import EventHashConflict, EventIdentityConflict, EventStore

STATIC_DIR = Path(__file__).parent / "static"


class EventBodyLimitMiddleware:
    def __init__(self, app: Any, max_bytes: int = MAX_EVENT_BYTES) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] != "http" or scope.get("method") != "POST" or scope.get("path") != "/v1/events":
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers", []))
        content_length = headers.get(b"content-length")
        if content_length:
            try:
                if int(content_length) > self.max_bytes:
                    await self._too_large(send)
                    return
            except ValueError:
                await send({"type": "http.response.start", "status": 400, "headers": [(b"content-length", b"0")]})
                await send({"type": "http.response.body", "body": b""})
                return

        messages: list[dict[str, Any]] = []
        size = 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            if message["type"] != "http.request":
                continue
            size += len(message.get("body", b""))
            if size > self.max_bytes:
                await self._too_large(send)
                return
            messages.append(message)
            if not message.get("more_body", False):
                break
        index = 0

        async def replay() -> dict[str, Any]:
            nonlocal index
            if index < len(messages):
                message = messages[index]
                index += 1
                return message
            return await receive()

        await self.app(scope, replay, send)

    @staticmethod
    async def _too_large(send: Any) -> None:
        body = b"request body exceeds configured limit"
        await send({"type": "http.response.start", "status": 413, "headers": [(b"content-type", b"text/plain; charset=utf-8"), (b"content-length", str(len(body)).encode())]})
        await send({"type": "http.response.body", "body": body})


def _bearer(request: Request) -> str:
    value = request.headers.get("authorization", "")
    scheme, _, token = value.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(status_code=401, detail="bearer token required", headers={"WWW-Authenticate": "Bearer"})
    return token


def _device_for_token(token: str, tokens: dict[str, str]) -> str:
    matched: str | None = None
    for candidate, device_id in tokens.items():
        if hmac.compare_digest(token.encode("utf-8"), candidate.encode("utf-8")):
            matched = device_id
    if matched is None:
        raise HTTPException(status_code=401, detail="invalid device credentials", headers={"WWW-Authenticate": "Bearer"})
    return matched


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


def create_app() -> FastAPI:
    try:
        config = load_server_config()
    except ValueError as exc:
        raise RuntimeError(str(exc)) from exc

    try:
        store = EventStore(config.mongo_uri, config.mongo_database)
    except PyMongoError:
        raise RuntimeError("MONGO_URI is invalid") from None
    app = FastAPI(title="AI Camera Lab API", version="1.0.0")
    app.add_middleware(EventBodyLimitMiddleware)
    app.state.event_store = store
    app.state.device_tokens = config.device_tokens
    app.state.dashboard_token = config.dashboard_token
    app.state.config_hash = config.config_hash

    @app.on_event("startup")
    def startup() -> None:
        store.ensure_ready()

    @app.on_event("shutdown")
    def shutdown() -> None:
        store.close()

    @app.get("/healthz")
    def health() -> dict[str, str]:
        try:
            store.client.admin.command("ping")
        except PyMongoError:
            raise HTTPException(status_code=503, detail="database unavailable")
        return {"status": "ok"}

    @app.get("/")
    def dashboard() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.post("/v1/events")
    async def ingest(request: Request) -> JSONResponse:
        authenticated_device = _device_for_token(_bearer(request), device_tokens)
        if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
            raise HTTPException(status_code=415, detail="Content-Type must be application/json")
        try:
            raw = json.loads(await request.body(), object_pairs_hook=_unique_object)
            event = validate_event(raw)
        except (json.JSONDecodeError, UnicodeDecodeError, RecursionError):
            raise HTTPException(status_code=400, detail="malformed JSON")
        except EventValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        if event["device_id"] != authenticated_device:
            raise HTTPException(status_code=403, detail="event device_id does not match authenticated device")
        if request.headers.get("idempotency-key") != event["message_id"]:
            raise HTTPException(status_code=422, detail="Idempotency-Key must match message_id")
        try:
            receipt = await run_in_threadpool(store.persist, event)
        except EventHashConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        except EventIdentityConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        except PyMongoError:
            # Unknown commit result is retried by the edge with the same identity and snapshot.
            raise HTTPException(status_code=503, detail="durable commit unavailable; retry the same event revision")
        return JSONResponse(receipt, status_code=200)

    @app.get("/v1/events")
    def list_events(request: Request, limit: int = 50) -> dict[str, Any]:
        token = _bearer(request)
        if not hmac.compare_digest(token.encode("utf-8"), dashboard_token.encode("utf-8")):
            raise HTTPException(status_code=401, detail="invalid dashboard credentials", headers={"WWW-Authenticate": "Bearer"})
        if not 1 <= limit <= 100:
            raise HTTPException(status_code=422, detail="limit must be between 1 and 100")
        try:
            return {"events": store.list_current(limit)}
        except PyMongoError:
            raise HTTPException(status_code=503, detail="event query unavailable")

    return app


app = create_app()
