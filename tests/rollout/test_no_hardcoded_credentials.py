"""No credential-shaped literal may be committed to the tracked tree.

The auto-sign token is a team-admin credential: it bypasses authentication on every
VirtualPyTest page and API. It once sat as a string literal in the measurement scripts,
and the URLs those scripts built (`?auto_signed=<token>`) ended up in the QA evidence
JSON they recorded — so the repo carried the credential in tracked files, and every
artifact those scripts wrote carried it too.

These tests fail if that happens again. Pure unit: the tree is read through git,
nothing is fetched, nothing is executed, no server and no device are needed.

It lives in tests/rollout because that is the repo's pure-unit Python lane — CI runs
`pytest tests/rollout -m "not manual"` (regression.yml) and `tests/run_all.sh rollout`
runs the same directory.
"""
import re
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from _auto_sign import PLACEHOLDER, auto_sign_token, redact  # noqa: E402

pytestmark = pytest.mark.unit

# The vector that leaked: a credential in the query string of a recorded URL.
AUTO_SIGNED_LITERAL = re.compile(r"auto_signed=([A-Za-z0-9_\-]{16,})")

# The shape that was there: a credential assigned to a credential-shaped name.
CREDENTIAL_ASSIGNMENT = re.compile(
    r"""(?i)\b(auto_sign_token|auto_sign|api_key|apikey|secret_key|password|passwd"""
    r"""|bearer_token|auth_token|access_token|x-auto-sign)\b"""
    r"""\s*[:=]\s*["']([A-Za-z0-9_\-\.]+)["']"""
)

# Values that are a placeholder word, not a credential.
PLACEHOLDER_VALUES = {
    "AUTO_SIGN_TOKEN", "TOKEN", "REDACTED", "PLACEHOLDER", "XXXX",
    "your_token_here", "test-token", "test_token",
}

EVIDENCE_FILES = [
    "docs/tasks/qa-evidence/tester/sweep-desktop-dark.json",
    "docs/tasks/qa-evidence/tester/sweep-desktop-light.json",
    "docs/tasks/qa-evidence/tester/sweep-mobile-dark.json",
]

MEASURE_SCRIPTS = [
    "scripts/measure_endtoend.py",
    "scripts/measure_e2e_via_cors.py",
    "scripts/measure_e2e_browser.py",
]


def _looks_random(value: str) -> bool:
    """True for a value shaped like a generated secret, False for a readable word.

    A fixture like "unit-test-strong-key" is a test value; a 64-char hex string is a
    credential. Only the second must be blocked.
    """
    if re.fullmatch(r"[0-9a-fA-F]{32,}", value):
        return True
    if len(value) >= 32 and re.search(r"\d", value) and re.search(r"[a-z]", value) \
            and re.search(r"[A-Z]", value):
        return True
    return False


def _tracked_paths(root: Path) -> list[str]:
    out = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z"],
        capture_output=True, text=True, check=True,
    ).stdout
    return [p for p in out.split("\0") if p]


def _texts(root: Path) -> dict[str, str]:
    """Every tracked text file of `root`, as {relative path: content}.

    Binary files are skipped: a credential cannot live in them and cannot be read
    as text without mangling the bytes.
    """
    texts: dict[str, str] = {}
    for rel in _tracked_paths(root):
        try:
            raw = (root / rel).read_bytes()
        except OSError:
            continue
        if b"\0" in raw[:8000]:
            continue
        try:
            texts[rel] = raw.decode("utf-8")
        except UnicodeDecodeError:
            continue
    return texts


def _flag_auto_signed(texts: dict[str, str]) -> list[str]:
    """Tracked files whose URL carries a literal in place of the token."""
    hits = []
    for rel, text in texts.items():
        for n, line in enumerate(text.splitlines(), 1):
            for m in AUTO_SIGNED_LITERAL.finditer(line):
                if m.group(1) not in PLACEHOLDER_VALUES:
                    hits.append(f"{rel}:{n}")
    return hits


def _flag_credential_assignments(texts: dict[str, str]) -> list[str]:
    """Tracked files that assign a generated secret to a credential-shaped name."""
    hits = []
    for rel, text in texts.items():
        for n, line in enumerate(text.splitlines(), 1):
            for m in CREDENTIAL_ASSIGNMENT.finditer(line):
                if m.group(2) not in PLACEHOLDER_VALUES and _looks_random(m.group(2)):
                    hits.append(f"{rel}:{n}")
    return hits


class TestNoCredentialLiteralInTheTree:
    def test_no_tracked_url_carries_a_literal_token(self):
        hits = _flag_auto_signed(_texts(PROJECT_ROOT))
        assert not hits, (
            "a credential is committed in a URL query — the auto-sign token belongs in "
            "AUTO_SIGN_TOKEN or scripts/agent/auto_sign_token.sh, never in a tracked "
            "file:\n  " + "\n  ".join(hits)
        )

    def test_no_tracked_file_assigns_a_generated_secret(self):
        hits = _flag_credential_assignments(_texts(PROJECT_ROOT))
        assert not hits, (
            "a credential-shaped name holds a generated secret — read it at runtime "
            "instead:\n  " + "\n  ".join(hits)
        )

    def test_the_evidence_files_redact_the_token_in_their_urls(self):
        for rel in EVIDENCE_FILES:
            text = (PROJECT_ROOT / rel).read_text()
            assert f"auto_signed={PLACEHOLDER}" in text, (
                f"{rel} must record the URL with a {PLACEHOLDER} placeholder — the "
                f"recorded URL is the evidence, the token in it is not"
            )

    def test_the_measure_scripts_read_the_token_at_runtime(self):
        for rel in MEASURE_SCRIPTS:
            text = (PROJECT_ROOT / rel).read_text()
            assert "auto_sign_token()" in text, (
                f"{rel} must read the token at runtime via scripts/_auto_sign.py"
            )
            assert "from _auto_sign import" in text, (
                f"{rel} must use the shared helper, not its own copy of the lookup"
            )


class TestTheScannerCatchesWhatItGuards:
    """The scanner is only worth having if it fires on the shape it was written for."""

    def test_it_flags_a_literal_in_a_url(self):
        hits = _flag_auto_signed({"a.json": '{"url": "?auto_signed=' + "a" * 64 + '"}'})
        assert hits == ["a.json:1"]

    def test_it_flags_a_secret_assigned_to_a_credential_name(self):
        hits = _flag_credential_assignments({"a.py": 'AUTO_SIGN = "' + "b1c2d3e4" * 8 + '"'})
        assert hits == ["a.py:1"]

    def test_it_leaves_a_placeholder_alone(self):
        assert not _flag_auto_signed({"a.json": f'"?auto_signed={PLACEHOLDER}"'})
        assert not _flag_credential_assignments({"a.py": 'AUTO_SIGN = "' + PLACEHOLDER + '"'})

    def test_it_leaves_a_readable_test_fixture_alone(self):
        assert not _flag_credential_assignments({"a.py": "API_KEY = 'unit-test-strong-key'"})


class TestTheAutoSignHelper:
    def test_redact_removes_the_token_from_a_url(self):
        token = "a" * 64
        out = redact(f"https://host/page?auto_signed={token}&tab=tests", token)
        assert token not in out
        assert out == f"https://host/page?auto_signed={PLACEHOLDER}&tab=tests"

    def test_redact_is_idempotent(self):
        token = "a" * 64
        once = redact(f"?auto_signed={token}", token)
        assert redact(once, token) == once

    def test_redact_removes_a_foreign_token_it_was_not_given(self):
        out = redact("https://host/page?auto_signed=" + "c" * 64, "b" * 64)
        assert "c" * 64 not in out
        assert out == f"https://host/page?auto_signed={PLACEHOLDER}"

    def test_the_environment_wins_over_the_fetch_script(self, monkeypatch):
        monkeypatch.setenv("AUTO_SIGN_TOKEN", "from-the-environment")
        assert auto_sign_token() == "from-the-environment"

    def test_without_a_token_it_fails_instead_of_guessing(self, monkeypatch):
        import _auto_sign

        monkeypatch.delenv("AUTO_SIGN_TOKEN", raising=False)
        monkeypatch.setattr(_auto_sign, "TOKEN_SCRIPT", Path("/nonexistent/auto_sign_token.sh"))
        with pytest.raises(SystemExit) as exc:
            auto_sign_token()
        message = str(exc.value)
        assert message, "the failure must say what is wrong"
        assert "AUTO_SIGN_TOKEN" in message, "the failure must name the way to supply it"
