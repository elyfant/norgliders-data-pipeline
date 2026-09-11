"""L1/L2 -> OG1-named NetCDF, as a step *after* the normal pyglider build.

Design decision (2026-09-11, pending ADR): do not use pyglider's own
``output_conventions: OG-1.0`` deployment-yaml mode. As of pyglider 0.0.9
that path has two confirmed bugs (dead ``*_QC`` placeholders; a hardcoded
``Conventions`` overwrite -- see ``qc/__init__.py`` and
``processing/pyglider_run.py``'s compatibility notes) and would require
rewriting ``OGDB/scripts/ingest_slocum_mission.py`` and
``norgliders-ERDDAP/ingest/inspect_netcdf.py`` at the same time, since both
read today's CF/lowercase variable names.

Instead: run pyglider normally (as ``processing/pyglider_run.py`` already
does), then rename the *already-built and verified* L1/L2 file's variables
to their OG1 names as a separate, later step. This is the same approach
DFO already runs in production for their SeaExplorer pipeline
(github.com/DFOglider/utils, referenced from
c-proof/pyglider#239 "OG1 compliance") -- adapted here to this repo's own
sensor catalog (``processing/sensor_catalog.py``) instead of their
per-mission YAML ``replaceName`` keys.

See ``convert.py`` for the actual mapping and what is/isn't done.
"""
