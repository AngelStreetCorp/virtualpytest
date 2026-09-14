#!/usr/bin/env python3
"""Offline regression for the settings-tab OK bug (no STB, no full exploration).

Reproduces, from the SAVED captures + state of run example_tv_autobuild2_clean, the exact probe
decisions involved and proves the surgical fix:

  • the OK on the Accessibility tab (Profiles list -> Accessibility list, dHash gap 40) is now a
    LEAF, not the dropped no-op it used to be — via _ok_entered_new_screen on a STATIC source;
  • the RIGHT that only moved focus is still a SIBLING;
  • NO REGRESSION on dynamic/volatile screens: home-menu items (which share the title "q home tv"
    but differ 83-88 dHash bits) stay SIBLINGS, and a home revisit still matches the home node.

The fix is deliberately NOT in _same_screen/_same_family (those still use the title fallback that
keeps home/tvguide from splitting); it lives at the probe site, gated on the source being static.
"""
import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
RUN = HERE / "live_runs" / "example_tv_autobuild2_clean"
CAPS = RUN / "captures"

spec = importlib.util.spec_from_file_location("ab", HERE / "auto_build_mcp_live.py")
ab = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ab)

STATE = json.loads((RUN / "state.json").read_text())["nodes"]


def fp_png(name):
    return ab._fingerprint(CAPS / name)


def fp_node(label):
    return dict(next(v["fingerprint"] for v in STATE.values() if v.get("label") == label))


def classify(node_fp, result_fp, key):
    """Mirror the probe-loop decision exactly."""
    ok_new = ab._ok_entered_new_screen(node_fp, result_fp, key)
    if ab._same_screen(node_fp, result_fp) and not ok_new:
        return "no-op"
    is_sibling = ab._same_family(node_fp, result_fp) and not ok_new
    return "sibling" if is_sibling else "leaf"


def classify_OLD(node_fp, result_fp, key):
    """Pre-fix decision (no _ok_entered_new_screen)."""
    if ab._same_screen(node_fp, result_fp):
        return "no-op"
    return "sibling" if ab._same_family(node_fp, result_fp) else "leaf"


def main():
    f_profiles_pf = fp_png("capture_0090.png")   # settings : Profiles focus,      Profiles body
    f_profiles_af = fp_png("capture_0092.png")   # node_0041: Accessibility focus,  Profiles body
    f_access_af = fp_png("capture_0093.png")     # OK result: Accessibility focus,  Accessibility body
    f_home = fp_node("home")
    f_home_tvguide = fp_node("home_tvguide")
    f_home_b = fp_png("recover_0014.png")        # home, later visit (self-drift 80)

    # dynamic bit, derived the way live _stamp_dynamic does (self-drift between same-screen frames):
    settings_drift = ab._hamming(f_profiles_pf["dhash"], f_profiles_af["dhash"])  # static -> ~0
    for f in (f_profiles_pf, f_profiles_af, f_access_af):
        f["dynamic"] = settings_drift > ab.DYNAMIC_DRIFT_BITS  # False (static)

    print(f"settings self-drift={settings_drift} bits -> dynamic={f_profiles_af['dynamic']}  "
          f"| OK dHash gap={ab._hamming(f_profiles_af['dhash'], f_access_af['dhash'])} bits")
    print(f"home-menu gaps: home..home_tvguide="
          f"{ab._hamming(f_home['dhash'], f_home_tvguide['dhash'])}  home self-drift(revisit)="
          f"{ab._hamming(f_home['dhash'], f_home_b['dhash'])}\n")

    checks = []

    def check(name, got, want):
        ok = got == want
        checks.append(ok)
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}: {got!r} (want {want!r})")

    print("--- the fix: OK on the Accessibility tab ---")
    check("OLD dropped it as a no-op", classify_OLD(f_profiles_af, f_access_af, "OK"), "no-op")
    check("NEW makes it a LEAF",        classify(f_profiles_af, f_access_af, "OK"),     "leaf")

    print("\n--- RIGHT only moved focus ---")
    check("RIGHT is a sibling", classify(f_profiles_pf, f_profiles_af, "RIGHT"), "sibling")

    print("\n--- NO regression on dynamic/volatile screens ---")
    check("home-menu RIGHT stays a sibling (not a leaf, despite 85-bit gap)",
          classify(f_home, f_home_tvguide, "RIGHT"), "sibling")
    check("home revisit still matches the home node (no split)",
          ab._same_screen(f_home, f_home_b), True)
    check("_ok_entered_new_screen never fires for a non-OK key",
          ab._ok_entered_new_screen(f_home, f_home_tvguide, "RIGHT"), False)

    print(f"\n{'ALL PASS' if all(checks) else 'FAILURES PRESENT'} ({sum(checks)}/{len(checks)})")
    return 0 if all(checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
