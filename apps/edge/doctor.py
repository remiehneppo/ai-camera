"""File/ONNX CPU lab preflight and startup CLI, separate from server doctor."""
from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import shutil
import sys
import time
from typing import Any

from apps.edge.config import EdgeConfig


def preflight(config: EdgeConfig) -> dict[str, Any]:
    recorder_available = bool(shutil.which('ffmpeg') and shutil.which('ffprobe'))
    analytics: dict[str, Any] = {'status': 'disabled', 'reason': config.disabled_reason}
    if config.analytics_enabled:
        try:
            from apps.edge.oracle_detector import OracleDetector
            detector = OracleDetector(config.manifest_path, config.model_path)  # type: ignore[arg-type]
            analytics = {'status': 'available', 'provider': detector.session.get_providers()[0]}
        except Exception:
            analytics = {'status': 'unavailable', 'reason': 'enabled analytics artifact or runtime validation failed'}
    return dict(scope='preflight', status='ok' if recorder_available and analytics['status'] != 'unavailable' else 'error',
                config_hash=config.config_hash, capabilities={
                    'recorder': {'status': 'available' if recorder_available else 'unavailable'},
                    'analytics': analytics})


def run(config: EdgeConfig) -> int:
    from apps.edge.runtime import EdgeRuntime
    values = asdict(config)
    for field in ('source_type', 'backend'):
        values.pop(field)
    runtime = None
    consumed = 0
    previous = None
    try:
        runtime = EdgeRuntime(**values)
        runtime.start()
        while True:
            consumed += len(runtime.observations())
            status = runtime.status()
            current = (status['recorder']['state'], status['analytics']['state'], status['degraded'])
            if current != previous:
                print(json.dumps(dict(scope='runtime', config_hash=config.config_hash, runtime=status,
                                      observations_consumed=consumed), sort_keys=True), flush=True)
                previous = current
            if status['outcome'] != 'running':
                break
            time.sleep(.01)
        consumed += len(runtime.observations())
        status = runtime.wait()
    except KeyboardInterrupt:
        if runtime is None:
            return 130
        status = runtime.stop()
    except Exception as error:
        if runtime is not None:
            runtime.stop()
        print(json.dumps(dict(scope='runtime', status='error', config_hash=config.config_hash,
                              reason='edge runtime execution failed', error_type=type(error).__name__)), flush=True)
        return 1
    print(json.dumps(dict(scope='runtime', config_hash=config.config_hash, runtime=status,
                          observations_consumed=consumed), sort_keys=True), flush=True)
    return 0 if status['outcome'] == 'ok' else 1


def main(argv: list[str] | None = None) -> int:
    from apps.edge.config import load_edge_config
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True, help='JSON file with explicit local source and output_dir')
    parser.add_argument('--start', action='store_true', help='run independent recorder and detector-only lab replay')
    args = parser.parse_args(argv)
    try:
        config = load_edge_config(json.loads(Path(args.config).read_text()))
    except (OSError, UnicodeError, ValueError, TypeError):
        print(json.dumps({'scope': 'preflight', 'status': 'error', 'reason': 'invalid edge configuration'}))
        return 1
    report = preflight(config)
    print(json.dumps(report, sort_keys=True), flush=True)
    if report['status'] != 'ok':
        return 1
    return run(config) if args.start else 0


if __name__ == '__main__':
    sys.exit(main())
