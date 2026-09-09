"""Environment + facility configuration for the processing pipeline.

Precedence (highest first):
  1. environment variables (SLOCUM_DATA_ROOT, SLOCUM_CACHE_DIR, SLOCUM_COMPEXP,
     DATABASE_URL)
  2. ``config/processing.local.toml``  (gitignored, per-machine)
  3. ``config/processing.toml``        (committed default)

Usage::

    from slocum_data_processing.settings import load_settings
    s = load_settings()
    s.data_root, s.master_cache_dir, s.database_url, s.facility["institution"]
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_CONFIG_DIR = _REPO_ROOT / "config"
_BASE = _CONFIG_DIR / "processing.toml"
_LOCAL = _CONFIG_DIR / "processing.local.toml"


@dataclass(frozen=True)
class Settings:
    data_root: Path
    master_cache_dir: Path
    compexp: Path | None
    database_url: str
    facility: dict = field(repr=False)

    def mission_dir(self, mission: int | str) -> Path:
        """The data folder for a mission, resolved by ``<NNN>-*`` prefix under
        ``data_root``. Raises if not exactly one match."""
        token = f"{int(mission):03d}" if str(mission).isdigit() else str(mission)
        matches = sorted(p for p in self.data_root.glob(f"{token}*") if p.is_dir())
        if not matches:
            raise FileNotFoundError(
                f"no mission folder under {self.data_root} matching {token!r}"
            )
        if len(matches) > 1:
            raise ValueError(
                f"ambiguous mission {token!r}: {[m.name for m in matches]}"
            )
        return matches[0]


def _deep_merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


@lru_cache(maxsize=1)
def load_settings() -> Settings:
    if not _BASE.is_file():
        raise FileNotFoundError(f"missing {_BASE}")
    data = tomllib.loads(_BASE.read_text())
    if _LOCAL.is_file():
        data = _deep_merge(data, tomllib.loads(_LOCAL.read_text()))

    paths = data.get("paths", {})
    db = data.get("database", {})

    data_root = Path(os.environ.get("SLOCUM_DATA_ROOT", paths.get("data_root", "")))
    cache_dir = Path(os.environ.get("SLOCUM_CACHE_DIR", paths.get("master_cache_dir", "")))
    compexp_raw = os.environ.get("SLOCUM_COMPEXP", paths.get("compexp", "")) or ""
    database_url = os.environ.get("DATABASE_URL", db.get("url", ""))

    return Settings(
        data_root=data_root,
        master_cache_dir=cache_dir,
        compexp=Path(compexp_raw) if compexp_raw else None,
        database_url=database_url,
        facility=dict(data.get("facility", {})),
    )
