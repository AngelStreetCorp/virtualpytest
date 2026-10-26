"""TASK-132: start a Practice Tool game as Garen, let the bot play it, record + score it, leave the game.

Run in the user's session (see create_garen_task.ps1). Safety: all input goes through game_input.PracticeGuard
(running League of Legends.exe AND gameMode == PRACTICETOOL). Writes into C:\\virtualpytest\\garen-run-<stamp>\\:
timeline.json, scorecard.json, scorecard.html, shots\\, result.json. Args: <seconds> [blue|red] (env GAREN_MAX_S / GAREN_TEAM). Red side: the lobby API cannot switch teams, so the Team 2 Join button is found by template and clicked.
"""
import json
import os
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, r"C:\virtualpytest\virtualpytest")
sys.path.insert(0, r"C:\virtualpytest")

import numpy as np  # noqa: E402
from PIL import ImageGrab  # noqa: E402

from shared.src.lib.game.leagueoflegends import live_recorder, scorecard as sc  # noqa: E402
from shared.src.lib.game.leagueoflegends.game_input import GameInput  # noqa: E402
from shared.src.lib.game.leagueoflegends.garen_bot import GarenBot  # noqa: E402
from shared.src.lib.game.leagueoflegends.minimap import zone_of  # noqa: E402
from shared.src.lib.game.leagueoflegends.perception import view_box_position  # noqa: E402
from shared.src.lib.game.leagueoflegends.practice_runner import PracticeConfig, PracticeRunner  # noqa: E402

GAREN = 86
OUT = Path(r"C:\virtualpytest") / time.strftime("garen-run-%Y%m%d-%H%M%S")
MAX_S = float(os.environ.get("GAREN_MAX_S", sys.argv[1] if len(sys.argv) > 1 else "600"))


def join_red() -> None:
    """Wait for the lobby's Team 2 "Join" button (template match on a screenshot), then click its centre."""
    import ctypes
    import tempfile

    from shared.src.lib.game.leagueoflegends.vision_nav import JOIN_TEAM2, NavTargetDetector

    det = NavTargetDetector()
    shot = Path(tempfile.gettempdir()) / "join_team2_probe.png"
    for _ in range(20):
        frame = ImageGrab.grab(all_screens=True)
        frame.save(shot)
        hit = det.detect_best(shot, JOIN_TEAM2)
        print(f"[join_red] button {'found' if hit else 'not found'}", flush=True)
        if hit is not None:
            w, h = frame.size
            u = ctypes.windll.user32
            u.SetCursorPos(int(hit.normalized.x * w), int(hit.normalized.y * h))
            time.sleep(0.3)
            u.mouse_event(2, 0, 0, 0, 0)
            time.sleep(0.1)
            u.mouse_event(4, 0, 0, 0, 0)
            return
        time.sleep(1.0)


def grab() -> np.ndarray:
    return np.asarray(ImageGrab.grab(all_screens=True).convert("RGB"))


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "shots").mkdir(exist_ok=True)
    log = open(OUT / "run.log", "w", buffering=1)
    sys.stdout = log
    sys.stderr = log  # a crash is never silent
    result = {"ok": False, "out": str(OUT)}
    video = None
    try:
        from shared.src.lib.game.leagueoflegends.recorder_proc import kill_stale_recorders

        kill_stale_recorders(lambda m: print(m, flush=True))  # orphans of crashed runs (10 h of desktop recording, 2026-10-18)
        red = (sys.argv[2] if len(sys.argv) > 2 else os.environ.get("GAREN_TEAM", "")).lower() in ("red", "chaos", "200")
        try:  # the same HUD every game: pin the settings the pixel constants are calibrated for (game is closed here)
            from shared.src.lib.game.leagueoflegends.hud_settings import pin_hud
            changes = pin_hud()
            print(f"[bot] hud_settings: pinned ({'; '.join(changes) if changes else 'already as calibrated'})", flush=True)
        except Exception as e:  # noqa: BLE001
            print(f"[bot] hud_settings: FAILED to pin: {e}", flush=True)
        cfg = PracticeConfig(champion_id=GAREN, game_timeout_s=240.0, player_team="200" if red else "100",
                             join_red_fn=join_red if red else None)
        started = PracticeRunner(cfg).run()
        result["start"] = {"ok": started.ok, "message": started.final_message}
        if not started.ok:
            raise RuntimeError(f"game did not start: {started.final_message}")

        # wait for the game clock to run (the loading screen answers the API earlier)
        data = None
        for _ in range(120):
            data = live_recorder.fetch_all_game_data()
            if data and (data.get("gameData") or {}).get("gameTime", 0) > 1:
                break
            time.sleep(1)
        if not data:
            raise RuntimeError("game clock never started")

        tl = live_recorder.new_timeline(data)
        tl.setdefault("zones", [])
        tl["meta"]["champion"] = tl["meta"].get("champion") or "Garen"
        tl["meta"]["assigned_position"] = "top"  # the bot always plays top; the API says "none" in Practice Tool
        state = {"last_poll": -99.0, "last_zone": -99.0, "last_shot": -99.0}

        from shared.src.lib.game.leagueoflegends.minion_events import MinionWatcher
        watcher = MinionWatcher()

        import collections
        ring = collections.deque(maxlen=6)  # (game time, frame) of the latest ticks
        follow = []  # [attempt dir, until game time]
        ticks = {"n": 0, "t0": time.monotonic(), "seen": 0}

        def save_frame(dir_, gt_, frame):
            from PIL import Image
            dir_.mkdir(parents=True, exist_ok=True)
            Image.fromarray(frame).save(dir_ / f"t{gt_:08.2f}.jpg", quality=90)  # full resolution, for the hand-check of last-hits

        def on_tick(d, img):
            gt = float((d.get("gameData") or {}).get("gameTime", 0.0))
            ticks["n"] += 1
            if ticks["n"] == 1:
                ticks["t0"] = time.monotonic()
            if img is not None:
                ring.append((gt, img))
                for fol in list(follow):
                    if gt <= fol[1]:
                        save_frame(fol[0], gt, img)
                    else:
                        follow.remove(fol)
                while ticks["seen"] < len(bot.mem.lasthits):  # a new last-hit attempt: frames from just before it, then 3.5 s after
                    a = bot.mem.lasthits[ticks["seen"]]
                    adir = OUT / "lasthit" / f"a{ticks['seen']:02d}"
                    for g_, f_ in ring:
                        if gt - g_ <= 1.6:
                            save_frame(adir, g_, f_)
                    follow.append((adir, gt + 3.5))
                    ticks["seen"] += 1
            try:  # TASK-131 minion deaths: which minions died near Garen and did he get the last hit
                me_ = next((p for p in d.get("allPlayers") or [] if (p.get("riotId") or p.get("summonerName"))
                            in {(d.get("activePlayer") or {}).get("riotId"), (d.get("activePlayer") or {}).get("summonerName")}), {})
                watcher.update(gt, bot.last_enemies, bot.last_cs if bot.last_cs is not None else int((me_.get("scores") or {}).get("creepScore", 0)))
            except Exception:  # noqa: BLE001
                pass
            if gt - state["last_poll"] >= 2.0:
                state["last_poll"] = gt
                live_recorder.add_poll(tl, d)
            if img is not None and gt - state["last_zone"] >= 5.0:
                state["last_zone"] = gt
                p = view_box_position(img)
                if p is not None:
                    tl["zones"].append({"t": gt, "zone": zone_of(*p), "x": round(p[0], 3), "y": round(p[1], 3)})
            if img is not None and gt - state["last_shot"] >= 20.0:
                state["last_shot"] = gt
                from PIL import Image
                Image.fromarray(img).resize((960, 600)).save(OUT / "shots" / f"t{int(gt):05d}.png")

        # video: ffmpeg gdigrab, no console window; video time of game 0:00 = (now - video start) - game time
        video_offset = 0.0
        try:
            import subprocess
            vp = OUT / "video.mp4"
            video = subprocess.Popen(
                [r"C:\ffmpeg\bin\ffmpeg.exe", "-y", "-f", "gdigrab", "-framerate", "10", "-i", "desktop",
                 "-vf", "scale=1280:-2", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "32", "-pix_fmt", "yuv420p", str(vp)],
                stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            d0 = live_recorder.fetch_all_game_data()
            g0 = float(((d0 or {}).get("gameData") or {}).get("gameTime", 0.0))
            video_offset = 1.5 - g0  # video time of game 0:00 (negative: the game started before the video; ffmpeg needs ~1.5 s)
        except Exception as e:  # noqa: BLE001
            result["video_error"] = str(e)

        gi = GameInput()
        free_cam = "free" in [a.lower() for a in sys.argv[3:]]
        if "marker" in [a.lower() for a in sys.argv[3:]]:  # training reference: the Practice Tool's last-hit marker decides (never the default)
            from shared.src.lib.game.leagueoflegends import garen_bot as _gb
            _gb.LASTHIT_SOURCE = "marker"
        result["lasthit_source"] = __import__("shared.src.lib.game.leagueoflegends.garen_bot", fromlist=["x"]).LASTHIT_SOURCE
        bot = GarenBot(gi, live_recorder.fetch_all_game_data, grab, on_tick=on_tick, camera_mode="free" if free_cam else "locked")
        result["camera_mode"] = bot.camera_mode
        from shared.src.lib.game.leagueoflegends.turn_log import TurnLog, read_turns
        tlog = TurnLog(str(OUT), live_path=r"C:\virtualpytest\lol-overlay-live.json")  # read-only: turns.jsonl, zones.jsonl, live overlay file
        gi.on_input = tlog.add_input
        bot.turn_log = tlog
        bot.shot_dir = OUT / "shop"
        if "calib" in [a.lower() for a in sys.argv[3:]]:
            bot.calib_dir = OUT / "target_calib"  # left-click minions and save the target frame: material for the exact-health reader
        if not bot.start_sequence():  # wait for the game, buy the start items, lock the camera; then the loop walks to lane
            from PIL import Image
            Image.fromarray(grab()).save(OUT / "start_failed.png")
            raise RuntimeError("start items could not be bought: run stopped (see start_failed.png and run.log)")
        stats = bot.run(MAX_S)
        if video is not None:
            from shared.src.lib.game.leagueoflegends.recorder_proc import stop_recorder

            result["recorder"] = stop_recorder(video, 5.0, lambda m: print(m, flush=True))
            result["video"] = "video.mp4"
        result["bot"] = stats
        result["actions_by_kind"] = {}
        for _, a in bot.log:
            result["actions_by_kind"][a[0]] = result["actions_by_kind"].get(a[0], 0) + 1
        live_recorder.save_timeline(tl, str(OUT / "timeline.json"))
        tl["fights"] = bot.mem.fights
        result["tick_hz"] = round(ticks["n"] / max(time.monotonic() - ticks["t0"], 1.0), 2)
        (OUT / "lasthit").mkdir(exist_ok=True)
        (OUT / "lasthit" / "attempts.json").write_text(json.dumps(
            {"attempts": [{k: v for k, v in h.items() if k != "t_wall"} for h in bot.mem.lasthits],
             "pokes": [{k: v for k, v in h.items() if k != "t_wall"} for h in bot.mem.pokes],
             "calibration": bot.mem.cal_log, "hp_scale": bot.mem.hp_scale}, indent=1))
        tl["minion_deaths"] = watcher.finish(float(tl["samples"][-1]["t"]) if tl.get("samples") else 0.0)
        tl["bot_events"] = bot.mem.events
        minutes = max((tl["samples"][-1]["t"] if tl.get("samples") else 60.0) / 60.0, 1.0)
        result["clicks"] = {**bot.mem.clicks, "per_min": {k: round(v / minutes, 1) for k, v in bot.mem.clicks.items()},
                            "total_sent": bot.mem.clicks["attack"] + bot.mem.clicks["move_screen"] + bot.mem.clicks["move_minimap"]}
        tl["clicks"] = result["clicks"]
        sm = tl.get("samples") or []
        taken = sum(max(0.0, a["hp"] - b["hp"]) for a, b in zip(sm, sm[1:]) if not b.get("dead"))
        result["damage_taken_per_min"] = round(taken / minutes, 1)
        checks = [h for h in bot.mem.lasthits if h.get("measured_dmg") is not None]
        result["exact_layer"] = bot.mem.sel_stats
        result["dmg_check"] = {"checked": len(checks), "differ_over_2": sum(1 for h in checks if abs(h["measured_dmg"] - h["dmg"]) > 2.0)}
        done = [h for h in bot.mem.lasthits if h["result"] is not None]
        hits = sum(1 for h in done if h["result"] == "hit")
        tl["lasthits"] = [{k: h[k] for k in ("t", "type", "result", "est_hp", "dmg")} for h in done]
        result["pokes"] = {"n": len(bot.mem.pokes), "killed": sum(1 for h in bot.mem.pokes if h["result"] == "hit")}
        result["miss_causes"] = {c: sum(1 for h in done if h["result"] == "miss" and h.get("cause") == c) for c in sorted({h.get("cause") for h in done if h["result"] == "miss" and h.get("cause")})}
        result["lasthit"] = {"attempts": len(done), "hits": hits, "misses": len(done) - hits,
                             "rate": round(hits / len(done), 2) if done else None, "hp_scale": round(bot.mem.hp_scale, 2),
                             "cannon_hits": sum(1 for h in done if h["type"] == "cannon" and h["result"] == "hit"),
                             "cannon_misses": sum(1 for h in done if h["type"] == "cannon" and h["result"] == "miss")}
        tl["stuck_s"] = round(bot.mem.stuck_s, 1)
        live_recorder.save_timeline(tl, str(OUT / "timeline.json"))
        card = sc.scorecard(tl)
        ref = sc.reference_for(tl)
        moments = sc.bad_moments(tl, ref) + [
            {"t": f["t"], "kind": f"fight ({f['action']})",
             "detail": f"enemy {int(f['enemy_frac'] * 100)} % health, Garen {int(f['my_frac'] * 100)} %"}
            for f in bot.mem.fights
        ]
        moments += [{"t": e["t"], "kind": e["kind"], "detail": e["detail"]}
                    for e in bot.mem.events if e["kind"] in ("stuck", "recall_interrupted", "shop_refused", "shop_not_open")
                    or (e["kind"] == "lasthit" and "miss" in e["detail"])
                    or "FAILED" in e["detail"]]
        moments.sort(key=lambda m_: m_["t"])
        sc.write_report(card, ref, str(OUT / "scorecard.json"), str(OUT / "scorecard.html"), moments=moments,
                        video_url="video.mp4" if video is not None else None, video_offset_s=video_offset,
                        turns=read_turns(str(OUT / "turns.jsonl")))
        result["turn_log"] = {"turns": tlog.turn, "errors": tlog.errors}
        result["stuck_s"] = tl["stuck_s"]
        result["bot_events"] = bot.mem.events
        try:  # TASK-131: scorecard page with the earlier runs side by side (lol-scorecard.html)
            from shared.src.lib.game.leagueoflegends.score_run import score_run_dir
            score_run_dir(str(OUT))
        except Exception as e:  # noqa: BLE001
            result["score_run_error"] = str(e)
        result["overall"] = card["overall"]
        result["areas"] = {a: r["score"] for a, r in card["areas"].items()}
        result["cs"] = (tl["samples"][-1].get("cs") if tl.get("samples") else None)
        result["ok"] = True
    except Exception:
        result["exception"] = traceback.format_exc()
    finally:
        try:  # a crashed or timed-out run must not leave the desktop recorder running
            from shared.src.lib.game.leagueoflegends.recorder_proc import stop_recorder

            r_ = stop_recorder(video, 5.0, lambda m: print(m, flush=True))
            if r_ != "not running":
                result.setdefault("recorder", r_)
        except Exception as e:  # noqa: BLE001
            result["recorder_error"] = str(e)
        try:
            import exit_game  # C:\virtualpytest\exit_game.py: Esc -> Exit Game -> Leave (Practice Tool only)
            exit_game.main()
            result["exit"] = json.loads((Path(r"C:\virtualpytest") / "exit-result.json").read_text())
        except Exception as e:  # noqa: BLE001
            result["exit"] = f"failed: {e}"
        (OUT / "result.json").write_text(json.dumps(result, indent=1))
        Path(r"C:\virtualpytest\garen-last.txt").write_text(str(OUT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
