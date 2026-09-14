"""
Tests for server_restart_routes.py (/server/restart/*)

Every endpoint on this blueprint proxies to a host restart controller that
generates/analyzes/dubs real video and audio files (some with 5-10 minute
timeouts), i.e. it triggers real, expensive, side-effecting work on a live
device/host. There is no safe read-only or pure-validation endpoint here
that doesn't risk kicking off that pipeline against a live service, so per
the backfill's safety rules, all endpoints are skipped rather than executed
against a live server in CI.
"""
import pytest

pytestmark = pytest.mark.skip(
    reason="restarts a live service — unsafe to run in every CI cycle"
)


def test_generate_restart_video():
    """POST /server/restart/generateRestartVideo — generates a real video on a host."""


def test_get_analysis_status():
    """POST /server/restart/analysisStatus/<video_id> — polls a host-side job."""


def test_analyze_restart_audio():
    """POST /server/restart/analyzeRestartAudio — triggers AI audio analysis on a host."""


def test_generate_restart_report():
    """POST /server/restart/generateRestartReport — triggers report generation on a host."""


def test_analyze_restart_complete():
    """POST /server/restart/analyzeRestartComplete — combined AI analysis on a host."""


def test_analyze_restart_video():
    """POST /server/restart/analyzeRestartVideo — async AI video analysis on a host."""


def test_prepare_dubbing_audio():
    """POST /server/restart/prepareDubbingAudio — extracts/separates real audio on a host."""


def test_generate_edge_speech():
    """POST /server/restart/generateEdgeSpeech — generates real TTS speech on a host."""


def test_create_dubbed_video():
    """POST /server/restart/createDubbedVideo — renders a real dubbed video on a host."""


def test_create_dubbed_video_fast():
    """POST /server/restart/createDubbedVideoFast — renders a real dubbed video on a host."""


def test_adjust_audio_timing():
    """POST /server/restart/adjustAudioTiming — re-renders audio timing on a host."""
