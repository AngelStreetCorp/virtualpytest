"""
Give git an HTTPS token without ever putting it in argv, the remote URL or a log line (TASK-101).

GitHub git-over-HTTPS wants Basic auth: user ``x-access-token``, password = the token. (A
``http.extraHeader=Authorization: Bearer ...`` is wrong for it, and puts the token in ``ps``.) The token
travels through a ``GIT_ASKPASS`` script written 0700 into a private 0700 directory that is removed when the
``with`` block ends.

    with askpass_env(token) as env:
        subprocess.run(['git', 'ls-remote', url], env={**os.environ, **env})

Used by the prerequisites check, the bundle builder (core and overlay clones) and the source listing.
"""

import contextlib
import json
import os
import shutil
import tempfile
from typing import Callable, Dict, Iterator, Mapping, Optional
from urllib.parse import urlparse

GITHUB_USER = 'x-access-token'


_token_provider: Optional[Callable[[], str]] = None


def set_token_provider(provider: Optional[Callable[[], str]]) -> None:
    """Platform update registers its settings resolver (TASK-128 G9): the saved GitHub token wins over the .env ones."""
    global _token_provider
    _token_provider = provider


def github_token(env: Optional[Mapping[str, str]] = None) -> str:
    """The saved Platform update token (when a provider is registered and ``env`` is the process one), else
    ``VPT_GITHUB_TOKEN``, else ``GITHUB_TOKEN`` (what the server .env usually carries)."""
    if env is None and _token_provider is not None:
        try:
            saved = (_token_provider() or '').strip()
        except Exception:
            saved = ''
        if saved:
            return saved
    env = os.environ if env is None else env
    return (env.get('VPT_GITHUB_TOKEN') or env.get('GITHUB_TOKEN') or '').strip()


def is_github_url(url: str) -> bool:
    return (urlparse(url or '').hostname or '').lower() in ('github.com', 'www.github.com')


def write_askpass(path: str, username: str, token: str) -> None:
    # Created 0700 from the start (O_EXCL: never reuse a path): a write-then-chmod leaves a window
    # where the token sits in a file other users can read.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o700)
    with os.fdopen(fd, 'w') as f:
        f.write('#!/bin/sh\n'
                'case "$1" in\n'
                f'  *Username*) printf %s {json.dumps(username)} ;;\n'
                f'  *)         printf %s {json.dumps(token)} ;;\n'
                'esac\n')


def git_env(script: str) -> Dict[str, str]:
    return {'GIT_TERMINAL_PROMPT': '0', 'GIT_ASKPASS': script, 'GIT_ASKPASS_REQUIRE': 'force'}


@contextlib.contextmanager
def askpass_env(token: str, username: str = GITHUB_USER) -> Iterator[Dict[str, str]]:
    """Env additions that make git answer its prompts with ``username``/``token``. Without a token it
    yields only ``GIT_TERMINAL_PROMPT=0`` (a public repo needs none; a private one fails, never hangs)."""
    if not token:
        yield {'GIT_TERMINAL_PROMPT': '0'}
        return
    scratch = tempfile.mkdtemp(prefix='vpt-askpass-')       # mkdtemp is 0700
    try:
        script = os.path.join(scratch, 'askpass')
        write_askpass(script, username, token)
        yield git_env(script)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
