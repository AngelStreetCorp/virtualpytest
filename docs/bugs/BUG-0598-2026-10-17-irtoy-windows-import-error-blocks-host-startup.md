# BUG-0598 — `import termios` in irtoy.py blocks vpt-host on Windows

## Problem

`backend_host/src/controllers/remote/irtoy.py` does `import termios` at the top
of the module. `termios` is a POSIX-only module — Python on Windows does not
ship it. `app.py` does `from controllers import *` at startup, so on a Windows
host (vpt-windows, the lab Windows box, any win32 native install), backend_host
exits with:

```
❌ Failed to import dependencies: No module named 'termios'
❌ Please ensure shared library and backend_host are properly installed
❌ Run: ./setup/local/install_all.sh
```

before it ever binds port 6109. The host then can't register against the
server, so it does not show up in `getAllHosts` and the dashboard sees no
Windows devices. Symptoms:

- `Get-NetTCPConnection -LocalPort 6109` empty after a wrapper restart
- `host.log` ends at "Starting hardware interface on port 6109" with no
  Flask "Running on" banner
- `vpt-windows` host missing from `GET /server/system/getAllHosts`

The same blast radius applies to any other Windows native install
(host_vnc on Windows, an ADB runner on Windows, …). Anything that imports
the controllers package trips the same error.

## Fix

`backend_host/src/controllers/remote/irtoy.py` — gate POSIX imports on
`sys.platform != "win32"`, expose a tiny stub for the baud constant, and
have `IRToyRemoteController.__init__` raise `NotImplementedError` on Windows
(since USB IR Toy is a Linux-only path). On Linux/macOS the module is
unchanged; on Windows it imports cleanly with `_IRTOY_SUPPORTED = False`.

The fix is the minimal change that keeps the POSIX path bit-for-bit
identical while unblocking Windows.

```python
import sys
# ...
if sys.platform == "win32":
    _IRTOY_SUPPORTED = False
    class _TermiosStub:
        B115200 = 115200
    termios = _TermiosStub()  # type: ignore[assignment]
    select = None             # type: ignore[assignment]
    tty = None                # type: ignore[assignment]
else:
    _IRTOY_SUPPORTED = True
    import select
    import termios
    import tty
```

```python
def __init__(self, ...):
    if not _IRTOY_SUPPORTED:
        raise NotImplementedError(
            "IRToyRemoteController requires POSIX termios (Linux/macOS). "
            f"Current platform is {sys.platform}; use IRRemoteController, "
            "IRTransRemoteController, or a different remote backend."
        )
    super().__init__(...)
```

## Verification

- vpt-windows (Windows 11 native install at `C:\virtualpytest\virtualpytest`):
  - `python -c "from backend_host.src.controllers.remote import irtoy; print(irtoy._IRTOY_SUPPORTED)"` → `False`
  - `host_wrapper.ps1` starts `app.py`, binds `0.0.0.0:6109`, registers against vpt-pi4
  - `GET /server/system/getAllHosts` on vpt-pi4 now lists `vpt-windows` with
    `device_count=2` (Host_Windows + Mobile_Emulator), alongside the
    pre-existing `vpt-pi4` (4), `vpt-lenovo1` (7), and `vpt-nipogi` (24)
- vpt-pi4 / vpt-lenovo1 / vpt-nipogi (all Linux) — unchanged, `_IRTOY_SUPPORTED`
  remains `True` and the controller behaviour matches the prior build.

## Side note

While debugging this, the vpt-windows install also had its `.env` reverted to
`.env.example` defaults (`HOST_NAME=MyHost`, `SERVER_URL=http://localhost:5109`,
`API_KEY=CHANGE_ME`). That happened before this session and is unrelated to
the termios bug — but the dashboard wouldn't have shown vpt-windows until both
the termios import was fixed **and** the right `.env` was restored. The fix
script lives at `scripts/_restore_env.ps1` (gitignored, debug helper).