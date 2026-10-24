"""FastAPI ingestion and lab dashboard API."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
from pathlib import Path
import time
from typing import Any, Mapping
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pymongo.errors import PyMongoError
from starlette.concurrency import run_in_threadpool

from domain.event_contract import EventValidationError, MAX_EVENT_BYTES, validate_event
from domain.evidence_contract import validate_storage_id
from domain.device_contract import (
    DeviceLifecycleError,
    DeviceRecord,
    ReviewerAccessRecord,
    check_device_access,
    check_reviewer_site_access,
)
from domain.retrieval_contract import (
    ERROR_ARTIFACT_CONFLICT,
    ERROR_COMMAND_TERMINAL,
    ERROR_STALE_LEASE,
    RetrievalError,
    wire_payload,
)
from domain.review_contract import ReviewValidationError, SEVERITY_VALUES, validate_review_request
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
MAX_EVIDENCE_BYTES = 100 * 1024 * 1024  # 100 MiB limit per evidence clip
MAX_TAXONOMY_LENGTH = 128


def _validate_queue_filters(severity: str | None, taxonomy: str | None) -> None:
    if severity is not None and severity not in SEVERITY_VALUES:
        raise HTTPException(status_code=422, detail="severity must be low, medium, high, or critical")
    if taxonomy is not None and (not taxonomy.strip() or len(taxonomy) > MAX_TAXONOMY_LENGTH):
        raise HTTPException(status_code=422, detail="taxonomy must be 1 to 128 characters")


def _infer_evidence_extension(metadata: dict[str, Any], content_type_header: str = "") -> str:
    ct = (
        metadata.get("content_type")
        or metadata.get("content-type")
        or metadata.get("mime_type")
        or content_type_header
    )
    if isinstance(ct, str):
        ct_clean = ct.split(";", 1)[0].strip().lower()
        if ct_clean in {"image/jpeg", "image/jpg"}:
            return ".jpg"
        if ct_clean == "image/png":
            return ".png"
        if ct_clean == "video/mp4":
            return ".mp4"
        if ct_clean == "video/x-matroska":
            return ".mkv"

    codec = metadata.get("codec")
    if isinstance(codec, str):
        c_clean = codec.strip().lower()
        if c_clean in {"jpeg", "mjpeg", "jpg"}:
            return ".jpg"
        if c_clean == "png":
            return ".png"
        if c_clean == "mp4":
            return ".mp4"
        if c_clean in {"mkv", "matroska", "h264", "h265", "hevc"}:
            return ".mkv"

    return ".mkv"


def _infer_media_type(record: dict[str, Any], file_path: Path) -> str:
    manifest = record.get("manifest", {})
    ct = (
        manifest.get("content_type")
        or manifest.get("content-type")
        or manifest.get("mime_type")
    )
    if isinstance(ct, str) and "/" in ct:
        return ct.split(";", 1)[0].strip().lower()

    codec = manifest.get("codec")
    if isinstance(codec, str):
        c_clean = codec.strip().lower()
        if c_clean in {"jpeg", "mjpeg", "jpg"}:
            return "image/jpeg"
        if c_clean == "png":
            return "image/png"
        if c_clean == "mp4":
            return "video/mp4"

    ext = file_path.suffix.lower()
    if ext in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if ext == ".png":
        return "image/png"
    if ext == ".mp4":
        return "video/mp4"

    return "video/x-matroska"


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


MAX_COMMAND_WAIT_SECONDS = 5.0

#: Retrieval failures that mean "your lease is no longer the live one", not "bad input".
RETRIEVAL_CONFLICT_CODES = frozenset({ERROR_STALE_LEASE, ERROR_COMMAND_TERMINAL, ERROR_ARTIFACT_CONFLICT})


def _reviewer_site_denied(actor: str | None, device_id: str, config: ServerConfig, store: EventStore) -> bool:
    """Reviewer site scoping for a device (ticket #33), shared by every reviewer-facing route."""
    allowed = config.reviewer_sites.get(actor or "", ())
    if not allowed:
        return False
    record = store.get_device(device_id)
    site = record.site_id if record else config.device_sites.get(device_id)
    access = ReviewerAccessRecord(reviewer_id=actor or "", allowed_sites=allowed)
    return not check_reviewer_site_access(access, site)


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

        # Ticket #33: Enforce device lifecycle and allowed cameras
        device_rec = store.get_device(authenticated_device)
        if device_rec is not None:
            allowed, reason = check_device_access(device_rec, camera_id=event.get("camera_id"))
            if not allowed:
                raise HTTPException(status_code=403, detail=f"device access denied: {reason}")
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
    def list_events(
        request: Request,
        limit: int = 50,
        cursor: str | None = None,
        severity: str | None = None,
        taxonomy: str | None = None,
    ) -> dict[str, Any]:
        token = _bearer(request)
        if not hmac.compare_digest(token.encode("utf-8"), dashboard_token.encode("utf-8")):
            raise HTTPException(status_code=401, detail="invalid dashboard credentials", headers={"WWW-Authenticate": "Bearer"})
        if not 1 <= limit <= 100:
            raise HTTPException(status_code=422, detail="limit must be between 1 and 100")
        _validate_queue_filters(severity, taxonomy)
        try:
            paginated = store.list_current(limit, cursor=cursor, severity=severity, taxonomy=taxonomy)
            return {
                "events": paginated,
                "next_cursor": getattr(paginated, "next_cursor", None),
                "review_enabled": bool(reviewer_tokens),
            }
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        except PyMongoError:
            raise HTTPException(status_code=503, detail="event query unavailable")

    @app.post("/v1/events/{device_id}/{event_id}/review")
    async def review_event(device_id: str, event_id: str, request: Request) -> dict[str, Any]:
        if not reviewer_tokens:
            raise HTTPException(status_code=503, detail="reviewer credentials are not configured")
        actor = _reviewer_for_token(_bearer(request), reviewer_tokens)
        if actor is None:
            raise HTTPException(status_code=401, detail="invalid reviewer credentials", headers={"WWW-Authenticate": "Bearer"})

        # Ticket #33: Enforce reviewer site scoping
        allowed_sites = config.reviewer_sites.get(actor, ())
        if allowed_sites:
            device_rec = store.get_device(device_id)
            event_site = device_rec.site_id if device_rec else config.device_sites.get(device_id)
            reviewer_access = ReviewerAccessRecord(reviewer_id=actor, allowed_sites=allowed_sites)
            if not check_reviewer_site_access(reviewer_access, event_site):
                raise HTTPException(status_code=403, detail="cross-site review access denied")

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
        severity: str | None = None,
        taxonomy: str | None = None,
        site_id: str | None = None,
    ) -> Response:
        token = _viewer_token(request)
        if not _is_authorized_viewer(token, dashboard_token, reviewer_tokens):
            raise HTTPException(status_code=401, detail="unauthorized viewer credentials", headers={"WWW-Authenticate": "Bearer"})

        # Ticket #33: Enforce reviewer site scoping for export
        actor = _reviewer_for_token(token, reviewer_tokens)
        scoped_allowed_sites: tuple[str, ...] | None = None
        if actor is not None and actor in config.reviewer_sites:
            allowed = config.reviewer_sites[actor]
            if allowed:
                if site_id is not None and site_id not in allowed:
                    raise HTTPException(status_code=403, detail="cross-site export access denied")
                scoped_allowed_sites = allowed
                if site_id is None and len(allowed) == 1:
                    site_id = allowed[0]

        _validate_queue_filters(severity, taxonomy)
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
                severity=severity,
                taxonomy=taxonomy,
                site_id=site_id,
                allowed_sites=scoped_allowed_sites,
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

        # Ticket #33: Enforce device lifecycle status
        device_rec = store.get_device(authenticated_device)
        if device_rec is not None:
            allowed, reason = check_device_access(device_rec)
            if not allowed:
                raise HTTPException(status_code=403, detail=f"device access denied: {reason}")

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

        expected_size = metadata.get("size_bytes")
        expected_size_int: int | None = None
        if expected_size is not None:
            try:
                expected_size_int = int(expected_size)
                if expected_size_int < 0:
                    raise ValueError
            except (ValueError, TypeError):
                raise HTTPException(status_code=422, detail="invalid size_bytes in metadata")

        root = Path(evidence_dir).resolve()
        target_dir = (root / device_id / event_id).resolve()
        if not target_dir.is_relative_to(root):
            raise HTTPException(status_code=422, detail="evidence path escapes storage root")
        target_dir.mkdir(parents=True, exist_ok=True)
        extension = _infer_evidence_extension(metadata, request.headers.get("content-type", ""))
        target_file = target_dir / f"{request_id}{extension}"
        temp_file = target_dir / f".{request_id}.{uuid4().hex}.tmp"

        hasher = hashlib.sha256()
        size_bytes = 0

        try:
            with open(temp_file, "wb") as f:
                async for chunk in request.stream():
                    if not chunk:
                        continue
                    size_bytes += len(chunk)
                    if size_bytes > MAX_EVIDENCE_BYTES:
                        raise HTTPException(status_code=413, detail="evidence payload exceeds maximum allowed size")
                    hasher.update(chunk)
                    f.write(chunk)
                f.flush()
                os.fsync(f.fileno())

            computed_sha256 = hasher.hexdigest()
            if computed_sha256 != sha256_header:
                raise HTTPException(status_code=422, detail="evidence SHA-256 checksum mismatch")

            if expected_size_int is not None and size_bytes != expected_size_int:
                raise HTTPException(status_code=422, detail="evidence size_bytes does not match payload")

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

        # Ticket #33: Enforce reviewer site scoping for evidence manifest
        actor = _reviewer_for_token(token, reviewer_tokens)
        if actor is not None and actor in config.reviewer_sites:
            allowed = config.reviewer_sites[actor]
            if allowed:
                device_rec = store.get_device(device_id)
                event_site = device_rec.site_id if device_rec else config.device_sites.get(device_id)
                reviewer_access = ReviewerAccessRecord(reviewer_id=actor, allowed_sites=allowed)
                if not check_reviewer_site_access(reviewer_access, event_site):
                    raise HTTPException(status_code=403, detail="cross-site evidence access denied")

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

        # Ticket #33: Enforce reviewer site scoping for evidence media
        actor = _reviewer_for_token(token, reviewer_tokens)
        if actor is not None and actor in config.reviewer_sites:
            allowed = config.reviewer_sites[actor]
            if allowed:
                device_rec = store.get_device(device_id)
                event_site = device_rec.site_id if device_rec else config.device_sites.get(device_id)
                reviewer_access = ReviewerAccessRecord(reviewer_id=actor, allowed_sites=allowed)
                if not check_reviewer_site_access(reviewer_access, event_site):
                    raise HTTPException(status_code=403, detail="cross-site evidence access denied")

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

        media_type = _infer_media_type(record, file_path)
        return FileResponse(
            file_path,
            media_type=media_type,
            headers={"Accept-Ranges": "bytes"},
            content_disposition_type=None,
        )

    # ---- Retained-evidence retrieval commands (Ticket #32) ----------------

    @app.post("/v1/evidence/{device_id}/{event_id}/{request_id}/retrieval")
    async def request_retrieval(
        device_id: str, event_id: str, request_id: str, request: Request
    ) -> dict[str, Any]:
        actor = _reviewer_for_token(_bearer(request), reviewer_tokens)
        if actor is None:
            raise HTTPException(
                status_code=401, detail="reviewer credentials required", headers={"WWW-Authenticate": "Bearer"}
            )
        try:
            for value in (device_id, event_id, request_id):
                validate_storage_id(value)
        except ValueError:
            raise HTTPException(status_code=422, detail="invalid evidence identity")
        if _reviewer_site_denied(actor, device_id, config, store):
            raise HTTPException(status_code=403, detail="cross-site evidence access denied")

        raw = await request.body()
        try:
            body = json.loads(raw) if raw else {}
        except Exception:
            raise HTTPException(status_code=400, detail="malformed JSON")
        if not isinstance(body, dict) or set(body) - {"target", "ttl_seconds", "retention_scope"}:
            raise HTTPException(status_code=422, detail="retrieval request carries an unknown field")
        target = body.get("target", "edge")
        if target not in ("edge", "server"):
            raise HTTPException(status_code=422, detail="target must be edge or server")
        ttl = body.get("ttl_seconds", 300.0)
        if type(ttl) not in (int, float) or not 0 < float(ttl) <= 3600:
            raise HTTPException(status_code=422, detail="ttl_seconds must be within (0, 3600]")
        scope = body.get("retention_scope", "clip")
        if scope not in ("clip", "metadata"):
            raise HTTPException(status_code=422, detail="retention_scope must be clip or metadata")
        try:
            doc = await run_in_threadpool(
                store.issue_retrieval,
                device_id,
                event_id,
                request_id,
                target=target,
                issued_by=actor,
                ttl_seconds=float(ttl),
                retention_scope=scope,
            )
        except ReviewNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except RetrievalError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        except PyMongoError:
            raise HTTPException(status_code=503, detail="retrieval command store unavailable")
        return await run_in_threadpool(store.retrieval_view, doc["command_id"])

    @app.get("/v1/retrieval/{command_id}")
    async def get_retrieval(command_id: str, request: Request) -> dict[str, Any]:
        token = _viewer_token(request)
        if not _is_authorized_viewer(token, dashboard_token, reviewer_tokens):
            raise HTTPException(status_code=401, detail="invalid credentials", headers={"WWW-Authenticate": "Bearer"})
        actor = _reviewer_for_token(token, reviewer_tokens)
        try:
            doc = await run_in_threadpool(store.get_retrieval, command_id)
        except PyMongoError:
            raise HTTPException(status_code=503, detail="retrieval command store unavailable")
        if doc is None:
            raise HTTPException(status_code=404, detail="retrieval command not found")
        if _reviewer_site_denied(actor, doc["device_id"], config, store):
            raise HTTPException(status_code=403, detail="cross-site evidence access denied")
        try:
            if doc["target"] == "server":
                await run_in_threadpool(store.settle_server_retrieval, command_id)
            return await run_in_threadpool(store.retrieval_view, command_id)
        except ReviewNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except RetrievalError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        except ReviewConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc))

    @app.get("/v1/devices/{device_id}/commands")
    async def poll_device_commands(device_id: str, request: Request) -> dict[str, Any]:
        authenticated = _device_for_token(_bearer(request), device_tokens)
        if authenticated != device_id:
            raise HTTPException(status_code=403, detail="device_id does not match authenticated device")
        device_rec = await run_in_threadpool(store.get_device, authenticated)
        if device_rec is not None:
            allowed, reason = check_device_access(device_rec)
            if not allowed:
                raise HTTPException(status_code=403, detail=f"device access denied: {reason}")
        try:
            wait = float(request.query_params.get("wait", "0"))
        except ValueError:
            raise HTTPException(status_code=422, detail="wait must be a number of seconds")
        if not 0 <= wait <= MAX_COMMAND_WAIT_SECONDS:
            raise HTTPException(status_code=422, detail=f"wait must be within [0, {MAX_COMMAND_WAIT_SECONDS}]")
        deadline = time.monotonic() + wait
        while True:
            try:
                doc = await run_in_threadpool(store.claim_retrieval, device_id)
            except PyMongoError:
                raise HTTPException(status_code=503, detail="retrieval command store unavailable")
            if doc is not None:
                return {"commands": [wire_payload(store.retrieval_state(doc), now=time.time())]}
            if time.monotonic() >= deadline:
                return {"commands": []}
            await asyncio.sleep(0.05)

    @app.post("/v1/devices/{device_id}/commands/{command_id}/ack")
    async def acknowledge_command(device_id: str, command_id: str, request: Request) -> dict[str, Any]:
        authenticated = _device_for_token(_bearer(request), device_tokens)
        if authenticated != device_id:
            raise HTTPException(status_code=403, detail="device_id does not match authenticated device")
        device_rec = await run_in_threadpool(store.get_device, authenticated)
        if device_rec is not None:
            allowed, reason = check_device_access(device_rec)
            if not allowed:
                raise HTTPException(status_code=403, detail=f"device access denied: {reason}")
        raw = await request.body()
        try:
            body = json.loads(raw) if raw else {}
        except Exception:
            raise HTTPException(status_code=400, detail="malformed JSON")
        if not isinstance(body, dict):
            raise HTTPException(status_code=422, detail="acknowledgement must be an object")
        lease_id = body.get("lease_id")
        ack = {key: value for key, value in body.items() if key != "lease_id"}
        try:
            await run_in_threadpool(
                store.acknowledge_retrieval, command_id, device_id, lease_id=lease_id, ack=ack
            )
        except ReviewNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except RetrievalError as exc:
            status_code = 409 if exc.code in RETRIEVAL_CONFLICT_CODES else 422
            raise HTTPException(status_code=status_code, detail=str(exc))
        except ReviewConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        except PyMongoError:
            raise HTTPException(status_code=503, detail="retrieval command store unavailable")
        return await run_in_threadpool(store.retrieval_view, command_id)

    # ---- Device Lifecycle endpoints (Ticket #33) ---------------------------

    @app.get("/v1/devices/{device_id}")
    def get_device_info(device_id: str, request: Request) -> dict[str, Any]:
        token = _bearer(request)
        if not hmac.compare_digest(token.encode("utf-8"), dashboard_token.encode("utf-8")):
            raise HTTPException(status_code=401, detail="admin dashboard credentials required", headers={"WWW-Authenticate": "Bearer"})
        device = store.get_device(device_id)
        if not device:
            raise HTTPException(status_code=404, detail="device not found")
        return device.to_dict()

    @app.post("/v1/devices/{device_id}/quarantine")
    async def quarantine_device_endpoint(device_id: str, request: Request) -> dict[str, Any]:
        token = _bearer(request)
        if not hmac.compare_digest(token.encode("utf-8"), dashboard_token.encode("utf-8")):
            raise HTTPException(status_code=401, detail="admin dashboard credentials required", headers={"WWW-Authenticate": "Bearer"})
        try:
            body = json.loads(await request.body()) if await request.body() else {}
        except Exception:
            raise HTTPException(status_code=400, detail="malformed JSON")
        reason = body.get("reason", "manual_quarantine")
        try:
            updated = store.quarantine_device(device_id, reason=reason)
            return updated.to_dict()
        except ReviewNotFound:
            raise HTTPException(status_code=404, detail="device not found")
        except DeviceLifecycleError as exc:
            raise HTTPException(status_code=422, detail=str(exc))

    @app.post("/v1/devices/{device_id}/reactivate")
    async def reactivate_device_endpoint(device_id: str, request: Request) -> dict[str, Any]:
        token = _bearer(request)
        if not hmac.compare_digest(token.encode("utf-8"), dashboard_token.encode("utf-8")):
            raise HTTPException(status_code=401, detail="admin dashboard credentials required", headers={"WWW-Authenticate": "Bearer"})
        try:
            body = json.loads(await request.body()) if await request.body() else {}
        except Exception:
            raise HTTPException(status_code=400, detail="malformed JSON")
        reason = body.get("reason")
        try:
            updated = store.reactivate_device(device_id, reason=reason)
            return updated.to_dict()
        except ReviewNotFound:
            raise HTTPException(status_code=404, detail="device not found")
        except DeviceLifecycleError as exc:
            raise HTTPException(status_code=422, detail=str(exc))

    @app.post("/v1/devices/{device_id}/revoke")
    async def revoke_device_endpoint(device_id: str, request: Request) -> dict[str, Any]:
        token = _bearer(request)
        if not hmac.compare_digest(token.encode("utf-8"), dashboard_token.encode("utf-8")):
            raise HTTPException(status_code=401, detail="admin dashboard credentials required", headers={"WWW-Authenticate": "Bearer"})
        try:
            body = json.loads(await request.body()) if await request.body() else {}
        except Exception:
            raise HTTPException(status_code=400, detail="malformed JSON")
        reason = body.get("reason", "manual_revocation")
        try:
            updated = store.revoke_device(device_id, reason=reason)
            return updated.to_dict()
        except ReviewNotFound:
            raise HTTPException(status_code=404, detail="device not found")
        except DeviceLifecycleError as exc:
            raise HTTPException(status_code=422, detail=str(exc))

    return app


try:
    app = create_app()
except RuntimeError:
    app = None  # type: ignore[assignment]
