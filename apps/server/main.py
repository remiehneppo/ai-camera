"""FastAPI ingestion and lab dashboard API."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pymongo.errors import PyMongoError
from starlette.concurrency import run_in_threadpool

from domain.event_contract import EventValidationError, MAX_EVENT_BYTES, validate_event
from domain.evidence_contract import validate_storage_id
from domain.review_contract import ReviewValidationError, validate_review_request
from apps.server.config import ServerConfig, load_server_config
from apps.server.dataset import export_dataset_records, records_to_jsonl
from apps.server.live_stream import LiveStreamService
from apps.server.store import (
    EventHashConflict,
    EventIdentityConflict,
    EventStore,
    ReviewConflict,
    ReviewNotFound,
    cleanup_temp_evidence,
)

STATIC_DIR = Path(__file__).parent / "static"


class EventBodyLimitMiddleware:
    def __init__(self, app: Any, max_bytes: int = MAX_EVENT_BYTES) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        path = scope.get("path", "")
        if scope["type"] != "http" or scope.get("method") != "POST" or not (
            path == "/v1/events" or path.startswith("/v1/events/") and path.endswith("/review")
        ):
            await self.app(scope, receive, send)
            return
        max_bytes = self.max_bytes if path == "/v1/events" else 16 * 1024
        headers = dict(scope.get("headers", []))
        content_length = headers.get(b"content-length")
        if content_length:
            try:
                if int(content_length) > max_bytes:
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
            if size > max_bytes:
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


def _device_for_token(token: str, tokens: Mapping[str, str] | dict[str, str]) -> str:
    matched: str | None = None
    for candidate, device_id in tokens.items():
        if hmac.compare_digest(token.encode("utf-8"), candidate.encode("utf-8")):
            matched = device_id
    if matched is None:
        raise HTTPException(status_code=401, detail="invalid device credentials", headers={"WWW-Authenticate": "Bearer"})
    return matched


def _reviewer_for_token(token: str, tokens: Mapping[str, str] | dict[str, str] | Any) -> str | None:
    matched: str | None = None
    for reviewer, candidate in tokens.items():
        if hmac.compare_digest(token.encode("utf-8"), candidate.encode("utf-8")):
            matched = reviewer
    return matched


def _is_authorized_viewer(token: str, dashboard_token: str, reviewer_tokens: dict[str, str] | Any) -> bool:
    if dashboard_token and hmac.compare_digest(token.encode("utf-8"), dashboard_token.encode("utf-8")):
        return True
    if _reviewer_for_token(token, reviewer_tokens) is not None:
        return True
    return False


def _viewer_token(request: Request) -> str:
    query_token = request.query_params.get("token")
    if query_token:
        return query_token
    return _bearer(request)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


def create_app(config: ServerConfig | None = None, live_service: LiveStreamService | None = None) -> FastAPI:
    if config is None:
        try:
            config = load_server_config()
        except ValueError as exc:
            raise RuntimeError(str(exc)) from exc

    try:
        store = EventStore(config.mongo_uri, config.mongo_database)
    except PyMongoError:
        raise RuntimeError("MONGO_URI is invalid") from None
    if live_service is None:
        live_service = LiveStreamService()
    device_tokens = config.device_tokens
    dashboard_token = config.dashboard_token
    reviewer_tokens = config.reviewer_tokens
    evidence_dir = config.evidence_dir
    app = FastAPI(title="AI Camera Lab API", version="1.0.0")
    app.add_middleware(EventBodyLimitMiddleware)
    app.state.event_store = store
    app.state.device_tokens = config.device_tokens
    app.state.reviewer_tokens = config.reviewer_tokens
    app.state.dashboard_token = config.dashboard_token
    app.state.evidence_dir = config.evidence_dir
    app.state.config_hash = config.config_hash
    app.state.live_service = live_service

    @app.on_event("startup")
    def startup() -> None:
        cleanup_temp_evidence(evidence_dir)
        store.ensure_ready()

    @app.on_event("shutdown")
    def shutdown() -> None:
        live_service.stop()
        store.close()

    @app.get("/healthz")
    def health() -> dict[str, str]:
        try:
            store.client.admin.command("ping")
        except PyMongoError:
            raise HTTPException(status_code=503, detail="database unavailable")
        return {"status": "ok"}

    @app.get("/v1/live/stream")
    def live_stream(request: Request, max_frames: int | None = None) -> StreamingResponse:
        token = _viewer_token(request)
        if not _is_authorized_viewer(token, dashboard_token, reviewer_tokens):
            raise HTTPException(status_code=401, detail="unauthorized viewer credentials", headers={"WWW-Authenticate": "Bearer"})
        return StreamingResponse(
            live_service.iter_frames(max_frames=max_frames),
            media_type="multipart/x-mixed-replace; boundary=frame",
        )

    @app.get("/v1/live/status")
    def live_status(request: Request) -> dict[str, Any]:
        token = _viewer_token(request)
        if not _is_authorized_viewer(token, dashboard_token, reviewer_tokens):
            raise HTTPException(status_code=401, detail="unauthorized viewer credentials", headers={"WWW-Authenticate": "Bearer"})
        return live_service.get_status()

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
            return {"events": store.list_current(limit), "review_enabled": bool(reviewer_tokens)}
        except PyMongoError:
            raise HTTPException(status_code=503, detail="event query unavailable")

    @app.post("/v1/events/{device_id}/{event_id}/review")
    async def review_event(device_id: str, event_id: str, request: Request) -> dict[str, Any]:
        if not reviewer_tokens:
            raise HTTPException(status_code=503, detail="reviewer credentials are not configured")
        actor = _reviewer_for_token(_bearer(request), reviewer_tokens)
        if actor is None:
            raise HTTPException(status_code=401, detail="invalid reviewer credentials", headers={"WWW-Authenticate": "Bearer"})
        if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
            raise HTTPException(status_code=415, detail="Content-Type must be application/json")
        try:
            raw = json.loads(await request.body(), object_pairs_hook=_unique_object)
            review = validate_review_request(raw)
        except (json.JSONDecodeError, UnicodeDecodeError, RecursionError):
            raise HTTPException(status_code=400, detail="malformed JSON")
        except ReviewValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        try:
            return await run_in_threadpool(
                store.record_review,
                {"device_id": device_id, "event_id": event_id},
                review,
                actor,
            )
        except ReviewConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        except ReviewNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except PyMongoError:
            raise HTTPException(status_code=503, detail="review commit unavailable; refetch before retrying")

    @app.get("/v1/dataset/export")
    def export_dataset(
        request: Request,
        split: str = "all",
        decision: str = "all",
        include_ambiguous: bool = False,
        format: str = "jsonl",
        split_by: str = "camera",
    ) -> Response:
        token = _viewer_token(request)
        if not _is_authorized_viewer(token, dashboard_token, reviewer_tokens):
            raise HTTPException(status_code=401, detail="unauthorized viewer credentials", headers={"WWW-Authenticate": "Bearer"})

        if split not in {"train", "val", "test", "all"}:
            raise HTTPException(status_code=422, detail="invalid split parameter")
        if decision not in {"confirmed", "false_positive", "resolved", "reopened", "all"}:
            raise HTTPException(status_code=422, detail="invalid decision parameter")
        if format not in {"jsonl", "json"}:
            raise HTTPException(status_code=422, detail="invalid format parameter")
        if split_by not in {"camera", "site_camera_time", "time"}:
            raise HTTPException(status_code=422, detail="invalid split_by parameter")

        try:
            records = export_dataset_records(
                store=store,
                split=split,
                decision=decision,
                include_ambiguous=include_ambiguous,
                split_by=split_by,
            )
        except PyMongoError:
            raise HTTPException(status_code=503, detail="dataset export unavailable")

        if format == "jsonl":
            content = records_to_jsonl(records)
            return Response(content=content, media_type="application/x-ndjson")
        return JSONResponse({"count": len(records), "records": records})

    @app.put("/v1/evidence/{device_id}/{event_id}/{request_id}")
    async def upload_evidence(
        device_id: str,
        event_id: str,
        request_id: str,
        request: Request,
    ) -> JSONResponse:
        authenticated_device = _device_for_token(_bearer(request), device_tokens)
        if authenticated_device != device_id:
            raise HTTPException(status_code=403, detail="evidence device_id does not match authenticated device")

        sha256_header = request.headers.get("x-evidence-sha256", "").strip().lower()
        if not sha256_header or len(sha256_header) != 64:
            raise HTTPException(status_code=400, detail="X-Evidence-Sha256 header must be a 64-character hex string")

        metadata_header = request.headers.get("x-evidence-metadata", "")
        if not metadata_header:
            raise HTTPException(status_code=400, detail="X-Evidence-Metadata header required")
        try:
            metadata = json.loads(metadata_header)
            if not isinstance(metadata, dict):
                raise ValueError
        except Exception:
            raise HTTPException(status_code=400, detail="X-Evidence-Metadata must be a valid JSON object")

        try:
            for value in (device_id, event_id, request_id):
                validate_storage_id(value)
            declared = await run_in_threadpool(store.evidence_request, device_id, event_id, request_id, metadata)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        except ReviewNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except PyMongoError:
            raise HTTPException(status_code=503, detail="evidence ownership query unavailable")

        body = await request.body()
        computed_sha256 = hashlib.sha256(body).hexdigest()
        if computed_sha256 != sha256_header:
            raise HTTPException(status_code=422, detail="evidence SHA-256 checksum mismatch")

        size_bytes = len(body)
        expected_size = metadata.get("size_bytes")
        if expected_size is not None:
            try:
                if int(expected_size) != size_bytes:
                    raise HTTPException(status_code=422, detail="evidence size_bytes does not match payload")
            except (ValueError, TypeError):
                raise HTTPException(status_code=422, detail="invalid size_bytes in metadata")

        root = Path(evidence_dir).resolve()
        target_dir = (root / device_id / event_id).resolve()
        if not target_dir.is_relative_to(root):
            raise HTTPException(status_code=422, detail="evidence path escapes storage root")
        target_dir.mkdir(parents=True, exist_ok=True)
        target_file = target_dir / f"{request_id}.mkv"
        temp_file = target_dir / f".{request_id}.{uuid4().hex}.tmp"

        try:
            with open(temp_file, "wb") as f:
                f.write(body)
                f.flush()
                os.fsync(f.fileno())
            try:
                # Exclusive publication also handles a retry after rename but before DB commit.
                os.link(temp_file, target_file)
            except FileExistsError:
                if target_file.is_symlink():
                    raise HTTPException(status_code=409, detail="evidence target is not a regular artifact")
                with target_file.open("rb") as existing:
                    if hashlib.file_digest(existing, "sha256").hexdigest() != computed_sha256:
                        raise HTTPException(status_code=409, detail="finalized evidence bytes are immutable")
            for directory in (target_dir, target_dir.parent, root, root.parent):
                fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(fd)
                finally:
                    os.close(fd)
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=500, detail="failed to store evidence file") from exc
        finally:
            temp_file.unlink(missing_ok=True)

        manifest_data = {**metadata, **declared}
        manifest_data["sha256"] = computed_sha256
        manifest_data["size_bytes"] = size_bytes

        try:
            await run_in_threadpool(
                store.record_evidence,
                device_id,
                event_id,
                request_id,
                manifest_data,
                str(target_file),
            )
        except EventHashConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        except PyMongoError:
            raise HTTPException(status_code=503, detail="database unavailable; retry evidence upload")

        receipt = {
            "request_id": request_id,
            "sha256": computed_sha256,
            "size_bytes": size_bytes,
            "location": f"/v1/evidence/{device_id}/{event_id}/{request_id}/media",
            "status": "committed",
        }
        return JSONResponse(receipt, status_code=200)

    @app.get("/v1/evidence/{device_id}/{event_id}/{request_id}")
    async def get_evidence_manifest(
        device_id: str,
        event_id: str,
        request_id: str,
        request: Request,
    ) -> dict[str, Any]:
        token = _viewer_token(request)
        if not _is_authorized_viewer(token, dashboard_token, reviewer_tokens):
            raise HTTPException(status_code=401, detail="invalid credentials", headers={"WWW-Authenticate": "Bearer"})

        try:
            record = await run_in_threadpool(store.get_evidence, device_id, event_id, request_id, verify_file=True)
        except PyMongoError:
            raise HTTPException(status_code=503, detail="database unavailable")

        if not record:
            raise HTTPException(status_code=404, detail="evidence not found")

        file_status = record.get("manifest", {}).get("file_status")
        if file_status in {"missing", "corrupt"}:
            raise HTTPException(status_code=404, detail=f"evidence file {file_status} on disk")

        return record

    @app.get("/v1/evidence/{device_id}/{event_id}/{request_id}/media")
    async def get_evidence_media(
        device_id: str,
        event_id: str,
        request_id: str,
        request: Request,
    ) -> Response:
        token = _viewer_token(request)
        if not _is_authorized_viewer(token, dashboard_token, reviewer_tokens):
            raise HTTPException(status_code=401, detail="invalid credentials", headers={"WWW-Authenticate": "Bearer"})

        try:
            record = await run_in_threadpool(store.get_evidence, device_id, event_id, request_id, verify_file=True)
        except PyMongoError:
            raise HTTPException(status_code=503, detail="database unavailable")

        if not record:
            raise HTTPException(status_code=404, detail="evidence not found")

        file_status = record.get("manifest", {}).get("file_status")
        if file_status in {"missing", "corrupt"}:
            raise HTTPException(status_code=404, detail=f"evidence file {file_status} on disk")
        file_path = Path(record["file_path"])
        if not file_path.is_file():
            raise HTTPException(status_code=404, detail="evidence file missing on disk")

        file_size = file_path.stat().st_size
        range_header = request.headers.get("range")

        if not range_header:
            with open(file_path, "rb") as f:
                content = f.read()
            return Response(
                content=content,
                status_code=200,
                headers={
                    "Content-Type": "video/x-matroska",
                    "Content-Length": str(file_size),
                    "Accept-Ranges": "bytes",
                },
            )

        if not range_header.startswith("bytes="):
            return Response(
                status_code=416,
                headers={"Content-Range": f"bytes */{file_size}"},
            )

        range_val = range_header[len("bytes="):].strip()
        if "," in range_val:
            range_val = range_val.split(",", 1)[0].strip()

        start_str, sep, end_str = range_val.partition("-")
        if not sep:
            return Response(
                status_code=416,
                headers={"Content-Range": f"bytes */{file_size}"},
            )

        try:
            if not start_str:
                suffix_len = int(end_str)
                if suffix_len <= 0 or file_size == 0:
                    return Response(status_code=416, headers={"Content-Range": f"bytes */{file_size}"})
                start = max(0, file_size - suffix_len)
                end = file_size - 1
            elif not end_str:
                start = int(start_str)
                end = file_size - 1
            else:
                start = int(start_str)
                end = int(end_str)
        except ValueError:
            return Response(status_code=416, headers={"Content-Range": f"bytes */{file_size}"})

        if file_size == 0 or start < 0 or start >= file_size or end < start:
            return Response(
                status_code=416,
                headers={"Content-Range": f"bytes */{file_size}"},
            )

        end = min(end, file_size - 1)
        chunk_len = end - start + 1

        with open(file_path, "rb") as f:
            f.seek(start)
            chunk = f.read(chunk_len)

        return Response(
            content=chunk,
            status_code=206,
            headers={
                "Content-Type": "video/x-matroska",
                "Content-Range": f"bytes {start}-{end}/{file_size}",
                "Content-Length": str(chunk_len),
                "Accept-Ranges": "bytes",
            },
        )

    return app


try:
    app = create_app()
except RuntimeError:
    app = None  # type: ignore[assignment]
