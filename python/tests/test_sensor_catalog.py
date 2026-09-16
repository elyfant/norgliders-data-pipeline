"""Sensor-model -> pyglider variable mapping. No database needed."""

import pytest

from norgliders_data_pipeline.processing import sensor_catalog as sc


@pytest.mark.parametrize("asset_type, model, expect_key, expect_vars", [
    ("ct_sensor",  "Sea-Bird SBE 41CP CTD",                 "ctd",
     {"conductivity", "temperature", "pressure"}),
    ("ct_sensor",  "Sea-Bird Slocum Glider Payload GPCTD",   "ctd",
     {"conductivity", "temperature", "pressure"}),
    ("ct_sensor",  "RBR Legato3 CTD",                        "ctd",
     {"conductivity", "temperature", "pressure"}),
    ("eco_sensor", "WET Labs ECO Puck FLNTU-SLK",            "optics",
     {"chlorophyll", "turbidity"}),
    ("eco_sensor", "WET Labs ECO Puck Triplet FLBBCD-SLC",   "optics",
     {"chlorophyll", "cdom", "backscatter_700"}),
    ("do_sensor",  "Aanderaa 3830 oxygen optode",            "oxygen",
     {"oxygen_concentration", "oxygen_saturation"}),
    ("do_sensor",  "Aanderaa 4831 oxygen optode",            "oxygen",
     {"oxygen_concentration", "oxygen_saturation"}),
])
def test_match(asset_type, model, expect_key, expect_vars):
    kind = sc.match_sensor(asset_type, model)
    assert kind is not None, f"no match for {asset_type} / {model!r}"
    assert kind.key == expect_key
    assert set(kind.netcdf_variables) == expect_vars


def test_optode_source_names_differ():
    o3835 = sc.match_sensor("do_sensor", "Aanderaa 3830 oxygen optode")
    o4831 = sc.match_sensor("do_sensor", "Aanderaa 4831 oxygen optode")
    assert o3835.netcdf_variables["oxygen_concentration"]["source"] == "sci_oxy3835_oxygen"
    assert o4831.netcdf_variables["oxygen_concentration"]["source"] == "sci_oxy4_oxygen"


def test_flntu_vs_flbbcd_source_prefix():
    flntu = sc.match_sensor("eco_sensor", "WET Labs ECO Puck FLNTU-SLK")
    flbbcd = sc.match_sensor("eco_sensor", "WET Labs ECO Puck Triplet FLBBCD-SLC")
    assert flntu.binary_prefix == "sci_flntu"
    assert flbbcd.binary_prefix == "sci_flbbcd"


def test_unknown_returns_none():
    assert sc.match_sensor("mr_sensor", "Rockland MicroRider-1000") is None
    assert sc.match_sensor("ct_sensor", "") is not None  # CTD matches any model


def test_nav_and_profile_blocks_are_dicts():
    assert "time" in sc.NAV_VARIABLES and "latitude" in sc.NAV_VARIABLES
    assert "profile_id" in sc.PROFILE_VARIABLES and "u" in sc.PROFILE_VARIABLES
