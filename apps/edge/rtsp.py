"""RTSP stream configuration and bounded probing with credential redaction.

The stream URL carries camera credentials, so it is kept out of ``repr``, out of
errors, and out of probe results. Callers that need to name the camera in a log
line use :func:`redact_rtsp_url` instead of the raw URL.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import math
import os
from pathlib import Path
import random
import subprocess
import threading
import time
from typing import Callable, Mapping
from urllib.parse import quote, unquote, urlsplit, urlunsplit

STREAM_URL_FIELD = "CAMERA_RTSP_URL"
DEFAULT_ENV_FILE = Path(__file__).resolve().parents[2] / ".env.local"
MAX_PROBE_TIMEOUT_SECONDS = 60.0

_RTSP_SCHEMES = frozenset({"rtsp", "rtsps"})
_REDACTED_URL = "<redacted rtsp url>"
_PROBE_OUTPUT_LIMIT = 300


@dataclass(frozen=True)
class CameraStreamConfig:
    """Validated camera stream target; ``stream_url`` is secret-bearing."""

    stream_url: str = field(repr=False)
    host: str
    port: int
    has_credentials: bool
    source: str

    @property
    def redacted_url(self) -> str:
        return redact_rtsp_url(self.stream_url)


def redact_rtsp_url(url: str) -> str:
    """Return ``url`` without userinfo so it is safe to log or raise.

    Anything that cannot be reduced to a readable RTSP target becomes a fixed
    placeholder, so a malformed credential-bearing value is never echoed.
    """
    try:
        parsed = urlsplit(url)
        netloc = parsed.netloc.rpartition("@")[2]
        if not netloc or not parsed.scheme:
            return _REDACTED_URL
        return urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, ""))
    except ValueError:
        return _REDACTED_URL


class RtspProbeError(RuntimeError):
    """Raised when a bounded ffprobe run yields no usable video stream metadata."""


class ExponentialBackoff:
    """Configurable exponential backoff with jitter and clock/sleeper injection."""

    def __init__(
        self,
        initial_delay: float = 1.0,
        max_delay: float = 30.0,
        backoff_factor: float = 2.0,
        jitter: float = 0.1,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] | None = None,
        random_fn: Callable[[], float] = random.random,
    ) -> None:
        self.initial_delay = float(initial_delay)
        self.max_delay = float(max_delay)
        self.backoff_factor = float(backoff_factor)
        self.jitter = float(jitter)
        self.clock = clock
        self.sleeper = sleeper
        self.random_fn = random_fn
        self.attempts: int = 0
        self.last_delay: float = 0.0

    def next_delay(self) -> float:
        try:
            base_delay = min(self.max_delay, self.initial_delay * (self.backoff_factor ** self.attempts))
        except OverflowError:
            # An outage long enough to overflow the float power is already far past the cap.
            base_delay = self.max_delay
        jitter_amount = base_delay * self.jitter * (2.0 * self.random_fn() - 1.0)
        delay = max(0.0, min(self.max_delay, base_delay + jitter_amount))
        self.last_delay = delay
        if base_delay < self.max_delay:
            # Once capped, stop counting so `attempts` stays bounded during multi-day outages.
            self.attempts += 1
        return delay

    def wait(self, stop_event: threading.Event | None = None) -> float:
        delay = self.next_delay()
        if self.sleeper is not None:
            self.sleeper(delay)
        elif stop_event is not None:
            stop_event.wait(delay)
        else:
            time.sleep(delay)
        return delay

    def reset(self) -> None:
        self.attempts = 0
        self.last_delay = 0.0


@dataclass(frozen=True)
class StreamProbeResult:
    """Codec and geometry of the probed video stream, without the source URL."""

    codec: str
    width: int
    height: int
    fps: float

    @property
    def resolution(self) -> str:
        return f"{self.width}x{self.height}"


def probe_rtsp_stream(url: str, timeout_seconds: float = 10.0) -> StreamProbeResult:
    """Probe one RTSP stream with ffprobe under a hard timeout.

    Both the ffprobe RTSP socket timeout and the subprocess wait are bounded by
    ``timeout_seconds``. Every failure is reported as :class:`RtspProbeError`
    carrying the redacted URL and sanitized probe output, never credentials.
    """
    bounded_timeout = _validate_probe_timeout(timeout_seconds)
    config = _validate_stream_url(url.strip(), "caller")
    command = _probe_command(config.stream_url, bounded_timeout)
    try:
        completed = subprocess.run(
            command, check=True, capture_output=True, text=True, timeout=bounded_timeout
        )
    except subprocess.TimeoutExpired:
        raise RtspProbeError(
            f"ffprobe timed out after {bounded_timeout:g}s for {config.redacted_url}"
        ) from None
    except subprocess.CalledProcessError as error:
        detail = sanitize_probe_output(f"{error.stderr or ''} {error.stdout or ''}".strip(), config.stream_url)
        raise RtspProbeError(
            f"ffprobe exited with {error.returncode} for {config.redacted_url}"
            + (f": {detail}" if detail else "")
        ) from None
    except OSError:
        raise RtspProbeError("ffprobe is unavailable; install FFmpeg to probe an RTSP stream") from None
    return _parse_probe_output(completed.stdout, config.stream_url)


def sanitize_probe_output(text: str, url: str) -> str:
    """Remove credential material from subprocess output before it is reported."""
    if not text:
        return ""
    sanitized = text.replace(url, redact_rtsp_url(url))
    for secret in _credential_forms(url):
        sanitized = sanitized.replace(secret, "***")
    return " ".join(sanitized.split())[:_PROBE_OUTPUT_LIMIT]


def _credential_forms(url: str) -> tuple[str, ...]:
    forms: list[str] = []
    try:
        parsed = urlsplit(url)
    except ValueError:
        return ()
    userinfo = parsed.netloc.rpartition("@")[0]
    if not userinfo:
        return ()
    forms.append(userinfo)
    if parsed.username:
        forms.append(parsed.username)
    if parsed.password:
        forms.append(parsed.password)
    for piece in list(forms):
        forms.append(unquote(piece))
        forms.append(quote(piece, safe=""))
    return tuple(sorted({piece for piece in forms if piece}, key=len, reverse=True))


def _validate_probe_timeout(timeout_seconds: float) -> float:
    try:
        value = float(timeout_seconds)
    except (TypeError, ValueError):
        raise ValueError("timeout_seconds must be a number of seconds") from None
    if not math.isfinite(value) or value <= 0 or value > MAX_PROBE_TIMEOUT_SECONDS:
        raise ValueError(
            f"timeout_seconds must be greater than 0 and at most {MAX_PROBE_TIMEOUT_SECONDS:g}"
        )
    return value


def _probe_command(url: str, timeout_seconds: float) -> list[str]:
    return [
        "ffprobe", "-v", "error",
        "-rtsp_transport", "tcp",
        "-timeout", str(round(timeout_seconds * 1_000_000)),
        "-select_streams", "v:0",
        "-show_entries", "stream=codec_name,width,height,avg_frame_rate,r_frame_rate",
        "-of", "json",
        url,
    ]


def _parse_probe_output(stdout: str, url: str) -> StreamProbeResult:
    try:
        stream = json.loads(stdout or "")["streams"][0]
        codec = str(stream["codec_name"])
        width = int(stream["width"])
        height = int(stream["height"])
        fps = _parse_frame_rate(stream.get("avg_frame_rate")) or _parse_frame_rate(stream.get("r_frame_rate"))
    except (ValueError, TypeError, KeyError, IndexError, AttributeError):
        raise RtspProbeError(
            f"ffprobe returned no usable video stream metadata for {redact_rtsp_url(url)}"
        ) from None
    if not codec or width <= 0 or height <= 0 or not fps:
        raise RtspProbeError(
            f"ffprobe returned no usable video stream metadata for {redact_rtsp_url(url)}"
        ) from None
    return StreamProbeResult(codec=codec, width=width, height=height, fps=fps)


def _parse_frame_rate(value: object) -> float | None:
    if not isinstance(value, str) or not value:
        return None
    numerator, _, denominator = value.partition("/")
    try:
        top = float(numerator)
        bottom = float(denominator) if denominator else 1.0
    except ValueError:
        return None
    if not math.isfinite(top) or not math.isfinite(bottom) or top <= 0 or bottom <= 0:
        return None
    return top / bottom


def load_rtsp_config(
    environ: Mapping[str, str] | None = None, env_file: Path | None = None
) -> CameraStreamConfig:
    """Read and validate ``CAMERA_RTSP_URL`` from the environment or ``.env.local``.

    The process environment wins over the file. Errors name the field only and
    never echo the submitted value.
    """
    process_values = os.environ if environ is None else environ
    file_values = _read_env_file(DEFAULT_ENV_FILE if env_file is None else env_file)
    for values, source in ((process_values, "environment"), (file_values, "env_file")):
        candidate = values.get(STREAM_URL_FIELD, "")
        if candidate.strip():
            return _validate_stream_url(candidate.strip(), source)
    raise ValueError(
        f"{STREAM_URL_FIELD} is required; set it in the environment or {DEFAULT_ENV_FILE.name}"
    )


def _read_env_file(env_file: Path) -> dict[str, str]:
    try:
        text = env_file.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    except OSError:
        raise ValueError(f"{STREAM_URL_FIELD} could not be read from {env_file.name}") from None

    values: dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        key, separator, raw_value = stripped.partition("=")
        if not separator:
            continue
        values[key.strip()] = _unquote(raw_value.strip())
    return values


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value


def _validate_stream_url(value: str, source: str) -> CameraStreamConfig:
    if not value:
        raise ValueError(f"{STREAM_URL_FIELD} must not be empty")
    if any(character in value for character in "<>") or any(character.isspace() for character in value):
        raise ValueError(f"{STREAM_URL_FIELD} must not be a placeholder or contain whitespace")
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        raise ValueError(f"{STREAM_URL_FIELD} must be a valid RTSP URL") from None
    if parsed.scheme.lower() not in _RTSP_SCHEMES:
        raise ValueError(f"{STREAM_URL_FIELD} must use the rtsp:// or rtsps:// scheme")
    if not parsed.hostname:
        raise ValueError(f"{STREAM_URL_FIELD} must include a camera host")
    if parsed.fragment:
        raise ValueError(f"{STREAM_URL_FIELD} must not include a URL fragment")
    return CameraStreamConfig(
        stream_url=value,
        host=parsed.hostname,
        port=554 if port is None else port,
        has_credentials=parsed.username is not None,
        source=source,
    )
