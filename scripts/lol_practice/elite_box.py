r"""Elite Garen replay scraper, box side (vpt-windows). Owner-approved: other players' replays (until patch 26.21), camera
inputs in the REPLAY viewer only (double-click Garen's portrait, fog dropdown). Laning window 1:30-8:00 (owner scope).

Session 0 (ssh), C:\Python\Python312\python.exe:
  elite_box.py find <Name#TAG> ...          -> JSON list of Garen-TOP ranked games on the client's patch (stdout)
  elite_box.py timelines <gameId> ...       -> C:\virtualpytest\lol-elite\timelines\<gid>.json (1 request/s)
  elite_box.py cfg-on | cfg-restore         -> EnableReplayApi=1 with a backup / restore the backup
Session 1 (create_elite_task.ps1, venv pythonw, needs PIL):
  elite_box.py capture <t_end> <speed> <gid:team> ...   -> C:\virtualpytest\lol-elite\replays\<gid>\ ; capture.log ; capture.done
  elite_box.py video <t_start> <t_end> <gid:team[:t0:t1]> ...  -> C:\virtualpytest\lol-elite\video\<gid>\{video,log,meta}_<t0>-<t1>.* ; video.done
                                                        owner window 60-480 (1:00-8:00); catch-up spec gid:team:55:95
Session 0 also: elite_box.py download <gameId> ...     -> fetch .rofl files
Read docs/agent/game/lol/REPLAYS.md and the lol-elite-scrape skill before changing anything here.
"""
import base64, ctypes, json, os, shutil, ssl, subprocess, sys, time, urllib.parse, urllib.request
from ctypes import wintypes
ROOT = r"C:\virtualpytest\lol-elite"
CFG = r"C:\Riot Games\League of Legends\Config\game.cfg"
BAK = os.path.join(ROOT, "game.cfg.bak")
T0 = 60.0  # owner (2026-10-19): capture from 1:00, 1:30 missed the first wave
GAREN = 86
SMITE = 11
os.makedirs(ROOT, exist_ok=True)
LOG = None
def log(*a):
    global LOG
    LOG = LOG or open(os.path.join(ROOT, "capture.log"), "a", encoding="utf-8")
    LOG.write(time.strftime("%H:%M:%S ") + " ".join(map(str, a)) + "\n"); LOG.flush()
ctx = ssl._create_unverified_context()
def http(method, url, body=None, auth=None, timeout=10):
    h = {"Content-Type": "application/json"}
    if auth: h["Authorization"] = auth
    req = urllib.request.Request(url, method=method, headers=h, data=None if body is None else json.dumps(body).encode())
    with urllib.request.urlopen(req, context=ctx, timeout=timeout) as r:
        t = r.read(); return json.loads(t) if t else {}
def lcu(method, path, body=None):
    lf = open(r"C:\Riot Games\League of Legends\lockfile").read().split(":")
    return http(method, f"https://127.0.0.1:{lf[2]}{path}", body, "Basic " + base64.b64encode(f"riot:{lf[3]}".encode()).decode(), 30)
def game(method, path, body=None):
    return http(method, "https://127.0.0.1:2999" + path, body)
u32 = ctypes.WinDLL("user32", use_last_error=True)
class MI(ctypes.Structure): _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD), ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]
class KI(ctypes.Structure): _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]
class U(ctypes.Union): _fields_ = [("ki", KI), ("mi", MI)]
class INP(ctypes.Structure): _fields_ = [("type", wintypes.DWORD), ("u", U)]
def send(i): u32.SendInput(1, (INP * 1)(i), ctypes.sizeof(INP))
def click(x, y):
    u32.SetCursorPos(int(x), int(y)); time.sleep(0.05)
    send(INP(0, U(mi=MI(0, 0, 0, 0x2, 0, 0)))); time.sleep(0.05); send(INP(0, U(mi=MI(0, 0, 0, 0x4, 0, 0))))
def focus():
    h = u32.FindWindowW(None, "League of Legends (TM) Client")
    if h: u32.ShowWindow(h, 9); u32.SetForegroundWindow(h)
    return bool(h)
def locked(img, team):
    """Camera dropdown (x 25-265, y 1090-1115) shows the followed player's name in team colour; 'Manual Camera' is white."""
    a = img.crop((25, 1090, 265, 1115)).convert("RGB"); n = 0
    for r, g, b in a.getdata():
        if (team == "200" and r > 150 and g < 90 and b < 90) or (team == "100" and b > 150 and r < 110): n += 1
    return n > 80
def lock(px, team, tries=6):
    for i in range(tries):
        focus(); time.sleep(0.2); click(px, 195); time.sleep(0.12); click(px, 195); time.sleep(0.8)
        u32.SetCursorPos(1915, 640); time.sleep(0.3)
        from PIL import ImageGrab
        if locked(ImageGrab.grab(all_screens=True), team): return i + 1
    return 0
def kill_replay():
    subprocess.run(["taskkill", "/IM", "League of Legends.exe", "/F"], capture_output=True, creationflags=0x08000000)


def find(rids):
    """Garen TOP (no Smite, < 30 jungle camps, >= 100 lane minions), ranked solo, client patch, >= 15 min; tier from ranked stats."""
    patch = lcu("GET", "/lol-replays/v1/configuration")["gameVersion"].rsplit(".", 2)[0]
    out = []
    for rid in rids:
        name, tag = rid.rsplit("#", 1)
        try:
            puuid = lcu("GET", f"/lol-summoner/v1/alias/lookup?gameName={urllib.parse.quote(name)}&tagLine={urllib.parse.quote(tag)}")["puuid"]
            tier = (lcu("GET", f"/lol-ranked/v1/ranked-stats/{puuid}").get("queueMap", {}).get("RANKED_SOLO_5x5", {}) or {}).get("tier", "")
            games = lcu("GET", f"/lol-match-history/v1/products/lol/{puuid}/matches?begIndex=0&endIndex=25")["games"]["games"]
        except Exception as e:
            print(json.dumps({"player": rid, "error": repr(e)}), file=sys.stderr); continue
        time.sleep(1)
        for g in games:
            p = g["participants"][0]
            if p["championId"] != GAREN or not g["gameVersion"].startswith(patch) or g["queueId"] != 420 or g["gameDuration"] < 900:
                continue
            d = lcu("GET", f"/lol-match-history/v1/games/{g['gameId']}"); time.sleep(1)
            me = next(x for x in d["participants"] if x["championId"] == GAREN); s = me["stats"]
            if SMITE in (me["spell1Id"], me["spell2Id"]) or s.get("neutralMinionsKilled", 0) > 30 or s.get("totalMinionsKilled", 0) < 100:
                continue
            ident = {i["participantId"]: i["player"] for i in d["participantIdentities"]}
            foes = sorted((x for x in d["participants"] if x["teamId"] != me["teamId"] and SMITE not in (x["spell1Id"], x["spell2Id"])),
                          key=lambda x: -x["stats"].get("totalMinionsKilled", 0))
            out.append({"gameId": g["gameId"], "player": rid, "tier": tier, "patch": g["gameVersion"], "team": str(me["teamId"]),
                        "player_name": ident.get(me["participantId"], {}).get("gameName"), "date": g["gameCreationDate"][:16],
                        "duration": g["gameDuration"], "win": s.get("win"), "foes_by_cs": [x["championId"] for x in foes[:3]]})
    print(json.dumps(out))

def timelines(gids):
    os.makedirs(os.path.join(ROOT, "timelines"), exist_ok=True)
    for gid in gids:
        path = os.path.join(ROOT, "timelines", f"{gid}.json")
        if os.path.exists(path):
            continue
        t = lcu("GET", f"/lol-match-history/v1/game-timelines/{gid}"); time.sleep(1)
        d = lcu("GET", f"/lol-match-history/v1/games/{gid}"); time.sleep(1)
        json.dump({"timeline": t, "game": d}, open(path, "w")); print(gid, len(t.get("frames", [])), "frames")

def download(gids):
    """Fetch .rofl files (about 6 s each); prints one JSON line per game with the final metadata state."""
    for gid in map(int, gids):
        try:
            lcu("POST", f"/lol-replays/v2/metadata/{gid}/create", {"gameId": gid, "gameType": "MATCHED_GAME", "queueId": 420, "gameEnd": 0})
            st = lcu("GET", f"/lol-replays/v1/metadata/{gid}")
            if st.get("state") == "download":
                lcu("POST", f"/lol-replays/v1/rofls/{gid}/download/graceful", {"componentType": "replay-button_match-history"})
                for _ in range(60):
                    st = lcu("GET", f"/lol-replays/v1/metadata/{gid}")
                    if st.get("state") not in ("download", "checking", "downloading"): break
                    time.sleep(2)
        except Exception as e:
            st = {"error": repr(e)}
        print(json.dumps({"gameId": gid, **st}), flush=True)

FFMPEG = r"C:\ffmpeg\bin\ffmpeg.exe"
FPS = int(os.environ.get("ELITE_FPS", "15"))  # 30 = League's server tick (2026-10-20 owner go); 15 = the first three games
PRESET = os.environ.get("ELITE_PRESET", "veryfast")  # x264 preset; ultrafast if 30 fps drops frames

def video(t_start, t_end, specs):
    """Raw 1x video (gdigrab 15 fps, libx264 crf 16, 4:4:4) of 1:30-t_end per game, camera locked on Garen, chat hidden, scoreboard always on; log.jsonl at 4 Hz (replay time, cameraPosition, Garen's Live Client Data)."""
    from PIL import ImageGrab
    done_flag = os.path.join(ROOT, "video.done")
    if os.path.exists(done_flag): os.remove(done_flag)
    for spec in specs:
        parts = spec.split(":"); gid, team = int(parts[0]), parts[1]
        t0, t1 = (float(parts[2]), float(parts[3])) if len(parts) >= 4 else (t_start, t_end)  # per-game window (catch-ups)
        out = os.path.join(ROOT, "video", str(gid)); os.makedirs(out, exist_ok=True)
        tag = f"{int(t0)}-{int(t1)}"
        ff = None
        try:
            if lcu("GET", "/lol-gameflow/v1/gameflow-phase") not in ("None", "Lobby"):
                log("client busy, stop"); break
            if lcu("GET", f"/lol-replays/v1/metadata/{gid}").get("state") != "watch":
                log(gid, "no local replay, skip"); continue
            lcu("POST", f"/lol-replays/v1/rofls/{gid}/watch", {"componentType": "replay-button_match-history"})
            for _ in range(120):
                try:
                    if game("GET", "/replay/playback").get("length", 0) > 0: break
                except Exception: pass
                time.sleep(2)
            time.sleep(5)
            json.dump(game("GET", "/liveclientdata/playerlist"), open(os.path.join(out, "players_start.json"), "w"))
            game("POST", "/replay/render", {"interfaceChat": False})
            game("POST", "/replay/playback", {"time": t0 - 6.0, "paused": True, "speed": 1.0}); time.sleep(2)
            focus(); time.sleep(0.3)
            px = 45 if team == "100" else 1865
            click(245, 1137); time.sleep(0.6); click(204, 1058 if team == "100" else 1084); time.sleep(0.5)  # fog of war = his team
            log(gid, "lock tries", lock(px, team))
            ff = subprocess.Popen([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-f", "gdigrab", "-framerate", str(FPS), "-draw_mouse", "0",
                                   "-i", "desktop", "-c:v", "libx264", "-preset", PRESET, "-crf", "16", "-pix_fmt", "yuv444p",
                                   os.path.join(out, f"video_{tag}.mkv")], stdin=subprocess.PIPE, creationflags=0x08000000)
            time.sleep(1.5)
            wall0 = time.time()
            game("POST", "/replay/playback", {"paused": False, "speed": 1.0}); time.sleep(0.5)
            click(245, 1137); time.sleep(0.5); click(204, 1058 if team == "100" else 1084); u32.SetCursorPos(1915, 640)  # fog = his team (a paused replay ignores it)
            game("POST", "/replay/render", {"interfaceScoreboard": True})  # owner: exact CS of all 10 players on EVERY frame
            json.dump({"gid": gid, "team": team, "t_start": t0, "t_end": t1, "video": f"video_{tag}.mkv", "log": f"log_{tag}.jsonl",
                       "fps": FPS, "codec": "libx264 crf16 yuv444p", "scoreboard": "always on", "video_starts_before_wall0_s": 2.0}, open(os.path.join(out, f"meta_{tag}.json"), "w"))
            logf = open(os.path.join(out, f"log_{tag}.jsonl"), "w"); relocks = 0; board_until = -1.0; next_board = t0 + 15.0; last_lock_check = 0.0
            while True:
                gt = game("GET", "/replay/playback").get("time", 0.0)
                if gt >= t1: break
                rec = {"wall": round(time.time() - wall0, 3), "t": round(gt, 3)}
                try:
                    rec["camera"] = game("GET", "/replay/render").get("cameraPosition")
                    g = next((p for p in game("GET", "/liveclientdata/playerlist") if p.get("championName") == "Garen"), {})
                    rec.update({"level": g.get("level"), "scores": g.get("scores"), "items": [i.get("itemID") for i in g.get("items", [])], "dead": g.get("isDead")})
                except Exception as e:
                    rec["err"] = repr(e)
                if time.time() - last_lock_check > 2.0:
                    last_lock_check = time.time(); rec["locked"] = locked(ImageGrab.grab(), team)
                    if not rec["locked"]:
                        relocks += 1; lock(px, team, 2)
                logf.write(json.dumps(rec) + "\n"); logf.flush()
                time.sleep(0.1)
            logf.close()
            try: json.dump(game("GET", "/liveclientdata/eventdata"), open(os.path.join(out, f"events_{tag}.json"), "w"))  # kills, first blood, ...
            except Exception as e: log(gid, "events", e)
            log(gid, tag, "video done, relocks", relocks)
        except Exception as e:
            log(gid, "ERROR", repr(e))
        finally:
            if ff is not None:  # stop the recorder in every case: 'q' then kill
                try: ff.communicate(b"q", timeout=20)
                except Exception: ff.kill()
            kill_replay(); time.sleep(8)
    log("video block done")
    open(done_flag, "w").write("1")

def cfg_on():
    if not os.path.exists(BAK):
        shutil.copy2(CFG, BAK)
    t = open(CFG, encoding="utf-8").read()
    if "EnableReplayApi=" not in t:
        t = t.replace("[General]\n", "[General]\nEnableReplayApi=1\n", 1).replace("[General]\r\n", "[General]\r\nEnableReplayApi=1\r\n", 1)
    open(CFG, "w", encoding="utf-8", newline="").write(t.replace("EnableReplayApi=0", "EnableReplayApi=1"))
    print("EnableReplayApi on, backup", os.path.exists(BAK))

def cfg_restore():
    if os.path.exists(BAK):
        shutil.copy2(BAK, CFG); os.remove(BAK)
    print("restored, EnableReplayApi present:", "EnableReplayApi" in open(CFG, encoding="utf-8").read())

def capture(t_end, speed, specs):
    from PIL import ImageGrab
    done_flag = os.path.join(ROOT, "capture.done")
    if os.path.exists(done_flag): os.remove(done_flag)
    for spec in specs:
        gid, team = spec.split(":")[:2]; gid = int(gid); out = os.path.join(ROOT, "replays", str(gid)); os.makedirs(out, exist_ok=True)
        try:
            if lcu("GET", "/lol-gameflow/v1/gameflow-phase") not in ("None", "Lobby"):
                log("client busy, stop"); break
            lcu("POST", f"/lol-replays/v2/metadata/{gid}/create", {"gameId": gid, "gameType": "MATCHED_GAME", "queueId": 420, "gameEnd": 0})
            st = lcu("GET", f"/lol-replays/v1/metadata/{gid}")
            if st.get("state") != "watch":
                lcu("POST", f"/lol-replays/v1/rofls/{gid}/download/graceful", {"componentType": "replay-button_match-history"})
                for _ in range(60):
                    st = lcu("GET", f"/lol-replays/v1/metadata/{gid}")
                    if st.get("state") in ("watch", "lost", "incompatible", "unsupported", "error"): break
                    time.sleep(2)
            log(gid, "metadata", st)
            if st.get("state") != "watch": continue
            lcu("POST", f"/lol-replays/v1/rofls/{gid}/watch", {"componentType": "replay-button_match-history"})
            for _ in range(120):
                try:
                    if game("GET", "/replay/playback").get("length", 0) > 0: break
                except Exception: pass
                time.sleep(2)
            time.sleep(5)
            players = game("GET", "/liveclientdata/playerlist")
            me = next((p for p in players if p.get("championName") == "Garen"), None)
            json.dump(players, open(os.path.join(out, "players_start.json"), "w"))
            game("POST", "/replay/playback", {"time": T0 - 12.0, "paused": False, "speed": speed}); time.sleep(3)
            focus(); time.sleep(0.3)
            px = 45 if team == "100" else 1865
            click(245, 1137); time.sleep(0.6); click(204, 1058 if team == "100" else 1084); time.sleep(0.5)  # fog of war = his team
            log(gid, "lock tries", lock(px, team))  # double-click portrait = camera follows Garen; verified on the dropdown text
            game("POST", "/replay/render", {"interfaceChat": False})  # red/blue chat names read as health bars
            relocks = 0
            rows, nxt = [], 0.0
            while True:
                pb = game("GET", "/replay/playback"); gt = pb.get("time", 0.0)
                if gt >= t_end: break
                if gt < T0: time.sleep(0.05); continue
                if gt + 1e-6 < nxt: time.sleep(0.03); continue
                nxt = (int(gt * 2) + 1) / 2.0
                img = ImageGrab.grab(all_screens=True); name = f"{gt:07.2f}.jpg"; img.convert("RGB").save(os.path.join(out, name), quality=88)
                row = {"t": round(gt, 2), "file": name, "locked": locked(img, team)}
                if not row["locked"]:
                    relocks += 1; lock(px, team, 2)
                try:
                    g = next((p for p in game("GET", "/liveclientdata/playerlist") if p.get("championName") == "Garen"), {})
                    row.update({"level": g.get("level"), "scores": g.get("scores"), "items": [i.get("itemID") for i in g.get("items", [])], "dead": g.get("isDead")})
                except Exception as e:
                    row["err"] = repr(e)
                rows.append(row)
            try: json.dump(game("GET", "/liveclientdata/eventdata"), open(os.path.join(out, "events.json"), "w"))
            except Exception as e: log(gid, "events", e)
            json.dump({"gid": gid, "team": team, "speed": speed, "relocks": relocks, "rows": rows, "garen": me}, open(os.path.join(out, "rows.json"), "w"))
            log(gid, "frames", len(rows))
        except Exception as e:
            log(gid, "ERROR", repr(e))
        finally:
            kill_replay(); time.sleep(8)
    log("capture done")
    open(done_flag, "w").write("1")

if __name__ == "__main__":
    cmd, args = sys.argv[1], sys.argv[2:]
    if cmd == "find": find(args)
    elif cmd == "timelines": timelines(args)
    elif cmd == "cfg-on": cfg_on()
    elif cmd == "cfg-restore": cfg_restore()
    elif cmd == "capture": capture(float(args[0]), float(args[1]), args[2:])
    elif cmd == "download": download(args)
    elif cmd == "video": video(float(args[0]), float(args[1]), args[2:])
    else: sys.exit(__doc__)
