"""Tests on synthetic inputs: no video, no tesseract. Run from the project root: pytest"""
import json
import os
import re

import pytest

from lol_dataset import __main__ as cli
from lol_dataset.build import build_tables, nearest
from lol_dataset.schema import TABLES

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _write(path, text):
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return str(path)


@pytest.fixture
def capture(tmp_path):
    """A 0.6 s capture at 5 Hz: the subject on CHAOS (red) with one minion of each side, one kill by the subject."""
    roster = [{"championName": "Garen", "team": "CHAOS", "riotIdGameName": "PlayerA"},
              {"championName": "Jinx", "team": "ORDER", "riotIdGameName": "PlayerB"}]
    rows = []
    for n, t in enumerate([60.0, 60.2, 60.4, 60.6]):
        rows.append({"t": t,
                     "state": {"hp": 500 - n, "hp_max": 600, "cs": n, "kda": [0, 0, 0], "ad": 80, "as": 0.6, "ms": 340,
                               "armor": 30, "level": 3, "items": [1054], "dead": False, "world_pos": [1000 + 40 * n, 2000],
                               "spells": {"Q": {"rank": 1, "ready": True, "ready_in_s": None}}},
                     "world": {"units": [
                         {"kind": "ally_minion", "id": 1, "hp_frac": 0.8, "px": [900, 500], "dist_px": 120, "in_attack_range": True},
                         {"kind": "enemy_minion", "id": 2, "hp_frac": 0.5 - 0.1 * n, "px": [1010, 520], "dist_px": 80,
                          "in_attack_range": False}]},
                     "events": [], "inputs": []})
    det = _write(tmp_path / "det.jsonl", "\n".join(json.dumps(r) for r in rows) + "\n")
    log = _write(tmp_path / "log.jsonl", "\n".join(json.dumps({"t": t, "camera": {"x": 4000.0, "z": 10000.0}})
                                                  for t in [59.9, 60.1, 60.3, 60.5, 60.7]) + "\n")
    events = _write(tmp_path / "events.json", json.dumps({"Events": [
        {"EventID": 2, "EventName": "ChampionKill", "EventTime": 60.5, "KillerName": "PlayerA", "VictimName": "PlayerB",
         "Assisters": []}]}))
    roster_path = _write(tmp_path / "roster.json", json.dumps(roster))
    return {"det": det, "log": log, "events": events, "roster": roster_path, "dir": tmp_path}


def test_nearest_finds_closest_within_tolerance():
    times = [0.0, 0.2, 0.4]
    assert nearest(times, 0.19, 0.05) == 1
    assert nearest(times, 0.5, 0.05) is None
    assert nearest([], 1.0, 1.0) is None


def test_build_on_synthetic_capture(capture):
    tables, meta, coverage = build_tables(None, capture["log"], capture["events"], capture["roster"], capture["det"],
                                          "Garen", 60.0, 60.6, "t1", frame0=52.5)
    assert set(TABLES) <= set(tables) and "decisions" in tables      # decisions.jsonl is the Jev export
    assert len(tables["ticks"]) == 7                       # 60.0 .. 60.6 at 10 Hz
    assert all(dp["chosen"] in ("hold", "move") or dp["chosen"].startswith("auto:") for dp in tables["decision_points"])
    assert all(dp["chosen_inferred"] is True for dp in tables["decision_points"])
    assert meta["subject_side"] == "red" and meta["subject_team"] == "CHAOS"
    subject = [r for r in tables["champions"] if r["is_subject"]]
    assert subject and subject[0]["uid"] == "Garen" and subject[0]["champion"] == "Garen" and subject[0]["level"] == 3
    minions = [r for r in tables["minions"] if r["observed"]]
    assert minions, "observed minion rows expected"
    ally = next(r for r in minions if r["rel"] == "ally")
    assert ally["x"] is None and ally["y"] is None            # no calibration: map units stay null
    assert ally["px"] == 900 and ally["pos_kind"] == "screen_px"
    # one stable uid per minion across the four observed frames; the enemy minion lost HP but did not die
    enemy_uids = {r["uid"] for r in minions if r["rel"] == "enemy"}
    assert len(enemy_uids) == 1
    enemy_rows = [r for r in minions if r["rel"] == "enemy"]
    assert all(enemy_rows[i]["hp_frac"] >= enemy_rows[i + 1]["hp_frac"] for i in range(len(enemy_rows) - 1))
    assert all(r["alive"] for r in enemy_rows)
    assert all(r["observed"] for r in tables["minions"])        # entity rows exist only on observed frames
    # the subject's kill at 60.5 counts for the red team (Garen is on CHAOS = 200)
    team_red = [r for r in tables["teams"] if r["team"] == "200" and r["tick"] >= 605]
    assert team_red and all(r["kills"] == 1 for r in team_red)
    assert coverage["turrets"]["uid"]["status"] == "missing"       # no turret detector: empty table
    assert coverage["minions"]["x"]["status"] == "missing"


def test_cli_extract_then_view(capture, tmp_path):
    out = tmp_path / "ds"
    cli.main(["extract", "--video", str(tmp_path / "none.mkv"), "--log", capture["log"], "--events", capture["events"],
              "--roster", capture["roster"], "--detections", capture["det"], "--subject", "Garen", "--gid", "t1",
              "--out", str(out), "--t0", "60.0", "--t1", "60.6", "--frame0", "52.5",
              "--salt-file", _write(tmp_path / "salt.txt", "test-salt")])
    for name in TABLES:
        assert (out / f"{name}.jsonl").exists()
    coverage = json.load(open(out / "coverage.json", encoding="utf-8"))
    assert set(coverage) == set(TABLES)
    html = tmp_path / "view.html"
    cli.main(["view", "--dataset", str(out), "--html", str(html)])
    assert "LoL dataset t1 (Garen)" in html.read_text(encoding="utf-8")


def test_unknown_subject_is_refused(capture):
    with pytest.raises(SystemExit):
        build_tables(None, capture["log"], capture["events"], capture["roster"], capture["det"], "Nobody", 60.0, 60.6, "t1",
                     frame0=52.5)


def test_package_has_no_hosts_ips_or_home_paths():
    pattern = re.compile(r"/Users/|~/|192\.168\.|10\.10\.|proxmox|angelstreet\.io|virtualpytest|vpt-[a-z]")
    hits = []
    for root, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in ("tests", "__pycache__", ".pytest_cache")]
        for name in files:
            if name.endswith((".py", ".md", ".toml", ".txt")):
                with open(os.path.join(root, name), encoding="utf-8", errors="ignore") as f:
                    for n, line in enumerate(f, 1):
                        if pattern.search(line):
                            hits.append(f"{name}:{n}")
    assert not hits, hits


def test_tracker_keeps_uid_through_camera_motion_and_a_gap():
    """One minion walks at 100 stage px/s while the camera pans (screen px move with the camera). A 0.8 s detection
    gap must not break its uid, and a second minion stays separate."""
    from lol_dataset import tracker
    frames = []
    for n in range(40):                                # 8 s at 5 Hz
        t = round(60.0 + 0.2 * n, 2)
        cam_x = 4000.0 + 50.0 * n                      # camera pans right
        cam_z = 10000.0
        world_sx = 500.0 + 100.0 * (t - 60.0)          # walker's stage position
        px = world_sx - tracker.KX * cam_x             # what the screen shows
        units = [] if 1.0 <= t - 60.0 < 1.8 else [{"kind": "enemy_minion", "px": [px, 300.0], "hp_frac": 0.9, "dist_px": 100}]
        units.append({"kind": "enemy_minion", "px": [1200.0 - tracker.KX * cam_x + 300.0, 600.0], "hp_frac": 0.6, "dist_px": 200})
        frames.append({"tick": round(t * 10), "t": t, "row": {"world": {"units": units}}, "cam_x": cam_x, "cam_z": cam_z})
    rows, tracks, _ = tracker.track_frames(frames, "g")
    walker = [r for r in rows if r["px"] < 1000 and r["py"] == 300.0]
    assert len({r["uid"] for r in walker}) == 1
    assert len(tracks) == 2


def test_default_keeps_public_riot_ids(capture, tmp_path):
    """Default export keeps the in-game Riot IDs (public names) in players.jsonl."""
    out = tmp_path / "ds"
    cli.main(["extract", "--video", str(tmp_path / "none.mkv"), "--log", capture["log"], "--events", capture["events"],
              "--roster", capture["roster"], "--detections", capture["det"], "--subject", "Garen", "--gid", "t1",
              "--out", str(out), "--t0", "60.0", "--t1", "60.6", "--frame0", "52.5"])
    assert "PlayerA" in (out / "players.jsonl").read_text(encoding="utf-8")


def test_anonymize_has_no_player_names(capture, tmp_path):
    """--anonymize: the output carries no roster Riot name; each is replaced by its salted pseudonym."""
    out = tmp_path / "ds"
    cli.main(["extract", "--video", str(tmp_path / "none.mkv"), "--log", capture["log"], "--events", capture["events"],
              "--roster", capture["roster"], "--detections", capture["det"], "--subject", "Garen", "--gid", "t1",
              "--out", str(out), "--t0", "60.0", "--t1", "60.6", "--frame0", "52.5", "--anonymize",
              "--salt-file", _write(tmp_path / "salt.txt", "test-salt")])
    names = ["PlayerA", "PlayerB"]
    for f in out.iterdir():
        text = f.read_text(encoding="utf-8")
        for n in names:
            assert n not in text, (f.name, n)


def test_pseudonym_is_salted_and_stable():
    from lol_dataset.privacy import pseudonym, scrub
    assert pseudonym("PlayerA", "a") == pseudonym("PlayerA", "a")
    assert pseudonym("PlayerA", "a") != pseudonym("PlayerA", "b")
    out = scrub({"x": ["Example Player did it", {"y": "Example"}]}, ["Example Player", "Example"], "s")
    assert "Example" not in str(out)


def test_jev_cut_no_double_count_and_options():
    """Coach and tactician points: the damage in a window is the HP lost across its 1 s slices (no double count), the
    chosen label is always one of the runtime options, and the window starts at the anchor."""
    from lol_dataset import jev_cut as jc
    rows = []
    for i in range(0, 140):                   # subject every 0.2 s, 60 .. 88 s; 54 HP lost over 60..63 s
        t = round(60.0 + 0.2 * i, 2)
        hp = 810 - 54 * min(1.0, (t - 60.0) / 3.0)
        rows.append({"tick": round(t * 10), "t_s": t, "observed": True, "is_subject": True, "champion": "Garen",
                     "uid": "Garen", "hp": hp, "hp_max": 810, "hp_frac": hp / 810, "level": 1, "cs": 0,
                     "alive": True, "est_x": 0.0, "est_z": 0.0, "x": None, "rel": "ally", "ad": 80, "items": [],
                     "cd_ready_in_s": [None, None, None, None, None, None]})
    tables = {"champions": rows, "minions": [], "events": []}
    pts = jc.cut(tables, "g", 60.0, 88.0, "tactician")
    p = next(x for x in pts if x["t_s"] == 60.0)
    assert p["outcome"]["damage"] == pytest.approx(54.0, abs=0.5)     # 810 -> 756 over 60.6 .. 63.6 s
    assert p["reward_parts"]["damage"] == pytest.approx(-0.54, abs=0.01)
    assert p["chosen"] in {o["id"] for o in p["options"]}
    coach = jc.cut(tables, "g", 60.0, 88.0, "coach")
    assert all(c["chosen"] in {o["id"] for o in c["options"]} for c in coach)
