"""Delayed-mode trigger: run the shared pyglider core over a fully-recovered mission.

Thin by design (planning repo, decision 0002) — it decides *when* to run and
over *what* raw-file set; all decode/concatenate logic lives in
``processing.pyglider_run``. QC (``qc/``) is separate and later.

Delayed mode vs NRT: here the mission is complete, so the run is one-shot
over every raw file, and L1/L2 are clipped to the confirmed deployment
window (``processing.l1_time_range`` in the mission's ``deployment.yml``).
"""

from __future__ import annotations

import logging
from pathlib import Path

from ..processing import config as _config
from ..processing import pyglider_run

log = logging.getLogger(__name__)


def run_for_mission(
    mission: str | int | Path,
    binary_dir: str | Path,
    work_root: str | Path,
    *,
    steps: tuple[str, ...] = ("l0", "l1", "l2"),
) -> pyglider_run.Products:
    """Process one delayed-mode mission.

    Parameters
    ----------
    mission
        Mission number (``2``), directory prefix (``"002"``), or path to the
        mission config directory under ``python/missions/``.
    binary_dir
        Directory of the mission's ``*.dbd`` / ``*.ebd`` files
        (e.g. ``/Data/.../delayed/002-.../binary``).
    work_root
        Scratch/work directory for intermediates and outputs
        (``rawnc/``, ``cache/``, ``L0/``, ``L1/``, ``L2/``).
    """
    cfg = _config.load(mission)
    log.info("delayed-mode run: %s  (%s)", cfg.deployment_name, cfg.mission_dir)
    return pyglider_run.run(cfg, binary_dir, work_root, steps=steps)
