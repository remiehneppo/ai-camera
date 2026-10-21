"""Versioned G2 quality-regression report for reviewed alerts and negative audits."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

if __package__ in (None, ""):  # run as `python tools/negative_audit_report.py`
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from domain.quality_eval import SamplingPlan, evaluate_quality_metrics

REPORT_VERSION = "g2-negative-audit-report-v1"
SCHEMA_VERSION = 1
_LIST_KEYS = ("records", "alerts", "negatives", "samples", "items", "data")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Evaluate stratified recall, FP rate and review load from reviewed alerts and "
            "negative audit samples, then emit a versioned G2 acceptance report."
        ),
        epilog=(
            "G2 never reports recall from alerts alone: with no reviewed negative sample the "
            "verdict is BLOCKED. Use --strict in CI to exit non-zero for FAIL/BLOCKED."
        ),
    )
    parser.add_argument("--alerts", required=True, help="JSON/JSONL file or directory of reviewed alert events")
    parser.add_argument("--negatives", default=None, help="JSON/JSONL file or directory of reviewed negative audit samples")
    parser.add_argument("--plan", default=None, help="Optional JSON sampling plan (strata and inclusion probabilities)")
    parser.add_argument("--capability", default="person_down", help="Capability under test (default: person_down)")
    parser.add_argument("--site", default=None, help="Site label recorded in the report")
    parser.add_argument("--output", "-o", default=None, help="Report file path (default: stdout)")
    parser.add_argument("--format", choices=("json", "markdown"), default=None, help="Report format (default: inferred or json)")
    parser.add_argument("--min-recall", type=float, default=0.90, help="Required recall target (default: 0.90)")
    parser.add_argument("--max-fp-per-day", type=float, default=2.0, help="Maximum FP per camera-day (default: 2.0)")
    parser.add_argument("--min-samples", type=int, default=None, help="Minimum reviewed negatives (default: plan or 30)")
    parser.add_argument(
        "--matching-window-seconds",
        type=float,
        default=None,
        help="Approved matching window to pin in the protocol block",
    )
    parser.add_argument("--generated-at", default=None, help="Override report timestamp (ISO-8601, for goldens)")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit 1 on FAIL and 2 on BLOCKED (default: exit 0 whenever a report is written)",
    )
    return parser


# ---- input loading ---------------------------------------------------------


def _records(payload: Any, origin: str) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        values = payload
    elif isinstance(payload, dict):
        nested = next((payload[key] for key in _LIST_KEYS if isinstance(payload.get(key), list)), None)
        values = nested if nested is not None else [payload]
    else:
        raise ValueError(f"{origin}: expected a JSON object, array, or JSONL records")
    for value in values:
        if not isinstance(value, dict):
            raise ValueError(f"{origin}: every reviewed record must be a JSON object")
    return values


def load_records(path: str | Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Load reviewed records from a JSON/JSONL file or a directory of them."""
    target = Path(path)
    if target.is_dir():
        files = sorted(
            child for child in target.iterdir() if child.is_file() and child.suffix in {".json", ".jsonl"} and child.name != "plan.json"
        )
        if not files:
            raise ValueError(f"{target}: no .json/.jsonl records found")
    elif target.is_file():
        files = [target]
    else:
        raise FileNotFoundError(f"input not found: {target}")

    records: list[dict[str, Any]] = []
    sources: list[dict[str, Any]] = []
    combined = hashlib.sha256()
    for file in files:
        raw = file.read_bytes()
        combined.update(raw)
        parsed = _parse_documents(raw, file)
        sources.append(
            {
                "path": str(file),
                "bytes": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest(),
                "records": len(parsed),
            }
        )
        records.extend(parsed)
    digest = combined.hexdigest() if len(files) > 1 else sources[0]["sha256"]
    return records, {"files": sources, "records": len(records), "sha256": digest}


def _parse_documents(raw: bytes, file: Path) -> list[dict[str, Any]]:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"{file}: not UTF-8 text") from exc
    stripped = text.strip()
    if not stripped:
        return []
    try:
        return _records(json.loads(stripped), str(file))
    except json.JSONDecodeError:
        records: list[dict[str, Any]] = []
        for number, line in enumerate(text.splitlines(), 1):
            line = line.strip()
            if not line:
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{file}:{number}: invalid JSON ({exc.msg})") from exc
            if not isinstance(value, dict):
                raise ValueError(f"{file}:{number}: every reviewed record must be a JSON object")
            records.append(value)
        return records


def load_plan(path: str | Path | None) -> SamplingPlan | None:
    if path is None:
        return None
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return SamplingPlan.from_dict(payload)


# ---- report ----------------------------------------------------------------


def _signoff_ticket(report: dict[str, Any]) -> dict[str, Any]:
    protocol = report["protocol"]
    return {
        "status": "pending",
        "required_fields": [
            "owner",
            "role",
            "signed_at",
            "verdict",
            "report_version",
            "plan_version",
            "thresholds",
            "residual_risk",
        ],
        "template": {
            "owner": "<name>",
            "role": "<product|ml|qa|operations>",
            "signed_at": "<ISO-8601 UTC>",
            "verdict": report["verdict"],
            "report_version": report["report_version"],
            "plan_version": protocol["plan_version"],
            "thresholds": {
                "min_recall": protocol["min_recall"],
                "max_fp_per_day": protocol["max_fp_per_day"],
                "confidence_level": protocol["confidence_level"],
                "min_samples": protocol["min_samples"],
            },
            "notes": "",
            "residual_risk": "",
        },
    }


def build_report(
    *,
    alerts: Sequence[dict[str, Any]],
    negatives: Sequence[dict[str, Any]] | None,
    plan: SamplingPlan | None,
    capability: str,
    site: str | None,
    min_recall: float,
    max_fp_per_day: float,
    min_samples: int | None,
    matching_window_seconds: float | None,
    generated_at: str,
    inputs: dict[str, Any],
) -> dict[str, Any]:
    metrics = evaluate_quality_metrics(
        alerts,
        negatives or [],
        plan=plan,
        capability=capability,
        min_recall=min_recall,
        max_fp_per_day=max_fp_per_day,
        min_samples=min_samples,
        site=site,
        matching_window_seconds=matching_window_seconds,
    )
    report = {
        "schema_version": SCHEMA_VERSION,
        "report_version": REPORT_VERSION,
        "generated_at": generated_at,
        "capability": metrics["capability"],
        "site": metrics["site"],
        "workload": metrics["workload"],
        "protocol": metrics["protocol"],
        "inputs": inputs,
        "counts": metrics["counts"],
        "recall": metrics["recall"],
        "branches": metrics["branches"],
        "false_positives": metrics["false_positives"],
        "review_load": metrics["review_load"],
        "coverage": metrics["coverage"],
        "sample_sufficiency": metrics["sample_sufficiency"],
        "verdict": metrics["verdict"],
        "verdict_reasons": metrics["verdict_reasons"],
        "blocking_gaps": metrics["blocking_gaps"],
    }
    report["owner_signoff"] = _signoff_ticket(report)
    return report


# ---- rendering -------------------------------------------------------------


def _percent(value: Any) -> str:
    return "n/a" if value is None else f"{value * 100:.2f}%"


def _decimal(value: Any, digits: int = 2) -> str:
    return "n/a" if value is None else f"{value:.{digits}f}"


def _interval(block: dict[str, Any]) -> str:
    if block.get("ci_low") is None or block.get("ci_high") is None:
        return "n/a"
    return f"{_percent(block['ci_low'])} – {_percent(block['ci_high'])}"


def render_markdown(report: dict[str, Any]) -> str:
    protocol = report["protocol"]
    recall = report["recall"]
    branches = report["branches"]
    counts = report["counts"]
    fp = report["false_positives"]
    load = report["review_load"]
    coverage = report["coverage"]
    sufficiency = report["sample_sufficiency"]
    reasons = ", ".join(report["verdict_reasons"]) or "none"
    lines = [
        f"# G2 quality report — {report['capability']}",
        "",
        f"- Report: `{report['report_version']}` (schema {report['schema_version']})",
        f"- Generated: {report['generated_at']}",
        f"- Site: {report['site'] or 'not specified'}",
        f"- Verdict: **{report['verdict']}** ({reasons})",
        "",
        "## Acceptance protocol",
        "",
        "| Field | Value |",
        "|---|---|",
        f"| Plan version | `{protocol['plan_version'] or 'not provided'}` |",
        f"| Plan sha256 | `{protocol['plan_sha256'] or 'n/a'}` |",
        f"| Recall target | {_percent(protocol['min_recall'])} |",
        f"| Max FP / camera-day | {_decimal(protocol['max_fp_per_day'])} |",
        f"| Confidence level | {_percent(protocol['confidence_level'])} |",
        f"| Min samples | {protocol['min_samples']} |",
        f"| Matching window | {protocol['matching_window_seconds'] if protocol['matching_window_seconds'] is not None else 'not pinned'} |",
        f"| Denominator | `{protocol['denominator_unit']}` |",
        f"| Recall estimator | `{protocol['recall_estimator']}` |",
        f"| Interval method | `{protocol['interval_method']}` |",
        "",
        "## Workload",
        "",
        f"- Cameras: {report['workload']['cameras']}",
        f"- Strata observed: {report['workload']['strata']}",
        f"- Estimated camera-hours: {_decimal(report['workload']['camera_hours_estimated'])}",
        f"- Reviewed negative hours (raw): {_decimal(report['workload']['reviewed_negative_hours_raw'])}",
        "",
        "## Alert and negative audit counts",
        "",
        "| Count | Value |",
        "|---|---|",
        f"| Alerts total | {counts['alerts_total']} |",
        f"| Alerts confirmed | {counts['alerts_confirmed']} |",
        f"| Alerts false positive | {counts['alerts_false_positive']} |",
        f"| Alerts unreviewed | {counts['alerts_unreviewed']} |",
        f"| Negative samples total | {counts['negative_samples_total']} |",
        f"| Negative samples reviewed | {counts['negative_samples_reviewed']} |",
        f"| Negative samples pending review | {counts['negative_samples_pending_review']} |",
        f"| Negative samples with missed events | {counts['negative_samples_with_missed_events']} |",
        "",
        "## Weighted recall",
        "",
        f"- Usable: {'yes' if recall['usable'] else 'no (no reviewed negative denominator)'}",
        f"- Estimate: {_percent(recall['estimate'])}",
        f"- 95% CI: {_interval(recall)}",
        f"- Effective sample size (Kish): {_decimal(recall['effective_sample_size'])}",
        f"- Weighted detected / total units: {_decimal(recall['weighted_detected_units'])} / {_decimal(recall['weighted_total_units'])}",
        "",
        "## Per-branch metrics",
        "",
        "| Branch | Recall | 95% CI | Effective n | Detected | Missed | FP |",
        "|---|---|---|---|---|---|---|",
    ]
    for name, block in branches.items():
        lines.append(
            f"| `{name}` | {_percent(block['estimate'])} | {_interval(block)} | "
            f"{_decimal(block['effective_sample_size'])} | {block['detected_units']} | "
            f"{block['missed_units']} | {block['false_positives']} |"
        )
    lines += [
        "",
        "## False positives",
        "",
        f"- Count: {fp['count']} (weighted {_decimal(fp['weighted_count'])})",
        f"- Per camera-hour: {_decimal(fp['per_camera_hour'])}",
        f"- Per camera-day: {_decimal(fp['per_camera_day'])}",
        f"- HT-estimated camera-hours: {_decimal(fp['camera_hours_estimated'])}",
        "",
        "## Review load",
        "",
        f"- Reviewed alerts: {load['reviewed_alerts']}",
        f"- Reviewed negatives: {load['reviewed_negatives']}",
        f"- Total review minutes: {_decimal(load['review_minutes_total'])}",
        f"- Minutes / alert: {_decimal(load['review_minutes_per_alert'])}",
        f"- Minutes / negative: {_decimal(load['review_minutes_per_negative'])}",
        f"- Minutes / camera-day: {_decimal(load['review_minutes_per_camera_day'])}",
        "",
        "## Sample sufficiency",
        "",
        f"- Sufficient: {'yes' if sufficiency['sufficient'] else 'no'}",
        f"- Reviewed negatives: {sufficiency['reviewed_negatives']}",
        f"- Effective negative samples: {_decimal(sufficiency['effective_negative_samples'])} "
        f"(minimum {sufficiency['min_samples']})",
        f"- Reasons: {', '.join(sufficiency['reasons']) or 'none'}",
        "",
        "## Coverage",
        "",
        "| Stratum | p_h | Samples | Reviewed samples | Alerts | Raw hours | Estimated hours |",
        "|---|---|---|---|---|---|---|",
    ]
    for stratum in coverage["strata"]:
        lines.append(
            f"| `{stratum['stratum_id']}` | {_decimal(stratum['inclusion_probability'], 4)} | "
            f"{stratum['samples']} | {stratum['reviewed_samples']} | {stratum['alerts']} | "
            f"{_decimal(stratum['raw_hours'])} | "
            f"{_decimal(stratum['estimated_hours'])} |"
        )
    lines += [
        "",
        f"- Missing strata: {', '.join(coverage['missing_strata']) or 'none'}",
        f"- Unplanned samples: {coverage['unplanned_samples']}",
        f"- Rights not cleared: {coverage['rights_not_cleared']}",
        f"- Missing inclusion probability: {coverage['missing_inclusion_probability']}",
        f"- Inclusion probability mismatch: {coverage['inclusion_probability_mismatch']}",
        f"- Missing duration samples: {coverage['missing_duration_samples']}",
        f"- Unreviewed alerts: {coverage['unreviewed_alerts']}",
        f"- Warnings: {', '.join(coverage['warnings']) or 'none'}",
        "",
        "## Owner sign-off",
        "",
        f"- Status: **{report['owner_signoff']['status']}**",
        "- [ ] Owner named and accountable for these thresholds",
        "- [ ] Report version, plan version and denominator reviewed",
        "- [ ] Verdict accepted with residual risk recorded",
        "",
        f"Template: `{json.dumps(report['owner_signoff']['template'], ensure_ascii=False, sort_keys=True)}`",
        "",
    ]
    return "\n".join(lines)


# ---- entry point -----------------------------------------------------------


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _resolve_format(requested: str | None, output: Path | None) -> str:
    if requested:
        return requested
    if output is not None and output.suffix.lower() in {".md", ".markdown"}:
        return "markdown"
    return "json"


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        alerts, alert_meta = load_records(args.alerts)
        negatives: list[dict[str, Any]] = []
        negative_meta: dict[str, Any] = {"files": [], "records": 0, "sha256": None}
        if args.negatives:
            negatives, negative_meta = load_records(args.negatives)
        plan = load_plan(args.plan)
        output = Path(args.output) if args.output else None
        report = build_report(
            alerts=alerts,
            negatives=negatives,
            plan=plan,
            capability=args.capability,
            site=args.site,
            min_recall=args.min_recall,
            max_fp_per_day=args.max_fp_per_day,
            min_samples=args.min_samples,
            matching_window_seconds=args.matching_window_seconds,
            generated_at=args.generated_at or _now(),
            inputs={
                "alerts": alert_meta,
                "negatives": negative_meta,
                "plan": None
                if plan is None
                else {"path": str(args.plan), "sha256": plan.content_hash(), "plan_version": plan.plan_version},
            },
        )
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    report_format = _resolve_format(args.format, output)
    rendered = (
        render_markdown(report)
        if report_format == "markdown"
        else json.dumps(report, ensure_ascii=False, allow_nan=False, indent=2) + "\n"
    )
    if output is None:
        sys.stdout.write(rendered)
    else:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8")
        print(f"wrote {output}", file=sys.stderr)

    if args.strict:
        if report["verdict"] == "BLOCKED":
            return 2
        if report["verdict"] == "FAIL":
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
