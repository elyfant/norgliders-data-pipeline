"""Read-only OGDB queries for `config.resolve()`.

All queries are parameterised and read-only. The connection string comes from
`settings.load_settings().database_url` (env `DATABASE_URL` overrides). Point it
at production via an SSH tunnel or at a local snapshot.

Sensor / model / sea-area names read ``nvs_terms.label`` (the generated
``COALESCE(display_label, pref_label)``), so a facility-set short label wins
over the verbose canonical NVS ``skos:prefLabel``.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass, field
from datetime import date, datetime

import psycopg2
import psycopg2.extras


@contextlib.contextmanager
def connect(database_url: str):
    if not database_url:
        raise RuntimeError(
            "no OGDB connection string — set DATABASE_URL or [database].url in "
            "config/processing.toml"
        )
    conn = psycopg2.connect(database_url)
    try:
        conn.set_session(readonly=True, autocommit=True)
        yield conn
    finally:
        conn.close()


def _row(conn, sql: str, params: tuple) -> dict | None:
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(sql, params)
        r = cur.fetchone()
        return dict(r) if r else None


def _rows(conn, sql: str, params: tuple) -> list[dict]:
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]


# --------------------------------------------------------------------------
_MISSION_SQL = """
SELECT nm.id, nm.mission_number, nm.mission_name, nm.std_mission_name,
       nm.site,
       nm.launch_date, nm.recovery_date, m.end_date_science,
       nm.launch_latitude, nm.launch_longitude,
       nm.recovery_latitude, nm.recovery_longitude,
       m.doi, m.glider_asset_id,
       proj.name        AS project_name,
       proj.long_name   AS project_long_name,
       proj.url         AS project_url,
       proj.funder      AS project_funder,
       proj.fund_number AS project_fund_number,
       proj.acknowledgement AS project_acknowledgement,
       oa.name          AS operating_agency,
       oa.long_name     AS operating_agency_long,
       oa.url           AS operating_agency_url,
       pi.first_name    AS pi_first, pi.last_name AS pi_last,
       pi.email         AS pi_email, pi.orcid AS pi_orcid, pi.webpage AS pi_webpage,
       tl.first_name    AS tl_first, tl.last_name AS tl_last, tl.email AS tl_email,
       ga.serial_number AS glider_serial,
       agd.glider_name  AS glider_name,
       agd.wmo          AS glider_wmo,
       plat.name        AS platform_name,
       plat.model       AS platform_model,
       b76.label        AS glider_model_label
FROM norglider_missions nm
JOIN missions m               ON m.id = nm.id
LEFT JOIN projects proj       ON proj.id = m.project_id
LEFT JOIN institutes oa       ON oa.id = m.operating_agency_id
LEFT JOIN contacts pi         ON pi.id = m.principal_investigator_id
LEFT JOIN contacts tl         ON tl.id = m.technical_lead_id
LEFT JOIN assets ga           ON ga.id = m.glider_asset_id
LEFT JOIN asset_glider_details agd ON agd.asset_id = ga.id
LEFT JOIN platforms plat      ON plat.id = agd.platform_id
LEFT JOIN nvs_terms b76       ON b76.id = plat.b76_model_id
WHERE nm.mission_number = %s
"""

# C19 sea areas linked to the mission (many-to-many via mission_sea_names).
_SEA_NAMES_SQL = """
SELECT t.label
FROM mission_sea_names msn
JOIN nvs_terms t ON t.id = msn.c19_term_id
WHERE msn.mission_id = %s
ORDER BY t.label
"""

# Recursive walk of the assignment tree under the glider, live at `on_date`.
_PAYLOAD_SQL = """
WITH RECURSIVE tree(asset_id) AS (
    SELECT child_asset_id FROM asset_assignments
     WHERE parent_asset_id = %(glider)s
       AND start_date <= %(on_date)s
       AND (end_date IS NULL OR end_date >= %(on_date)s)
    UNION ALL
    SELECT aa.child_asset_id FROM asset_assignments aa
      JOIN tree t ON aa.parent_asset_id = t.asset_id
     WHERE aa.start_date <= %(on_date)s
       AND (aa.end_date IS NULL OR aa.end_date >= %(on_date)s)
)
SELECT a.id, at.name AS asset_type, a.serial_number,
       mf.name AS manufacturer,
       l05.label AS l05_family,
       l22.label AS l22_model,
       l22.uri        AS l22_uri
FROM tree
JOIN assets a          ON a.id = tree.asset_id
JOIN asset_types at    ON at.id = a.asset_type_id
LEFT JOIN manufacturers mf         ON mf.id = a.manufacturer_id
LEFT JOIN asset_sensor_details asd  ON asd.asset_id = a.id
LEFT JOIN nvs_terms l05 ON l05.id = asd.l05_family_id
LEFT JOIN nvs_terms l22 ON l22.id = asd.l22_model_id
WHERE at.name IN ('ct_sensor', 'do_sensor', 'eco_sensor')
ORDER BY at.name
"""

_CAL_TABLE = {
    "ct_sensor": "asset_ct_sensor_cal",
    "do_sensor": "asset_do_sensor_cal",
    "eco_sensor": "asset_eco_sensor_cal",
}


@dataclass
class Sensor:
    asset_id: int
    asset_type: str
    serial: str
    manufacturer: str | None
    l05_family: str | None
    l22_model: str | None
    l22_uri: str | None
    cal_date: date | None = None
    cal_facility: str | None = None

    @property
    def model_text(self) -> str:
        """Best available model string for catalog matching."""
        return self.l22_model or self.l05_family or ""


@dataclass
class MissionRecord:
    mission: dict
    sensors: list[Sensor] = field(default_factory=list)
    sea_names: list[str] = field(default_factory=list)   # C19 nvs_terms.label
    payload_resolved: bool = True   # False if OGDB had no assignments


def fetch_mission_record(conn, mission_number: int) -> MissionRecord:
    mission = _row(conn, _MISSION_SQL, (mission_number,))
    if mission is None:
        raise LookupError(f"OGDB has no mission with mission_number={mission_number}")

    sea_names = [r["label"]
                 for r in _rows(conn, _SEA_NAMES_SQL, (mission["id"],))]

    launch = mission["launch_date"]
    on_date = (launch.date() if isinstance(launch, datetime) else launch)

    sensors: list[Sensor] = []
    if mission["glider_asset_id"] and on_date:
        rows = _rows(conn, _PAYLOAD_SQL,
                     {"glider": mission["glider_asset_id"], "on_date": on_date})
        for r in rows:
            s = Sensor(
                asset_id=r["id"], asset_type=r["asset_type"],
                serial=(r["serial_number"] or "").strip(),
                manufacturer=r["manufacturer"], l05_family=r["l05_family"],
                l22_model=r["l22_model"], l22_uri=r["l22_uri"],
            )
            cal = _latest_cal(conn, s.asset_type, s.asset_id, on_date)
            if cal:
                s.cal_date, s.cal_facility = cal
            sensors.append(s)

    return MissionRecord(
        mission=mission, sensors=sensors, sea_names=sea_names,
        payload_resolved=bool(sensors),
    )


def _latest_cal(conn, asset_type: str, asset_id: int, on_date: date):
    table = _CAL_TABLE.get(asset_type)
    if not table:
        return None
    r = _row(
        conn,
        f"SELECT cal_date, calibration_facility FROM {table} "
        f"WHERE asset_id = %s AND cal_date <= %s "
        f"ORDER BY cal_date DESC LIMIT 1",
        (asset_id, on_date),
    )
    if not r:
        return None
    return r["cal_date"], r["calibration_facility"]
