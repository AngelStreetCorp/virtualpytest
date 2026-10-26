"""The auto-sign test token, read at runtime — never stored in the repo.

The token is a team-admin credential: it bypasses authentication on every VirtualPyTest
page and API. It lives in the main backend server's .env and is fetched with
scripts/agent/auto_sign_token.sh, so a script that needs it must read it at runtime and
must never write it into a tracked file, a log, a screenshot or a report.

Two rules follow from that, and both are enforced here rather than at each call site:
  - the token is returned to the caller, never printed by this module;
  - `redact()` replaces it with a placeholder in anything on its way to stdout or a file,
    because these scripts build `?auto_signed=<token>` URLs and those URLs end up in
    the evidence they record. That is how the token once ended up in committed JSON.
"""
import os
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TOKEN_SCRIPT = REPO_ROOT / "scripts" / "agent" / "auto_sign_token.sh"
PLACEHOLDER = "<AUTO_SIGN_TOKEN>"


def auto_sign_token() -> str:
    """The live token: AUTO_SIGN_TOKEN from the environment, else the fetch script.

    Exits with a message that names the two ways to supply it and carries no token.
    """
    token = (os.environ.get("AUTO_SIGN_TOKEN") or "").strip()
    if token:
        return token
    try:
        proc = subprocess.run([str(TOKEN_SCRIPT)], capture_output=True, text=True, timeout=120)
    except OSError as exc:
        sys.exit(f"error: cannot run {TOKEN_SCRIPT}: {exc}. Export AUTO_SIGN_TOKEN, "
                 f"or make {TOKEN_SCRIPT} work.")
    token = (proc.stdout or "").strip()
    if proc.returncode != 0 or not token:
        sys.exit(f"error: could not read the auto-sign token. Export AUTO_SIGN_TOKEN, "
                 f"or make {TOKEN_SCRIPT} work (it reads the token from the backend "
                 f"server's .env over ssh).")
    return token


def redact(text: object, token: str) -> str:
    """The token replaced by a placeholder — for anything printed or written.

    Also catches an `auto_signed=` value that is not the token (a token from another
    deployment, or a stale one), so a URL never carries a credential-looking value out.
    """
    out = str(text)
    if token:
        out = out.replace(token, PLACEHOLDER)
    return re.sub(r"(auto_signed=)[^&\s\"'<>]+", r"\1" + PLACEHOLDER, out)
