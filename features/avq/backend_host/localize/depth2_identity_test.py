#!/usr/bin/env python3
"""Offline regression (no device): DIALOG identity at depth 2, plus the focus-less DOM.

Replays REAL captured frames from two depth-2 settings builds and asserts that
``_same_screen`` tells distinct settings dialogs apart while still merging re-captures of
the SAME dialog — including ACROSS runs.

Guards the 2026-07-18 over-merge. A modal renders OVER the page header, so every settings
dialog OCRs ``title='settings'``; the shared fingerprint reads ``title`` from a narrow
far-LEFT crop and ``text`` from the TOP BAND only, so a dialog's own heading never reaches
it. Distinct dialogs therefore collapsed onto ONE node with contradictory BACK parents,
which surfaced as a bogus "non-returnable dive".

Two independent discriminators are exercised here, because each covers a case the other
misses:
  * ``dialog`` heading (``_dialog_heading``) — works regardless of focus kind. Needed
    because the CV frequently reports focus ``none`` on a dialog (the PIN pad is not a
    detected box), which slipped past a box-scoped check.
  * ``center``-region dHash (``DIALOG_BODY_MAX``) — covers dialogs with NO heading text at
    all (the profile picker is just a list).

It equally guards the OPPOSITE errors: over-splitting a dialog that was merely re-captured,
and the heading extractor firing on a CONTENT screen (which would split tvguide/apps on
every revisit — the apps grid's tiles measure the same glyph height as a dialog heading, so
the modal-plate/dimming test is what separates them).

Run:  python depth2_identity_test.py      -> prints RESULT: PASS / FAIL
"""
import contextlib
import importlib.util
import io
import itertools
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
# Recorded corpora (rsync from the run machine). KEEP these run dirs: they are the only
# place these frames exist, and every assertion indexes into them by filename.
C1 = SCRIPTS / "live_runs/depth2_settings_0718_1754/captures"
C2 = SCRIPTS / "live_runs/depth2_settings_0718_2013/captures"
D1 = SCRIPTS / "live_runs/depth1_verify_0718_1949/captures"

spec = importlib.util.spec_from_file_location("ab", SCRIPTS / "auto_build_mcp_live.py")
ab = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ab)

# capture -> (dialog identity, corpus). Frames sharing an identity are the SAME dialog
# re-captured (reached by OK and by RIGHT, and in two cases from two different RUNS);
# every other pairing is a genuinely different dialog and must NOT merge.
DIALOGS = {
    "0291": ("profile_picker", C1),        # a list, NO heading -> body-hash discriminator
    "0293": ("profile_picker", C1),
    "0359": ("high_contrast", C1),
    "0361": ("high_contrast", C1),
    "0315": ("high_contrast", C2),         # same dialog, DIFFERENT run
    "0433": ("hdmi_resolution", C1),
    "0435": ("hdmi_resolution", C1),
    "0460": ("audio_output", C1),
    "0548": ("zoom_mode", C1),
    "0495": ("home_network_wizard", C1),
    "0342": ("enter_pin", C2),             # focus reports 'none' -> heading discriminator
    "0376": ("enter_pin", C2),
}

# Content screens must yield NO dialog heading, or their identity would split on revisit.
CONTENT = {"tvguide": "0003", "apps": "0006", "home": "0016", "search": "0018",
           "profile": "0039", "settings": "0042", "recordings": "0074"}


def _fp(cap: str, corpus: Path):
    path = corpus / f"capture_{cap}.png"
    if not path.exists():
        raise SystemExit(f"corpus frame missing: {path}\n"
                         f"(the depth-2 run dirs are the corpus — rsync from the run machine)")
    with contextlib.redirect_stdout(io.StringIO()):
        return ab._fingerprint(path)


def main() -> int:
    fps = {c: _fp(c, corpus) for c, (_, corpus) in DIALOGS.items()}
    failures, checks = [], 0

    for a, b in itertools.combinations(sorted(DIALOGS), 2):
        expected = DIALOGS[a][0] == DIALOGS[b][0]
        with contextlib.redirect_stdout(io.StringIO()):
            verdict = ab._same_screen(fps[a], fps[b])
        checks += 1
        if verdict != expected:
            failures.append(
                f"  {DIALOGS[a][0]}({a}) vs {DIALOGS[b][0]}({b}): _same_screen={verdict}, "
                f"expected {expected} [center={ab._region_ham(fps[a], fps[b], 'center')}, "
                f"dialog={fps[a].get('dialog')!r} vs {fps[b].get('dialog')!r}]"
                + ("  <- OVER-MERGE" if verdict else "  <- OVER-SPLIT"))

    # Every dialog that HAS heading text must expose it (else the discriminator is inert).
    for cap in ("0315", "0342", "0433", "0495"):
        checks += 1
        if not fps[cap].get("dialog"):
            failures.append(f"  {DIALOGS[cap][0]}({cap}): no dialog heading extracted")

    # ...and no CONTENT screen may produce one.
    for label, cap in CONTENT.items():
        checks += 1
        with contextlib.redirect_stdout(io.StringIO()):
            heading = ab._dialog_heading(D1 / f"capture_{cap}.png")
        if heading:
            failures.append(f"  content screen {label}({cap}) produced heading {heading!r} "
                            f"-> would split it on revisit")

    # A dialog with no focusable control is a VALID DOM, not a reason to abort the round.
    checks += 1
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            ab._validate_dom({"screen_summary": "Diagnostics panel; no focusable controls.",
                              "screen_type": "dialog", "focused_element_id": None,
                              "focusable_elements": [], "navigation": {}},
                             Path("focusless.json"))
    except ab.LiveBuildError as exc:
        failures.append(f"  focus-less DOM rejected: {exc}")

    print(f"depth-2 dialog identity: {checks - len(failures)}/{checks} checks passed "
          f"({len(DIALOGS)} dialog frames, {len({v[0] for v in DIALOGS.values()})} distinct "
          f"dialogs, {len(CONTENT)} content screens)")
    if failures:
        print("\n".join(["FAILURES:"] + failures))
    print("RESULT:", "FAIL" if failures else "PASS")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
