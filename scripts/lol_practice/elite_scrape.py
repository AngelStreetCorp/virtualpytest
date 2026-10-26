#!/usr/bin/env python3
"""Elite Garen scraper, Mac side: drives scripts/lol_practice/elite_box.py on vpt-windows over ssh. Run from the repo root.
Skill: ~/.claude/skills/lol-elite-scrape/SKILL.md. Data: ~/vpt-deliverables/lol-elite/ (index.json = dedup of game ids).

  elite_scrape.py push                       copy elite_box.py + create_elite_task.ps1 to C:\\virtualpytest\\
  elite_scrape.py find [Name#TAG ...]        find Garen-TOP games (players: args or players.txt) -> index.json (state "new")
  elite_scrape.py capture N [--speed 2]      lease, cfg-on, capture the next N "new" games 1:00-8:00, copy back, cfg-restore, release
  elite_scrape.py timelines [N]              fetch timelines of indexed games not fetched yet (no lease: run between bot games)
  elite_scrape.py extract                    turns.json for captured games without one (perception.find_bars)
  elite_scrape.py status                     counts and disk use
Exit code 3 = lease busy (wait and retry), 4 = client busy (a game is running), 1 = error.
"""
import json, os, subprocess, sys, time
HOME = os.path.expanduser("~/vpt-deliverables/lol-elite")
INDEX = os.path.join(HOME, "index.json")
PLAYERS = os.path.join(HOME, "players.txt")
BOX = "vpt-windows"
PY0 = r"C:\Python\Python312\python.exe"
AGENT = "mac:lol-elite-scrape"
T_END = 480.0  # owner scope: laning window ends 8:00
HERE = os.path.dirname(os.path.abspath(__file__))
os.makedirs(HOME, exist_ok=True)

def sh(cmd, check=True, timeout=600):
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
    if check and r.returncode != 0:
        raise SystemExit(f"FAILED ({r.returncode}): {cmd}\n{r.stdout[-800:]}\n{r.stderr[-800:]}")
    return r.stdout

def box(args, timeout=600):
    return sh(f"ssh {BOX} '{PY0} C:\\virtualpytest\\elite_box.py {args}'", timeout=timeout)

def load():
    return json.load(open(INDEX)) if os.path.exists(INDEX) else {}

def save(ix):
    json.dump(ix, open(INDEX + ".tmp", "w"), indent=1); os.replace(INDEX + ".tmp", INDEX)

def client_idle():
    out = sh(f"ssh {BOX} 'tasklist /FI \"IMAGENAME eq League of Legends.exe\"'", check=False)
    return "League of Legends.exe" not in out

def lease(action, lid=None, ttl=60):
    if action == "check":
        out = sh("ssh proxmox '~/bin/vpt-lease list 2>/dev/null; echo LISTOK'")
        if "LISTOK" not in out: raise SystemExit("lease registry unreachable")
        return "vpt-windows/game" not in out
    if action == "claim":
        return sh(f"ssh proxmox '~/bin/vpt-lease claim vpt-windows game --agent {AGENT} --purpose \"elite Garen replay capture\" --ttl {ttl}'").split()[0]
    sh(f"ssh proxmox '~/bin/vpt-lease release {lid}'", check=False)

def cmd_push():
    sh(f"scp -q {HERE}/elite_box.py {HERE}/create_elite_task.ps1 {BOX}:C:/virtualpytest/"); print("pushed")

def cmd_find(players):
    players = players or [l.strip() for l in open(PLAYERS) if l.strip() and not l.startswith("#")]
    ix, new = load(), 0
    for i in range(0, len(players), 3):  # 3 players per call keeps one ssh call short
        args = " ".join(f'"{p}"' for p in players[i:i + 3])
        for g in json.loads(box(f"find {args}", timeout=900) or "[]"):
            k = str(g["gameId"])
            if k not in ix:
                g["state"] = "new"; ix[k] = g; new += 1
        save(ix)
    print(f"index: {len(ix)} games, {new} new")

def cmd_capture(n, speed):
    if not lease("check"): print("lease busy: wait and retry"); sys.exit(3)
    if not client_idle(): print("client busy (a game is running)"); sys.exit(4)
    ix = load()
    todo = [g for g in ix.values() if g["state"] == "new"][:n]
    if not todo: print("nothing new: run find first"); return
    lid = lease("claim", ttl=int(6 * len(todo)) + 10)
    try:
        cmd_push(); print(box("cfg-on"))
        specs = " ".join(f'{g["gameId"]}:{g["team"]}' for g in todo)
        sh(f"ssh {BOX} 'del /q C:\\virtualpytest\\lol-elite\\capture.done 2>nul & powershell -NoProfile -ExecutionPolicy Bypass -File C:\\virtualpytest\\create_elite_task.ps1 -A \"{T_END:.0f} {speed} {specs}\"'")
        deadline = time.time() + 420 * len(todo) + 300
        while time.time() < deadline:
            time.sleep(30)
            if "DONE" in sh(f"ssh {BOX} 'if exist C:\\virtualpytest\\lol-elite\\capture.done echo DONE'", check=False): break
        log = sh(f"ssh {BOX} 'type C:\\virtualpytest\\lol-elite\\capture.log'", check=False)
        for g in todo:
            k = str(g["gameId"]); d = os.path.join(HOME, "replays", k); os.makedirs(d, exist_ok=True)
            sh(f"scp -q -r '{BOX}:C:/virtualpytest/lol-elite/replays/{k}/*' {d}/", check=False)
            sh(f"scp -q '{BOX}:C:/Users/joach/OneDrive/Documents/League of Legends/Replays/EUW1-{k}.rofl' {d}/ 2>/dev/null", check=False)
            ok = os.path.exists(os.path.join(d, "rows.json"))
            g["state"] = "captured" if ok else "failed"; g["frames"] = len(json.load(open(os.path.join(d, "rows.json")))["rows"]) if ok else 0
            if ok:  # free the box disk once copied
                sh(f"ssh {BOX} 'rmdir /s /q C:\\virtualpytest\\lol-elite\\replays\\{k}'", check=False)
        save(ix)
        print(log[-1500:])
    finally:
        print(box("cfg-restore")); lease("release", lid)
    print({k: g["state"] for k, g in ix.items() if g in todo})

def cmd_timelines(n):
    if not client_idle(): print("client busy (a game is running): retry between games"); sys.exit(4)
    ix = load(); todo = [k for k, g in ix.items() if not g.get("timeline")][:n]
    for i in range(0, len(todo), 10):
        chunk = todo[i:i + 10]; box("timelines " + " ".join(chunk), timeout=900)
        d = os.path.join(HOME, "timelines"); os.makedirs(d, exist_ok=True)
        for k in chunk:
            if sh(f"scp -q '{BOX}:C:/virtualpytest/lol-elite/timelines/{k}.json' {d}/", check=False) is not None and os.path.exists(os.path.join(d, f"{k}.json")):
                ix[k]["timeline"] = True
        save(ix)
    print(f"timelines: {sum(1 for g in ix.values() if g.get('timeline'))}")

def cmd_extract():
    ix = load()
    for k, g in ix.items():
        d = os.path.join(HOME, "replays", k)
        if g["state"] == "captured" and not os.path.exists(os.path.join(d, "turns.json")):
            sh(f"python3 {HERE}/elite_extract_rows.py {d}", timeout=3600); print("extracted", k)

def cmd_status():
    ix = load(); from collections import Counter
    print(Counter(g["state"] for g in ix.values()), "timelines", sum(1 for g in ix.values() if g.get("timeline")))
    print(sh(f"du -sh {HOME}", check=False).strip())
    print(sh(f"ssh {BOX} 'dir C:\\ | find \"octets libres\"'", check=False).strip())

if __name__ == "__main__":
    a = sys.argv[1:]
    if not a: sys.exit(__doc__)
    c = a[0]
    if c == "push": cmd_push()
    elif c == "find": cmd_find(a[1:])
    elif c == "capture": cmd_capture(int(a[1]), float(a[a.index("--speed") + 1]) if "--speed" in a else 2.0)
    elif c == "timelines": cmd_timelines(int(a[1]) if len(a) > 1 else 1000)
    elif c == "extract": cmd_extract()
    elif c == "status": cmd_status()
    else: sys.exit(__doc__)
