# Security Reports

Automated security analysis for VirtualPyTest backend components.

## View Reports

**[📊 Security Dashboard](./index.html)** - Interactive HTML report

**Raw Data:**
- [Host Report (JSON)](./host-report.json) - Backend host Bandit scan results
- [Server Report (JSON)](./server-report.json) - Backend server Bandit scan results
- [Frontend Report (JSON)](./frontend-report.json) - Frontend npm audit results
- Snyk Code (SARIF) reports are generated only when the `snyk` CLI is logged in and are
  **not committed** (SARIF embeds source snippets, which once leaked API keys).

## Generate Reports

### Prerequisites

```bash
# Activate venv
source venv/bin/activate

# Install Python tools (included in backend_server/requirements.txt)
pip install bandit

# Install Snyk CLI (optional but recommended)
npm install -g snyk
snyk auth  # Login with free Snyk account
```

### Run

```bash
# From project root
bash scripts/generate-security-docs.sh
```

### Output

Files generated in `docs/security/`:
- `index.html` - Interactive HTML dashboard
- `host-report.json` - Backend host Bandit results  
- `server-report.json` - Backend server Bandit results
- `frontend-report.json` - Frontend npm audit results
- `snyk-host-report.json` - Backend host Snyk Code results (SARIF)
- `snyk-server-report.json` - Backend server Snyk Code results (SARIF)

## What It Scans

| Component | Tool | Checks |
|-----------|------|--------|
| **backend_host/src/** | Bandit | Python code vulnerabilities |
| **backend_server/src/** | Bandit | Python code vulnerabilities |
| **shared/src/** | Bandit | Python code vulnerabilities (DB layer, utils, portability) |
| **backend_host/src/** | Snyk Code | SAST (Path Traversal, CORS, etc.) |
| **backend_server/src/** | Snyk Code | SAST (Path Traversal, CORS, etc.) |
| **shared/src/** | Snyk Code | SAST (Path Traversal, CORS, etc.) |
| **frontend/** | npm audit | Dependency CVEs |

### Not scanned: Python dependency CVEs

`backend_host/requirements.txt` and `backend_server/requirements.txt` are **not** checked against
any vulnerability feed. This table used to claim they were, via Safety, and that was never true:
the tool was declared in a requirements file the build host does not install, and on a machine
that did have it the output went to a temp file no parser read and the run then deleted. The
warning it printed on every build was the only trace it ever left (BUG-0148).

Safety has been removed rather than repaired — it reports no severity, and 3.x is account-gated,
which does not belong in an unattended build. `pip-audit` was evaluated as a replacement and
**not adopted**: the frontend VM has no virtualenv, Debian 12 refuses system `pip` installs
(PEP 668), and there is no `python3-pip-audit` package — so it could only be installed through
pipx or a purpose-built venv, which is more machinery than this dashboard is worth right now.

The gap is real and known: **a vulnerable pinned dependency will not show up here.** Bandit scans
our own Python code, not what it imports; npm audit covers the frontend only. Until something
fills it, Python dependency CVEs are checked by hand, off this page.

## Triage policy (`bandit.yaml` + `.snyk`)

`bandit.yaml` (repo root, passed with `-c`) excludes test files and skips the rule classes that
describe how the system is built (subprocess orchestration, `/tmp` scratch paths, binding
0.0.0.0, `try/except: pass`). Each skip carries a one-line rationale in the file; everything
else (exec, chmod, hardcoded secrets, XML, missing timeouts…) still reports.

False positives are recorded in the repo-root `.snyk` file (Snyk policy format, one entry
per rule + file with a `reason`). It is applied twice: by the Snyk CLI on its own scans,
and by `scripts/parse-security-to-html.py`, which drops matching findings from the
dashboard and shows the count as "· N ignored" in the section header. Anything ignored
there is a deliberate decision, not a missing scan — review the reasons before extending it.

The dashboard header is the sum of every section (Bandit + Snyk Code + npm audit).

## Severity Levels

- 🔴 **HIGH** - Fix immediately
- 🟡 **MEDIUM** - Fix soon
- ⚪ **LOW** - Best practices

## Typical Workflow

```bash
# 1. Generate
bash scripts/generate-security-docs.sh

# 2. Review
open docs/security/index.html

# 3. Fix issues in code

# 4. Re-generate to verify
bash scripts/generate-security-docs.sh

# 5. Commit
git add docs/security/
git commit -m "chore: update security reports"
```

## Access

- **Local**: `docs/security/index.html`
- **Development**: `/docs/security/`
- **Production**: Served as static documentation

No frontend build needed - reports generated directly in docs!
