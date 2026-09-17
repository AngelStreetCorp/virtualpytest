"""virtual-scripts feature — CRUD plus the invariants that actually matter.

`/server/virtual-script/*` (features/virtual-scripts/backend_server/) stores Python
source in the database and hands it to the executor, so the rules worth testing are not
"does the row round-trip" but the gates that stop a broken script reaching a device:

  * syntax is a HARD gate — a script that will not compile must never persist
  * names are unique per team — a duplicate must be rejected, not silently overwrite
  * the analyzer only reads the first 300 lines, so `_script_args` below that is invisible
    (docs: feedback_script_args_top_300_lines) — a real trap encoded here as a test

All tier A: server API only, no device. Every test creates its own script and deletes it
in teardown so the suite is independent of existing data.
"""

import uuid

import pytest

from .conftest import assert_not_auth_failure

VALID_SOURCE = '''"""A virtual script used by the CI suite."""

_script_description = "created by tests/backend_server/test_virtual_scripts.py"
_script_args = ['--channel:number:3']


def main():
    print("ok")
'''

BROKEN_SOURCE = "def main(:\n    print('this does not parse')\n"


def _unique_name() -> str:
    return f"zz_ci_vscript_{uuid.uuid4().hex[:8]}"


@pytest.fixture
def virtual_script(post, delete, api_headers, team_id):
    """Create a virtual script; always remove it afterwards."""
    name = _unique_name()
    response = post(
        "/server/virtual-script/save",
        headers=api_headers,
        params={"team_id": team_id},
        json={"name": name, "source": VALID_SOURCE},
    )
    assert_not_auth_failure(response, "creating a virtual script")
    if response.status_code != 200 or not response.json().get("success"):
        pytest.skip(f"could not create a virtual script ({response.status_code}): {response.text[:200]}")

    body = response.json()
    created = {"id": body.get("id"), "name": name, "body": body}
    yield created

    if created["id"]:
        delete(f"/server/virtual-script/{created['id']}",
               headers=api_headers, params={"team_id": team_id})


class TestVirtualScriptCrud:
    def test_list_returns_scripts(self, get, api_headers, team_id):
        response = get("/server/virtual-script/list", headers=api_headers,
                       params={"team_id": team_id})
        assert response.status_code == 200, response.text[:300]

        body = response.json()
        assert body.get("success") is True
        assert isinstance(body.get("scripts"), list)
        assert body.get("count") == len(body["scripts"])

    def test_create_returns_id_and_parsed_parameters(self, virtual_script):
        assert virtual_script["id"], virtual_script["body"]
        params = virtual_script["body"].get("parameters") or []
        # _script_args is declared at the top of VALID_SOURCE, so the analyzer must see it.
        assert any(p.get("name") == "channel" for p in params), params

    def test_created_script_is_readable_with_its_source(
        self, get, api_headers, team_id, virtual_script
    ):
        response = get(f"/server/virtual-script/{virtual_script['id']}",
                       headers=api_headers, params={"team_id": team_id})
        assert response.status_code == 200, response.text[:300]

        script = response.json().get("script") or response.json()
        assert "def main():" in (script.get("source") or ""), script

    def test_created_script_appears_in_the_list(self, get, api_headers, team_id, virtual_script):
        response = get("/server/virtual-script/list", headers=api_headers,
                       params={"team_id": team_id})
        names = {s.get("name") for s in response.json().get("scripts") or []}
        assert virtual_script["name"] in names

    def test_edit_persists_new_source(self, post, get, api_headers, team_id, virtual_script):
        edited = VALID_SOURCE.replace('print("ok")', 'print("edited")')
        response = post(
            "/server/virtual-script/save",
            headers=api_headers,
            params={"team_id": team_id},
            json={"id": virtual_script["id"], "name": virtual_script["name"], "source": edited},
        )
        assert response.status_code == 200, response.text[:300]
        assert response.json().get("success") is True

        reread = get(f"/server/virtual-script/{virtual_script['id']}",
                     headers=api_headers, params={"team_id": team_id})
        script = reread.json().get("script") or reread.json()
        assert 'print("edited")' in (script.get("source") or "")

    def test_delete_removes_it(self, post, get, delete, api_headers, team_id):
        name = _unique_name()
        created = post("/server/virtual-script/save", headers=api_headers,
                       params={"team_id": team_id},
                       json={"name": name, "source": VALID_SOURCE})
        assert_not_auth_failure(created, "creating a virtual script")
        if created.status_code != 200 or not created.json().get("success"):
            pytest.skip(f"could not create a virtual script: {created.text[:200]}")

        removed = delete(f"/server/virtual-script/{created.json()['id']}",
                         headers=api_headers, params={"team_id": team_id})
        assert removed.status_code == 200, removed.text[:300]

        listed = get("/server/virtual-script/list", headers=api_headers,
                     params={"team_id": team_id})
        assert name not in {s.get("name") for s in listed.json().get("scripts") or []}


class TestVirtualScriptGates:
    """The rules that stop a broken script reaching a device."""

    def test_broken_syntax_is_rejected_and_not_persisted(
        self, post, get, delete, api_headers, team_id
    ):
        name = _unique_name()
        response = post("/server/virtual-script/save", headers=api_headers,
                        params={"team_id": team_id},
                        json={"name": name, "source": BROKEN_SOURCE})

        # Clean up defensively: this test asserts nothing was created, so on the day that
        # assertion is wrong it would otherwise leak the row it just proved shouldn't exist.
        created_id = response.json().get("id") if response.status_code == 200 else None
        try:
            assert response.status_code == 400, response.text[:300]
            assert response.json().get("error") == "syntax_error", response.json()

            # The gate is only worth anything if nothing was written.
            listed = get("/server/virtual-script/list", headers=api_headers,
                         params={"team_id": team_id})
            assert name not in {s.get("name") for s in listed.json().get("scripts") or []}, \
                "a script that does not compile was persisted"
        finally:
            if created_id:
                delete(f"/server/virtual-script/{created_id}",
                       headers=api_headers, params={"team_id": team_id})

    def test_duplicate_name_is_rejected(self, post, api_headers, team_id, virtual_script):
        response = post("/server/virtual-script/save", headers=api_headers,
                        params={"team_id": team_id},
                        json={"name": virtual_script["name"], "source": VALID_SOURCE})
        assert response.status_code == 409, response.text[:300]

    def test_validate_accepts_valid_and_rejects_broken(self, post, api_headers, team_id):
        ok = post("/server/virtual-script/validate", headers=api_headers,
                  params={"team_id": team_id}, json={"source": VALID_SOURCE})
        assert ok.status_code == 200
        assert (ok.json().get("validation") or {}).get("valid") is True, ok.json()

        bad = post("/server/virtual-script/validate", headers=api_headers,
                   params={"team_id": team_id}, json={"source": BROKEN_SOURCE})
        assert bad.status_code == 200
        assert (bad.json().get("validation") or {}).get("valid") is False, bad.json()


class TestVirtualScriptAnalyzer:
    def test_script_args_at_the_top_are_parsed(self, post, api_headers, team_id):
        response = post("/server/virtual-script/analyze", headers=api_headers,
                        params={"team_id": team_id},
                        json={"source": VALID_SOURCE, "name": "probe"})
        assert response.status_code == 200, response.text[:300]
        names = {p.get("name") for p in response.json().get("parameters") or []}
        assert "channel" in names, response.json()

    def test_script_args_below_line_300_are_invisible(self, post, api_headers, team_id):
        """The analyzer reads only the first 300 lines — a documented limit, and a trap.

        This is not asserting desirable behaviour, it is pinning known behaviour so the
        limit cannot change silently: a script declaring `_script_args` further down gets
        no parameters, with no error to say why.
        """
        buried = ("# padding\n" * 320) + "_script_args = ['--buried:string']\n"
        response = post("/server/virtual-script/analyze", headers=api_headers,
                        params={"team_id": team_id},
                        json={"source": buried, "name": "probe"})
        assert response.status_code == 200, response.text[:300]

        names = {p.get("name") for p in response.json().get("parameters") or []}
        assert "buried" not in names, (
            "the analyzer now reads past line 300 — feedback_script_args_top_300_lines and "
            "any docs describing that limit need updating"
        )


class TestConvertDiskScript:
    """Convert-to-virtual — the naming and helper rules, not the row round trip.

    Conversion is not a copy: a virtual script materializes at the test_scripts/
    ROOT, so the name must lose its folder (a slashed name crashes _script_libs
    materialization, which writes `<vslib_dir>/<name>.py` with no mkdir) and any
    `from test_scripts.<pkg>.<mod> import ...` has to become a declared library.

    These run against a deployed server's own test_scripts/ tree, so they use a
    script the platform always ships.
    """

    CONVERTIBLE = "gw/dns_lookuptime"   # no helper imports, no __file__ paths

    def test_dry_run_reports_a_plan_and_writes_nothing(self, post, get, delete, api_headers, team_id):
        # A CI run cancelled mid-conversion (cancel-in-progress) leaves the converted row behind;
        # clear it first so this checks the dry run, not the previous run's leftovers.
        for s in (get("/server/virtual-script/list", headers=api_headers,
                      params={"team_id": team_id}).json().get("scripts") or []):
            if s.get("name") == "dns_lookuptime" and s.get("id"):
                delete(f"/server/virtual-script/{s['id']}", headers=api_headers,
                       params={"team_id": team_id})

        response = post("/server/virtual-script/convert", headers=api_headers,
                        params={"team_id": team_id},
                        json={"script_name": self.CONVERTIBLE, "dry_run": True})
        assert_not_auth_failure(response, "convert dry run")
        if response.status_code == 404:
            pytest.skip(f"{self.CONVERTIBLE}.py not present on this server")
        assert response.status_code == 200, response.text[:300]

        body = response.json()
        assert body.get("dry_run") is True
        assert body.get("errors") == []
        names = [u["name"] for u in body.get("units") or []]
        assert "dns_lookuptime" in names

        listed = get("/server/virtual-script/list", headers=api_headers,
                     params={"team_id": team_id}).json()
        assert "dns_lookuptime" not in [s["name"] for s in listed.get("scripts") or []]

    def test_convert_names_by_basename_and_files_under_the_disk_folder(
            self, post, delete, get, api_headers, team_id):
        response = post("/server/virtual-script/convert", headers=api_headers,
                        params={"team_id": team_id},
                        json={"script_name": self.CONVERTIBLE})
        assert_not_auth_failure(response, "convert")
        if response.status_code == 404:
            pytest.skip(f"{self.CONVERTIBLE}.py not present on this server")
        assert response.status_code == 200, response.text[:300]

        body = response.json()
        script_id = body.get("id")
        try:
            assert body.get("success") is True
            # The folder is dropped from the NAME and kept as the folder.
            assert body.get("name") == "dns_lookuptime"
            assert "/" not in body["name"]
            root = next(u for u in body["units"] if not u["is_helper"])
            assert root["folder"] == "gw"

            # Re-converting is an update, not a duplicate or a 409.
            again = post("/server/virtual-script/convert", headers=api_headers,
                         params={"team_id": team_id},
                         json={"script_name": self.CONVERTIBLE})
            assert again.status_code == 200, again.text[:300]
            assert again.json().get("action") == "updated"
            assert again.json().get("id") == script_id
        finally:
            if script_id:
                delete(f"/server/virtual-script/{script_id}",
                       headers=api_headers, params={"team_id": team_id})

    def test_convert_rejects_a_missing_script(self, post, api_headers, team_id):
        response = post("/server/virtual-script/convert", headers=api_headers,
                        params={"team_id": team_id},
                        json={"script_name": "gw/zz_does_not_exist"})
        assert_not_auth_failure(response, "convert missing script")
        assert response.status_code == 404, response.text[:300]
        assert response.json().get("success") is False

    def test_convert_rejects_path_traversal(self, post, api_headers, team_id):
        response = post("/server/virtual-script/convert", headers=api_headers,
                        params={"team_id": team_id},
                        json={"script_name": "../backend_server/src/app"})
        assert_not_auth_failure(response, "convert traversal")
        assert response.status_code == 400, response.text[:300]

    def test_convert_batch_requires_a_selection(self, post, api_headers, team_id):
        response = post("/server/virtual-script/convert-batch", headers=api_headers,
                        params={"team_id": team_id}, json={})
        assert_not_auth_failure(response, "convert-batch without selection")
        assert response.status_code == 400, response.text[:300]

    def test_convert_batch_dry_run_dedupes_shared_helpers(self, post, api_headers, team_id):
        """A helper imported by two scripts is converted once, not twice."""
        response = post("/server/virtual-script/convert-batch", headers=api_headers,
                        params={"team_id": team_id},
                        json={"folder": "gw", "dry_run": True, "allow_warnings": True})
        assert_not_auth_failure(response, "convert-batch dry run")
        if response.status_code != 200:
            pytest.skip(f"gw/ not convertible on this server: {response.text[:200]}")

        units = response.json().get("units") or []
        names = [u["name"] for u in units]
        assert len(names) == len(set(names)), f"duplicate units: {names}"
        assert all("/" not in n for n in names)
