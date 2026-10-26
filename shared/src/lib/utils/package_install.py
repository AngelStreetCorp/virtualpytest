"""
The one ready command that installs missing tools with this machine's package manager (TASK-128 G10).

Platform update step 0 (``tools`` check) names the tools a machine lacks. Installing a package needs root, which the
update's sudoers drop-in deliberately does not give, so the app never runs the install: it shows the line to copy.
Detection runs on the machine itself (the host reports ``pkg_manager`` in ``updatePrereqs``; the server detects locally).
"""

import shutil
from typing import Callable, Dict, Iterable, List, Optional

# Order matters only when a box has several (a Debian image with a dnf shim is not a thing, but be deterministic).
PACKAGE_MANAGERS = ('apt-get', 'dnf', 'apk', 'pacman')

# tool name -> package name, per manager. A tool missing from a table is installed under its own name.
TOOL_PACKAGES: Dict[str, Dict[str, str]] = {
    'apt-get': {},
    'dnf': {},
    'apk': {},
    'pacman': {'python3': 'python'},
}

# Install verb, with the flags that make it non-interactive.
_INSTALL: Dict[str, str] = {
    'apt-get': 'apt-get install -y',
    'dnf': 'dnf install -y',
    'apk': 'apk add',
    'pacman': 'pacman -S --noconfirm',
}


def detect(which: Callable[[str], Optional[str]] = shutil.which) -> str:
    """The package manager found on PATH, or '' when none of the supported ones is."""
    for name in PACKAGE_MANAGERS:
        if which(name):
            return name
    return ''


def packages_for(manager: str, tools: Iterable[str]) -> List[str]:
    """Package names for the tools, de-duplicated, in the order given."""
    table = TOOL_PACKAGES.get(manager, {})
    out: List[str] = []
    for tool in tools:
        pkg = table.get(tool, tool)
        if pkg not in out:
            out.append(pkg)
    return out


def install_command(manager: str, tools: Iterable[str]) -> str:
    """``sudo apt-get install -y rsync zip`` for the missing tools; '' when the manager is unknown or nothing is missing.
    When ``sudo`` itself is missing the line has no ``sudo`` prefix: it must be run as root."""
    tools = list(tools)
    if manager not in _INSTALL or not tools:
        return ''
    prefix = '' if 'sudo' in tools else 'sudo '
    return f'{prefix}{_INSTALL[manager]} {" ".join(packages_for(manager, tools))}'
