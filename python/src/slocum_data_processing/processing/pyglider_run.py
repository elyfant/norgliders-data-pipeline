"""Mode-agnostic pyglider decode+concatenate step.

Pyglider itself doesn't know or care whether it's running in near-real-time
or delayed mode -- it decodes and concatenates whatever raw glider files it's
given, using a deployment config, into L0/L1/L2 NetCDF. What differs between
NRT and delayed-mode is *what triggers this* and *how complete the raw data
is at the time it's called* -- not the decode logic itself.

Both `nrt/trigger.py` and `delayed/trigger.py` are expected to call `run()`
here with whatever raw-file set and config are appropriate for their mode.
QC is a deliberately separate, later concern -- see `qc/` -- not performed
by this module.

Not yet implemented: the raw-file layout (Raw Ingestion -> NRT Processing
directory/naming convention) and the deployment-yaml resolution strategy
(see `config.py`) are both still open questions in the planning repo's
`dependencies.md` -- need to be settled before this can do real work.
"""

from __future__ import annotations

from pathlib import Path


def run(raw_files: list[Path], config: "DeploymentConfig") -> list[Path]:
    """Decode and concatenate `raw_files` per `config`, returning the
    resulting L0/L1/L2 NetCDF file paths.

    Placeholder -- raises until the raw-file layout and deployment-config
    conventions this depends on are decided.
    """
    raise NotImplementedError(
        "pyglider decode/concatenate not yet wired up -- see dependencies.md "
        "for the open raw-file-layout and deployment-config questions this "
        "needs first"
    )
