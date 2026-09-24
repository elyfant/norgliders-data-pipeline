"""build_qc() wiring to pelagos-py. Runs a real (not mocked) pelagos-py
Pipeline against a synthetic OG1 L1 file -- no real mission data needed."""

import numpy as np
import xarray as xr

from norgliders_data_pipeline.og1.convert import convert_to_og1
from norgliders_data_pipeline.qc.run import build_qc


def _synthetic_og1_l1(tmp_path):
    """A tiny genuinely-OG1.0-structured L1 (N_MEASUREMENTS dim, TIME not
    an index) -- built via convert_to_og1 itself, so this fixture is only
    as good as code already covered by test_og1_convert.py."""
    n = 5
    ds = xr.Dataset(
        {
            "temperature": ("time", np.array([10.0, 10.1, 10.2, 10.3, 10.4])),
            "conductivity": ("time", np.full(n, 3.5)),
            "latitude": ("time", np.full(n, 60.0)),
            "longitude": ("time", np.full(n, 5.0)),
            "pressure": ("time", np.linspace(0, 50, n)),
            "trajectory": ((), "test-deployment"),
        },
        coords={"time": ("time", np.array(
            ["2017-09-06T12:00:00", "2017-09-06T12:00:10", "2017-09-06T12:00:20",
             "2017-09-06T12:00:30", "2017-09-06T12:00:40"], dtype="datetime64[s]"))},
        attrs={"Conventions": "CF-1.8, ACDD-1.3", "processing_level": "L1",
               "deployment_name": "test-deployment"},
    )
    cf_src = tmp_path / "in_L1.nc"
    ds.to_netcdf(cf_src)

    og1_src = tmp_path / "in_L1_OG1.nc"
    convert_to_og1(cf_src, og1_src, rename_point_dim=True)
    return og1_src


def _empty_pipeline_yaml(tmp_path):
    p = tmp_path / "empty_pipeline.yaml"
    p.write_text("steps: []\n")
    return p


def test_build_qc_runs_pelagos_and_writes_output(tmp_path):
    og1_l1 = _synthetic_og1_l1(tmp_path)
    out_dir = tmp_path / "QC"

    dst = build_qc("test-deployment", og1_l1, out_dir,
                    pipeline_yaml=_empty_pipeline_yaml(tmp_path))

    assert dst == out_dir / "test-deployment_L1_QC.nc"
    assert dst.is_file()


def test_qc_output_carries_the_same_values_through_when_no_steps_run(tmp_path):
    og1_l1 = _synthetic_og1_l1(tmp_path)
    out_dir = tmp_path / "QC"

    dst = build_qc("test-deployment", og1_l1, out_dir,
                    pipeline_yaml=_empty_pipeline_yaml(tmp_path))

    with xr.open_dataset(og1_l1) as before, xr.open_dataset(dst) as after:
        np.testing.assert_array_equal(before["TEMP"].values, after["TEMP"].values)
        np.testing.assert_array_equal(before["CNDC"].values, after["CNDC"].values)


def test_og1_source_file_is_not_modified(tmp_path):
    og1_l1 = _synthetic_og1_l1(tmp_path)
    out_dir = tmp_path / "QC"
    before_mtime = og1_l1.stat().st_mtime

    build_qc("test-deployment", og1_l1, out_dir,
             pipeline_yaml=_empty_pipeline_yaml(tmp_path))

    assert og1_l1.stat().st_mtime == before_mtime


def test_default_facility_pipeline_is_used_when_none_given(tmp_path):
    # No pipeline_yaml passed -- must fall back to the packaged
    # facility_pipeline.yaml (currently steps: []) without raising.
    og1_l1 = _synthetic_og1_l1(tmp_path)
    dst = build_qc("test-deployment", og1_l1, tmp_path / "QC")
    assert dst.is_file()
