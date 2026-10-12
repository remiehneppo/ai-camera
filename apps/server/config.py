"""Validated server configuration without exposing secret values."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from types import MappingProxyType
from typing import Mapping
from urllib.parse import parse_qsl, urlsplit


@dataclass(frozen=True)
class ServerConfig:
    device_tokens: Mapping[str, str]
    reviewer_tokens: Mapping[str, str]
    dashboard_token: str
    mongo_uri: str
    mongo_database: str
    config_hash: str


def load_server_config(environ: Mapping[str, str] | None = None) -> ServerConfig:
    values = os.environ if environ is None else environ
    try:
        token_json = values["DEVICE_TOKENS"]
        dashboard_token = values["DASHBOARD_TOKEN"]
        mongo_uri = values["MONGO_URI"]
    except KeyError as exc:
        raise ValueError(f"{exc.args[0]} is required") from None

    try:
        device_tokens = json.loads(token_json)
    except (json.JSONDecodeError, TypeError):
        raise ValueError("DEVICE_TOKENS must be a JSON object") from None
    if not isinstance(device_tokens, dict) or not device_tokens or any(
        not isinstance(token, str) or not token or not isinstance(device, str) or not device
        for token, device in device_tokens.items()
    ):
        raise ValueError("DEVICE_TOKENS must map non-empty bearer tokens to device IDs")
    try:
        reviewer_tokens = json.loads(values.get("REVIEWER_TOKENS", "") or "{}")
    except (json.JSONDecodeError, TypeError):
        raise ValueError("REVIEWER_TOKENS must be a JSON object") from None
    if not isinstance(reviewer_tokens, dict) or any(
        not isinstance(reviewer, str) or not reviewer or len(reviewer) > 128
        or not isinstance(token, str) or not token or token == dashboard_token or token in device_tokens
        for reviewer, token in reviewer_tokens.items()
    ) or len(set(reviewer_tokens.values())) != len(reviewer_tokens):
        raise ValueError("REVIEWER_TOKENS must map unique reviewer IDs to unique bearer tokens")
    if not dashboard_token:
        raise ValueError("DASHBOARD_TOKEN must not be empty")

    try:
        parsed = urlsplit(mongo_uri)
        if parsed.scheme not in {"mongodb", "mongodb+srv"} or not parsed.hostname or parsed.fragment:
            raise ValueError
        mongo_target = {
            "scheme": parsed.scheme,
            "host": parsed.hostname.lower(),
            "port": parsed.port,
            "database_path": parsed.path,
            "options": sorted(
                (key, value)
                for key, value in parse_qsl(parsed.query)
                if key.lower() in {
                    "connecttimeoutms", "directconnection", "journal", "readpreference",
                    "replicaset", "retrywrites", "serverselectiontimeoutms", "tls", "w",
                }
            ),
        }
    except (ValueError, TypeError):
        raise ValueError("MONGO_URI must be a valid MongoDB URI") from None

    mongo_database = values.get("MONGO_DATABASE", "camera_lab")
    if not mongo_database:
        raise ValueError("MONGO_DATABASE must not be empty")
    public_config = {
        "mongo_target": mongo_target,
        "mongo_database": mongo_database,
        "device_ids": sorted(device_tokens.values()),
        "reviewer_ids": sorted(reviewer_tokens),
        "dashboard_token_configured": True,
    }
    config_hash = hashlib.sha256(
        json.dumps(public_config, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return ServerConfig(
        device_tokens=MappingProxyType(device_tokens),
        reviewer_tokens=MappingProxyType(reviewer_tokens),
        dashboard_token=dashboard_token,
        mongo_uri=mongo_uri,
        mongo_database=mongo_database,
        config_hash=config_hash,
    )
