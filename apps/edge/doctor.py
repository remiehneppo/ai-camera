"""File/ONNX CPU lab preflight and startup CLI, separate from server doctor."""
from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import shutil
import sys
import time
from typing import Any, Iterable

from apps.edge.config import EdgeConfig
from domain.alert_module_config import (
    AlertModuleDefinition,
    AlertModuleRegistry,
    ConfigError,
)


_SQLITE_FIXED = {(3, 44): (3, 44, 6), (3, 50): (3, 50, 7)}


def sqlite_wal_reset_check(version: str | None = None) -> dict[str, Any]:
    """Warn-only check for the SQLite WAL-reset race (fixed in 3.51.3; backports 3.44.6, 3.50.7).

    A distro may backport the fix without changing the version string, so 'unpatched' means unverified.
    """
    import sqlite3
    version = version or sqlite3.sqlite_version
    parts = tuple(int(p) for p in version.split('.')[:3])
    fixed = parts >= (3, 51, 3) or parts >= _SQLITE_FIXED.get(parts[:2], (99,))
    result: dict[str, Any] = {'status': 'ok' if fixed else 'warning', 'version': version}
    if not fixed:
        result['reason'] = 'sqlite version predates WAL-reset race fix (3.51.3, backports 3.44.6/3.50.7); verify distro backport or upgrade'
    return result


_MODULE_DOCUMENT_FIELDS = {'module', 'config_version', 'required_fields', 'thresholds', 'cameras'}


def _document_error(message: str, **context: Any) -> ConfigError:
    return ConfigError('invalid_module_config_document', message, **context)


def load_module_registry(path: str | Path) -> AlertModuleRegistry:
    """Parse one operator module x camera document, failing fast on the first bad config."""
    try:
        document = json.loads(Path(path).read_text())
    except (OSError, UnicodeError, ValueError):
        raise _document_error('module configuration document is not readable JSON') from None
    if not isinstance(document, dict) or set(document) != {'modules'} or not isinstance(document['modules'], list):
        raise _document_error('module configuration document must be an object with a modules list')
    registry = AlertModuleRegistry()
    for entry in document['modules']:
        if not isinstance(entry, dict) or set(entry) - _MODULE_DOCUMENT_FIELDS:
            raise _document_error('each module entry may only define module/config_version/required_fields/thresholds/cameras')
        for key in ('module', 'config_version'):
            if key not in entry:
                raise _document_error('each module entry needs ' + key)
        cameras = entry.get('cameras') or {}
        if not isinstance(cameras, dict):
            raise _document_error('cameras must map camera_id to configuration', module=entry['module'])
        definition = AlertModuleDefinition(
            module=entry['module'],
            config_version=entry['config_version'],
            required_fields=frozenset(entry.get('required_fields') or ()),
            thresholds=frozenset(entry.get('thresholds') or ()),
        )
        registry.register(definition)
        for camera_id, payload in cameras.items():
            registry.stage(registry.parse(definition.module, camera_id, payload))
    return registry


def module_capabilities(paths: Iterable[str | Path]) -> dict[str, Any]:
    """Doctor view of configured modules; only documents that were supplied are reported."""
    report: dict[str, Any] = {'status': 'not_configured', 'documents': []}
    for path in paths:
        try:
            capabilities = load_module_registry(path).capabilities()
        except ConfigError as error:
            report['status'] = 'error'
            report['reason'] = 'invalid module configuration'
            report.setdefault('errors', []).append({**error.describe(), 'document': str(path)})
            continue
        report['documents'].append({'document': str(path), **capabilities})
        if report['status'] == 'not_configured':
            report['status'] = 'ok'
    return report


def preflight(config: EdgeConfig, module_configs: Iterable[str | Path] = ()) -> dict[str, Any]:
    recorder_available = bool(shutil.which('ffmpeg') and shutil.which('ffprobe'))
    analytics: dict[str, Any] = {'status': 'disabled', 'reason': config.disabled_reason}
    if config.analytics_enabled:
        try:
            from apps.edge.oracle_detector import OracleDetector
            detector = OracleDetector(config.manifest_path, config.model_path)  # type: ignore[arg-type]
            analytics = {'status': 'available', 'provider': detector.session.get_providers()[0]}
        except Exception:
            analytics = {'status': 'unavailable', 'reason': 'enabled analytics artifact or runtime validation failed'}
    sqlite = sqlite_wal_reset_check()
    if sqlite['status'] != 'ok':
        print(f"warning: {sqlite['reason']} (running {sqlite['version']})", file=sys.stderr, flush=True)
    modules = module_capabilities(module_configs)
    ok = recorder_available and analytics['status'] != 'unavailable' and modules['status'] != 'error'
    return dict(scope='preflight', status='ok' if ok else 'error',
                config_hash=config.config_hash, capabilities={
                    'sqlite': sqlite,
                    'recorder': {'status': 'available' if recorder_available else 'unavailable'},
                    'analytics': analytics,
                    'modules': modules})


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
    parser.add_argument('--module-config', action='append', default=[],
                        help='JSON document of independent module x camera configuration; may repeat')
    args = parser.parse_args(argv)
    try:
        config = load_edge_config(json.loads(Path(args.config).read_text()))
    except (OSError, UnicodeError, ValueError, TypeError):
        print(json.dumps({'scope': 'preflight', 'status': 'error', 'reason': 'invalid edge configuration'}))
        return 1
    report = preflight(config, args.module_config)
    print(json.dumps(report, sort_keys=True), flush=True)
    if report['status'] != 'ok':
        return 1
    return run(config) if args.start else 0


if __name__ == '__main__':
    sys.exit(main())
