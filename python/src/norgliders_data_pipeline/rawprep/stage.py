"""Staging steps: raw dump -> clean ``binary/`` dir. See package docstring."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from .headers import HeaderError, read_header

log = logging.getLogger(__name__)

# Teledyne-compressed extension -> its decompressed form.
COMPRESSED_EXT = {
    ".scd": ".sbd", ".mcd": ".mbd", ".tcd": ".tbd", ".ncd": ".nbd",
    ".dcd": ".dbd", ".ecd": ".ebd", ".mcg": ".mlg", ".ncg": ".nlg",
    ".ccc": ".cac",
}
FULL_BINARY_EXT = (".dbd", ".ebd")
TELEMETRY_BINARY_EXT = (".sbd", ".tbd", ".mbd", ".nbd")
LOG_EXT = (".mlg", ".nlg")
CACHE_EXT = (".cac",)


# --------------------------------------------------------------------------
# reports
# --------------------------------------------------------------------------
@dataclass
class RenameReport:
    renamed: dict[str, str] = field(default_factory=dict)   # old name -> new name
    quarantined: list[str] = field(default_factory=list)
    logs_renamed: dict[str, str] = field(default_factory=dict)


@dataclass
class CacheReport:
    needed: set[str] = field(default_factory=set)           # CRCs referenced by factored files
    present: set[str] = field(default_factory=set)          # already in cache_dir
    copied: dict[str, str] = field(default_factory=dict)    # cache name -> source path
    inline: set[str] = field(default_factory=set)           # sensor list carried inline by another file in the set
    missing: set[str] = field(default_factory=set)          # not in cache_dir, master, or inline anywhere

    @property
    def ok(self) -> bool:
        """True if every needed cache is satisfiable (on disk or reconstructable
        from an inline file — dbdreader/pyglider build those automatically)."""
        return not self.missing


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _iter_files(directory: Path, suffixes) -> list[Path]:
    """Recursive, case-insensitive suffix match."""
    want = {s.lower() for s in suffixes}
    return sorted(
        p for p in directory.rglob("*")
        if p.is_file() and p.suffix.lower() in want
    )


def _resolve_tool(explicit, env_var: str, name: str) -> Path:
    candidate = explicit or os.environ.get(env_var)
    if not candidate:
        raise FileNotFoundError(
            f"{name} not provided — pass it explicitly or set ${env_var}. "
            f"It is a Teledyne tool, not distributed with this repo."
        )
    path = Path(candidate)
    if not path.is_file():
        raise FileNotFoundError(f"{name} not found at {path}")
    return path


# --------------------------------------------------------------------------
# 1. copy
# --------------------------------------------------------------------------
def copy_raw_to_binary(
    raw_dir: str | Path,
    binary_dir: str | Path,
    master_cache_dir: str | Path,
    *,
    include_telemetry: bool = False,
    include_compressed: bool = True,
) -> Counter:
    """Recursively copy binary + log + cache files out of ``raw_dir`` into a
    flat ``binary_dir`` (cache files go to ``master_cache_dir``).

    ``raw_dir`` may have any internal layout (per-card, per-glider, ...).
    Existing files are overwritten (idempotent). Returns a count per suffix.

    Parameters
    ----------
    include_telemetry
        Also copy the compressed-telemetry binaries (``*.sbd`` / ``*.tbd`` /
        ``*.mbd`` / ``*.nbd`` and their ``*.[smn]cd`` compressed forms).
        Default False — most delayed-mode work uses the full ``*.dbd`` /
        ``*.ebd`` only.
    include_compressed
        Also copy Teledyne-compressed forms (``*.dcd`` / ``*.ecd`` / ...);
        :func:`decompress_dir` expands them afterwards.
    """
    raw_dir, binary_dir = Path(raw_dir), Path(binary_dir)
    master_cache_dir = Path(master_cache_dir)
    if not raw_dir.is_dir():
        raise FileNotFoundError(f"raw_dir not found: {raw_dir}")
    binary_dir.mkdir(parents=True, exist_ok=True)
    master_cache_dir.mkdir(parents=True, exist_ok=True)

    binary_ext = list(FULL_BINARY_EXT)
    if include_telemetry:
        binary_ext += list(TELEMETRY_BINARY_EXT)
    if include_compressed:
        binary_ext += [c for c, d in COMPRESSED_EXT.items() if d in binary_ext]

    counts: Counter = Counter()
    plan = [
        (binary_ext, binary_dir),
        (list(LOG_EXT) + [".mcg", ".ncg"], binary_dir),
        (list(CACHE_EXT) + [".ccc"], master_cache_dir),
    ]
    for suffixes, dest in plan:
        for src in _iter_files(raw_dir, suffixes):
            shutil.copy2(src, dest / src.name)
            counts[src.suffix.lower()] += 1

    log.info("copied from %s: %s", raw_dir,
             ", ".join(f"{n}{ext}" for ext, n in sorted(counts.items())) or "nothing")
    return counts


# --------------------------------------------------------------------------
# 2. decompress
# --------------------------------------------------------------------------
def decompress_dir(
    directory: str | Path,
    *,
    compexp: str | Path | None = None,
    remove_compressed: bool = True,
) -> list[Path]:
    """Expand every Teledyne-compressed ``*.[dest]cd`` file in ``directory``.

    ``compexp`` is Teledyne's decompression tool (or set ``$SLOCUM_COMPEXP``).
    No-op if nothing is compressed. Returns the decompressed paths.
    """
    directory = Path(directory)
    targets = _iter_files(directory, COMPRESSED_EXT.keys())
    if not targets:
        log.info("decompress: no compressed files in %s", directory)
        return []

    tool = _resolve_tool(compexp, "SLOCUM_COMPEXP", "compexp")
    done: list[Path] = []
    for src in targets:
        dst = src.with_suffix(COMPRESSED_EXT[src.suffix.lower()])
        subprocess.run([str(tool), "x", str(src), str(dst)],
                       check=True, capture_output=True)
        if remove_compressed:
            src.unlink()
        done.append(dst)
    log.info("decompressed %d files in %s", len(done), directory)
    return done


# --------------------------------------------------------------------------
# 3. rename
# --------------------------------------------------------------------------
def rename_to_full_filenames(
    binary_dir: str | Path,
    *,
    logs_dir: str | Path | None = None,
    quarantine_dir: str | Path | None = None,
) -> RenameReport:
    """Rename 8x3 DOS-named binaries to their full segment name, from each
    file's header (``00070000.dbd`` -> ``snotra-2012-071-0-0.dbd``).

    Matching ``*.mlg`` / ``*.nlg`` log files (same 8x3 stem) are renamed to
    match, then moved to ``logs_dir`` if given. Files with no readable header
    (empty / corrupt) are moved to ``quarantine_dir`` (default
    ``binary_dir/unused``). Files already using the full name are left alone.
    Idempotent.
    """
    binary_dir = Path(binary_dir)
    quarantine_dir = Path(quarantine_dir) if quarantine_dir else binary_dir / "unused"
    report = RenameReport()

    binaries = _iter_files(binary_dir, FULL_BINARY_EXT + TELEMETRY_BINARY_EXT)
    binaries = [p for p in binaries if p.parent == binary_dir]

    for path in binaries:
        try:
            header = read_header(path)
        except HeaderError as exc:
            log.warning("quarantining %s: %s", path.name, exc)
            quarantine_dir.mkdir(parents=True, exist_ok=True)
            shutil.move(str(path), quarantine_dir / path.name)
            report.quarantined.append(path.name)
            continue

        stem_now = path.stem.lower()
        if stem_now == header.full_filename.lower():
            continue  # already renamed

        new_path = path.with_name(header.full_filename + path.suffix.lower())
        path.rename(new_path)
        report.renamed[path.name] = new_path.name

        # rename sibling log files sharing the 8x3 stem
        for log_ext in LOG_EXT:
            for cand in (binary_dir / f"{header.the8x3_filename}{log_ext}",
                         binary_dir / f"{header.the8x3_filename}{log_ext.upper()}"):
                if cand.is_file():
                    new_log = cand.with_name(header.full_filename + log_ext)
                    cand.rename(new_log)
                    report.logs_renamed[cand.name] = new_log.name

    if logs_dir is not None:
        logs_dir = Path(logs_dir)
        logs_dir.mkdir(parents=True, exist_ok=True)
        for log_file in _iter_files(binary_dir, LOG_EXT):
            if log_file.parent == binary_dir:
                shutil.move(str(log_file), logs_dir / log_file.name)

    log.info("renamed %d binaries, %d logs; quarantined %d",
             len(report.renamed), len(report.logs_renamed), len(report.quarantined))
    return report


# --------------------------------------------------------------------------
# 4. cache sync
# --------------------------------------------------------------------------
def sync_cache_files(
    binary_dir: str | Path,
    master_cache_dir: str | Path,
    *,
    cache_dir: str | Path | None = None,
) -> CacheReport:
    """Ensure every ``.cac`` sensor-list cache the binaries need is available.

    Reads each binary's header for its ``sensor_list_crc``, then copies the
    matching ``<crc>.cac`` from ``master_cache_dir`` into ``cache_dir``
    (default ``binary_dir/cache``). Full ``.dbd``/``.ebd`` with an inline
    sensor list contribute no requirement. Returns a :class:`CacheReport` —
    check ``.ok`` / ``.missing`` before decoding compressed telemetry.
    """
    binary_dir = Path(binary_dir)
    master_cache_dir = Path(master_cache_dir)
    cache_dir = Path(cache_dir) if cache_dir else binary_dir / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    report = CacheReport()

    # A Slocum segment carries its full sensor list inline on the first file
    # after a science-computer reboot (sensor_list_factored = 0); later files
    # in that run reference it by CRC (factored = 1). dbdreader/pyglider
    # rebuild the .cac from an inline file automatically, so a referenced CRC
    # is only truly missing if nothing carries it inline either.
    for path in _iter_files(binary_dir, FULL_BINARY_EXT + TELEMETRY_BINARY_EXT):
        try:
            header = read_header(path)
        except HeaderError:
            continue
        if not header.sensor_list_crc:
            continue
        if header.sensor_list_factored:
            report.needed.add(header.cache_name)
        else:
            report.inline.add(header.cache_name)

    for name in report.needed:
        if (cache_dir / name).is_file():
            report.present.add(name)
            continue
        for candidate in (master_cache_dir / name,
                          master_cache_dir / name.upper(),
                          master_cache_dir / name.replace(".cac", ".CAC")):
            if candidate.is_file():
                shutil.copy2(candidate, cache_dir / name)
                report.copied[name] = str(candidate)
                break
        else:
            if name not in report.inline:
                report.missing.add(name)

    if report.missing:
        log.warning("cache: %d referenced file(s) unavailable and not inline: %s",
                    len(report.missing), ", ".join(sorted(report.missing)))
    else:
        log.info("cache: %d referenced, %d on disk, %d reconstructable from inline files",
                 len(report.needed), len(report.present) + len(report.copied),
                 len(report.needed & report.inline))
    return report


# --------------------------------------------------------------------------
# inventory
# --------------------------------------------------------------------------
def inventory(*directories: str | Path) -> dict[str, Counter]:
    """Count files by suffix in each directory (recursive). For comparing
    ``raw`` vs ``binary`` coverage."""
    out: dict[str, Counter] = {}
    for d in directories:
        d = Path(d)
        c: Counter = Counter()
        if d.is_dir():
            for p in d.rglob("*"):
                if p.is_file():
                    c[p.suffix.lower() or "(none)"] += 1
        out[str(d)] = c
    return out
