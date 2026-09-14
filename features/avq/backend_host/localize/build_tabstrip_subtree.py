#!/usr/bin/env python3
"""Build a navigation subtree for ANY horizontal TAB-STRIP screen, live, into a push-ready run dir.

A "tab strip" is a screen where LEFT/RIGHT move the tab HIGHLIGHT (the body does NOT change) and OK
COMMITS the highlighted tab (the body changes, focus stays on the strip) — e.g. an operator TV UI
*Settings* (Profiles · Accessibility · Parental · Sound&Image · System · Info). It emits the
two-layer structure push_autobuild_to_db.py consumes, mirroring example_tv's convention
(home → home_tvguide → tvguide):

    <root>  (leftmost tab, committed)                         ← e.g. settings (Profiles)
       │RIGHT                                                 move highlight (focus sibling)
       ├─ <root>_<tab1>  ──OK──▶  <tab1>                      commit (content leaf)
       │RIGHT
       ├─ <root>_<tab2>  ──OK──▶  <tab2>
       … one (sibling, leaf) pair per tab

Why it is not trivial (all handled here):
  • the STB REMEMBERS the last tab, so entering the screen lands on an unknown tab → normalize.
  • the strip WRAPS, so a fixed LEFT count overshoots → step LEFT until focus wraps, then RIGHT back.
  • the body LAGS the highlight, and only OK commits it → re-commit Profiles before each tab so every
    sibling shows a consistent body, and read each leaf AFTER its OK.
  • batching RIGHT…+OK fires OK before the highlight settles → press one settled segment at a time.

Reusable: pass the keys to reach the screen and the tab labels. Then push with
push_autobuild_to_db.py. See docs/agent/INTERFACE_EXPLORATION_AI.md § "Tab-strip subtrees".

  # settings (6 tabs; the leftmost = the root, the other five are --tabs):
  python3 build_tabstrip_subtree.py --ui-name example_tv_settings --root-label settings \
      --entry-keys "RIGHT*7,OK" --tabs accessibility,parentalcontrol,soundimage,system,info
"""
import argparse
import importlib.util
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("ab", HERE / "auto_build_mcp_live.py")
ab = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ab)


def _title(fp):
    return re.sub(r"\W+", " ", str((fp or {}).get("title") or "").lower()).strip()


def _fx(fp):
    return float((fp.get("focus") or {}).get("x") or 0)


def parse_keys(spec_str):
    """'RIGHT*7,OK' / 'RIGHT,RIGHT,OK' -> ['RIGHT',...,'OK'] (commas separate, *N repeats)."""
    out = []
    for part in spec_str.split(","):
        part = part.strip()
        if not part:
            continue
        if "*" in part:
            k, n = part.split("*")
            out += [k.strip().upper()] * int(n)
        else:
            out.append(part.upper())
    return out


def main():
    ap = argparse.ArgumentParser(description="Build a tab-strip subtree live into a push-ready run dir.")
    ap.add_argument("--ui-name", required=True, help="output UI name, e.g. example_tv_settings")
    ap.add_argument("--root-label", required=True, help="label of the screen / its leftmost tab, e.g. settings")
    ap.add_argument("--entry-keys", required=True, help="keys home->screen, e.g. 'RIGHT*7,OK'")
    ap.add_argument("--tabs", required=True,
                    help="comma list of the NON-leftmost tab content labels, left->right")
    ap.add_argument("--title-match", default=None,
                    help="fingerprint title that confirms we are on the screen (default: --root-label)")
    ap.add_argument("--max-tabs", type=int, default=12, help="safety cap for the wrap walk")
    ap.add_argument("--host", default="host1")
    ap.add_argument("--device", default="device4")
    ap.add_argument("--device-name", default="blestbv1")
    ap.add_argument("--ui", default="example_tv", help="userinterface to goto-home with")
    ap.add_argument("--mcp-config", default=".mcp.json")
    ap.add_argument("--mcp-url", default="https://rpitest.angelstreet.io/server/mcp")
    args = ap.parse_args()

    tabs = [t.strip() for t in args.tabs.split(",") if t.strip()]
    want_title = (args.title_match or args.root_label).lower()
    entry = parse_keys(args.entry_keys)
    HOST, DEVICE, NAME, UI = args.host, args.device, args.device_name, args.ui

    client = ab.MCPClient(args.mcp_url, ab._find_auth(args.mcp_config), verify_tls=False)
    ab._validate_target(client, HOST, DEVICE, NAME)

    run_dir = HERE / "live_runs" / args.ui_name
    (run_dir / "captures").mkdir(parents=True, exist_ok=True)
    state = {"version": 4, "userinterface_name": args.ui_name,
             "target": {"host_name": HOST, "device_id": DEVICE, "device_name": NAME},
             "next_capture": 0, "nodes": {}, "edges": []}

    def grab(prefix, keys):
        return ab._settled_capture(client, run_dir, state, prefix, host=HOST, device=DEVICE, keys=keys)

    def nav(keys):
        return grab("_nav", keys)[1]

    def on_screen(fp):
        return _title(fp) == want_title

    def enter():
        client.goto_home(HOST, DEVICE, UI)
        fp = None
        for k in entry:                       # one settled segment per key: OK must not fire early
            fp = nav([k])
        if not on_screen(fp):
            raise SystemExit(f"entry keys did not reach {want_title!r} (title={_title(fp)!r}); aborting")
        return fp

    def to_leftmost():
        """Land on the leftmost tab and COMMIT it. The strip wraps, so step LEFT until focus jumps
        RIGHT (we wrapped past the leftmost), then RIGHT back onto it. Generic (no x threshold)."""
        prev = _fx(grab("_nav", [])[1])
        for _ in range(args.max_tabs + 1):
            fp = nav(["LEFT"])
            if _fx(fp) > prev + 0.02:          # wrapped: previous position was the leftmost
                fp = nav(["RIGHT"])
                if not on_screen(fp):
                    raise SystemExit(f"left edge left the screen (title={_title(fp)!r}); aborting")
                return nav(["OK"])             # commit leftmost -> body = leftmost tab
            prev = _fx(fp)
        raise SystemExit("could not find the left edge of the tab strip; aborting")

    nid = [0]

    def add(label, kind, depth, path, shot, fp):
        nid[0] += 1
        node_id = f"node_{nid[0]:04d}"
        state["nodes"][node_id] = {
            "node_id": node_id, "label": label, "kind": kind, "depth": depth,
            "subtree_root": node_id if kind in ("root", "screen") else None,
            "path": path, "screenshot": shot, "fingerprint": fp, "capture_fp": dict(fp),
            "dom": None, "tried": [],
        }
        return node_id

    # root: the leftmost tab, committed -----------------------------------------------------------
    print(f"home -> {want_title} (leftmost tab) …", flush=True)
    enter()
    to_leftmost()
    shot, fp = grab(args.root_label, [])
    root = add(args.root_label, "root", 0, [], shot, fp)
    state["nodes"][root]["subtree_root"] = root
    print(f"  {args.root_label}: title={_title(fp)!r} focus={fp.get('focus')}", flush=True)

    prev_sibling = root
    for i, tab in enumerate(tabs, start=1):
        print(f"[{tab}] -> leftmost, RIGHT*{i} (focus), OK (content) …", flush=True)
        to_leftmost()                                          # renormalize: body = leftmost tab
        sib_shot, sib_fp = grab(f"{args.root_label}_{tab}", ["RIGHT"] * i)
        if not on_screen(sib_fp):
            raise SystemExit(f"tab {tab}: RIGHT*{i} left the screen (title={_title(sib_fp)!r}); aborting")
        sib = add(f"{args.root_label}_{tab}", "sibling", 0, ["RIGHT"] * i, sib_shot, sib_fp)
        state["edges"].append({"source": prev_sibling, "key": "RIGHT", "target": sib,
                               "observed_capture": sib_shot})

        con_shot, con_fp = grab(tab, ["OK"])                   # commit the tab -> content leaf
        gap = ab._hamming(sib_fp.get("dhash", ""), con_fp.get("dhash", ""))
        leaf = ab._ok_entered_new_screen(sib_fp, con_fp, "OK")
        con = add(tab, "screen", 1, ["RIGHT"] * i + ["OK"], con_shot, con_fp)
        state["edges"].append({"source": sib, "key": "OK", "target": con,
                               "observed_capture": con_shot})
        print(f"  {tab}: focus={sib_fp.get('focus')} -> OK dHash gap={gap} "
              f"static={not sib_fp.get('dynamic')} leaf={leaf}", flush=True)
        prev_sibling = sib

    (run_dir / "state.json").write_text(json.dumps(state, indent=1))
    print(f"\nwrote {run_dir/'state.json'} ({len(state['nodes'])} nodes, {len(state['edges'])} edges)", flush=True)
    print("nodes:", ", ".join(f"{n['label']}({n['kind']})" for n in state["nodes"].values()), flush=True)
    print(f"\nnext: push it with\n  python3 features/avq/backend_host/localize/push_autobuild_to_db.py "
          f"--run-dir {run_dir} --ui-name {args.ui_name}", flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
