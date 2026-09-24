"""Rename an L1 or L2 NetCDF's variables to their OG1.0 names.

See the package docstring (``og1/__init__.py``) for why this runs as a
separate step after the normal pyglider build rather than using pyglider's
own ``output_conventions: OG-1.0`` mode.

Deliberately conservative, on two points:

* ``time`` -> ``N_MEASUREMENTS`` dimension rename is opt-in
  (``rename_point_dim``), not automatic. Structural OG1.0 compliance (the
  point/obs dimension renamed, every variable's ``processing_role`` set)
  is more than a rename -- this only does the dimension + index-coordinate
  part. Found to be *required*, not optional, once qc/ actually needed to
  feed pelagos-py's ``Load OG1`` step (2026-09-24): pelagos internally
  calls ``ds.reset_coords("TIME")``, which xarray refuses whenever TIME is
  still an index coordinate -- true whether or not its *name* matches the
  dimension name (renaming the dimension to ``N_MEASUREMENTS`` alone does
  NOT fix this; ``drop_indexes`` is also required, verified directly).
  Only meaningful for L1 (a sparse trajectory) -- L2 is a genuine 2-D
  (depth, time) grid, which OG1.0 doesn't define a convention for, so its
  call leaves ``rename_point_dim`` False.
* No ``*_QC`` / ``ancillary_variables`` are written. ``qc/`` is still
  empty -- there is nothing honest to point ``ancillary_variables`` at
  yet. Once ``qc/`` writes real ``*_QC`` variables, wire the naming and
  ``ancillary_variables`` attribute in here (see ``qc/__init__.py``).
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import xarray as xr

log = logging.getLogger(__name__)

# CF/GDAC variable name (as written by processing/pyglider_run.py's L1/L2)
# -> OG1.0 variable name. Two independent sources of truth went into this,
# noted per group below -- anything not in this table is passed through
# under its existing name rather than guessed (see convert_to_og1).
#
#   [pyglider-og1]  verified directly: ran pyglider's own bundled OG 1.0
#                   example (docs/og10-yaml.md fixture) in the 2026-09-11
#                   spike and inspected the variable names it wrote.
#   [[DFO]]         also matches github.com/DFOglider/utils'
#                   postProcess_SeaExplorer_delayed.py, which additionally
#                   sets the OG1 `vocabulary` attr to
#                   http://vocab.nerc.ac.uk/collection/OG1/current/<NAME>/
#                   for these -- the strongest confirmation in this table.
CF_TO_OG1: dict[str, str] = {
    # coordinates / nav -- [pyglider-og1]
    "time": "TIME",
    "latitude": "LATITUDE",
    "longitude": "LONGITUDE",
    "depth": "DEPTH",
    "heading": "HEADING",
    "pitch": "PITCH",
    "roll": "ROLL",
    "waypoint_latitude": "WAYPOINT_LATITUDE",
    "waypoint_longitude": "WAYPOINT_LONGITUDE",
    "trajectory": "TRAJECTORY",
    "distance_over_ground": "DISTANCE_OVER_GROUND",
    "profile_direction": "PROFILE_DIRECTION",
    # CTD -- [pyglider-og1] + [[DFO]]
    "conductivity": "CNDC",
    "temperature": "TEMP",
    "pressure": "PRES",
    "salinity": "PSAL",
    "potential_temperature": "THETA",
    "density": "DENSITY",
    # optics -- [pyglider-og1] (its test fixture carries an ECO puck)
    "chlorophyll": "CHLA",
    "cdom": "CDOM",
    "backscatter_700": "BBP700",
    # oxygen -- [pyglider-og1] + [[DFO]] for concentration only
    "oxygen_concentration": "DOXY",
    # L2's 1-D per-profile id (cf_role=profile_id, pyglider 0.0.8+ -- see
    # pyglider_run.py's mission-028 diff notes) matches OG1's
    # PROFILE_NUMBER semantics directly.
    "profile": "PROFILE_NUMBER",
    # -- deliberately NOT in this table, left as passthrough --
    # turbidity, oxygen_saturation: no OG1.0 example or DFO reference
    # confirms a name for either.
    # potential_density: pyglider's OG 1.0 fixture computes its SIGTHETA
    # via a specifically-named processing_method (potential_density_sigma0)
    # -- not confirmed this is the same quantity as get_derived_eos_raw's
    # plain "potential_density". Passed through unmapped rather than
    # guessed as SIGTHETA.
    # profile_index: L1's fractional grid-membership index (N=inside
    # profile N, N+0.5=between profiles) -- a different quantity from
    # "profile" above, no OG1 equivalent found.
}


def convert_to_og1(src: str | Path, dst: str | Path, *, rename_point_dim: bool = False) -> Path:
    """Rename ``src`` (an already-built L1 or L2 NetCDF)'s variables to
    their OG1.0 names per :data:`CF_TO_OG1`, writing the result to ``dst``.

    Any variable not in :data:`CF_TO_OG1` is kept under its existing name
    -- never dropped -- and listed in the log, so gaps in the mapping are
    visible on every run instead of silently guessed or lost.

    ``rename_point_dim=True`` (L1 only -- see module docstring) also
    renames the ``time`` dimension to ``N_MEASUREMENTS`` and strips TIME's
    index-coordinate status, matching real OG1.0 structure. Required for
    pelagos-py to be able to load the file at all.
    """
    src = Path(src)
    dst = Path(dst)

    with xr.open_dataset(src) as ds:
        ds = ds.load()

    rename = {k: v for k, v in CF_TO_OG1.items() if k in ds.variables}
    unmapped = sorted(set(ds.variables) - set(rename))
    if unmapped:
        log.info("og1 convert %s: %d variable(s) with no OG1 mapping, kept as-is: %s",
                 src.name, len(unmapped), ", ".join(unmapped))

    if rename_point_dim and "time" in ds.dims:
        ds = ds.rename_dims({"time": "N_MEASUREMENTS"}).drop_indexes("time", errors="ignore")
    ds = ds.rename(rename)

    conventions = ds.attrs.get("Conventions", "")
    if "OG-1.0" not in conventions:
        ds.attrs["Conventions"] = f"{conventions}, OG-1.0" if conventions else "OG-1.0"

    time_name = "TIME" if "TIME" in ds.variables else "time"
    encoding = {}
    if time_name in ds.variables and np.issubdtype(ds[time_name].dtype, np.datetime64):
        encoding[time_name] = {"units": "seconds since 1970-01-01T00:00:00Z", "dtype": "float64"}

    dst.parent.mkdir(parents=True, exist_ok=True)
    ds.to_netcdf(dst, mode="w", encoding=encoding)
    log.info("wrote OG1 %s -> %s", src.name, dst)
    return dst
