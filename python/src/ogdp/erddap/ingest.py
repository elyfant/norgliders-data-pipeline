"""Ingest an L1/L2 NetCDF file: register its metadata in OGDB, then SFTP
it to the ERDDAP server.

Dry-run by default, --commit to actually write/transfer -- same
convention as OGDB's own backfill scripts (scripts/backfill_phase1_
assets.py and siblings), including the same lesson learned there: the
report of what *would* happen is built unconditionally, not gated behind
`if commit`.

Order of operations, and why: register the OGDB document BEFORE the SFTP
transfer, not after. If the transfer fails partway, OGDB records a
document whose file isn't live on ERDDAP yet -- a visible, honest gap.
The reverse order (transfer first) risks the opposite: a file that's
live on ERDDAP with OGDB never told, which is exactly the "goes stale"
failure mode this whole pipeline exists to avoid. A gap you can see
beats a lie you can't.

Confirming the ERDDAP push (erddap_pushes) happens last, and only with
--confirm-live, kept as a separate explicit step rather than automatic --
this script controls getting the file and its metadata to where they
belong; whether what's live on ERDDAP right now genuinely serves this
file (dataset fragment written, container restarted/reloaded) is a
separate fact this script cannot itself verify, so it doesn't assert it
by default.

Required environment variables (all in --commit mode; none needed for a
dry run beyond the file path itself):
  OGDB_GATEWAY_URL        e.g. http://localhost:3001
  OGDB_SERVICE_EMAIL      a real user with role='editor' or 'admin'
  OGDB_SERVICE_PASSWORD
  ERDDAP_SFTP_HOST        e.g. 158.39.77.95
  ERDDAP_SFTP_USER
  ERDDAP_SFTP_KEY_PATH    the restricted, SFTP-only key -- not the
                          general admin key used to manage the box
"""

from __future__ import annotations

import argparse
import os
import sys

from .gateway_client import GatewayClient, GatewayError, NetcdfMetadata
from .inspect_netcdf import inspect_netcdf
from .sftp_transfer import upload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("mission_id", type=int, help="OGDB mission id")
    parser.add_argument("stage", choices=["DM", "PUB"], help="Processing maturity this file represents")
    parser.add_argument("path", help="Path to the local L1/L2 NetCDF file")
    parser.add_argument(
        "mission_slug",
        help="Directory name under /data/ogdp/processed/{level}/ on the ERDDAP "
        "server for this mission (matches the fileDir in the mission's "
        "datasets.d fragment) -- not auto-derived, since the two conventions "
        "(pyglider vs. seaglider_basestation3) don't share one naming scheme.",
    )
    parser.add_argument("--commit", action="store_true", help="Actually write to OGDB and transfer the file. Default is dry-run.")
    parser.add_argument("--confirm-live", action="store_true", help="Also confirm this level is live on ERDDAP (erddap_pushes). Only meaningful with --commit.")
    parser.add_argument("--erddap-remote-base", default="/data/ogdp/processed", help="Base directory on the ERDDAP server (default: /data/ogdp/processed)")
    args = parser.parse_args()

    if not os.path.isfile(args.path):
        print(f"ERROR: no such file: {args.path}", file=sys.stderr)
        sys.exit(1)

    report = inspect_netcdf(args.path)
    print(f"File:       {args.path}")
    print(f"Convention: {report.convention}")
    print(f"Level:      {report.level}")
    print(f"Dimensions: {report.dimensions}")
    print(f"Variables:  {len(report.variables)}")
    for w in report.warnings:
        print(f"  WARNING: {w}")

    if report.level not in ("L1", "L2"):
        print(
            f"ERROR: could not confidently classify this file as L1 or L2 "
            f"(got '{report.level}') -- refusing to proceed. This step is "
            f"only for L1/L2.",
            file=sys.stderr,
        )
        sys.exit(1)
    if report.convention == "unknown":
        print(
            "ERROR: could not classify the processing convention -- refusing "
            "to proceed without a human looking at this file first.",
            file=sys.stderr,
        )
        sys.exit(1)

    remote_dir = f"{args.erddap_remote_base}/{report.level}/{args.mission_slug}"
    remote_filename = os.path.basename(args.path)
    sftp_host_display = os.environ.get("ERDDAP_SFTP_HOST", "$ERDDAP_SFTP_HOST")

    print()
    print("Plan:")
    print(f"  1. Register document on mission {args.mission_id}, stage={args.stage}, "
          f"document_type={args.stage.lower()}_output")
    print(f"  2. SFTP {args.path} -> {sftp_host_display}:{remote_dir}/{remote_filename}")
    if args.confirm_live:
        print(f"  3. Confirm ERDDAP push: level={report.level}, status={args.stage}")

    if not args.commit:
        print()
        print("Dry run -- nothing written. Pass --commit to actually do this.")
        return

    gateway_url = os.environ["OGDB_GATEWAY_URL"]
    sftp_host = os.environ["ERDDAP_SFTP_HOST"]
    sftp_user = os.environ["ERDDAP_SFTP_USER"]
    sftp_key = os.environ["ERDDAP_SFTP_KEY_PATH"]

    print()
    print("Uploading via SFTP...")
    transfer = upload(
        local_path=args.path,
        remote_dir=remote_dir,
        remote_filename=remote_filename,
        host=sftp_host,
        username=sftp_user,
        key_path=sftp_key,
    )
    print(f"  transferred: {transfer.remote_path} ({transfer.file_size_bytes} bytes, sha256={transfer.file_hash})")

    print("Registering document in OGDB...")
    client = GatewayClient(base_url=gateway_url)
    try:
        client.login()
        metadata = NetcdfMetadata(
            level=report.level,
            convention=report.convention,
            dimensions=report.dimensions,
            global_attrs=report.global_attrs,
            variables={k: {"dims": list(v.dims), "dtype": v.dtype} for k, v in report.variables.items()},
        )
        client.register_document(
            mission_id=args.mission_id,
            stage=args.stage,
            file_reference=transfer.remote_path,
            file_hash=transfer.file_hash,
            file_size_bytes=transfer.file_size_bytes,
            metadata=metadata,
        )
        print("  registered.")

        if args.confirm_live:
            client.confirm_erddap_push(
                mission_id=args.mission_id, level=report.level, status=args.stage
            )
            print(f"  confirmed live: level={report.level}, status={args.stage}")
    except GatewayError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        print(
            "NOTE: the file has already been transferred to the ERDDAP server "
            "but OGDB was not updated. Re-run is not automatically safe here -- "
            "check state manually before retrying.",
            file=sys.stderr,
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
