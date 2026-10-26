"""Small helpers shared by core and the analyzers."""

# audio_status.json is rewritten every 5-10 s by vpt-monitor-audio's audio check.
AUDIO_STATUS_MAX_AGE_S = 60


def _format_volume_db(volume) -> str:
    """Render a mean volume for logs. None means the device captures no audio at all;
    formatting it with `:.1f` raises TypeError, and an f-string in a logger call is
    evaluated whatever the log level - inside the frame-save path that exception cost
    the frame its entire analysis JSON."""
    if volume is None:
        return 'N/A'
    try:
        return f"{volume:.1f}dB"
    except (TypeError, ValueError):
        return str(volume)
