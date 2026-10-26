#!/usr/bin/env python3
"""vpt-monitor-img entry point (unit ExecStart is unchanged). The monitor lives in monitor/ (TASK-90)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

if __name__ == '__main__':
    # PC-host idle gate (BUG-0563). On a host whose every device runs `pc` (or any profile with
    # `services.img: false` — `tv_lite` and `caption_playback-when-no-img` included), this call loops
    # every 60 s, holding only the python interpreter: no OpenCV, no inotify-adapters, no model files,
    # no per-capture worker threads. Once a Settings save flips a device to a profile that needs img,
    # the next recheck returns the folder and the rest of the imports below load. This is the same
    # "service is needed?" decision the host orchestrator makes via
    # `apply_monitor_profiles`; both consult `folders_needing_service` in
    # `shared.src.lib.utils.monitor_profile`, so the per-device and the per-host decision can never
    # disagree. See `shared.src.lib.utils.monitor_service` module docstring for the full picture.
    from shared.src.lib.utils.monitor_service import wait_until_needed
    wait_until_needed('img', 'vpt-monitor-img')

from shared.src.lib.utils.tesseract_env import harden_pytesseract  # noqa: E402
harden_pytesseract()  # 1 OpenMP thread + reap timed-out tesseract children

from monitor.core import main  # noqa: E402

if __name__ == '__main__':
    main()
