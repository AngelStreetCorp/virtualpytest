"""
Video File Stream Controller Implementation

This controller handles local-file or HTTP(S) video acquisition (mp4, mkv,
mov, ts, webm, avi, flv, m4v) by referencing continuously captured
screenshots. The host continuously takes screenshots using FFmpeg, and this
controller references them by timestamp. Uses shared FFmpeg-based capture
functionality, like HDMIStreamController.

Designed for smoke-test videos and regression captures: no capture card, no
mobile, no STB. The source is a file path or an HTTP(S) URL FFmpeg can read.
"""

from typing import Dict, Any, Optional
from ..base_controller import FFmpegCaptureController


class VideoFileStreamController(FFmpegCaptureController):
    """Local / HTTP(S) video file controller. Loop and on-demand modes."""

    def __init__(
        self,
        video_stream_path: str,
        video_capture_path: str,
        video_file_path: Optional[str] = None,
        loop: bool = True,
        **kwargs,
    ):
        """
        Initialize the Video File Stream controller.

        Args:
            video_stream_path: Stream path for URLs (e.g., "/host/stream/capture2")
            video_capture_path: Local capture path (e.g., "/var/www/html/stream/capture2")
            video_file_path: Absolute path or HTTP(S) URL of the video to play.
                Required. Examples:
                  - /var/www/html/videos/smoke.mp4
                  - https://example.com/clip.mp4
            loop: Default loop state. local_video defaults to True; can be
                changed at runtime via set_loop().
        """
        super().__init__("Video File Stream Controller", "VIDEO", video_stream_path, video_capture_path, **kwargs)

        self.video_file_path = video_file_path or ""
        self.loop = bool(loop)

        # A runtime override (load_or_download) outlives a vpt-host restart; report it.
        from shared.src.lib.utils.storage_path_utils import get_active_video_path_conf_path, read_source_override
        override = read_source_override(get_active_video_path_conf_path(), video_capture_path)
        if override and override[0]:
            self.video_file_path = override[0]

        if not self.video_file_path:
            print(
                f"VIDEO[{self.capture_source}]: WARNING - video_file_path is empty. "
                "Set DEVICE<n>_VIDEO (when STREAM_TYPE=videofile) or "
                f"video_file_path in the controller params."
            )
        else:
            print(
                f"VIDEO[{self.capture_source}]: file={self.video_file_path} loop={self.loop}"
            )

    def load_or_download(
        self,
        url_or_path: str,
        cache_dir: str = "/var/www/html/videos",
        timeout: int = 120,
        restart: bool = False,
    ) -> bool:
        """
        Load a local file, or download a URL to the cache dir and switch source
        (TASK-31 follow-up). Mirrors RTSPController.set_url() so both controllers
        can have their source flipped at runtime.

        Behavior:
          - If `url_or_path` is an existing filesystem path, switch to it directly.
          - If `url_or_path` looks like a URL (http://, https://, ftp://), derive a
            filename from the URL path and download to <cache_dir>/<filename>.
            On success, switch source to the downloaded file. On failure, return
            False without changing the source (the player keeps streaming the
            previous file).
          - Otherwise return False (no source change).

        The download is a plain `curl -fsSL` — no auth, no resume, no checksum.
        That matches the smoke / regression use case (Big Buck Bunny, hosted
        test videos). For authenticated downloads or large files this would
        need richer plumbing (auth headers, range / resume, progress events).

        Args:
            url_or_path: existing file path or HTTP(S)/FTP URL.
            cache_dir: where downloads land (default /var/www/html/videos).
            timeout: curl timeout in seconds (default 120).
            restart: also write a restart token (3rd field), so run_ffmpeg.sh restarts the
                device's ffmpeg even when the file is already playing: the film starts again
                from second 0 (TASK-50 subtitle QA needs a known start).

        Returns:
            True if the source was updated, False on error.
        """
        import os
        import re
        import subprocess

        if not url_or_path or not isinstance(url_or_path, str):
            print(f"VIDEO[{self.device_id}]: load_or_download: empty arg")
            return False

        # Existing local file? Use it.
        if os.path.exists(url_or_path):
            new_path = url_or_path
            print(f"VIDEO[{self.device_id}]: load_or_download: file exists at {new_path}")
        elif re.match(r"^(http|https|ftp)://", url_or_path):
            # Derive filename from URL.
            from urllib.parse import urlparse
            parsed = urlparse(url_or_path)
            base = os.path.basename(parsed.path) or "downloaded.bin"
            if "." not in base:
                base += ".mp4"
            new_path = os.path.join(cache_dir, base)

            try:
                os.makedirs(cache_dir, exist_ok=True)
            except Exception as e:
                print(f"VIDEO[{self.device_id}]: ERROR creating {cache_dir}: {e}")
                return False

            print(f"VIDEO[{self.device_id}]: load_or_download: downloading {url_or_path} → {new_path}")
            try:
                result = subprocess.run(
                    ["curl", "-fsSL", "--max-time", str(timeout), "-o", new_path, url_or_path],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if result.returncode != 0:
                    print(f"VIDEO[{self.device_id}]: ERROR curl failed (rc={result.returncode}): {result.stderr.strip()}")
                    return False
            except Exception as e:
                print(f"VIDEO[{self.device_id}]: ERROR download raised: {e}")
                return False

            if not os.path.exists(new_path) or os.path.getsize(new_path) == 0:
                print(f"VIDEO[{self.device_id}]: ERROR download produced empty file")
                return False
        else:
            print(f"VIDEO[{self.device_id}]: load_or_download: not a path or URL: {url_or_path!r}")
            return False

        # Write the override file so the watcher picks it up on its next tick.
        import re as _re
        config_file = "/var/www/html/stream/active_video_path.conf"
        target = os.path.normcase(os.path.normpath(self.video_capture_path))

        try:
            config_dir = os.path.dirname(config_file)
            if config_dir and not os.path.exists(config_dir):
                os.makedirs(config_dir, exist_ok=True)

            entries = []
            if os.path.exists(config_file):
                with open(config_file, "r") as f:
                    entries = [line.strip() for line in f if line.strip()]

            new_value = f"{self.video_capture_path},{new_path}"
            if restart:
                import time as _time
                new_value += f",{int(_time.time() * 1000)}"

            found = False
            for i, entry in enumerate(entries):
                parts = entry.split(",")
                if parts and os.path.normcase(os.path.normpath(parts[0])) == target:
                    entries[i] = new_value
                    found = True
                    break

            if not found:
                entries.append(new_value)

            with open(config_file, "w") as f:
                f.write("\n".join(entries) + "\n")

            # Update in-memory state so get_status() reflects the change immediately.
            self.video_file_path = new_path
            print(f"VIDEO[{self.device_id}]: file → {new_path}")
            return True
        except Exception as e:
            print(f"VIDEO[{self.device_id}]: ERROR writing path override: {e}")
            return False

    def set_loop(self, enabled: bool) -> bool:
        """Soft per-device loop toggle. Persisted in active_loop.conf; the
        vpt-stream watcher picks it up on the next 1 s tick."""
        import os
        from shared.src.lib.utils.storage_path_utils import get_active_loop_conf_path

        config_file = get_active_loop_conf_path()
        target = os.path.normcase(os.path.normpath(self.video_capture_path))
        enabled_str = "1" if enabled else "0"

        try:
            # Ensure the config file's parent dir exists (TASK-31: on a fresh install
            # /var/www/html/stream may not exist yet when the first set_loop call lands).
            config_dir = os.path.dirname(config_file)
            if config_dir and not os.path.exists(config_dir):
                os.makedirs(config_dir, exist_ok=True)

            entries = []
            if os.path.exists(config_file):
                with open(config_file, "r") as f:
                    entries = [line.strip() for line in f if line.strip()]

            found = False
            for i, entry in enumerate(entries):
                parts = entry.split(",")
                if len(parts) >= 2 and os.path.normcase(os.path.normpath(parts[0])) == target:
                    entries[i] = f"{parts[0]},{enabled_str}"
                    found = True
                    break

            if not found:
                entries.append(f"{self.video_capture_path},{enabled_str}")

            with open(config_file, "w") as f:
                f.write("\n".join(entries) + "\n")

            self.loop = bool(enabled)
            print(f"VIDEO[{self.device_id}]: loop → {enabled_str}")
            return True
        except Exception as e:
            print(f"VIDEO[{self.device_id}]: ERROR writing loop config: {e}")
            return False

    def get_loop(self) -> bool:
        return self.loop

    def play(self) -> bool:
        """Restart ffmpeg via the loop-config write the watcher reacts to."""
        print(f"VIDEO[{self.device_id}]: play() — watcher restarts on next tick")
        return self.set_loop(self.loop)  # touch the file; watcher restarts

    def stop(self) -> bool:
        """Soft stop: disable loop and let the file finish."""
        print(f"VIDEO[{self.device_id}]: stop() — disable loop, ffmpeg exits at EOF")
        return self.set_loop(False)

    def get_status(self) -> Dict[str, Any]:
        base = {
            "success": True,
            "controller_type": "av",
            "is_streaming": True,
            "is_capturing": getattr(self, "is_capturing_video", False),
            "capture_session_id": getattr(self, "capture_session_id", None),
            "message": "Video File controller",
        }
        base.update({
            "source_kind": "videofile",
            "source_url": self.video_file_path,
            "loop": self.loop,
            "is_live": False,
        })
        return base