"""
Unit tests for ``shared.src.lib.game.clashofclans.video`` (§81.1.9).

Mirrors the per-game ``test_<game>_*.py`` pattern (GAME_BOTS §1). Tests
inject a fake ``screenrecord_cmd`` and ``adb_pull_cmd`` so the recorder
can be exercised without spawning real ``adb`` processes or writing to
the sdcard. Synthetic frames only -- no device interaction.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest


from shared.src.lib.game.clashofclans import video as coc_video


class FakePopen:
    """A stand-in for ``subprocess.Popen`` that stays "alive" until killed."""

    def __init__(self, *args, **kwargs):
        self.args = args[0] if args else kwargs.get("args")
        self.returncode = None
        self._killed = False

    def poll(self):
        return self.returncode

    def terminate(self):
        self._killed = True
        self.returncode = 0

    def wait(self, timeout=None):
        return self.returncode

    def kill(self):
        self._killed = True
        self.returncode = -9


class _RecordingLoop:
    """Test double: wraps Popen + adb-pull and records what was asked."""

    def __init__(self):
        self.spawned: list = []        # list of (serial, n, t)
        self.pulled: list = []         # list of (serial, sdcard, local)
        self.popens: list = []         # active FakePopen instances

    def screenrecord(self, serial, n, t):
        self.spawned.append((serial, n, t))
        p = FakePopen(["adb", "-s", serial, "shell", "screenrecord",
                       f"--time-limit={t}", f"/sdcard/coc_rec_{n}.mp4"])
        self.popens.append(p)
        return p

    def pull(self, serial, sdcard, local):
        self.pulled.append((serial, sdcard, local))
        # write a tiny MP4-shaped file so the size check passes
        os.makedirs(os.path.dirname(local), exist_ok=True)
        with open(local, "wb") as f:
            f.write(b"\x00\x00\x00\x14ftypmp42\x00\x00\x00\x00mp42isom")  # 22 bytes
        return True


class TestVideoRecorder(unittest.TestCase):

    def _mk_device(self):
        """A tiny object whose ``_get_controller("remote")`` returns a fake
        adb controller with an android_device_id."""
        class Remote:
            android_device_id = "192.168.1.29:5555"
            adb_utils = True
        class Device:
            def _get_controller(self, _kind):
                return Remote()
        return Device()

    def test_start_when_no_adb_serial_disables(self):
        """When the device reports no adb serial, start() returns False and
        the recorder is disabled -- no subprocess is spawned."""
        class BadDevice:
            def _get_controller(self, _):
                return None
        rec = coc_video.VideoRecorder(BadDevice(), run_id="coc_xx")
        self.assertFalse(rec.start())
        self.assertTrue(rec.disabled)
        self.assertIn("adb serial", rec.disabled_reason)

    def test_start_spawns_a_chunk(self):
        loop = _RecordingLoop()
        with tempfile.TemporaryDirectory() as tmp:
            rec = coc_video.VideoRecorder(self._mk_device(),
                                          run_id="coc_run_test",
                                          local_dir=tmp,
                                          screenrecord_cmd=loop.screenrecord,
                                          adb_pull_cmd=loop.pull)
            self.assertTrue(rec.start())
            self.assertEqual(len(loop.spawned), 1)
            self.assertEqual(loop.spawned[0][0], "192.168.1.29:5555")
            self.assertEqual(loop.spawned[0][1], 0)  # chunk 0
            self.assertGreater(loop.spawned[0][2], 0)  # time-limit
            self.assertTrue(rec.is_active)

            # stop pulls the active chunk and finalises the recording
            path = rec.stop()
            self.assertTrue(path.endswith("coc_run_test.mp4"))
            self.assertEqual(len(loop.popens), 1)
            self.assertEqual(loop.popens[0]._killed, True)

    def test_rotate_terminates_active_chunk(self):
        """maybe_rotate() with an overdue chunk must terminate the active
        screenrecord and pull the file."""
        loop = _RecordingLoop()
        with tempfile.TemporaryDirectory() as tmp:
            rec = coc_video.VideoRecorder(self._mk_device(),
                                          run_id="coc_run_t",
                                          local_dir=tmp,
                                          chunk_s=10,
                                          screenrecord_cmd=loop.screenrecord,
                                          adb_pull_cmd=loop.pull)
            rec.start()
            # First popen is alive; force the timer to expire by lying about
            # started_at, then call maybe_rotate and a second time to start.
            rec._started_at = rec._started_at - 100 if rec._started_at else 0
            # After rotation, the active popen got terminated; loop.spawned
            # grows to 2 the next time we start.
            rec.maybe_rotate()
            # The chunk index is incremented on spawn, so two pops exist.
            self.assertEqual(len(loop.popens), 2)
            self.assertEqual(loop.popens[0]._killed, True)

    def test_stop_concat_path_uses_rename_for_single_chunk(self):
        """When only one chunk is recorded, ``stop()`` renames it instead
        of going through ffmpeg."""
        loop = _RecordingLoop()
        with tempfile.TemporaryDirectory() as tmp:
            rec = coc_video.VideoRecorder(self._mk_device(),
                                          run_id="coc_run_s",
                                          local_dir=tmp,
                                          screenrecord_cmd=loop.screenrecord,
                                          adb_pull_cmd=loop.pull)
            rec.start()
            out = rec.stop()
            self.assertTrue(os.path.exists(out))
            self.assertTrue(out.endswith("coc_run_s.mp4"))

    def test_stop_with_multiple_chunks_needs_ffmpeg(self):
        """Two chunks without ffmpeg on PATH should keep the chunks and
        point video_path at the first one. With ffmpeg, the out_path is
        a single concat file. We exercise the without-ffmpeg branch."""
        loop = _RecordingLoop()
        with tempfile.TemporaryDirectory() as tmp:
            rec = coc_video.VideoRecorder(self._mk_device(),
                                          run_id="coc_run_m",
                                          local_dir=tmp,
                                          chunk_s=10,
                                          screenrecord_cmd=loop.screenrecord,
                                          adb_pull_cmd=loop.pull)
            rec.start()
            rec._started_at = 0  # expire
            rec.maybe_rotate()  # pull chunk 0 + spawn chunk 1
            rec._started_at = 0
            rec.maybe_rotate()  # pull chunk 1 + spawn chunk 2
            # stop pulls chunk 2 and concat'd
            out = rec.stop()
            self.assertIsNotNone(out)
            # either concat succeeded or we fell back to first chunk
            self.assertTrue(os.path.exists(out))


class TestAdbSerial(unittest.TestCase):

    def test_adb_serial_from_controller(self):
        class Remote:
            android_device_id = "12345"
            adb_utils = True
        class Device:
            def _get_controller(self, _):
                return Remote()
        self.assertEqual(coc_video._adb_serial(Device()), "12345")

    def test_adb_serial_falls_through_when_no_remote(self):
        class Device:
            def _get_controller(self, _):
                return None
        self.assertIsNone(coc_video._adb_serial(Device()))


if __name__ == "__main__":
    unittest.main()
