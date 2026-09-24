"""OG1 variable renaming. No database, no real mission data needed."""

import numpy as np
import xarray as xr

from norgliders_data_pipeline.og1.convert import CF_TO_OG1, convert_to_og1


def _synthetic_l1(tmp_path):
    """A tiny CF-named dataset shaped like our real L1 output, including
    both mapped (temperature, conductivity, ...) and deliberately-unmapped
    (turbidity, profile_index) variables."""
    n = 5
    ds = xr.Dataset(
        {
            "temperature": ("time", np.array([10.0, 10.1, np.nan, 10.3, 10.4])),
            "conductivity": ("time", np.full(n, 3.5)),
            "salinity": ("time", np.full(n, 35.0)),
            "chlorophyll": ("time", np.full(n, 0.5)),
            "oxygen_concentration": ("time", np.full(n, 250.0)),  # no matching glider_devices entry -- see below
            "turbidity": ("time", np.full(n, 0.1)),          # deliberately unmapped
            "profile_index": ("time", np.array([1, 1, 1.5, 2, 2])),  # deliberately unmapped
            "trajectory": ((), "test-deployment"),
        },
        coords={"time": ("time", np.array(["2017-09-06T12:00:00"] * n, dtype="datetime64[s]"))},
        attrs={"Conventions": "CF-1.8, ACDD-1.3", "processing_level": "L1"},
    )
    ds = ds.assign_coords(
        depth=("time", np.linspace(0, 40, n)),
        latitude=("time", np.full(n, 60.0)),
        longitude=("time", np.full(n, 5.0)),
    )
    ds["trajectory"].attrs["cf_role"] = "trajectory_id"
    src = tmp_path / "in_L1.nc"
    ds.to_netcdf(src)
    return src


_SAMPLE_GLIDER_DEVICES = {
    "ctd": {
        "make": " ",  # blank placeholder, like real deployment.yml -- must not become an attr
        "model": "Sea-Bird SBE 41CP",
        "serial": "69",
        "make_model": "Sea-Bird SBE 41CP",
        "factory_calibrated": "no",
        "calibration_date": "2016-02-19",
        "calibration_report": " ",
        "comment": "binary prefix sci_ctd41cp",
    },
    "optics": {
        "make": "WET Labs",
        "model": "ECO Puck FLNTU-SLK",
        "serial": "771",
    },
    # deliberately no "oxygen" entry -- mirrors mission 028's real gap
}


_SAMPLE_METADATA = {
    "deployment_name": "test-deployment",
    "summary": "Test mission for og1 convert unit tests.",
    "deployment_start": "2017-09-06",
    "naming_authority": "no.uib",
    "sea_name": "Norwegian Sea",
    "project": "testproj",
    "doi": "10.1234/test",
    "contributor_name": "Test Person",
    "creator_email": "test.person@uib.no",
    "contributor_role": "Principal Investigator, Made Up Role",
    "institution": "University of Bergen",
}


def test_known_variables_are_renamed(tmp_path):
    src = _synthetic_l1(tmp_path)
    dst = tmp_path / "out_OG1.nc"
    convert_to_og1(src, dst)

    out = xr.open_dataset(dst)
    try:
        for cf_name, og1_name in [
            ("temperature", "TEMP"), ("conductivity", "CNDC"),
            ("salinity", "PSAL"), ("chlorophyll", "CHLA"),
        ]:
            assert cf_name not in out.variables
            assert og1_name in out.variables
    finally:
        out.close()


def test_unmapped_variables_pass_through_unrenamed(tmp_path):
    src = _synthetic_l1(tmp_path)
    dst = tmp_path / "out_OG1.nc"
    convert_to_og1(src, dst)

    out = xr.open_dataset(dst)
    try:
        # not in CF_TO_OG1 -> kept under their original name, not dropped
        assert "turbidity" in out.variables
        assert "profile_index" in out.variables
    finally:
        out.close()


def test_values_are_unchanged_by_the_rename(tmp_path):
    src = _synthetic_l1(tmp_path)
    dst = tmp_path / "out_OG1.nc"
    convert_to_og1(src, dst)

    with xr.open_dataset(src) as before, xr.open_dataset(dst) as after:
        np.testing.assert_array_equal(before["temperature"].values, after["TEMP"].values)
        np.testing.assert_array_equal(before["conductivity"].values, after["CNDC"].values)


def test_conventions_gains_og1_marker(tmp_path):
    src = _synthetic_l1(tmp_path)
    dst = tmp_path / "out_OG1.nc"
    convert_to_og1(src, dst)

    with xr.open_dataset(dst) as out:
        conventions = out.attrs["Conventions"]
        assert "CF-1.8" in conventions  # existing conventions preserved
        assert "OG-1.0" in conventions  # marker added


def test_no_variable_is_ever_silently_dropped(tmp_path):
    src = _synthetic_l1(tmp_path)
    dst = tmp_path / "out_OG1.nc"
    with xr.open_dataset(src) as before:
        before_vars = set(before.variables)
    convert_to_og1(src, dst)
    with xr.open_dataset(dst) as after:
        after_vars = {CF_TO_OG1.get(v, v) for v in before_vars}
        assert after_vars <= set(after.variables)


def test_default_does_not_produce_n_measurements(tmp_path):
    # rename_point_dim defaults to False -- this is the L2 (gridded) path.
    # The plain variable rename ("time" -> "TIME") still carries the
    # dimension along with it (that's ordinary xarray behaviour, not new),
    # but it must NOT go as far as OG1.0's N_MEASUREMENTS structure, and
    # TIME stays an index coordinate.
    src = _synthetic_l1(tmp_path)
    dst = tmp_path / "out_OG1.nc"
    convert_to_og1(src, dst)

    with xr.open_dataset(dst) as out:
        assert "N_MEASUREMENTS" not in out.sizes
        assert "TIME" in out.indexes


def test_rename_point_dim_produces_real_og1_structure(tmp_path):
    # rename_point_dim=True is the L1 path -- this is what pelagos-py's
    # "Load OG1" step actually requires (see convert_to_og1's docstring:
    # it calls ds.reset_coords("TIME"), which xarray refuses if TIME is
    # still an index coordinate).
    src = _synthetic_l1(tmp_path)
    dst = tmp_path / "out_OG1.nc"
    convert_to_og1(src, dst, rename_point_dim=True)

    with xr.open_dataset(dst) as out:
        assert "N_MEASUREMENTS" in out.sizes
        assert "time" not in out.sizes
        assert "TIME" not in out.indexes  # not an index coordinate anymore
        # the actual operation pelagos-py's Load OG1 step performs -- must
        # not raise "cannot remove index coordinates with reset_coords"
        out.reset_coords("TIME", drop=False)


def test_geophysical_variables_get_a_vocabulary_attr(tmp_path):
    src = _synthetic_l1(tmp_path)
    dst = tmp_path / "out_OG1.nc"
    convert_to_og1(src, dst)

    with xr.open_dataset(dst) as out:
        assert out["TEMP"].attrs["vocabulary"] == "http://vocab.nerc.ac.uk/collection/OG1/current/TEMP/"
        assert out["CNDC"].attrs["vocabulary"] == "http://vocab.nerc.ac.uk/collection/OG1/current/CNDC/"


def test_structural_variables_do_not_get_a_vocabulary_attr(tmp_path):
    # TRAJECTORY is renamed (it's in CF_TO_OG1) but is not a "geophysical
    # variable" in the format manual's sense -- no vocabulary claim.
    src = _synthetic_l1(tmp_path)
    dst = tmp_path / "out_OG1.nc"
    convert_to_og1(src, dst)

    with xr.open_dataset(dst) as out:
        assert "vocabulary" not in out["TRAJECTORY"].attrs


def test_coordinates_attr_is_reformatted_to_og1_order(tmp_path):
    # xarray decodes and strips the `coordinates` attribute into real
    # coordinate structure on open_dataset -- it's not visible via the
    # normal (decoded) .attrs, only in the raw file. Check the raw file,
    # same as the direct verification this behaviour was confirmed with.
    src = _synthetic_l1(tmp_path)
    dst = tmp_path / "out_OG1.nc"
    convert_to_og1(src, dst)

    with xr.open_dataset(dst, decode_cf=False) as raw:
        assert raw["TEMP"].attrs["coordinates"] == "TIME, LONGITUDE, LATITUDE, DEPTH"


def test_metadata_none_adds_no_global_attrs(tmp_path):
    # Default -- no metadata passed -- must not add id/title/platform/etc.
    # (this is also what all the earlier tests in this file rely on).
    src = _synthetic_l1(tmp_path)
    dst = tmp_path / "out_OG1.nc"
    convert_to_og1(src, dst)

    with xr.open_dataset(dst) as out:
        assert "platform" not in out.attrs
        assert "id" not in out.attrs


def test_metadata_fills_in_og1_global_attrs(tmp_path):
    src = _synthetic_l1(tmp_path)
    dst = tmp_path / "out_OG1.nc"
    convert_to_og1(src, dst, metadata=_SAMPLE_METADATA)

    with xr.open_dataset(dst) as out:
        assert out.attrs["id"] == "test-deployment"
        assert out.attrs["title"] == "Test mission for og1 convert unit tests."
        assert out.attrs["platform"] == "sub-surface gliders"
        assert out.attrs["platform_vocabulary"] == "http://vocab.nerc.ac.uk/collection/L06/current/27/"
        assert out.attrs["rtqc_method"] == "No QC applied"
        assert out.attrs["naming_authority"] == "no.uib"
        assert out.attrs["site"] == "Norwegian Sea"
        assert out.attrs["program"] == "testproj"
        assert out.attrs["doi"] == "10.1234/test"
        assert out.attrs["contributor_email"] == "test.person@uib.no"  # fell back to creator_email
        assert out.attrs["contributing_institutions"] == "University of Bergen"
        assert out.attrs["contributing_institutions_role"] == "Operator"
        assert (out.attrs["contributing_institutions_role_vocabulary"]
                == "http://vocab.nerc.ac.uk/collection/W08/current/CONT0003/")
        assert "date_created" in out.attrs  # generated, just check it's there


def test_partially_mapped_contributor_role_leaves_vocabulary_unset(tmp_path):
    # "Made Up Role" (in _SAMPLE_METADATA) has no ROLE_TO_NERC_CONT entry --
    # the whole contributor_role_vocabulary attr must be left unset rather
    # than a partial/misleading list.
    src = _synthetic_l1(tmp_path)
    dst = tmp_path / "out_OG1.nc"
    convert_to_og1(src, dst, metadata=_SAMPLE_METADATA)

    with xr.open_dataset(dst) as out:
        assert out.attrs["contributor_role"] == "Principal Investigator, Made Up Role"
        assert "contributor_role_vocabulary" not in out.attrs


def test_fully_mapped_contributor_role_sets_vocabulary(tmp_path):
    src = _synthetic_l1(tmp_path)
    dst = tmp_path / "out_OG1.nc"
    metadata = dict(_SAMPLE_METADATA, contributor_role="Principal Investigator, Operator")
    convert_to_og1(src, dst, metadata=metadata)

    with xr.open_dataset(dst) as out:
        assert out.attrs["contributor_role_vocabulary"] == (
            "http://vocab.nerc.ac.uk/collection/W08/current/CONT0004/, "
            "http://vocab.nerc.ac.uk/collection/W08/current/CONT0003/"
        )


def test_no_glider_devices_adds_no_sensor_variables(tmp_path):
    src = _synthetic_l1(tmp_path)
    dst = tmp_path / "out_OG1.nc"
    convert_to_og1(src, dst)  # no glider_devices passed at all

    with xr.open_dataset(dst) as out:
        assert not [v for v in out.variables if v.startswith("SENSOR_")]
        assert "sensor" not in out["TEMP"].attrs


def test_ctd_device_creates_sensor_ctd_and_tags_its_variables(tmp_path):
    src = _synthetic_l1(tmp_path)
    dst = tmp_path / "out_OG1.nc"
    convert_to_og1(src, dst, glider_devices=_SAMPLE_GLIDER_DEVICES)

    with xr.open_dataset(dst) as out:
        assert "SENSOR_CTD" in out.variables
        sensor = out["SENSOR_CTD"].attrs
        assert sensor["make_model"] == "Sea-Bird SBE 41CP"
        assert sensor["sensor_serial_number"] == "69"
        assert sensor["sensor_calibration_date"] == "2016-02-19"
        assert sensor["type"] == "CTD"
        # blank placeholder fields (" ") must not become attrs
        assert "maker" not in sensor
        assert "calibration_report" not in sensor

        assert out["TEMP"].attrs["sensor"] == "SENSOR_CTD"
        assert out["CNDC"].attrs["sensor"] == "SENSOR_CTD"
        assert out["PSAL"].attrs["sensor"] == "SENSOR_CTD"  # derived CTD quantity, still attributed to the CTD


def test_optics_device_creates_sensor_fluorometer(tmp_path):
    src = _synthetic_l1(tmp_path)
    dst = tmp_path / "out_OG1.nc"
    convert_to_og1(src, dst, glider_devices=_SAMPLE_GLIDER_DEVICES)

    with xr.open_dataset(dst) as out:
        assert "SENSOR_FLUOROMETER" in out.variables
        assert out["SENSOR_FLUOROMETER"].attrs["maker"] == "WET Labs"
        assert out["CHLA"].attrs["sensor"] == "SENSOR_FLUOROMETER"


def test_variable_with_no_device_entry_gets_no_sensor_attr(tmp_path):
    # Mirrors mission 028's real gap: oxygen_concentration/DOXY is present
    # in the file, but glider_devices has no "oxygen" entry (OGDB never got
    # an asset assignment for it). Must not fabricate a SENSOR_DOXY, and
    # DOXY must not get a `sensor` attribute pointing at nothing.
    src = _synthetic_l1(tmp_path)
    dst = tmp_path / "out_OG1.nc"
    convert_to_og1(src, dst, glider_devices=_SAMPLE_GLIDER_DEVICES)

    with xr.open_dataset(dst) as out:
        assert "DOXY" in out.variables  # the data is still there
        assert "SENSOR_DOXY" not in out.variables
        assert "sensor" not in out["DOXY"].attrs


def test_sensor_variables_are_scalar_nan(tmp_path):
    # Matches pyglider's own OG1.0 fixture: SENSOR_* carry no real data,
    # all information lives in their attributes.
    src = _synthetic_l1(tmp_path)
    dst = tmp_path / "out_OG1.nc"
    convert_to_og1(src, dst, glider_devices=_SAMPLE_GLIDER_DEVICES)

    with xr.open_dataset(dst) as out:
        assert out["SENSOR_CTD"].dims == ()
        assert np.isnan(out["SENSOR_CTD"].values)
