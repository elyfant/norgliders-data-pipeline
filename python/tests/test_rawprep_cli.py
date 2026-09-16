"""slocum-rawprep CLI wiring — synthetic dirs, no real Slocum binaries."""

import pytest

from norgliders_data_pipeline.scripts import rawprep_mission as cli


@pytest.fixture()
def mission_tree(tmp_path):
    root = tmp_path / "delayed"
    raw = root / "042-test_mission" / "raw"
    (raw / "cardA").mkdir(parents=True)
    (raw / "cardB").mkdir(parents=True)
    # not real headers -> step 3 will quarantine them, but steps 1/2/4 still run
    (raw / "cardA" / "00010000.dbd").write_text("junk")
    (raw / "cardB" / "00010000.ebd").write_text("junk")
    (raw / "cardA" / "abcd1234.cac").write_text("x")
    cache = tmp_path / "cache"
    cache.mkdir()
    return root, cache


def test_stages_and_quarantines(mission_tree, caplog):
    root, cache = mission_tree
    rc = cli.main(["42", "--data-root", str(root), "--cache", str(cache)])
    assert rc == 0  # no *referenced* cache missing

    binary = root / "042-test_mission" / "binary"
    # binaries copied out of the nested card layout, then quarantined as unreadable
    assert (binary / "unused" / "00010000.dbd").is_file()
    assert (binary / "unused" / "00010000.ebd").is_file()
    # cache file routed to the master cache, not binary/
    assert (cache / "abcd1234.cac").is_file()


def test_unknown_mission_errors(tmp_path):
    with pytest.raises(SystemExit):
        cli.main(["77", "--data-root", str(tmp_path)])


def test_explicit_raw_binary(mission_tree, tmp_path):
    root, cache = mission_tree
    out = tmp_path / "elsewhere" / "binary"
    rc = cli.main([
        "anything",
        "--raw", str(root / "042-test_mission" / "raw"),
        "--binary", str(out),
        "--cache", str(cache),
    ])
    assert rc == 0
    assert (out / "unused").is_dir()
