"""
customer_bundle.py — the rollout side of TASK-91. Tier A: pure logic, no network, no device.

These moved out of `tests/backend_server/test_gitlab.py` with the module itself: packaging is a
rollout concern, so its tests live with the rollout and not inside the GitLab feature's suite.

Two of these classes are regression tests for defects a REAL build found, which no unit test would
have predicted and which a shallow clone reintroduces silently:

  - TestCloneKeepsHistory — `--depth 1` killed the delivery note, because `delivery_note.sh`
    reads `git show <pin>:VERSION.txt`, the release note at that pin and the diff since the last
    one. The build SUCCEEDED and shipped without the page describing it.
  - TestCloneBranchesAndTags — checking out after the extra fetches landed the checkout on
    whatever FETCH_HEAD the last `release-*` glob had rewritten.

The web-page job layer (a background thread, a status file and a poll endpoint) is gone with the
panel; what remains of its validation — a PIN that is a production tag, a token present — is
TestBuildValidation.
"""
import os
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

pytestmark = pytest.mark.unit


class TestBundleCandidates:
    """The candidate list decides what an operator can even attempt, so it has to be exactly
    what the remote can actually hand over — a PIN that 404s twenty minutes into a stage is the
    one failure this page exists to prevent."""

    @pytest.fixture(autouse=True)
    def _bundle(self, monkeypatch):
        import importlib
        monkeypatch.syspath_prepend(str(PROJECT_ROOT))
        import setup.proxmox.node.lib.customer_bundle as mod
        self.mod = mod

    def _ls_remote(self, monkeypatch, stdout, returncode=0, stderr=""):
        import subprocess as sp
        monkeypatch.setattr(self.mod.subprocess, "run",
                            lambda *a, **k: sp.CompletedProcess(a[0], returncode, stdout, stderr))

    def test_only_production_shapes_are_offered(self, monkeypatch):
        self._ls_remote(monkeypatch, "\n".join([
            "aaa\trefs/tags/main-2026.10.13-63721",
            "bbb\trefs/tags/main-2026.09.26-9375",
            "ccc\trefs/tags/release-2026.09.15",
            "ddd\trefs/tags/v1.0.0",
            "eee\trefs/tags/nightly-thing",       # not a release stamp
            "fff\trefs/tags/whatever",
        ]))
        refs = [r["ref"] for r in self.mod.core_refs()]
        assert refs == ["main-2026.10.13-63721", "main-2026.09.26-9375",
                        "release-2026.09.15", "v1.0.0"]

    def test_an_undated_tag_sorts_last_not_first(self, monkeypatch):
        self._ls_remote(monkeypatch, "\n".join([
            "a\trefs/tags/v9.9.9",                 # newest-looking name, no date
            "b\trefs/tags/main-2020.01.01-1",      # dated, but older
        ]))
        assert [r["ref"] for r in self.mod.core_refs()] == ["main-2020.01.01-1", "v9.9.9"]

    def test_annotated_tag_keeps_the_tag_object_not_the_commit(self, monkeypatch):
        # An annotated tag lists twice; the ^{} line is the dereferenced commit. Using it would
        # pin the build to a commit whose tree differs from what the tag names.
        self._ls_remote(monkeypatch, "\n".join([
            "tagobj\trefs/tags/release-2026.09.15",
            "commitx\trefs/tags/release-2026.09.15^{}",
        ]))
        assert self.mod.core_refs()[0]["sha"] == "tagobj"

    def test_same_day_builds_sort_by_build_number(self, monkeypatch):
        self._ls_remote(monkeypatch, "\n".join([
            "a\trefs/tags/main-2026.10.13-9",
            "b\trefs/tags/main-2026.10.13-100",     # numerically higher, same day
            "c\trefs/tags/main-2026.10.12-9999",    # older day, higher number
        ]))
        assert [r["ref"] for r in self.mod.core_refs()] == [
            "main-2026.10.13-100", "main-2026.10.13-9", "main-2026.10.12-9999"]

    def test_unreachable_remote_is_reported_not_swallowed(self, monkeypatch):
        self._ls_remote(monkeypatch, "", returncode=128, stderr="repository not found")
        with pytest.raises(self.mod.BuildError) as exc:
            self.mod.core_refs()
        assert "repository not found" in str(exc.value)

    def test_core_remote_is_the_configured_one(self, monkeypatch):
        monkeypatch.setenv("VPT_CORE_REMOTE", "http://gl.corp/team/core.git")
        assert self.mod.core_remote() == "http://gl.corp/team/core.git"
        monkeypatch.delenv("VPT_CORE_REMOTE")
        assert self.mod.core_remote().startswith("https://")

    def test_overlay_clone_url_is_the_project_with_git_suffix(self):
        assert self.mod.overlay_clone_url("http://gl.corp/", "/team/app") == "http://gl.corp/team/app.git"


@pytest.mark.unit
class TestBundleSecrets:
    """The PAT must not be readable from `ps` or from the build log."""

    @pytest.fixture(autouse=True)
    def _mod(self, monkeypatch):
        monkeypatch.syspath_prepend(str(PROJECT_ROOT))
        import setup.proxmox.node.lib.customer_bundle as mod
        self.mod = mod

    def test_askpass_file_is_owner_only(self, tmp_path):
        script = tmp_path / ".askpass"
        self.mod._write_askpass(str(script), "root", "glpat-secret")
        assert oct(script.stat().st_mode)[-3:] == "700"

    def test_askpass_answers_username_then_token(self, tmp_path):
        script = tmp_path / ".askpass"
        self.mod._write_askpass(str(script), "root", "glpat-secret")
        import subprocess as sp
        assert "root" in sp.run([str(script), "Username for x"], capture_output=True, text=True).stdout
        assert "glpat-secret" in sp.run([str(script), "Password for x"], capture_output=True, text=True).stdout

    def test_no_token_reaches_the_git_environment(self):
        env = self.mod._askpass_env("/tmp/.askpass", {})
        assert "glpat" not in "".join(env.values())
        assert env["GIT_TERMINAL_PROMPT"] == "0"


@pytest.mark.unit
class TestCloneKeepsHistory:
    """`build_customer_bundle.sh` calls `delivery_note.sh`, which reads `git show <pin>:VERSION.txt`,
    the release note at that pin and the commit diff between two pins. A shallow clone has none of
    that, and the note then fails silently at the end of an otherwise successful build."""

    @pytest.fixture(autouse=True)
    def _mod(self, monkeypatch, tmp_path):
        monkeypatch.syspath_prepend(str(PROJECT_ROOT))
        import setup.proxmox.node.lib.customer_bundle as mod
        self.mod = mod
        self.cmds = []
        monkeypatch.setattr(mod, "_remote_has_tag", lambda dest, ref, env=None: True)
        monkeypatch.setattr(mod.subprocess, "run",
                            lambda *a, **k: __import__("subprocess").CompletedProcess(a[0], 0, "", ""))

        def fake_run(cmd, **kwargs):
            self.cmds.append(cmd)
            return 0

        monkeypatch.setattr(mod, "_run", fake_run)
        self.tmp = tmp_path

    def test_no_fetch_is_shallow(self):
        self.mod._clone(str(self.tmp / "c"), "http://gl/core.git", "release-2026.09.15",
                        __import__("collections").deque(maxlen=10), str(self.tmp / "log"))
        fetches = [c for c in self.cmds if "fetch" in c]
        assert fetches, "no fetch was run"
        for cmd in fetches:
            assert "--depth" not in cmd

    def test_the_tag_lands_as_a_ref_the_note_can_name(self):
        self.mod._clone(str(self.tmp / "c"), "http://gl/core.git", "release-2026.09.15",
                        __import__("collections").deque(maxlen=10), str(self.tmp / "log"))
        spec = [c for c in self.cmds if "refs/tags/release-2026.09.15" in " ".join(c)]
        assert spec, "the tag was not fetched into refs/tags, so git show <pin>:VERSION.txt fails"

    def test_the_previous_pin_is_fetched_too(self):
        self.mod._clone(str(self.tmp / "c"), "http://gl/core.git", "release-2026.09.15",
                        __import__("collections").deque(maxlen=10), str(self.tmp / "log"),
                        also=["release-2026.09.11"])
        assert any("release-2026.09.11" in " ".join(c) for c in self.cmds), \
            "without the previous pin the delivery note has no changelog to write"


@pytest.mark.unit
class TestPackers:
    @pytest.fixture(autouse=True)
    def _mod(self, monkeypatch):
        monkeypatch.syspath_prepend(str(PROJECT_ROOT))
        import setup.proxmox.node.lib.customer_bundle as mod
        self.mod = mod

    def test_reports_what_the_host_can_actually_produce(self, monkeypatch):
        monkeypatch.setattr(self.mod.shutil, "which", lambda b: "/usr/bin/zip" if b == "zip" else None)
        assert self.mod.packers() == {"zip": True, "tar.gz": False}

    def test_a_host_without_zip_says_so_up_front(self, monkeypatch):
        # Found the hard way: zip is a separate package, and the builder only discovers it is
        # missing after staging thousands of files.
        monkeypatch.setattr(self.mod.shutil, "which", lambda b: None)
        assert self.mod.packers()["zip"] is False


@pytest.mark.unit
class TestCloneBranchesAndTags:
    """A branch checkout must name the ref it just created. Every fetch rewrites FETCH_HEAD, so
    a clone that waits until last and checks out FETCH_HEAD lands on whatever the final glob
    matched — or on nothing, with "does not take a path argument"."""

    @pytest.fixture(autouse=True)
    def _mod(self, monkeypatch, tmp_path):
        monkeypatch.syspath_prepend(str(PROJECT_ROOT))
        import setup.proxmox.node.lib.customer_bundle as mod
        self.mod = mod
        self.cmds = []
        self.is_tag = True
        monkeypatch.setattr(mod, "_remote_has_tag", lambda dest, ref, env=None: self.is_tag)
        monkeypatch.setattr(mod, "_run", lambda cmd, **kw: (self.cmds.append(cmd), 0)[1])
        self.tmp = tmp_path

    def _clone(self, ref, **kw):
        return self.mod._clone(str(self.tmp / "c"), "http://gl/o.git", ref,
                               __import__("collections").deque(maxlen=10),
                               str(self.tmp / "log"), **kw)

    def test_a_branch_is_fetched_into_remotes_and_checked_out_by_name(self):
        self.is_tag = False
        assert self._clone("main") == "origin/main"
        checkout = [c for c in self.cmds if c[1] == "checkout"][0]
        assert checkout[-1] == "origin/main", checkout

    def test_a_tag_is_checked_out_by_its_own_name(self):
        self.is_tag = True
        assert self._clone("release-2026.09.15") == "release-2026.09.15"
        checkout = [c for c in self.cmds if c[1] == "checkout"][0]
        assert checkout[-1] == "release-2026.09.15", checkout

    def test_checkout_happens_before_the_extra_fetches(self):
        # Otherwise the release-* glob rewrites FETCH_HEAD out from under the checkout.
        self.is_tag = False
        self._clone("main", tag_glob="release-*")
        order = [i for i, c in enumerate(self.cmds) if c[1] == "checkout"][0]
        last_glob = max(i for i, c in enumerate(self.cmds) if "release-*" in " ".join(c))
        assert order < last_glob, "checkout must not depend on a FETCH_HEAD a later fetch rewrote"


class TestBuildValidation:
    """The three checks that stop a build before it spends twenty minutes staging the wrong tree.
    They used to guard the web page's Start button; they guard the CLI now."""

    @pytest.fixture(autouse=True)
    def _mod(self, monkeypatch, tmp_path):
        monkeypatch.setenv("VPT_BUILD_ROOT", str(tmp_path / "builds"))
        import setup.proxmox.node.lib.customer_bundle as mod
        self.mod = mod

    def _build(self, **kw):
        params = dict(core="github:release-2026.09.15", overlay="gitlab:team/app@main",
                      api="http://gl", tok="glpat-x", base_url="http://gl")
        params.update(kw)
        return self.mod.build(**params)

    def test_a_branch_is_not_accepted_as_a_pin(self):
        with pytest.raises(self.mod.BuildError) as exc:
            self._build(core="github:main")
        assert "production tag" in str(exc.value)

    def test_pin_is_required(self):
        with pytest.raises(self.mod.BuildError):
            self._build(core="github:")

    def test_a_token_is_required_to_read_the_overlay(self):
        with pytest.raises(self.mod.BuildError) as exc:
            self._build(tok="")
        assert "token" in str(exc.value)

    def test_every_accepted_pin_shape(self):
        for pin in ("main-2026.10.13-63726", "release-2026.09.15", "v1.2.3"):
            assert self.mod.PIN_RE.match(pin), pin
        for not_a_pin in ("main", "develop", "release-latest", "1.2.3"):
            assert not self.mod.PIN_RE.match(not_a_pin), not_a_pin


# ─── regressions found in review, against REAL git (a local repo as the remote) ──────────────

def _git(cwd, *args):
    import subprocess as sp
    return sp.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, check=True).stdout.strip()


@pytest.fixture
def remote_repo(tmp_path):
    """A real repo with a branch `main`, the tag `main-2026.10.01-1` (tag only, no branch of
    that name) and the tag `main-2026.10.13-2`."""
    repo = tmp_path / "remote"
    repo.mkdir()
    _git(repo, "init", "--quiet", "-b", "main")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    (repo / "VERSION.txt").write_text("1\n")
    _git(repo, "add", "VERSION.txt")
    _git(repo, "commit", "--quiet", "-m", "one")
    _git(repo, "tag", "main-2026.10.01-1")
    (repo / "VERSION.txt").write_text("2\n")
    _git(repo, "commit", "--quiet", "-am", "two")
    _git(repo, "tag", "-a", "-m", "annotated", "main-2026.10.13-2")
    return repo


@pytest.mark.unit
class TestCloneRealGit:
    """The mocked clone tests cannot see git's own behaviour: one `git fetch` with a tag refspec
    AND a branch refspec fails entirely (`couldn't find remote ref refs/heads/X`) when X is only
    a tag, and the old code ignored that exit code, so the delivery note lost its changelog."""

    @pytest.fixture(autouse=True)
    def _mod(self, monkeypatch, tmp_path):
        monkeypatch.syspath_prepend(str(PROJECT_ROOT))
        import collections
        import setup.proxmox.node.lib.customer_bundle as mod
        self.mod = mod
        self.tmp = tmp_path
        self.log = collections.deque(maxlen=50)

    def _clone(self, remote, ref, **kw):
        dest = self.tmp / "clone"
        self.mod._clone(str(dest), str(remote), ref, self.log, str(self.tmp / "log"), **kw)
        return dest

    def test_a_previous_pin_that_is_only_a_tag_becomes_a_local_tag(self, remote_repo):
        dest = self._clone(remote_repo, "main-2026.10.13-2", also=["main-2026.10.01-1"])
        assert _git(dest, "show", "main-2026.10.01-1:VERSION.txt") == "1"
        assert _git(dest, "show", "main-2026.10.13-2:VERSION.txt") == "2"

    def test_a_previous_pin_that_does_not_exist_is_an_error(self, remote_repo):
        with pytest.raises(self.mod.BuildError) as exc:
            self._clone(remote_repo, "main-2026.10.13-2", also=["main-2026.09.01-9"])
        assert "main-2026.09.01-9" in str(exc.value)

    def test_a_previous_pin_that_is_a_branch_is_fetched_as_one(self, remote_repo):
        dest = self._clone(remote_repo, "main-2026.10.13-2", also=["main"])
        assert _git(dest, "show", "origin/main:VERSION.txt") == "2"

    def test_a_pin_fetched_by_name_still_gets_a_local_tag(self, remote_repo, monkeypatch):
        # The fallback path (refspec fetch refused) lands on FETCH_HEAD; the pin must still be
        # nameable afterwards or the builder's `git show <pin>:VERSION.txt` fails.
        real_run = self.mod._run

        def refuse_refspec(cmd, **kw):
            if cmd[:2] == ["git", "fetch"] and cmd[-1].startswith("+refs/tags/main-2026.10.13-2"):
                return 1
            return real_run(cmd, **kw)

        monkeypatch.setattr(self.mod, "_run", refuse_refspec)
        dest = self.tmp / "clone"
        assert self.mod._clone(str(dest), str(remote_repo), "main-2026.10.13-2", self.log,
                               str(self.tmp / "log"), also=["main-2026.10.01-1"]) == "main-2026.10.13-2"
        assert _git(dest, "show", "main-2026.10.13-2:VERSION.txt") == "2"
        assert _git(dest, "show", "main-2026.10.01-1:VERSION.txt") == "1"


@pytest.mark.unit
class TestCollectsThisBuildsArchive:
    """The out dir is shared by every build. Picking "the newest archive" can hand back an
    earlier build's file, or a stale one when this builder produced nothing."""

    @pytest.fixture(autouse=True)
    def _mod(self, monkeypatch, tmp_path):
        monkeypatch.syspath_prepend(str(PROJECT_ROOT))
        import setup.proxmox.node.lib.customer_bundle as mod
        self.mod = mod
        self.out = tmp_path / "out"
        self.out.mkdir()
        self.log = tmp_path / "build.log"

    def _archive(self, base, fmt="zip"):
        (self.out / f"{base}.{fmt}").write_bytes(b"x" * 10)
        (self.out / f"{base}.{fmt}.sha256").write_text(f"abc123  {base}.{fmt}\n")
        (self.out / f"DELIVERY-{base}.md").write_text("note")

    def test_the_base_is_read_from_the_builders_own_output(self):
        self.log.write_text("$ bash b\n=== BUNDLE_MANIFEST.txt ===\nbundle: vpt-acme-v1\nversion: v1\n")
        assert self.mod._bundle_base(str(self.log)) == "vpt-acme-v1"

    def test_no_bundle_line_means_no_base(self):
        self.log.write_text("ERROR: something\n")
        assert self.mod._bundle_base(str(self.log)) == ""

    @pytest.mark.parametrize("older_name", ["vpt-aaa-v0", "vpt-zzz-v9"])
    def test_an_archive_sorting_either_side_does_not_win(self, older_name):
        self._archive(older_name)          # an earlier build, named before AND after this one
        self._archive("vpt-acme-v1")
        rec = self.mod._collect(str(self.out), "vpt-acme-v1", "zip")
        assert rec["name"] == "vpt-acme-v1.zip"
        assert rec["sha256"] == "abc123"
        assert rec["delivery_note"] == "DELIVERY-vpt-acme-v1.md"

    def test_the_named_archive_missing_is_no_archive(self):
        self._archive("vpt-old-v0")        # stale one present, this build's absent
        assert self.mod._collect(str(self.out), "vpt-acme-v1", "zip") == {}
        assert self.mod._collect(str(self.out), "", "zip") == {}

    def test_the_wrong_format_is_not_picked_up(self):
        self._archive("vpt-acme-v1", "tar.gz")
        assert self.mod._collect(str(self.out), "vpt-acme-v1", "zip") == {}


@pytest.mark.unit
class TestBuildCleansUp:
    """The PAT must not stay on disk, and the overlay checkout is per-build scratch."""

    @pytest.fixture(autouse=True)
    def _mod(self, monkeypatch, tmp_path):
        monkeypatch.setenv("VPT_BUILD_ROOT", str(tmp_path / "builds"))
        monkeypatch.syspath_prepend(str(PROJECT_ROOT))
        import setup.proxmox.node.lib.customer_bundle as mod
        self.mod = mod
        self.root = tmp_path / "builds"
        self.seen = {}
        monkeypatch.setattr(mod, "_clone", self._fake_clone)
        monkeypatch.setattr(mod.gitlab_api, "current_user", lambda **kw: {"username": "bob"})
        monkeypatch.setattr(mod, "_run", lambda *a, **k: 1)

    def _fake_clone(self, dest, url, ref, log, log_path, env=None, **kw):
        if env and "GIT_ASKPASS" in env:     # the overlay clone: the token file must exist, owner-only
            self.seen["askpass"] = env["GIT_ASKPASS"]
            self.seen["mode"] = oct(os.stat(env["GIT_ASKPASS"]).st_mode)[-3:]
            self.seen["overlay"] = dest
            Path(dest, "customer.conf").write_text("x")
        return ref

    def _build(self):
        return self.mod.build("github:release-2026.09.15", "gitlab:team/app@main",
                              api="http://gl", tok="glpat-x", base_url="http://gl")

    def test_askpass_is_owner_only_while_used_and_gone_after(self):
        (self.root / "core-release-2026.09.15" / "setup" / "proxmox" / "node").mkdir(parents=True)
        (self.root / "core-release-2026.09.15" / "setup" / "proxmox" / "node" / "build_customer_bundle.sh").write_text("")
        with pytest.raises(self.mod.BuildError):      # _run fails -> builder "exited 1"
            self._build()
        assert self.seen["mode"] == "700"
        assert not os.path.exists(self.seen["askpass"])
        assert not os.path.exists(self.seen["overlay"])

    def test_askpass_is_gone_when_the_overlay_clone_fails(self, monkeypatch):
        def failing(dest, url, ref, log, log_path, env=None, **kw):
            if env and "GIT_ASKPASS" in env:
                self.seen["askpass"] = env["GIT_ASKPASS"]
                self.seen["overlay"] = dest
                raise self.mod.BuildError("clone failed")
            return ref
        monkeypatch.setattr(self.mod, "_clone", failing)
        with pytest.raises(self.mod.BuildError):
            self._build()
        assert not os.path.exists(self.seen["askpass"])
        assert not os.path.exists(self.seen["overlay"])

    def test_askpass_is_never_created_over_an_existing_path(self, tmp_path):
        path = tmp_path / ".askpass"
        path.write_text("someone else's")
        with pytest.raises(FileExistsError):
            self.mod._write_askpass(str(path), "u", "t")


@pytest.mark.unit
class TestCandidatesFailLoudly:
    @pytest.fixture(autouse=True)
    def _mod(self, monkeypatch):
        monkeypatch.syspath_prepend(str(PROJECT_ROOT))
        import setup.proxmox.node.lib.customer_bundle as mod
        self.mod = mod

        def unreachable():
            raise mod.BuildError("git ls-remote failed for x: nope")
        monkeypatch.setattr(mod, "core_refs", unreachable)

    def test_an_unreachable_core_remote_is_reported_per_source_not_as_an_empty_success(self):
        out = self.mod.candidates("team/app", "http://gl", "", "http://gl")
        gh = out["core"]["github"]
        assert gh["usable"] is False and "nope" in gh["error"]
        assert out["core"]["zip"]["usable"] is True        # an offline install still has a zip

    def test_each_overlay_source_says_whether_it_is_usable(self, monkeypatch):
        monkeypatch.setattr(self.mod, "overlay_refs", lambda *a, **k: ["main", "demo"])
        out = self.mod.candidates("team/app", "http://gl", "tok", "http://gl")["overlay"]
        assert out["gitlab"] == {"usable": True, "project": "team/app", "refs": ["main", "demo"],
                                 "reason": "", "error": ""}
        assert out["none"]["usable"] and out["zip"]["usable"] and out["github"]["usable"]
        no_token = self.mod.candidates("team/app", "", "", "")["overlay"]["gitlab"]
        assert no_token["usable"] is False and "VPT_GITLAB_TOKEN" in no_token["reason"]

    def test_a_failing_gitlab_is_an_error_on_that_source(self, monkeypatch):
        def boom(*a, **k):
            raise self.mod.GitLabError(401, "bad token")
        monkeypatch.setattr(self.mod, "overlay_refs", boom)
        gl = self.mod.candidates("team/app", "http://gl", "tok", "http://gl")["overlay"]["gitlab"]
        assert gl["usable"] is False and "bad token" in gl["error"]

    def test_candidates_prints_json_and_needs_no_gitlab(self, monkeypatch, capsys):
        monkeypatch.delenv("VPT_GITLAB_URL", raising=False)
        monkeypatch.delenv("VPT_GITLAB_TOKEN", raising=False)
        assert self.mod.main(["candidates"]) == 0
        assert '"packers"' in capsys.readouterr().out

    def test_a_gitlab_overlay_needs_url_and_token_but_the_others_do_not(self, monkeypatch):
        monkeypatch.delenv("VPT_GITLAB_URL", raising=False)
        monkeypatch.delenv("VPT_GITLAB_TOKEN", raising=False)
        with pytest.raises(SystemExit):
            self.mod.main(["build", "--core", "github:release-2026.09.15", "--overlay", "gitlab:team/app@main"])
        monkeypatch.setenv("VPT_GITLAB_URL", "http://gl")
        with pytest.raises(SystemExit):
            self.mod.main(["build", "--core", "github:release-2026.09.15", "--overlay", "gitlab:team/app@main"])
        seen = {}
        monkeypatch.setattr(self.mod, "build", lambda *a, **k: seen.update(kw=k, a=a) or {})
        assert self.mod.main(["build", "--core", "github:release-2026.09.15", "--overlay", "none"]) == 0
        assert seen["a"] == ("github:release-2026.09.15", "none")

    def test_a_malformed_source_is_failed_not_a_traceback(self, capsys):
        assert self.mod.main(["build", "--core", "gitlab:x", "--overlay", "none"]) == 1
        assert "FAILED:" in capsys.readouterr().err

    def test_one_resolved_url_serves_the_api_and_the_clone(self, monkeypatch):
        seen = {}
        monkeypatch.setenv("VPT_GITLAB_TOKEN", "tok")
        monkeypatch.setenv("VPT_GITLAB_URL", "http://env-gl")
        monkeypatch.setattr(self.mod, "build", lambda *a, **k: seen.update(kw=k, a=a) or {})
        self.mod.main(["build", "--core", "github:release-2026.09.15", "--overlay", "gitlab:team/app@main"])
        assert seen["kw"]["api"] == "http://env-gl" and seen["kw"]["base_url"] == "http://env-gl"
        assert seen["a"] == ("github:release-2026.09.15", "gitlab:team/app@main")


class TestGithubTokenViaAskpass:
    """The core is the PRIVATE GitHub snapshot: ls-remote and the clone need the token, as Basic auth
    (user x-access-token) through askpass. Never argv, never the URL; no file left behind."""

    TOKEN = "ghp_" + "z" * 36

    @pytest.fixture(autouse=True)
    def _mod(self, monkeypatch, tmp_path):
        monkeypatch.syspath_prepend(str(PROJECT_ROOT))
        import setup.proxmox.node.lib.customer_bundle as mod
        self.mod = mod
        self.seen = []
        monkeypatch.delenv("VPT_GITHUB_TOKEN", raising=False)
        monkeypatch.setenv("GITHUB_TOKEN", self.TOKEN)          # the server .env carries GITHUB_TOKEN only
        monkeypatch.setenv("VPT_CORE_REMOTE", "https://github.com/AngelStreetCorp/virtualpytest.git")

        import subprocess as sp
        real_run = sp.run

        def record(cmd, env):
            script = (env or {}).get("GIT_ASKPASS")
            entry = {"cmd": list(cmd), "script": script, "user": None, "pass": None}
            if script:
                entry["user"] = real_run([script, "Username for 'https://github.com': "], capture_output=True, text=True).stdout
                entry["pass"] = real_run([script, "Password for 'https://x-access-token@github.com': "], capture_output=True, text=True).stdout
            self.seen.append(entry)

        def fake_run(cmd, **kw):
            import subprocess as sp
            record(cmd, kw.get("env"))
            return sp.CompletedProcess(cmd, 0, "aaa\trefs/tags/v1.0.0\n", "")
        monkeypatch.setattr(mod.subprocess, "run", fake_run)
        monkeypatch.setattr(mod, "_run", lambda cmd, **kw: (record(cmd, kw.get("env")), 0)[1])

    def _check(self):
        assert self.seen
        for e in self.seen:
            assert self.TOKEN not in " ".join(e["cmd"]) and "extraHeader" not in " ".join(e["cmd"])
            assert e["script"] and e["user"] == "x-access-token" and e["pass"] == self.TOKEN
            assert not os.path.exists(e["script"])                 # gone after the call

    def test_candidates_ls_remote(self):
        assert [r["ref"] for r in self.mod.core_refs()] == ["v1.0.0"]
        self._check()

    def test_core_clone(self, tmp_path):
        from collections import deque
        self.mod._prepare_core("github", "v1.0.0", str(tmp_path), "", deque(maxlen=5), str(tmp_path / "log"))
        self._check()
        assert any(e["cmd"][:2] == ["git", "fetch"] for e in self.seen)

    def test_a_mirror_never_sees_the_github_token(self, monkeypatch):
        monkeypatch.setenv("VPT_CORE_REMOTE", "http://gl.corp/team/core.git")
        self.mod.core_refs()
        assert self.seen[0]["script"] is None
