"""Immutable file/ONNX CPU lab configuration; no production capability claims."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any, Mapping


@dataclass(frozen=True)
class EdgeConfig:
    source: str
    output_dir: str
    source_type: str = 'file'
    backend: str = 'onnx_cpu'
    camera_id: str = 'lab-camera'
    session_id: str = 'lab-replay'
    analytics_enabled: bool = True
    disabled_reason: str | None = None
    manifest_path: str | None = None
    model_path: str | None = None
    sample_fps: float = 2.0
    mode: str = 'fast'
    segment_seconds: float = 2.0
    ring_seconds: float = 600.0
    queue_capacity: int = 8
    observation_capacity: int = 64
    stop_timeout_seconds: float = 3.0
    io_timeout_seconds: float = 30.0

    def __post_init__(self) -> None:
        if self.source_type != 'file' or self.backend != 'onnx_cpu':
            raise ValueError('only file source and onnx_cpu backend are supported')
        for name in ('source', 'output_dir'):
            value = getattr(self, name)
            if not isinstance(value, str) or not value or '://' in value:
                raise ValueError('source and output_dir must be local paths')
        if not Path(self.source).is_file():
            raise ValueError('source file is unavailable')
        if type(self.analytics_enabled) is not bool:
            raise ValueError('analytics_enabled must be boolean')
        for name in ('camera_id', 'session_id'):
            value = getattr(self, name)
            if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_-]+', value):
                raise ValueError('camera_id and session_id must be safe identifiers')
        if self.mode != 'fast':
            raise ValueError('edge runtime supports fast replay only')
        for name in ('sample_fps', 'segment_seconds', 'ring_seconds', 'stop_timeout_seconds', 'io_timeout_seconds'):
            value = getattr(self, name)
            if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
                raise ValueError('lab timing values must be finite and positive')
        for name in ('queue_capacity', 'observation_capacity'):
            value = getattr(self, name)
            if type(value) is not int or value <= 0:
                raise ValueError('lab capacities must be positive integers')
        for value in (self.manifest_path, self.model_path):
            if value is not None and (not isinstance(value, str) or not value or '://' in value):
                raise ValueError('manifest and model paths must be local paths')
        if self.analytics_enabled:
            if self.disabled_reason is not None:
                raise ValueError('enabled analytics cannot have a disabled reason')
            for value in (self.manifest_path, self.model_path):
                if not isinstance(value, str) or not value or '://' in value:
                    raise ValueError('enabled analytics requires local manifest and model paths')
        elif not isinstance(self.disabled_reason, str) or not self.disabled_reason.strip():
            raise ValueError('disabled analytics requires a reason')

    @property
    def config_hash(self) -> str:
        return hashlib.sha256(json.dumps(asdict(self), sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def load_edge_config(values: Mapping[str, Any]) -> EdgeConfig:
    if not isinstance(values, Mapping) or set(values) - set(EdgeConfig.__dataclass_fields__):
        raise ValueError('unknown configuration field')
    fields = dict(values)
    if not {'source', 'output_dir'} <= fields.keys():
        raise ValueError('source and output_dir are required')
    if fields.get('analytics_enabled') is False and not fields.get('disabled_reason'):
        fields['disabled_reason'] = 'analytics disabled by configuration'
    return EdgeConfig(**fields)
