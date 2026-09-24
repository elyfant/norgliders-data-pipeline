"""Mode-agnostic Slocum decode + concatenate core (planning repo, decision 0002).

NRT and delayed-mode both call into here; they differ only in *what triggers
the run* and *how complete the raw data is*, not in the decode logic. QC
(``qc/``) is a deliberately separate, later concern and is not done here.

Products
--------
L0  Time-merged flight + science, one CF Discrete-Sampling-Geometry
    ``trajectory`` file, **raw Slocum sensor names**, no derived variables,
    no QC. A faithful decoded archive of the binary data. Built with
    ``dbdreader`` directly (fast; L0 is our own step, like QC).
L1  ``pyglider.slocum.binary_to_timeseries``: CF variable names, derived
    salinity / density (TEOS-10 via gsw), profile index, clipped to the
    deployment window. Pre-QC. **Intermediate, not persisted** — deleted
    once OG1 is written from it (see ``_discard_cf_intermediates``).
L2  ``pyglider.ncprocess.make_gridfiles``: gridded time x depth. Pre-QC.
    **Intermediate, not persisted** — same as L1.

Why not ``binary_to_rawnc`` for the decode
-----------------------------------------
pyglider's ``binary_to_rawnc`` uses a pure-Python bitstring parser that
reads every column of every cycle regardless of the sensor filter — ~5-8 s
per file, hours for a full mission. ``binary_to_timeseries`` and our L0
step both use ``dbdreader`` (C extension): the same mission decodes in
seconds.

Compatibility note
------------------
pyglider 0.0.7 called ``xr.open_mfdataset(..., lock=False)`` with the default
*threaded* dask scheduler; against a non-thread-safe libhdf5 this segfaulted
(``free(): invalid size``). :func:`_guard` forces the single-threaded
scheduler around pyglider calls. pyglider also logs a harmless ``TypeError``
(``_log.info('Opening:', a, b)`` — bad %-formatting, still present in 0.0.9);
ignore it.

pyglider 0.0.9 (2026-09-11 spike, see docs/architecture — pending ADR):
bumped from 0.0.7. ``binary_to_timeseries``/``make_gridfiles`` signatures
are unchanged (only new optional kwargs added). 3x runs of pyglider's own
bundled Slocum fixture under the default threaded scheduler (:func:`_guard`
bypassed) didn't reproduce the segfault, but that fixture is tiny next to a
real mission, so it wasn't proof either way.

Verified against real mission 028 (270 binary files, run *with* :func:`_guard`
still active, via this module as normal) and diffed against the existing
0.0.7 output already on disk:

* L0 — byte-identical, all 66 variables (expected: dbdreader-only, no
  pyglider involvement).
* L1 — byte-identical (NaN-aware), all 20 variables. No regression risk
  from the version bump at this level.
* L2 — 19/21 variables identical. Two real differences:
  ``profile_time_start``/``profile_time_end`` were wrong in the 0.0.7
  output (epoch-adjacent garbage, e.g. ``1970-01-01T00:01:10``) — 0.0.9
  fixes this (matches upstream PR #223, "fix profile times"); our
  committed L2 product has had incorrect profile timestamps since it was
  generated. And ``profile_index`` (2D depth x time, grid-cell profile
  membership) is gone from L2 in 0.0.9, replaced by ``profile`` (1D, one
  id per profile, ``cf_role: profile_id``) — not equivalent, coarser.
  Nothing in this repo reads ``profile_index`` off L2 (only off L1, via
  :func:`build_l2`, which is unaffected). Checked against the two actual
  downstream consumers too: ``OGDB/scripts/ingest_slocum_mission.py``
  reads only ``latitude``/``longitude``/``time``/``temperature``/
  ``salinity``/``profile_direction``/``distance_over_ground`` (all
  unchanged) and never touches ``profile_index``;
  ``norgliders-ERDDAP/ingest/inspect_netcdf.py`` classifies L2 by "has a
  depth dim and *some* 2-D variable," not by ``profile_index``
  specifically. Neither is affected by this rename.

Still open: this run kept :func:`_guard` active throughout, so it confirms
0.0.9 works correctly at real mission scale *with* the guard — it does not
yet show whether the guard is safe to remove at that scale.

OG1
---
L1 and L2 are also converted to OG1-named NetCDF as a last step (see
``og1/convert.py``) — a rename of the already-built, already-verified
CF output, not pyglider's own ``output_conventions: OG-1.0`` mode. See
``og1/__init__.py`` for why.

Facility decision (2026-09-12): only L0 and OG1 persist on disk. Once
OG1 is written, the CF L1/L2 files are deleted (``_discard_cf_intermediates``)
— they're fully reproducible from L0 + ``deployment.yml`` if ever needed
again. This only happens when ``"og1"`` is actually in ``steps``, so the
window-tuning loop (``--steps l1,l2``, no ``og1``) still leaves L1/L2 on
disk to inspect before committing.
"""

from __future__ import annotations

import contextlib
import logging
from dataclasses import dataclass, field
from pathlib import Path

import dask
import numpy as np
import pandas as pd
import xarray as xr

import dbdreader
import pyglider.ncprocess as ncprocess
import pyglider.slocum as slocum

from .config import DeploymentConfig
from ..og1.convert import convert_to_og1
from ..qc.run import build_qc as _run_pelagos_qc

log = logging.getLogger(__name__)

_L1_TIME_BASE = "sci_water_temp"  # pyglider binary_to_timeseries interpolant


@dataclass
class Products:
    l0: Path | None = None
    l1: Path | None = None
    l2: list[Path] = field(default_factory=list)
    og1: list[Path] = field(default_factory=list)  # OG1-renamed L1 + L2
    qc: Path | None = None  # pelagos-py output from the OG1 L1 file, see qc/__init__.py


@contextlib.contextmanager
def _guard():
    with dask.config.set(scheduler="single-threaded"):
        yield


@dataclass
class WorkDirs:
    root: Path
    cache: Path
    l0: Path
    l1: Path
    l2: Path
    og1: Path
    qc: Path

    @classmethod
    def under(cls, root: str | Path) -> "WorkDirs":
        root = Path(root)
        d = cls(root=root, cache=root / "cache",
                l0=root / "L0", l1=root / "L1", l2=root / "L2", og1=root / "OG1",
                qc=root / "QC")
        for p in (d.cache, d.l0, d.l1, d.l2, d.og1, d.qc):
            p.mkdir(parents=True, exist_ok=True)
        return d


# --------------------------------------------------------------------------
# steps
# --------------------------------------------------------------------------
def _read_sensor_list(path: Path) -> list[str]:
    out = []
    for line in Path(path).read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            out.append(line)
    return out


def _slice_time(ds: xr.Dataset, rng: tuple[str, str] | None) -> xr.Dataset:
    if not rng:
        return ds
    return ds.sel(time=slice(np.datetime64(rng[0]), np.datetime64(rng[1])))


def build_l0(cfg: DeploymentConfig, binary_dir: Path, work: WorkDirs) -> Path:
    """Faithful decoded archive: every sensor in ``sensors.txt`` that carries
    data, flight + science, on one union time axis, raw names, no QC."""
    binary_dir = Path(binary_dir)
    wanted = set(_read_sensor_list(cfg.sensor_list))

    # Slocum flight files *declare* sci_* sensor names too (as empty columns);
    # the science file is the authority for sci_*. Take non-sci_ from flight,
    # sci_ from science, so there is no ambiguous overlap.
    streams = ((cfg.glidersuffix, lambda n: not n.startswith("sci_")),
               (cfg.scisuffix, lambda n: n.startswith("sci_")))

    series: dict[str, pd.Series] = {}
    for suffix, keep in streams:
        if not any(binary_dir.glob(f"*.{suffix}")):
            continue
        dbd = dbdreader.MultiDBD(pattern=f"{binary_dir}/*.{suffix}",
                                 cacheDir=str(work.cache))
        avail = {p for grp in dbd.parameterNames.values() for p in grp}
        params = sorted(p for p in (wanted & avail) if keep(p))
        if not params:
            continue
        got = dbd.get(*params)
        if len(params) == 1:
            got = [got]
        for name, (t, v) in zip(params, got):
            v = np.asarray(v, dtype="float64")
            ok = np.isfinite(v)
            if ok.sum() == 0:
                continue  # sensor declared but never logged
            s = pd.Series(v[ok],
                          index=pd.to_datetime(np.asarray(t, dtype="float64")[ok],
                                               unit="s"))
            series[name] = s[~s.index.duplicated(keep="first")].sort_index()

    if not series:
        raise RuntimeError("L0: no sensors from sensors.txt carried data")

    df = pd.concat(series, axis=1).sort_index()
    df = df[~df.index.duplicated(keep="first")]
    df.index.name = "time"

    ds = xr.Dataset.from_dataframe(df)
    ds = _slice_time(ds, cfg.l0_time_range)
    ds = _add_trajectory(ds, cfg)
    ds.attrs.update(_global_attrs(cfg, processing_level="L0"))
    ds["time"].attrs.update(standard_name="time", long_name="Time", axis="T")
    for name in df.columns:
        ds[name].attrs.setdefault("source_sensor", name)

    out = work.l0 / f"{cfg.deployment_name}_L0.nc"
    ds.to_netcdf(out, mode="w",
                 encoding={"time": {"units": "seconds since 1970-01-01T00:00:00Z", "dtype": "float64"}})
    log.info("wrote L0: %s  (%d samples x %d sensors)",
             out, ds.sizes["time"], len(df.columns))
    return out


def build_l1(cfg: DeploymentConfig, binary_dir: Path, work: WorkDirs) -> Path:
    """pyglider timeseries (CF names, TEOS-10 salinity/density, profiles),
    clipped to the deployment window (``processing.l1_time_range``)."""
    search = f"*.[{cfg.glidersuffix[0]}{cfg.scisuffix[0]}]{cfg.glidersuffix[1:]}"
    with _guard():
        raw = slocum.binary_to_timeseries(
            str(binary_dir), str(work.cache), str(work.l1),
            str(cfg.deployment_yaml),
            search=search, time_base=_L1_TIME_BASE,
            profile_filt_time=cfg.profile_filt_time,
            profile_min_time=cfg.profile_min_time,
        )
    raw = Path(raw)

    with xr.open_dataset(raw) as ds:
        ds = ds.load()
    clipped = _slice_time(ds, cfg.l1_time_range)
    if clipped.sizes.get("time", 0) == 0:
        raise ValueError(
            f"l1_time_range {cfg.l1_time_range} selects no samples "
            f"(data spans {ds.time.values[0]}..{ds.time.values[-1]})"
        )
    coords = [c for c in ("latitude", "longitude", "depth") if c in clipped.variables]
    clipped = clipped.set_coords(coords)
    if "trajectory" not in clipped:
        clipped = _add_trajectory(clipped, cfg)
    clipped.attrs.update(_global_attrs(cfg, processing_level="L1"))

    out = work.l1 / f"{cfg.deployment_name}_L1.nc"
    if raw.resolve() != out.resolve():
        raw.unlink()
    clipped.to_netcdf(out, mode="w",
                      encoding={"time": {"units": "seconds since 1970-01-01T00:00:00Z", "dtype": "float64"}})
    log.info("wrote L1: %s  (%d samples, %s..%s)", out, clipped.sizes["time"],
             str(clipped.time.values[0])[:19], str(clipped.time.values[-1])[:19])
    return out


def build_l2(cfg: DeploymentConfig, work: WorkDirs, l1_file: Path) -> list[Path]:
    """pyglider gridded product (time x depth) from the windowed L1."""
    with xr.open_dataset(l1_file) as ds:
        ds = ds.load()
    nprof = int(np.nanmax(ds["profile_index"].values)) if "profile_index" in ds else 0
    if nprof < 1:
        log.warning("L1 has no complete profiles — skipping L2")
        return []

    # pyglider's make_gridfiles does ~np.isnan(ds[k]) over every variable and
    # chokes on the string `trajectory` scalar — grid from a numeric-only copy.
    numeric = ds.drop_vars(
        [v for v in ds.data_vars if not np.issubdtype(ds[v].dtype, np.number)]
    )
    grid_in = work.l2 / f"{cfg.deployment_name}_L1-for-grid.nc"
    numeric.to_netcdf(grid_in, mode="w",
                      encoding={"time": {"units": "seconds since 1970-01-01T00:00:00Z",
                                         "dtype": "float64"}})
    with _guard():
        out = ncprocess.make_gridfiles(
            str(grid_in), str(work.l2), str(cfg.deployment_yaml), dz=cfg.grid_dz,
        )
    grid_in.unlink()
    out = Path(out)
    final = out.with_name(f"{cfg.deployment_name}_L2.nc")
    with xr.open_dataset(out) as ds:
        ds = ds.load()
    ds.attrs.update(_global_attrs(cfg, processing_level="L2"))
    ds.attrs["featureType"] = "trajectoryProfile"
    ds.to_netcdf(final, mode="w")
    if out.resolve() != final.resolve():
        out.unlink()
    log.info("wrote L2: %s", final)
    return [final]


def build_og1(cfg: DeploymentConfig, work: WorkDirs, l1_file: Path,
              l2_files: list[Path]) -> list[Path]:
    """OG1-named copies of L1 and each L2 file (see ``og1/convert.py``).

    L1 gets the structural ``N_MEASUREMENTS`` dimension rename too
    (``rename_point_dim=True``) -- required for pelagos-py's ``Load OG1``
    step, and the only one of the two that's a sparse trajectory rather
    than a 2-D grid. L2 stays dimension-unchanged.
    """
    out = [convert_to_og1(l1_file, work.og1 / f"{cfg.deployment_name}_L1_OG1.nc",
                          rename_point_dim=True)]
    for l2 in l2_files:
        out.append(convert_to_og1(l2, work.og1 / f"{l2.stem}_OG1.nc"))
    return out


def run(cfg: DeploymentConfig, binary_dir: str | Path, work_root: str | Path,
        *, steps: tuple[str, ...] = ("l0", "l1", "l2", "og1")) -> Products:
    """Full delayed-mode / NRT run: L0 (all data) -> L1 (windowed) -> L2 -> OG1."""
    binary_dir = Path(binary_dir)
    work = WorkDirs.under(work_root)
    prod = Products()

    if "l0" in steps:
        prod.l0 = build_l0(cfg, binary_dir, work)
    if "l1" in steps:
        prod.l1 = build_l1(cfg, binary_dir, work)

    if "l2" in steps:
        l1 = prod.l1 or (work.l1 / f"{cfg.deployment_name}_L1.nc")
        if not Path(l1).is_file():
            raise FileNotFoundError(f"L2 needs an L1 file — {l1} not found (run l1 first)")
        prod.l2 = build_l2(cfg, work, Path(l1))

    if "og1" in steps:
        l1 = prod.l1 or (work.l1 / f"{cfg.deployment_name}_L1.nc")
        if not Path(l1).is_file():
            raise FileNotFoundError(f"OG1 needs an L1 file — {l1} not found (run l1 first)")
        l2s = prod.l2 or [p for p in work.l2.glob(f"{cfg.deployment_name}_L2.nc")]
        l1, l2s = Path(l1), [Path(p) for p in l2s]
        prod.og1 = build_og1(cfg, work, l1, l2s)
        _discard_cf_intermediates(l1, l2s)
        prod.l1 = None
        prod.l2 = []

    if "qc" in steps:
        l1_og1 = next((p for p in prod.og1 if "_L1_OG1" in p.name), None)
        l1_og1 = l1_og1 or (work.og1 / f"{cfg.deployment_name}_L1_OG1.nc")
        if not Path(l1_og1).is_file():
            raise FileNotFoundError(f"qc needs the OG1 L1 file — {l1_og1} not found (run og1 first)")
        prod.qc = _run_pelagos_qc(cfg.deployment_name, Path(l1_og1), work.qc)
    return prod


def _discard_cf_intermediates(l1_file: Path, l2_files: list[Path]) -> None:
    """Delete the CF-named L1/L2 once OG1 has been written from them.

    Facility decision (2026-09-12): only L0 (faithful decoded archive) and
    OG1 (renamed, shareable) are meant to persist. L1/L2 are pyglider's
    intermediates — real files on disk because L2 is built *from* the L1
    file and OG1 is a rename of each, not because they're a wanted final
    product. Reproducible from L0 + deployment.yml if ever needed again
    (design principle: "NetCDF products are not [versioned] — regenerable
    from raw"). Only called from the "og1" branch of :func:`run`, so this
    never runs on a partial `--steps l1,l2` window-tuning pass.
    """
    for f in [l1_file, *l2_files]:
        if f.is_file():
            f.unlink()
            log.info("deleted CF intermediate: %s (superseded by OG1)", f)


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _add_trajectory(ds: xr.Dataset, cfg: DeploymentConfig) -> xr.Dataset:
    ds["trajectory"] = xr.DataArray(
        cfg.deployment_name,
        attrs={
            "cf_role": "trajectory_id",
            "long_name": "Trajectory/Deployment Name",
            "comment": "A trajectory is one deployment of a glider.",
        },
    )
    return ds


def _global_attrs(cfg: DeploymentConfig, *, processing_level: str) -> dict:
    md = cfg.metadata
    attrs = {
        "Conventions": "CF-1.8, ACDD-1.3",
        "featureType": "trajectory",
        "processing_level": processing_level,
        "deployment_name": cfg.deployment_name,
        "glider_name": md.get("glider_name", ""),
        "glider_serial": str(md.get("glider_serial", "")),
        "wmo_id": str(md.get("wmo_id", md.get("glider_wmo", ""))),
        "institution": md.get("institution", ""),
        "project": md.get("project", ""),
        "source": md.get("source", "Observational data from a profiling glider."),
        "processing_package": f"pyglider {_pyglider_version()}",
    }
    return {k: v for k, v in attrs.items() if v != ""}


def _pyglider_version() -> str:
    try:
        import pyglider._version as v
        return v.__version__
    except Exception:  # pragma: no cover
        return "unknown"
