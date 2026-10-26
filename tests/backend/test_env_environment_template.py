"""The ENVIRONMENT label a fresh install starts with (BUG-0783).

The Settings page shows every key of the server's .env, so the ENVIRONMENT key
ships in the install templates and is what an operator reads on the live
platform. The production template must not start a public install as
"development"; the local one must keep "development".
"""
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

VM_BACKEND = REPO / "setup" / "proxmox" / "vm" / "backend-server"
RUNNER_INSTALLER = REPO / "setup" / "proxmox" / "vm" / "runner" / "install_runner.sh"


def _env_value(path: Path, key: str) -> str:
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("#") or not stripped:
            continue
        match = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$", stripped)
        if match and match.group(1) == key:
            return match.group(2)
    raise AssertionError(f"{key} is not set in {path}")


def test_production_template_says_production():
    assert _env_value(VM_BACKEND / ".env.server.example", "ENVIRONMENT") == "production"


def test_local_template_says_development():
    assert _env_value(VM_BACKEND / ".env.server.local.example", "ENVIRONMENT") == "development"


def test_runner_installer_says_production():
    assert _env_value(RUNNER_INSTALLER, "ENVIRONMENT") == "production"
