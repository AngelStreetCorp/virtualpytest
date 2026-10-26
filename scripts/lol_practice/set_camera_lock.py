"""Make every League game start with the camera locked and the minimap at the size the bot is calibrated for (2026-10-18).

Sets HUD CameraLockMode=1 and MinimapScale=1.23 (the bot's pixel constants assume it; someone had set 0.45) in both ``game.cfg`` and ``PersistedSettings.json`` under ``C:\\Riot Games\\League of Legends\\Config``,
after a timestamped backup next to each file. Refuses while ``League of Legends.exe`` runs (the game rewrites both files on exit).
Run on the box: ``python set_camera_lock.py`` (``--undo`` restores the newest backup). Idempotent.
"""
import glob
import json
import re
import shutil
import subprocess
import sys
import time

CFG_DIR = r"C:\Riot Games\League of Legends\Config"
GAME_CFG = CFG_DIR + r"\game.cfg"
PERSISTED = CFG_DIR + r"\PersistedSettings.json"
WANTED = {"CameraLockMode": "1", "MinimapScale": "1.2300"}


def game_running() -> bool:
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq League of Legends.exe", "/NH"], capture_output=True, text=True,
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
    return "League of Legends.exe" in out


def backup(path: str) -> str:
    dst = f"{path}.bak-{time.strftime('%Y%m%d-%H%M%S')}"
    shutil.copy2(path, dst)
    return dst


def set_game_cfg() -> bool:
    text = open(GAME_CFG, encoding="utf-8").read()
    new = text
    for key, value in WANTED.items():
        new = re.sub(rf"(?m)^({key}=)[0-9.]+", rf"\g<1>{value}", new)
    if new == text:
        return False
    backup(GAME_CFG)
    open(GAME_CFG, "w", encoding="utf-8", newline="").write(new)
    return True


def set_persisted() -> bool:
    raw = open(PERSISTED, encoding="utf-8-sig").read()
    data = json.loads(raw)
    changed = False
    for f in data.get("files", []):
        for sec in f.get("sections", []):
            for st in sec.get("settings", []):
                want = WANTED.get(st.get("name"))
                if want is not None and float(st.get("value") or 0) != float(want):
                    st["value"] = want
                    changed = True
    if changed:
        backup(PERSISTED)
        open(PERSISTED, "w", encoding="utf-8").write(json.dumps(data, indent=4))
    return changed


def undo() -> None:
    for path in (GAME_CFG, PERSISTED):
        baks = sorted(glob.glob(path + ".bak-*"))
        if baks:
            shutil.copy2(baks[0], path)  # the oldest backup is the original
            print("restored", path, "from", baks[0])


if __name__ == "__main__":
    if game_running():
        sys.exit("League of Legends.exe is running: refusing (the game rewrites these files on exit)")
    if "--undo" in sys.argv:
        undo()
    else:
        print("game.cfg changed:", set_game_cfg(), "| PersistedSettings.json changed:", set_persisted())
