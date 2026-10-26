# BUG-0752 — Atlas spent 220 s on a docs question and never found the IR doc

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0752                                                     |
| Reported  | 2026-10-21                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | High                                                         |
| Area      | backend (agent loop, docs tools) / docs / frontend           |
| Fixed in  | build 90145 |
| Commit    | TBD                                                          |

---

## Symptom

On `/ai-agent`, "which IR standard do you use, can you share the file for apollo or EOS" ran for
220 s (217 s shown as thinking, 49 model rounds, about 40 tool calls) and ended with no answer.
The copied conversation showed the same result under every call of a tool: every `search_docs`
showed `"query": "IR standard infrared remote"` with 0 results, every `read_doc` showed `INDEX.md`,
every `code_refs` showed the `apollo` miss.

## Root cause

Four separate faults.

1. **The master index sent Atlas to files that no longer exist.** `docs/INDEX.md` still listed
   about 50 agent docs at their old flat path (`agent/INFRARED.md`, `agent/MAP.md`,
   `agent/DEVICE_CONTROL.md`, ...) after they moved into `agent/devices/`, `agent/navigation/`,
   `agent/validation/`, ... Every `read_doc` the index suggested answered "File not found". The
   search-docs skill's own path list had the same stale paths.
2. **`search_docs` matched the whole query as one phrase.** "IR key map profile" and "IR standard
   infrared remote" returned 0 files, so the model kept rephrasing.
3. **Nothing capped one answer.** The loop in `AgentManager` had no limit on rounds, tool calls or
   time; the skill's `timeout_seconds` (60 s for search-docs) was declared and never read.
4. **The conversation export paired results by tool name.** `ChatInput.tsx` and `ChatMessages.tsx`
   used `toolResults.find(r => r.tool_name === tool.tool_name)`, so every call showed the first
   result of that tool. The model saw the real results; only the copied transcript was wrong, which
   made the run look like a tool cache bug.

The answer was in the docs all along: `docs/agent/devices/INFRARED.md` explains the IR transports
(lirc, IRTrans, IRToy), the raw-pulse keymaps in `backend_host/src/controllers/remote/ir_conf/<type>.json`
and gives a sample.

## Fix

- `docs/INDEX.md`: every `agent/...` path rewritten to the file's real location; the search-docs
  `SKILL.md` path list too, plus a hint to search with 1-3 keywords.
- `backend_server/src/mcp/tools/docs_tools.py`: `search_docs` keeps a file when every word of the
  query appears in it (word start, so "ir" no longer matches "their"), ranks by capped hits per word
  plus a file-name bonus, bug reports and release notes at half score. `read_doc` on a missing path
  answers "Did you mean: agent/devices/INFRARED.md" with the served files of the same name.
- `backend_server/src/agent/core/manager.py` + `skills/skill_schema.py`: an answer budget. Model time
  (sum of model calls, tool time excluded) defaults to 20 s, tool calls to 12, wall clock to the
  skill's `timeout_seconds` (120 s with no skill). The system prompt states the budget. Past any
  limit the model gets one last round with `tool_choice: none` and must answer with what it found;
  a tool call in that round is never run. Skills that drive devices or build trees set larger
  `think_budget_seconds` / `max_tool_calls` in their frontmatter (120 s / 40, tree builds and
  crawl 600 s / 150).
- Export: a call's result is the `tool_result` between it and the next call.

## Verification

Local: `search_docs("IR keymap")` and `search_docs("infrared")` rank `agent/devices/INFRARED.md`
first; `read_doc("agent/INFRARED.md")` suggests `agent/devices/INFRARED.md`. After deploy: the
same question on `/ai-agent` answers from `agent/devices/INFRARED.md` within the budget.
