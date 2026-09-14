#!/usr/bin/env python3
"""Targeted LIVE repro of the settings-tab OK bug on the real STB (no full exploration).

Drives blestbv1/example_tv via the same MCP the explorer uses, through exactly the path that
mis-fired, and prints the NEW verdicts so we confirm end-to-end on hardware:

  goto home -> stamp dynamic         (expect dynamic=True : video tile + live rails)
  RIGHT x7, OK -> settings           (expect dynamic=False: static panel)
  RIGHT -> Accessibility tab focus   (sibling of settings: focus moved, body still Profiles)
  OK   -> Accessibility content      (LEAF: body changed; the press the old code dropped)

Then it applies the patched _same_screen/_same_family and asserts the OK is a real new screen
(leaf), the RIGHT is a focus sibling, and home stayed dynamic. Reuses auto_build_mcp_live so the
exact production code path (fingerprint + _stamp_dynamic + identity) is exercised.

  python3 live_check_settings_ok.py --mcp-config .mcp.json
"""
import argparse
import importlib.util
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("ab", HERE / "auto_build_mcp_live.py")
ab = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ab)

HOST, DEVICE, NAME, UI = "host1", "device4", "blestbv1", "example_tv"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--mcp-config", default=".mcp.json")
    p.add_argument("--mcp-url", default="https://rpitest.angelstreet.io/server/mcp")
    args = p.parse_args()

    client = ab.MCPClient(args.mcp_url, ab._find_auth(args.mcp_config), verify_tls=False)
    ab._validate_target(client, HOST, DEVICE, NAME)

    # minimal state shim for the helpers that expect a run dict (id counters + a scratch dir)
    run_dir = HERE / "live_runs" / "_settings_ok_check"
    (run_dir / "captures").mkdir(parents=True, exist_ok=True)
    state = {"next_capture": 0}

    def grab(prefix, keys):
        _shot, fp = ab._settled_capture(client, run_dir, state, prefix,
                                        host=HOST, device=DEVICE, keys=keys)
        return fp

    print("goto home …")
    client.goto_home(HOST, DEVICE, UI)
    f_home = grab("home", [])
    print(f"  home    : dynamic={f_home.get('dynamic')} title={f_home.get('title')!r} "
          f"focus={f_home.get('focus')}")

    print("RIGHT x7 + OK -> settings …")
    grab("nav", ["RIGHT"] * 6)
    f_settings = grab("settings", ["RIGHT"])          # land on home_settings highlight
    f_settings = grab("settings", ["OK"])             # enter settings (Profiles tab)
    print(f"  settings: dynamic={f_settings.get('dynamic')} title={f_settings.get('title')!r} "
          f"focus={f_settings.get('focus')}")

    print("RIGHT -> Accessibility tab focus …")
    f_focus = grab("acc_focus", ["RIGHT"])
    print(f"  focus   : dynamic={f_focus.get('dynamic')} focus={f_focus.get('focus')}")

    print("OK -> Accessibility content …")
    f_content = grab("acc_content", ["OK"])
    print(f"  content : dynamic={f_content.get('dynamic')} focus={f_content.get('focus')} "
          f"dHash gap vs focus-frame={ab._hamming(f_focus['dhash'], f_content['dhash'])}")

    def classify(node_fp, result_fp, key):
        ok_new = ab._ok_entered_new_screen(node_fp, result_fp, key)
        if ab._same_screen(node_fp, result_fp) and not ok_new:
            return "no-op"
        return "sibling" if (ab._same_family(node_fp, result_fp) and not ok_new) else "leaf"

    checks = []

    def check(name, got, want):
        ok = got == want
        checks.append(ok)
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}: got={got!r} want={want!r}")

    print(f"\n  (info) home dynamic={f_home.get('dynamic')}  settings dynamic={f_settings.get('dynamic')}")
    print("=== probe verdicts (patched code, LIVE frames) ===")
    check("settings is static (so the OK override can trust the dHash)",
          bool(f_settings.get("dynamic")), False)
    check("RIGHT (Profiles->Accessibility tab) is a focus SIBLING",
          classify(f_settings, f_focus, "RIGHT"), "sibling")
    check("OK (commit Accessibility tab) is a LEAF, not a dropped no-op",
          classify(f_focus, f_content, "OK"), "leaf")

    print(f"\n{'ALL PASS' if all(checks) else 'FAILURES PRESENT'} ({sum(checks)}/{len(checks)})")
    return 0 if all(checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
