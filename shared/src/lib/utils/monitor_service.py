"""Idle until a monitor profile needs this service (TASK-90 goal 6).

The five host services (vpt-monitor-img / -audio / -subtitle / -archiver / -kpi / -avq) are auto-starting
systemd units; they come up at boot whether or not any device on the host needs them. The savings happen
in three coordinated layers, all of which use the **same single source of truth**:
`shared.src.lib.utils.monitor_profile.folders_needing_service`. Changing a device's profile in the host
.env, or via Settings → Host & Devices, therefore cannot leave a service in an inconsistent state — the
imager, the audio unit and the host orchestrator (`apply_monitor_profiles`) all consult the same function.

1. **The service itself** (this file). `wait_until_needed()` is called at the top of each unit's
   `__main__` *before* the heavy imports (cv2, pytesseract, inotify-adapters, model files). On a host whose
   every device runs `pc` / `tv_lite` (or any profile with `services.<x>: false`), the imager process holds
   only the python interpreter — a few MB, no OpenCV, no workers, no inotify watches — and re-checks every
   `RECHECK_S` (60 s). When a Settings save flips a device to a profile that needs the service, the next
   60 s recheck returns the folder and the unit loads the rest of itself.

2. **The host orchestrator** (`backend_host.src.lib.utils.monitor_profile.apply_monitor_profiles`,
   triggered by `POST /host/system/config`). It compares `services` sets in the last-applied
   `/var/tmp/vpt_monitor_profiles_applied.json` with the desired set computed by
   `folders_needing_service_for_devices`, and decides which units to restart. A service whose device set
   shrunk to empty is *not* stopped here (the unit is left enabled and idles, per #1).

3. **The capture_filter** (`capture_monitor.py` line 1176 onwards). Inside the imager, even when the
   service is running because *some* device on the host needs img, the per-capture-dir filter in
   `folders_needing_service('img', [...])` skips every capture folder whose device's profile turns img
   off. No inotify watch, no per-capture frame worker, no per-capture incident worker is started for
   those folders. The result is on the wire in the journal: `Found 3 capture directories` and three
   `[capture<N>] Monitoring [HOT (RAM)]: ...` lines, even when the host has six devices.

The net effect: a host that wants no monitoring at all (every device on `pc` / `tv_lite`) pays only for
the python interpreter for each service; a mixed host pays for the services it needs and only the
device-side work for those that need them.

`wait_until_needed` returns the list of capture folders the service must handle, or sleeps while there
are none. A host with no capture folder at all is *not* idle: the service starts as before, because
that is the boot-time state of a fresh host before `run_ffmpeg.sh` has registered its devices.
"""
import logging
import os
import signal
import time
from typing import List

from shared.src.lib.utils.monitor_profile import folders_needing_service, reload_profile_env

logger = logging.getLogger('monitor_service')
RECHECK_S = 60


def capture_folders() -> List[str]:
    from shared.src.lib.utils.storage_path_utils import get_capture_base_directories
    return [os.path.basename(d) for d in get_capture_base_directories()]


def wait_until_needed(service: str, service_unit: str, recheck_s: float = RECHECK_S, sleep=time.sleep) -> List[str]:
    """Return the capture folders this service must handle, sleeping while there are none.

    The "this service is needed?" question is delegated to
    `shared.src.lib.utils.monitor_profile.folders_needing_service`, the same function the host
    orchestrator uses (see the module docstring). When a device's profile is `pc` / `tv_lite` (or any
    profile with `services.<this_service>: false`), that capture folder is filtered out here AND in
    the imager's per-directory filter, AND in `apply_monitor_profiles` — they cannot diverge.

    A host with no capture folder at all is *not* idle: the service starts as before and deals with it.
    That covers the boot-time state of a fresh host, before `run_ffmpeg.sh` has registered any device.
    """
    # `pkill -USR1 -f capture_monitor.py` toggles verbose logging, but its handler is installed only once the service
    # runs: until then the default action of SIGUSR1/2 would kill an idle service.
    for name in ('SIGUSR1', 'SIGUSR2'):
        if hasattr(signal, name):
            try:
                signal.signal(getattr(signal, name), signal.SIG_IGN)
            except ValueError:   # not the main thread
                pass
    if not logging.getLogger().handlers:
        logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
    announced = False
    while True:
        reload_profile_env()
        folders = capture_folders()
        needed = folders_needing_service(service, folders)
        if needed or not folders:
            if announced:
                logger.info("%s: a device needs it now, starting: %s", service_unit, needed)
            return needed
        if not announced:
            logger.info("%s idle: no device on this host has a profile that needs the %s service "
                        "(devices: %s); checking again every %ss", service_unit, service, folders, recheck_s)
            announced = True
        sleep(recheck_s)
