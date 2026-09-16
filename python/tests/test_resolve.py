"""config.resolve() against a live OGDB.

Skipped unless an OGDB is reachable (``DATABASE_URL`` / ``[database].url``).

- ``test_metadata_only`` reads mission 28 as-is — runs against production or
  the local snapshot, both of which have mission 28's row + sea-name seed.
- ``test_payload_resolves`` needs mission 28's science payload. It fabricates
  it (tagged, cleaned up after) for the local snapshot, and auto-skips
  against a DB that already has it (production).
"""

import datetime as dt

import pytest

from norgliders_data_pipeline.processing import config, ogdb
from norgliders_data_pipeline.settings import load_settings

FIXTURE_TAG = "RESOLVE_TEST_FIXTURE"

_UP = """
INSERT INTO manufacturers (name)
SELECT v FROM (VALUES ('Sea-Bird'),('WET Labs'),('Aanderaa')) t(v)
WHERE NOT EXISTS (SELECT 1 FROM manufacturers m WHERE m.name = t.v);

INSERT INTO assets (asset_type_id, serial_number, manufacturer_id, notes)
SELECT (SELECT id FROM asset_types WHERE name = t.atype), t.sn,
       (SELECT id FROM manufacturers WHERE name = t.mfr), %(tag)s
FROM (VALUES ('ct_sensor','69','Sea-Bird'),('eco_sensor','771','WET Labs'),
             ('do_sensor','903','Aanderaa')) t(atype, sn, mfr);

INSERT INTO asset_sensor_details (asset_id, l22_model_id)
SELECT a.id, (SELECT id FROM nvs_terms WHERE uri LIKE '%%' || t.tool || '%%')
FROM (VALUES ('69','TOOL0669'),('771','TOOL1993'),('903','TOOL0836')) t(sn, tool)
JOIN assets a ON a.serial_number = t.sn AND a.notes = %(tag)s;

INSERT INTO asset_assignments (child_asset_id, parent_asset_id, start_date, end_date)
SELECT a.id, 8, DATE '2017-08-01', DATE '2017-10-01'
FROM assets a WHERE a.notes = %(tag)s;

INSERT INTO asset_ct_sensor_cal (asset_id, cal_date, calibration_facility, note)
SELECT a.id, DATE '2016-02-19', 'Sea-Bird', %(tag)s
FROM assets a WHERE a.serial_number='69' AND a.notes=%(tag)s;
INSERT INTO asset_eco_sensor_cal (asset_id, cal_date, calibration_facility)
SELECT a.id, DATE '2016-02-22', 'WET Labs' FROM assets a WHERE a.serial_number='771' AND a.notes=%(tag)s;
INSERT INTO asset_do_sensor_cal (asset_id, cal_date, calibration_facility)
SELECT a.id, DATE '2016-02-16', 'Aanderaa' FROM assets a WHERE a.serial_number='903' AND a.notes=%(tag)s;
"""

_DOWN = """
DELETE FROM asset_ct_sensor_cal  WHERE note = %(tag)s;
DELETE FROM asset_eco_sensor_cal WHERE asset_id IN (SELECT id FROM assets WHERE notes=%(tag)s);
DELETE FROM asset_do_sensor_cal  WHERE asset_id IN (SELECT id FROM assets WHERE notes=%(tag)s);
DELETE FROM asset_assignments    WHERE child_asset_id IN (SELECT id FROM assets WHERE notes=%(tag)s);
DELETE FROM asset_sensor_details WHERE asset_id IN (SELECT id FROM assets WHERE notes=%(tag)s);
DELETE FROM assets               WHERE notes = %(tag)s;
"""


@pytest.fixture(scope="module")
def ogdb_url():
    import psycopg2

    url = load_settings().database_url
    if not url:
        pytest.skip("no OGDB connection configured")
    sep = "&" if "?" in url else "?"
    probe_url = f"{url}{sep}connect_timeout=5"
    try:
        conn = psycopg2.connect(probe_url)
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM missions WHERE mission_number = 28")
            found = cur.fetchone()
        conn.close()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"OGDB unreachable: {exc}")
    if found is None:
        pytest.skip("OGDB has no mission 28")
    return probe_url


@pytest.fixture()
def payload_fixture(ogdb_url):
    # Fabricates gna's Sep-2017 payload — only meaningful on a DB that doesn't
    # already have it (the local snapshot). On one that does (production),
    # duplicating the assignments gives ambiguous results, so skip.
    if config.resolve(28, database_url=ogdb_url)["_meta"]["payload_resolved"]:
        pytest.skip("OGDB already has mission 28's payload — this fixture is snapshot-only")

    import psycopg2
    conn = psycopg2.connect(ogdb_url)
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute(_DOWN, {"tag": FIXTURE_TAG})   # in case a prior run died
        cur.execute(_UP, {"tag": FIXTURE_TAG})
    yield ogdb_url
    with conn.cursor() as cur:
        cur.execute(_DOWN, {"tag": FIXTURE_TAG})
    conn.close()


def test_metadata_only(ogdb_url):
    r = config.resolve(28, database_url=ogdb_url)
    md = r["metadata"]
    assert md["deployment_name"] == "028-gna_provolo_lofoten_sep2017"
    assert md["deployment_id"] == "28"
    assert md["glider_name"] == "gna"
    assert md["glider_wmo"] == "6801615"
    assert md["creator_name"] == "Ilker Fer"
    assert md["data_mode"] == "D"
    assert "delayed-mode dataset" in md["summary"]
    # mission 28 is seeded to the Norwegian Sea (C19) in mission_sea_names
    assert md["sea_name"] == "Norwegian Sea"
    assert "Norwegian Sea" in md["summary"]


def test_unused_sensors_keeps_vars_drops_metadata(ogdb_url):
    # only meaningful once mission 28's payload resolves (production)
    base = config.resolve(28, database_url=ogdb_url)
    if not base["_meta"]["payload_resolved"]:
        pytest.skip("mission 28 payload not resolved on this DB")
    if "optics" not in base["glider_devices"]:
        pytest.skip("no optics device on mission 28 to mark unused")

    r = config.resolve(28, database_url=ogdb_url, unused_sensors=["optics"])
    assert "optics" not in r["glider_devices"]
    assert "instrument_flntu" not in r["profile_variables"]
    # the data channels stay, minus their dangling instrument ref
    assert "chlorophyll" in r["netcdf_variables"]
    assert "instrument" not in r["netcdf_variables"]["chlorophyll"]
    assert "logged no data" in r["netcdf_variables"]["chlorophyll"]["comment"]
    assert any("unused_sensors" in n for n in r["_meta"]["notes"])
    # ctd / oxygen untouched
    assert "ctd" in r["glider_devices"]


def test_payload_resolves(payload_fixture):
    r = config.resolve(28, database_url=payload_fixture)
    assert r["_meta"]["payload_resolved"] is True
    assert not r["_meta"]["warnings"]

    assert r["metadata"]["sea_name"] == "Norwegian Sea"
    assert "Norwegian Sea" in r["metadata"]["summary"]

    gd = r["glider_devices"]
    assert set(gd) == {"ctd", "optics", "oxygen", "pressure"}
    assert gd["ctd"]["serial"] == "69"
    assert gd["ctd"]["calibration_date"] == "2016-02-19"
    assert gd["ctd"]["factory_calibrated"] == "yes"
    assert gd["oxygen"]["comment"].startswith("binary prefix sci_oxy3835")

    nv = r["netcdf_variables"]
    assert {"conductivity", "temperature", "pressure",
            "chlorophyll", "turbidity",
            "oxygen_concentration", "oxygen_saturation"} <= set(nv)
    assert nv["chlorophyll"]["source"] == "sci_flntu_chlor_units"

    pv = r["profile_variables"]
    assert {"instrument_ctd", "instrument_flntu", "instrument_oxygen"} <= set(pv)
