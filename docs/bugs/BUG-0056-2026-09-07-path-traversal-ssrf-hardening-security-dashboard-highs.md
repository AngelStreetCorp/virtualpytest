# BUG-0056 — Security dashboard's remaining highs: path traversal and SSRF in host/server routes

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0056                                                     |
| Reported  | 2026-09-07                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | High (unauthenticated file read / server-side request from crafted parameters) |
| Area      | backend_host av/stream/translation routes · backend_server heatmap/integrations/monitoring/postman/system routes · features/cicd report serving |
| Fixed in  | build 8713                                                   |
| Commit    | `ba876e7c1` `d78e4e4df` (triage of the false positives: `056cac3e4`) |

---

## Symptom

`docs/security` (the Bandit + Snyk Code + npm audit dashboard) reported **98 high**. After
triage (see below) 28 remained, and 19 of those were real Snyk Code findings:

| Where | Rule | Count |
|---|---|---|
| backend_host routes (av, stream, translation) | Path traversal | 11 |
| backend_server routes (heatmap, integrations, monitoring, postman) | SSRF | 6 |
| backend_server routes (system, ci reports) | Path traversal | 2 |

The other 9 were already gone: Bandit's one high (`verify=False`) was fixed in `969a714a5`,
and the 8 npm audit highs came from a stale `node_modules` — the committed lockfile already
pinned the fixed versions.

## Root cause

Request-controlled strings reached filesystem and outbound-request sinks with either no
validation or a check Snyk could not see:

- `resolveCaptureFilePath` only rejected `..` and a leading `/`; anything else was joined under
  `/tmp/captures`. `resolveImageFilePath` used `normpath` (not `realpath`), so a symlink inside an
  allowed root could point outside it.
- `stream/<device_folder>/…` joined `device_folder` straight into the path; `takeScreenshot`
  used `device_id` as a folder name; `translate-segments` used JSON `hour`/`chunk_index` as path
  components with no type check.
- `_extract_server_path` (heatmap) returned whatever sat between `heatmaps/` and the file name
  and then fetched a URL built from it; the JIRA "test connection" route called
  `https://{domain}/…` with the user's credentials for any `domain` string; `proxyImage`
  interpolated `host_port`/`filename`/`device_id` into the host URL; the Postman runner would
  request any URL an environment or path substitution produced.
- `/server/system/source/*` accepted any `storage_path`, then ran `git -C <path>`, read
  `<path>/VERSION.txt` and extracted zips into it — and the routes were not admin-gated.
- `features/cicd` served `CI_REPORTS_DIR / run` for any `run` (including `..`).

## Fix (`ba876e7c1`)

- **Shared resolvers** — bare file name only + `realpath` containment for captures; `realpath`
  before the allow-list check for images.
- **Host** — `sanitize_folder_name` on `device_folder` and `device_id`; hot/cold stream file must
  resolve under the stream base path; `hour`/`chunk_index` coerced to bounded ints; language code
  validated.
- **Server** — heatmap server_path limited to a plain name; JIRA domain must be a public DNS
  hostname (no scheme/port/path/credentials/IP/localhost); `proxyImage` validates port, filename
  and device id (host_ip was already allow-listed); Postman API paths restricted to their
  character set and the runner only calls this server or a registered host; `storage_path` must
  be absolute and resolve under `STORAGE_SOURCE_ROOTS` (default: parent of the default source
  path) and the six `/source/*` routes require an admin JWT — `CodeDeployment.tsx` now uses
  `apiClient` so it sends one.
- **CI/CD** — `run` must be a single directory directly under `CI_REPORTS_DIR`.

## Triage of the false positives (`056cac3e4`)

74 server + 4 host Snyk `python/XSS` hits were Flask routes ending in `return jsonify(...)`:
JSON responses are never rendered as HTML. They are ignored per file in the repo-root `.snyk`
(the parser applies the same policy, so the dashboard shows them as "· N ignored"). The
dashboard header also now includes the npm audit counts, which it previously dropped.

## Verification

- Validators exercised locally: traversal names, IP/localhost/credential/port JIRA domains,
  `..`/`//`/`#`/`@` Postman paths, out-of-root storage paths, non-int chunk coordinates all
  rejected; legitimate values pass.
- `docs/security` regenerated: Bandit 0 high, npm audit 0. The Snyk sections still come from the
  last SARIF (no Snyk login on the dev machine), so they keep listing the 19 fixed findings until
  someone runs `snyk auth && bash scripts/generate-security-docs.sh`.
- Deployed-server tests (`tests/backend_server/test_{heatmap,integrations,monitoring,postman}.py`)
  target the live server and should be rerun after deploy.

## Result (fresh scan after deploy, `d78e4e4df`)

Snyk scans `backend_host/src` and `backend_server/src` separately, so validators living in
`shared/` are opaque to it and 19 high stayed on the first re-scan. Second pass: the
existing checks were given a scanner-visible form next to each sink (`secure_filename`
after `sanitize_folder_name`, `urllib.parse.quote` on validated URL parts) and one more
real hole closed — the MCP screenshot fetch absolutised relative URLs with the caller's
`Host`/`X-Forwarded-Host` header (now trusted only for our own hostnames). The four
findings behind checks the scanner cannot model (realpath/abspath containment, admin JWT,
server-generated URL) are ignored per file in `.snyk` with reasons.

| | High | Medium | Low |
|---|---|---|---|
| Bandit host / server / shared | 0 / 0 / 0 | 41 / 13 / 10 | 288 / 75 / 126 |
| npm audit | 0 | 0 | 0 |
| Snyk host / server / shared | 0 / 0 / 0 (7 / 78 ignored) | 17 / 7 / 5 | 8 / 6 / 4 |
| **Dashboard header** | **0** | **93** | **507** |

## Medium / low pass (`86705b065`)

Seven routes echoed the exception text to the client (now logged, generic message returned),
adb XML is parsed with defusedxml, and `call_host` passes its timeout explicitly. The rest of
the 93 medium / 507 low described how the system is built rather than bugs, so they are
skipped with a rationale each in `bandit.yaml` (subprocess orchestration, `/tmp` scratch,
0.0.0.0 bind, `try/except: pass`, test asserts) and `.snyk` (guarded `extractall`,
`shutil.which` binaries, wildcard CORS on credential-free assets).

| | High | Medium | Low |
|---|---|---|---|
| Dashboard header | 0 | 2 | 30 |

The 2 medium left are intentional and stay visible: `exec()` in the custom-code builder block
and `chmod 660` on the BLE remote FIFO.

## Host deploy step (defusedxml)

`update_core.sh` rsyncs code but never runs pip, so the hardened XML parser needs a one-off
install on every machine running `vpt-host` (the frontend and server VMs do not need it):

```
sudo -u vpt_user /opt/virtualpytest/venv/bin/pip install 'defusedxml>=0.7.1'
```

Until it is installed the code falls back to `xml.etree` (no crash, no hardening).
Installed 2026-09-07: host-clone-1, sample-app-dongle, sample-app-mobile, sample-app-tablet, vpt-pi1.
Still to do: sample-app-web, sample-app-backend (the deploy user needs a password there), vpt-pi3 (port 223
unreachable at the time).

## Follow-ups

- Deploy `d78e4e4df` + `86705b065` (host + server; the host needs `pip install defusedxml`, falls back to ElementTree until then) — the MCP Host allow-list and the secure_filename calls are not on the VMs yet.
- `/server/system/source/*` admin gating relies on the JWT secret being configured (it is in
  prod); environments without it get `500` from `require_user_auth`, as for `runCommandOnHost`.
