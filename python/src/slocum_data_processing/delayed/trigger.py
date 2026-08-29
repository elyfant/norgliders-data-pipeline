"""Delayed-mode trigger: decides *when* to run the shared pyglider core.

Intended to run once a mission is fully recovered (all raw files present,
unlike NRT's partial/incremental view) and call
`slocum_data_processing.processing.pyglider_run.run()` over the complete
raw-file set for that mission. Deliberately thin -- all actual
decode/concatenate logic lives in `processing/`, shared with `nrt/`.

Not yet implemented: depends on the same raw-file layout question as
`nrt/trigger.py`, plus how "mission fully recovered" gets determined
(manually invoked for now, presumably).
"""

from __future__ import annotations


def run_for_mission(mission_id: int) -> None:
    """Run delayed-mode processing for a fully-recovered mission. Placeholder."""
    raise NotImplementedError(
        "delayed-mode trigger not yet wired up -- see dependencies.md, "
        "'Raw Ingestion -> NRT Processing'"
    )
