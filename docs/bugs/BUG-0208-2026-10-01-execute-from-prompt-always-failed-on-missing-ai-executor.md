# BUG-0208 — Running a testcase from a prompt always failed: the host looked for an AI executor that no longer exists

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0208                                                     |
| Reported  | 2026-10-01                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium — an API route that never worked; no current UI calls it |
| Area      | `backend_host/src/routes/host_testcase_routes.py` · `backend_server/src/routes/server_testcase_routes.py` |
| Fixed in  | build 90145 |
| Commit    | this commit                                                  |

---

## Symptom

`POST /server/testcase/execute-from-prompt` (prompt → testcase → run) answered
`500 Device device1 does not have AIExecutor initialized` on every host and device, before
touching the device. `POST /server/testcase/generate-with-ai` proxied to the same host
route, so it failed the same way.

Nobody noticed because no page calls either route. The only frontend caller is the
`useAI` hook (the old Live AI modal), and nothing imports it any more. The AI feature people
use, the AI panel in the device stream modal (`AIExecutionPanel` in `RecHostStreamModal`),
goes through `/server/ai/generatePlan` + `/server/testcase/execute` instead.

## Root cause

Prompt handling moved from a per-device `ai_executor` to `AIGraphBuilder`
(`device.ai_builder`, created in `controller_manager.py`), which only builds the graph;
running it is the `TestCaseExecutor`'s job. `/host/testcase/execute-from-prompt` was never
moved over: it still checked `device.ai_executor` and called `ai_executor.execute_prompt`,
and nothing sets that attribute.

## Fix

- `/host/testcase/execute-from-prompt` now generates the graph with
  `device.ai_builder.generate_graph` (preprocessing, disambiguation and cache live there),
  saves it when `save=true`, and runs it through the shared `TestCaseExecutor`, the same
  sync or async path as `/host/testcase/execute`. An async run returns an `execution_id`
  and emits the standard `testcase` execution events. The response carries the executor
  result plus `graph`, `analysis`, `saved` and `testcase_id`. A disambiguation answer keeps
  its shape (`needs_disambiguation`, `analysis`, `available_nodes`). `use_cache` and
  `skip_validation` are gone: the builder decides both.
- The server route keeps the device locked until the async run's terminal event (as
  `/server/testcase/execute` does), with a 180 s proxy timeout to cover the LLM call.
- `/server/testcase/generate-with-ai` now calls `/host/ai/generatePlan`: it generates
  only and never runs anything, which is what it always claimed to do.

## Verification

- Flask test client, host route, with a fake device (`ai_builder.generate_graph` mocked) and
  a mocked executor: async → `execution_id` and the graph is passed to
  `execute_testcase_from_graph_async` with host, model, name and trigger; sync → executor
  result; `save=true` → `create_testcase(creation_method='ai')` and the name is used for the
  run; `save=true` without a name → 400; disambiguation → 200 `needs_disambiguation` and
  nothing runs; a generation error → 400; an unknown device → 404.
- Server route with the host call mocked: lock held while the run is going, released on the
  `completed` event, released at once on a disambiguation answer; `generate-with-ai` hits
  `/host/ai/generatePlan` and takes no lock.
- Not yet run against a live host and LLM.

Remaining `ai_executor` references, all equally dead: `/host/ai/executePlan`,
`/executeTestCase`, `/analyzeCompatibility`, `/analyzePrompt`, `/saveDisambiguation`,
`/getStatus`, `/stopExecution`, `/getDevicePosition`, `/updateDevicePosition`, `/status/<id>`.

Related, not fixed here: the stream-modal AI panel posts `/server/ai/saveDisambiguationAndRegenerate`
when the user resolves a disambiguation with *save* ticked, and no server route of that name
exists (404).
