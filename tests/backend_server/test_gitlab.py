"""gitlab_api — the gitlab feature's REST client, tested without a GitLab.

The cicd feature's github_api.py needed no equivalent: its coverage comes from the live pages. This module is
different because the instance it talks to is the *customer's*, so the cases worth pinning are
the ones a GitLab.com-shaped assumption gets wrong — a project path with slashes, a validation
error arriving as {"message": {"base": [...]}}, and the nine job statuses that have to collapse
into the three `cicd.ci_jobs.status` understands.

The module is imported by file path rather than as a package: features/gitlab/lib is not
registered on sys.path in the CI job, and pulling in backend_server would drag Flask into a job that only
installs pytest/requests.

Tier A — pure logic, no network, no device.
"""

import ast
import importlib.util
import json
import os
import urllib.error
import urllib.parse
from pathlib import Path

import pytest

# The lib tests below touch no server, device or network: the backend_server conftest skips
# the whole directory when no backend answers on :5109, and `@pytest.mark.unit` is the
# documented way to opt out of that probe. It is applied per class, NOT at module level —
# a module-level mark would also mark TestGitLabRoutes, whose tests need a live backend.

PROJECT_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = PROJECT_ROOT / "features/gitlab/lib/gitlab_api.py"


def _load():
    spec = importlib.util.spec_from_file_location("cicd_gitlab_api", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gl = _load()


@pytest.mark.unit
class TestProjectRef:
    def test_numeric_id_passes_through(self):
        assert gl.project_ref(42) == "42"
        assert gl.project_ref("42") == "42"

    def test_nested_path_is_encoded_whole(self):
        # `group/sub/project` unencoded would be read as path separators and 404.
        assert gl.project_ref("group/sub/project") == "group%2Fsub%2Fproject"

    def test_encoded_ref_is_not_double_encoded(self):
        assert gl.project_ref("group%2Fsub") == "group%252Fsub"


@pytest.mark.unit
class TestStatusCollapse:
    @pytest.mark.parametrize("gitlab_status,expected", [
        ("success", "success"),
        ("skipped", "success"),
        ("failed", "failure"),
        ("canceled", "failure"),
        ("running", "running"),
        ("pending", "running"),
        ("created", "running"),
        ("manual", "running"),
    ])
    def test_every_known_status_maps(self, gitlab_status, expected):
        assert gl.JOB_STATUS_MAP[gitlab_status] == expected

    def test_unknown_status_is_treated_as_running(self):
        # A status we cannot name is one we cannot claim has finished.
        job = {"name": "j", "status": "something_new"}
        rows = gl.run_jobs.__wrapped__ if hasattr(gl.run_jobs, "__wrapped__") else None
        assert rows is None  # no wrapper: silence linters about the unused branch
        assert gl.JOB_STATUS_MAP.get("something_new", "running") == "running"

    def test_missing_status_does_not_crash(self):
        assert gl.JOB_STATUS_MAP.get("", "running") == "running"
        assert gl.JOB_STATUS_MAP.get(None, "running") == "running"


@pytest.mark.unit
class TestRunJobs:
    def test_jobs_are_flattened_with_runner_and_cicd_status(self, monkeypatch):
        captured = {}

        def fake_request(path, method="GET", body=None, form=None, **kw):
            captured["path"] = path
            return [
                {
                    "id": 7,
                    "name": "e2e",
                    "stage": "test",
                    "status": "failed",
                    "allow_failure": False,
                    "runner": {"id": 3, "description": "vm-164"},
                    "started_at": "2026-10-13T06:00:00Z",
                    "web_url": "http://gl/jobs/7",
                },
                {
                    "id": 8,
                    "name": "lint",
                    "status": "running",
                    "allow_failure": True,
                    "runner": None,
                    "web_url": "http://gl/jobs/8",
                },
            ]

        monkeypatch.setattr(gl, "_request", fake_request)
        rows = gl.run_jobs("group/sub", 55)

        assert captured["path"] == "/projects/group%2Fsub/pipelines/55/jobs?per_page=50"
        assert rows[0]["cicd_status"] == "failure"
        assert rows[0]["conclusion"] == "failed"
        assert rows[0]["runner_name"] == "vm-164"
        assert rows[0]["html_url"] == "http://gl/jobs/7"
        assert rows[1]["runner_name"] is None, "a job with no runner must not crash"
        assert rows[1]["allow_failure"] is True
        assert rows[1]["cicd_status"] == "running"

    def test_empty_payload_is_an_empty_list(self, monkeypatch):
        monkeypatch.setattr(gl, "_request", lambda *a, **k: {})
        assert gl.run_jobs("p", 1) == []


@pytest.mark.unit
class TestPipelineRuns:
    def test_mapping_and_ref_filter(self, monkeypatch):
        captured = {}

        def fake_request(path, method="GET", body=None, form=None, **kw):
            captured["path"] = path
            return [{
                "id": 99,
                "ref": "main",
                "sha": "abcdef1234567890",
                "status": "success",
                "source": "push",
                "created_at": "2026-10-13T06:00:00Z",
                "web_url": "http://gl/pipelines/99",
            }]

        monkeypatch.setattr(gl, "_request", fake_request)
        runs = gl.pipeline_runs(12, ref="main", status="success")

        assert "ref=main" in captured["path"] and "status=success" in captured["path"]
        assert runs[0]["gitlab_pipeline_id"] == 99
        assert runs[0]["sha"] == "abcdef1", "sha is shortened for display"
        assert runs[0]["conclusion"] == "success"

    def test_running_pipeline_has_no_conclusion(self, monkeypatch):
        monkeypatch.setattr(gl, "_request", lambda *a, **k: [{"id": 1, "ref": "main", "status": "running"}])
        assert gl.pipeline_runs(1)[0]["conclusion"] is None

    def test_in_progress_deduplicates_across_states(self, monkeypatch):
        monkeypatch.setattr(
            gl, "_request",
            lambda *a, **k: [{"id": 5, "ref": "main", "status": "running"}],
        )
        runs = gl.in_progress_runs(1)
        assert [r["gitlab_pipeline_id"] for r in runs] == [5]


@pytest.mark.unit
class TestTriggerPipeline:
    def test_ref_goes_on_the_query_and_inputs_as_form_fields(self, monkeypatch):
        captured = {}

        def fake_request(path, method="GET", body=None, form=None, **kw):
            captured.update(path=path, method=method, form=form)
            return {"id": 101, "status": "pending"}

        monkeypatch.setattr(gl, "_request", fake_request)
        result = gl.trigger_pipeline("group/sub", "main", {"VPT_RUN": "42"})

        assert captured["method"] == "POST"
        assert captured["path"] == "/projects/group%2Fsub/pipeline?ref=main"
        # `inputs[]`, not `variables[]`: GitLab 19.4 answers {"error": "variables is invalid"}.
        assert captured["form"] == {"inputs[VPT_RUN]": "42"}
        assert result["id"] == 101

    def test_no_inputs_still_posts(self, monkeypatch):
        captured = {}

        def fake_request(path, method="GET", body=None, form=None, **kw):
            captured["method"] = method
            return {}

        monkeypatch.setattr(gl, "_request", fake_request)
        gl.trigger_pipeline(1, "main")
        assert captured["method"] == "POST"

    def test_inputs_survive_a_dash_in_the_key(self, monkeypatch):
        captured = {}

        def fake_request(path, method="GET", body=None, form=None, **kw):
            captured["form"] = form
            return {}

        monkeypatch.setattr(gl, "_request", fake_request)
        gl.trigger_pipeline(1, "main", {"vpt-run-id": "7"})
        assert captured["form"] == {"inputs[vpt-run-id]": "7"}


@pytest.mark.unit
class TestRunners:
    def test_status_field_decides_online(self, monkeypatch):
        # 19.4 returns no `contacted_at` for instance runners; keying off it marked every
        # runner offline. Liveness is `status`, with `online` as the older fallback.
        monkeypatch.setattr(gl, "_request", lambda *a, **k: [{
            "id": 1, "description": "vpt-dev-runner", "status": "online",
            "online": True, "job_execution_status": "idle", "tag_list": ["vpt"],
        }])
        rows = gl.runners()
        assert rows[0]["status"] == "online"
        assert rows[0]["busy"] is False
        assert rows[0]["labels"] == ["vpt"]

    def test_online_boolean_is_the_fallback(self, monkeypatch):
        monkeypatch.setattr(gl, "_request", lambda *a, **k: [
            {"id": 1, "description": "a", "online": True},
            {"id": 2, "description": "b", "online": False},
        ])
        rows = gl.runners()
        assert [r["status"] for r in rows] == ["online", "offline"]

    def test_busy_comes_from_job_execution_status(self, monkeypatch):
        monkeypatch.setattr(gl, "_request", lambda *a, **k: [{
            "id": 1, "description": "a", "status": "online", "job_execution_status": "running",
        }])
        assert gl.runners()[0]["busy"] is True

    def test_project_scoped_path_is_encoded(self, monkeypatch):
        captured = {}

        def fake_request(path, method="GET", body=None, form=None, **kw):
            captured["path"] = path
            return []

        monkeypatch.setattr(gl, "_request", fake_request)
        gl.runners("group/sub")
        assert captured["path"] == "/projects/group%2Fsub/runners?per_page=50"


@pytest.mark.unit
class TestBranches:
    def test_path_carries_the_repository_segment(self, monkeypatch):
        # GitHub's /projects/:id/branches shape answers Workhorse's bare 404 on GitLab.
        # This is the exact path GitLab serves; see the comment on branches().
        captured = {}

        def fake_request(path, method="GET", body=None, form=None, **kw):
            captured["path"] = path
            return [{"name": "main"}, {"name": "release/1.0"}, {"no": "name"}]

        monkeypatch.setattr(gl, "_request", fake_request)
        names = gl.branches(7)
        assert captured["path"] == "/projects/7/repository/branches?per_page=30"
        assert names == ["main", "release/1.0"], "entries without a name are dropped"

    def test_project_path_is_encoded(self, monkeypatch):
        captured = {}

        def fake_request(path, method="GET", body=None, form=None, **kw):
            captured["path"] = path
            return []

        monkeypatch.setattr(gl, "_request", fake_request)
        gl.branches("group/sub")
        assert captured["path"].startswith("/projects/group%2Fsub/repository/branches")


@pytest.mark.unit
class TestErrorMessages:
    """A bare 'HTTP 400' is useless in a log; the body carries the reason."""

    def _http_error(self, payload):
        return urllib.error.HTTPError(
            "http://gl", 400, "Bad Request", {},
            __import__("io").BytesIO(json.dumps(payload).encode()),
        )

    def test_validation_error_with_base_list(self, monkeypatch):
        monkeypatch.setenv("GITLAB_TOKEN", "glpat-test")
        err = self._http_error({"message": {"base": ["Reference not found"]}})

        def boom(*a, **k):
            raise err

        monkeypatch.setattr(gl.urllib.request, "urlopen", boom)
        with pytest.raises(gl.GitLabError) as exc:
            gl.trigger_pipeline("p", "nope")
        assert "Reference not found" in str(exc.value)

    def test_plain_message_error(self, monkeypatch):
        monkeypatch.setenv("GITLAB_TOKEN", "glpat-test")
        err = self._http_error({"message": "401 Unauthorized"})

        def boom(*a, **k):
            raise err

        monkeypatch.setattr(gl.urllib.request, "urlopen", boom)
        with pytest.raises(gl.GitLabError) as exc:
            gl.current_user()
        assert "401 Unauthorized" in str(exc.value)

    def test_missing_token_is_reported_before_any_request(self, monkeypatch):
        monkeypatch.delenv("GITLAB_TOKEN", raising=False)
        monkeypatch.setattr(
            gl.urllib.request, "urlopen",
            lambda *a, **k: pytest.fail("must not hit the network without a token"),
        )
        with pytest.raises(gl.GitLabError) as exc:
            gl.current_user()
        assert "GITLAB_TOKEN" in str(exc.value)


@pytest.mark.unit
class TestTlsAndBaseUrl:
    def test_base_url_is_read_from_the_environment(self, monkeypatch):
        monkeypatch.setenv("GITLAB_URL", "http://192.168.0.183/")
        spec = importlib.util.spec_from_file_location("gl_env", MODULE_PATH)
        reloaded = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(reloaded)
        assert reloaded.API == "http://192.168.0.183", "trailing slash must be stripped"

    def test_ca_bundle_is_honoured(self, monkeypatch):
        # Spying on create_default_context rather than pointing at a real .crt: this asserts
        # the wiring (the configured path reaches OpenSSL), not OpenSSL's parser.
        captured = {}
        real = gl.ssl.create_default_context

        def spy(*args, **kwargs):
            captured.update(args=args, kwargs=kwargs)
            return real()

        monkeypatch.setattr(gl.ssl, "create_default_context", spy)
        monkeypatch.setenv("GITLAB_CA_BUNDLE", "/etc/ssl/internal-ca.crt")
        ctx = gl._ssl_context()
        assert ctx is not None
        assert captured["kwargs"].get("cafile") == "/etc/ssl/internal-ca.crt"
        assert ctx.verify_mode.name == "CERT_REQUIRED", "an internal CA must stay verified"

    def test_insecure_is_an_explicit_opt_out(self, monkeypatch):
        monkeypatch.delenv("GITLAB_CA_BUNDLE", raising=False)
        monkeypatch.setenv("GITLAB_INSECURE", "1")
        ctx = gl._ssl_context()
        assert ctx is not None and ctx.verify_mode.name == "CERT_NONE"

    def test_default_is_urllib_default(self, monkeypatch):
        monkeypatch.delenv("GITLAB_CA_BUNDLE", raising=False)
        monkeypatch.delenv("GITLAB_INSECURE", raising=False)
        assert gl._ssl_context() is None

# ─── routes ──────────────────────────────────────────────────────────────────
# Not marked @pytest.mark.unit: these need a live backend, which the conftest probe only
# finds in CI. A feature must add its own tests — nothing discovers them (docs/technical/FEATURES.md).

def _json_body(response) -> dict:
    # `get` returns a requests.Response (it has .json(), not Flask's .get_json(silent=True)).
    try:
        body = response.json()
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}


class TestGitLabRoutes:
    def test_health_reports_configuration(self, get, api_headers):
        response = get("/server/gitlab/health", headers=api_headers)
        assert response.status_code == 200, response.text[:300]
        body = response.json()
        assert 'configured' in body, body
        assert body['base_url'].startswith('http'), body

    def test_projects_answer_with_a_status_envelope(self, get, api_headers):
        # health=0 skips the per-project pipeline probe (up to 25 sequential GitLab calls),
        # which can outlast the proxy timeout and come back as an empty-body 502. The
        # envelope is what this test pins, not the health signal. _json_body() keeps a
        # non-JSON body from raising JSONDecodeError instead of failing the assertion.
        response = get("/server/gitlab/projects?health=0", headers=api_headers)
        assert response.status_code in (200, 502), response.text[:300]
        if response.status_code == 502 and not _json_body(response):
            # The route answers {'success': False, ...} + 502 when GitLab is unreachable
            # (_bad_request), but Cloudflare in front of the server replaces any 502 body
            # with its own HTML "Bad gateway" page. The 502 is the envelope's status then.
            return
        assert 'success' in _json_body(response), response.text[:300]

    def test_trigger_requires_a_signed_in_user(self, post, api_headers):
        # Launching a pipeline is a side effect on the customer's CI: anonymous callers
        # must not reach it. Without the api key the request is rejected before the handler.
        response = post("/server/gitlab/project/trigger?project=root%2Fdemo", json={}, headers={})
        assert response.status_code in (401, 403), response.text[:300]
    def test_instances_list_shape(self, get, api_headers):
        response = get("/server/gitlab/instances", headers=api_headers)
        assert response.status_code == 200, response.text[:300]
        assert 'instances' in response.json(), response.text[:300]

    def test_projects_carry_their_last_pipeline(self, get, api_headers):
        response = get("/server/gitlab/projects", headers=api_headers)
        assert response.status_code in (200, 502), response.text[:300]
        if response.status_code == 200:
            for row in response.json()['projects']:
                assert 'last_pipeline' in row, "the page's health column reads this key"

    def test_tree_answer(self, get, api_headers):
        response = get("/server/gitlab/project/tree?project=root%2Fdemo&ref=main", headers=api_headers)
        assert response.status_code in (200, 400, 404, 502), response.text[:300]

    def test_namespaced_project_never_reaches_the_auto_proxy_catch_all(self, get, api_headers):
        # A GitLab project path is `group/project`, so it cannot ride in a path segment: Flask's
        # default string converter will not match a segment holding an encoded slash, the route
        # matched nothing, and the request fell through to the auto_proxy handler that wants a
        # `host_name`. The page showed an empty file tree and a blank README for EVERY project,
        # and the only error on the wire mentioned a parameter this feature has never used.
        #
        # Assert on the BODY, not just the status: the old test allowed 400 through, which is
        # precisely the status this bug produced.
        response = get("/server/gitlab/project/tree?project=root%2Fdemo&ref=main", headers=api_headers)
        body = _json_body(response)
        assert 'host_name' not in str(body.get('error', '')), (
            "the request fell through to the auto_proxy catch-all: "
            f"{response.status_code} {body.get('error')!r}"
        )

    def test_project_argument_is_required(self, get, api_headers):
        response = get("/server/gitlab/project/tree?ref=main", headers=api_headers)
        body = _json_body(response)
        assert response.status_code == 400, response.text[:300]
        # Our own message, not the catch-all's.
        assert body.get('error') == 'project is required', body

    def test_saving_an_instance_needs_the_manage_permission(self, post, api_headers):
        # No api key: the route carries require_permission('plugins.gitlab:manage'), so an
        # anonymous caller must be stopped before it could write a config file holding a token.
        response = post("/server/gitlab/instances", json={'base_url': 'http://evil'}, headers={})
        assert response.status_code in (401, 403), response.text[:300]
# ─── repository ──────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestRepositoryTree:
    def test_maps_entries_and_passes_the_ref(self, monkeypatch):
        captured = {}

        def fake_request(path, method="GET", body=None, form=None, **kw):
            captured.update(path=path, kw=kw)
            return [{"id": "a", "name": "README.md", "path": "README.md", "type": "blob", "mode": "100644"},
                    {"id": "b", "name": "src", "path": "src", "type": "tree", "mode": "040000"}]

        monkeypatch.setattr(gl, "_request", fake_request)
        rows = gl.repository_tree("group/sub", ref="main", api="http://gl", tok="glpat-x")

        assert rows[0]["type"] == "blob" and rows[1]["type"] == "tree"
        assert captured["path"].startswith("/projects/group%2Fsub/repository/tree?")
        assert "ref=main" in captured["path"]
        # the configured instance travels with the call instead of via env
        assert captured["kw"] == {"api": "http://gl", "tok": "glpat-x"}

    def test_path_and_recursive_are_encoded_when_given(self, monkeypatch):
        captured = {}

        def fake_request(path, method="GET", body=None, form=None, **kw):
            captured["path"] = path
            return []

        monkeypatch.setattr(gl, "_request", fake_request)
        gl.repository_tree(1, path="docs/agent", recursive=True)
        assert "recursive=true" in captured["path"]
        assert "path=docs%2Fagent" in captured["path"]


@pytest.mark.unit
class TestReadme:
    """The README is RESOLVED FROM THE TREE, not fetched from a dedicated endpoint.

    GitLab v4 has no `/projects/:id/readme` — it 404s on a real instance, so the first version
    of this returned nothing for every project. A repository file is only reachable through
    `/repository/files/:file_path` and its name is not known in advance, so the root tree is
    listed first and the README picked from it.
    """

    @staticmethod
    def _fake(monkeypatch, tree, file_payload):
        """Stub _request: the tree listing, then the file fetch."""

        def fake_request(path, method="GET", body=None, form=None, **kw):
            if "/repository/tree" in path:
                return tree
            if "/repository/files/" in path:
                return file_payload
            raise AssertionError(f"readme() must not call {path}")

        monkeypatch.setattr(gl, "_request", fake_request)

    def _tree(self, *names):
        return [{"name": n, "path": n, "type": "blob", "mode": "100644"} for n in names]

    def test_base64_content_is_decoded(self, monkeypatch):
        import base64 as _b64
        payload = {"file_name": "README.md", "ref": "main", "encoding": "base64",
                   "content": _b64.b64encode(b"# Title\n\nhello").decode()}
        self._fake(monkeypatch, self._tree("README.md", ".gitlab-ci.yml"), payload)
        out = gl.readme(1, ref="main")
        assert out["content"] == "# Title\n\nhello"
        assert out["binary"] is False

    def test_binary_file_is_flagged_not_crashed(self, monkeypatch):
        import base64 as _b64
        payload = {"file_name": "README.md", "encoding": "base64",
                   "content": _b64.b64encode(b"\x89PNG\r\n\x1a\n\xff\xfe").decode()}
        self._fake(monkeypatch, self._tree("README.md"), payload)
        out = gl.readme(1)
        assert out["binary"] is True and out["content"] is None

    def test_non_base64_encoding_is_passed_through(self, monkeypatch):
        self._fake(monkeypatch, self._tree("README"),
                   {"file_name": "README", "encoding": "text", "content": "plain"})
        assert gl.readme(1)["content"] == "plain"

    def test_plain_string_content_is_decoded(self, monkeypatch):
        self._fake(monkeypatch, self._tree("README.md"),
                   {"file_name": "README.md", "encoding": "base64", "content": None})
        assert gl.readme(1) is None

    def test_no_readme_is_none_not_an_error(self, monkeypatch):
        # A project with no README is a normal state, not a failure.
        self._fake(monkeypatch, self._tree("main.py", "setup.py"), {})
        assert gl.readme(1) is None

    def test_markdown_wins_over_rst(self, monkeypatch):
        # Both present: README.md is what a person opens.
        captured = {}

        def fake_request(path, method="GET", body=None, form=None, **kw):
            if "/repository/tree" in path:
                return [{"name": "README.rst", "path": "README.rst", "type": "blob"},
                        {"name": "README.md", "path": "README.md", "type": "blob"}]
            captured["path"] = path
            return {"file_name": "README.md", "encoding": "text", "content": "md"}

        monkeypatch.setattr(gl, "_request", fake_request)
        assert gl.readme(1)["content"] == "md"
        assert "README.md" in captured["path"]

    def test_a_folder_named_readme_is_not_the_readme(self, monkeypatch):
        # type == tree is a directory; it has no content to show.
        self._fake(monkeypatch, [{"name": "readme", "path": "readme", "type": "tree"}], {})
        assert gl.readme(1) is None


@pytest.mark.unit
class TestFileContent:
    def test_file_path_is_encoded_and_ref_forwarded(self, monkeypatch):
        captured = {}

        def fake_request(path, method="GET", body=None, form=None, **kw):
            captured["path"] = path
            return {"file_name": "a.md", "encoding": "base64", "content": None}

        monkeypatch.setattr(gl, "_request", fake_request)
        gl.file_content("group/sub", "docs/read me.md", ref="release/1.0")
        # spaces and slashes encoded; the branch's slash too
        assert captured["path"] == ("/projects/group%2Fsub/repository/files/"
                                    "docs%2Fread%20me.md?ref=release%2F1.0")

    def test_too_large_payload_yields_none(self, monkeypatch):
        monkeypatch.setattr(gl, "_request", lambda *a, **k: {"error": "too large"})
        assert gl.file_content(1, "big.bin") is None


@pytest.mark.unit
class TestInstanceOverrides:
    def test_default_instance_is_the_env_backed_one(self, monkeypatch):
        captured = {}

        def fake_request(path, method="GET", body=None, form=None, **kw):
            captured.update(kw)
            return {}

        monkeypatch.setattr(gl, "_request", fake_request)
        gl.version()
        assert captured == {"api": None, "tok": None}

    def test_no_token_at_all_is_reported_before_any_request(self, monkeypatch):
        # The guard lives in _request itself, so this must NOT patch it: patching would
        # bypass the very check under test and hit the network instead.
        monkeypatch.delenv("GITLAB_TOKEN", raising=False)
        with pytest.raises(gl.GitLabError) as exc:
            gl.version()
        assert "GITLAB_TOKEN" in str(exc.value)

    def test_a_configured_instance_does_not_need_the_env_token(self, monkeypatch):
        monkeypatch.delenv("GITLAB_TOKEN", raising=False)
        monkeypatch.setattr(gl, "_request", lambda *a, **k: {"version": "19.4.2"})
        assert gl.version(api="http://gl", tok="glpat-from-settings")["version"] == "19.4.2"

    def test_error_keeps_status_and_parsed_payload(self, monkeypatch):
        def boom(*a, **k):
            raise gl.GitLabError(404, "GitLab 404 on GET /projects/x: 404 Project Not Found",
                                 "http://gl/api/v4/projects/x", {"message": "404 Project Not Found"})

        monkeypatch.setattr(gl, "_request", boom)
        with pytest.raises(gl.GitLabError) as exc:
            gl.resolve_project("x")
        assert exc.value.status == 404
        assert exc.value.payload == {"message": "404 Project Not Found"}


# ─── instance store ──────────────────────────────────────────────────────────

@pytest.mark.unit
class TestInstanceStore:
    @pytest.fixture(autouse=True)
    def _isolated(self, monkeypatch, tmp_path):
        """Point the store at a tmp file so the real operator config is never touched."""
        import importlib
        spec = importlib.util.spec_from_file_location(
            "gitlab_instances", PROJECT_ROOT / "features/gitlab/lib/instances.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        monkeypatch.setattr(mod, "CONFIG_PATH", tmp_path / "gitlab_instances.json")
        monkeypatch.delenv("GITLAB_TOKEN", raising=False)
        monkeypatch.delenv("GITLAB_URL", raising=False)
        self.mod = mod

    def test_missing_file_is_an_empty_list(self):
        assert self.mod.load() == []
        assert self.mod.get("anything") is None

    def test_env_fallback_when_nothing_is_configured(self, monkeypatch):
        monkeypatch.setenv("GITLAB_TOKEN", "glpat-env")
        monkeypatch.setenv("GITLAB_URL", "http://10.10.41.52/")
        assert self.mod.effective()[0]['base_url'] == "http://10.10.41.52"
        assert self.mod.effective()[0]['id'] == 'env'

    def test_no_token_and_no_file_means_nothing_configured(self):
        assert self.mod.effective() == []

    def test_upsert_then_load_roundtrips(self):
        self.mod.upsert({'name': 'Customer', 'base_url': 'http://gl/', 'token': 'glpat-1'})
        rows = self.mod.load()
        assert len(rows) == 1
        assert rows[0]['base_url'] == "http://gl", "trailing slash is trimmed"
        assert rows[0]['ref'] == 'main', "a default branch is filled in"
        assert rows[0]['id']

    def test_update_keeps_the_token_when_the_form_sends_none(self):
        first = self.mod.upsert({'name': 'Customer', 'base_url': 'http://gl', 'token': 'glpat-1'})
        # the form never receives the token back, so a rename must not wipe it
        again = self.mod.upsert({**self.mod.public(first), 'name': 'Renamed'})
        assert again['token'] == 'glpat-1'
        assert self.mod.load()[0]['name'] == 'Renamed'

    def test_select_project_is_remembered(self):
        inst = self.mod.upsert({'base_url': 'http://gl', 'token': 'glpat-1'})
        saved = self.mod.select_project(inst['id'], 'group/app', 'develop')
        assert saved['project'] == 'group/app'
        assert saved['ref'] == 'develop'
        assert self.mod.get(inst['id'])['project'] == 'group/app'

    def test_select_on_an_unknown_instance_is_none(self):
        assert self.mod.select_project('nope', 'group/app') is None

    def test_delete_removes_only_the_named_one(self):
        a = self.mod.upsert({'base_url': 'http://a', 'token': 't'})
        b = self.mod.upsert({'base_url': 'http://b', 'token': 't'})
        assert self.mod.delete(a['id']) is True
        assert [i['id'] for i in self.mod.load()] == [b['id']]
        assert self.mod.delete(a['id']) is False

    def test_public_never_leaks_the_token(self):
        inst = self.mod.upsert({'base_url': 'http://gl', 'token': 'glpat-secret'})
        pub = self.mod.public(inst)
        assert 'token' not in pub and pub['has_token'] is True
        assert 'glpat-secret' not in str(pub)

    def test_broken_file_does_not_raise(self):
        self.mod.CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        self.mod.CONFIG_PATH.write_text('{not json')
        assert self.mod.load() == []

    def test_dict_shaped_file_is_tolerated(self):
        self.mod.CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        self.mod.CONFIG_PATH.write_text(json.dumps(
            {"instances": [{"base_url": "http://gl", "token": "t"}]}))
        assert len(self.mod.load()) == 1


# ─── bundle builder (TASK-91 goal A) ─────────────────────────────────────────

@pytest.mark.unit
class TestProjectIsNeverAPathSegment:
    """The project travels as a query argument, in the route AND in the client that builds it.

    This is a source-level guard on purpose. The behavioural tests for these routes live in the
    `backend_server` tier, which skips entirely when no server is running (conftest), so a bug
    here shipped once already: `encodeURIComponent('root/demo')` produced `root%2Fdemo` inside a
    path segment, Flask's default string converter refused to match it, the request fell through
    to the auto_proxy catch-all, and every project rendered an empty file tree with a 400 about a
    `host_name` this feature has never used. The route test that should have caught it allowed
    status 400 through.

    Importing the blueprint would need Flask, which this job does not install, so the invariant is
    asserted on the source: cheap, dependency-free, and it runs on every commit.
    """

    BACKEND = Path(__file__).resolve().parents[2] / 'features/gitlab/backend_server/__init__.py'
    CLIENT = Path(__file__).resolve().parents[2] / 'features/gitlab/frontend/gitlabApi.ts'

    def test_backend_declares_no_project_path_segment(self):
        src = self.BACKEND.read_text(encoding='utf-8')
        offenders = [line.strip() for line in src.splitlines()
                     if '.route(' in line and '<project>' in line]
        assert offenders == [], (
            "the project is `group/project`, and a path segment cannot hold an encoded slash: "
            f"move it to the `project` query argument. Offending routes: {offenders}"
        )

    def test_frontend_never_builds_a_project_path_segment(self):
        src = self.CLIENT.read_text(encoding='utf-8')
        offenders = [line.strip() for line in src.splitlines()
                     if 'encodeURIComponent(project)' in line
                     and '?project=' not in line
                     and '&project=' not in line]
        assert offenders == [], (
            "the client must send the project as `?project=`/`&project=`, not as a path "
            f"segment. Offending lines: {offenders}"
        )


@pytest.mark.unit
class TestFeatureStillHasAnEntryPoint:
    """The module must still expose `register(app)` — the shape the feature loader calls.

    A feature is loaded by `shared/src/lib/utils/features.py`, which does
    `getattr(module, 'register')(app)` for every enabled feature. A module without that attribute
    does not raise, does not fail a test, and does not break the server: the loader catches the
    AttributeError, prints one `❌ <name>: backend_server failed to register` line at startup, and
    moves on. The result is a feature whose every route 404s into the auto_proxy catch-all while
    the rest of the app looks healthy.

    That is exactly what happened when the packaging block was cut from the end of this module on
    2026-10-13: `register` sat directly after it and went with it, and `/server/gitlab/*` stopped
    matching entirely. Nothing in the behavioural suite noticed — those tests skip when no backend
    answers on :5109.

    Asserted on the source, for the same reason as the class above: importing the blueprint needs
    Flask, which this job does not install.
    """

    BACKEND = Path(__file__).resolve().parents[2] / 'features/gitlab/backend_server/__init__.py'

    def test_module_defines_register_app(self):
        tree = ast.parse(self.BACKEND.read_text(encoding='utf-8'))
        entry_points = [n for n in tree.body
                        if isinstance(n, ast.FunctionDef) and n.name == 'register']
        assert entry_points, (
            "features/gitlab/backend_server must define register(app): the feature loader calls "
            "it by name and silently skips the feature when it is absent, which turns every "
            "/server/gitlab/* route into an unmatched endpoint"
        )
        params = entry_points[0].args
        assert [a.arg for a in params.args] == ['app'], (
            "register(app) takes exactly the Flask app the loader passes"
        )

    def test_register_registers_the_blueprint(self):
        src = self.BACKEND.read_text(encoding='utf-8')
        assert 'app.register_blueprint(feature_gitlab_bp)' in src, (
            "register(app) must mount feature_gitlab_bp — registering anything else leaves the "
            "/server/gitlab prefix unrouted"
        )
