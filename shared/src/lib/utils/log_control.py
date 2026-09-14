#!/usr/bin/env python3
"""
Runtime log-level control for the standalone host services
(capture_monitor / hot_cold_archiver / transcript_accumulator).

Why this exists
---------------
These services run on the live 5fps capture path. On the RPi capture nodes
(host*) the systemd journal lives on the SD card, so verbose per-frame
logging both contends with capture I/O on a slow device and wears the card.
We therefore run them at a quiet default and raise verbosity *only while
actively debugging* — without a restart, since restarting vpt-monitor /
vpt-stream drops capture.

Two controls, deliberately minimal (stdlib only, no extra thread/file watcher):

  1. Default level via env var, applied at startup:
       VPT_LOG_LEVEL=WARNING|INFO|DEBUG        (fleet-wide default)
     plus an optional service-specific override checked first
     (e.g. CAPTURE_MONITOR_LOG_LEVEL).

  2. Runtime toggle via Unix signals (NO restart):
       SIGUSR1 -> DEBUG (verbose)
       SIGUSR2 -> restore the configured default level

Trigger from a host shell (vpt_user has NOPASSWD pkill):

    sudo pkill -USR1 -f capture_monitor.py        # verbose ON
    sudo pkill -USR2 -f capture_monitor.py        # verbose OFF
    sudo pkill -USR1 -f hot_cold_archiver.py
    sudo pkill -USR1 -f transcript_accumulator.py

The level is set on the root logger. These services use
`logging.basicConfig(...)` + module loggers (`logging.getLogger(__name__)`)
that propagate to root, so the root level is the single effective gate.
"""
import logging
import os
import signal

logger = logging.getLogger(__name__)


def install_runtime_log_control(service_env: str = None, fallback: str = 'INFO') -> int:
    """Apply the env-configured default level and install the SIGUSR toggle.

    Args:
        service_env: optional service-specific env var name checked before
            the shared VPT_LOG_LEVEL (e.g. 'CAPTURE_MONITOR_LOG_LEVEL').
        fallback: level name used when no env var is set.

    Returns:
        The resolved default logging level (int).

    Must be called from the main thread — signal handlers can only be
    registered there. Call it once from each service's main()/entrypoint
    before the work loop starts.
    """
    level_name = fallback
    for name in (service_env, 'VPT_LOG_LEVEL'):
        if name and os.getenv(name):
            level_name = os.getenv(name)
            break
    level_name = level_name.upper()
    default_level = getattr(logging, level_name, logging.INFO)

    logging.getLogger().setLevel(default_level)

    def _to_debug(_signum, _frame):
        logging.getLogger().setLevel(logging.DEBUG)
        logger.warning("🔊 SIGUSR1 — log level → DEBUG (verbose). Send SIGUSR2 to restore.")

    def _to_default(_signum, _frame):
        logging.getLogger().setLevel(default_level)
        logger.warning("🔉 SIGUSR2 — log level → %s (configured default).", level_name)

    # SIGUSR1/SIGUSR2 only exist on POSIX. On Windows the names are absent
    # from the `signal` module entirely (AttributeError on attribute access),
    # so guard with hasattr before touching them — env default still applies.
    sig_usr1 = getattr(signal, 'SIGUSR1', None)
    sig_usr2 = getattr(signal, 'SIGUSR2', None)
    if sig_usr1 is None or sig_usr2 is None:
        logger.debug("SIGUSR log toggle not installed (platform has no SIGUSR1/2); env default applied")
        return default_level

    try:
        signal.signal(sig_usr1, _to_debug)
        signal.signal(sig_usr2, _to_default)
        logger.info("Runtime log control active: default=%s, SIGUSR1→DEBUG / SIGUSR2→default",
                    level_name)
    except (ValueError, OSError):
        # Not main thread / unsupported platform — env default still applied.
        logger.debug("SIGUSR log toggle not installed (non-main thread?); env default applied")

    return default_level
