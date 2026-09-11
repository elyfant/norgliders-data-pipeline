"""CF L1/L2 cleanup once OG1 has been written. No pyglider/real data needed
-- just the file-deletion behaviour."""

from slocum_data_processing.processing.pyglider_run import _discard_cf_intermediates


def test_deletes_l1_and_l2(tmp_path):
    l1 = tmp_path / "mission_L1.nc"
    l2a = tmp_path / "mission_L2.nc"
    l1.write_text("l1"), l2a.write_text("l2")

    _discard_cf_intermediates(l1, [l2a])

    assert not l1.exists()
    assert not l2a.exists()


def test_multiple_l2_files_all_deleted(tmp_path):
    l1 = tmp_path / "mission_L1.nc"
    l2s = [tmp_path / f"mission_L2_{i}.nc" for i in range(3)]
    l1.write_text("l1")
    for f in l2s:
        f.write_text("l2")

    _discard_cf_intermediates(l1, l2s)

    assert not l1.exists()
    assert all(not f.exists() for f in l2s)


def test_missing_files_are_not_an_error(tmp_path):
    # L2 build can be skipped (e.g. no complete profiles) -- l2s may be empty,
    # or a path may simply not exist. Should never raise.
    l1 = tmp_path / "mission_L1.nc"
    l1.write_text("l1")
    _discard_cf_intermediates(l1, [tmp_path / "does_not_exist_L2.nc"])
    assert not l1.exists()


def test_other_files_in_the_directory_are_untouched(tmp_path):
    l1 = tmp_path / "mission_L1.nc"
    l1.write_text("l1")
    l0 = tmp_path / "mission_L0.nc"
    l0.write_text("keep me")

    _discard_cf_intermediates(l1, [])

    assert not l1.exists()
    assert l0.exists()
