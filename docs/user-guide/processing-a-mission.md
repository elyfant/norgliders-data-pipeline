# Processing a Slocum mission (delayed mode)

How to take one mission's raw glider binaries through to L0/L1/L2 NetCDF
using the pyglider pipeline in this repo.

Worked reference: mission 002 (`002-gna_naco_faroe_jun2012`), already done —
look at its `python/missions/002-gna_naco_faroe_jun2012/` for a filled-in
example of everything below.

---

## What the pipeline produces

| Level | What it is | How |
|---|---|---|
| **L0** | Every decoded sample from **all** binary files, flight + science time-merged into one CF-DSG `trajectory`, **raw Slocum sensor names**, no derived variables, no QC. A faithful decoded archive. | `dbdreader` directly |
| **L1** | CF / OG1 variable names, derived salinity & density (TEOS-10), profile index. Clipped to the deployment window. Pre-QC. | `pyglider.slocum.binary_to_timeseries` |
| **L2** | Gridded time × depth. Pre-QC. | `pyglider.ncprocess.make_gridfiles` |

QC (auto for delayed-mode, manual for the published dataset) is a separate,
later step — not part of this pipeline.

---

## One-time setup

```bash
cd ~/projects/slocum_data_processing
python3 -m venv .venv                 # only if .venv is missing or broken
.venv/bin/pip install -e python/
```

This installs `pyglider==0.0.7` + `dbdreader` + the scientific stack pinned
in `python/requirements.txt`, and the `slocum-process-mission` command.

> **Why the old pyglider?** 0.0.7 is what the facility standardised on. The
> pipeline carries two compatibility shims for it (single-threaded dask to
> avoid an HDF5 segfault; the `dbdreader` decode path instead of the ~25×
> slower `binary_to_rawnc`). See `processing/pyglider_run.py`.

---

## Step 1 — stage the binary files

The pipeline reads a `binary/` directory of **full** `.dbd` (flight) and
`.ebd` (science) files. `raw/` is the immutable archive and is never
touched.

```bash
D=/Data/gfi/projects/slocum/data/delayed/<NNN-mission-name>
mkdir -p "$D/binary"
cp "$D"/raw/*.dbd "$D"/raw/*.ebd "$D/binary/"
```

Notes:

- **Full files only.** `.dbd`/`.ebd` carry their sensor list inline, so no
  cache (`.cac`) files are needed. The compressed `.sbd`/`.tbd`/`.mbd`/`.nbd`
  telemetry variants are a different workflow (they need cache files and
  `search='*.[st]bd'`) — not covered here.
- Files may arrive with numeric names (`00530013.dbd`) or already renamed
  to `glider-YYYY-DDD-N-N.{dbd,ebd}`. Either works — pyglider reads the real
  name from the file header. Renaming is just for human/chronological
  legibility.
- **Sanity-check coverage before processing.** A real deployment is
  hundreds of files over weeks. If `binary/` has only a handful spanning a
  few days, the deployment data probably hasn't all been downloaded yet.

---

## Step 2 — inspect the payload and the real deployment window

**Science sensors actually in the files:**

```bash
strings "$D"/binary/*.ebd \
  | grep -oE 'sci_(water|flntu|flbbcd|oxy[a-z0-9]*|bb[a-z0-9]*)_[a-z_]+' \
  | sort -u
```

Typical Slocum payloads: `sci_ctd41cp` / `sci_water_*` = Sea-Bird CT;
`sci_flntu_*` = WET Labs FLNTU (chlorophyll + turbidity); `sci_flbbcd_*` =
WET Labs FLBBCD (chlorophyll + CDOM + backscatter); `sci_oxy4_*` = Aanderaa
optode.

> A sensor being *declared* in the header does not mean it *logged data*.
> Old missions often ran the CTD only, with an optics puck configured but
> disabled — confirm with Step 3's check.

**Deployment window** — plot depth vs time across all files:

```bash
.venv/bin/python - <<EOF
import dbdreader, numpy as np, matplotlib; matplotlib.use('Agg')
import matplotlib.pyplot as plt
from datetime import datetime, timezone
D = "$D/binary"
d = dbdreader.MultiDBD(pattern=f"{D}/*.dbd",
                       cacheDir="/Data/gfi/projects/slocum/data/cache")
t, z = d.get("m_depth")
plt.figure(figsize=(15, 5))
plt.plot([datetime.fromtimestamp(x, tz=timezone.utc) for x in t], z, ".", ms=1)
plt.gca().invert_yaxis(); plt.ylabel("m_depth [m]"); plt.grid(alpha=.3)
plt.tight_layout(); plt.savefig("/tmp/mission_depth.png", dpi=90)
print("data span:", datetime.utcfromtimestamp(t.min()),
      "->", datetime.utcfromtimestamp(t.max()))
EOF
```

Open `/tmp/mission_depth.png`. Old missions frequently contain **several
distinct periods** — bench tests, a pre-deployment checkout dive, then the
real deployment — with gaps between. Pick the window where the glider is
actually profiling continuously; check the science channels are on for it
(next step). The folder-name month is often wrong.

---

## Step 3 — write the mission config

```bash
M=python/missions/<NNN-mission-name>
mkdir -p "$M"
cp python/missions/002-gna_naco_faroe_jun2012/deployment.yml "$M"/
cp python/missions/002-gna_naco_faroe_jun2012/sensors.txt   "$M"/
```

Edit `$M/deployment.yml`:

| Field | Set to |
|---|---|
| `processing.l1_time_range` | `['<start>', '<end>']` — the deployment window from Step 2 (L2 follows L1) |
| `processing.l0_time_range` | `null` (L0 = all data) |
| `metadata.deployment_name` | `<NNN-mission-name>` |
| `metadata.deployment_id` | the mission number, as a string |
| `metadata.deployment_start` / `_end` | the window dates |
| `metadata.glider_name` | e.g. `snotra` |
| `metadata.glider_serial`, `glider_wmo`, `wmo_id` | from the glider record / OGDB |
| `metadata.institution` / `project` / `sea_name` | mission facts |
| `glider_devices.ctd.serial` + `profile_variables.instrument_ctd.serial_number` | the CT sensor serial assigned to this mission in OGDB |
| `glider_devices.ctd.calibration_date` | latest cal before launch (OGDB `asset_ct_sensor_cal`) |

The `# TODO` / `# OGDB-gap` comments in the file mark every field that will
eventually come from OGDB automatically — fill them by hand for now.

**Optics.** Mission 002 is CTD-only. If your mission's optics puck carries
real data:

```bash
.venv/bin/python -c "
import dbdreader, numpy as np
d = dbdreader.MultiDBD(pattern='$D/binary/*.ebd',
                       cacheDir='/Data/gfi/projects/slocum/data/cache')
for p in ['sci_flntu_chlor_units','sci_flntu_turb_units',
          'sci_flbbcd_chlor_units','sci_flbbcd_bb_units','sci_oxy4_oxygen']:
    try:
        t,v = d.get(p); print(f'{p:26} finite={np.isfinite(v).sum()}')
    except Exception: pass
"
```

For each channel with data, un-comment (or add) its block in
`netcdf_variables:` and the matching `instrument_*` block in
`profile_variables:`. Variable/attribute conventions: lowercase CF-derived
names, e.g. `chlorophyll` ← `sci_flntu_chlor_units`, `cdom` ←
`sci_flbbcd_cdom_units`, `oxygen_concentration` ← `sci_oxy4_oxygen`.

`sensors.txt` — the mission-002 copy (nav + attitude + engineering + CTD +
FLNTU, ~60 sensors) is a fine default. It drives the single decode pass;
L0 keeps all of it, L1 takes only what `deployment.yml` maps. Add a line
per extra channel you need in L0; the `u_`/`f_`/`cc_` config constants are
deliberately excluded (not timeseries data, and ~25× slower to decode).

---

## Step 4 — run

```bash
.venv/bin/slocum-process-mission <N> \
    --work /Data/gfi/projects/slocum/data/delayed/<NNN-mission-name>/pyglider
```

`<N>` is the mission number (or a `python/missions/` directory prefix).
Output lands in `pyglider/L0/`, `pyglider/L1/`, `pyglider/L2/`.

Useful flags:

- `--steps l1,l2` — skip L0 (e.g. re-running after a window change)
- `--binary <dir>` — if the binaries aren't at the derived path
- `-v` / `-vv` — info / debug logging

A full mission is ~1–3 minutes.

---

## Step 5 — check the output

```bash
.venv/bin/python - <<EOF
import xarray as xr, numpy as np, pandas as pd
d = "/Data/gfi/projects/slocum/data/delayed/<NNN-mission-name>/pyglider"
name = "<NNN-mission-name>"
for lvl in ["L0", "L1", "L2"]:
    ds = xr.open_dataset(f"{d}/{lvl}/{name}_{lvl}.nc")
    print(f"{lvl}: dims={dict(ds.dims)} "
          f"processing_level={ds.attrs.get('processing_level')}")
    for v in ("temperature", "salinity"):
        if v in ds:
            a = ds[v].values
            print(f"   {v}: p1..p99 = "
                  f"{np.nanpercentile(a,1):.3f} .. {np.nanpercentile(a,99):.3f}")
EOF
```

Sanity checks:

- L1 time span matches your window; L1 & L2 profile counts are non-zero.
- Temperature / salinity p1–p99 are physically plausible for the region
  (near-zero salinity spikes and slightly negative surface pressures are
  expected pre-QC artifacts).
- Plot it — adapt `plot_products.py` from a previous mission's scratch, or
  use `pyglider.utils.example_gridplot` on the L2 file.

If the window was wrong, edit `processing.l1_time_range` in `deployment.yml`
and re-run with `--steps l1,l2` (~90 s).

---

## Step 6 — commit the config

The per-mission `deployment.yml` + `sensors.txt` are version-controlled;
the NetCDF products are not (they live on `/Data`, regenerable from raw).

```bash
git add python/missions/<NNN-mission-name>/
git commit -m "Add mission <N> processing config"
```

---

## Downstream

Once L1/L2 exist, `norgliders-ERDDAP/ingest/ingest.py` registers them in
OGDB (`documents`) and transfers them to the ERDDAP server. That step is
separate from this pipeline and lives in that repo.
