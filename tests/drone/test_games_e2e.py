"""Both demos end to end against two in-process Tello simulators (needs ffmpeg for the video link)."""
import os
import shutil
import sys

import pytest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(REPO_ROOT, "test_scripts", "drone", "local"))

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is required for the simulator video")


def run(tmp_path, *args):
    import run_local
    return run_local.main(["--report_dir", str(tmp_path / "report"), "--kill_file", str(tmp_path / "kill"),
                           "--sim_speed", "4", *args])


def assert_report(tmp_path):
    idx = tmp_path / "report" / "index.html"
    assert idx.exists()
    assert list((tmp_path / "report" / "frames").glob("*.jpg"))


def test_race_sofa_has_referee_confirmed_winner(tmp_path):
    k = run(tmp_path, "--game", "race", "--target", "sofa", "--seed", "1")
    assert k["winner"] in ("drone1", "drone2")
    assert k["time_to_win_s"] is not None and k["claims"] >= 1
    assert k["landed"]
    assert list((tmp_path / "report" / "frames").glob("*_winner_*.jpg"))
    assert_report(tmp_path)


def test_hide_and_seek_ends_cleanly(tmp_path):
    k = run(tmp_path, "--game", "hide", "--seed", "1", "--hide_s", "12", "--seek_s", "60")
    assert k["winner"] in ("drone1", "drone2")  # seeker found the hider, or the hider stayed hidden
    assert k["landed"] and not k["killed"]
    assert_report(tmp_path)
