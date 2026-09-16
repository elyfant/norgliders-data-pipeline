"""Read the ASCII header of a Slocum dinkum binary file (``*.dbd`` / ``*.ebd`` /
``*.sbd`` / ``*.tbd`` / ...).

Every dinkum binary starts with a run of ``key: value`` text lines before the
binary payload. This reads just that header. Adapted from pyglider's
``pyglider.slocum.dbd_get_meta``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


class HeaderError(ValueError):
    """The file has no readable dinkum header."""


@dataclass(frozen=True)
class DbdHeader:
    """Parsed dinkum header fields (the ones we actually use)."""

    the8x3_filename: str          # DOS-style card name, e.g. "00070000"
    full_filename: str            # segment name, e.g. "snotra-2012-071-0-0"
    filename_extension: str       # "dbd", "ebd", ...
    mission_name: str             # e.g. "lastgasp.mi"
    fileopen_time: str            # e.g. "Mon_Mar_12_08:46:32_2012"
    sensor_list_crc: str          # identifies the .cac cache file
    sensor_list_factored: bool    # True -> sensor list is external (.cac); False -> inline
    raw: dict[str, str] = field(repr=False, default_factory=dict)

    @property
    def cache_name(self) -> str:
        """Lowercase ``<crc>.cac`` — the cache file this segment decodes with."""
        return f"{self.sensor_list_crc.lower()}.cac"


def read_header(path: str | Path, *, max_lines: int = 99) -> DbdHeader:
    """Parse the header of one dinkum binary file.

    Raises
    ------
    HeaderError
        If the file is empty, not decodable as ASCII, or missing the
        ``the8x3_filename`` / ``full_filename`` tags (i.e. not a dinkum
        binary, or a corrupt/truncated one).
    """
    path = Path(path)
    if path.stat().st_size == 0:
        raise HeaderError(f"{path.name}: empty file")

    meta: dict[str, str] = {}
    with path.open("rb") as fh:
        for _ in range(max_lines):
            line = fh.readline()
            if b":" not in line:
                break
            try:
                key, _, value = line.decode("ascii").partition(":")
            except UnicodeDecodeError:
                break
            meta[key.strip()] = value.strip()
            expected = meta.get("num_ascii_tags")
            if expected and len(meta) >= int(expected):
                break

    missing = [k for k in ("the8x3_filename", "full_filename") if k not in meta]
    if missing:
        raise HeaderError(f"{path.name}: header missing {missing} "
                          f"(not a dinkum binary, or truncated)")

    return DbdHeader(
        the8x3_filename=meta["the8x3_filename"],
        full_filename=meta["full_filename"],
        filename_extension=meta.get("filename_extension", path.suffix.lstrip(".")).lower(),
        mission_name=meta.get("mission_name", ""),
        fileopen_time=meta.get("fileopen_time", ""),
        sensor_list_crc=meta.get("sensor_list_crc", ""),
        sensor_list_factored=meta.get("sensor_list_factored", "0") not in ("0", ""),
        raw=meta,
    )
