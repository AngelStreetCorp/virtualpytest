# BUG-0148 — The security dashboard claimed to scan Python dependencies for CVEs and never did

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                                         |
|-----------|-------------------------------------------------------------------------------|
| ID        | BUG-0148                                                                      |
| Reported  | 2026-09-17                                                                    |
| Status    | Fixed (the false claim is gone; the coverage gap is open and documented)       |
| Severity  | Medium (no exploit; a whole scan class was advertised and absent for months)   |
| Area      | `scripts/generate-security-docs.sh`, `docs/security/README.md`                 |
| Fixed in  | Unreleased                                                                    |
| Commit    | `67878bf13d`                                                                         |

---

## Symptom

Every `npm run build` printed a warning nobody acted on:

```
→ Checking security tools...
  ✓ Bandit available
  ⚠ Safety not found
     Install: pip install safety (from backend_server/requirements.txt)
```

Reported as: *"i always see this on frontend why"*.

The warning was the visible half. The invisible half was that `docs/security/README.md` listed

| **backend_host/requirements.txt** | Safety | Dependency CVEs |
| **backend_server/requirements.txt** | Safety | Dependency CVEs |

as covered, and the dashboard those rows describe had no such card — on any machine, whether or
not Safety was installed.

## Root cause

Two independent failures that hid each other.

**1. The tool was never installed where the scan runs.** `safety>=3.0.0` was declared in
`backend_server/requirements.txt`, but the frontend VM — the machine that runs the docs pipeline,
via `vpt-frontend-prod.service` → `ensure_dist.sh` → `prebuild.sh` — does not install that file.
It has **no virtualenv at all**; its `bandit` comes from the Debian package `python3-bandit`
(`dpkg -S /usr/bin/bandit`), which is why bandit resolves on `PATH` there and nothing else does.

**2. Even when installed, the output was discarded.** `generate-security-docs.sh` wrote
`safety check` output to `docs/security/temp/host_safety.txt` and `server_safety.txt`, and
`parse-security-to-html.py` never opened either file — it reads bandit JSON, npm audit JSON and
the Snyk SARIF files, and nothing else. `docs/security/temp/` is gitignored and the generator
deletes it on the way out, so the results were written, ignored and destroyed in one run.

Nobody noticed because failure (1) meant the step was skipped on every machine, and a skipped
step and a discarded result look identical from the outside: no card on the dashboard.

## Fix

Safety is **removed, not replaced**, and the coverage claim is removed with it. What is left is
`docs/security/README.md` saying plainly that Python dependency CVEs are not scanned — which is
what was true all along.

- `scripts/generate-security-docs.sh` — the tool check, the scan block and the two temp files are
  gone. The header comment now names what the script actually needs (bandit; optionally snyk).
- `backend_server/requirements.txt` — `safety>=3.0.0` dropped.
- `docs/security/README.md` — the two Safety rows are replaced by a **Not scanned** section that
  states the gap and why it is open.

### Why no replacement

`pip-audit` (PyPA, OSV feed, no account) was integrated and tested first: it works, takes ~80s
for both requirement files, and on its first run found four vulnerable packages — `pillow 10.4.0`
with 33 advisories, `aiohttp 3.12.15` with 64, `starlette 0.50.0` with 10, `click 8.1.8` with 1.
It was then backed out, because getting it onto the machine that runs the scan is the whole
problem and it is worse than it looks:

- the frontend VM has no virtualenv, so there is nothing to `pip install` into;
- Debian 12 refuses system-wide `pip install` (PEP 668, `externally-managed-environment`);
- there is no `python3-pip-audit` apt package on bookworm, so it cannot arrive the way bandit did.

That leaves pipx or a purpose-built venv plus a change to the systemd unit's `PATH` — more
machinery, on a production VM, than this dashboard justifies today. Backing out is a deliberate
choice to leave a **known, written-down** gap rather than a second mechanism that might quietly
become the next no-op.

The findings above are still real and are not addressed by this or any other commit.
`Pillow>=10.0.0,<11.0.0` in `backend_host/requirements.txt` is the clearest one: the fix is in
12.x, so our own ceiling is what holds 33 advisories open.

## Verification

Full generator run on 2026-09-17 — no Safety warning, no missing-tool noise, dashboard unchanged
apart from losing nothing (it never had a Python-dependency card to lose):

```
→ Checking security tools...
  ✓ Bandit available
→ Running Bandit security scans...
  ✓ Host scan complete   ✓ Server scan complete   ✓ Shared scan complete
→ Running npm audit for frontend...
  ✓ Frontend dependencies scanned
✓ Security documentation generated!
```

Header totals match the sum of the cards (0 high / 2 medium / 12 low), and `index.html` contains
no reference to a dependency scanner that does not run.

To check Python dependencies by hand, until something fills the gap:

```bash
pipx run pip-audit -r backend_host/requirements.txt
pipx run pip-audit -r backend_server/requirements.txt
```
