"""File/ONNX CPU lab preflight and startup CLI, separate from server doctor."""
from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import shutil
import sys
import time
from typing import Any, Iterable, NamedTuple

from apps.edge.config import EdgeConfig
from domain.alert_module_config import (
    AlertModuleDefinition,
    AlertModuleRegistry,
    CameraModuleConfig,
    ConfigError,
)


_SQLITE_FIXED: dict[tuple[int, int], tuple[int, int, int]] = {(3, 44): (3, 44, 6), (3, 50): (3, 50, 7)}


def sqlite_wal_reset_check(version: str | None = None) -> dict[str, Any]:
    """Warn-only check for the SQLite WAL-reset race (fixed in 3.51.3; backports 3.44.6, 3.50.7).

    A distro may backport the fix without changing the version string, so 'unpatched' means unverified.
    """
    import sqlite3
    version = version or sqlite3.sqlite_version
    numbers = [int(part) for part in version.split('.')[:3]]
    while len(numbers) < 3:
        numbers.append(0)
    parts: tuple[int, int, int] = (numbers[0], numbers[1], numbers[2])
    fixed = parts >= (3, 51, 3) or parts >= _SQLITE_FIXED.get((parts[0], parts[1]), (99, 99, 99))
    result: dict[str, Any] = {'status': 'ok' if fixed else 'warning', 'version': version}
    if not fixed:
        result['reason'] = 'sqlite version predates WAL-reset race fix (3.51.3, backports 3.44.6/3.50.7); verify distro backport or upgrade'
    return result


_DOCUMENT_FIELDS = frozenset({'modules', 'session'})
_MODULE_ENTRY_FIELDS = frozenset(
    {'module', 'config_version', 'factory', 'required_fields', 'thresholds', 'perception_profile', 'cameras'}
)


class LoadedModuleConfig(NamedTuple):
    """Registry built from operator documents, plus the session they activate under."""

    registry: AlertModuleRegistry
    session: str | None
    documents: tuple[str, ...]


def _document_error(message: str, **context: Any) -> ConfigError:
    return ConfigError('invalid_module_config_document', message, **context)


def _as_paths(paths: str | Path | Iterable[str | Path] | None) -> list[str | Path]:
    if paths is None:
        return []
    if isinstance(paths, (str, Path)):
        return [paths]
    return list(paths)


def _name_set(entry: dict[str, Any], key: str) -> frozenset[str]:
    value = entry.get(key)
    if value is None:
        return frozenset()
    module = str(entry.get('module'))
    if isinstance(value, (str, bytes)) or not isinstance(value, (list, tuple, set, frozenset)):
        raise _document_error(key + ' must be a list of names, not a single value', module=module)
    if not all(isinstance(item, str) for item in value):
        raise _document_error(key + ' must be a list of names', module=module)
    return frozenset(value)


def load_module_registry(
    paths: str | Path | Iterable[str | Path] | None,
) -> LoadedModuleConfig:
    """Parse operator module x camera documents, failing fast on the first bad config."""
    registry = AlertModuleRegistry()
    session: str | None = None
    documents: list[str] = []
    staged: list[CameraModuleConfig] = []
    for path in _as_paths(paths):
        try:
            document = json.loads(Path(path).read_text())
        except (OSError, UnicodeError, ValueError):
            raise _document_error('module configuration document is not readable JSON') from None
        if not isinstance(document, dict) or set(document) - _DOCUMENT_FIELDS or not isinstance(document.get('modules'), list):
            raise _document_error('module configuration document must be an object with a modules list and an optional session')
        declared = document.get('session')
        if declared is not None:
            if not isinstance(declared, str) or not declared.strip():
                raise _document_error('session must be a non-empty string')
            if session is not None and session != declared:
                raise _document_error('documents declare conflicting sessions')
            session = declared
        for entry in document['modules']:
            if not isinstance(entry, dict) or set(entry) - _MODULE_ENTRY_FIELDS:
                raise _document_error(
                    'each module entry may only define module/config_version/factory/'
                    'required_fields/thresholds/perception_profile/cameras'
                )
            for key in ('module', 'config_version', 'factory'):
                if key not in entry:
                    raise _document_error('each module entry needs ' + key)
            if 'cameras' in entry and not isinstance(entry['cameras'], dict):
                raise _document_error('cameras must map camera_id to configuration', module=str(entry['module']))
            definition = AlertModuleDefinition(
                module=entry['module'],
                config_version=entry['config_version'],
                factory=entry['factory'],
                required_fields=_name_set(entry, 'required_fields'),
                thresholds=_name_set(entry, 'thresholds'),
                perception_profile=entry.get('perception_profile'),
            )
            registry.register(definition)
            for camera_id, payload in (entry.get('cameras') or {}).items():
                config = registry.parse(definition.module, camera_id, payload)
                registry.stage(config)
                staged.append(config)
        documents.append(str(path))
    if session is not None:
        for config in staged:
            registry.activate(config, session_id=session)
    return LoadedModuleConfig(registry=registry, session=session, documents=tuple(documents))


def _camera_ids(capabilities: dict[str, Any]) -> list[str]:
    cameras = {camera['camera_id'] for module in capabilities['modules'] for camera in module['cameras']}
    return sorted(cameras)


def module_capabilities(paths: str | Path | Iterable[str | Path] | None) -> dict[str, Any]:
    """Doctor view of configured modules; only documents that were supplied are reported."""
    report: dict[str, Any] = {'status': 'not_configured', 'documents': []}
    for path in _as_paths(paths):
        try:
            loaded = load_module_registry([path])
        except ConfigError as error:
            report['status'] = 'error'
            report['reason'] = 'invalid module configuration'
            report.setdefault('errors', []).append({**error.describe(), 'document': str(path)})
            continue
        capabilities = loaded.registry.capabilities()
        entry: dict[str, Any] = {
            'document': str(path),
            **capabilities,
            'perception_groups': loaded.registry.perception_groups(),
        }
        if loaded.session is not None:
            entry['session'] = loaded.session
            entry['effective'] = {
                camera: loaded.registry.activation_for_camera(camera, loaded.session)
                for camera in _camera_ids(capabilities)
            }
        report['documents'].append(entry)
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


def run(config: EdgeConfig, loaded: LoadedModuleConfig | None = None) -> int:
    from apps.edge.runtime import EdgeRuntime
    values = asdict(config)
    for field in ('source_type', 'backend'):
        values.pop(field)
    if loaded is not None:
        values['module_registry'] = loaded.registry
        values['module_session'] = loaded.session
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
    if not args.start:
        return 0
    try:
        loaded = load_module_registry(args.module_config) if args.module_config else None
    except ConfigError:
        print(json.dumps({'scope': 'runtime', 'status': 'error', 'reason': 'invalid module configuration'}))
        return 1
    return run(config, loaded)


if __name__ == '__main__':
    sys.exit(main())
