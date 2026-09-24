"""QC and corrections, via pelagos-py -- scaffolded 2026-09-24, step
selection still pending.

Architecture (decided, see the 2026-09-24 planning conversation)
------------------------------------------------------------------
Runs after ``og1``, reading the mission's OG1 L1 file. Unlike ``og1``
(which deletes the CF L1/L2 it converts from), **this step never modifies
or deletes OG1** -- OG1 stays a kept, standing product. The QC'd output is
a separate, new file, *not labelled OG1* (OG1.0 has no ``PARAM_ADJUSTED``
convention -- see the "adjusted data" section below -- so a file with one
isn't OG1-compliant and shouldn't claim to be). Per parameter this means
up to three variables: ``PARAM`` (as read from OG1), ``PARAM_QC`` (flag,
Argo/OG1-compatible 0-4 scale), ``PARAM_ADJUSTED`` (once correction steps
are chosen). Persistence is now three products, not two: L0, OG1, and
this QC output -- update anything downstream still written against "only
L0 and OG1 persist" (e.g. the pipeline docstring in
``processing/pyglider_run.py``, the runbook) once this is more than a
scaffold.

Dependency: ``pelagos-py`` (github.com/NOC-OBG-Autonomy/pelagos-py),
pinned via git tag in requirements.txt/pyproject.toml -- no real PyPI
release exists yet (only a ``0.0.0`` placeholder despite GitHub tags up
to v0.0.10, confirmed 2026-09-24). Its ``Load OG1`` step requires genuine
OG1.0 *structure*, not just OG1 *names* -- confirmed the hard way: it
calls ``ds.reset_coords("TIME")`` internally, which xarray refuses when
TIME is still an index coordinate. ``og1/convert.py``'s
``rename_point_dim=True`` (L1 only) exists because of this.

Not yet decided -- waiting on a colleague, see run.py's facility_pipeline.yaml
------------------------------------------------------------------
Which of pelagos-py's QC test steps and correction steps to actually run.
The goal is to mirror what BS3 already does for Seaglider processing, not
pick pelagos-py steps in isolation -- both platforms should converge on
the same QC approach now that both produce OG1. pelagos-py's available
steps (as of v0.0.10): QC tests -- spike_qc, range_qc, stuck_value_qc,
valid_profile_qc, impossible_date_qc, position_on_land_qc,
impossible_speed_qc, impossible_location_qc, par_irregularity_qc,
flag_full_profile. Corrections/derived -- derive_ctd, salinity, oxygen,
bbp, chla_quenching, deep_correction, mixed_layer_depth, find_profiles.

Adjusted data -- confirmed, not assumed
------------------------------------------------------------------
Checked the OG1.0 format manual directly (2026-09-24): it defines one
value variable per parameter plus its ``_QC`` flag, no Argo-style
``PARAM``/``PARAM_ADJUSTED`` pair. This is a live, unresolved question in
the format's own community -- see
github.com/OceanGlidersCommunity/OG-format-user-manual#286 ("Adjusted
data?"), opened by the pyglider maintainer. A collaborator there proposes
adopting Argo's ``_ADJUSTED`` convention; his reply sketches an emerging
(not formalised) pattern of separate files per ``data_mode``
(realtime/delayed/QC'd), each potentially carrying ``_ADJUSTED``
variables -- not one file updated in place. Worth revisiting whether to
track ``data_mode`` once that settles upstream, but not blocking this
scaffold. pelagos-py itself already treats the OG1
"prefer ``PARAM_ADJUSTED`` if it exists" idiom as a first-class pattern
(``utils/qc_handling.py``), and follows Argo flagging standards for
``_QC`` natively (0=no QC, 1=good, 2=probably good, 3=probably bad,
4=bad, ... -- Wong et al. 2025, Mancini et al. 2021) -- so no QARTOD-to-
OG1 flag translation is needed; that concern from the pyglider-0.0.9-era
notes below is resolved, not open.

Findings from the pyglider 0.0.9 spike (2026-09-11), still relevant
------------------------------------------------------------------
* pyglider's own OG1.0 output path (``output_conventions: OG-1.0``)
  declares ``*_QC`` variables but never populates them -- dead config
  keys. pyglider's only real automated QC (``utils.flag_CTD_data``) is
  narrow (conductivity only, binary flag) and lives in
  ``process_adjusted.py``, a script this pipeline doesn't call. Not
  relevant to the pelagos-py path above except as a reminder that
  pyglider was never meant to be a QC tool.
"""
