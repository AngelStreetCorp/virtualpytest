# BUG-0042 — Script report: "Test Steps" header toggle never collapses the steps; expanded icon renders as ◀

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0042                                                     |
| Reported  | 2026-09-03                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Low (cosmetic / navigation nuisance on every script report)  |
| Area      | `shared/src/lib/utils/report_template_html.py`, `report_template_css.py` |
| Fixed in  | build 8713                                                   |
| Commit    | `59b1ff96e`                                                  |

---

## Symptom

On the generated script report (`report.html`), clicking the **Test Steps (N/N passed)** section
header does nothing: the step list stays fully visible, and the header icon never changes.
The icon in the expanded state shows **◀** instead of ▼, so the section looks collapsed while
it is open. The **Execution Summary** header collapses fine (but also shows ◀ while open).

## Root cause

Two independent defects in the shared report template:

1. `#steps-content` was emitted with classes `collapsible-content steps-expanded` — **without**
   the `expanded` class the JS toggle keys on. `.steps-expanded` set `max-height:none;
   overflow:visible` unconditionally. `toggleSection()` therefore took the *expand* branch on
   the first click (no-op, content already visible), and even when the class state flipped, the
   `overflow:visible` from `.steps-expanded` kept every step painted through the `max-height:0`
   collapse. The 400 ms cleanup then cleared the inline `max-height`, handing control back to
   `.steps-expanded` (`none`), so the section could never be hidden.
2. `.toggle-btn.expanded { transform: rotate(90deg) }` was stacked on top of the JS glyph swap
   (`▶` ↔ `▼`). Rotating `▼` by 90° yields `◀`, hence the wrong arrow in the expanded state.

## Fix

- `report_template_html.py`: both section containers now use `collapsible-content expanded`;
  the `steps-expanded` class is gone.
- `report_template_css.py`: removed the `.steps-expanded` rule and the `.toggle-btn.expanded`
  rotation (the glyph swap alone indicates state). `.collapsible-content.expanded` already
  provides `max-height:none; overflow:visible`, so reports still render fully open without JS.

Per-step `toggleStep()` (row click → details) is untouched.

## Verification

Headless Chromium (Playwright) against `backend_server/src/agent/benchmarks/tests/report.html`
with the template change applied:

| State                  | Before fix                                   | After fix                          |
|------------------------|----------------------------------------------|------------------------------------|
| initial                | h=300, overflow visible, ▼ rotated 90° (◀)   | h=300, overflow visible, ▼, no rotation |
| click "Test Steps"     | h=300, unchanged                             | h=0, overflow hidden, ▶            |
| click again            | h=300, unchanged                             | h=300, overflow visible, ▼         |
| click a step row       | details expand                               | details expand / collapse as before |
