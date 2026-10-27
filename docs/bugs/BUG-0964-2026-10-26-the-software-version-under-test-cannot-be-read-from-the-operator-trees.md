# BUG-0964 — The software version under test cannot be read from the operator trees: two published trees have no `info` node and a third asserts no version

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0964                                                     |
| Reported  | 2026-10-26                                                   |
| Status    | Open                                                         |
| Severity  | Medium                                                       |
| Area      | platform / navigation trees                                  |
| Fixed in  | Unreleased                                                   |
| Commit    | —                                                            |

---

## Symptom

`AGENTS.md` (owner, 2026-10-26) states the rule every operator tree must satisfy:

> **Every tree has a `settings` node and an `info` node that reads the software version.**
> A tree without them is not finished: the version under test must be readable from the tree.

Read against the live platform on 2026-10-26, that rule holds for **one** published tree. The
others do not reach the version at all, or reach the screen that carries it without asserting
anything on it:

| Tree (platform) | Published | `settings` | `info` | The version under test |
|---|---|---|---|---|
| web | v2, 2026-10-26 20:20 | yes | yes | **readable** — the settings route, the version row's label, and an edge that scrolls that row into view. The model. |
| web | v1, 2026-10-22 12:11 | yes | **no** | **not reachable** — nothing in the tree gets to the version row |
| STB | v1, 2026-10-26 11:33 | yes | yes | **not asserted** — the `info` node reaches the About screen but waits for the screen's title, never for a version value |
| Android mobile | v1, 2026-10-26 14:08 | yes | **no** | **not reachable** — and the `settings` node carries no verification at all |
| Android TV | not published (dev only) | yes | **no** | **not reachable** |

Measured with the platform's own API
(`GET /server/navigationTrees/getTreeByUserInterfaceId/<id>`, then
`GET /server/userinterface/<id>/publishes`):

* **web, v1** — 26 nodes, 25 edges. The `settings` node verifies the app's settings route. There
  is no `info` node. The tree carries 36 `execute_javascript` actions and every one of them is a
  navigation helper — a wait, a scroll, a synthesised tap on a semantics node — so the tree can
  drive the app but never asks what version it is driving.
* **STB, v1** — the published snapshot is 98 nodes / 83 edges over 26 trees with 4 variants; the
  prod root tree itself returns 24 nodes. It has `settings`, `settings_info` and `info`. The
  `info` node's verification is a `waitForTextToAppear` on the localized *About* title (reference
  `settings_about_text`, area 320×90 at 500,65), so the node arrives at the screen that carries
  the version and stops there. Nothing in the tree mentions a version: **zero** occurrences of
  the word, zero `execute_javascript` actions.
* **Android mobile, v1** — 11 nodes, 11 edges. The `settings` node exists but its verification
  list is **empty**, and there is no `info` node.
* **Android TV** — 14 nodes, 14 edges, never published. A `settings` node exists, an `info` node
  does not.

So for two published trees the answer to "which version was this run against?" is not in the tree
at all, and for a third the tree can reach the screen without ever reading it.

## Root cause

**The rule was written as a convention, and a convention has no gate.** `AGENTS.md` states the
requirement and one tree demonstrates it, but nothing in the repository or in the platform checks
a tree against the rule before it is published. The trees that violate it were published on
2026-10-22 and 2026-10-26 — the same day the rule was written, and after it. They were not
published against the rule; they were published without it.

Two further points make the gap invisible rather than merely unfixed:

1. **A tree can carry an `info` node and still not read a version.** The STB tree proves it: the
   node is there, the verification reaches the right screen, and no assertion covers the version
   string. A check that only looked for the *presence* of a node named `info` would have passed
   it. The requirement is behavioural — a version value is read — not a naming convention.
2. **The repository's own inventory of these trees is out of date, and it is what an agent reads
   to decide what is finished.** The internal operator-tree inventory (in `docs/tasks/`, whose
   file name carries an operator codename and is therefore not repeated here) still lists the STB
   tree as *not published*, while the platform shows it published to prod v1 on 2026-10-26 11:33
   (26 trees, 4 variants, 98 nodes, 83 edges). The same document contradicts itself on the
   Android mobile tree: its summary table says the tree was validated on 2026-10-26 at 87 % and
   published, while its gap table says the tree "has never been validated" and that there are
   "zero `validation` rows". The platform records **two** runs for that tree, on the Pi backend
   (2026-10-26 13:44 and 13:59), and **both are failures**: `success=False`,
   `error_msg="Script execution failed"`. The second run's own review says it produced 27 steps
   and 84 screenshots and that "a generic 'Script execution failed' after substantial progress
   suggests real product failure, not setup issue". So the run happened and failed; the
   inventory's "validated" wording does not say that.

An inventory that says a tree is unpublished, and a gap table that says a tree was never run
while the run failed, are worse than no inventory: they answer a question nobody asked, with an
answer that is wrong.

## Fix

The trees are fixed in the platform, by the sessions that own them, in dev and then through the
normal validate-then-promote procedure — not by editing prod. This document records the gap and
the shape to copy; the tree work is tracked with the owning sessions.

**The model to copy is the web v2 tree.** Its shape, measured on the live tree:

* the `settings` node verifies `waitForUrlToMatch` on the app's settings route (timeout 10 s);
* the `info` node verifies the same route plus `waitForElementToAppear` on the version row's
  label (timeout 10 s);
* the edge between them is an `execute_javascript` action that finds the element whose text is
  exactly that label and scrolls it into view (`scrollIntoView({block:'center'})`), waiting 1.5 s.

The version is then read off the page with a script over the page text — `innerText` matched
against `Version\s+(V[\d.]+)` — because the OCR-based `getMenuInfo` reads only the top of the page
and misses the row below the fold, and an XPath `waitForElementToAppear` on the version row made
the validation hang. The tree's job is to *reach and hold* the version row; the read is a script
on top of it. The exact strings for the app under test are in the internal operator inventories,
not here.

**For STB and Android the shape is the same and the screen is different:** Settings, then the
About / app-info screen, and the version is read from *that* screen. The STB tree already has the
navigation half — `settings` → `settings_info` → `info` arrives at the About screen — so what it
needs is the missing half: a `waitForTextToAppear` on the version value itself, in the area of
that screen where the version line is rendered, matching the version pattern rather than the
screen title. The Android mobile and Android TV trees need both halves: an `info` node that
reaches their About / app-info screen, and the version assertion on it. The Android mobile
`settings` node also needs a verification — it currently asserts nothing.

**The check that would have caught this is the part that belongs in the repository.** The rule
lives in `AGENTS.md`; the tree inventory (`scripts/agent/operator_ui_inventory.py`) already walks
every operator tree and reports its nodes, edges, variants, publishes and validation runs. It
reported *how many* nodes a tree had and never *which* ones, so a tree with 26 nodes and no `info`
node looked exactly like a tree with 26 nodes and one. It now reports, per tree, whether the
`settings` node and the `info` node are present, what the `info` node waits for, and whether any
string in the tree mentions a version — so "is this tree finished?" is answered by the platform
instead of by memory, and the inventory document can be regenerated from the platform rather than
written by hand.

The verdict it prints is about the two nodes, because that is what the platform can decide. The
deeper question — whether the `info` node reaches the version *row* — is app-specific: the row
is labelled in the app's own language, and the model tree holds that row without the word
"version" appearing anywhere, the version itself being read by a script on top of the tree. So
the inventory prints what the `info` node waits for and leaves the judgement to whoever owns
the tree. That is what makes the STB case visible instead of invisible: its `info` node waits for
the About screen's *title*, and the printed assertion says exactly that.

That last point is the one that keeps the gap from coming back: the inventory document has to be
regenerated from the platform after each platform's work, and its publish state and validation
rows have to come from the same read, so that a stale "not published" or "never validated" line
cannot outlive the state it describes.

## Verification

1. Re-read every published operator tree from the platform and check the rule directly:

   ```
   GET /server/navigationTrees/getTreeByUserInterfaceId/<dev-id>?team_id=<team>
   GET /server/userinterface/<dev-id>/publishes?team_id=<team>
   ```

   For each tree: a node labelled `settings`, a node labelled `info`, and — the part that is not
   a naming convention — the `info` node must assert on the version *row* of the app's own
   About screen, not only on that screen's title. The row is labelled in the app's own
   language, so that check is made against the app; the inventory prints the assertions so the
   difference is visible instead of assumed.

2. After the fix, `python3 scripts/agent/operator_ui_inventory.py` must report `settings and
   info` for every published operator tree — and the assertion it prints for the `info` node
   must be the one on the version row — and the inventory document's publish state and
   validation rows must match the platform's rows, including the two Android-mobile runs that
   are currently `success=False`, and the STB tree that is published but listed as not
   published.

3. The regression CI: `bash scripts/docs/check_bug_ids.sh` and the release-note check
   (`python3 scripts/release/check_release_notes.py`) stay green, and the leak gate accepts the
   change — this document names no operator and no customer.
