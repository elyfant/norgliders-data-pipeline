"""Load config/app.json, matching js/src/config.js's convention exactly --
same file, same path resolution (relative to this module, up to the repo
root, then into config/), same "load JSON + validate required fields with
one error per missing field" style. Deliberately not environment
variables: this repo already has an established config-file convention
(config/*.example.json committed as templates, config/*.json gitignored,
holding real values) and there's no reason for the Python side to invent
a different one.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_CONFIG_DIR = Path(__file__).resolve().parents[4] / "config"


def _load_json(filename: str) -> dict:
    path = _CONFIG_DIR / filename
    if not path.exists():
        raise FileNotFoundError(f"Missing configuration file: {path}")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _require(d: dict, key: str, context: str) -> Any:
    if key not in d or d[key] in (None, ""):
        raise ValueError(f"Configuration error: missing {context}.")
    return d[key]


def load_erddap_config() -> dict:
    app_config = _load_json("app.json")
    section = _require(app_config, "erddap", "erddap section in app.json")

    return {
        "gateway_url": _require(section, "gatewayUrl", "erddap.gatewayUrl"),
        "service_email": _require(section, "serviceEmail", "erddap.serviceEmail"),
        "service_password": _require(
            section, "servicePassword", "erddap.servicePassword"
        ),
        "sftp_host": _require(section, "sftpHost", "erddap.sftpHost"),
        "sftp_user": _require(section, "sftpUser", "erddap.sftpUser"),
        "sftp_key_path": _require(section, "sftpKeyPath", "erddap.sftpKeyPath"),
        "remote_base_path": section.get("remoteBasePath", "/data/ogdp/processed"),
    }
