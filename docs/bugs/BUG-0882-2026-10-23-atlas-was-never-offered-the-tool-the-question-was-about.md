# BUG-0882 — Atlas was never offered the tool the question was about, because stop-words filled the 11 tool slots

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0882                                                     |
| Reported  | 2026-10-23                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | High                                                        |
| Area      | backend / ai agent                                           |
| Fixed in  | build 90145 |
| Commit    | `421556198`                                                |

---

## Symptom

Atlas answered a plain question with the wrong tool, or with no tool at all, while the right tool was
**never in its tool list**. Measured on the contract (TASK-163, 46 read-only rows against the
production server, 25/46 passed): in **7 of the 21 failures** the expected tool was not in the list at all.

| Prompt | Tool Atlas should have used | What happened |
|---|---|---|
| "What is on the screen of labox-mobile?" | `capture_screenshot` | never offered; Atlas used `dump_ui_elements` |
| "Show me what labbox-mobile is displaying" | `capture_screenshot` | never offered; Atlas used `execute_device_action` |
| "Is labbox-mobile showing a black screen?" | `capture_screenshot` | never offered; Atlas used `dump_ui_elements` |
| "How many android_mobile do we have?" | `list_hosts` | never offered; Atlas used `list_actions` |
| "Open the TV guide on labbox-mobile" | `navigate_to_node` | never offered; Atlas used `get_device_info`, `dump_ui_elements`, `execute_device_action` |
| "What screens can virtualpytest_web reach?" | `list_navigation_nodes` | never offered; Atlas used `get_node` and the docs tools |
| "Is labox-mobile free or in use?" | `get_device_info` | never offered; Atlas used `render_analytics_artifact` |

The other 14 failures are a different problem: the expected tool **was** offered and the model called
something else ("Is labbox-mobile free or in use?" -> `render_analytics_artifact` although
`get_device_info` was in the list; "Show me the open alerts" -> `search_videos` although `get_alerts` was
in the list). That is a tool-choice problem, not a tool-list problem, and this fix does not address it.

## Root cause

`QAManagerAgent._select_router_data_tools` (`backend_server/src/agent/core/manager.py`) offers the model
11 data tools + 3 companion tools. It scores every tool by

- the tool **name** tokens against the question (+8 + 3 per hit),
- the tool **description** tokens against the question (+2 per hit),
- the tool **category** against a per-category hint list (+5),
- `list_*` / `get_*` prefixes (+2).

Three defects in that scoring:

1. **The description match counted English stop-words.** "is", "the", "of", "in", "show", "what",
   "on" appear in nearly every tool description, so `description_overlap` was never empty. Every tool
   scored something, the 11 slots filled with tools that had nothing to do with the question
   (`search_videos`, `code_refs`, `create_custom_page`, `auto_layout_tree`), and a canonical tool could
   be pushed out — `capture_screenshot` was, for every screenshot question of the baseline
   (UC-042, UC-043, UC-056). The fallback list that holds those tools only applies when fewer than 11
   tools scored, which never happened.
2. **The `screenshot` category had no word for "screen".** Its hints were
   `{screenshot, capture, image}`, so "what is on the screen", "is it showing a black screen" and
   "show me what it is displaying" gave the screenshot tools no +5, while `dump_ui_elements`,
   `analyze_screen_for_*`, `auto_discover_screen` and `localize` all matched "screen" and took the
   slots instead. The `navigation` category had the same gap for "open the TV guide" (UC-091) and
   "what screens can X reach" (UC-093).
3. **Only the `analytics` category had core tools that are always offered.** `_ATLAS_ROUTER_CATEGORY_CORE_TOOLS`
   held one entry, so for every other category the canonical tool could be outscored and never offered
   (`list_hosts`, `capture_screenshot`, `list_navigation_nodes`, `navigate_to_node`,
   `list_campaigns`, `list_testcases`, `get_script_execution_status`, `get_alerts`).

## Fix

`backend_server/src/agent/core/manager.py`:

- `_ATLAS_ROUTER_STOPWORDS`: a stop-word set, applied to the **description** match only
  (`description_overlap = (query_tokens & description_tokens) - self._ATLAS_ROUTER_STOPWORDS`). The
  tool-name match and the category hints still see the raw query tokens, so "list the campaigns" still
  matches `list_campaigns` by name.
- `_ATLAS_ROUTER_CATEGORY_HINTS['screenshot']` gains `screen, picture, photo, display, displaying,
  showing, shown`; `['device']` gains the live-state vocabulary the FAQ guard already knows
  (`free, busy, locked, unlocked, awake, asleep, online, offline, alive, reachable, available,
  controlling, controlled, connected`) and `wake, turn, power`; `['navigation']` gains `guide`.
- `_ATLAS_ROUTER_CATEGORY_CORE_TOOLS` now also covers `device`, `screenshot`, `navigation`, `analysis`,
  `script`, `campaign`, `testcase`, `group` and `action`: a question that matches a category's hints
  always gets that category's core tools, however many other tools outscore them.
- The reserved core tools are taken **inside** the budget, not on top of it. The budget of a turn is the
  size of the list the model received before this fix — `_ATLAS_ROUTER_BUDGET_HINTS` and
  `_ATLAS_ROUTER_BUDGET_CORE_TOOLS` keep that scoring — so a reserved core tool takes the room of the
  tools that score lowest and the list is never shorter than before and never longer. Reserving the core
  tools on top of the 11 slots instead made the list grow: "Open YouTube in the browser, search for ..."
  went from 12 tools to 13, over the ceiling of the tool-payload contract that
  `test_router_tools_include_prerequisites` asserts.

### The second defect: the reservation took the room of the tool the question was about

A paired comparison of the branch against `origin/main` over **every** prompt of the contract (not only
the rows of the baseline) found one row that regressed: **UC-030 "Open the app {app} on {device}"**
lost `execute_device_action`, the tool the question is about. Two causes, both introduced by this fix:

1. **The navigation hints held the generic verb `open`.** "Open the app Chrome" is a device action, not
   a navigation question, but `open` put it in the navigation category — so `list_navigation_nodes` and
   `navigate_to_node` were reserved for it and took the room of `execute_device_action`. ("Open the TV
   guide" is a navigation question, and says so with `guide`.)
2. **The reservation took its room without looking at what the question names.** The tools the question
   names score the highest, so they must be in the list before a reserved tool can take their room.

The fix:

- `['navigation']` loses `open` (the generic verb); `guide` carries "open the TV guide".
- The list is built in **score order**: the docs tools first, then the tools that score, best first.
  The tools the question names score the highest, so they are in before any reserved core tool can
  take their room.
- The reserved core tools come after them and take the room of the tools that score **lowest**. A core
  tool that this bug added never takes the room of a tool the question **names directly** (one of the
  question's words is in the tool's name) and never of a tool another offered tool needs (a tool offered
  without the tool that feeds it cannot be used — BUG-0170). The analytics core `origin/main` already
  reserved keeps main's behaviour.
- The `device` core also gets `capture_screenshot`: a question about a device ("is it awake?",
  "turn it on") is answered by the picture of it (UC-033, UC-038).

## Verification

The tool offering is deterministic, so it is verified without a model — **with the router's own code**,
not with a copy of it: the method works on `self.router_tool_names` (114 tools), and a hand-written
replica of the scoring over a different tool list gives different answers.

Measured on the 21 rows that failed in the baseline (`/tmp/bench-baseline-r1.jsonl`), "before" being the
code that was on the server when the baseline ran. The prompt is the **filled** one (the bench sends
"Open the app Chrome on labox-mobile", not the contract's "Open the app {app} on {device}") — measured
on the unfilled prompt the tool list is a different one, and the numbers do not say what the model
actually received:

| The 21 baseline failures | expected tool offered before | expected tool offered after |
|---|---|---|
| 7 rows where it was missing (UC-013, UC-042, UC-043, UC-054, UC-056, UC-091, UC-093) | 0 of 7 | **7 of 7** |
| the other 14 rows | already offered | already offered — a tool-choice problem this fix does not address |

The tool list is bounded too, and that bound was measured on every row of the contract (109 rows)
against `origin/main`'s own selection, "before" being the code that was on the server when the
baseline ran:

| The list the model receives | origin/main | the fix |
|---|---|---|
| size | 13–14 tools | 13–14 tools — the same size on every row |
| rows with a **shorter** list than origin/main | — | **0** |
| rows with a **longer** list than origin/main | — | **0** |
| rows offering a tool without the tool that feeds it | — | **0** |

The paired comparison per row — the expected tool of the row, offered on `origin/main` and on the
branch. Counted the way the bench counts (`grade()`): an **expected-tool entry** is one comma-separated
item of the "Expected tool call(s)" cell, and an entry written `a/b` is **one** entry, satisfied by
either alternative. The 109 contract rows name 137 entries:

| expected-tool entry | count |
|---|---|
| offered on **both** `origin/main` and the branch | 116 |
| offered on `origin/main` only — **a regression** | **0** |
| offered on the **branch** only — what the fix adds | **15**, over 14 rows (UC-013, UC-014, UC-015, UC-032, UC-035, UC-036, UC-037, UC-042, UC-043, UC-054, UC-056, UC-091, UC-093, UC-104) |
| offered on neither | 6 |

The message of `test_router_tools_include_prerequisites` ("Open YouTube in the browser, search for
"Raspberry Pi" and tell me the title of the first result.") offers **12** tools on `origin/main` and
**12** with the fix, with `read_doc`, `analyze_screen_for_action` and `dump_ui_elements` in the list.

The check to run after a change:

```bash
python3 - <<'EOF'
import sys; sys.path.insert(0, '.')
from backend_server.src.agent.core.manager import QAManagerAgent
agent = QAManagerAgent.__new__(QAManagerAgent); agent.agent_id = 'assistant'
for prompt, expected in [("What is on the screen of labox-mobile?", "capture_screenshot"),
                          ("Open the TV guide on labox-mobile", "navigate_to_node"),
                          ("What screens can virtualpytest_web reach?", "list_navigation_nodes")]:
    print(expected, expected in agent._select_router_data_tools(prompt))
EOF
```

End-to-end re-measurement needs the fix deployed:

```bash
scripts/atlas_usecase_bench.py --vars /tmp/vars.json --agents 10 --out /tmp/bench-after.jsonl
```
