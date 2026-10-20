"""ByteTrack multi-object tracker with sliding window kinematics."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class TrackObservation:
    timestamp: float
    bbox: list[float]
    score: float
    cx: float
    cy: float
    aspect_ratio: float


def bbox_iou(box1: list[float], box2: list[float]) -> float:
    """Compute Intersection-over-Union (IoU) between two bounding boxes [x1, y1, x2, y2]."""
    x1 = max(box1[0], box2[0])
    y1 = max(box1[1], box2[1])
    x2 = min(box1[2], box2[2])
    y2 = min(box1[3], box2[3])
    inter_w = max(0.0, x2 - x1)
    inter_h = max(0.0, y2 - y1)
    inter_area = inter_w * inter_h
    if inter_area <= 0.0:
        return 0.0
    area1 = max(0.0, box1[2] - box1[0]) * max(0.0, box1[3] - box1[1])
    area2 = max(0.0, box2[2] - box2[0]) * max(0.0, box2[3] - box2[1])
    union_area = area1 + area2 - inter_area
    if union_area <= 0.0:
        return 0.0
    return inter_area / union_area


class Track:
    """Tracked object representation with motion history."""

    def __init__(
        self,
        track_id: int,
        bbox: list[float],
        score: float,
        label: str,
        timestamp: float,
        state: str = "active",
        max_gap: float = 1.0,
    ) -> None:
        self.max_gap: float = float(max_gap)
        self.track_id: int = track_id
        self.bbox: list[float] = [float(x) for x in bbox]
        self.score: float = float(score)
        self.label: str = str(label)
        self.state: str = str(state)
        self.start_time: float = float(timestamp)
        self.last_time: float = float(timestamp)
        self.consecutive_hits: int = 1
        self.activate_after: int | None = None
        self.history: list[TrackObservation] = []
        self._record_observation(self.bbox, self.score, timestamp)

    @property
    def width(self) -> float:
        return max(0.0, self.bbox[2] - self.bbox[0])

    @property
    def height(self) -> float:
        return max(0.0, self.bbox[3] - self.bbox[1])

    @property
    def cx(self) -> float:
        return (self.bbox[0] + self.bbox[2]) / 2.0

    @property
    def cy(self) -> float:
        return (self.bbox[1] + self.bbox[3]) / 2.0

    @property
    def aspect_ratio(self) -> float:
        h = self.height
        return self.width / max(h, 1e-6)

    def _record_observation(self, bbox: list[float], score: float, timestamp: float) -> None:
        cx = (bbox[0] + bbox[2]) / 2.0
        cy = (bbox[1] + bbox[3]) / 2.0
        w = max(0.0, bbox[2] - bbox[0])
        h = max(0.0, bbox[3] - bbox[1])
        ar = w / max(h, 1e-6)
        self.history.append(
            TrackObservation(
                timestamp=float(timestamp),
                bbox=[float(x) for x in bbox],
                score=float(score),
                cx=cx,
                cy=cy,
                aspect_ratio=ar,
            )
        )
        # shortcut: five seconds/256 observations cover lab sampling; resize before high-FPS acceptance.
        self.history[:] = [obs for obs in self.history if obs.timestamp >= float(timestamp) - 5][-256:]

    def update(self, bbox: list[float], score: float, timestamp: float) -> None:
        ts = float(timestamp)
        if ts < self.last_time or ts - self.last_time > self.max_gap:
            # Gap or clock jump: pre-gap motion/hit evidence must not bridge to this observation.
            self.history.clear()
            self.consecutive_hits = 0
        self.bbox = [float(x) for x in bbox]
        self.score = float(score)
        self.last_time = float(timestamp)
        if self.state == "tentative":
            # ByteTracker owns promotion via activate_after (set on tracks it creates); a bare Track
            # used on its own keeps the contract default of two consecutive hits.
            self.consecutive_hits += 1
            if self.activate_after is None and self.consecutive_hits >= 2:
                self.state = "active"
        else:
            self.state = "active"
            self.consecutive_hits += 1
        self._record_observation(self.bbox, self.score, timestamp)

    def mark_lost(self) -> None:
        self.state = "lost"

    def mark_removed(self) -> None:
        self.state = "removed"

    def predict_bbox(self, timestamp: float) -> list[float]:
        """Predicts bounding box [x1, y1, x2, y2] at timestamp using constant velocity."""
        if len(self.history) < 2:
            return list(self.bbox)
        latest = self.history[-1]
        prev = self.history[-2]
        dt_obs = latest.timestamp - prev.timestamp
        dt = float(timestamp) - latest.timestamp
        if dt_obs <= 1e-6 or dt <= 0.0:
            return list(self.bbox)

        vx = (latest.cx - prev.cx) / dt_obs
        vy = (latest.cy - prev.cy) / dt_obs

        pred_cx = latest.cx + vx * dt
        pred_cy = latest.cy + vy * dt
        w = self.width
        h = self.height
        return [pred_cx - w / 2.0, pred_cy - h / 2.0, pred_cx + w / 2.0, pred_cy + h / 2.0]

    def vertical_velocity(self, window_seconds: float = 1.0) -> float:
        """Computes vertical velocity (pixels/second, positive = downward) over sliding window."""
        if len(self.history) < 2:
            return 0.0
        latest = self.history[-1]
        threshold_time = latest.timestamp - window_seconds
        earliest_in_window = latest
        for obs in self.history:
            if obs.timestamp >= threshold_time:
                earliest_in_window = obs
                break
        dt = latest.timestamp - earliest_in_window.timestamp
        if dt <= 0.0:
            prev = self.history[-2]
            dt = latest.timestamp - prev.timestamp
            if dt <= 0.0:
                return 0.0
            return (latest.cy - prev.cy) / dt
        return (latest.cy - earliest_in_window.cy) / dt

    def aspect_ratio_change(self, window_seconds: float = 1.0) -> float:
        """Computes aspect ratio change (latest - earliest) over sliding window."""
        if len(self.history) < 2:
            return 0.0
        latest = self.history[-1]
        threshold_time = latest.timestamp - window_seconds
        earliest_in_window = latest
        for obs in self.history:
            if obs.timestamp >= threshold_time:
                earliest_in_window = obs
                break
        return latest.aspect_ratio - earliest_in_window.aspect_ratio


class ByteTracker:
    """ByteTrack two-stage association multi-object tracker."""

    def __init__(
        self,
        high_threshold: float = 0.5,
        low_threshold: float = 0.1,
        match_threshold: float = 0.2,
        match_threshold_low: float = 0.1,
        max_lost_time: float = 2.0,
        activate_after: int = 2,
        max_observation_gap: float = 1.0,
    ) -> None:
        self.max_observation_gap: float = float(max_observation_gap)
        self.high_threshold: float = float(high_threshold)
        self.low_threshold: float = float(low_threshold)
        self.match_threshold: float = float(match_threshold)
        self.match_threshold_low: float = float(match_threshold_low)
        self.max_lost_time: float = float(max_lost_time)
        self.activate_after: int = int(activate_after)
        self._next_track_id: int = 1
        self.tracks: list[Track] = []

    def reset(self):
        self.tracks.clear()
        self._next_track_id = 1

    def _match_iou(
        self,
        tracks: list[Track],
        detections: list[dict[str, Any]],
        threshold: float,
        timestamp: float | None = None,
    ) -> tuple[list[tuple[Track, dict[str, Any]]], list[Track], list[dict[str, Any]]]:
        if not tracks or not detections:
            return [], list(tracks), list(detections)

        candidates: list[tuple[float, int, int]] = []
        for t_idx, t in enumerate(tracks):
            box = t.predict_bbox(timestamp) if timestamp is not None else t.bbox
            for d_idx, d in enumerate(detections):
                iou = bbox_iou(box, d["bbox"])
                if iou >= threshold:
                    candidates.append((iou, t_idx, d_idx))

        candidates.sort(key=lambda x: x[0], reverse=True)

        matched_tracks: set[int] = set()
        matched_dets: set[int] = set()
        matches: list[tuple[Track, dict[str, Any]]] = []

        for _, t_idx, d_idx in candidates:
            if t_idx in matched_tracks or d_idx in matched_dets:
                continue
            matched_tracks.add(t_idx)
            matched_dets.add(d_idx)
            matches.append((tracks[t_idx], detections[d_idx]))

        unmatched_tracks = [t for i, t in enumerate(tracks) if i not in matched_tracks]
        unmatched_dets = [d for i, d in enumerate(detections) if i not in matched_dets]
        return matches, unmatched_tracks, unmatched_dets

    def update(self, detections: list[dict[str, Any]], timestamp: float) -> list[Track]:
        ts = float(timestamp)
        valid_dets = [
            d for d in detections
            if isinstance(d.get("bbox"), (list, tuple))
            and len(d["bbox"]) == 4
            and float(d.get("score", 0.0)) >= self.low_threshold
        ]

        high_dets = [d for d in valid_dets if float(d["score"]) >= self.high_threshold]
        low_dets = [
            d for d in valid_dets
            if self.low_threshold <= float(d["score"]) < self.high_threshold
        ]

        active_tracks = [t for t in self.tracks if t.state == "active"]
        tentative_tracks = [t for t in self.tracks if t.state == "tentative"]
        lost_tracks = [t for t in self.tracks if t.state == "lost"]

        # Stage 1a: Match active tracks with high-score detections using motion prediction
        matches_1, unmatched_active, remaining_high_1 = self._match_iou(
            active_tracks, high_dets, self.match_threshold, timestamp=ts
        )
        for track, det in matches_1:
            track.update(det["bbox"], float(det["score"]), ts)

        # Stage 1b: Match tentative tracks with remaining high-score detections
        matches_tentative, unmatched_tentative, remaining_high_2 = self._match_iou(
            tentative_tracks, remaining_high_1, self.match_threshold, timestamp=ts
        )
        for track, det in matches_tentative:
            track.update(det["bbox"], float(det["score"]), ts)
            if track.consecutive_hits >= self.activate_after:
                track.state = "active"

        # Tentative tracks that did not match high-score detections are dropped immediately
        for track in unmatched_tentative:
            track.mark_removed()

        # Stage 2: Match remaining active tracks with low-score detections
        matches_2, unmatched_active_2, _ = self._match_iou(
            unmatched_active, low_dets, self.match_threshold_low, timestamp=ts
        )
        for track, det in matches_2:
            track.update(det["bbox"], float(det["score"]), ts)

        # Stage 3: Match remaining high-score detections with lost tracks
        matches_3, remaining_lost, unmatched_high_dets = self._match_iou(
            lost_tracks, remaining_high_2, self.match_threshold, timestamp=ts
        )
        for track, det in matches_3:
            track.update(det["bbox"], float(det["score"]), ts)
            track.state = "active"

        # Initialize new tracks for unmatched high-score detections
        for det in unmatched_high_dets:
            initial_state = "active" if self.activate_after <= 1 else "tentative"
            new_track = Track(
                track_id=self._next_track_id,
                bbox=det["bbox"],
                score=float(det["score"]),
                label=str(det.get("label", "unknown")),
                timestamp=ts,
                state=initial_state,
                max_gap=self.max_observation_gap,
            )
            new_track.activate_after = self.activate_after
            self._next_track_id += 1
            self.tracks.append(new_track)

        # Mark unmatched active tracks as lost or removed if expired
        for track in unmatched_active_2:
            track.consecutive_hits = 0
            if (ts - track.last_time) > self.max_lost_time:
                track.mark_removed()
            else:
                track.mark_lost()

        # Update remaining lost tracks (remove if expired)
        for track in remaining_lost:
            track.consecutive_hits = 0
            if (ts - track.last_time) > self.max_lost_time:
                track.mark_removed()

        self.tracks[:] = [t for t in self.tracks if t.state != "removed"]
        return [t for t in self.tracks if t.state == "active"]

    def get_all_tracks(self) -> list[Track]:
        return list(self.tracks)

    @property
    def active_tracks(self) -> list[Track]:
        return [t for t in self.tracks if t.state == "active"]
