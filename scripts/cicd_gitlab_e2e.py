"""End-to-end check of features/gitlab/lib/gitlab_api.py against a live GitLab.

Needs a real instance and a PAT with `api` scope. From a host with no route to the GitLab,
tunnel it first — e.g. from the Mac:  ssh -f -N -L 8183:192.168.0.183:80 proxmox

    GITLAB_URL=http://127.0.0.1:8183 GITLAB_TOKEN=glpat-... \
        python3 scripts/cicd_gitlab_e2e.py

It creates/updates the `vpt-gitlab-e2e` project, commits a .gitlab-ci.yml, triggers a
pipeline, then reads pipelines, jobs and runners back through the connector.
"""
import json
import os
import sys
import time
import urllib.parse
import urllib.request

# Resolve the connector from the repo root so this runs from any working directory.
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, 'features/gitlab/lib'))
import gitlab_api as gl

TOKEN = os.environ['GITLAB_TOKEN']
# Three GitLab-19.4 traps encoded here, each hit and diagnosed during this build:
#   * no leading newline — the CI parser rejects a blank first line
#   * content sent RAW, never percent-encoded — encoding stores a file starting with '%',
#     which the parser reports as "non-alphabetical character while scanning a directive"
#   * `- exit 1`, not `- false` — unquoted false is a YAML boolean, and GitLab rejects the
#     script list ("should be a string or a nested array of strings")
CI_YML = """stages: [build, test]

probe:
  stage: build
  script:
    - echo "VPT orchestrator probe on $(hostname)"
    - test -f README.md

deliberate-failure:
  stage: test
  script:
    - echo "this job fails on purpose"
    - exit 1
"""


def api(method, path, body=None):
    """Raw API call for the setup steps the connector does not cover (create/commit)."""
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        f"{gl.API}/api/v4{path}", data=data, method=method,
        headers={'PRIVATE-TOKEN': TOKEN, 'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=30) as r:
        raw = r.read()
        return json.loads(raw) if raw else {}


def step(msg):
    print(f"\n--- {msg}", flush=True)


step("1. connectivity")
info = gl.version()
print("version:", info.get('version'), "revision:", (info.get('revision') or '')[:8])
assert info.get('version'), "no version returned"

step("2. who the token is")
me = gl.current_user()
print("user:", me.get('username'), "admin:", me.get('is_admin'))

step("3. create the project")
path = "vpt-gitlab-e2e"
projects = {p['path']: p for p in gl.projects(search='vpt-customer')}
proj = projects.get(path)
if proj:
    print("reusing existing project id", proj['id'])
else:
    proj = api('POST', '/projects', {
        # No parentheses: GitLab allows only letters, digits, '_', '.', '+', dashes, spaces.
        'name': 'VPT Customer Orchestrator Dev',
        'path': path,
        'visibility': 'private',
        'initialize_with_readme': True,
    })
    print("created project id", proj['id'])

pid = proj['id']
print("path_with_namespace:", proj['path_with_namespace'])

step("4. put a .gitlab-ci.yml in it")
files = api('GET', f'/projects/{pid}/repository/tree')
names = [f['name'] for f in files]
print("tree:", names)
if '.gitlab-ci.yml' not in names:
    action = 'create'
else:
    action = 'update'
body = json.dumps({
    'branch': 'main',
    'commit_message': 'set ci pipeline for connector test',
    'actions': [{
        'action': action,
        'file_path': '.gitlab-ci.yml',
        'content': CI_YML,
    }],
}).encode()
req = urllib.request.Request(
    f"{gl.API}/api/v4/projects/{pid}/repository/commits", data=body, method='POST',
    headers={'PRIVATE-TOKEN': TOKEN, 'Content-Type': 'application/json'})
with urllib.request.urlopen(req, timeout=30) as r:
    print("commit:", json.loads(r.read())['id'][:8])

step("5. branches")
print("branches:", gl.branches(pid))

step("6. trigger a pipeline through the connector")
# Bare ref: GitLab CE 19.4 rejects both variables[] and inputs[] here.
p = gl.trigger_pipeline(pid, 'main')
print("triggered pipeline", p.get('id'), "status", p.get('status'))

step("7. read pipelines back")
time.sleep(3)
runs = gl.pipeline_runs(pid, ref='main', per_page=5)
for r in runs:
    print(f"  pipeline {r['gitlab_pipeline_id']} ref={r['branch']} sha={r['sha']} "
          f"status={r['status']} conclusion={r['conclusion']}")
assert runs, "no pipelines came back"

step("8. read jobs through the connector")
jobs = gl.run_jobs(pid, p['id'])
for j in jobs:
    print(f"  job {j['name']:20s} stage={j['stage']:6s} status={j['status']:10s} "
          f"cicd={j['cicd_status']:8s} allow_failure={j['allow_failure']} url={j['html_url']}")
assert jobs, "no jobs came back"

step("9. in-progress view")
print("in_progress:", gl.in_progress_runs(pid))

step("10. runners visible to the instance")
for r in gl.runners(per_page=10):
    print(" ", r)

step("11. error path — a ref that does not exist")
try:
    gl.trigger_pipeline(pid, 'no-such-branch')
    print("UNEXPECTED: no error raised")
    sys.exit(1)
except gl.GitLabError as e:
    print("GitLabError:", e)
    assert 'Reference not found' in str(e), "expected GitLab's own reason in the message"

print("\nE2E OK")