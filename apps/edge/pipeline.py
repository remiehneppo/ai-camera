"""End-to-end Edge Perception Pipeline composing detector, tracker, incident engine, recorder, outbox, and uploader."""

from __future__ import annotations

from datetime import datetime, timezone
from fractions import Fraction
import logging
from pathlib import Path
from typing import Any
from uuid import uuid4

import numpy as np

from apps.edge.incident import IncidentEngine
from apps.edge.oracle_detector import OracleDetector
from apps.edge.outbox import EventOutbox
from apps.edge.recorder import FileRecorder
from apps.edge.tracker import ByteTracker
from apps.edge.uploader import EdgeUploader
from domain.event_contract import validate_event
from domain.evidence_contract import make_evidence_request

logger = logging.getLogger(__name__)


class PerceptionPipeline:
    """Perception pipeline composing detection, ByteTrack, fall incident engine, and evidence upload."""

    def __init__(
        self,
        *,
        recorder: FileRecorder,
        outbox: EventOutbox,
        detector: OracleDetector | None = None,
        tracker: ByteTracker | None = None,
        incident_engine: IncidentEngine | None = None,
        uploader: EdgeUploader | None = None,
        manifest_path: str | Path | None = None,
        model_path: str | Path | None = None,
        camera_id: str = "lab-camera-01",
        device_id: str = "lab-edge-01",
        stream_session_id: str | None = None,
        pipeline_id: str = "perception-pipeline-v1",
        pipeline_version: str = "1",
        config_version: str = "pipeline-v1",
        calibration_version: str = "uncalibrated",
        quality_state: str = "unknown",
        origin: str = "live",
    ) -> None:
        self.recorder = recorder
        self.outbox = outbox
        self.uploader = uploader
        self.camera_id = camera_id
        self.device_id = device_id
        self.stream_session_id = stream_session_id or str(uuid4())
        self.pipeline_id = pipeline_id
        self.pipeline_version = pipeline_version
        self.config_version = config_version
        self.calibration_version = calibration_version
        self.quality_state = quality_state
        self.origin = origin

        # Initialize or assign detector
        if detector is not None:
            self.detector: OracleDetector | None = detector
        elif manifest_path and model_path:
            self.detector = OracleDetector(manifest_path, model_path)
        else:
            self.detector = None

        # Tracking and incident engines
        self.tracker = tracker or ByteTracker(
            high_threshold=0.5,
            low_threshold=0.1,
            match_threshold=0.2,
        )
        self.incident_engine = incident_engine or IncidentEngine(
            standing_aspect_ratio=0.85,
            lying_aspect_ratio=1.2,
            min_drop_velocity=15.0,
            min_lying_duration=3.0,
            cooldown_seconds=30.0,
        )

        # Model provenance lineage
        if self.detector is not None and hasattr(self.detector, "_manifest"):
            model_id = self.detector._manifest.get("model_id", "yolox-tiny")
            self.model_lineage = [{"role": "oracle_detector", "version": str(model_id)}]
            self.model_artifact_hash = str(self.detector._manifest.get("artifact", {}).get("sha256", "unknown_artifact"))
        else:
            self.model_lineage = [{"role": "detector", "version": "yolox-tiny-v1"}]
            self.model_artifact_hash = "unknown_artifact"

    def process_frame(
        self,
        rgb: np.ndarray,
        timestamp: float,
        frame_id: int,
        *,
        detections: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        """Process one video frame: detection -> tracking -> incident engine -> event/pin/outbox."""
        ts = float(timestamp)
        fid = int(frame_id)

        # 1. Detect objects if detections are not externally provided
        raw_dets: list[dict[str, Any]] = []
        if detections is not None:
            raw_dets = detections
        elif self.detector is not None:
            pts = int(round(ts * 1_000_000))
            frame_meta = {
                "camera_id": self.camera_id,
                "stream_session_id": self.stream_session_id,
                "core_epoch": 1,
                "origin": "replay",
                "frame_id": fid,
                "pts": pts,
                "time_base": "1/1000000",
                "event_time": float(pts * Fraction("1/1000000")),
            }
            try:
                det_result = self.detector.detect(rgb, frame_meta)
                raw_dets = det_result.get("detections", [])
            except Exception as exc:
                logger.warning("Detector execution failed for frame %d: %s", fid, exc)
                raw_dets = []

        # Format detections for ByteTracker
        formatted_dets: list[dict[str, Any]] = []
        for d in raw_dets:
            bbox = d.get("bbox")
            if bbox is None:
                bbox = d.get("bbox_xyxy")
            if bbox is not None and isinstance(bbox, (list, tuple)) and len(bbox) == 4:
                formatted_dets.append({
                    "bbox": [float(x) for x in bbox],
                    "score": float(d.get("score", 0.0)),
                    "label": str(d.get("label", "person")),
                    "class_id": d.get("class_id"),
                })

        # 2. Update multi-object tracker
        tracks = self.tracker.update(formatted_dets, timestamp=ts)

        # 3. Assess incident engine
        incidents = self.incident_engine.process_tracks(tracks, timestamp=ts)

        # 4. Handle emitted incidents
        emitted_events: list[dict[str, Any]] = []
        for incident in incidents:
            if incident.get("taxonomy") == "person_fall":
                event = self._handle_fall_incident(incident, ts)
                emitted_events.append(event)

        return emitted_events

    def _handle_fall_incident(self, incident: dict[str, Any], timestamp: float) -> dict[str, Any]:
        """Construct validated Event snapshot, pin ring buffer, and atomically enqueue to outbox."""
        event_id = str(uuid4())
        message_id = f"msg-{uuid4().hex[:12]}"
        request_id = f"req-{uuid4().hex[:12]}"
        anchor_time = float(incident.get("anchor_time", timestamp))

        now_iso = datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")

        # Create structured evidence request: [anchor_time - 10, anchor_time + 20]
        evidence_request = make_evidence_request(
            request_id=request_id,
            session_id=self.stream_session_id,
            anchor_kind="onset",
            anchor_time=anchor_time,
        )

        event_snapshot: dict[str, Any] = {
            "schema_version": 1,
            "message_id": message_id,
            "event_id": event_id,
            "revision": 1,
            "device_id": self.device_id,
            "camera_id": self.camera_id,
            "stream_session_id": self.stream_session_id,
            "pipeline_id": self.pipeline_id,
            "pipeline_version": self.pipeline_version,
            "origin": self.origin,
            "event_time": now_iso,
            "produced_at": now_iso,
            "config_version": self.config_version,
            "model_lineage": self.model_lineage,
            "model_artifact_hash": self.model_artifact_hash,
            "calibration_version": self.calibration_version,
            "quality_state": self.quality_state,
            "payload": {
                "taxonomy": "person_fall",
                "lifecycle": "candidate",
                "severity": "critical",
                "confidence": float(incident.get("confidence", 0.9)),
                "track_id": incident.get("track_id"),
                "anchor_time": anchor_time,
                "detection_time": float(incident.get("detection_time", timestamp)),
                "detections": incident.get("detections", []),
                "evidence_requests": [evidence_request],
            },
        }

        # Validate event contract
        validated_event = validate_event(event_snapshot)

        # Pin ring buffer in FileRecorder
        owner = f"{self.device_id}/{event_id}/1"
        try:
            self.recorder.pin(
                request_id,
                self.stream_session_id,
                evidence_request["requested_start"],
                evidence_request["requested_end"],
                owner,
            )
        except Exception as exc:
            logger.warning("Recorder pin failed for %s: %s", request_id, exc)

        # Atomically enqueue into durable SQLite outbox
        self.outbox.enqueue(validated_event)

        return validated_event

    def trigger_upload(self, *, reconcile: bool = True) -> int:
        """Trigger reconciliation and upload of pending events and evidence clips to server."""
        if self.uploader is None:
            return 0

        # Reconcile pins and finalize clips
        if reconcile:
            try:
                self.outbox.reconcile_evidence(
                    self.recorder,
                    finish_sessions=[self.stream_session_id],
                )
            except Exception as exc:
                logger.warning("Evidence reconciliation failed: %s", exc)

        # Deliver pending event metadata to server /v1/events
        try:
            from apps.edge.send_synthetic import deliver_pending

            deliver_pending(
                self.outbox,
                self.uploader.server_url,
                self.uploader.device_token,
            )
        except Exception as exc:
            logger.warning("Event metadata delivery failed: %s", exc)

        # Upload pending evidence clips to /v1/evidence
        return self.uploader.upload_pending(reconcile=reconcile)
