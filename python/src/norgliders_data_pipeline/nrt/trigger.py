"""Near-real-time trigger: decides *when* to run the shared pyglider core.

Intended to react to new-file arrival from Raw Data Ingestion (the
SFMC/rsync side in `js/`) and call
`norgliders_data_pipeline.processing.pyglider_run.run()` with whatever raw
files have landed so far for a mission. Deliberately thin -- all actual
decode/concatenate logic lives in `processing/`, shared with `delayed/`.

Not yet implemented: depends on the raw-file layout / naming convention
(open item in the planning repo's `dependencies.md`, "Raw Ingestion -> NRT
Processing") that this needs in order to know what "new file" even means.
"""

from __future__ import annotations


def on_new_file(path: str) -> None:
    """Handle a newly-arrived raw file. Placeholder."""
    raise NotImplementedError(
        "NRT trigger not yet wired up -- see dependencies.md, "
        "'Raw Ingestion -> NRT Processing'"
    )
