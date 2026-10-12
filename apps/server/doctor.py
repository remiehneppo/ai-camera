"""Check lab server configuration and report reachable capabilities."""

from __future__ import annotations

import json
import sys

from apps.server.config import load_server_config


def main() -> int:
    try:
        config = load_server_config()
    except ValueError as exc:
        print(json.dumps({"status": "error", "reason": str(exc)}))
        return 1

    try:
        from pymongo import MongoClient
        from pymongo.errors import PyMongoError

        with MongoClient(config.mongo_uri, serverSelectionTimeoutMS=2000) as client:
            client.admin.command("ping")
    except ImportError:
        print(json.dumps({
            "status": "error",
            "config_hash": config.config_hash,
            "capabilities": {"server_api": "available", "mongo": "unavailable"},
            "reason": "MongoDB driver unavailable",
        }, sort_keys=True))
        return 1
    except PyMongoError:
        print(json.dumps({
            "status": "error",
            "config_hash": config.config_hash,
            "capabilities": {"server_api": "available", "mongo": "unavailable"},
            "reason": "database unavailable",
        }, sort_keys=True))
        return 1

    print(json.dumps({
        "status": "ok",
        "config_hash": config.config_hash,
        "capabilities": {
            "server_api": "available",
            "mongo": "reachable",
            "analytics": {"status": "disabled", "reason": "analytics runtime is not implemented"},
            "recorder": {"status": "unavailable", "reason": "recorder runtime is not implemented"},
        },
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
