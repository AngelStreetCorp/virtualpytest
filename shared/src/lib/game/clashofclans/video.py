"""
Per-cycle host-screen recording for the CoC farm bot (TASK-81 §81.1.9).

Mirrors the role of ``game_pokemon.runner.VptIO.js('() => vptGB.startRecording()')``:
a single continuous clip of the live device's screen for the whole
``run()``. Pokemon records via the Game Boy emulator; here we record
the Android device's screen via ``adb shell screenrecord``.

``adb screenrecord`` has a hard 3-minute cap on the hardware encoder,
so the recorder rotates every ``CHUNK_S`` (< 180 s) — terminate the
current process, ``adb pull`` the resulting chunk to a local dir,
start a new one. On stop the chunks are concatenated with ``ffmpeg
-f concat -c copy`` (loss-less) into one MP4.

Failure modes:

* no adb serial on the device         -> disabled, no record attempted
* ``adb screenrecord`` returns non-0  -> that chunk is dropped, next starts
* ``ffmpeg`` not on PATH              -> we keep the chunk files; the
                                         HTML report shows each chunk and
                                         ``concat`` is left for the host.

The recorder is intentionally not a runner-import blocker: every
public method returns early when the recorder is disabled. Tests
inject a fake recorder through ``runner.RunnerConfig.video_recorder``.
"""

from __future__ import annotations

import os
import subprocess
import time
from typing import Any, List, Optional


# Why 150? adb screenrecord's hard cap is 180 s on most encoders; 150
# gives us a 30 s grace before the chunk closes itself.
CHUNK_S = 150
SDCARD_TEMPLATE = "/sdcard/coc_rec_{n}.mp4"
LOCAL_CHUNK_DIR = "/var/lib/vpt/coc_frames/rec_chunks"


# ---------------------------------------------------------------------------
# adb helpers
# ---------------------------------------------------------------------------

def _adb_serial(device: Any) -> Optional[str]:
    """Best-effort lookup of the device's adb serial.

    Mirrors ``device_utils._try_adb_screenshot`` — both the AV
    controller path (preferred) and the raw ``adb -s <serial>`` path
    (used by the recorder) end up in the same place.
    """
    try:
        remote = device._get_controller("remote")
        if remote and getattr(remote, "adb_utils", None):
            serial = getattr(remote, "android_device_id", None)
            if serial:
                return serial
    except Exception:
        pass
    return None


def _which(name: str) -> Optional[str]:
    for d in os.environ.get("PATH", "").split(":"):
        c = os.path.join(d, name)
        if os.path.exists(c) and os.access(c, os.X_OK):
            return c
    return None


# ---------------------------------------------------------------------------
# VideoRecorder
# ---------------------------------------------------------------------------

class VideoRecorder:
    """One continuous recording across ``runner.run()``.

    Public surface:

        .start()           -- spawn the first chunk
        .maybe_rotate()     -- call from the runner loop; rotates when the
                                current chunk has run for ``CHUNK_S``
        .stop()             -- terminate, pull final chunk, concat
        .video_path         -- the final ``.mp4`` path or ``None`` on failure
        .chunks             -- list of pulled local chunk paths (in order)
        .disabled_reason    -- empty when recording; otherwise a human-readable
                                reason the recorder was disabled
    """

    def __init__(self, device: Any, run_id: str,
                 local_dir: str = LOCAL_CHUNK_DIR,
                 chunk_s: int = CHUNK_S,
                 screenrecord_cmd: Optional[List[str]] = None,
                 adb_pull_cmd: Optional[List[str]] = None):
        """``screenrecord_cmd`` and ``adb_pull_cmd`` are injected for tests
        so the recorder can be exercised without an actual adb process."""
        self._device = device
        self._run_id = run_id
        self._local_dir = local_dir
        self._chunk_s = chunk_s
        self._inject_screenrecord = screenrecord_cmd
        self._inject_pull = adb_pull_cmd
        self._chunk_index = 0
        self._popen = None
        self._started_at: Optional[float] = None
        self._local_chunks: List[str] = []
        self._disabled = False
        self._disabled_reason = ""
        self._serial: Optional[str] = None
        self._final_path: Optional[str] = None

    @property
    def is_active(self) -> bool:
        return self._popen is not None and self._popen.poll() is None

    @property
    def chunks(self) -> List[str]:
        return list(self._local_chunks)

    @property
    def video_path(self) -> Optional[str]:
        return self._final_path

    @property
    def disabled(self) -> bool:
        return self._disabled

    @property
    def disabled_reason(self) -> str:
        return self._disabled_reason

    # --- lifecycle ---------------------------------------------------------

    def start(self) -> bool:
        """Spawn the first chunk. Idempotent — calling start() on an
        already-active recorder is a no-op."""
        if self._disabled:
            return False
        if self.is_active:
            return True
        if self._serial is None:
            self._serial = _adb_serial(self._device)
        if not self._serial:
            self._disabled = True
            self._disabled_reason = "no adb serial for the device"
            return False
        os.makedirs(self._local_dir, exist_ok=True)
        return self._spawn_chunk()

    def _spawn_chunk(self) -> bool:
        """Spawn one screenrecord subprocess; on failure, mark disabled
        so subsequent calls short-circuit."""
        try:
            if self._inject_screenrecord is not None:
                # test mode: a callable returning a stand-in Popen-like object
                proc = self._inject_screenrecord(self._serial, self._chunk_index,
                                                 self._chunk_s)
            else:
                cmd = [
                    "adb", "-s", self._serial, "shell",
                    "screenrecord",
                    f"--time-limit={self._chunk_s}",
                    "--output-format=mp4",
                    SDCARD_TEMPLATE.format(n=self._chunk_index),
                ]
                proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL,
                                        stderr=subprocess.DEVNULL)
            self._popen = proc
            self._chunk_index += 1
            self._started_at = time.time()
            return True
        except Exception as e:
            self._disabled = True
            self._disabled_reason = f"screenrecord spawn failed: {e}"
            return False

    def _terminate_current(self) -> Optional[str]:
        """Stop the running screenrecord, wait for the chunk to finalize on
        sdcard, pull it to the local chunk dir. Returns the local path."""
        if self._popen is None:
            return None
        proc, self._popen = self._popen, None
        try:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
        except Exception:
            pass
        last = self._chunk_index - 1
        sdcard = SDCARD_TEMPLATE.format(n=last)
        local = os.path.join(self._local_dir, f"{self._run_id}_{last:03d}.mp4")
        if self._pull(self._serial, sdcard, local):
            self._local_chunks.append(local)
            return local
        return None

    def _pull(self, serial: str, sdcard_path: str, local_path: str) -> bool:
        """``adb pull <sdcard> <local>``. Test hook."""
        if self._inject_pull is not None:
            try:
                return bool(self._inject_pull(serial, sdcard_path, local_path))
            except Exception:
                return False
        try:
            out = subprocess.run(
                ["adb", "-s", serial, "pull", sdcard_path, local_path],
                capture_output=True, timeout=30,
            )
            return out.returncode == 0 and os.path.exists(local_path) \
                   and os.path.getsize(local_path) > 0
        except Exception:
            return False

    def maybe_rotate(self) -> Optional[str]:
        """Rotate the chunk when needed. Called from the runner loop
        after each cycle. Returns the local path of the just-pulled
        chunk (so the runner can attach it to the cycle's event log),
        or ``None`` when no rotation was needed.

        Invariant: after ``maybe_rotate`` the recorder is either
        ``disabled`` or has one active chunk, unless the disable path
        ran (no adb serial). Rotation is idempotent — calling it on
        every cycle is cheap when nothing has expired.
        """
        if self._disabled:
            return None
        rotated = False
        pulled = None
        if not self.is_active:
            # either we never started, or the previous screenrecord
            # finished itself (its own time-limit triggered). Pull what
            # is on sdcard and start a new chunk.
            pulled = self._terminate_current()
            self._spawn_chunk()
            return pulled
        if self._started_at is not None \
           and (time.time() - self._started_at) >= self._chunk_s:
            pulled = self._terminate_current()
            self._spawn_chunk()
            return pulled
        return None

    def stop(self) -> Optional[str]:
        """Final stop. Returns the path of the concatenated video, or
        ``None`` when no chunks were recorded or ffmpeg concat failed."""
        if self._disabled:
            return None
        # Pull whatever is still in flight
        self._terminate_current()
        if not self._local_chunks:
            return None
        out_path = os.path.join(self._local_dir, f"{self._run_id}.mp4")
        if len(self._local_chunks) == 1:
            try:
                os.rename(self._local_chunks[0], out_path)
                self._local_chunks = [out_path]
            except OSError:
                out_path = self._local_chunks[0]
            self._final_path = out_path
            return self._final_path
        # multiple chunks -> concat
        if not _ffmpeg_concat(self._local_chunks, out_path):
            # ffmpeg missing or concat failed; keep the chunks,
            # point video_path at the first chunk so the report at
            # least has something to show.
            self._final_path = self._local_chunks[0]
            return self._final_path
        self._final_path = out_path
        return self._final_path


def _ffmpeg_concat(chunks: List[str], out_path: str) -> bool:
    """Loss-less concat with ``ffmpeg -f concat -c copy``. Returns True on
    success. Falls back silently when ffmpeg isn't on PATH."""
    ffmpeg_bin = _which("ffmpeg")
    if not ffmpeg_bin:
        return False
    list_path = out_path + ".list.txt"
    try:
        with open(list_path, "w") as f:
            for c in chunks:
                # single-quote the path; sanitize internal single quotes
                f.write("file '" + c.replace("'", "'\\''") + "'\n")
        out = subprocess.run(
            [ffmpeg_bin, "-y", "-f", "concat", "-safe", "0",
             "-i", list_path, "-c", "copy", out_path],
            capture_output=True, timeout=180,
        )
        return (out.returncode == 0
                and os.path.exists(out_path)
                and os.path.getsize(out_path) > 0)
    except Exception:
        return False
    finally:
        try:
            os.unlink(list_path)
        except Exception:
            pass
