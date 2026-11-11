"""Perception Pipeline & Multi-Model Detection Benchmark.

Compares configured detection models on:
- Class-aware 1-to-1 Detection Recall & Night Recall on validation frames.
- CPU Inference Latency (P50 / P95).
- Perception Pipeline execution (`PerceptionPipeline`: Detector -> Tracker -> Homography -> Pose -> Engines)
  on video clips (recording, evidence packaging, and WAN upload are not exercised).
- Measured Markdown report generation.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys
import time
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import cv2
import numpy as np

from apps.edge.homography import GroundPlaneHomography
from apps.edge.incident import IncidentEngine
from apps.edge.oracle_detector import CiviWatchDetector
from apps.edge.outbox import EventOutbox
from apps.edge.perception import PerceptionExecution
from apps.edge.pipeline import PerceptionPipeline
from apps.edge.pose import PoseManager, PoseScheduler, RtmposeEstimator
from apps.edge.recorder import FileRecorder
from apps.edge.vehicle_incident import VehicleIncidentEngine
from tools.replay_runner import run_replay_session

MODELS_CONFIG: list[dict[str, Any]] = [
    {
        "id": "yolox_tiny_coco",
        "name": "YOLOX-Tiny (Baseline COCO)",
        "manifest": ROOT / "models/yolox-tiny/manifest.json",
        "model": ROOT / "data/oracle/yolox_tiny.onnx",
        "resolution": 416,
        "decode": "yolox_grid",
    },
    {
        "id": "yolox_tiny_hcmc",
        "name": "CiviWatch YOLOX-Tiny (HCMC 416)",
        "manifest": ROOT / "models/yolox-tiny-hcmc/manifest.json",
        "model": ROOT / "models/yolox-tiny-hcmc/yolox_tiny_civiwatch_416.onnx",
        "resolution": 416,
        "decode": "yolox_grid",
    },
    {
        "id": "yolox_s_hcmc",
        "name": "CiviWatch YOLOX-s (HCMC 640)",
        "manifest": ROOT / "models/yolox-s-hcmc/manifest.json",
        "model": ROOT / "models/yolox-s-hcmc/yolox_s_civiwatch_640.onnx",
        "resolution": 640,
        "decode": "yolox_grid",
    },
    {
        "id": "yolo26s_hcmc",
        "name": "CiviWatch YOLO26s (HCMC 640 NMS-Free)",
        "manifest": ROOT / "models/civiwatch-640/manifest.json",
        "model": ROOT / "models/civiwatch-640/yolo26s_civiwatch_640.onnx",
        "resolution": 640,
        "decode": "nms_free",
    },
]


def iou(b1: Sequence[float], b2: Sequence[float]) -> float:
    x1 = max(b1[0], b2[0])
    y1 = max(b1[1], b2[1])
    x2 = min(b1[2], b2[2])
    y2 = min(b1[3], b2[3])
    inter = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    a1 = max(0.0, b1[2] - b1[0]) * max(0.0, b1[3] - b1[1])
    a2 = max(0.0, b2[2] - b2[0]) * max(0.0, b2[3] - b2[1])
    union = a1 + a2 - inter
    if union <= 0.0:
        return 0.0
    return float(inter / union)


def match_predictions_to_ground_truth(
    ground_truths: Sequence[dict[str, Any]],
    predictions: Sequence[tuple[int, Sequence[float]]],
    iou_threshold: float = 0.4,
) -> tuple[set[int], set[int]]:
    """Class-aware one-to-one greedy matching between ground truths and predictions."""
    candidates: list[tuple[float, int, int]] = []
    for gt_idx, gt in enumerate(ground_truths):
        gt_cat = int(gt["category_id"])
        gbox = gt.get("bbox_xyxy")
        if gbox is None:
            bx, by, bw, bh = gt["bbox"]
            gbox = [bx, by, bx + bw, by + bh]
        for pred_idx, (pred_cat, pbox) in enumerate(predictions):
            if pred_cat != gt_cat:
                continue
            iou_val = iou(pbox, gbox)
            if iou_val >= iou_threshold:
                candidates.append((iou_val, gt_idx, pred_idx))

    candidates.sort(key=lambda item: (-item[0], item[1], item[2]))

    matched_gts: set[int] = set()
    matched_preds: set[int] = set()
    for _, gt_idx, pred_idx in candidates:
        if gt_idx not in matched_gts and pred_idx not in matched_preds:
            matched_gts.add(gt_idx)
            matched_preds.add(pred_idx)

    return matched_gts, matched_preds


def evaluate_detection_accuracy(
    model_cfg: dict[str, Any],
    val_data: dict[str, Any],
    images_base: Path,
    sample_count: int = 100,
    iou_threshold: float = 0.4,
) -> dict[str, Any]:
    """Benchmark class-aware 1-to-1 detection recall and CPU latency on validation frames."""
    manifest_p = Path(model_cfg["manifest"])
    model_p = Path(model_cfg["model"])
    if not manifest_p.is_file() or not model_p.is_file():
        return {"status": "unavailable", "reason": "model file not found"}

    images = val_data.get("images") or []
    if sample_count <= 0 or not images:
        return {"status": "failed", "reason": "no validation images configured", "frames_processed": 0}

    detector = CiviWatchDetector(manifest_p, model_p, strict_runtime=False)

    anns_by_img: dict[int, list[dict[str, Any]]] = {}
    for a in val_data.get("annotations", []):
        anns_by_img.setdefault(int(a["image_id"]), []).append(a)

    LABEL_MAP = {
        "two_wheeler": 1,
        "motorcycle": 1,
        "bicycle": 1,
        "car": 2,
        "bus": 3,
        "truck": 4,
    }

    sample_imgs = images[:: max(1, len(images) // sample_count)][:sample_count]
    gt_counts = {1: 0, 2: 0, 3: 0, 4: 0}
    tp_counts = {1: 0, 2: 0, 3: 0, 4: 0}
    pred_counts: dict[str, int] = {}
    latencies: list[float] = []
    night_gt = 0
    night_tp = 0

    for idx, info in enumerate(sample_imgs):
        img_p = images_base / info["file_name"]
        if not img_p.is_file():
            continue
        bgr = cv2.imread(str(img_p))
        if bgr is None:
            continue
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        is_dark = float(np.mean(rgb)) < 75.0
        frame = PerceptionExecution.frame("aic-bench", "s1", 1, "replay", idx, idx / 10.0)
        t0 = time.perf_counter()
        res = detector.detect(rgb, frame)
        det_status = res.get("detection_status")
        if det_status not in {"ok", "ok_empty"}:
            return {
                "status": "failed",
                "error": f"Detector failed on frame {idx}: status={det_status}, error={res.get('error')}",
                "frames_processed": len(latencies),
            }
        latencies.append((time.perf_counter() - t0) * 1000.0)

        preds: list[tuple[int, list[float]]] = []
        for d in res.get("detections", []):
            lbl = d["label"]
            pred_counts[lbl] = pred_counts.get(lbl, 0) + 1
            if lbl in LABEL_MAP:
                preds.append((LABEL_MAP[lbl], d["bbox_xyxy"]))

        img_gts = [
            g for g in anns_by_img.get(int(info["id"]), []) if int(g.get("category_id", -1)) in gt_counts
        ]
        for g in img_gts:
            cat = int(g["category_id"])
            gt_counts[cat] += 1
            if is_dark:
                night_gt += 1

        matched_gts, _ = match_predictions_to_ground_truth(img_gts, preds, iou_threshold=iou_threshold)
        for gt_idx in matched_gts:
            cat = int(img_gts[gt_idx]["category_id"])
            tp_counts[cat] += 1
            if is_dark:
                night_tp += 1

    if not latencies:
        return {
            "status": "failed",
            "reason": "no valid validation images processed",
            "frames_processed": 0,
        }

    tot_gt = sum(gt_counts.values())
    tot_tp = sum(tp_counts.values())
    return {
        "status": "completed",
        "frames_processed": len(latencies),
        "file_size_mb": round(model_p.stat().st_size / 1e6, 1),
        "overall_recall": round((tot_tp / max(1, tot_gt)) * 100.0, 1),
        "moto_recall": round((tp_counts[1] / max(1, gt_counts[1])) * 100.0, 1),
        "car_recall": round((tp_counts[2] / max(1, gt_counts[2])) * 100.0, 1),
        "bus_recall": round((tp_counts[3] / max(1, gt_counts[3])) * 100.0, 1),
        "truck_recall": round((tp_counts[4] / max(1, gt_counts[4])) * 100.0, 1),
        "night_recall": round((night_tp / max(1, night_gt)) * 100.0, 1) if night_gt else 0.0,
        "person_detections": pred_counts.get("person", 0),
        "latency_p50_ms": round(float(np.median(latencies)), 1),
        "latency_p95_ms": round(float(np.percentile(latencies, 95)), 1),
        "pred_counts": pred_counts,
    }


def evaluate_perception_pipeline_on_video(
    model_cfg: dict[str, Any],
    video_path: Path,
    max_frames: int = 100,
    sample_fps: float = 10.0,
) -> dict[str, Any]:
    """Benchmark PerceptionPipeline execution on a video clip.

    Exercises perception path (detector, tracker, homography, pose, incident engines)
    without claiming full edge ring recording, evidence packaging, or WAN upload.
    """
    unexercised = ["full_edge_recording", "evidence_packaging", "wan_outbox_upload"]
    manifest_p = Path(model_cfg["manifest"])
    model_p = Path(model_cfg["model"])
    if not manifest_p.is_file() or not model_p.is_file() or not Path(video_path).is_file():
        return {
            "status": "unavailable",
            "pipeline_type": "perception_pipeline",
            "unexercised_components": unexercised,
            "frames_processed": 0,
            "pipeline_fps": 0.0,
            "total_events": 0,
            "total_detections": 0,
        }

    def pipeline_factory(tmp_root: Path, vw: int, vh: int, native_fps: float) -> tuple[PerceptionPipeline, EventOutbox]:
        rec = FileRecorder(tmp_root / "ring", ring_seconds=120)
        outbox = EventOutbox(tmp_root / "events.sqlite3")
        hom = GroundPlaneHomography.default_urban_cctv(vw, vh, road_width_m=15.0, road_depth_m=45.0)
        vehicle_eng = VehicleIncidentEngine(
            homography=hom,
            min_moving_speed=15.0,
            impact_deceleration_threshold=120.0,
            enable_vlm=False,
        )
        person_eng = IncidentEngine()
        estimator = RtmposeEstimator(
            manifest_path=ROOT / "models/rtmpose-tiny/manifest.json",
            model_path=ROOT / "models/rtmpose-tiny/rtmpose_tiny.onnx",
        )
        pose_mgr = PoseManager(estimator=estimator, max_queue_size=30, max_cached_frames=30)
        scheduler = PoseScheduler(batch_budget=8)
        p = PerceptionPipeline(
            recorder=rec,
            outbox=outbox,
            manifest_path=manifest_p,
            model_path=model_p,
            incident_engines=[vehicle_eng, person_eng],
            pose_manager=pose_mgr,
            pose_scheduler=scheduler,
            origin="replay",
        )
        return p, outbox

    res = run_replay_session(
        video_path,
        pipeline_factory,
        sample_fps=sample_fps,
        max_frames=max_frames,
        fail_fast=False,
    )

    if res.status != "completed":
        return {
            "status": res.status,
            "error": res.error or "Replay session failed",
            "pipeline_type": "perception_pipeline",
            "unexercised_components": unexercised,
            "frames_processed": res.frames_processed,
            "total_detections": res.total_detections,
            "total_events": res.total_events,
            "pipeline_fps": 0.0,
        }

    actual_fps = round(len(res.latencies_ms) / max(0.001, res.elapsed_seconds), 1)
    persisted_outbox = len(res.outbox_events)

    return {
        "status": "completed",
        "pipeline_type": "perception_pipeline",
        "unexercised_components": unexercised,
        "frames_processed": len(res.latencies_ms),
        "total_detections": res.total_detections,
        "total_events": res.total_events,
        "persisted_outbox": persisted_outbox,
        "pipeline_fps": actual_fps,
        "pipeline_p50_ms": round(float(np.median(res.latencies_ms)), 1),
        "pipeline_p95_ms": round(float(np.percentile(res.latencies_ms, 95)), 1),
    }


def generate_markdown_report(results: list[dict[str, Any]]) -> str:
    """Render measured benchmark outcomes into a Markdown report without unmeasured claims."""
    report_lines = [
        "# Báo cáo Đo lường & So sánh Hiệu năng Model Nhận diện CiviWatch (Perception Pipeline)",
        "",
        f"**Thời điểm thực hiện:** {time.strftime('%Y-%m-%d %H:%M:%S')}  ",
        "**Môi trường đo kiểm:** CPU ONNXRuntime (Perception Pipeline replay)  ",
        "",
        "---",
        "",
        "## 1. Cấu hình Kỹ thuật các Model được Đánh giá",
        "",
        "| Model | Kiến trúc | Độ phân giải | Kích thước file | Định dạng đầu ra | Trạng thái |",
        "|---|:---:|:---:|:---:|:---:|:---:|",
    ]

    for r in results:
        cfg = r["model_config"]
        acc = r.get("accuracy", {})
        size_mb = acc.get("file_size_mb")
        size_str = f"{size_mb} MB" if size_mb is not None else "N/A"
        status_str = str(acc.get("status", "unknown"))
        arch = cfg["id"].split("_")[0].upper()
        report_lines.append(
            f"| **{cfg['name']}** | {arch} | {cfg['resolution']}×{cfg['resolution']} | {size_str} | `{cfg['decode']}` | `{status_str}` |"
        )

    report_lines.extend([
        "",
        "---",
        "",
        "## 2. Đo kiểm Recall (1-to-1 Class-Aware @ IoU>=0.4) & Độ trễ CPU",
        "",
        "| Model | Xe máy (`two_wheeler`) | Ô tô (`car`) | Xe buýt (`bus`) | Xe tải (`truck`) | **Tổng thể Recall@0.4** | **Ban đêm / Thiếu sáng** | Người (`person`) | Độ trễ CPU (P50) |",
        "|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|",
    ])

    def _pct(val: Any) -> str:
        return f"{val}%" if isinstance(val, (int, float)) else "N/A"

    for r in results:
        cfg = r["model_config"]
        acc = r.get("accuracy", {})
        if acc.get("status") == "completed":
            p50_str = f"**{acc['latency_p50_ms']} ms**" if acc.get("latency_p50_ms") is not None else "N/A"
            person_str = f"{acc.get('person_detections', 'N/A')} dets"
            report_lines.append(
                f"| **{cfg['name']}** | {_pct(acc.get('moto_recall'))} | {_pct(acc.get('car_recall'))} | "
                f"{_pct(acc.get('bus_recall'))} | {_pct(acc.get('truck_recall'))} | **{_pct(acc.get('overall_recall'))}** | "
                f"**{_pct(acc.get('night_recall'))}** | {person_str} | {p50_str} |"
            )
        else:
            report_lines.append(
                f"| **{cfg['name']}** | N/A | N/A | N/A | N/A | N/A | N/A | N/A | N/A ({acc.get('status', 'unavailable')}) |"
            )

    video_names: list[str] = []
    for r in results:
        for v_name in r.get("videos", {}):
            if v_name not in video_names:
                video_names.append(v_name)

    report_lines.extend([
        "",
        "---",
        "",
        "## 3. Đo kiểm Đường Nhận diện Edge (Perception Pipeline trên Video)",
        "",
        "Phạm vi đo: `PerceptionPipeline` (Detector $\\rightarrow$ ByteTrack $\\rightarrow$ Homography $\\rightarrow$ PoseManager $\\rightarrow$ Incident Engines). "
        "Lưu ý: Ghi hình ring đầy đủ, đóng gói evidence và đồng bộ WAN outbox **không** được thực thi trong bài đo này.",
        "",
    ])

    if video_names:
        header = "| Model | " + " | ".join(video_names) + " |"
        sep = "|---|" + "|".join([":---:"] * len(video_names)) + "|"
        report_lines.extend([header, sep])
        for r in results:
            cfg = r["model_config"]
            vids = r.get("videos", {})
            cells: list[str] = []
            for v_name in video_names:
                v_res = vids.get(v_name, {})
                if v_res.get("status") == "completed":
                    cells.append(
                        f"**{v_res.get('pipeline_fps')} FPS** / {v_res.get('total_detections')} dets / {v_res.get('total_events')} ev"
                    )
                else:
                    cells.append(f"`{v_res.get('status', 'N/A')}`")
            report_lines.append(f"| **{cfg['name']}** | " + " | ".join(cells) + " |")
    else:
        report_lines.append("_Không có video nào được cấu hình để đo kiểm._")

    report_lines.extend([
        "",
        "---",
        "",
        "## 4. Kết quả Đo được & Giới hạn Phạm vi",
        "",
    ])

    for r in results:
        cfg = r["model_config"]
        acc = r.get("accuracy", {})
        if acc.get("status") == "completed":
            report_lines.append(
                f"- **{cfg['name']}:** Overall Recall@0.4 = **{acc.get('overall_recall')}%** "
                f"(xe máy: {acc.get('moto_recall')}%, ban đêm: {acc.get('night_recall')}%), "
                f"độ trễ CPU P50 = **{acc.get('latency_p50_ms')} ms** (P95 = {acc.get('latency_p95_ms')} ms)."
            )
        else:
            reason = acc.get("reason") or acc.get("error") or "không khả dụng"
            report_lines.append(f"- **{cfg['name']}:** `{acc.get('status', 'unavailable')}` ({reason}).")

    report_lines.extend([
        "",
        "**Giới hạn chưa đo trong bài benchmark này:** mAP COCO, tốc độ suy luận GPU thực tế, ghi hình ring liên tục, đóng gói evidence, đồng bộ WAN và kiểm định bản quyền/phần cứng triển khai cần đánh giá riêng theo từng môi trường mục tiêu.",
    ])

    return "\n".join(report_lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample-count", type=int, default=100)
    parser.add_argument("--max-video-frames", type=int, default=100)
    parser.add_argument("--out-report", type=Path, default=ROOT / "docs/reports/2026-11-10-three-models-benchmark-comparison.md")
    args = parser.parse_args()

    print("=" * 72)
    print("   CIVIWATCH MULTI-MODEL DETECTION & PERCEPTION PIPELINE BENCHMARK")
    print("=" * 72)

    D = Path("/media/tieubaoca/HDD1/F/dataset/video/AIC_HCMC_2020")
    val_data = json.load(open(D / "aihcmcity2020_annotations/annotations/annotations_val.json"))
    images_base = D / "ai-hcm-city2020/images"

    test_videos = [
        ("sample_01.mp4 (HCMC Traffic 1)", Path("/media/tieubaoca/HDD1/F/dataset/video/AIC_HCMC_2020/sample_data/videos/sample_01.mp4")),
        ("sample_02.mp4 (HCMC Traffic 2)", Path("/media/tieubaoca/HDD1/F/dataset/video/AIC_HCMC_2020/sample_data/videos/sample_02.mp4")),
        ("shibuya_crossing_1080p.mp4 (Pedestrian/Veh)", ROOT / "data/benchmark/shibuya_crossing_1080p.mp4"),
        ("intersection_traffic_1080p.mp4 (Traffic 1080p)", ROOT / "data/benchmark/intersection_traffic_1080p.mp4"),
        ("fall_0001.mp4 (Person Fall)", ROOT / "data/benchmark/unidata/fall_0001.mp4"),
    ]

    results: list[dict[str, Any]] = []

    for m_cfg in MODELS_CONFIG:
        print(f"\n---> Evaluating: {m_cfg['name']} ({m_cfg['resolution']}x{m_cfg['resolution']}) ...")
        acc = evaluate_detection_accuracy(m_cfg, val_data, images_base, sample_count=args.sample_count)
        print(
            f"     Accuracy [{acc.get('status')}] -> Overall Recall: {acc.get('overall_recall')}% | "
            f"Moto: {acc.get('moto_recall')}% | Night: {acc.get('night_recall')}% | CPU P50: {acc.get('latency_p50_ms')} ms"
        )

        vid_results: dict[str, Any] = {}
        for v_name, v_path in test_videos:
            v_res = evaluate_perception_pipeline_on_video(m_cfg, v_path, max_frames=args.max_video_frames)
            vid_results[v_name] = v_res
            print(
                f"     Video [{v_res.get('status')}]: {v_name:<30s} -> {v_res.get('pipeline_fps')} FPS | "
                f"Detections: {v_res.get('total_detections')} | Incidents: {v_res.get('total_events')}"
            )

        results.append({
            "model_config": m_cfg,
            "accuracy": acc,
            "videos": vid_results,
        })

    report_text = generate_markdown_report(results)
    args.out_report.parent.mkdir(parents=True, exist_ok=True)
    args.out_report.write_text(report_text, encoding="utf-8")
    print(f"\n[REPORT] Saved comparative perception benchmark report to: {args.out_report}")


if __name__ == "__main__":
    main()
