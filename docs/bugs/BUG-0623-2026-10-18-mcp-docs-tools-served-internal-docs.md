# BUG-0623 — MCP docs tools served internal docs and unscrubbed lab addresses

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0623                                                     |
| Reported  | 2026-10-18                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium                                                       |
| Area      | backend / mcp / docs                                         |
| Fixed in  | build 90145 |
| Commit    | TBD                                                          |

---

## Symptom

The MCP tools `list_docs`, `search_docs` and `read_doc` (`backend_server/src/mcp/tools/docs_tools.py`)
served everything under `docs/` except dotfiles and names containing words like "secret". That
included gitignored runbooks (`docs/agent/infra/`, `docs/agent/TROUBLESHOOT.md`, …) and the
internal-only paths listed in `scripts/security/internal-paths.txt` (`docs/tasks/`,
`docs/agent/release/`, `docs/security/*.json`, …). The agent docs it did serve still held
private lab addresses (`192.168.x.…`, `10.10.x.…`), a public gateway address, a clear-text database password,
a default VNC password and an operator login name.

Separately, a client saw `{"properties": {}, "required": []}` as the input schema of `read_doc`, so
`path` could not be passed.

## Root cause

- The tools only filtered by file name; nothing consulted `.gitignore` or `internal-paths.txt`.
- Tool schemas are generated from docstrings (`mcp/tool_definitions/auto_generator.py`), which reads
  an `Args: params: { 'name': type (REQUIRED - …) }` block. `read_doc` and `list_docs` had no such
  block, so their schema came out empty. `search_docs` already had one and was correct.

## Fix

- `docs_tools.py` parses the `docs/` lines of the repo-root `.gitignore` and of
  `scripts/security/internal-paths.txt` once (path rules only, no git at runtime; case-insensitive,
  so tracked-but-gitignored files are blocked as well). `read_doc` refuses internal paths; `list_docs`
  and `search_docs` skip them. The one deliberate exception is the whole-directory `docs/agent/`
  entry: that is the public-snapshot rule, and the agent docs are what this server exists to serve.
  Every finer entry under it still applies.
- `read_doc` and `list_docs` gained the `Args:` block, so the schemas now list `path` (required) and
  `section`. Stale examples (`agent/MAP.md`) point at `agent/navigation/MAP.md`.
- The served docs were scrubbed following `docs/agent/release/ANONYMIZATION.md`: lab addresses become
  `192.168.x.N` / `10.10.x.N`, the public gateway address `<gateway-ip>`, passwords and the operator
  login name placeholders. Generic home-network examples in `docs/get-started/`, `docs/user-guide/`
  and `docs/technical/` were left as written.
- A second pass removed what the first left: internal infrastructure hostnames (now `<pi-server-host>`,
  `<host-server>`, `<app-host>` …), operator home paths (`<repo>` / `~/`) and a probe e-mail on our
  own domain (`@example.com`). The old clear-text database password is no longer quoted here.
- `scripts/security/served_docs_check.py` keeps it that way: it lists the served set through
  `docs_tools.py` (same filter, nothing copied) and fails on lab and tailnet addresses outside the
  tutorial blocks, `*.angelstreet.io` hosts other than the public product URL, `/Users/<name>/`
  paths, `@angelstreet.io` addresses, `PGPASSWORD=<literal>` and token shapes. `review_gate.sh`
  runs it as a blocking check on any push that touches `docs/` or `docs_tools.py`.
- The check also fails the lab subnets with a placeholder last octet (a lab network with `xxx`, `<VMID>` or `x` as the last octet): the network leaks even when the host does not. They now read `192.168.x.xxx` / `192.168.x.<VMID>` / `10.10.x.…`.

## Verification

`pytest tests/backend_server/test_mcp_docs_internal.py`; `python3 scripts/security/served_docs_check.py`; `scripts/security/leak_gate.sh --all` clean.
