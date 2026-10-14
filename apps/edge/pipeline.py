"""End-to-end Edge Perception Pipeline composing detector, tracker, incident engine, recorder, outbox, and uploader."""

from __future__ import annotations

from datetime import datetime, timezone
import logging
import threading
from pathlib import Path
from typing import Any
from uuid import uuid4

import numpy as np

from apps.edge.evidence import EvidenceLifecycle
from apps.edge.incident import IncidentEngine
from apps.edge.oracle_detector import OnnxDetector
from apps.edge.perception import PerceptionExecution
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
        detector: OnnxDetector | None = None,
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
        execution: PerceptionExecution | None = None,
    ) -> None:
        self.recorder = recorder
        self.outbox = outbox
        self.uploader = uploader
        self.evidence = EvidenceLifecycle(outbox, recorder, uploader)
        self.camera_id = camera_id
        self.device_id = device_id
        self.stream_session_id = stream_session_id or str(uuid4())
        self.pipeline_id = pipeline_id
        self.pipeline_version = pipeline_version
        self.config_version = config_version
        self.calibration_version = calibration_version
        self.quality_state = quality_state
        self.origin = origin

        if execution is not None and (detector is not None or manifest_path or model_path):
            raise ValueError("provide execution or detector configuration, not both")
        self.execution = execution or PerceptionExecution(detector, manifest_path=manifest_path,
                                                         model_path=model_path, origin=origin)
        self.detector = self.execution.detector
        self.core_epoch = 1
        self._last_frame_id = -1
        self._last_timestamp: float | None = None
        self.last_observation: dict[str, Any] | None = None
        self._processing_lock = threading.RLock()
        self._lineage = (self.camera_id, self.stream_session_id, self.core_epoch, self.origin, self.config_version)

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

        provenance = self.execution.provenance
        self.model_lineage = [{"role": "detector", "version": provenance.get("model_id", "unknown")}]
        self.model_artifact_hash = provenance.get("model_sha256", "unknown_artifact")

    def process_frame(self, rgb, timestamp, frame_id, *, detections=None, observation_status=None):
        with self._processing_lock:
            return self._process_frame(rgb, timestamp, frame_id, detections=detections,
                                       observation_status=observation_status)

    def _process_frame(
        self,
        rgb: np.ndarray,
        timestamp: float,
        frame_id: int,
        *,
        detections: list[dict[str, Any]] | None = None,
        observation_status: str | None = None,
    ) -> list[dict[str, Any]]:
        """Process one video frame: detection -> tracking -> incident engine -> event/pin/outbox."""
        ts = float(timestamp)
        fid = int(frame_id)

        lineage = (self.camera_id, self.stream_session_id, self.core_epoch, self.origin, self.config_version)
        if lineage != self._lineage:
            self.tracker.reset()
            self.incident_engine.reset()
            self._last_frame_id = -1
            self._last_timestamp = None
            self._lineage = lineage
        frame = self.execution.frame(self.camera_id, self.stream_session_id, self.core_epoch,
                                     self.origin, fid, ts)
        if fid <= self._last_frame_id or (self._last_timestamp is not None and ts <= self._last_timestamp):
            self.last_observation = {**frame, "detection_status": "stale", "detections": []}
            self._observation_gap()
            return []
        self._last_frame_id = fid
        self._last_timestamp = ts
        observation = self.execution.execute(rgb, frame, detections=detections, status=observation_status)
        self.last_observation = observation
        if observation["detection_status"] not in {"ok", "ok_empty"}:
            self._observation_gap()
            return []
        formatted_dets = observation["detections"]
        provenance = observation.get("provenance") or {}
        if provenance:
            self.model_lineage = [{"role": "detector", "version": provenance.get("model_id", "unknown")}]
            self.model_artifact_hash = provenance.get("model_sha256", "unknown_artifact")

        # 2. Update multi-object tracker
        tracks = self.tracker.update(formatted_dets, timestamp=ts)

        for track in self.tracker.get_all_tracks():
            if track.state != "active":
                track.history.clear()

        # 3. Assess incident engine
        incidents = self.incident_engine.process_tracks(tracks, timestamp=ts)

        # 4. Handle emitted incidents
        emitted_events: list[dict[str, Any]] = []
        for incident in incidents:
            if incident.get("taxonomy") in {"person_fall", "person_lying_persistent"}:
                event = self._handle_incident(incident, ts)
                emitted_events.append(event)

        return emitted_events

    def _observation_gap(self):
        self.incident_engine.observation_gap()
        # Retain track IDs/cooldown, discard pre-gap motion and standing evidence.
        for track in self.tracker.get_all_tracks():
            track.history.clear()

    def _handle_incident(self, incident: dict[str, Any], timestamp: float) -> dict[str, Any]:
        """Construct validated Event snapshot, pin ring buffer, and atomically enqueue to outbox."""
        event_id = str(uuid4())
        message_id = f"msg-{uuid4().hex[:12]}"
        request_id = f"req-{uuid4().hex[:12]}"
        anchor_time = float(incident.get("anchor_time", timestamp))
        taxonomy = str(incident.get("taxonomy", "person_fall"))
        anchor_kind = str(incident.get("anchor_kind", "onset"))
        severity = str(incident.get("severity", "critical"))

        now_iso = datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")

        # Create structured evidence request: [anchor_time - 10, anchor_time + 20]
        evidence_request = make_evidence_request(
            request_id=request_id,
            session_id=self.stream_session_id,
            anchor_kind=anchor_kind,
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
                "taxonomy": taxonomy,
                "lifecycle": "candidate",
                "severity": severity,
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

        self.evidence.persist(validated_event)

        return validated_event

    def _handle_fall_incident(self, incident: dict[str, Any], timestamp: float) -> dict[str, Any]:
        """Backwards compatibility delegation to _handle_incident."""
        return self._handle_incident(incident, timestamp)

    def trigger_upload(self, *, reconcile: bool = True, finish_sessions=()) -> int:
        """Trigger reconciliation and upload of pending events and evidence clips to server."""
        if self.uploader is None:
            return 0

        if reconcile:
            self.evidence.reconcile(finish_sessions=finish_sessions)

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
        return self.evidence.upload_pending()
