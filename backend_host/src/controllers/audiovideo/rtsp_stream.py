"""
RTSP Stream Controller Implementation

This controller handles network-stream acquisition (RTSP, HLS, MJPEG, public
IPTV feeds) by referencing continuously captured screenshots. The host
continuously takes screenshots using FFmpeg, and this controller references
them by timestamp. Uses shared FFmpeg-based capture functionality, like
HDMIStreamController and VNCStreamController.

Source types this controller can drive, set via DEVICE{i}_STREAM_TYPE:
  - rtsp   : rtsp://… (IP cameras, public test streams, IPTV)
  - hls    : .m3u8 URLs, including those resolved from YouTube / Twitch
             by the optional `yt-dlp` resolver (DEVICE{i}_YOUTUBE_URL)
  - mjpeg  : HTTP MJPEG streams (axis-cgi/mjpg/video.cgi, etc.)
"""

from typing import Dict, Any, Optional
from ..base_controller import FFmpegCaptureController


class RTSPStreamController(FFmpegCaptureController):
    """RTSP / HLS / MJPEG stream controller. Loop and on-demand modes."""

    def __init__(
        self,
        video_stream_path: str,
        video_capture_path: str,
        rtsp_url: Optional[str] = None,
        hls_url: Optional[str] = None,
        mjpeg_url: Optional[str] = None,
        youtube_url: Optional[str] = None,
        loop: bool = True,
        **kwargs,
    ):
        """
        Initialize the RTSP Stream controller.

        Args:
            video_stream_path: Stream path for URLs (e.g., "/host/stream/capture1")
            video_capture_path: Local capture path (e.g., "/var/www/html/stream/capture1")
            rtsp_url: Source URL — rtsp:// or rtsps://
            hls_url: Source URL — http(s)://…m3u8 (HLS playlist)
            mjpeg_url: Source URL — HTTP MJPEG multipart stream
            youtube_url: Optional. If set, the vpt-stream watcher resolves this
                through `yt-dlp --get-url` and the resulting URL is fed to
                FFmpeg. Requires `yt-dlp` on PATH.
            loop: Default loop state. rtsp_video defaults to True; can be
                changed at runtime via set_loop().
        """
        super().__init__("RTSP Stream Controller", "RTSP", video_stream_path, video_capture_path, **kwargs)

        # Pick the first non-empty source. The vpt-stream watcher sets
        # DEVICE{i}_VIDEO to the resolved URL after yt-dlp expansion, so this
        # controller sees only the final input — no yt-dlp dependency here.
        self.source_url = rtsp_url or hls_url or mjpeg_url or youtube_url or ""
        self.stream_kind = (
            "rtsp" if rtsp_url else
            "hls" if hls_url else
            "mjpeg" if mjpeg_url else
            "youtube" if youtube_url else
            "unknown"
        )
        self.loop = bool(loop)
        self.youtube_url = youtube_url  # kept for status reporting

        # A runtime override (set_url) outlives a vpt-host restart; report it.
        from shared.src.lib.utils.storage_path_utils import get_active_rtsp_url_conf_path, read_source_override
        override = read_source_override(get_active_rtsp_url_conf_path(), video_capture_path)
        if override and override[0]:
            self.source_url = override[0]
            self.youtube_url = override[1] if len(override) > 1 and override[1] else None
            self.stream_kind = "youtube" if self.youtube_url else "rtsp" if self.source_url.startswith("rtsp") else "hls"

        if self.source_url:
            print(
                f"RTSP[{self.capture_source}]: source={self.stream_kind} "
                f"loop={self.loop} url={self.source_url}"
            )
        else:
            print(
                f"RTSP[{self.capture_source}]: WARNING - no source URL configured "
                f"(rtsp_url/hls_url/mjpeg_url/youtube_url all empty)"
            )

    def set_url(self, new_url: str, youtube_url: Optional[str] = None) -> bool:
        """
        Update the source URL at runtime (TASK-31 follow-up).

        Writes the new URL to a per-device override file that the vpt-stream
        watcher reads on its next 1 s tick. The watcher then kills the current
        ffmpeg child and starts a new one with the new source. Old HLS segments
        keep playing for ~1 s while the new pipeline warms up; the player
    transparently retries.

        The override file is <stream_base_path>/active_rtsp_url.conf with CSV
    format `<capture_path>,<url>[,<youtube_url>]`. Both files (this and
        active_loop.conf) live alongside active_captures.conf so the watcher
        sees them with one readdir.

        Args:
            new_url: rtsp://, rtsps://, https:// (HLS), or http:// (MJPEG) URL.
                Must be detectable by detect_source_type().
            youtube_url: Optional YouTube watch URL. If set, the watcher
                resolves this through yt-dlp and the resolved URL is what
                ffmpeg consumes (matches the DEVICE{i}_YOUTUBE_URL flow).

        Returns:
            True on success, False on filesystem or arg error.
        """
        import os
        import re
        from shared.src.lib.utils.storage_path_utils import get_active_rtsp_url_conf_path

        # Validate: must be a non-empty string that looks like a URL.
        if not new_url or not isinstance(new_url, str):
            print(f"RTSP[{self.device_id}]: set_url: empty url")
            return False
        if not re.match(r"^(rtsp|rtsps|http|https)://", new_url):
            print(f"RTSP[{self.device_id}]: set_url: bad scheme in {new_url!r}")
            return False

        config_file = get_active_rtsp_url_conf_path()
        target = os.path.normcase(os.path.normpath(self.video_capture_path))

        try:
            config_dir = os.path.dirname(config_file)
            if config_dir and not os.path.exists(config_dir):
                os.makedirs(config_dir, exist_ok=True)

            entries = []
            if os.path.exists(config_file):
                with open(config_file, "r") as f:
                    entries = [line.strip() for line in f if line.strip()]

            new_value = f"{self.video_capture_path},{new_url}"
            if youtube_url:
                new_value += f",{youtube_url}"

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
            self.source_url = new_url
            self.youtube_url = youtube_url
            print(f"RTSP[{self.device_id}]: url → {new_url!r}")
            return True
        except Exception as e:
            print(f"RTSP[{self.device_id}]: ERROR writing url override: {e}")
            return False

    def set_loop(self, enabled: bool) -> bool:
        """
        Soft per-device loop toggle. Persisted in active_loop.conf and picked up
        on the next 1 s watcher tick. Returns True on write, False on failure.

        The watcher kills the current ffmpeg child and starts a new one with
        -stream_loop -1 (enabled) or no -stream_loop (disabled, plays once).
        """
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
            print(f"RTSP[{self.device_id}]: loop → {enabled_str}")
            return True
        except Exception as e:
            print(f"RTSP[{self.device_id}]: ERROR writing loop config: {e}")
            return False

    def get_loop(self) -> bool:
        """Return the in-memory loop state. Re-reads the file at watcher tick."""
        return self.loop

    def play(self) -> bool:
        """
        Start playback. For an RTSP feed this is a no-op (the watcher is
        already running it); for on-demand HLS / file sources the watcher
        picks up the next tick and starts a new ffmpeg child. Returns True.
        """
        print(f"RTSP[{self.device_id}]: play() — watcher handles restart")
        return True

    def stop(self) -> bool:
        """
        Soft stop: write loop=0 so the watcher does not restart us when the
        source ends, and let the existing ffmpeg child finish naturally.
        """
        print(f"RTSP[{self.device_id}]: stop() — disable loop, ffmpeg exits when source ends")
        return self.set_loop(False)

    def _youtube_now_playing(self) -> Optional[str]:
        """Video vpt-stream is playing for a YouTube source, e.g. "https://www.youtube.com/watch?v=ID 3/9"
        for a playlist entry (run_ffmpeg.sh youtube_resolve writes it), or None."""
        if not self.youtube_url:
            return None
        import os
        try:
            with open(os.path.join(self.video_capture_path, "youtube_now_playing.txt")) as f:
                return f.read().strip() or None
        except OSError:
            return None

    def get_status(self) -> Dict[str, Any]:
        """Extend the base status with source + loop info."""
        base = super().get_status() if hasattr(super(), "get_status") else {}
        # FFmpegCaptureController has no get_status; build from state.
        base = {
            "success": True,
            "controller_type": "av",
            "is_streaming": True,  # RTSP is "always streaming" if the watcher is up
            "is_capturing": getattr(self, "is_capturing_video", False),
            "capture_session_id": getattr(self, "capture_session_id", None),
            "message": "RTSP controller",
        }
        base.update({
            "source_kind": self.stream_kind,
            "source_url": self.source_url,
            "youtube_url": self.youtube_url,
            "youtube_now_playing": self._youtube_now_playing(),
            "loop": self.loop,
            "is_live": self.stream_kind in ("rtsp", "mjpeg"),
        })
        return base