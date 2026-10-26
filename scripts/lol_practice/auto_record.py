"""TASK-131: record and score every League game on vpt-windows without anyone asking (runs forever, read-only).

Run under ``pythonw.exe`` (no console window, BUG-0628) by the hidden scheduled task made with
``install_auto_record_task.ps1``. Waits for ``League of Legends.exe``; when a game's clock runs, polls the Live Client
Data API every 2 s, reads the minimap zone every 5 s and saves a 960x600 screenshot every 20 s into
``C:\\virtualpytest\\lol-run-<stamp>\\``; when the game ends writes ``lol-scorecard.json`` + ``.html`` there.
Skipped while the Garen bot is playing (it records its own run). Never sends input.
"""
import os
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, r"C:\virtualpytest\virtualpytest")
sys.path.insert(0, r"C:\virtualpytest")

ROOT = Path(os.environ.get("LOL_RUNS_ROOT", r"C:\virtualpytest"))
BOT_SCRIPTS = ("run_garen_bot", "run_llm_bench", "garen_bot")  # any bot runner records its own run folder


def bot_is_playing(root: Path = ROOT, now=time.time) -> bool:
    """True while a bot run records: its process is alive, or a garen-run folder has a fresh timeline and no result."""
    import psutil

    for p in psutil.process_iter(["cmdline"]):
        if any(s in " ".join(p.info.get("cmdline") or []) for s in BOT_SCRIPTS):
            return True
    for d in root.glob("*run*"):
        if d.name.startswith("lol-run-"):
            continue  # our own folders
        tl = d / "timeline.json"
        if tl.exists() and not (d / "result.json").exists() and now() - tl.stat().st_mtime < 180:
            return True
    return False


def record_one(root: Path = ROOT) -> None:
    from PIL import Image, ImageGrab
    import numpy as np

    from shared.src.lib.game.leagueoflegends import cs_reader, live_recorder, minimap, perception, score_run
    from shared.src.lib.game.leagueoflegends.minion_events import MinionWatcher
    from shared.src.lib.game.leagueoflegends.process_utils import is_running

    out = root / time.strftime("lol-run-%Y%m%d-%H%M%S")
    (out / "shots").mkdir(parents=True)
    tl, last = None, {"poll": -99.0, "zone": -99.0, "shot": -99.0}
    watcher, last_t = MinionWatcher(), 0.0
    misses = 0
    while True:
        d = live_recorder.fetch_all_game_data()
        if d is None:
            misses += 1
            if misses >= 15 or not is_running("League of Legends.exe"):
                break
            time.sleep(2)
            continue
        misses = 0
        gt = float((d.get("gameData") or {}).get("gameTime", 0.0))
        if tl is None:
            if gt <= 1:
                time.sleep(1)
                continue
            tl = live_recorder.new_timeline(d)
            tl.setdefault("zones", [])
        if gt - last["poll"] >= 2.0:
            last["poll"] = gt
            if live_recorder.add_poll(tl, d):  # GameEnd
                break
        try:  # every pass (about 2 Hz): enemy minion bars + exact CS -> minion deaths, ours or missed
            full = np.asarray(ImageGrab.grab().convert("RGB"))
            watcher.update(gt, perception.find_bars(full, "enemy"), cs_reader.read_cs(full[..., ::-1]))
            last_t = gt
        except Exception:
            traceback.print_exc()
        if gt - last["zone"] >= 5.0:
            last["zone"] = gt
            try:
                img = np.asarray(ImageGrab.grab().convert("RGB"))[..., ::-1]  # BGR
                cs = cs_reader.read_cs(img)
                if cs is not None:
                    tl.setdefault("cs_exact", []).append({"t": gt, "cs": cs})
                z = minimap.find_camera_box(minimap.crop_minimap(img))
                if z is not None:
                    tl["zones"].append({"t": gt, "zone": minimap.zone_of(*z), "x": round(z[0], 3), "y": round(z[1], 3)})
                if gt - last["shot"] >= 20.0:
                    last["shot"] = gt
                    Image.fromarray(img[..., ::-1]).resize((960, 600)).save(out / "shots" / f"t{int(gt):05d}.png")
            except Exception:
                traceback.print_exc()
        time.sleep(0.3)
    if tl is None:
        return
    tl["minion_deaths"] = watcher.finish(last_t)
    live_recorder.save_timeline(tl, str(out / "timeline.json"))
    (out / "result.json").write_text('{"recorded_by": "auto_record"}')
    score_run.score_run_dir(str(out))


def main() -> int:
    log = open(ROOT / "auto_record.log", "a", buffering=1)
    sys.stdout = sys.stderr = log
    from shared.src.lib.game.leagueoflegends.process_utils import is_running

    print(time.strftime("%F %T"), "auto_record started", flush=True)
    while True:
        try:
            if is_running("League of Legends.exe") and not bot_is_playing():
                print(time.strftime("%F %T"), "game found, recording", flush=True)
                record_one()
                print(time.strftime("%F %T"), "game scored", flush=True)
                while is_running("League of Legends.exe"):  # one record per game; wait for the client to close it
                    time.sleep(10)
        except Exception:
            traceback.print_exc()
        time.sleep(5)


if __name__ == "__main__":
    raise SystemExit(main())
