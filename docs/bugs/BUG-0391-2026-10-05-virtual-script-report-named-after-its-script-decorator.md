# BUG-0391 — A virtual script's report was named after the @script() name in its code

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0391                                                     |
| Reported  | 2026-10-05                                                   |
| Status    | Closed                                                       |
| Severity  | Low                                                          |
| Area      | backend_host / shared executors                              |
| Fixed in  | Unreleased |
| Commit    | TBD                                                          |

---

## Symptom

Running the virtual script `smoke_goto_live` produced a report titled `goto_live.py`: the name in
the `@script("goto_live", …)` decorator inside its source, not the virtual script's own name. A
script copied from another one kept reporting under the original's name.

## Root cause

The host materialises a virtual script into a temp file and runs it as a subprocess. The parent
already passes the right name: `script_name` (the virtual script's name) goes to the child as
`VPT_SCRIPT_REF`, with `VPT_VIRTUAL_SCRIPT_ID`. But inside the child, the `@script` decorator builds
`ScriptExecutor(name, …)` with the decorator's argument, and every report artefact uses
`f"{self.script_name}.py"` (report title, metadata, verification review, result row) — so the
decorator name won.

## Fix

`ScriptExecutor.__init__` (`shared/src/lib/executors/script_executor.py`) takes its name from
`_virtual_script_name()` when the process runs a virtual script (`VPT_VIRTUAL_SCRIPT_ID` set): the
basename of `VPT_SCRIPT_REF`. Disk scripts keep their decorator name, as before.

## Verification

- `python3 -m pytest tests/shared/test_virtual_script_report_name.py` — virtual run uses the
  virtual name, disk run keeps the decorator name, virtual run without a ref falls back.
- On the deployed build: run `smoke_goto_live` from Virtual Scripts; the report and the Test Reports
  row read `smoke_goto_live.py`.

### Live check (2026-10-05, node1)

Virtual script `smoke_goto_live` run on host-clone-1/host through `POST /server/script/execute`: report `<title>` is `Validation Report - smoke_goto_live.py` (decorator name is `goto_live`); result row `script_name` = smoke_goto_live.
