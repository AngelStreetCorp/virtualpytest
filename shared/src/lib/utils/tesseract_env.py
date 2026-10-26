"""The environment every tesseract subprocess runs with: one OpenMP thread.

tesseract is linked against libgomp and starts nproc threads by default. On a loaded host
(vpt-pi1, 2026-10-04: 4 cores at load 8-10 from ffmpeg, the capture monitor and whisper) those
threads spin at barriers waiting for cores, so a 380x75 crop took 0.2 s to 7.3 s and a check's
p99 was 21.7 s (max 31 s, the subprocess timeout). Single-threaded, the same crop takes 0.19 s
flat and the full frame 0.7 s, with identical output (BUG-0274).
"""
import os
import threading


def tesseract_env() -> dict:
    return {**os.environ, 'OMP_THREAD_LIMIT': '1'}


def harden_pytesseract() -> None:
    """Process-wide tesseract fixes for long-running monitors that call pytesseract.

    1. One OpenMP thread (see above): set in os.environ because pytesseract inherits it.
    2. Reap on timeout. pytesseract's kill() does terminate(), wait(1), kill() and then forces
       `returncode`, so the killed child is never waited for: a zombie per `timeout=` hit, until
       the monitor restarts (vpt-pi1 subtitle_monitor, 14 defunct tesseract, 2026-10-15).
       A child that is still not gone 3 s after SIGKILL (stuck in uninterruptible I/O on a loaded
       Pi) is left to a waiter thread instead of being marked done: marking it done is what still
       leaked 579 zombies on vpt-pi1 in a week (BUG-0939).
    """
    os.environ['OMP_THREAD_LIMIT'] = '1'
    try:
        from pytesseract import pytesseract as _pt
    except ImportError:
        return

    def kill(process, code):
        process.terminate()
        try:
            process.wait(1)
        except Exception:
            process.kill()
            try:
                process.wait(2)
            except Exception:
                threading.Thread(target=process.wait, daemon=True, name='tesseract-reaper').start()
                return
        process.returncode = code

    _pt.kill = kill
