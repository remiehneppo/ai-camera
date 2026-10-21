"""CLI tool for exporting reviewed event dataset with lineage."""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Sequence

from apps.server.dataset import export_dataset_records, records_to_jsonl
from apps.server.store import EventStore


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Export reviewed dataset records with complete audit lineage.")
    parser.add_argument(
        "--mongo-uri",
        default=os.environ.get("MONGO_URI", "mongodb://192.168.96.2:27017/?replicaSet=rs0&directConnection=true"),
        help="MongoDB replica set connection URI",
    )
    parser.add_argument(
        "--database",
        default=os.environ.get("MONGO_DATABASE", "ai_camera"),
        help="MongoDB database name",
    )
    parser.add_argument(
        "--output",
        "-o",
        default=None,
        help="Output file path (default: stdout)",
    )
    parser.add_argument(
        "--split",
        choices=["train", "val", "test", "all"],
        default="all",
        help="Dataset split filter",
    )
    parser.add_argument(
        "--decision",
        choices=["confirmed", "false_positive", "resolved", "reopened", "all"],
        default="all",
        help="Review decision filter",
    )
    parser.add_argument(
        "--include-ambiguous",
        action="store_true",
        help="Include ambiguous or re-review pending records",
    )
    parser.add_argument(
        "--split-by",
        choices=["camera", "site_camera_time", "time"],
        default="camera",
        help="Partitioning key strategy for splitting",
    )
    parser.add_argument(
        "--format",
        choices=["jsonl", "json"],
        default="jsonl",
        help="Output export format (jsonl or json)",
    )
    parser.add_argument(
        "--taxonomy",
        default=None,
        help="Optional taxonomy filter (for example person_on_stationary_vehicle)",
    )
    parser.add_argument(
        "--severity",
        default=None,
        help="Optional severity filter (low, medium, high, critical)",
    )
    parser.add_argument(
        "--token",
        default=None,
        help="Optional authorization token for scoped export",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        store = EventStore(args.mongo_uri, args.database)
    except Exception as exc:
        sys.stderr.write(f"Failed to connect to EventStore: {exc}\n")
        return 1

    try:
        records = export_dataset_records(
            store=store,
            split=args.split,
            decision=args.decision,
            include_ambiguous=args.include_ambiguous,
            split_by=args.split_by,
            taxonomy=args.taxonomy,
            severity=args.severity,
        )

        if args.format == "jsonl":
            output_content = records_to_jsonl(records)
        else:
            output_content = json.dumps({"count": len(records), "records": records}, indent=2)

        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                f.write(output_content)
        else:
            sys.stdout.write(output_content)
            if not output_content.endswith("\n"):
                sys.stdout.write("\n")

        return 0
    finally:
        store.close()


if __name__ == "__main__":
    sys.exit(main())
