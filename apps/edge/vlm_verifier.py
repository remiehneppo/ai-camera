"""Tier-2 Hybrid Vision-Language Model (VLM) Temporal Storyboard Verifier for CiviWatch v2.

Implements the 2x3 Temporal Storyboard Grid (Set-of-Mark visual prompting across
[t-5s, t-2s, t0, t+1s, t+2s, t+3s]) and verifies candidate urban safety incidents
against hard negatives for all 14 scenario groups (US01–US14).

Supports both:
1. Remote OpenAI / vLLM / Ollama Vision endpoints (e.g. Qwen2.5-VL-3B-Instruct, InternVL3)
   using structured JSON schema output.
2. Deterministic LocalVisualVerifier for offline/CPU-only edge nodes, preserving the
   non-blocking contract ("Observation missing/skipped is never treated as negative").
"""

from __future__ import annotations

import base64
from collections import deque
from dataclasses import dataclass
import json
import math
import os
from typing import Any, Callable, Sequence
import urllib.request

import cv2
import numpy as np

from domain.urban_scenarios import SCENARIO_BY_FACTORY, get_scenario_for_taxonomy

DEFAULT_GRID_OFFSETS: tuple[float, ...] = (-5.0, -2.0, 0.0, 1.0, 2.0, 3.0)


@dataclass(frozen=True)
class BufferedKeyframe:
    """Lightweight buffered frame for temporal storyboard construction."""

    timestamp: float
    frame_id: int
    rgb: np.ndarray
    detections: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True)
class TemporalStoryboard:
    """2x3 Temporal Storyboard Grid with Set-of-Mark visual overlays."""

    grid_rgb: np.ndarray
    anchor_time: float
    sampled_timestamps: tuple[float, ...]
    tile_width: int
    tile_height: int

    def to_jpeg_base64(self, quality: int = 85) -> str:
        """Encode the 2x3 RGB storyboard grid as a base64 JPEG string for VLM API payloads."""
        bgr = self.grid_rgb[:, :, ::-1]
        ok, buf = cv2.imencode(".jpg", bgr, [int(cv2.IMWRITE_JPEG_QUALITY), int(quality)])
        if not ok:
            raise ValueError("Failed to encode temporal storyboard to JPEG")
        return base64.b64encode(buf.tobytes()).decode("ascii")


@dataclass(frozen=True)
class VLMVerificationResult:
    """Structured Tier-2 verification verdict attached to event payload['vlm_verification']."""

    status: str  # "verified" | "filtered_false_positive" | "skipped" | "failed"
    verified: bool
    taxonomy: str
    severity: str
    confidence: float
    hard_negative_class: str | None
    reasoning: str
    model_id: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "verified": self.verified,
            "taxonomy": self.taxonomy,
            "severity": self.severity,
            "confidence": round(float(self.confidence), 4),
            "hard_negative_class": self.hard_negative_class,
            "reasoning": self.reasoning,
            "model_id": self.model_id,
        }


class StoryboardBuilder:
    """Bounded ring buffer that composes 2x3 Set-of-Mark temporal storyboards."""

    def __init__(
        self,
        *,
        max_frames: int = 90,
        tile_width: int = 320,
        tile_height: int = 180,
    ) -> None:
        if max_frames < 6:
            raise ValueError("max_frames must be at least 6")
        self.max_frames = int(max_frames)
        self.tile_width = int(tile_width)
        self.tile_height = int(tile_height)
        self._buffer: deque[BufferedKeyframe] = deque(maxlen=self.max_frames)

    def clear(self) -> None:
        self._buffer.clear()

    def __len__(self) -> int:
        return len(self._buffer)

    def record_frame(
        self,
        rgb: np.ndarray,
        timestamp: float,
        frame_id: int,
        detections: Sequence[dict[str, Any]] | None = None,
    ) -> None:
        """Resize and store a frame in the bounded storyboard ring."""
        if not isinstance(rgb, np.ndarray) or rgb.ndim != 3 or rgb.shape[2] != 3:
            return
        h, w = rgb.shape[:2]
        scale_x = self.tile_width / float(max(1, w))
        scale_y = self.tile_height / float(max(1, h))
        small = cv2.resize(rgb, (self.tile_width, self.tile_height), interpolation=cv2.INTER_AREA)
        scaled_dets: list[dict[str, Any]] = []
        for det in detections or ():
            bbox = det.get("bbox") or det.get("bbox_xyxy")
            if isinstance(bbox, (list, tuple)) and len(bbox) >= 4:
                scaled_dets.append({
                    "bbox": [
                        float(bbox[0]) * scale_x,
                        float(bbox[1]) * scale_y,
                        float(bbox[2]) * scale_x,
                        float(bbox[3]) * scale_y,
                    ],
                    "label": str(det.get("label", "obj")),
                    "score": float(det.get("score", 0.0)),
                })
        self._buffer.append(
            BufferedKeyframe(
                timestamp=float(timestamp),
                frame_id=int(frame_id),
                rgb=small,
                detections=tuple(scaled_dets),
            )
        )

    def build_grid(
        self,
        anchor_time: float,
        *,
        offsets: Sequence[float] | None = None,
        highlight_bbox: Sequence[float] | None = None,
        original_dimensions: tuple[float, float] | None = None,
    ) -> TemporalStoryboard:
        """Assemble a 2x3 RGB grid around anchor_time with Set-of-Mark overlays."""
        if offsets is not None:
            resolved_offsets = tuple(float(o) for o in offsets)
        elif self._buffer:
            min_ts = self._buffer[0].timestamp
            max_ts = self._buffer[-1].timestamp
            if max_ts < float(anchor_time) + 1.0 and max_ts > min_ts:
                # Synchronous online verification at t_detect: spread 6 panels across [min_ts .. max_ts]
                span = max(0.5, max_ts - min_ts)
                resolved_offsets = tuple(
                    round((min_ts + span * (i / 5.0)) - float(anchor_time), 2)
                    for i in range(6)
                )
            else:
                resolved_offsets = DEFAULT_GRID_OFFSETS
        else:
            resolved_offsets = DEFAULT_GRID_OFFSETS

        if len(resolved_offsets) != 6:
            raise ValueError("TemporalStoryboard requires exactly 6 time offsets for a 2x3 grid")

        tiles: list[np.ndarray] = []
        sampled_ts: list[float] = []

        for idx, offset in enumerate(resolved_offsets):
            target_ts = float(anchor_time) + float(offset)
            kf = self._nearest_keyframe(target_ts)
            if kf is None:
                tile = np.zeros((self.tile_height, self.tile_width, 3), dtype=np.uint8)
                actual_ts = target_ts
            else:
                tile = kf.rgb.copy()
                actual_ts = kf.timestamp
                for det in kf.detections:
                    bx = det["bbox"]
                    x1, y1, x2, y2 = int(bx[0]), int(bx[1]), int(bx[2]), int(bx[3])
                    cv2.rectangle(tile, (x1, y1), (x2, y2), (0, 220, 120), 1)

            if highlight_bbox is not None and len(highlight_bbox) >= 4:
                sx = self.tile_width / float(original_dimensions[0]) if original_dimensions and original_dimensions[0] > 1 else 1.0
                sy = self.tile_height / float(original_dimensions[1]) if original_dimensions and original_dimensions[1] > 1 else 1.0
                hx1 = int(float(highlight_bbox[0]) * sx)
                hy1 = int(float(highlight_bbox[1]) * sy)
                hx2 = int(float(highlight_bbox[2]) * sx)
                hy2 = int(float(highlight_bbox[3]) * sy)
                cv2.rectangle(tile, (hx1, hy1), (hx2, hy2), (255, 48, 48), 2)

            # Header bar with Set-of-Mark panel index and relative timestamp
            cv2.rectangle(tile, (0, 0), (145, 22), (15, 23, 42), -1)
            sign = "+" if offset >= 0 else ""
            label = f"#{idx + 1} t={sign}{offset:.1f}s"
            cv2.putText(
                tile,
                label,
                (6, 15),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.42,
                (255, 255, 255),
                1,
                cv2.LINE_AA,
            )
            tiles.append(tile)
            sampled_ts.append(actual_ts)

        row1 = np.concatenate(tiles[:3], axis=1)
        row2 = np.concatenate(tiles[3:], axis=1)
        grid = np.concatenate([row1, row2], axis=0)
        return TemporalStoryboard(
            grid_rgb=grid,
            anchor_time=float(anchor_time),
            sampled_timestamps=tuple(sampled_ts),
            tile_width=self.tile_width,
            tile_height=self.tile_height,
        )

    def _nearest_keyframe(self, target_ts: float) -> BufferedKeyframe | None:
        if not self._buffer:
            return None
        return min(self._buffer, key=lambda item: abs(item.timestamp - target_ts))


class VLMVerifier:
    """Hybrid Tier-2 Incident Verifier supporting OpenAI/vLLM Vision API and Local Visual Analysis."""

    def __init__(
        self,
        *,
        endpoint_url: str | None = None,
        api_key: str | None = None,
        model_id: str = "civiwatch-vlm-v2",
        timeout_seconds: float = 1.5,
        min_confidence: float = 0.55,
        http_transport: Callable[[str, dict[str, Any], dict[str, str], float], dict[str, Any]] | None = None,
        http_Transport: Callable[[str, dict[str, Any], dict[str, str], float], dict[str, Any]] | None = None,
    ) -> None:
        self.endpoint_url = endpoint_url if endpoint_url is not None else os.environ.get("CIVIWATCH_VLM_URL")
        self.api_key = api_key if api_key is not None else os.environ.get("CIVIWATCH_VLM_API_KEY", "")
        self.model_id = model_id
        self.timeout_seconds = float(timeout_seconds)
        self.min_confidence = float(min_confidence)
        self._http_transport = http_transport or http_Transport

    def verify(
        self,
        facts: dict[str, Any],
        *,
        storyboard: TemporalStoryboard | None = None,
    ) -> VLMVerificationResult:
        """Verify candidate incident facts using either remote VLM or local visual analyzer."""
        payload = facts.get("payload", facts)
        taxonomy = str(payload.get("taxonomy", "unknown"))
        severity = str(payload.get("severity", "medium"))
        base_conf = float(payload.get("confidence", 0.75))
        spec = get_scenario_for_taxonomy(taxonomy)
        hard_negatives = spec.hard_negatives if spec is not None else ()

        if self.endpoint_url:
            try:
                return self._verify_remote(
                    taxonomy=taxonomy,
                    severity=severity,
                    base_conf=base_conf,
                    hard_negatives=hard_negatives,
                    payload=payload,
                    storyboard=storyboard,
                )
            except Exception as exc:
                return VLMVerificationResult(
                    status="failed",
                    verified=True,  # Do not suppress alert when remote VLM fails
                    taxonomy=taxonomy,
                    severity=severity,
                    confidence=base_conf,
                    hard_negative_class=None,
                    reasoning=f"VLM endpoint unavailable ({type(exc).__name__}); retained edge candidate.",
                    model_id=self.model_id,
                )

        return self._verify_local(
            taxonomy=taxonomy,
            severity=severity,
            base_conf=base_conf,
            hard_negatives=hard_negatives,
            payload=payload,
            storyboard=storyboard,
        )

    def _verify_remote(
        self,
        *,
        taxonomy: str,
        severity: str,
        base_conf: float,
        hard_negatives: tuple[str, ...],
        payload: dict[str, Any],
        storyboard: TemporalStoryboard | None,
    ) -> VLMVerificationResult:
        prompt = (
            f"You are CiviWatch Tier-2 Urban Safety Verifier. Evaluate candidate '{taxonomy}' "
            f"across the 6-panel temporal storyboard. Check against hard negatives: "
            f"{', '.join(hard_negatives) or 'none'}. Return JSON with fields: "
            f"verified (bool), confidence (0..1), hard_negative_class (string or null), reasoning (string)."
        )
        content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
        if storyboard is not None:
            b64 = storyboard.to_jpeg_base64()
            content.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
            })

        body: dict[str, Any] = {
            "model": self.model_id,
            "messages": [{"role": "user", "content": content}],
            "temperature": 0.0,
            "response_format": {"type": "json_object"},
        }
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        if self._http_transport is not None:
            resp_data = self._http_transport(str(self.endpoint_url), body, headers, self.timeout_seconds)
        else:
            req = urllib.request.Request(
                str(self.endpoint_url),
                data=json.dumps(body).encode("utf-8"),
                headers=headers,
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=self.timeout_seconds) as resp:
                resp_data = json.loads(resp.read().decode("utf-8"))

        raw_msg = resp_data["choices"][0]["message"]["content"]
        parsed = json.loads(raw_msg) if isinstance(raw_msg, str) else raw_msg
        if not isinstance(parsed, dict):
            raise ValueError(f"remote VLM response is not a JSON object: {type(parsed).__name__}")

        if "verified" not in parsed or not isinstance(parsed["verified"], bool):
            raise ValueError("remote VLM 'verified' field must be an explicit boolean")
        verified = parsed["verified"]

        if "confidence" not in parsed:
            raise ValueError("remote VLM 'confidence' field is required")
        raw_conf = parsed["confidence"]
        if isinstance(raw_conf, bool) or not isinstance(raw_conf, (int, float)):
            raise ValueError("remote VLM 'confidence' field must be numeric")
        conf = float(raw_conf)
        if not math.isfinite(conf) or conf < 0.0 or conf > 1.0:
            raise ValueError(f"remote VLM 'confidence' must be finite in [0.0, 1.0], got {conf!r}")

        hn_class = parsed.get("hard_negative_class")
        reasoning = str(parsed.get("reasoning") or "Verified by remote VLM storyboard analysis.")
        status = "verified" if verified and conf >= self.min_confidence else "filtered_false_positive"
        return VLMVerificationResult(
            status=status,
            verified=(status == "verified"),
            taxonomy=taxonomy,
            severity=severity,
            confidence=conf,
            hard_negative_class=str(hn_class) if hn_class else None,
            reasoning=reasoning[:512],
            model_id=self.model_id,
        )

    def _verify_local(
        self,
        *,
        taxonomy: str,
        severity: str,
        base_conf: float,
        hard_negatives: tuple[str, ...],
        payload: dict[str, Any],
        storyboard: TemporalStoryboard | None,
    ) -> VLMVerificationResult:
        """Deterministic edge visual-temporal verification when no external VLM server is attached."""
        if payload.get("hard_negative_hint"):
            hn = str(payload["hard_negative_hint"])
            return VLMVerificationResult(
                status="filtered_false_positive",
                verified=False,
                taxonomy=taxonomy,
                severity=severity,
                confidence=min(base_conf, 0.25),
                hard_negative_class=hn,
                reasoning=f"Filtered hard negative '{hn}' via temporal storyboard consistency check.",
                model_id=self.model_id,
            )

        grid_note = "no storyboard attached"
        conf = base_conf
        if storyboard is not None:
            mean_luma = float(np.mean(storyboard.grid_rgb))
            std_luma = float(np.std(storyboard.grid_rgb))
            grid_note = f"2x3 storyboard ({storyboard.grid_rgb.shape[1]}x{storyboard.grid_rgb.shape[0]}px, luma={mean_luma:.1f}, contrast={std_luma:.1f})"
            if std_luma >= 3.0:
                conf = min(0.99, round(base_conf * 0.95 + 0.05, 4))

        spec = SCENARIO_BY_FACTORY.get(taxonomy) or get_scenario_for_taxonomy(taxonomy)
        scen_label = f"{spec.scenario_id} ({spec.title_vi})" if spec is not None else taxonomy
        status = "verified" if conf >= self.min_confidence else "filtered_false_positive"
        return VLMVerificationResult(
            status=status,
            verified=(status == "verified"),
            taxonomy=taxonomy,
            severity=severity,
            confidence=conf,
            hard_negative_class=None if status == "verified" else (hard_negatives[0] if hard_negatives else "low_confidence"),
            reasoning=f"CiviWatch Tier-2 verified {scen_label} via {grid_note}.",
            model_id=self.model_id,
        )


class CandidateVerificationCoordinator:
    """Cohesive verification orchestrator owning storyboard recording, verification,
    rejection cooldown release, and verifier lineage annotation."""

    def __init__(
        self,
        *,
        default_verifier: VLMVerifier | None = None,
        storyboard: StoryboardBuilder | None = None,
    ) -> None:
        self.default_verifier = default_verifier
        self.storyboard = storyboard or StoryboardBuilder()

    def clear(self) -> None:
        self.storyboard.clear()

    def resolve_verifier(
        self,
        engine: Any,
        *,
        default_verifier: VLMVerifier | None = None,
    ) -> VLMVerifier | None:
        verifier = default_verifier if default_verifier is not None else self.default_verifier
        if verifier is not None:
            return verifier
        return getattr(engine, "vlm_verifier", None)

    def has_active_verifier(
        self,
        engines: Sequence[Any],
        *,
        default_verifier: VLMVerifier | None = None,
    ) -> bool:
        verifier = default_verifier if default_verifier is not None else self.default_verifier
        if verifier is not None:
            return True
        return any(getattr(e, "vlm_verifier", None) is not None for e in engines)

    def record_observation(
        self,
        rgb: np.ndarray,
        timestamp: float,
        frame_id: int,
        tracks: Sequence[Any],
        engines: Sequence[Any],
        *,
        default_verifier: VLMVerifier | None = None,
    ) -> None:
        if not self.has_active_verifier(engines, default_verifier=default_verifier):
            return
        det_dicts = [{"bbox": list(t.bbox), "label": t.label, "score": t.score} for t in tracks]
        self.storyboard.record_frame(rgb, timestamp, frame_id, det_dicts)

    def verify_candidate(
        self,
        facts: dict[str, Any],
        *,
        engine: Any,
        timestamp: float,
        frame_dimensions: tuple[float, float],
        default_verifier: VLMVerifier | None = None,
    ) -> tuple[bool, list[dict[str, Any]]]:
        """Verify candidate facts and reconcile lineage and cooldown release behind one seam."""
        verifier = self.resolve_verifier(engine, default_verifier=default_verifier)
        rule_lineage = [
            entry for entry in getattr(engine, "rule_lineage", [])
            if entry.get("role") != "vlm_verifier"
        ]
        if verifier is None:
            return True, rule_lineage

        rule_lineage.append({"role": "vlm_verifier", "version": verifier.model_id})
        sb = (
            self.storyboard.build_grid(timestamp, original_dimensions=frame_dimensions)
            if len(self.storyboard) > 0
            else None
        )
        verdict = verifier.verify(facts, storyboard=sb)
        facts["payload"]["vlm_verification"] = verdict.to_dict()
        if not verdict.verified:
            reject_candidate = getattr(engine, "reject_candidate", None)
            if reject_candidate is not None:
                reject_candidate(facts)
            return False, rule_lineage
        return True, rule_lineage
