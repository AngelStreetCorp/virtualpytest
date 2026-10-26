"""
customer_bundle.py source matrix (TASK-99 G2-G4): core github|zip x overlay gitlab|github|zip|none.

Tier A with REAL git and the REAL builder: the core is a tiny repo that carries the real
`build_customer_bundle.sh` / `deploy_customer.sh` / `delivery_note.sh`, a local bare repo stands
in for GitHub (VPT_CORE_REMOTE, and `github:<path>@main` for the overlay), zips are built in the
test, and only the GitLab API is mocked. The builder needs `zip` and `rsync`; without them the
build tests skip and the rest (parsing, safe extraction, wrapping) still run.
"""
import os
import shutil
import stat
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

pytestmark = pytest.mark.unit

TAG = "main-2026.10.14-1"
NEEDS_TOOLS = pytest.mark.skipif(
    not (shutil.which("zip") and shutil.which("rsync") and shutil.which("git")),
    reason="the bundle builder needs zip, rsync and git")


def git(cwd, *args, env=None):
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, check=True,
                          env={**os.environ, **(env or {})}).stdout.strip()


def init_repo(path, branch="main"):
    path.mkdir(parents=True, exist_ok=True)
    git(path, "init", "--quiet", "-b", branch)
    git(path, "config", "user.email", "t@t")
    git(path, "config", "user.name", "t")


def write(path, text, mode=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    if mode:
        path.chmod(mode)


def zip_dir(src, dest, prefix=""):
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(Path(src).rglob("*")):
            if ".git" in f.relative_to(src).parts:
                continue
            if f.is_file():
                z.write(f, os.path.join(prefix, f.relative_to(src)))
    return dest


@pytest.fixture
def mod(monkeypatch, tmp_path):
    monkeypatch.setenv("VPT_BUILD_ROOT", str(tmp_path / "builds"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    import setup.proxmox.node.lib.customer_bundle as m
    return m


@pytest.fixture
def core_tree(tmp_path):
    """A minimal core: the real scripts the builder runs, plus one feature and a VERSION.txt."""
    root = tmp_path / "core-src"
    for rel in ("setup/proxmox/node/build_customer_bundle.sh", "setup/proxmox/node/deploy_customer.sh",
                "setup/proxmox/node/lib/feature_units.sh", "setup/proxmox/node/reconcile_feature_units.sh",
                "setup/proxmox/node/update_core.sh", "scripts/release/delivery_note.sh",
                "scripts/release/format_changes.py", "scripts/disabled_features_excludes.sh"):
        src = PROJECT_ROOT / rel
        if src.exists():
            (root / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, root / rel)
    write(root / "VERSION.txt", f"current:{TAG}\nprevious:main-2026.10.13-0-abc1234\n")
    write(root / "features/demo/manifest.json", '{"name": "demo", "parts": ["frontend"]}')
    write(root / "features/demo/frontend/Demo.tsx", "export {}\n")
    write(root / "frontend/package.json", "{}\n")
    write(root / "README.md", "core\n")
    return root


@pytest.fixture
def core_remote(tmp_path, core_tree, monkeypatch):
    """A bare repo standing in for the public GitHub repo, with the production tag."""
    work = tmp_path / "core-work"
    shutil.copytree(core_tree, work)
    init_repo(work)
    git(work, "add", "-f", "-A")
    git(work, "commit", "--quiet", "-m", "core")
    git(work, "tag", TAG)
    bare = tmp_path / "github-core.git"
    git(tmp_path, "clone", "--quiet", "--bare", str(work), str(bare))
    monkeypatch.setenv("VPT_CORE_REMOTE", str(bare))
    return bare


@pytest.fixture
def core_zip(tmp_path, core_tree):
    # GitHub's "Download ZIP" wraps everything in <repo>-<ref>/
    return zip_dir(core_tree, tmp_path / "core.zip", prefix="virtualpytest-main")


@pytest.fixture
def overlay_tree(tmp_path):
    root = tmp_path / "vpt-customer-acme"
    write(root / "customer.conf", "PIN=main-2026.10.13-0\nDISABLED_FEATURES=\n")
    write(root / "VERSION.txt", "current:prod-2026.10.14-3\n")
    write(root / "frontend/.env.production", "VITE_BRAND=acme\n")
    return root


@pytest.fixture
def overlay_bare(tmp_path, overlay_tree):
    work = tmp_path / "overlay-work"
    shutil.copytree(overlay_tree, work)
    init_repo(work)
    git(work, "add", "-f", "-A")
    git(work, "commit", "--quiet", "-m", "overlay")
    bare = tmp_path / "overlay.git"
    git(tmp_path, "clone", "--quiet", "--bare", str(work), str(bare))
    return bare


@pytest.fixture
def overlay_zip(tmp_path, overlay_tree):
    return zip_dir(overlay_tree, tmp_path / "acme-overlay.zip", prefix="acme-main")


def check_artifacts(record, out_dir, name_part, fmt="zip"):
    assert record["name"].startswith(f"vpt-{name_part}-") and record["name"].endswith("." + fmt)
    archive = Path(record["path"])
    assert archive.is_file() and Path(str(archive) + ".sha256").is_file()
    assert Path(str(archive) + ".sha256").read_text().split()[0] == record["sha256"]
    note = Path(out_dir) / record["delivery_note"]
    assert note.is_file()
    names = zipfile.ZipFile(archive).namelist() if fmt == "zip" else []
    if names:
        assert "virtualpytest/BUNDLE_MANIFEST.txt" in names
        assert not any("/.git/" in n for n in names)
    return note.read_text(), names


# ─── parsing ───────────────────────────────────────────────────────────────────

class TestParsing:
    def test_core_specs(self, mod):
        assert mod.parse_core("github:main-2026.10.13-1") == ("github", "main-2026.10.13-1")
        assert mod.parse_core("zip:/tmp/a b.zip") == ("zip", "/tmp/a b.zip")
        for bad in ("", "main-2026.10.13-1", "gitlab:x", "zip:", "github: "):
            with pytest.raises(mod.BuildError):
                mod.parse_core(bad)

    def test_overlay_specs(self, mod):
        assert mod.parse_overlay("none")["kind"] == "none"
        assert mod.parse_overlay("gitlab:team/app@demo") == {"kind": "gitlab", "loc": "team/app", "ref": "demo"}
        assert mod.parse_overlay("gitlab:team/app")["ref"] == "main"
        assert mod.parse_overlay("zip:/tmp/o.zip")["loc"] == "/tmp/o.zip"
        gh = mod.parse_overlay("github:https://github.com/acme/overlay@feat/x")
        assert (gh["loc"], gh["ref"]) == ("https://github.com/acme/overlay", "feat/x")
        for bad in ("", "gitlab:", "ftp:x", "github"):
            with pytest.raises(mod.BuildError):
                mod.parse_overlay(bad)

    def test_an_at_sign_in_the_url_authority_is_not_a_ref(self, mod):
        gh = mod.parse_overlay("github:https://user@github.com/acme/overlay")
        assert (gh["loc"], gh["ref"]) == ("https://user@github.com/acme/overlay", "main")

    def test_github_clone_url(self, mod):
        assert mod.github_clone_url("acme/overlay") == "https://github.com/acme/overlay.git"
        assert mod.github_clone_url("https://github.com/acme/o") == "https://github.com/acme/o"
        assert mod.github_clone_url("/srv/o.git") == "/srv/o.git"


# ─── safe extraction ───────────────────────────────────────────────────────────

def raw_zip(path, entries):
    """entries: (name, data, unix_mode)"""
    with zipfile.ZipFile(path, "w") as z:
        for name, data, mode in entries:
            info = zipfile.ZipInfo(name)
            info.external_attr = mode << 16
            z.writestr(info, data)
    return path


class TestSafeExtract:
    F = stat.S_IFREG | 0o644

    @pytest.mark.parametrize("name", ["/etc/evil", "../evil", "a/../../evil", "a\\..\\evil", "C:evil"])
    def test_unsafe_paths_are_refused_and_nothing_is_written(self, mod, tmp_path, name):
        z = raw_zip(tmp_path / "z.zip", [("ok.txt", "x", self.F), (name, "x", self.F)])
        dest = tmp_path / "dest"
        with pytest.raises(mod.BuildError, match="unsafe path"):
            mod.safe_extract_zip(str(z), str(dest))
        assert not (dest / "ok.txt").exists()
        assert not (tmp_path / "evil").exists()

    @pytest.mark.parametrize("target", ["/etc/passwd", "../../outside", "a/../../.."])
    def test_a_symlink_that_escapes_is_refused(self, mod, tmp_path, target):
        z = raw_zip(tmp_path / "z.zip", [("link", target, stat.S_IFLNK | 0o777)])
        with pytest.raises(mod.BuildError, match="symlink"):
            mod.safe_extract_zip(str(z), str(tmp_path / "dest"))

    def test_writing_through_a_symlink_is_refused(self, mod, tmp_path):
        outside = tmp_path / "outside"
        outside.mkdir()
        z = raw_zip(tmp_path / "z.zip", [("d", "sub", stat.S_IFLNK | 0o777), ("d/../x", "x", self.F)])
        with pytest.raises(mod.BuildError):
            mod.safe_extract_zip(str(z), str(tmp_path / "dest"))
        # a symlink to a sibling inside the archive is kept; a file through it is not allowed to leave
        z2 = raw_zip(tmp_path / "z2.zip", [("up", "..", stat.S_IFLNK | 0o777)])
        with pytest.raises(mod.BuildError):
            mod.safe_extract_zip(str(z2), str(tmp_path / "dest2"))

    def test_an_internal_symlink_and_the_exec_bit_survive(self, mod, tmp_path):
        z = raw_zip(tmp_path / "z.zip", [
            ("pkg/real.txt", "hello", self.F),
            ("pkg/run.sh", "#!/bin/sh\n", stat.S_IFREG | 0o755),
            ("pkg/alias", "real.txt", stat.S_IFLNK | 0o777)])
        dest = tmp_path / "dest"
        mod.safe_extract_zip(str(z), str(dest))
        assert (dest / "pkg/alias").is_symlink() and (dest / "pkg/alias").read_text() == "hello"
        assert os.access(dest / "pkg/run.sh", os.X_OK)
        assert not os.access(dest / "pkg/real.txt", os.X_OK)

    def test_a_zip_bomb_is_refused(self, mod, tmp_path, monkeypatch):
        monkeypatch.setattr(mod, "ZIP_MAX_BYTES", 10)
        z = raw_zip(tmp_path / "z.zip", [("big", "x" * 100, self.F)])
        with pytest.raises(mod.BuildError, match="expands past"):
            mod.safe_extract_zip(str(z), str(tmp_path / "dest"))

    def test_not_a_zip_and_missing_are_errors(self, mod, tmp_path):
        (tmp_path / "bad.zip").write_text("nope")
        for p in (tmp_path / "bad.zip", tmp_path / "missing.zip"):
            with pytest.raises(mod.BuildError):
                mod.safe_extract_zip(str(p), str(tmp_path / "d"))


# ─── zip -> git wrapping ───────────────────────────────────────────────────────

class TestZipCore:
    def test_a_core_zip_becomes_a_one_commit_repo_tagged_with_its_version(self, mod, core_zip, tmp_path):
        from collections import deque
        d, pin, scratch = mod._prepare_core("zip", str(core_zip), str(tmp_path / "root"), "", deque(), str(tmp_path / "l.log"))
        try:
            assert pin == TAG
            assert git(d, "rev-list", "--count", "HEAD") == "1"
            assert git(d, "tag", "-l", TAG) == TAG
            assert git(d, "show", f"{TAG}:VERSION.txt").startswith(f"current:{TAG}")   # ignored file still tracked
            assert git(d, "log", "-1", "--format=%an") == "vpt-bundle"
            assert os.path.basename(d) == "virtualpytest-main"
        finally:
            shutil.rmtree(scratch, ignore_errors=True)

    def test_a_zip_that_is_not_a_core_is_refused_and_cleaned_up(self, mod, tmp_path):
        z = raw_zip(tmp_path / "x.zip", [("hello.txt", "x", stat.S_IFREG | 0o644)])
        from collections import deque
        with pytest.raises(mod.BuildError, match="not a VirtualPyTest core"):
            mod._prepare_core("zip", str(z), str(tmp_path / "root"), "", deque(), str(tmp_path / "l.log"))
        assert not list((tmp_path / "root").glob("core-zip-*"))

    def test_a_zip_overlay_needs_customer_conf(self, mod, tmp_path):
        from collections import deque
        z = raw_zip(tmp_path / "o.zip", [("README.md", "x", stat.S_IFREG | 0o644)])
        with pytest.raises(mod.BuildError, match="customer.conf"):
            mod._prepare_overlay({"kind": "zip", "loc": str(z), "ref": ""}, str(tmp_path / "root"),
                                 "", "", "", "", deque(), str(tmp_path / "l.log"))
        assert not list((tmp_path / "root").glob("overlay-*"))

    def test_the_overlay_folder_carries_the_overlay_name(self, mod, overlay_zip, tmp_path):
        from collections import deque
        d, scratch = mod._prepare_overlay({"kind": "zip", "loc": str(overlay_zip), "ref": ""},
                                          str(tmp_path / "root"), "", "", "", "", deque(), str(tmp_path / "l.log"))
        try:
            assert os.path.basename(d) == "acme-overlay"
            assert (Path(d) / "customer.conf").is_file() and (Path(d) / ".git").is_dir()
        finally:
            shutil.rmtree(scratch, ignore_errors=True)


# ─── GitHub overlay token handling ─────────────────────────────────────────────

class TestGithubOverlayToken:
    def _run(self, mod, tmp_path, monkeypatch, github_tok):
        from collections import deque
        seen = {}

        def fake_clone(dest, url, ref, log, log_path, env=None, **kw):
            seen.update(url=url, ref=ref, env=env)
            if env:
                seen["script"] = Path(env["GIT_ASKPASS"]).read_text()
            write(Path(dest) / "customer.conf", "x")
            return ref
        monkeypatch.setattr(mod, "_clone", fake_clone)
        mod._prepare_overlay({"kind": "github", "loc": "acme/overlay", "ref": "prod"}, str(tmp_path / "root"),
                             "", "", "", github_tok, deque(), str(tmp_path / "l.log"))
        return seen

    def test_the_token_goes_through_askpass_and_never_the_url(self, mod, tmp_path, monkeypatch):
        seen = self._run(mod, tmp_path, monkeypatch, "ghp_secret")
        assert seen["url"] == "https://github.com/acme/overlay.git" and "ghp_secret" not in seen["url"]
        assert "ghp_secret" in seen["script"] and "x-access-token" in seen["script"]
        assert not list((tmp_path / "root").glob(".askpass-*"))
        assert "ghp_secret" not in str(sorted(seen["env"].items()))

    def test_a_public_overlay_needs_no_token(self, mod, tmp_path, monkeypatch):
        assert self._run(mod, tmp_path, monkeypatch, "")["env"] is None


# ─── the matrix, through the real builder ──────────────────────────────────────

@NEEDS_TOOLS
class TestBuildMatrix:
    def test_github_core_and_no_overlay(self, mod, core_remote, tmp_path):
        out = tmp_path / "out"
        rec = mod.build(f"github:{TAG}", "none", out_dir=str(out))
        note, names = check_artifacts(rec, out, "platform")
        assert TAG in rec["name"]
        assert "virtualpytest/features/demo/manifest.json" in names
        assert "Changelog unavailable" in note and "(zip source)" not in note   # no previous release in this remote

    def test_zip_core_and_zip_overlay(self, mod, core_zip, overlay_zip, tmp_path):
        out = tmp_path / "out"
        rec = mod.build(f"zip:{core_zip}", f"zip:{overlay_zip}", out_dir=str(out), fmt="zip")
        note, names = check_artifacts(rec, out, "acme-overlay")
        assert "virtualpytest/frontend/.env.production" in names                # the overlay's frontend config
        assert "virtualpytest/customer.conf" not in names                       # overlay housekeeping stays out
        assert "Changelog unavailable (zip source)" in note
        manifest = zipfile.ZipFile(rec["path"]).read("virtualpytest/BUNDLE_MANIFEST.txt").decode()
        assert f"platform_ref: {TAG}" in manifest and "overlay_version: prod-2026.10.14-3" in manifest
        # the wrapper repo and the zip scratch are gone
        assert not list((tmp_path / "builds").glob("core-zip-*")) and not list((tmp_path / "builds").glob("overlay-*"))

    def test_zip_core_tar_gz_and_pin_is_the_version(self, mod, core_zip, tmp_path):
        out = tmp_path / "out"
        rec = mod.build(f"zip:{core_zip}", "none", out_dir=str(out), fmt="tar.gz")
        assert rec["name"] == f"vpt-platform-{TAG}.tar.gz"
        assert (out / (rec["name"] + ".sha256")).is_file()

    def test_github_core_and_gitlab_overlay_with_the_api_mocked(self, mod, core_remote, overlay_bare, tmp_path, monkeypatch):
        calls = []
        monkeypatch.setattr(mod.gitlab_api, "current_user", lambda **kw: calls.append(kw) or {"username": "bob"})
        monkeypatch.setattr(mod, "overlay_clone_url", lambda base, project: str(overlay_bare))
        out = tmp_path / "out"
        rec = mod.build(f"github:{TAG}", "gitlab:team/vpt-customer-acme@main", api="http://gl",
                        tok="glpat-secret", base_url="http://gl", out_dir=str(out))
        check_artifacts(rec, out, "acme")
        assert calls and calls[0]["tok"] == "glpat-secret"
        log = "".join(p.read_text() for p in (tmp_path / "builds").glob("build-*.log"))
        assert "glpat-secret" not in log
        assert not list((tmp_path / "builds").glob(".askpass-*"))

    def test_github_overlay_by_a_local_bare_repo(self, mod, core_remote, overlay_bare, tmp_path):
        out = tmp_path / "out"
        rec = mod.build(f"github:{TAG}", f"github:{overlay_bare}@main", out_dir=str(out))
        check_artifacts(rec, out, "overlay")

    def test_github_overlay_without_customer_conf_is_refused(self, mod, core_remote, tmp_path):
        bare_src = tmp_path / "plain"
        init_repo(bare_src)
        write(bare_src / "app.py", "x")
        git(bare_src, "add", "-A")
        git(bare_src, "commit", "--quiet", "-m", "app")
        with pytest.raises(mod.BuildError, match="customer.conf"):
            mod.build(f"github:{TAG}", f"github:{bare_src}@main", out_dir=str(tmp_path / "out"))
        assert not list((tmp_path / "builds").glob("overlay-*"))

    def test_cli_end_to_end(self, mod, core_zip, tmp_path, capsys):
        rc = mod.main(["build", "--core", f"zip:{core_zip}", "--overlay", "none", "--out", str(tmp_path / "out")])
        assert rc == 0 and '"sha256"' in capsys.readouterr().out
