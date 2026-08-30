"""Resolve the processing configuration for a mission.

Model (see the planning repo, decisions/ + dependencies.md): OGDB is the
system of record for mission / glider / sensor / calibration metadata. The
pyglider ``deployment.yml`` is a *generate-then-edit* artifact — rendered
from OGDB, then edited by the processing scientist for the things OGDB does
not model (QC narrative, pyglider run knobs, free-text prose) and committed
next to the mission. Regeneration later is opt-in with a diff, never a
silent overwrite of the edited file.

Today only the consumer half exists:

* :func:`load` — read a committed mission directory (``deployment.yml`` +
  ``sensors.txt``) and return a :class:`DeploymentConfig`.
* :func:`resolve` — the OGDB-backed generator. Stub: raises with a pointer
  to the field-map until OGDB has a mission-metadata read path. When built,
  ``resolve(2)`` must reproduce the committed mission 002 ``deployment.yml``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

# Repo layout: python/src/slocum_data_processing/processing/config.py
#           -> python/missions/<NNN-name>/
_MISSIONS_DIR = Path(__file__).resolve().parents[3] / "missions"


@dataclass
class DeploymentConfig:
    """Everything the processing core needs for one mission run."""

    mission_dir: Path
    deployment_yaml: Path
    sensor_list: Path
    deployment: dict = field(repr=False)  # full parsed deployment.yml

    scisuffix: str = "ebd"
    glidersuffix: str = "dbd"
    profile_filt_time: float = 100.0
    profile_min_time: float = 100.0
    grid_dz: float = 1.0
    l0_time_range: tuple[str, str] | None = None
    l1_time_range: tuple[str, str] | None = None

    @property
    def metadata(self) -> dict:
        return self.deployment["metadata"]

    @property
    def deployment_name(self) -> str:
        return self.metadata["deployment_name"]

    @property
    def glider_id(self) -> str:
        """``glider_name`` + ``glider_serial`` — how pyglider names its
        merged raw files (``<glider_id>rawdbd.nc`` / ``rawebd.nc``)."""
        md = self.metadata
        return f"{md['glider_name']}{md['glider_serial']}"


def _mission_dir(mission: str | int | Path) -> Path:
    if isinstance(mission, Path):
        return mission
    if isinstance(mission, str) and ("/" in mission or Path(mission).is_dir()):
        return Path(mission)
    # a mission number or "NNN" / "NNN-name" prefix
    token = f"{int(mission):03d}" if str(mission).isdigit() else str(mission)
    matches = sorted(p for p in _MISSIONS_DIR.glob(f"{token}*") if p.is_dir())
    if not matches:
        raise FileNotFoundError(
            f"No mission directory under {_MISSIONS_DIR} matching {token!r}"
        )
    if len(matches) > 1:
        raise ValueError(f"Ambiguous mission {token!r}: {[m.name for m in matches]}")
    return matches[0]


def load(mission: str | int | Path, **overrides) -> DeploymentConfig:
    """Load a committed mission config directory.

    ``mission`` may be a mission number (``2``), a directory-name prefix
    (``"002"``), or a path to the mission directory. ``overrides`` replace
    values from the ``processing:`` block of ``deployment.yml``.
    """
    mdir = _mission_dir(mission)
    dyaml = mdir / "deployment.yml"
    sensors = mdir / "sensors.txt"
    if not dyaml.is_file():
        raise FileNotFoundError(f"{dyaml} not found")
    if not sensors.is_file():
        raise FileNotFoundError(f"{sensors} not found")

    deployment = yaml.safe_load(dyaml.read_text())
    if "metadata" not in deployment:
        raise ValueError(f"{dyaml}: missing 'metadata' block")

    proc = dict(deployment.get("processing", {}))
    proc.update(overrides)

    def _range(v):
        return tuple(v) if v else None

    return DeploymentConfig(
        mission_dir=mdir,
        deployment_yaml=dyaml,
        sensor_list=sensors,
        deployment=deployment,
        scisuffix=proc.get("scisuffix", "ebd"),
        glidersuffix=proc.get("glidersuffix", "dbd"),
        profile_filt_time=float(proc.get("profile_filt_time", 100)),
        profile_min_time=float(proc.get("profile_min_time", 100)),
        grid_dz=float(proc.get("grid_dz", 1.0)),
        l0_time_range=_range(proc.get("l0_time_range")),
        l1_time_range=_range(proc.get("l1_time_range")),
    )


def resolve(mission_number: int) -> DeploymentConfig:  # pragma: no cover - stub
    """Render a :class:`DeploymentConfig` from OGDB for ``mission_number``.

    Not implemented. Needs an OGDB mission-metadata read path (production is
    reachable via the ``nrec_app`` SSH tunnel, or a local ``ogdb`` Docker
    snapshot). The field map (which deployment.yml field <- which OGDB
    column / query) is documented in the planning repo's dependencies.md
    and the mission 002 deployment.yml header. Acceptance test once built:
    ``resolve(2)`` reproduces the committed mission 002 deployment.yml
    (bar the fields OGDB genuinely does not model).
    """
    raise NotImplementedError(
        "OGDB-backed deployment config generation not implemented yet — "
        "use config.load(<mission dir>) with a committed deployment.yml. "
        "See dependencies.md, 'OGDB <-> NRT/Delayed-Mode Processing'."
    )
