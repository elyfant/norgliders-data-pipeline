"""config.resolve() against a live OGDB.

Skipped unless an OGDB is reachable. Loads a self-contained science-payload
fixture for mission 28 (gna, Sep 2017) in a way that is cleaned up afterwards,
so it works against the local snapshot which otherwise has no assignments for
that glider.
"""

import datetime as dt

import pytest

from slocum_data_processing.processing import config, ogdb
from slocum_data_processing.settings import load_settings

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

-- sea area: link mission 28 to the C19 Norwegian Sea term (upsert the term
-- so the test is self-contained on a snapshot that hasn't run a full sync).
INSERT INTO nvs_terms (collection, uri, pref_label, deprecated, synced_at)
VALUES ('C19', 'http://vocab.nerc.ac.uk/collection/C19/current/9_7/', 'Norwegian Sea', false, now())
ON CONFLICT (uri) DO NOTHING;
INSERT INTO mission_sea_names (mission_id, c19_term_id)
SELECT m.id, t.id FROM missions m, nvs_terms t
WHERE m.mission_number = 28
  AND t.uri = 'http://vocab.nerc.ac.uk/collection/C19/current/9_7/'
ON CONFLICT DO NOTHING;
"""

_DOWN = """
DELETE FROM mission_sea_names
 WHERE mission_id = (SELECT id FROM missions WHERE mission_number = 28)
   AND c19_term_id = (SELECT id FROM nvs_terms
                      WHERE uri = 'http://vocab.nerc.ac.uk/collection/C19/current/9_7/');
DELETE FROM asset_ct_sensor_cal  WHERE note = %(tag)s;
DELETE FROM asset_eco_sensor_cal WHERE asset_id IN (SELECT id FROM assets WHERE notes=%(tag)s);
DELETE FROM asset_do_sensor_cal  WHERE asset_id IN (SELECT id FROM assets WHERE notes=%(tag)s);
DELETE FROM asset_assignments    WHERE child_asset_id IN (SELECT id FROM assets WHERE notes=%(tag)s);
DELETE FROM asset_sensor_details WHERE asset_id IN (SELECT id FROM assets WHERE notes=%(tag)s);
DELETE FROM assets               WHERE notes = %(tag)s;
"""


@pytest.fixture(scope="module")
def ogdb_url():
    url = load_settings().database_url
    if not url:
        pytest.skip("no OGDB connection configured")
    try:
        with ogdb.connect(url) as conn, conn.cursor() as cur:
            cur.execute("SELECT 1 FROM missions WHERE mission_number = 28")
            if cur.fetchone() is None:
                pytest.skip("OGDB has no mission 28")
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"OGDB unreachable: {exc}")
    return url


@pytest.fixture()
def payload_fixture(ogdb_url):
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
