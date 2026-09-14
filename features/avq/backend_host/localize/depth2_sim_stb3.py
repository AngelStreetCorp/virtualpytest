#!/usr/bin/env python3
"""FULL OFFLINE DEPTH-2 REBUILD of the stb3 settings subtree.

Sibling of offline_sim_stb3.py, which stops at depth 1. That sim hand-authors its device
model (a 9-node nav ring + one dive per tab); the settings subtree is far too big for that
— 44 nodes of tabs, panes, rows and modal dialogs. So this one is TABLE-DRIVEN: the device
model is the transition table that the live run already proved on hardware.

Ground truth: `live_runs/depth2_settings_0719_0151` (2026-07-19, 60 nodes / 136 edges).
Only edges whose validation verdict was `pass` / `pass_on_retry` become transitions — 106 of
134. The 7 `fail_wrong_screen` and 13 `source_unreachable` edges are the builder's MISTAKES,
so admitting them would bake the bugs into the oracle and make the sim agree with whatever
the builder does. An unrecorded (state, key) is a no-op (the frame does not change), which is
the honest reading of "we never saw this key do anything here".

Why frames ROTATE (`FRAMES[node]` is a list, not one file): the live run captured the same
screen many times, and those frames are NOT identical — JPEG noise and render timing move the
CV detector's output. That is not an artefact to average away, it is the defect under test:
`_dialog_plate` detected the 'guidance' modal on one capture and missed it on the next 2s
later, so `_find_node` merged a modal frame into an ordinary depth-1 pane row and the
explorer desynced (1 non-returnable dive, 2026-07-19). Serving one canonical frame per node
would hide that class of bug completely. Rotation reproduces it deterministically.

Run:  python depth2_sim_stb3.py            # explore --under settings --max-depth 2, then validate
"""
import base64
import collections
import importlib.util
import json
import shutil
import sys
import zlib
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
SRC = SCRIPTS / "live_runs/depth2_settings_0719_0151"   # graph + frames (hardware ground truth)
SEED = SCRIPTS / "live_runs/depth1_verify_0718_1949"    # certified depth-1 starting point
NEW = SCRIPTS / "live_runs/depth2_sim_rebuild"

spec = importlib.util.spec_from_file_location("ab", SCRIPTS / "auto_build_mcp_live.py")
ab = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ab)

_src = json.load(open(SRC / "state.json"))
_val = _src.get("validation") or {}

# --- device model: only hardware-VERIFIED edges ------------------------------------------
TRANS = {}
for _key, _rec in _val.items():
    if _rec.get("status") in ("pass", "pass_on_retry"):
        _s, _k, _d = _key.split("|")
        TRANS[(_s, _k)] = _d

# --- frames: every capture we ever took of each node, in recorded order -------------------
_frames = collections.defaultdict(list)


def _add(node_id, path):
    if path and path not in _frames[node_id] and Path(path).exists():
        _frames[node_id].append(path)


for _nid, _n in _src["nodes"].items():
    _add(_nid, _n.get("screenshot"))
for _e in _src["edges"]:
    _add(_e["target"], _e.get("observed_capture"))
for _key, _rec in _val.items():
    _add(_key.split("|")[2], _rec.get("screenshot"))

# Keep only frames that really ARE this node's screen. 28% of the collected frames (73 of 258)
# sit 20+ bits from their node's canonical dHash — up to 123 — because a capture gets attributed
# to whatever node the builder BELIEVED it was on, and every mis-step files a foreign frame here.
# Serving those made consecutive looks at one sim state return visibly different screens, which
# no real device does, and the builder rightly read it as "I am not where I thought": 7 spurious
# non-returnable dives, all of them simulator fiction (2026-07-19).
#
# 4 bits is chosen from the measured distribution, which is cleanly bimodal (165 frames at 0-1,
# then nothing above 11 until a cluster at 20+): it sits above the <=2 same-screen bound so
# genuine re-captures survive — including the `_dialog_plate` flap this sim exists to reproduce,
# whose two captures were ~0 bits apart — and below the 7-bit minimum separation between sibling
# rows of a pane, so a neighbouring row's frame can never be served for this node.
#
# LIMITATION: the home-ring nodes have a rotating hero, so their wide spread is GENUINE, not
# mis-attribution, and this filter flattens them to a static frame. That is acceptable here —
# this sim drives `--under settings`, and the ring is only crossed while repositioning — but it
# does make repositioning more deterministic than the real device. offline_sim_stb3.py is the
# harness that models the ring honestly (WATCH_FRAMES). Do not use this sim to reason about the
# home ring.
FRAME_DIST_MAX = 4
_cache_path = SCRIPTS / "live_runs" / ".depth2_sim_frame_dhash.json"
_focus_path = SCRIPTS / "live_runs" / ".depth2_sim_frame_focus.json"
_cache = json.loads(_cache_path.read_text()) if _cache_path.exists() else {}
_focus_cache = json.loads(_focus_path.read_text()) if _focus_path.exists() else {}
_before = sum(len(v) for v in _frames.values())
FRAMES, _dirty = {}, False
for _nid, _fs in _frames.items():
    _can = (_src["nodes"].get(_nid, {}).get("fingerprint") or {}).get("dhash")
    if not _can:
        FRAMES[_nid] = _fs
        continue
    _keep = []
    for _f in _fs:
        if _f not in _cache or _f not in _focus_cache:
            _fp = ab._fingerprint(_f)
            _cache[_f] = _fp.get("dhash", "")
            _focus_cache[_f] = _fp.get("focus") or {}
            _dirty = True
        if ab._hamming(_can, _cache[_f]) > FRAME_DIST_MAX:
            continue
        # dHash alone CANNOT separate home-ring siblings: their difference is a thin nav
        # underline that the 16x16 dHash barely sees, so a home_recordings frame measured
        # within 4 bits of home_settings' canonical and got served as home_settings, aborting
        # replay. Drop a frame whose DETECTED focus contradicts the node's own.
        # `focus=none` is deliberately KEPT: that is the CV losing the marker, which happens on
        # the real device (~20% of ring looks, ~95% of pane-row looks) and is a defect this sim
        # must keep reproducing — not mis-attribution to filter away.
        _ffocus = (_focus_cache.get(_f) or {})
        _cfocus = (_src["nodes"][_nid].get("fingerprint") or {}).get("focus") or {}
        if _ffocus.get("kind") and _cfocus.get("kind") and not ab._focus_agrees(_ffocus, _cfocus):
            continue
        _keep.append(_f)
    FRAMES[_nid] = _keep or [_fs[0]]        # never strand a node with no frame at all
if _dirty:
    _cache_path.write_text(json.dumps(_cache))
    _focus_path.write_text(json.dumps(_focus_cache))
_after = sum(len(v) for v in FRAMES.values())

# Structural BACK. Only 20 of the 60 nodes have a BACK edge that validation actually exercised,
# so a table built from verified edges alone leaves BACK a no-op in most states — the device
# could never leave, and the builder read that as 7 "non-returnable dives" that the real STB
# does not have. The device truth is structural and was hand-verified (2026-07-19): ONE BACK
# closes a dialog / leaves a pane and lands on whatever you came from. So fall back to the
# discovering parent: the source of the first forward (non-reverse) edge that reached the node.
# Only a real DIVE creates a return point. Keying this off "any forward edge" was wrong: a DOWN
# between two rows of a pane is a SIBLING move, so BACK appeared to step to the row above
# (node_0032 y=0.46 --BACK--> node_0030 y=0.38). The STB does not do that — BACK leaves the pane.
# So BACK exits the SUBTREE: find the edge that dove into this node's subtree_root and return to
# its source. Matches the hand-verified truth that a full-page dive returns to the menu in 1 BACK.
_DIVE_PARENT = {}
for _e in _src["edges"]:
    if _e["key"] == "BACK" or _e.get("reverse"):
        continue
    _tgt = _src["nodes"].get(_e["target"]) or {}
    _srcn = _src["nodes"].get(_e["source"]) or {}
    if _tgt.get("kind") == "screen" and int(_tgt.get("depth") or 0) > int(_srcn.get("depth") or 0):
        _DIVE_PARENT.setdefault(_e["target"], _e["source"])

PARENT = {}
for _nid, _n in _src["nodes"].items():
    _root = _n.get("subtree_root") or _nid
    _p = _DIVE_PARENT.get(_nid) or _DIVE_PARENT.get(_root)
    if _p and _p != _nid:
        PARENT[_nid] = _p

import os
TRACE = bool(os.environ.get("SIM_TRACE"))
ROOT = "node_0001"
# Identify as the SEEDED run's target: we continue that run's state.json, and _validate_target
# refuses to drive a device whose host/id/name differ from the one the run was started against.
_seed_target = json.load(open(SEED / "state.json")).get("target") or {}
HOST = _seed_target.get("host_name", "sim_host")
DEV = _seed_target.get("device_id", "device1")
NAME = _seed_target.get("device_name", "SimSTB")


class SimClient:
    """Drop-in MCPClient driven by TRANS/FRAMES.

    Device state is CLASS-level for the same reason as offline_sim_stb3.SimClient: the real
    MCP client is stateless (the device holds the screen) and the builder constructs a fresh
    client per subcommand/round, so instance state would silently teleport the device home
    every round."""

    state = ROOT
    frame_i = collections.Counter()
    presses = []
    goto_count = 0

    def __init__(self, url, authorization, verify_tls=False):
        pass

    def _frame(self) -> bytes:
        fs = FRAMES.get(SimClient.state)
        if not fs:
            raise ab.LiveBuildError(f"sim: no frame recorded for {SimClient.state}")
        i = SimClient.frame_i[SimClient.state]
        SimClient.frame_i[SimClient.state] = i + 1
        return Path(fs[i % len(fs)]).read_bytes()   # rotate: see module docstring

    def _press(self, key: str) -> None:
        cls = SimClient
        cls.presses = cls.presses + [key]
        was = cls.state
        nxt = TRANS.get((cls.state, key))
        if nxt:
            cls.state = nxt
        elif key == "BACK" and cls.state in PARENT:
            cls.state = PARENT[cls.state]     # structural BACK — see PARENT above
        elif key == "HOME":
            # stb3 truth: HOME toggles TV<->menu. From anywhere inside the menus it lands home,
            # which is what the recovery ladder relies on.
            cls.state = ROOT
        # otherwise: unrecorded key => no-op, the frame does not change.
        if TRACE:
            print(f"      [sim] {was} --{key}--> {cls.state}"
                  f"{'  (NO-OP)' if cls.state == was else ''}")

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
        SimClient.state = ROOT
        return {}


# --- focus-loss fault injection ----------------------------------------------------------
# The corpus CANNOT reproduce this on its own, and a sim without it is green for the wrong
# reason. A frame is only ever SAVED when the builder matched it to a node, so the saved set
# systematically over-represents successful detections: only 4 of the 102 `focus=none` frames
# survive as genuine same-screen captures (4% of what is served), while the live log — which
# counts every LOOK, matched or not — measures the CV losing the focus marker on ~20% of nav
# looks and ~95% of pane-row looks (35 'row' vs 664 'none', 2026-07-19 depth-2 run).
#
# So inject the loss at the measured rate instead of pretending the corpus shows it. This is
# the defect that makes `_same_screen` veto a screen the device is actually standing on, which
# is what aborts replay and drives the goto storm. Deterministic (seeded per state+look) so a
# failure is reproducible; set SIM_FOCUS_LOSS=0 to disable and isolate other behaviour.
FOCUS_LOSS = {"row": 0.95, "nav": 0.20}      # measured; box/none left alone (not measured)
_inject = os.environ.get("SIM_FOCUS_LOSS", "1") != "0"
_real_fingerprint = ab._fingerprint


def _lossy_fingerprint(path):
    fp = _real_fingerprint(path)
    if not _inject:
        return fp
    kind = ((fp.get("focus") or {}).get("kind")) or ""
    rate = FOCUS_LOSS.get(kind)
    if rate:
        # deterministic per (state, look-count): same run => same losses. crc32, NOT hash():
        # str hashing is salted per process (PYTHONHASHSEED), which would make every run differ.
        h = zlib.crc32(f"{SimClient.state}|{SimClient.frame_i[SimClient.state]}|{kind}".encode())
        if (h % 100) < int(rate * 100):
            fp = dict(fp)
            fp["focus"] = {"kind": "none"}
    return fp


ab._fingerprint = _lossy_fingerprint


def run(argv) -> int:
    sys.argv = ["auto_build_mcp_live.py"] + argv
    return ab.main()


def main():
    ab.MCPClient = SimClient
    ab.time.sleep = lambda s: None          # offline: no settle waits
    import os
    os.environ["VPT_MCP_AUTHORIZATION"] = "Bearer sim"

    # Never deepen the certified depth-1 run in place — same rule as the live driver.
    if NEW.exists():
        shutil.rmtree(NEW)
    shutil.copytree(SEED, NEW)
    seeded = json.load(open(NEW / "state.json"))
    SimClient.state = seeded.get("current") or ROOT
    print(f"[sim] seeded from {SEED.name}: {len(seeded['nodes'])} nodes, "
          f"start={SimClient.state} | {len(TRANS)} verified transitions, "
          f"{_after} frames over {len(FRAMES)} nodes "
          f"({_before - _after} mis-attributed frames dropped at >{FRAME_DIST_MAX} bits)")

    rounds = 0
    for rnd in range(1, 121):
        rounds = rnd
        rc = run(["explore", "--run-dir", str(NEW), "--under", "settings",
                  "--max-depth", "2", "--max-actions", "100"])
        st = json.load(open(NEW / "state.json"))
        if rc != ab.EXIT_MORE_WORK:
            print(f"\n[explore DONE rc={rc} after {rnd} round(s)] "
                  f"nodes={len(st['nodes'])} edges={len(st['edges'])}")
            break
        if rnd % 10 == 0:
            print(f"[explore round {rnd}] nodes={len(st['nodes'])} edges={len(st['edges'])}")
    else:
        print(f"\n[explore HIT ROUND CAP at {rounds}] — frontier not exhausted")
        rc = ab.EXIT_MORE_WORK

    vrc = run(["validate", "--run-dir", str(NEW), "--under", "settings"])
    st = json.load(open(NEW / "state.json"))
    summary = st.get("validation_summary") or {}
    par = collections.defaultdict(set)
    for e in st["edges"]:
        par[e["target"]].add(e["source"])
    d2 = [n for n in st["nodes"].values() if n.get("depth") == 2]
    multi = [n["node_id"] for n in d2 if len(par[n["node_id"]]) != 1]

    print(f"\n[validate rc={vrc}]")
    print(f"  explore rounds      : {rounds}{' (HIT CAP)' if rc == ab.EXIT_MORE_WORK else ''}")
    print(f"  nodes/edges         : {len(st['nodes'])}/{len(st['edges'])}  depth-2={len(d2)}")
    print(f"  depth-2 multi-parent: {len(multi)} {multi if multi else ''}")
    print(f"  gotos (repositioning): {(summary.get('reposition') or {}).get('gotos')}")
    for k in ("pass", "pass_on_retry", "fail_wrong_screen", "fail_no_effect",
              "source_unreachable"):
        print(f"  {k:<20}: {summary.get(k)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
