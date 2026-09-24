"""Run a mission's OG1 L1 file through pelagos-py.

See the package docstring (``qc/__init__.py``) for the architecture this
implements: OG1 is read, never modified or deleted; the result is a new,
separately-named file (not called OG1) carrying ``PARAM``, ``PARAM_QC``,
and (once correction steps are chosen) ``PARAM_ADJUSTED`` for whichever
variables pelagos-py's steps touch.

Only L1 -- pelagos-py's ``Load OG1`` step is built for a sparse trajectory
(``N_MEASUREMENTS``-dimensioned, per ``og1/convert.py``'s
``rename_point_dim``), not a 2-D grid, and OG1.0 itself has no gridded-
product convention. Whether a QC'd L2 comes from re-gridding the QC'd L1
afterward, or from something else, is an open question -- not decided,
not attempted here.
"""

from __future__ import annotations

import logging
from pathlib import Path

import yaml
from pelagos_py.pipeline import Pipeline

log = logging.getLogger(__name__)

_HERE = Path(__file__).resolve().parent
_FACILITY_PIPELINE = _HERE / "facility_pipeline.yaml"


def build_qc(deployment_name: str, og1_l1_file: str | Path, out_dir: str | Path,
             *, pipeline_yaml: str | Path | None = None) -> Path:
    """Run pelagos-py over ``og1_l1_file``, writing
    ``<out_dir>/<deployment_name>_L1_QC.nc``.

    The QC/correction step list comes from ``pipeline_yaml`` (default:
    the packaged ``facility_pipeline.yaml`` -- currently empty, see that
    file). ``Load OG1`` and ``Data Export`` are added automatically around
    it; the yaml only needs to name what happens in between.

    Parameters
    ----------
    deployment_name
        Used for the output filename and the pelagos-py log file name.
    og1_l1_file
        Path to the mission's ``..._L1_OG1.nc`` (untouched, not modified
        by this call).
    out_dir
        Directory the QC'd file (and pelagos-py's own log) are written
        into.
    pipeline_yaml
        Override the facility-default step list, e.g. for a mission that
        needs different QC settings.
    """
    og1_l1_file = Path(og1_l1_file)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    dst = out_dir / f"{deployment_name}_L1_QC.nc"

    steps_source = Path(pipeline_yaml) if pipeline_yaml else _FACILITY_PIPELINE
    facility = yaml.safe_load(steps_source.read_text()) or {}
    qc_steps = facility.get("steps", [])

    config = {
        "pipeline": {
            "out_directory": str(out_dir),
            "log_file": f"{deployment_name}_pelagos.log",
            "continue_on_step_fail": False,
        },
        "steps": [
            {"name": "Load OG1",
             "parameters": {"file_path": str(og1_l1_file), "filter_bad_time": False}},
            *qc_steps,
            {"name": "Data Export",
             "parameters": {"output_path": str(dst), "export_format": "netcdf"}},
        ],
    }

    log.info("qc: running pelagos-py over %s (%d step(s) from %s)",
             og1_l1_file.name, len(qc_steps), steps_source.name)
    Pipeline(config=config).run()
    log.info("wrote QC %s -> %s", og1_l1_file.name, dst)
    return dst
