# BUG-0210 — AI-generated test graphs failed on every action and verification block

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0210                                                     |
| Reported  | 2026-10-01                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | High — a generated graph passes only when it is navigation-only; Test Prompt's Run graph adds verifications for every acceptance criterion |
| Area      | `backend_host/src/services/ai/ai_builder.py` (graph generation, usage `text.plan`) |
| Fixed in  | build 90145 |
| Commit    | this commit                                                  |

---

## Symptom

A test graph generated from a prompt runs its navigation blocks. It then stops at the first
action or verification block with *Action block has no actions — re-create the block* or
*Verification block has no verifications — re-create the block*. This affects every caller of
`ai_builder.generate_graph`: Test Prompt **Run graph** (TASK-36), the stream-modal AI panel
(`/server/ai/generatePlan` then `/server/testcase/execute`), the Test Builder's AI generation,
and `/server/testcase/execute-from-prompt`. Found while reading the generated graph's shape for
TASK-36 phase 2 (can QuickTest open it?). It has not yet been seen on a device, because Run graph
was not deployed.

## Root cause

There were two block shapes. The testcase executor and both builders use container blocks
(`data.actions: [{command, action_type, params}]`,
`data.verifications: [{command, verification_type, params}]`). The executor rejects any other
shape. `ai_builder._steps_to_graph` still wrote the single-command shape (`data.command` for an
action, `data.verification_type` for a verification).

The LLM was also asked only for a command name (`Action: press_key`), never its params. So even
in the right shape, `press_key` had no key and `waitForTextToAppear` had no text.

## Fix

- The prompt lists each action and verification with its params (`press_key(key=OK)`,
  `waitForTextToAppear(text=<Text to search for>, timeout=<…, optional>)`). The LLM writes steps
  the same way: `Action: press_key(key=OK)`, `Verify: waitForTextToAppear(text="Live TV")`.
- `_steps_to_graph` writes container blocks. Each item is typed from the device catalog
  (`action_type`; for a verification, `verification_type` from its `verification_<type>`). The
  LLM's params are merged over the catalog's schema defaults. A concrete catalog value, such as
  `press_key`'s `key=UP`, is an example and is never used as a default.
- Labels, the invalid-node filter and the debug log read the command from the container.
- The graph cache fingerprint (`ai_graph_cache_db._generate_fingerprint`) now includes
  `graph_format: 2`, so graphs cached in the old shape are not served again.

## Verification

- Offline, with a stubbed catalog (`press_key` key=UP/OK, `input_text`, `waitForTextToAppear`
  with a typed `text`/`timeout`/`area`): the reply
  `Action: press_key(key=OK)`, `Action: input_text(text="Hello, world")`,
  `Verify: waitForTextToAppear(text="Live TV", timeout=5000)` becomes
  `actions: [{press_key, remote, {key: OK}}]`, `actions: [{input_text, remote, {text: "Hello, world"}}]`
  and `verifications: [{waitForTextToAppear, text, {text: "Live TV", timeout: 5000}}]`. The area
  param is left out of the prompt.
- Still to do: on a device after deploy, run a prompt with an acceptance criterion through Test
  Prompt **Run graph** (TASK-36 §2.7). The verification block runs instead of failing on its
  shape.
