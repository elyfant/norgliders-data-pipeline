# Processing a Slocum mission (delayed mode)

Raw glider binaries → L0/L1/L2/OG1 NetCDF, via the `slocum-process-mission` CLI.

| Level | What | Window |
|---|---|---|
| **L0** | Full decoded archive — every binary file, flight + science merged, raw Slocum names, no derived vars, no QC. | all data |
| **L1** | `pyglider` timeseries: CF names (`temperature`, `conductivity`, …), TEOS-10 salinity & density, profile index. **Not OG1** — see OG1 row. | deployment window |
| **L2** | L1 gridded time × depth. Also CF-named. | deployment window |
| **OG1** | L1 and L2, variables renamed to OG1.0 vocabulary (`TEMP`, `CNDC`, …) — see `og1/convert.py`. Unmapped variables are kept under their CF name, never dropped. | same as L1/L2 |

**Only L0 and OG1 persist.** Running the `og1` step deletes the CF L1/L2
files it converted from — they're pyglider intermediates, not a wanted
final product, and fully reproducible from L0 + `deployment.yml`. Don't
include `og1` in a step list until you're done inspecting L1/L2 (see
step 4) — once it runs, they're gone.

QC is a separate later step. Worked references: `python/missions/002-…`, `028-…`.

---

## Setup (once)

```bash
cd ~/projects/slocum_data_processing
source .venv/bin/activate            # python3 -m venv .venv  if missing
pip install -e "python/[notebook]"   # pyglider 0.0.9 + dbdreader + CLI + notebook deps
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

Drop the raw flashcard / telemetry dump (any folder layout) into
`<data_root>/<NNN-mission-name>/raw/`, then:

```bash
slocum-rawprep <N>
```

Runs, in order: copy `raw/` → flat `binary/` · decompress `*.[dest]cd`
(needs `compexp` / `$SLOCUM_COMPEXP`; no-op if none) · rename 8×3 DOS names
to full segment names from each header · verify every referenced `.cac` is
on disk or inline. Idempotent; non-zero exit if a cache can't be resolved.

`--include-telemetry` also stages `*.sbd`/`*.tbd`; `--raw` / `--binary`
override the derived paths. Sanity-check coverage — a real deployment is
hundreds of files over weeks.

(Or drive the `slocum_data_processing.rawprep` functions directly from
`python/notebooks/mission_processing.ipynb`.)

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
slocum-process-mission <N> --from-ogdb --regenerate --steps l0,l1,l2
```

`--regenerate` refreshes the OGDB block and **keeps your `processing:` block**,
then runs L0 → L1 → L2 (~1–3 min). **Deliberately not `og1` yet** — L1/L2
are still CF-named on disk at this point, for inspection in step 5.

Iterate on just the window (no OGDB re-query, no L0 rebuild):

```bash
# edit l1_time_range, then:
slocum-process-mission <N> --from-ogdb --steps l1,l2
```

---

## 5. Check, finalize to OG1, commit

Verify in `data_exploration.ipynb`: L1 span matches the window, profile
counts non-zero, T/S ranges physically plausible (pre-QC).

Happy with the window? Finalize — this deletes the CF L1/L2 you just
inspected, leaving only L0 and OG1 on disk:

```bash
slocum-process-mission <N> --from-ogdb --steps og1
```

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
| `--steps l0` / `l1,l2` / `og1` | run a subset. Only include `og1` once you're done inspecting L1/L2 — it deletes them. |
| `--binary DIR` / `--work DIR` | override derived paths |
| `--database-url URL` | OGDB connection (else `DATABASE_URL` / `processing.toml`) |
| `-v` / `-vv` | info / debug logging |

Without `--from-ogdb`, `<N>` reads the committed
`python/missions/<NNN>-*/deployment.yml` instead.

---

## Downstream

`norgliders-ERDDAP/ingest/ingest.py` registers L1/L2 in OGDB (`documents`)
and transfers them to the ERDDAP server — separate from this pipeline.

**Known gap, not yet fixed (2026-09-12):** now that CF L1/L2 are deleted
and only OG1 persists, `norgliders-ERDDAP/ingest/ingest.py` and
`OGDB/scripts/ingest_slocum_mission.py` both still expect CF-named L2
(`temperature`, `salinity`, `profile_direction`, ...) — they'll fail
against an OG1-named file (`TEMP`, `PSAL`, `PROFILE_DIRECTION`, ...).
Update those two scripts (or point them at the OG1 file with updated
variable names) before ingesting a mission processed under this change.
