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
cd ~/projects/norgliders-data-pipeline
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

(Or drive the `norgliders_data_pipeline.rawprep` functions directly from
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

Open `python/notebooks/data_exploration_l0.ipynb` on the L0 file: track,
depth-vs-time with a suggested start/stop window, and a summary of every
science channel that carried data. (`data_exploration.ipynb` is for
verifying L1/L2 once they exist — step 7 below.)

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

### `slocum-rawprep <N>`

| Flag | Default | Does |
|---|---|---|
| `--data-root DIR` | `[paths].data_root` in `processing.toml` | base to find `<NNN>-*/` under, when `--raw`/`--binary` aren't given explicitly |
| `--raw DIR` | `<mission folder>/raw` | override the input dir. With `--binary` also given, skips `--data-root`/mission lookup entirely — point at any two paths |
| `--binary DIR` | `<mission folder>/binary` | override the output dir (same override behaviour as `--raw`) |
| `--cache DIR` | `[paths].master_cache_dir` | the shared `.cac` library — read from (for step 4) and written to (for step 1's `.cac`/`.ccc` found in `raw/`) |
| `--compexp PATH` | `[paths].compexp` / `$SLOCUM_COMPEXP` | Teledyne's decompression tool. Only matters if `raw/` actually has Teledyne-compressed files (`*.dcd`/`*.ecd`/…) — decompression is a silent no-op otherwise |
| `--include-telemetry` | off | also stage `.sbd`/`.tbd`/`.mbd`/`.nbd` (+ their compressed forms) alongside `.dbd`/`.ebd`. Stages **all** binary types found, regardless of what `deployment.yml` is configured to actually process |
| `-v` / `-vv` | INFO | INFO / DEBUG logging. **A single `-v`/`--verbose` does nothing** — the level only steps up at `-vv` (`args.verbose > 1`) |

**Exit code**: `0` clean · `1` a referenced `.cac` couldn't be resolved (check the logged `missing:` list) · `2` compressed files present but no `compexp` configured.

Never reads `deployment.yml` — purely filesystem staging, driven only by these flags. `deployment.yml`'s `scisuffix`/`glidersuffix` are read later, by `slocum-process-mission`, and only decide which staged file types get *processed* — not which get staged here.

### `slocum-process-mission <N>`

| Flag | Default | Does |
|---|---|---|
| `--from-ogdb` | off | generate/use `<data folder>/deployment.yml` from OGDB, instead of the committed `python/missions/<NNN>-*/deployment.yml` |
| `--regenerate` | off | with `--from-ogdb`: refresh an *existing* file's OGDB-derived block (metadata/glider_devices/netcdf_variables/profile_variables) from OGDB again. The human `processing:` block — window, `unused_sensors`, everything you've hand-edited — is preserved verbatim, not touched. Without this flag, an existing file is used as-is and OGDB isn't queried at all |
| `--generate-only` | off | with `--from-ogdb`: write/refresh the config and stop — no L0/L1/L2/OG1 build |
| `--steps l0,l1,l2,og1` | `l0,l1,l2,og1` (all four) | comma list of which products to (re)build this run. `l2` needs an L1 file to exist (fresh or already on disk); `og1` needs L1 (+ L2 if built) and **deletes the CF L1/L2 it converts from** once done |
| `--binary DIR` | `<data_root>/<NNN-mission-name>/binary` | dir of `.dbd`/`.ebd`/… to read (whatever `deployment.yml`'s `glidersuffix`/`scisuffix` say) |
| `--work DIR` | `<data_root>/<NNN-mission-name>/pyglider` | output dir — `cache/`, `L0/`, `L1/`, `L2/`, `og1/` land here |
| `--data-root DIR` | `[paths].data_root` in `processing.toml` | base for auto-deriving the mission folder, `--binary`, and `--work` when those aren't given explicitly |
| `--database-url URL` | `DATABASE_URL` env / `[database].url` in `processing.toml` | OGDB connection string, only used with `--from-ogdb` |
| `-v` / `-vv` | INFO | same convention as `slocum-rawprep` — a single `-v` has no effect, `-vv` for DEBUG |

Without `--from-ogdb`, `<N>` reads the committed
`python/missions/<NNN>-*/deployment.yml` instead, and OGDB is never touched.

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
