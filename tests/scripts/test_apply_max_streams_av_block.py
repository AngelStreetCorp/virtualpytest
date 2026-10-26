"""Regression test for the apply_max_streams.py device-block bug.

The 2026-10-17 incident (BUG-0583 follow-up):
  `apply_max_streams.py` wrote NAME/STREAM_TYPE/VIDEO/VIDEO_FPS/VIDEO_CAPTURE_PATH/
  VIDEO_STREAM_PATH but never wrote `DEVICE<N>_MODEL=rtsp_video` or
  `DEVICE<N>_STREAM_LOOP=1`. On nipogi, 8 of the 12 NEW devices ended up registered
  to the backend with `av=None`, which the /device-control page filters out — the
  operator saw 17 of 25 nipogi streams, the other 8 were silently invisible.

This test pins the contract: every NEW device block (REPLACE or APPEND) MUST
include the 8 env vars a tv_lite rtsp_video device needs to register with full
av capabilities. If the script ever drops one again, this test fails.
"""
import os
import re
import subprocess
import sys
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPT = os.path.join(REPO, "scripts", "apply_max_streams.py")


def _run_apply(text, host="vpt-test-fixture"):
    """Run apply() against an in-memory .env fixture. Returns the resulting text."""
    sys.path.insert(0, os.path.dirname(SCRIPT))
    import apply_max_streams as m
    # monkey-patch ssh to read/write local files instead
    m.ssh_run = lambda h, *a, capture=False: subprocess.CompletedProcess(
        args=(), returncode=0, stdout=text if capture else "", stderr=""
    )
    orig_write = m.write_env
    captured = {}
    def _capture(h, content):
        captured["text"] = content
    m.write_env = _capture
    m.apply(host, check_only=False)
    m.write_env = orig_write
    return captured.get("text", "")


class ApplyMaxStreamsBlock(unittest.TestCase):
    def test_new_block_has_all_required_vars(self):
        """Each NEW device (REPLACE or APPEND path) must include MODEL/STREAM_TYPE/STREAM_LOOP."""
        # Use REPLACE[5] (Pluto TV Histoire) so we exercise the REPLACE branch.
        # Then keep DEVICE25 (NEW[25]) with NAME/VIDEO but missing MODEL/STREAM_TYPE/STREAM_LOOP
        # to exercise the PATCH branch. Drop DEVICE25 from the next fixture to exercise APPEND.
        host_env = (
            "# initial\n"
            "DEVICE5_NAME=old Pluto TV Histoire\n"
            "DEVICE5_VIDEO=https://example.com/old.m3u8\n"
            "DEVICE5_VIDEO_CAPTURE_PATH=/var/www/html/stream/capture5\n"
            "DEVICE5_VIDEO_STREAM_PATH=/host/stream/capture5\n"
            "DEVICE25_NAME=existing but missing MODEL\n"
            "DEVICE25_VIDEO=https://jmp2.uk/plu-654a58dbf9cc82000868f0fb.m3u8\n"
            "DEVICE25_VIDEO_CAPTURE_PATH=/var/www/html/stream/capture25\n"
            "DEVICE25_VIDEO_STREAM_PATH=/host/stream/capture25\n"
        )
        out = _run_apply(host_env)
        # REPLACE: device5 must now have all 8 keys
        block5 = re.findall(r"^DEVICE5_(\w+)=", out, re.MULTILINE)
        for required in (
            "NAME", "MODEL", "STREAM_TYPE", "STREAM_LOOP",
            "VIDEO", "VIDEO_FPS", "VIDEO_CAPTURE_PATH", "VIDEO_STREAM_PATH",
        ):
            self.assertIn(required, block5, f"REPLACE block missing DEVICE5_{required}; got {block5}")
        self.assertEqual(block5[0], "NAME")  # ordering: NAME first
        # PATCH (existing but missing MODEL): device25 should get MODEL/STREAM_TYPE/STREAM_LOOP added
        block25 = re.findall(r"^DEVICE25_(\w+)=", out, re.MULTILINE)
        for required in ("MODEL", "STREAM_TYPE", "STREAM_LOOP"):
            self.assertIn(required, block25, f"PATCH missing DEVICE25_{required}; got {block25}")
        # APPEND path: device26 onwards are appended for indices not yet present
        block26_appended = re.findall(r"^DEVICE26_(\w+)=", out, re.MULTILINE)
        for required in (
            "NAME", "MODEL", "STREAM_TYPE", "STREAM_LOOP",
            "VIDEO", "VIDEO_FPS", "VIDEO_CAPTURE_PATH", "VIDEO_STREAM_PATH",
        ):
            self.assertIn(required, block26_appended,
                          f"APPEND block missing DEVICE26_{required}; got {block26_appended}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
