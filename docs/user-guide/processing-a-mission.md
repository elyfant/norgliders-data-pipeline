# Processing a Slocum mission (delayed mode)

Raw glider binaries → L0/L1/L2 NetCDF, via the `slocum-process-mission` CLI.

| Level | What | Window |
|---|---|---|
| **L0** | Full decoded archive — every binary file, flight + science merged, raw Slocum names, no derived vars, no QC. | all data |
| **L1** | `pyglider` timeseries: CF/OG1 names, TEOS-10 salinity & density, profile index. | deployment window |
| **L2** | L1 gridded time × depth. | deployment window |

QC is a separate later step. Worked references: `python/missions/002-…`, `028-…`.

---

## Setup (once)

```bash
cd ~/projects/slocum_data_processing
source .venv/bin/activate            # python3 -m venv .venv  if missing
pip install -e "python/[notebook]"   # pyglider 0.0.7 + dbdreader + CLI + notebook deps
```

Paths and the OGDB connection come from `config/processing.toml`
(`[paths].data_root` = `/Data/gfi/projects/slocum/data/delayed`,
`[database].url` = local snapshot). Override per-machine in
`config/processing.local.toml`, or with env vars (`SLOCUM_DATA_ROOT`,
`DATABASE_URL`).

To resolve against **production** OGDB, open a tunnel and export its URL:

```bash
ssh -N -L 5555:localhost:5432 nrec_app &
export DATABASE_URL="postgresql://ogdb:<pw>@localhost:5555/ogdb"
```

---

## 1. Stage the binaries

Full `.dbd` (flight) + `.ebd` (science) files into
`<data_root>/<NNN-mission-name>/binary/`. `raw/` is the untouched archive.

Raw-prep (offload → flat `binary/`, decompress, rename, cache-sync) is the
`slocum_data_processing.rawprep` module — run it from
`python/notebooks/mission_processing.ipynb`.

Sanity-check coverage: a real deployment is hundreds of files over weeks.

---

## 2. Generate the config from OGDB

```bash
slocum-process-mission <N> --from-ogdb --generate-only
```

Writes `<data_root>/<NNN-mission-name>/deployment.yml`: the OGDB-derived
block (metadata, sensors, calibrations) plus a human-owned `processing:`
block (window + knobs) seeded from OGDB launch/recovery dates.

---

## 3. First pass — L0, then inspect

```bash
slocum-process-mission <N> --from-ogdb --steps l0
```

Watch the log: a sensor OGDB assigns to the glider but that logged no data
this deployment is flagged here (warning / note).

Open `python/notebooks/data_exploration.ipynb` on the L0 file: check the
depth-vs-time track, decide the real **start/stop**, confirm which science
channels carried data.

---

## 4. Set the window, run

Edit the `processing:` block of the generated `deployment.yml`:

```yaml
processing:
  l1_time_range: ['2017-09-06', '2017-09-13']   # real window from L0
  unused_sensors: [optics]                       # optional: aboard per OGDB, logged nothing
```

`unused_sensors` keeps the sensor's data variables (fill values, documenting
the channel) but drops its instrument metadata / calibration claims.

```bash
slocum-process-mission <N> --from-ogdb --regenerate
```

`--regenerate` refreshes the OGDB block and **keeps your `processing:` block**,
then runs L0 → L1 → L2 into `<data_root>/<NNN-mission-name>/pyglider/{L0,L1,L2}/`
(~1–3 min).

Iterate on just the window (no OGDB re-query, no L0 rebuild):

```bash
# edit l1_time_range, then:
slocum-process-mission <N> --from-ogdb --steps l1,l2
```

---

## 5. Check & commit

Verify in `data_exploration.ipynb`: L1 span matches the window, profile
counts non-zero, T/S ranges physically plausible (pre-QC).

The `deployment.yml` (with its `processing:` block) is the versioned
artifact; NetCDF products are not (regenerable from raw).

```bash
cp <data_root>/<NNN-mission-name>/deployment.yml python/missions/<NNN-mission-name>/
git add python/missions/<NNN-mission-name>/
git commit -m "Mission <N>: processing config"
```

---

## Flags

| Flag | |
|---|---|
| `--from-ogdb` | generate/use `<data folder>/deployment.yml` from OGDB |
| `--regenerate` | refresh the OGDB block of an existing file (keeps `processing:`) |
| `--generate-only` | write the config and stop |
| `--steps l0` / `l1,l2` | run a subset |
| `--binary DIR` / `--work DIR` | override derived paths |
| `--database-url URL` | OGDB connection (else `DATABASE_URL` / `processing.toml`) |
| `-v` / `-vv` | info / debug logging |

Without `--from-ogdb`, `<N>` reads the committed
`python/missions/<NNN>-*/deployment.yml` instead.

---

## Downstream

`norgliders-ERDDAP/ingest/ingest.py` registers L1/L2 in OGDB (`documents`)
and transfers them to the ERDDAP server — separate from this pipeline.
