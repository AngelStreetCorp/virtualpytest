"""
The frontend bundle stamp must move when anything that changes dist/ changes.

`frontend/scripts/ensure_dist.sh` rebuilds only when `bundle_inputs_hash()` differs from the
stamp in dist/.build-stamp, and it prints "dist is current" — skipping a 1m45s Vite build —
otherwise. So any input of the build that the hash misses is an input the deploy silently
ignores, and the site keeps serving the previous bundle while the rsync'd sources on disk look
perfectly correct. That is not hypothetical: an optional feature IS part of dist/ whenever it is
enabled (vite.config.ts emits one static import per `features/<name>/frontend/routes.tsx`), and
the features trees were not in the hash, so every feature-only change deployed as a no-op.

These are behavioural — the real shell function is sourced against a synthetic tree — rather than
string checks on the script, because the failure this guards against is a list that LOOKS right.
"""
import os
import shutil
import subprocess
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
LIB = PROJECT_ROOT / "frontend" / "scripts" / "lib" / "build_hashes.sh"

pytestmark = pytest.mark.unit

needs_sha1sum = pytest.mark.skipif(
    shutil.which("sha1sum") is None or shutil.which("bash") is None,
    reason="build_hashes.sh needs GNU sha1sum (not the BSD default on macOS) and bash",
)


@pytest.fixture
def tree(tmp_path: Path):
    """A minimal repo shaped like the parts bundle_inputs_hash reads."""
    (tmp_path / "features" / "gitlab" / "frontend").mkdir(parents=True)
    (tmp_path / "features" / "gitlab" / "lib").mkdir(parents=True)
    # device-farm really has no frontend/ dir; an unmatched glob must not break the hash.
    (tmp_path / "features" / "device-farm").mkdir(parents=True)
    (tmp_path / "features" / "device-farm" / "manifest.json").write_text("{}")
    (tmp_path / "frontend" / "src").mkdir(parents=True)
    (tmp_path / "frontend" / "src" / "App.tsx").write_text("export const a = 1;\n")
    (tmp_path / "features" / "gitlab" / "frontend" / "routes.tsx").write_text("export default 1;\n")
    (tmp_path / "features" / "gitlab" / "frontend" / "GitLabMark.tsx").write_text("export const m = 1;\n")
    (tmp_path / "features" / "gitlab" / "lib" / "gitlab_api.py").write_text("VERSION = 1\n")
    return tmp_path


def stamp(tree: Path, **env: str) -> str:
    """Run the real bundle_inputs_hash() over `tree` and return its output."""
    script = (
        f'REPO_ROOT="{tree}"\n'
        f'FRONTEND_DIR="{tree}/frontend"\n'
        f'. "{LIB}"\n'
        "bundle_inputs_hash\n"
    )
    proc = subprocess.run(
        ["bash", "-c", script],
        capture_output=True,
        text=True,
        env={**os.environ, **env},
        timeout=120,
    )
    assert proc.returncode == 0, f"bundle_inputs_hash failed: {proc.stderr}"
    out = proc.stdout.strip()
    assert out, "empty stamp — nothing was hashed, which ensure_dist.sh cannot compare"
    return out


@needs_sha1sum
class TestBundleStampCoversTheBundle:
    def test_it_is_stable_when_nothing_changes(self, tree):
        # A stamp that moved on its own would rebuild on every restart.
        assert stamp(tree) == stamp(tree)

    def test_frontend_source_change_moves_it(self, tree):
        before = stamp(tree)
        (tree / "frontend" / "src" / "App.tsx").write_text("export const a = 2;\n")
        assert stamp(tree) != before

    def test_a_feature_frontend_change_moves_it(self, tree):
        # The regression: this change alters dist/ and used to leave the stamp identical, so
        # ensure_dist.sh declared dist current and the deploy shipped the previous bundle.
        before = stamp(tree)
        (tree / "features" / "gitlab" / "frontend" / "GitLabMark.tsx").write_text("export const m = 2;\n")
        assert stamp(tree) != before

    def test_a_new_feature_file_moves_it(self, tree):
        before = stamp(tree)
        (tree / "features" / "gitlab" / "frontend" / "NewPage.tsx").write_text("export default 2;\n")
        assert stamp(tree) != before

    def test_disabling_a_feature_moves_it(self, tree):
        # VITE_DISABLED_FEATURES decides which routes.tsx files get imported, so switching a
        # feature off changes the bundle while nothing on disk changes. It reaches the build as
        # an environment variable, so no file hash can see it.
        assert stamp(tree) != stamp(tree, VITE_DISABLED_FEATURES="gitlab")

    def test_a_feature_backend_change_does_not_move_it(self, tree):
        # features/<name>/lib and db/ are backend inputs. Hashing them would buy a 1m45s
        # frontend rebuild for a python edit that cannot alter dist/.
        before = stamp(tree)
        (tree / "features" / "gitlab" / "lib" / "gitlab_api.py").write_text("VERSION = 2\n")
        assert stamp(tree) == before