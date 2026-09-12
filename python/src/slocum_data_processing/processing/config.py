"""Resolve the processing configuration for a mission.

Model (planning repo, decision 0003): OGDB is the system of record for
mission / glider / sensor / calibration metadata. The pyglider
``deployment.yml`` is **generated from OGDB per run** and written into the
mission's data folder — it is not a hand-maintained repo file. Only the
``processing:`` block (window, run knobs, later QC notes) is set by a human.

* :func:`resolve` — build the OGDB-derived deployment dict for a mission.
* :func:`write_deployment_yaml` — resolve + render + write to a target path,
  preserving the ``processing:`` block on ``--regenerate``.
* :func:`load` — read a ``deployment.yml`` (+ ``sensors.txt``, falling back
  to the packaged facility default) into a :class:`DeploymentConfig`.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from ..settings import load_settings
from . import ogdb, sensor_catalog

_HERE = Path(__file__).resolve().parent
_MISSIONS_DIR = _HERE.parents[2] / "missions"          # python/missions/  (legacy)
_DEFAULT_SENSORS = _HERE / "default_sensors.txt"        # packaged facility default
_PKG_VERSION = "0.0.1"

_GENERATED_MARKER = "# ===  GENERATED FROM OGDB  "


# ==========================================================================
# consumer side
# ==========================================================================
@dataclass
class DeploymentConfig:
    mission_dir: Path
    deployment_yaml: Path
    sensor_list: Path
    deployment: dict = field(repr=False)

    scisuffix: str = "ebd"
    glidersuffix: str = "dbd"
    profile_filt_time: float = 100.0
    profile_min_time: float = 100.0
    grid_dz: float = 1.0
    l0_time_range: tuple[str, str] | None = None
    l1_time_range: tuple[str, str] | None = None

    @property
    def metadata(self) -> dict:
        return self.deployment["metadata"]

    @property
    def deployment_name(self) -> str:
        return self.metadata["deployment_name"]

    @property
    def glider_id(self) -> str:
        md = self.metadata
        return f"{md['glider_name']}{md['glider_serial']}"


def _mission_dir(mission: str | int | Path) -> Path:
    if isinstance(mission, Path):
        return mission
    if isinstance(mission, str) and ("/" in mission or Path(mission).is_dir()):
        return Path(mission)
    token = f"{int(mission):03d}" if str(mission).isdigit() else str(mission)
    matches = sorted(p for p in _MISSIONS_DIR.glob(f"{token}*") if p.is_dir())
    if not matches:
        raise FileNotFoundError(
            f"No mission directory under {_MISSIONS_DIR} matching {token!r}"
        )
    if len(matches) > 1:
        raise ValueError(f"Ambiguous mission {token!r}: {[m.name for m in matches]}")
    return matches[0]


def load(mission: str | int | Path, **overrides) -> DeploymentConfig:
    """Load a mission's ``deployment.yml`` (a data folder, a
    ``python/missions/`` dir, or a mission number). ``sensors.txt`` falls back
    to the packaged facility default when the directory has none."""
    mdir = _mission_dir(mission)
    dyaml = mdir / "deployment.yml"
    if not dyaml.is_file():
        raise FileNotFoundError(f"{dyaml} not found")
    sensors = mdir / "sensors.txt"
    if not sensors.is_file():
        sensors = _DEFAULT_SENSORS

    deployment = yaml.safe_load(dyaml.read_text())
    if "metadata" not in deployment:
        raise ValueError(f"{dyaml}: missing 'metadata' block")

    proc = dict(deployment.get("processing", {}))
    proc.update(overrides)

    def _range(v):
        return tuple(v) if v else None

    return DeploymentConfig(
        mission_dir=mdir, deployment_yaml=dyaml, sensor_list=sensors,
        deployment=deployment,
        scisuffix=proc.get("scisuffix", "ebd"),
        glidersuffix=proc.get("glidersuffix", "dbd"),
        profile_filt_time=float(proc.get("profile_filt_time", 100)),
        profile_min_time=float(proc.get("profile_min_time", 100)),
        grid_dz=float(proc.get("grid_dz", 1.0)),
        l0_time_range=_range(proc.get("l0_time_range")),
        l1_time_range=_range(proc.get("l1_time_range")),
    )


# ==========================================================================
# generator side
# ==========================================================================
def _iso(d) -> str:
    if isinstance(d, _dt.datetime):
        d = d.date()
    return d.isoformat() if d else ""


def _blank(v) -> str:
    return str(v).strip() if v not in (None, "") else " "


def resolve(mission_number: int, *, database_url: str | None = None,
            binary_dir: str | Path | None = None,
            unused_sensors: "list[str] | tuple[str, ...]" = ()) -> dict:
    """Build the OGDB-derived deployment dict for ``mission_number``.

    Returns a dict with ``metadata`` / ``glider_devices`` / ``netcdf_variables``
    / ``profile_variables`` — everything except the human ``processing:`` block.
    ``binary_dir``, if given, is used to cross-check sensor ``source`` names
    against the mission's real binary sensor list (warnings only).

    ``unused_sensors`` — device keys ("optics", "oxygen", ...) that OGDB
    assigns to the glider but which logged no usable data this deployment
    (the operator confirms this on the first pass). Their ``netcdf_variables``
    are kept (they document the channel; pyglider fills them with NaN) but the
    instrument-level metadata — the ``glider_devices`` entry and the
    ``profile_variables`` ``instrument_*`` container — is dropped, since we
    can't vouch for a calibration/serial on a sensor that never ran. Set via
    ``processing.unused_sensors`` in ``deployment.yml``.
    """
    s = load_settings()
    fac = s.facility
    url = database_url or s.database_url

    with ogdb.connect(url) as conn:
        rec = ogdb.fetch_mission_record(conn, mission_number)

    m = rec.mission
    std = (m["std_mission_name"] or "").lower()
    dep_name = f"{int(mission_number):03d}-{std}"
    launch, recovery = m["launch_date"], m["recovery_date"]
    glider_model = (m["glider_model_label"]
                    or (f"Slocum {(m['platform_model'] or '').strip()}".strip()))

    warnings: list[str] = []
    notes: list[str] = []
    unused = {k.strip().lower() for k in unused_sensors if k and k.strip()}

    # ---- metadata ----
    pi_name = " ".join(x for x in (m["pi_first"], m["pi_last"]) if x).strip()
    tl_name = " ".join(x for x in (m["tl_first"], m["tl_last"]) if x).strip()
    contributors = ", ".join(x for x in (pi_name, tl_name) if x)

    # verbatim projects.acknowledgement wins; else compose from funder / grant
    ack = (m["project_acknowledgement"] or "").strip()
    if not ack and m["project_funder"]:
        ack = f"This deployment was funded by {m['project_funder']}"
        if m["project_fund_number"]:
            ack += f" under grant {m['project_fund_number']}"
        ack += "."

    when = launch.strftime("%Y %B") if launch else ""
    seas = ", ".join(rec.sea_names)   # C19 terms via mission_sea_names
    if not seas:
        warnings.append("no mission_sea_names in OGDB — sea_name left blank")
    summary = ", ".join(x for x in (
        f"{glider_model} {m['glider_name']} delayed-mode dataset",
        m["site"] or "", seas, when) if x) + "."

    metadata = {
        "deployment_name": dep_name,
        "deployment_id": str(mission_number),
        "deployment_start": _iso(launch),
        "deployment_end": _iso(recovery or m["end_date_science"]),
        "glider_name": m["glider_name"],
        "glider_serial": _blank(m["glider_serial"]),
        "glider_model": glider_model,
        "glider_instrument_name": "slocum",
        "glider_wmo": _blank(m["glider_wmo"]),
        "wmo_id": _blank(m["glider_wmo"]),
        "institution": m["operating_agency_long"] or fac.get("institution", ""),
        "project": m["project_name"] or "",
        "project_url": m["project_url"] or "",
        "creator_name": pi_name or " ",
        "creator_email": _blank(m["pi_email"]),
        "creator_url": m["pi_webpage"] or m["operating_agency_url"] or fac.get("creator_url", ""),
        "creator_orcid": _blank(m["pi_orcid"]),
        "contributor_name": contributors or " ",
        "contributor_role": "Principal Investigator, Technical Lead",
        "publisher_name": fac.get("publisher_name", ""),
        "publisher_email": fac.get("publisher_email", "") or " ",
        "publisher_url": m["operating_agency_url"] or fac.get("publisher_url", ""),
        "summary": summary,
        "acknowledgement": ack or " ",
        "comment": " ",
        "data_mode": "D",
        "sea_name": seas or " ",   # C19 terms via mission_sea_names
        "doi": _blank(m["doi"]),
        "format_version": fac.get("format_version", ""),
        "keywords": fac.get("keywords", ""),
        "keywords_vocabulary": fac.get("keywords_vocabulary", ""),
        "license": fac.get("license", ""),
        "naming_authority": fac.get("naming_authority", ""),
        "platform_type": fac.get("platform_type", "Slocum Glider"),
        "processing_level": "Delayed-mode processing with pyglider. No QC applied at this stage.",
        "references": fac.get("references", ""),
        "source": fac.get("source", "Observational data from a profiling glider."),
        "standard_name_vocabulary": fac.get("standard_name_vocabulary", ""),
        "transmission_system": fac.get("transmission_system", "IRIDIUM"),
    }

    # ---- payload -> glider_devices / netcdf_variables / profile_variables ----
    binary_sci = _binary_science_prefixes(binary_dir) if binary_dir else None

    glider_devices: dict = {}
    ncvars: dict = dict(sensor_catalog.NAV_VARIABLES)
    profvars: dict = dict(sensor_catalog.PROFILE_VARIABLES)

    if not rec.payload_resolved:
        warnings.append(
            "OGDB has no asset_assignments for this glider at the launch date "
            "-- glider_devices / science variables NOT resolved. Point "
            "DATABASE_URL at production (the local snapshot lacks the payload), "
            "or fill the assignments in OGDB, then --regenerate."
        )

    for sen in rec.sensors:
        kind = sensor_catalog.match_sensor(sen.asset_type, sen.model_text)
        if kind is None:
            warnings.append(
                f"no catalog entry for {sen.asset_type} "
                f"model={sen.model_text!r} (SN {sen.serial}) -- skipped"
            )
            continue

        prefix = kind.binary_prefix
        if binary_sci is not None:
            present = {v["source"] for v in kind.netcdf_variables.values()
                       if v["source"] in binary_sci}
            missing = [v["source"] for v in kind.netcdf_variables.values()
                       if v["source"] not in binary_sci]
            if not present:
                warnings.append(
                    f"{kind.key}: OGDB has {sen.model_text or sen.asset_type} "
                    f"(SN {sen.serial}) but none of {missing} are in the binary "
                    f"data -- mapping it anyway"
                )

        l22_code = (sen.l22_uri.rstrip("/").rsplit("/", 1)[-1] if sen.l22_uri else "")
        # the L22 pref_label is the canonical make+model string
        make_model = sen.l22_model or " ".join(
            x for x in (sen.manufacturer, sen.model_text) if x) or kind.long_name
        long_name = f"{make_model} SN{sen.serial}".strip() if sen.serial else make_model

        if kind.key in unused:
            # Aboard per OGDB but logged no usable data this deployment. Keep
            # the data variables (NaN-filled by pyglider; they document the
            # channel) minus their dangling instrument ref; drop the
            # glider_devices entry and the instrument_* container.
            for vname, vdef in kind.netcdf_variables.items():
                v = {k: val for k, val in vdef.items() if k != "instrument"}
                extra = (f"{make_model} (SN {sen.serial}) was installed for this "
                         f"deployment but logged no data; channel kept for the "
                         f"record (values are fill).")
                v["comment"] = f"{v['comment'].rstrip('.')}. {extra}" if v.get("comment") else extra
                ncvars[vname] = v
            notes.append(
                f"{kind.key}: OGDB assigns {make_model} (SN {sen.serial}) but it is "
                f"listed in processing.unused_sensors -- data vars kept, instrument "
                f"metadata omitted"
            )
            continue

        glider_devices[kind.key] = {
            "make": sen.manufacturer or " ",
            "model": sen.model_text or kind.long_name,
            "serial": _blank(sen.serial),
            "long_name": long_name,
            "make_model": make_model,
            "factory_calibrated": _factory_calibrated(sen),
            "calibration_date": _iso(sen.cal_date) or " ",
            "calibration_report": " ",
            "comment": f"binary prefix {prefix}"
                       + (f"; NVS L22 {l22_code}" if l22_code else ""),
        }
        ncvars.update(kind.netcdf_variables)
        profvars[kind.instrument_key] = {
            "comment": f"{make_model}; binary prefix {prefix}",
            "calibration_date": _iso(sen.cal_date) or " ",
            "calibration_report": " ",
            "factory_calibrated": _factory_calibrated(sen),
            "long_name": long_name,
            "make_model": make_model,
            "platform": "platform",
            "serial_number": _blank(sen.serial),
            "type": "platform",
        }

    glider_devices.setdefault("pressure", {"make": " ", "model": " ", "serial": " "})

    return {
        "_meta": {
            "warnings": warnings,
            "notes": notes,
            "payload_resolved": rec.payload_resolved,
            "launch_date": _iso(launch),
            "recovery_date": _iso(recovery),
            "database_url": _redact(url),
        },
        "metadata": metadata,
        "glider_devices": glider_devices,
        "netcdf_variables": ncvars,
        "profile_variables": profvars,
    }


def _factory_calibrated(sen: ogdb.Sensor) -> str:
    """D7: derive from calibration_facility vs manufacturer."""
    if not sen.cal_facility:
        return " "
    fac = sen.cal_facility.strip().lower()
    man = (sen.manufacturer or "").strip().lower()
    if man and (fac in man or man in fac or fac in {"sbe", "sea-bird", "seabird"}
                and "sea-bird" in man):
        return "yes"
    return "no"


def _redact(url: str) -> str:
    if "@" in url:
        return url.split("@", 1)[0].rsplit(":", 1)[0] + ":***@" + url.split("@", 1)[1]
    return url


def _binary_science_prefixes(binary_dir) -> set[str]:
    """The set of sci_* sensor names present in the mission's .ebd files."""
    import dbdreader
    s = load_settings()
    ebd = sorted(Path(binary_dir).glob("*.ebd"))
    if not ebd:
        return set()
    d = dbdreader.MultiDBD(pattern=f"{binary_dir}/*.ebd",
                           cacheDir=str(s.master_cache_dir))
    return {p for grp in d.parameterNames.values() for p in grp if p.startswith("sci_")}


# ---- rendering / writing ----
_DEFAULT_PROCESSING = {
    "scisuffix": "ebd", "glidersuffix": "dbd",
    "profile_filt_time": 100, "profile_min_time": 100, "grid_dz": 1.0,
    "l0_time_range": None,
}


def _processing_block(existing_text: str | None, launch: str, recovery: str) -> str:
    """The human-owned block. Preserved verbatim from ``existing_text`` on
    regenerate; otherwise seeded from the launch/recovery dates."""
    if existing_text:
        return existing_text.rstrip() + "\n"
    end = recovery or launch
    try:
        end = (_dt.date.fromisoformat(end) + _dt.timedelta(days=1)).isoformat()
    except ValueError:
        pass
    return (
        "# Human-owned. --regenerate never touches this block.\n"
        "processing:\n"
        "  scisuffix: ebd\n"
        "  glidersuffix: dbd\n"
        "  profile_filt_time: 100      # s, up/down detection smoothing\n"
        "  profile_min_time: 100       # s, minimum profile duration\n"
        "  grid_dz: 1.0                # m, L2 vertical bin\n"
        "  l0_time_range: null         # L0 = all decoded data\n"
        f"  l1_time_range: ['{launch}', '{end}']   # seeded from OGDB launch/recovery; "
        "trim after looking at L0\n"
    )


def _existing_processing_key(processing_text: str | None, key: str):
    """Pull one value out of an existing ``processing:`` block (raw text)."""
    if not processing_text:
        return None
    try:
        doc = yaml.safe_load(processing_text) or {}
    except yaml.YAMLError:
        return None
    return (doc.get("processing") or {}).get(key)


def _split_processing(text: str) -> str:
    """Return just the leading ``processing:`` block of an existing file."""
    marker = text.find(_GENERATED_MARKER)
    if marker != -1:
        return text[:marker].rstrip() + "\n"
    # no marker: take everything up to the first top-level 'metadata:'
    idx = text.find("\nmetadata:")
    return (text[:idx] if idx != -1 else text).rstrip() + "\n"


def render_deployment_yaml(resolved: dict, processing_block: str, db_label: str) -> str:
    body = {k: v for k, v in resolved.items() if not k.startswith("_")}
    yml = yaml.safe_dump(body, sort_keys=False, default_flow_style=False,
                         allow_unicode=True, width=100)
    now = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    header = (
        f"\n{_GENERATED_MARKER}=========================================\n"
        f"# GENERATED by slocum_data_processing {_PKG_VERSION} from OGDB\n"
        f"#   {db_label}\n"
        f"# at {now}. OGDB is the source of truth for everything below.\n"
        f"# Re-run with --regenerate to refresh it; the processing: block above\n"
        f"# is preserved. Do not hand-edit -- fix the value in OGDB instead.\n"
        f"# ====================================================================\n"
    )
    return processing_block.rstrip() + "\n" + header + yml


def write_deployment_yaml(mission_number: int, target: str | Path, *,
                          regenerate: bool = False,
                          database_url: str | None = None,
                          binary_dir: str | Path | None = None,
                          ) -> tuple[Path, list[str], list[str]]:
    """Resolve from OGDB and write ``target``. Refuses to overwrite unless
    ``regenerate`` (then it preserves the existing ``processing:`` block,
    including any ``unused_sensors:`` list). Returns ``(path, warnings, notes)``."""
    target = Path(target)
    if target.exists() and not regenerate:
        raise FileExistsError(
            f"{target} exists -- pass regenerate=True to refresh the OGDB block "
            f"(your processing: block is kept)"
        )

    existing = _split_processing(target.read_text()) if target.exists() else None
    unused = _existing_processing_key(existing, "unused_sensors") or ()

    resolved = resolve(mission_number, database_url=database_url,
                       binary_dir=binary_dir, unused_sensors=unused)
    proc = _processing_block(existing, resolved["_meta"]["launch_date"],
                             resolved["_meta"]["recovery_date"])
    text = render_deployment_yaml(resolved, proc, resolved["_meta"]["database_url"])

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text)
    return target, resolved["_meta"]["warnings"], resolved["_meta"]["notes"]
