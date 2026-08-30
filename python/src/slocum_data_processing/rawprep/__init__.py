"""Prepare a raw Slocum flashcard / telemetry dump into a clean ``binary/`` dir.

This is the manual delayed-mode entry point (facility "Raw Data Ingestion",
the flashcard-offload path — the live SFMC/rsync path lives in ``js/``).

Workflow, in order:

1. :func:`copy_raw_to_binary` — recursively pull the binary + log + cache
   files out of a ``raw/`` archive (any directory layout) into a flat
   ``binary/`` working dir.
2. :func:`decompress_dir` — expand Teledyne-compressed ``*.[dest]cd`` files
   (only if present; needs the ``compexp`` tool).
3. :func:`rename_to_full_filenames` — 8x3 DOS names (``00070000.dbd``) ->
   full names (``snotra-2012-071-0-0.dbd``), from each file's header.
4. :func:`sync_cache_files` — make sure the ``.cac`` sensor-list cache each
   binary needs is available (for compressed ``.sbd``/``.tbd``; the full
   ``.dbd``/``.ebd`` carry their list inline and need none).

:func:`inventory` counts file types across directories so you can check
``raw`` vs ``binary`` coverage.

After this the ``binary/`` dir is ready for
``slocum_data_processing.processing`` / dbdreader / pyglider.
"""

from __future__ import annotations

from .headers import DbdHeader, HeaderError, read_header
from .stage import (
    CacheReport,
    RenameReport,
    copy_raw_to_binary,
    decompress_dir,
    inventory,
    rename_to_full_filenames,
    sync_cache_files,
)

__all__ = [
    "DbdHeader",
    "HeaderError",
    "read_header",
    "CacheReport",
    "RenameReport",
    "copy_raw_to_binary",
    "decompress_dir",
    "inventory",
    "rename_to_full_filenames",
    "sync_cache_files",
]
