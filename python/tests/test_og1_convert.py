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
            "turbidity": ("time", np.full(n, 0.1)),          # deliberately unmapped
            "profile_index": ("time", np.array([1, 1, 1.5, 2, 2])),  # deliberately unmapped
            "trajectory": ((), "test-deployment"),
        },
        coords={"time": ("time", np.array(["2017-09-06T12:00:00"] * n, dtype="datetime64[s]"))},
        attrs={"Conventions": "CF-1.8, ACDD-1.3", "processing_level": "L1"},
    )
    src = tmp_path / "in_L1.nc"
    ds.to_netcdf(src)
    return src


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
