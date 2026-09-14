#!/usr/bin/env python3
"""FULL OFFLINE REBUILD of the stb3 UI from scratch.

A corpus-backed device simulator (frames from the recorded stb3_max_build run) stands in
for the STB + MCP server. The REAL auto_build_mcp_live.py drives init -> explore -> validate
against it, exercising every change end-to-end: DOM-guided button focus (home_watch), the
dynamic-card probe filter, and reverse-BACK edge recording. No device, no network, no paid
vision calls (family DOM cache hits).

Device model (from measured stb3 behavior):
  - nav ring of 9 siblings, RIGHT/LEFT wrap; includes PROFILE (missed by the original build)
  - DOWN from any nav sibling -> the hero Watch chip state ('watch'), rotating hero frames
  - watch: UP/BACK -> home, DOWN -> content rail (capture_0030), OK -> no-op (plays content)
  - OK on a sibling dives to its screen; BACK returns; OK on profile -> no-op (no frame in corpus)
"""
import base64
import importlib.util
import json
import shutil
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
OLD = SCRIPTS / "live_runs/stb3_max_build"      # recorded corpus (rsync from the run machine)
NEW = SCRIPTS / "live_runs/stb3_sim_rebuild"

spec = importlib.util.spec_from_file_location("ab", SCRIPTS / "auto_build_mcp_live.py")
ab = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ab)

old = json.load(open(OLD / "state.json"))
FRAME = {n["label"]: n["screenshot"] for n in old["nodes"].values()
         if n.get("label") and n.get("screenshot")}

RING = ["home_search", "home", "home_tvguide", "home_apps", "home_replay",
        "home_moviesseries", "home_recordings", "home_settings", "home_profile"]
DIVES = {"home_tvguide": "tvguide", "home_apps": "apps", "home_replay": "replay",
         "home_moviesseries": "moviesseries", "home_recordings": "recordings",
         "home_settings": "settings", "home_search": "search"}
PARENT = {v: k for k, v in DIVES.items()}
WATCH_FRAMES = [OLD / "captures" / f for f in
                ["capture_0056.png", "capture_0072.png", "capture_0089.png",
                 "capture_0108.png", "capture_0130.png", "validate_0896.png",
                 "validate_0917.png"]]
RAIL_FRAME = OLD / "captures" / "capture_0030.png"

HOST, DEV, NAME = "sim_host", "device1", "SimSTB"


class SimClient:
    """Drop-in MCPClient: a deterministic stb3 built from the recorded corpus.

    Device state is CLASS-level: the real MCP client is stateless (the device holds the
    screen), and the builder constructs a new client per subcommand/round. Instance-level
    state silently reset the 'device' to home every explore round, desyncing the DFS
    (bogus OK->home edges — first sim run, 2026-07-16)."""

    state = "home"
    watch_i = 0
    presses = []
    last_ring = "home"      # the nav row KEEPS LAST FOCUS: UP/BACK from watch returns HERE
    goto_count = 0          # mirrors MCPClient.goto_count so validation's reposition roll-up works

    def __init__(self, url, authorization, verify_tls=False):
        pass

    def _frame(self) -> bytes:
        if SimClient.state == "watch":
            f = WATCH_FRAMES[SimClient.watch_i % len(WATCH_FRAMES)]
            SimClient.watch_i += 1          # rotating hero: every look at 'watch' differs
            return f.read_bytes()
        if SimClient.state == "rail":
            return RAIL_FRAME.read_bytes()
        return Path(FRAME[SimClient.state]).read_bytes()

    def _press(self, key: str) -> None:
        cls = SimClient
        s = cls.state
        cls.presses = cls.presses + [key]
        if s == "watch":
            cls.state = {"UP": cls.last_ring, "BACK": cls.last_ring, "DOWN": "rail"}.get(key, s)
        elif s == "rail":
            cls.state = {"UP": "watch", "BACK": cls.last_ring, "HOME": "home"}.get(key, s)
        elif s in RING:
            i = RING.index(s)
            if key == "RIGHT":
                cls.state = RING[(i + 1) % len(RING)]
            elif key == "LEFT":
                cls.state = RING[(i - 1) % len(RING)]
            elif key == "DOWN":
                cls.last_ring = s        # measured live 2026-07-17: UP returns to the LAST tab
                cls.state = "watch"
            elif key == "OK" and s in DIVES:
                cls.state = DIVES[s]
            elif key == "HOME":
                cls.state = "home"
        else:                                   # inside a dive leaf
            if key == "BACK":
                cls.state = PARENT.get(s, "home")
            elif key == "HOME":
                cls.state = "home"

    def _img(self):
        return {"content": [{"type": "image",
                             "data": base64.b64encode(self._frame()).decode()}]}

    def call(self, tool, params, timeout=240):
        if tool == "get_device_info":
            return {"content": [{"type": "text", "text": json.dumps({"devices": [
                {"host_name": HOST, "device_id": DEV, "device_name": NAME,
                 "status": "online"}]})}]}
        if tool == "list_actions":
            return {"device_action_types": {"remote": [
                {"command": "press_key", "params": {"key": k}}
                for k in ["HOME", "BACK", "UP", "DOWN", "LEFT", "RIGHT", "OK"]]}}
        if tool == "execute_device_action":
            for a in params.get("actions") or []:
                self._press(str((a.get("params") or {}).get("key", "")).upper())
            return self._img()
        if tool == "capture_screenshot":
            return self._img()
        raise ab.LiveBuildError(f"sim: unexpected tool {tool}")

    def image_bytes(self, body):
        return base64.b64decode(body["content"][0]["data"])

    def goto_home(self, host, device, ui_name, timeout=240, include_screenshot=False):
        SimClient.goto_count += 1
        SimClient.state = "home"
        return {}


def run(argv) -> int:
    sys.argv = ["auto_build_mcp_live.py"] + argv
    return ab.main()


def main():
    ab.MCPClient = SimClient
    ab.time.sleep = lambda s: None          # offline: no settle waits
    import os
    os.environ["VPT_MCP_AUTHORIZATION"] = "Bearer sim"

    if NEW.exists():
        shutil.rmtree(NEW)

    rc = run(["init", "--run-dir", str(NEW), "--mcp-url", "http://sim",
              "--host", HOST, "--device", DEV, "--device-name", NAME,
              "--ui-name", "stb3_sim", "--max-depth", "1", "--settle-ms", "0"])
    print(f"\n[init rc={rc}]")
    if rc:
        return rc

    for rnd in range(1, 60):
        before = len(json.load(open(NEW / "state.json"))["probes"])
        rc = run(["explore", "--run-dir", str(NEW), "--max-actions", "100"])
        after_state = json.load(open(NEW / "state.json"))
        after = len(after_state["probes"])
        print(f"\n[explore round {rnd} rc={rc}] probes {before} -> {after}, "
              f"nodes={len(after_state['nodes'])}, edges={len(after_state['edges'])}")
        if rc == 0:
            break                              # status=complete
        if rc != ab.EXIT_MORE_WORK:
            return rc                          # a real error

    rc = run(["validate", "--run-dir", str(NEW)])
    print(f"\n[validate rc={rc}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
