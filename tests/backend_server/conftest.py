import os
import time

import pytest
import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def _truthy(value: str) -> bool:
    return value.lower() in {"1", "true", "yes", "on"}


def _normalize_server_base(url: str) -> str:
    normalized = url.rstrip("/")
    if normalized.endswith("/server"):
        normalized = normalized[:-7]
    return normalized


@pytest.fixture(scope="session")
def base_url() -> str:
    raw = os.environ.get("SERVER_URL", "http://localhost:5109")
    return _normalize_server_base(raw)


@pytest.fixture(scope="session")
def team_id() -> str:
    return os.environ.get("TEAM_ID", "00000000-0000-0000-0000-000000000001")


@pytest.fixture(scope="session")
def api_key() -> str:
    return os.environ.get("API_KEY", "")


@pytest.fixture(scope="session")
def auth_jwt() -> str:
    return os.environ.get("AUTH_TEST_JWT", "")


@pytest.fixture(scope="session")
def admin_jwt() -> str:
    """Admin-role token (admin.test@vpt.local), minted by scripts/setup_test_accounts.py."""
    return os.environ.get("ADMIN_TEST_JWT", "")


@pytest.fixture(scope="session")
def tester_jwt() -> str:
    """Tester-role token — used to prove admin-only routes reject a non-admin."""
    return os.environ.get("TESTER_TEST_JWT", "")


@pytest.fixture(scope="session")
def request_timeout() -> float:
    return float(os.environ.get("REQUEST_TIMEOUT_SECONDS", "20"))


@pytest.fixture(scope="session")
def verify_ssl() -> bool:
    return _truthy(os.environ.get("VERIFY_SSL", "false"))


@pytest.fixture(scope="session")
def api_headers(api_key: str) -> dict:
    headers = {
        "Content-Type": "application/json",
    }
    if api_key:
        headers["X-API-Key"] = api_key
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


CI_FIXTURE_TEAM_NAME = "__ci_fixture_team__"
CI_MUTATION_TARGET_EMAIL = "mutable.test@vpt.local"


@pytest.fixture(scope="session")
def ci_user_id(base_url: str, api_headers: dict, verify_ssl: bool, request_timeout: float) -> str:
    """The one account the suite is allowed to mutate.

    ~14 tests flip a user's role, rewrite their permissions or move them between teams.
    They used to pick `users[0]` or "the first non-admin", i.e. whichever REAL row happened
    to sort first — today that is a real person's account, and a test that dies mid-run
    leaves it with the wrong role. mutable.test@vpt.local exists only to be written to;
    login is banned and nothing authenticates as it (scripts/setup_test_accounts.py).
    """
    resp = requests.get(
        f"{base_url}/server/users", headers=api_headers,
        timeout=request_timeout, verify=verify_ssl,
    )
    if resp.status_code != 200:
        pytest.skip(f"Cannot list users ({resp.status_code}) — no mutation target available")
    match = next((u for u in resp.json() if u.get("email") == CI_MUTATION_TARGET_EMAIL), None)
    if not match:
        pytest.skip(
            f"{CI_MUTATION_TARGET_EMAIL} missing — run scripts/setup_test_accounts.py. "
            "Refusing to mutate a real account instead."
        )
    return match["id"]


@pytest.fixture(scope="session")
def ci_team_id(base_url: str, api_headers: dict, verify_ssl: bool, request_timeout: float) -> str:
    """A CI-owned team for membership writes, so the shared Default Team stays clean.

    Find-or-create by name rather than a hardcoded id, so a fresh database self-heals on
    the first run instead of needing a provisioning step.
    """
    listing = requests.get(
        f"{base_url}/server/teams", headers=api_headers,
        timeout=request_timeout, verify=verify_ssl,
    )
    if listing.status_code != 200:
        pytest.skip(f"Cannot list teams ({listing.status_code}) — no CI team available")
    teams = listing.json()
    teams = teams if isinstance(teams, list) else teams.get("teams", [])
    existing = next((t for t in teams if t.get("name") == CI_FIXTURE_TEAM_NAME), None)
    if existing:
        return existing["id"]

    created = requests.post(
        f"{base_url}/server/teams", headers=api_headers,
        json={"name": CI_FIXTURE_TEAM_NAME,
              "description": "CI-owned team. Tests add/remove members here. Not for real work."},
        timeout=request_timeout, verify=verify_ssl,
    )
    if created.status_code not in (200, 201):
        pytest.skip(f"Could not create {CI_FIXTURE_TEAM_NAME} ({created.status_code})")
    body = created.json()
    return (body.get("team") or body)["id"]


CI_FIXTURE_INTERFACE_NAME = "__ci_fixture_interface__"
CI_FIXTURE_NODE_LABEL = "home"


@pytest.fixture(scope="session")
def ci_userinterface(base_url: str, api_headers: dict, verify_ssl: bool,
                     request_timeout: float, team_id: str) -> str:
    """A CI-owned userinterface with a root navigation tree and one `home` node.

    test_quicktest saves a testcase whose graph navigates to `home`, and
    /server/testcase/save validates that label against the interface's tree. The fixture used
    to name `virtualpytest_web`, which exists only under the real team — so against the CI
    fixture team every save answered 400 "Graph validation failed" and six tests skipped
    themselves, on every run, forever.

    Find-or-create like ci_team_id, so a fresh database self-heals on the first run instead of
    needing a provisioning step. Assert rather than skip: if the platform cannot create an
    interface, a tree and a node, that is the regression, not a reason to stop asking.
    """
    def _req(method: str, path: str, **kwargs):
        return requests.request(
            method, f"{base_url}{path}", headers=api_headers,
            timeout=request_timeout, verify=verify_ssl, **kwargs,
        )

    listing = _req("GET", f"/server/userinterface/getAllUserInterfaces?team_id={team_id}")
    assert listing.status_code == 200, f"cannot list userinterfaces: {listing.text[:200]}"
    body = listing.json()
    interfaces = body if isinstance(body, list) else body.get("userinterfaces", [])
    existing = next((u for u in interfaces if u.get("name") == CI_FIXTURE_INTERFACE_NAME), None)
    if existing:
        interface_id = existing["id"]
    else:
        created = _req(
            "POST", f"/server/userinterface/createUserInterface?team_id={team_id}",
            json={"name": CI_FIXTURE_INTERFACE_NAME, "models": ["web"]},
        )
        assert created.status_code == 201, f"cannot create the CI userinterface: {created.text[:200]}"
        interface_id = created.json()["userinterface"]["id"]

    trees = _req("GET", f"/server/navigationTrees?team_id={team_id}")
    assert trees.status_code == 200, f"cannot list navigation trees: {trees.text[:200]}"
    root = next(
        (t for t in (trees.json().get("trees") or [])
         if t.get("userinterface_id") == interface_id and t.get("is_root_tree")),
        None,
    )
    if root:
        tree_id = root["id"]
    else:
        made = _req(
            "POST", f"/server/navigationTrees?team_id={team_id}",
            json={"name": f"{CI_FIXTURE_INTERFACE_NAME} root",
                  "userinterface_id": interface_id,
                  "is_root_tree": True,
                  "description": "CI fixture tree — created by tests/backend_server/conftest.py"},
        )
        assert made.status_code == 200 and made.json().get("success"), (
            f"cannot create the CI navigation tree: {made.text[:200]}")
        tree_id = made.json()["tree"]["id"]

    nodes = _req("GET", f"/server/navigationTrees/{tree_id}/nodes?team_id={team_id}")
    assert nodes.status_code == 200, f"cannot list tree nodes: {nodes.text[:200]}"
    nodes_body = nodes.json()
    node_list = nodes_body if isinstance(nodes_body, list) else (nodes_body.get("nodes") or [])
    if CI_FIXTURE_NODE_LABEL not in {n.get("label") for n in node_list}:
        node = _req(
            "POST", f"/server/navigationTrees/{tree_id}/nodes?team_id={team_id}",
            json={"node_id": CI_FIXTURE_NODE_LABEL, "label": CI_FIXTURE_NODE_LABEL,
                  "node_type": "screen", "position_x": 250, "position_y": 0,
                  "verifications": [], "data": {}},
        )
        assert node.status_code in (200, 201), f"cannot create the `home` node: {node.text[:200]}"

    return CI_FIXTURE_INTERFACE_NAME


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "unit: pure unit test — runs without a live backend server"
    )
    config.addinivalue_line(
        "markers",
        "device: tier-B black-box test — executes on the device host (host-clone-1), "
        "not just against the server API. Deselect with -m 'not device'.",
    )
    # One reason a test cannot run on every push. It used to be a permanent
    # `pytest.mark.skip`, which put a row saying "skipped" in every CI report forever and
    # made the test unrunnable even where it WOULD work. As a marker it is deselected in
    # CI (-m "not manual") and still runs on demand.
    #
    # `local_only` is gone as of 2026-09-16: the three route groups that carried it
    # (/api/events, /navigate, /docs/api) were unreachable because they were mounted
    # outside /server/*, which is the only prefix nginx proxies. That was a platform
    # defect wearing a marker — the events API was dead in production. The blueprints
    # moved under /server/*, and their 12 tests now run everywhere like any other.
    config.addinivalue_line(
        "markers",
        "manual: has a real external side effect (spends LLM credits, posts to Slack, "
        "restarts a service). Run deliberately: -m manual.",
    )


# pytest-html is optional. Declaring its hook unconditionally makes pytest abort collection
# with "unknown hook 'pytest_html_report_title'" wherever the plugin is absent — which is any
# machine that has not installed the CI extras (hit on vpt-pi1, 2026-09-07). Guard it so the
# suite runs anywhere `pytest` and `requests` exist, and still titles the report under CI.
try:  # pragma: no cover - trivial import guard
    import pytest_html as _pytest_html  # noqa: F401

    _HAS_PYTEST_HTML = True
except ImportError:  # pragma: no cover
    _HAS_PYTEST_HTML = False


if _HAS_PYTEST_HTML:
    def pytest_html_report_title(report):
        """pytest-html names the report after its file ("index.html"). CI sets
        CI_REPORT_TITLE to "<project> #<run> · <branch> · <sha> · <date>" so the
        page header carries the run identity instead (see regression.yml)."""
        title = os.environ.get("CI_REPORT_TITLE", "").strip()
        if title:
            report.title = title


@pytest.fixture(scope="session")
def _probe_server(base_url: str, verify_ssl: bool) -> None:
    """Probe the backend once per session; skip callers if unreachable."""
    probe_timeout = 5.0
    try:
        response = requests.get(
            f"{base_url}/server/health",
            timeout=probe_timeout,
            verify=verify_ssl,
        )
        # Also skip if server returns an error status (e.g., 502 Bad Gateway)
        if response.status_code >= 400:
            pytest.skip(
                f"Backend server at {base_url} returned {response.status_code} — skipping all backend_server tests."
            )
    # RequestException covers ConnectionError/Timeout/SSLError/etc. The old
    # explicit tuple referenced requests.exceptions.SSLVerificationError,
    # which doesn't exist — a latent AttributeError that only surfaced when
    # the server was actually unreachable.
    except requests.exceptions.RequestException:
        pytest.skip(
            f"Backend server at {base_url} is not reachable — skipping all backend_server tests."
        )


@pytest.fixture(autouse=True)
def require_server_reachable(request) -> None:
    """Skip server-dependent tests when the backend is not reachable.

    Tests marked @pytest.mark.unit run without a live server and bypass
    the probe entirely.
    """
    if request.node.get_closest_marker("unit"):
        return
    request.getfixturevalue("_probe_server")


@pytest.fixture(scope="session")
def system_health_reachable(base_url: str, verify_ssl: bool, api_headers: dict) -> bool:
    """Check if /server/system/health endpoint is reachable.

    This endpoint makes internal calls that may time out if the remote
    host (e.g. <origin-ip>) is unavailable. Returns True if reachable,
    False otherwise.
    """
    probe_timeout = 10.0
    try:
        response = requests.get(
            f"{base_url}/server/system/health",
            headers=api_headers,
            timeout=probe_timeout,
            verify=verify_ssl,
        )
        return response.status_code == 200
    # Same latent AttributeError _probe_server had: the explicit tuple named
    # requests.exceptions.SSLVerificationError, which doesn't exist (it is a
    # urllib3 name). Evaluating the tuple raised, so a probe that should have
    # skipped the two tests reported them as ERROR instead — and only when the
    # server was genuinely unreachable, i.e. exactly when the skip mattered.
    except requests.exceptions.RequestException:
        return False


_REDACTED_HEADERS = {"authorization", "x-api-key", "cookie"}


@pytest.fixture(autouse=True)
def _log_http_calls(monkeypatch):
    """Print every HTTP call a test makes so the pytest-html report shows it.

    pytest-html renders whatever a test writes to stdout under "Captured stdout call";
    without this every passed test read "No log output captured" (run #332), which made
    the report useless for seeing *what* a test actually asked the server. Hooks
    ``requests.Session.request`` so the ``get``/``post``/``delete`` fixtures and the ~460
    direct ``requests.get(...)`` calls are all covered without touching the tests.
    """
    original = requests.Session.request

    def logged(self, method, url, **kwargs):
        started = time.perf_counter()
        try:
            response = original(self, method, url, **kwargs)
        except Exception as exc:
            print(f"{method.upper()} {url} -> EXC {type(exc).__name__}: {exc}")
            raise
        elapsed_ms = (time.perf_counter() - started) * 1000
        params = kwargs.get("params") or {}
        headers = {k: v for k, v in (kwargs.get("headers") or {}).items()
                   if k.lower() not in _REDACTED_HEADERS}
        print(f"{method.upper()} {url} -> {response.status_code} ({elapsed_ms:.0f}ms)")
        if params:
            print(f"  params : {params}")
        if headers:
            print(f"  headers: {headers}")
        if kwargs.get("json") is not None:
            print(f"  json   : {str(kwargs['json'])[:500]}")
        body = (response.text or "").strip().replace("\n", " ")
        if body:
            print(f"  body   : {body[:500]}{'…' if len(body) > 500 else ''}")
        return response

    monkeypatch.setattr(requests.Session, "request", logged)


@pytest.fixture
def get(base_url: str, verify_ssl: bool, request_timeout: float):
    def _get(path: str, *, params: dict | None = None, headers: dict | None = None):
        return requests.get(
            f"{base_url}{path}",
            params=params,
            headers=headers,
            timeout=request_timeout,
            verify=verify_ssl,
        )

    return _get


@pytest.fixture
def post(base_url: str, verify_ssl: bool, request_timeout: float):
    def _post(path: str, *, json: dict | None = None, params: dict | None = None,
              headers: dict | None = None, timeout: float | None = None):
        return requests.post(
            f"{base_url}{path}",
            json=json,
            params=params,
            headers=headers,
            timeout=timeout or request_timeout,
            verify=verify_ssl,
        )

    return _post


@pytest.fixture
def delete(base_url: str, verify_ssl: bool, request_timeout: float):
    def _delete(path: str, *, params: dict | None = None, headers: dict | None = None):
        return requests.delete(
            f"{base_url}{path}",
            params=params,
            headers=headers,
            timeout=request_timeout,
            verify=verify_ssl,
        )

    return _delete


def assert_not_auth_failure(response, what: str) -> None:
    """Fail — never skip — when the server rejects our credentials.

    A 401/403 means the request was understood and refused: the API_KEY is missing, wrong
    or no longer accepted. That is a real failure and must be loud. Skipping on it turns a
    broken credential into a wall of green-ish "skipped", which is exactly what happened on
    2026-09-07 when /server/* was closed by default: 30 tests produced 16 skips, 14 errors
    and one genuine verdict, and a suite that reports mostly-skipped reads far healthier
    than it is.

    Callers may still skip on a genuinely absent environment (connection refused, 404, a
    feature that is not deployed) — that is a different thing from being turned away.
    """
    if response is not None and response.status_code in (401, 403):
        raise AssertionError(
            f"{what}: server returned {response.status_code} — credentials rejected. "
            f"Set API_KEY (CI passes it from secrets; /server/* is closed by default since "
            f"the 2026-09-07 auth hardening). Body: {response.text[:200]}"
        )


#: Everything these suites create is named with this prefix so it can be swept.
CI_FIXTURE_PREFIXES = ("zz-ci-", "zz_ci_")


@pytest.fixture(scope="session", autouse=True)
def _sweep_ci_fixtures(base_url, verify_ssl, request_timeout, team_id, api_headers):
    """Delete anything these suites created, after the whole session.

    Per-test teardown is the primary cleanup, but it does not run when a test is
    interrupted, when teardown itself errors, or when a run is killed — and two testcases
    did leak into the shared team that way on 2026-09-07. These tests write to a *shared*
    database that real people look at, so a best-effort sweep at session end is worth the
    few seconds. Never raises: failing to clean up must not fail the run.
    """
    yield

    endpoints = (
        ("/server/testcase/list", "testcases", "name", "testcase_id", "/server/testcase/{id}"),
        ("/server/virtual-script/list", "scripts", "name", "id", "/server/virtual-script/{id}"),
    )
    for path, key, name_key, id_key, delete_path in endpoints:
        try:
            listed = requests.get(f"{base_url}{path}", headers=api_headers,
                                  params={"team_id": team_id},
                                  timeout=request_timeout, verify=verify_ssl)
            if listed.status_code != 200:
                continue
            for row in listed.json().get(key) or []:
                name = str(row.get(name_key) or row.get("testcase_name") or "")
                if not name.startswith(CI_FIXTURE_PREFIXES):
                    continue
                row_id = row.get(id_key) or row.get("id")
                if not row_id:
                    continue
                requests.delete(f"{base_url}{delete_path.format(id=row_id)}",
                                headers=api_headers, params={"team_id": team_id},
                                timeout=request_timeout, verify=verify_ssl)
                print(f"[cleanup] removed leftover {name}")
        except Exception as exc:                      # noqa: BLE001 - cleanup must never fail a run
            print(f"[cleanup] sweep of {path} skipped: {exc}")


@pytest.fixture(scope="session")
def host_url() -> str:
    return os.environ.get("HOST_URL", "http://localhost:5108")


@pytest.fixture(scope="session")
def device_team_id(team_id: str) -> str:
    """The team the tier-B device tests run against.

    Tier A writes to the CI fixture team, whose interface (ci_userinterface) is a shell: one
    `home` node and no edges, enough to save a testcase and nothing more. A real execution has
    to resolve a navigable path, so it needs the team that owns the real navigation trees —
    verified 2026-09-16: tier B passes against the real team with DEVICE_USERINTERFACE=
    virtualpytest_web and fails against the CI team with "No path found from Entry to home".

    Defaults to team_id, so nothing changes until DEVICE_TEAM_ID is set.
    """
    return os.environ.get("DEVICE_TEAM_ID", "") or team_id


@pytest.fixture(scope="session")
def device_host() -> str:
    """Host that tier-B (device black-box) tests execute against.

    `host-clone-1` is VirtualPyTest's own device host; the sample-app-* hosts belong to the
    sample-app product's fleet — see docs/technical/FEATURES.md → "Testing a feature".
    """
    return os.environ.get("DEVICE_HOST", "host-clone-1")


@pytest.fixture(scope="session")
def device_id() -> str:
    return os.environ.get("DEVICE_ID", "host")


@pytest.fixture(scope="session")
def device_userinterface(request) -> str:
    """The userinterface the tier-B device tests navigate.

    Defaults to `virtualpytest_web`, which `host-clone-1` drives through Playwright. The
    same tests run against a real set-top box by pointing the three fixtures at it — both
    trees happen to expose a `home` node, so the graph needs no change:

        SERVER_URL=http://<rpi1>:5109 \
        DEVICE_HOST=vpt-pi1 DEVICE_ID=device3 DEVICE_USERINTERFACE=stb_tv \
        pytest tests/backend_server/test_quicktest.py -m device

    Verified on stb3 (IR remote) on 2026-09-07: navigated to `home`, verified against the
    tree's reference image, recorded success with a video and HTML report.

    With DEVICE_USERINTERFACE unset it falls back to the CI fixture interface rather than to
    a hardcoded `virtualpytest_web`, which exists only under the real team — naming it meant
    every tier-A quicktest test skipped itself against the CI fixture team. getfixturevalue
    defers the provisioning, so an explicit DEVICE_USERINTERFACE (a tier-B device run against
    a real tree) never creates anything.
    """
    override = os.environ.get("DEVICE_USERINTERFACE", "")
    if override:
        return override
    return request.getfixturevalue("ci_userinterface")
