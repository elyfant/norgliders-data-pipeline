"""Quality control -- deliberately empty for now.

QC is a separate concern from decoding/concatenation (`processing/`) and is
being designed separately, later. Nothing here yet.

Findings from the pyglider 0.0.9 spike (2026-09-11, branch
spike/pyglider-0.0.9) relevant when this gets built:

* pyglider's OG1.0 output path (``output_conventions: OG-1.0`` in the
  deployment yaml) declares ``*_QC`` variables (``TEMP_QC``, ``PSAL_QC``,
  ``PRES_QC``, uppercase, OG1 naming) but never populates them -- they're
  dead config keys today (verified: absent from the written file despite a
  misleading "working on TEMP_QC" log line). pyglider's *only* real
  automated QC (``utils.flag_CTD_data``, a conductivity depth-space stdev
  screen) writes differently-named, lowercase vars (``conductivity_QC``,
  ``salinity_QC``, ``temperature_QC``) via a separate script
  (``process_adjusted.py``) that nothing in our pipeline calls. So: don't
  expect pyglider to generate QC variables for us. This module has to write
  them.

* If/when this module targets pyglider's OG1.0 output, it needs to write
  the uppercase OG1 names (``TEMP_QC`` etc.), not lowercase CF-style ones,
  and needs to fill pyglider's ``ancillary_variables`` attribute (currently
  written blank) to point at them.

* OG1.0's QC flag vocabulary (0/1/2/3/4 = no QC / good / probably good /
  probably bad / bad -- see OceanGliders OG-format-user-manual) is *not*
  the same scale as QARTOD (1/2/3/4/9 = good / not evaluated / suspect /
  fail / missing -- what ``ioos_qc`` produces). Whatever this module runs
  ioos_qc/QARTOD or otherwise needs an explicit flag-value translation to
  OG1's scale before writing ``*_QC``, not a same-numbers passthrough.
"""
