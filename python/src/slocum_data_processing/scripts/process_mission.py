"""CLI: run delayed-mode processing for one Slocum mission.

    slocum-process-mission 28                       # L0 -> L1 -> L2
    slocum-process-mission 28 --steps l0            # just L0 (inspect, then...)
    slocum-process-mission 28 --steps l1,l2         # ...window set, finish

Config source (decision 0003):
    default        : a committed python/missions/<NNN>-*/deployment.yml
    --from-ogdb    : generate <data folder>/deployment.yml from OGDB first,
                     then process from there. --regenerate refreshes the
                     OGDB-derived block, keeping your processing: block.
    --generate-only: write the deployment.yml and stop.

Paths default from config/processing.toml ([paths].data_root); override with
--binary / --work or the SLOCUM_DATA_ROOT env var.
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from ..delayed import trigger
from ..processing import config as _config
from ..settings import load_settings


def main(argv: list[str] | None = None) -> int:
    s = load_settings()
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("mission", help="mission number (28) or a folder-name prefix")
    p.add_argument("--from-ogdb", action="store_true",
                   help="generate <data folder>/deployment.yml from OGDB, then use it")
    p.add_argument("--regenerate", action="store_true",
                   help="with --from-ogdb: refresh the OGDB block of an existing file")
    p.add_argument("--generate-only", action="store_true",
                   help="with --from-ogdb: write the deployment.yml and stop")
    p.add_argument("--binary", type=Path, help="dir of *.dbd/*.ebd files")
    p.add_argument("--work", type=Path, help="work/output dir (cache, L0/L1/L2)")
    p.add_argument("--data-root", type=Path, default=s.data_root,
                   help=f"base for auto-derived paths (default: {s.data_root})")
    p.add_argument("--database-url", help="OGDB connection (else DATABASE_URL / config)")
    p.add_argument("--steps", default="l0,l1,l2", help="comma list of l0,l1,l2")
    p.add_argument("-v", "--verbose", action="count", default=0)
    args = p.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose > 1 else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    log = logging.getLogger("slocum-process-mission")

    # locate the mission data folder by <NNN>-* prefix under data_root
    try:
        data_folder = next(
            d for d in sorted(args.data_root.glob(
                f"{int(args.mission):03d}*" if str(args.mission).isdigit()
                else f"{args.mission}*")) if d.is_dir())
    except (StopIteration, ValueError):
        data_folder = None

    binary = args.binary or (data_folder / "binary" if data_folder else None)
    work = args.work or (data_folder / "pyglider" if data_folder else None)

    if args.from_ogdb:
        if data_folder is None:
            p.error(f"no data folder under {args.data_root} for mission {args.mission!r}")
        target = data_folder / "deployment.yml"
        if not target.exists() or args.regenerate:
            path, warnings = _config.write_deployment_yaml(
                int(args.mission), target,
                regenerate=args.regenerate, database_url=args.database_url,
                binary_dir=binary if binary and binary.is_dir() else None,
            )
            log.info("wrote %s", path)
            for w in warnings:
                log.warning("%s", w)
        else:
            log.info("using existing %s (pass --regenerate to refresh from OGDB)", target)
        cfg_src = data_folder
        if args.generate_only:
            return 0
    else:
        cfg_src = args.mission   # -> python/missions/<NNN>-*/

    cfg = _config.load(cfg_src)
    binary = binary or (args.data_root / cfg.mission_dir.name / "binary")
    work = work or (args.data_root / cfg.mission_dir.name / "pyglider")
    if not Path(binary).is_dir():
        p.error(f"binary dir not found: {binary} (run raw prep first)")

    prod = trigger.run_for_mission(
        cfg_src, binary, work,
        steps=tuple(x.strip() for x in args.steps.split(",") if x.strip()),
    )
    print("\n=== products ===")
    print(f"L0: {prod.l0}")
    print(f"L1: {prod.l1}")
    print(f"L2: {', '.join(map(str, prod.l2)) or '(none)'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
