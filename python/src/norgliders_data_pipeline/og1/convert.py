"""Rename an L1 or L2 NetCDF's variables to their OG1.0 names, and fill in
as much of OG1.0's required/highly-desirable metadata as this facility can
answer confidently.

See the package docstring (``og1/__init__.py``) for why this runs as a
separate step after the normal pyglider build rather than using pyglider's
own ``output_conventions: OG-1.0`` mode.

Checked directly against the OG1.0 format manual (2026-09-24,
oceangliderscommunity.github.io/OG-format-user-manual) for its mandatory /
highly-desirable global and variable attribute lists, rather than guessed.

Deliberately NOT attempted, on three points:

* The ``sensor`` variable attribute and the ``SENSOR_*`` scalar variables
  it should point at (e.g. ``SENSOR_CTD``) -- pyglider's own OG1.0 fixture
  carries these, built from ``glider_devices`` in ``deployment.yml``. Not
  built here: setting ``sensor`` without the variable it references would
  be a dangling reference, worse than omitting it. A real, separate piece
  of work.
* Claiming ``CF-1.10`` in ``Conventions`` (pyglider's own OG1.0 fixture
  does). Not verified that this file's structure actually satisfies
  CF-1.10 beyond CF-1.8 (mostly geometry/ragged-array conventions) --
  left as whatever the input file already declares.
* ``*_QC`` / ``ancillary_variables``. ``qc/`` writes those into a
  *separate* file now (see ``qc/__init__.py``, 2026-09-24 architecture
  decision) -- OG1 itself never carries them, so there's nothing to
  point ``ancillary_variables`` at from here, ever, under the current
  design.

``time`` -> ``N_MEASUREMENTS`` dimension rename is opt-in
(``rename_point_dim``), L1 only -- see :func:`convert_to_og1`.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
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

# OG1 names confident enough to be "geophysical variables" in the format
# manual's sense (i.e. get a `vocabulary` attribute) -- restricted to
# measured/derived physical parameters actually seen in a real, verified
# OG1.0 file (pyglider's own fixture). Structural/navigational names
# (TRAJECTORY, WAYPOINT_*, PROFILE_*, HEADING/PITCH/ROLL,
# DISTANCE_OVER_GROUND, and the coordinates LATITUDE/LONGITUDE/TIME/DEPTH
# themselves) are deliberately excluded -- their presence in the OG1
# vocabulary collection specifically wasn't individually verified.
_GEOPHYSICAL_OG1_NAMES = {
    "TEMP", "CNDC", "PRES", "PSAL", "THETA", "DENSITY", "CHLA", "CDOM", "BBP700", "DOXY",
}
_OG1_VOCAB_URL = "http://vocab.nerc.ac.uk/collection/OG1/current/{name}/"

# OG1's required `coordinates` order (format manual: "TIME, LONGITUDE,
# LATITUDE, DEPTH"), comma-separated -- our pyglider-built input files use
# CF's own convention instead (space-separated, lowercase, "time depth
# latitude longitude"). This reformats, it doesn't add or drop anything.
_OG1_COORD_ORDER = ["TIME", "LONGITUDE", "LATITUDE", "DEPTH"]

# Fixed (not mission-specific) NERC vocabulary terms -- verified directly
# against vocab.nerc.ac.uk (2026-09-24), not guessed. Safe to reuse across
# every mission this facility runs.
_PLATFORM = "sub-surface gliders"
_PLATFORM_VOCAB = "http://vocab.nerc.ac.uk/collection/L06/current/27/"
_OPERATOR_ROLE_VOCAB = "http://vocab.nerc.ac.uk/collection/W08/current/CONT0003/"

# deployment.yml's metadata.contributor_role text (comma-separated) ->
# NERC W08 CI_RoleCode URI. Verified against vocab.nerc.ac.uk/collection/W08/
# (2026-09-24) for "Principal Investigator"/"Operator". "Technical Lead" has
# no exact W08 term -- mapped to the closest one (Technical Coordinator) as
# an approximation, flagged here rather than silently treated as exact.
# This table is the one place role *text* becomes a vocabulary *claim* --
# extend/correct it here, not by guessing elsewhere.
ROLE_TO_NERC_CONT: dict[str, str] = {
    "principal investigator": "http://vocab.nerc.ac.uk/collection/W08/current/CONT0004/",
    "pi": "http://vocab.nerc.ac.uk/collection/W08/current/CONT0004/",
    "technical coordinator": "http://vocab.nerc.ac.uk/collection/W08/current/CONT0005/",
    "technical lead": "http://vocab.nerc.ac.uk/collection/W08/current/CONT0005/",  # approximate, no exact W08 term
    "operator": _OPERATOR_ROLE_VOCAB,
}


def _og1_coordinates_encoding(var: xr.DataArray) -> str | None:
    """OG1's ``"TIME, LONGITUDE, LATITUDE, DEPTH"`` form for ``var``, built
    from which of those four actually apply to it (via ``var.coords``, not
    by reformatting a ``coordinates`` *attribute* -- xarray decodes and
    strips that attribute into real coordinate structure on read, so by
    the time :func:`convert_to_og1` sees the dataset it's already gone;
    confirmed directly rather than assumed). Returns ``None`` if none of
    the four apply (nothing to set)."""
    have = set(var.coords) & set(_OG1_COORD_ORDER)
    if not have:
        return None
    return ", ".join(n for n in _OG1_COORD_ORDER if n in have)


def _og1_metadata_attrs(metadata: dict) -> dict:
    """OG1.0 global attributes this facility can fill confidently from
    ``deployment.yml``'s ``metadata:`` block (see module docstring for
    what's deliberately NOT attempted)."""
    attrs: dict = {}
    deployment_name = metadata.get("deployment_name", "")
    attrs["id"] = deployment_name
    attrs["title"] = metadata.get("summary") or deployment_name
    attrs["date_created"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if metadata.get("deployment_start"):
        attrs["start_date"] = metadata["deployment_start"]

    attrs["platform"] = _PLATFORM
    attrs["platform_vocabulary"] = _PLATFORM_VOCAB
    attrs["rtqc_method"] = "No QC applied"  # honest for this pipeline stage -- matches pyglider's own OG1.0 fixture's wording for the same pre-QC state

    if metadata.get("naming_authority"):
        attrs["naming_authority"] = metadata["naming_authority"]
    if metadata.get("sea_name"):
        attrs["site"] = metadata["sea_name"]
    if metadata.get("project"):
        attrs["program"] = metadata["project"]
    if metadata.get("doi"):
        attrs["doi"] = metadata["doi"]

    contributor_email = metadata.get("contributor_email") or metadata.get("creator_email")
    if metadata.get("contributor_name"):
        attrs["contributor_name"] = metadata["contributor_name"]
    if contributor_email:
        attrs["contributor_email"] = contributor_email
    if metadata.get("contributor_role"):
        attrs["contributor_role"] = metadata["contributor_role"]
        roles = [r.strip() for r in metadata["contributor_role"].split(",")]
        vocab = [ROLE_TO_NERC_CONT.get(r.lower(), "") for r in roles]
        if all(vocab):
            attrs["contributor_role_vocabulary"] = ", ".join(vocab)
        else:
            log.warning(
                "og1 convert: no NERC W08 mapping for contributor role(s) %s -- "
                "contributor_role_vocabulary left unset, extend ROLE_TO_NERC_CONT",
                [r for r, v in zip(roles, vocab) if not v],
            )

    if metadata.get("institution"):
        attrs["contributing_institutions"] = metadata["institution"]
        attrs["contributing_institutions_role"] = "Operator"
        attrs["contributing_institutions_role_vocabulary"] = _OPERATOR_ROLE_VOCAB

    return attrs


def convert_to_og1(src: str | Path, dst: str | Path, *, rename_point_dim: bool = False,
                    metadata: dict | None = None) -> Path:
    """Rename ``src`` (an already-built L1 or L2 NetCDF)'s variables to
    their OG1.0 names per :data:`CF_TO_OG1`, writing the result to ``dst``.

    Any variable not in :data:`CF_TO_OG1` is kept under its existing name
    -- never dropped -- and listed in the log, so gaps in the mapping are
    visible on every run instead of silently guessed or lost.

    ``rename_point_dim=True`` (L1 only -- see module docstring) also
    renames the ``time`` dimension to ``N_MEASUREMENTS`` and strips TIME's
    index-coordinate status, matching real OG1.0 structure. Required for
    pelagos-py to be able to load the file at all.

    ``metadata``, if given (typically ``DeploymentConfig.metadata``, i.e.
    ``deployment.yml``'s ``metadata:`` block), fills in the OG1.0 global
    attributes this facility can answer from it -- see
    :func:`_og1_metadata_attrs`. Applies to both L1 and L2 (deployment-level
    metadata isn't processing-level-specific), independent of
    ``rename_point_dim``.
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

    for og1_name in rename.values():
        if og1_name not in ds.variables or og1_name in _OG1_COORD_ORDER:
            continue  # the coordinate variables themselves don't reference each other
        if og1_name in _GEOPHYSICAL_OG1_NAMES:
            ds[og1_name].attrs["vocabulary"] = _OG1_VOCAB_URL.format(name=og1_name)
        coordinates = _og1_coordinates_encoding(ds[og1_name])
        if coordinates:
            ds[og1_name].encoding["coordinates"] = coordinates

    if metadata:
        ds.attrs.update(_og1_metadata_attrs(metadata))

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
