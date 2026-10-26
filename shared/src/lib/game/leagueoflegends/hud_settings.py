"""TASK-132: pin the League HUD settings the bot's pixel constants are calibrated for (Windows box, game closed).

The bot clicks on the minimap and reads the HUD at fixed pixels (1920x1200, MinimapScale 1.23). Someone changed MinimapScale to
0.45 once and every constant was off, so every launch writes these values into ``game.cfg`` and ``PersistedSettings.json``
(after a one-time ``.bak-orig`` backup of each) and logs what it changed. The game rewrites both files on exit, so this runs
before the game starts, never while it runs.
"""

from __future__ import annotations

import json
import os
import re
import shutil
from typing import Dict, List

CFG_DIR = r"C:\Riot Games\League of Legends\Config"
PINNED = {"MinimapScale": "1.2300", "CameraLockMode": "1", "Width": "1920", "Height": "1200"}  # known good (2026-10-18)


def _same(a: str, b: str) -> bool:
    try:
        return abs(float(a) - float(b)) < 1e-6
    except ValueError:
        return a == b


def _backup_once(path: str) -> None:
    dst = path + ".bak-orig"
    if os.path.exists(path) and not os.path.exists(dst):
        shutil.copy2(path, dst)


def pin_game_cfg(path: str, wanted: Dict[str, str] = PINNED) -> List[str]:
    text = open(path, encoding="utf-8").read()
    changes: List[str] = []
    for key, value in wanted.items():
        m = re.search(rf"(?m)^{key}=([0-9.]+)", text)
        if m and not _same(m.group(1), value):
            text = text[:m.start(1)] + value + text[m.end(1):]
            changes.append(f"game.cfg {key} {m.group(1)} -> {value}")
    if changes:
        _backup_once(path)
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(text)
    return changes


def pin_persisted(path: str, wanted: Dict[str, str] = PINNED) -> List[str]:
    data = json.loads(open(path, encoding="utf-8-sig").read())
    changes: List[str] = []
    for f in data.get("files", []):
        for sec in f.get("sections", []):
            for st in sec.get("settings", []):
                value = wanted.get(st.get("name"))
                if value is not None and not _same(str(st.get("value")), value):
                    changes.append(f"PersistedSettings {st['name']} {st.get('value')} -> {value}")
                    st["value"] = value
    if changes:
        _backup_once(path)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(data, indent=4))
    return changes


def pin_hud(cfg_dir: str = CFG_DIR, game_running: bool = False) -> List[str]:
    """Write the pinned settings into both files. Returns the changes (empty = already pinned). Refuses while a game runs."""
    if game_running:
        raise RuntimeError("a League game is running: the settings would be rewritten on exit; not pinning")
    return pin_game_cfg(os.path.join(cfg_dir, "game.cfg")) + pin_persisted(os.path.join(cfg_dir, "PersistedSettings.json"))
