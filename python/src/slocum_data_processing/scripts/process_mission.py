"""CLI: run delayed-mode processing for one Slocum mission.

    slocum-process-mission 2 \\
        --binary /Data/gfi/projects/slocum/data/delayed/002-gna_naco_faroe_jun2012/binary \\
        --work   /Data/gfi/projects/slocum/data/delayed/002-gna_naco_faroe_jun2012/pyglider

With no --binary/--work, paths are derived from --data-root and the mission
directory name.
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from ..delayed import trigger
from ..processing import config as _config

_DEFAULT_DATA_ROOT = Path("/Data/gfi/projects/slocum/data/delayed")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("mission", help="mission number, or a python/missions/ dir prefix")
    p.add_argument("--binary", type=Path, help="dir of *.dbd/*.ebd files")
    p.add_argument("--work", type=Path, help="work/output dir (rawnc, cache, L0/L1/L2)")
    p.add_argument("--data-root", type=Path, default=_DEFAULT_DATA_ROOT,
                   help=f"base for auto-derived paths (default: {_DEFAULT_DATA_ROOT})")
    p.add_argument("--steps", default="l0,l1,l2",
                   help="comma list of: l0,l1,l2 (default: l0,l1,l2)")
    p.add_argument("-v", "--verbose", action="count", default=0)
    args = p.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose > 1 else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    cfg = _config.load(args.mission)
    binary = args.binary or (args.data_root / cfg.mission_dir.name / "binary")
    work = args.work or (args.data_root / cfg.mission_dir.name / "pyglider")

    if not binary.is_dir():
        p.error(f"binary dir not found: {binary}")

    prod = trigger.run_for_mission(
        args.mission, binary, work,
        steps=tuple(s.strip() for s in args.steps.split(",") if s.strip()),
    )
    print("\n=== products ===")
    print(f"L0: {prod.l0}")
    print(f"L1: {prod.l1}")
    print(f"L2: {', '.join(map(str, prod.l2)) or '(none)'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
