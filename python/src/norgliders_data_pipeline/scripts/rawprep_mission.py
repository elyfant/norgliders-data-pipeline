"""CLI: stage a raw Slocum dump into a clean ``binary/`` dir for processing.

    slocum-rawprep 28                    # <data_root>/028-*/raw  ->  .../028-*/binary
    slocum-rawprep 28 --include-telemetry
    slocum-rawprep 28 --raw /path/to/dump --binary /path/to/binary

Steps, in order (each idempotent):

  1. copy        raw/ (any layout) -> flat binary/ ; cache files -> master cache
  2. decompress  *.[dest]cd -> *.[dest]bd   (needs compexp; no-op if none present)
  3. rename      8x3 DOS names -> full segment names, read from each file header
  4. cache       ensure every referenced *.cac is on disk or carried inline

Paths and the compexp tool default from ``config/processing.toml``; override
with flags or env vars (SLOCUM_DATA_ROOT, SLOCUM_CACHE_DIR, SLOCUM_COMPEXP).
Exit status is non-zero if a needed sensor-list cache can't be resolved.
"""

from __future__ import annotations

import argparse
import logging
from collections import Counter
from pathlib import Path

from .. import rawprep
from ..settings import load_settings


def _fmt(counter: Counter) -> str:
    return ", ".join(f"{n}{ext}" for ext, n in sorted(counter.items())) or "nothing"


def _find_mission_folder(data_root: Path, mission: str) -> Path | None:
    token = f"{int(mission):03d}" if str(mission).isdigit() else str(mission)
    try:
        return next(d for d in sorted(data_root.glob(f"{token}*")) if d.is_dir())
    except StopIteration:
        return None


def main(argv: list[str] | None = None) -> int:
    s = load_settings()
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("mission", help="mission number (28) or a folder-name prefix")
    p.add_argument("--data-root", type=Path, default=s.data_root,
                   help=f"base for <NNN>-*/ folders (default: {s.data_root})")
    p.add_argument("--raw", type=Path, help="raw dump dir (default: <mission folder>/raw)")
    p.add_argument("--binary", type=Path,
                   help="output binary dir (default: <mission folder>/binary)")
    p.add_argument("--cache", type=Path, default=s.master_cache_dir,
                   help=f"master .cac cache (default: {s.master_cache_dir})")
    p.add_argument("--compexp", type=Path, default=s.compexp,
                   help="Teledyne compexp tool (default: config / $SLOCUM_COMPEXP)")
    p.add_argument("--include-telemetry", action="store_true",
                   help="also stage compressed telemetry binaries (*.sbd/*.tbd/...)")
    p.add_argument("-v", "--verbose", action="count", default=0)
    args = p.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose > 1 else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    log = logging.getLogger("slocum-rawprep")

    folder = _find_mission_folder(args.data_root, args.mission)
    raw_dir = args.raw or (folder / "raw" if folder else None)
    binary_dir = args.binary or (folder / "binary" if folder else None)
    if raw_dir is None or binary_dir is None:
        p.error(
            f"no folder under {args.data_root} matching {args.mission!r} -- "
            f"pass --raw and --binary explicitly"
        )
    logs_dir = (folder / "logs") if folder else binary_dir.parent / "logs"
    cache_out = (folder / "pyglider" / "cache") if folder else binary_dir.parent / "cache"

    if not Path(raw_dir).is_dir():
        p.error(f"raw dir not found: {raw_dir}")

    inv = rawprep.inventory(raw_dir, binary_dir)
    log.info("raw:    %s", _fmt(inv[str(raw_dir)]))

    # 1. copy
    rawprep.copy_raw_to_binary(raw_dir, binary_dir, args.cache,
                               include_telemetry=args.include_telemetry)

    # 2. decompress
    try:
        rawprep.decompress_dir(binary_dir, compexp=args.compexp)
    except FileNotFoundError as exc:
        log.error("%s", exc)
        return 2

    # 3. rename
    rename = rawprep.rename_to_full_filenames(binary_dir, logs_dir=logs_dir)
    if rename.quarantined:
        log.warning("quarantined %d unreadable file(s): %s",
                    len(rename.quarantined), ", ".join(sorted(rename.quarantined)))

    # 4. cache
    cache = rawprep.sync_cache_files(binary_dir, args.cache, cache_dir=cache_out)

    inv = rawprep.inventory(raw_dir, binary_dir)
    log.info("binary: %s", _fmt(inv[str(binary_dir)]))

    if not cache.ok:
        log.error("cache unresolved (referenced, not on disk, not inline): %s",
                  ", ".join(sorted(cache.missing)))
        return 1

    print(f"\nstaged: {binary_dir}")
    print(f"next:   slocum-process-mission {args.mission} --from-ogdb")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
