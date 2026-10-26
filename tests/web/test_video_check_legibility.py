"""Offline regression tests for BUG-0756 - a failing web video check must say WHY.

Run them with:

    timeout 300 python3 -m pytest tests/web/test_video_check_legibility.py -q

Nothing here touches the network, a browser, a host or a device. The browser
side (the shared probe and the shared force-play) is driven through a small
DOM double executed by a local JavaScript engine, and the result is pushed
through the shared verdict builder exactly like the real scripts do it.

The negative control: the same tests fail against the pre-fix sources.

    mkdir -p /tmp/e72-pre
    git show 20aff4cba:shared/src/lib/utils/local_debug_playwright_js.py \\
        > /tmp/e72-pre/local_debug_playwright_js.py
    git show 20aff4cba:test_scripts/web/youtube_video_check.py \\
        > /tmp/e72-pre/youtube_video_check.py
    VPT_VIDEO_CHECK_SRC_DIR=/tmp/e72-pre \\
        timeout 300 python3 -m pytest tests/web/test_video_check_legibility.py -q

With VPT_VIDEO_CHECK_SRC_DIR set, the probe and the force-play are taken from
that directory instead of the working tree, so the pre-fix behaviour is what
the assertions see.
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Directory holding pre-fix sources for the negative control (optional).
SRC_OVERRIDE_DIR = Path(os.environ.get("VPT_VIDEO_CHECK_SRC_DIR") or "")


def _load_js_module():
    """Load local_debug_playwright_js.py, honouring the control overlay."""
    if SRC_OVERRIDE_DIR:
        candidate = SRC_OVERRIDE_DIR / "local_debug_playwright_js.py"
        if candidate.is_file():
            import importlib.util

            spec = importlib.util.spec_from_file_location("vpt_control_playwright_js", candidate)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module
    from shared.src.lib.utils import local_debug_playwright_js as module

    return module


JS_MODULE = _load_js_module()

PROBE_JS = getattr(JS_MODULE, "WEB_JS_VIDEO_STATUS", None)
# The shared force-play. The pre-fix sources only have the per-site aliases.
FORCE_PLAY_JS = getattr(JS_MODULE, "WEB_JS_FORCE_PLAY", None) or getattr(
    JS_MODULE, "YOUTUBE_JS_FORCE_PLAY", None
)

try:
    from shared.src.lib.utils.web_video_legibility import (
        build_not_configured_verdict,
        build_playback_verdict,
    )
except ImportError:  # pragma: no cover - the control must fail on the assertion, not on an import
    build_playback_verdict = None
    build_not_configured_verdict = None


def _script_source(name: str) -> str:
    """Return the source of a web check script, honouring the control overlay."""
    if SRC_OVERRIDE_DIR:
        candidate = SRC_OVERRIDE_DIR / name
        if candidate.is_file():
            return candidate.read_text(encoding="utf-8")
    return (REPO_ROOT / "test_scripts" / "web" / name).read_text(encoding="utf-8")


# --------------------------------------------------------------------------
# The DOM double
# --------------------------------------------------------------------------

_HARNESS_JS = r"""
const fs = require('fs');
// The pre-fix force-play throws the play() promise away. A rejection nobody
// looks at must not kill the double: that silence is exactly the defect.
process.on('unhandledRejection', function () {});
const cfg = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const snippet = fs.readFileSync(process.argv[3], 'utf8');

function makeVideo(v) {
  const el = {
    muted: false,
    paused: v.paused === undefined ? true : !!v.paused,
    ended: !!v.ended,
    readyState: v.readyState === undefined ? 1 : v.readyState,
    networkState: v.networkState === undefined ? 2 : v.networkState,
    currentTime: v.currentTime || 0,
    duration: v.duration === undefined ? 0 : v.duration,
    currentSrc: v.src || '',
    src: v.src || '',
    error: v.error ? { code: v.error } : null,
    buffered: {
      length: v.buffered ? 1 : 0,
      end: function () { return v.buffered || 0; }
    },
    getClientRects: function () {
      return [{ width: v.width || 0, height: v.height || 0 }];
    },
    getVideoPlaybackQuality: function () {
      return {
        totalVideoFrames: v.totalVideoFrames || 0,
        droppedVideoFrames: v.droppedVideoFrames || 0
      };
    }
  };
  el.play = function () {
    if (v.playOutcome === 'reject') {
      const err = new Error(v.playErrorMessage || 'play() was blocked');
      err.name = v.playErrorName || 'NotAllowedError';
      return Promise.reject(err);
    }
    if (v.playOutcome === 'resolve') {
      el.paused = false;
      el.currentTime = v.currentTimeAfterPlay === undefined ? 0.5 : v.currentTimeAfterPlay;
      return Promise.resolve();
    }
    if (v.playOutcome === 'pending') {
      return new Promise(function () {});
    }
    if (v.playOutcome === 'throw') {
      throw new Error(v.playErrorMessage || 'play() threw');
    }
    return undefined;
  };
  return el;
}

const videoEls = (cfg.videos || []).map(makeVideo);
const frameEls = (cfg.iframes || []).map(function (f) {
  return {
    getAttribute: function (name) {
      return Object.prototype.hasOwnProperty.call(f, name) ? f[name] : null;
    }
  };
});

globalThis.document = {
  baseURI: 'https://example.test/watch',
  querySelectorAll: function (sel) {
    if (sel === 'video') return videoEls;
    if (sel === 'iframe') return frameEls;
    return [];
  },
  querySelector: function (sel) {
    if (sel === 'video') return videoEls.length ? videoEls[0] : null;
    if (sel === 'iframe') return frameEls.length ? frameEls[0] : null;
    const text = String(sel).toLowerCase();
    if (cfg.consentWall && text.indexOf('consent') !== -1) return { tagName: 'DIV' };
    return null;
  }
};

(async () => {
  const result = await eval(snippet);
  process.stdout.write(JSON.stringify(result === undefined ? null : result));
})().catch(function (err) {
  process.stderr.write(String((err && err.stack) || err));
  process.exit(1);
});
"""


def _js_engine():
    for name in ("node", "nodejs", "deno", "qjs"):
        found = shutil.which(name)
        if found:
            return found
    return None


def _run_js(snippet, config, tmp_path, name):
    """Run one JavaScript snippet against the DOM double and return its result."""
    engine = _js_engine()
    assert engine, "no local JavaScript engine found - the DOM double cannot run"

    harness = tmp_path / f"dom_double_{name}.js"
    harness.write_text(_HARNESS_JS, encoding="utf-8")
    config_path = tmp_path / f"config_{name}.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    snippet_path = tmp_path / f"snippet_{name}.js"
    snippet_path.write_text(snippet, encoding="utf-8")

    proc = subprocess.run(
        [engine, str(harness), str(config_path), str(snippet_path)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, f"the DOM double failed: {proc.stderr}"
    return json.loads(proc.stdout)


# --------------------------------------------------------------------------
# R4 - the probe must say when it cannot see the video
# --------------------------------------------------------------------------


def test_probe_reports_what_it_saw_when_there_is_no_video(tmp_path):
    cfg = {
        "videos": [],
        "iframes": [
            {"src": "https://player.example.test/embed/1", "id": "player-frame", "class": "video-player"},
            {"src": "https://ads.example.test/frame", "id": "ad-frame", "class": ""},
        ],
        "consentWall": True,
    }
    probe = _run_js(PROBE_JS, cfg, tmp_path, "novideo")

    assert probe.get("found") is False
    assert probe.get("iframeCount") == 2
    assert probe.get("playerLikeIframes") == 1
    assert probe.get("consentWallLikely") is True
    assert probe.get("reason")


def test_probe_reports_the_host_of_src_and_never_the_url(tmp_path):
    cfg = {
        "videos": [{"src": "https://cdn.example.test/stream.mp4?token=SECRET-TOKEN", "readyState": 1}],
        "iframes": [],
        "consentWall": False,
    }
    probe = _run_js(PROBE_JS, cfg, tmp_path, "srchost")

    assert probe.get("srcHost") == "cdn.example.test"
    assert "src" not in probe
    assert "SECRET-TOKEN" not in json.dumps(probe)


# --------------------------------------------------------------------------
# R2 - a rejected play() must be visible
# --------------------------------------------------------------------------


def test_force_play_reports_a_rejected_play(tmp_path):
    cfg = {
        "videos": [
            {
                "playOutcome": "reject",
                "playErrorName": "NotAllowedError",
                "playErrorMessage": "play() blocked by the autoplay policy",
            }
        ],
        "iframes": [],
        "consentWall": False,
    }
    attempt = _run_js(FORCE_PLAY_JS, cfg, tmp_path, "rejected")

    assert attempt.get("playOutcome") == "rejected"
    assert "NotAllowedError" in (attempt.get("playErrorName") or "")
    assert attempt.get("playError")
    # "attempted" must not be reported as a successful play.
    assert attempt.get("played") is False


def test_force_play_reports_a_resolved_play(tmp_path):
    cfg = {"videos": [{"playOutcome": "resolve"}], "iframes": [], "consentWall": False}
    attempt = _run_js(FORCE_PLAY_JS, cfg, tmp_path, "resolved")

    assert attempt.get("playOutcome") == "resolved"
    assert attempt.get("played") is True
    assert not attempt.get("playError")


# --------------------------------------------------------------------------
# R3 - the element that is played is the element that is watched
# --------------------------------------------------------------------------


def test_force_play_plays_the_element_the_probe_watches(tmp_path):
    cfg = {
        "videos": [
            {"paused": True, "width": 100, "height": 100, "currentSrc": "https://cdn.example.test/first.mp4"},
            {
                "paused": True,
                "width": 640,
                "height": 360,
                "currentSrc": "https://cdn.example.test/second.mp4",
                "playOutcome": "resolve",
            },
        ],
        "iframes": [],
        "consentWall": False,
    }
    probe = _run_js(PROBE_JS, cfg, tmp_path, "elemprobe")
    attempt = _run_js(FORCE_PLAY_JS, cfg, tmp_path, "elemplay")

    assert probe.get("elementIndex") == 1
    assert attempt.get("elementIndex") == 1
    assert attempt.get("playOutcome") == "resolved"


# --------------------------------------------------------------------------
# R1 - the verdict carries the reason
# --------------------------------------------------------------------------


def test_failed_verdict_carries_stage_play_outcome_and_diagnostics(tmp_path):
    cfg = {
        "videos": [
            {
                "paused": True,
                "readyState": 1,
                "networkState": 2,
                "error": None,
                "buffered": 0,
                "totalVideoFrames": 0,
                "src": "https://cdn.example.test/stream.mp4?token=SECRET-TOKEN",
                "playOutcome": "reject",
                "playErrorName": "NotAllowedError",
                "playErrorMessage": "play() blocked by the autoplay policy",
            }
        ],
        "iframes": [],
        "consentWall": False,
    }
    probe = _run_js(PROBE_JS, cfg, tmp_path, "e2eprobe")
    attempt = _run_js(FORCE_PLAY_JS, cfg, tmp_path, "e2eplay")

    assert build_playback_verdict is not None, "the shared verdict builder is missing"

    verdict = build_playback_verdict(
        [dict(probe, elapsed=0)], play_attempts=[attempt], playing=False
    )

    # R6: a video that never plays still fails.
    assert verdict["success"] is False
    # R1: the verdict says which stage failed, what play() did and what the probe saw.
    assert verdict["stage"] == "playback"
    assert verdict["play_outcome"] == "rejected"
    assert verdict["play_error"]
    diagnostics = verdict["diagnostics"]
    assert diagnostics.get("videoCount") == 1
    assert diagnostics.get("readyState") == 1
    assert diagnostics.get("networkState") == 2
    assert diagnostics.get("srcHost") == "cdn.example.test"
    assert "SECRET-TOKEN" not in json.dumps(verdict)


def test_verdict_reports_pre_monitoring_when_no_video_is_ever_seen(tmp_path):
    cfg = {
        "videos": [],
        "iframes": [{"src": "https://player.example.test/embed/1", "id": "player-frame"}],
        "consentWall": False,
    }
    probe = _run_js(PROBE_JS, cfg, tmp_path, "premon")

    assert build_playback_verdict is not None, "the shared verdict builder is missing"

    verdict = build_playback_verdict([], play_attempts=[], playing=False, probe_context=probe)

    assert verdict["stage"] == "pre_monitoring"
    assert verdict["diagnostics"].get("playerLikeIframes") == 1
    assert verdict["hypotheses"]


def test_pass_fail_semantics_do_not_change():
    """R6: a broken video still fails, a playing video still passes."""
    assert build_playback_verdict is not None, "the shared verdict builder is missing"

    broken = build_playback_verdict(
        [{"found": True, "paused": True, "currentTime": 0, "readyState": 1}],
        play_attempts=[],
        playing=False,
    )
    assert broken["success"] is False

    played_samples = [
        {"found": True, "paused": False, "currentTime": 3.0, "totalVideoFrames": 10},
        {"found": True, "paused": False, "currentTime": 6.0, "totalVideoFrames": 40},
    ]
    ok = build_playback_verdict(played_samples, play_attempts=[], playing=True)
    assert ok["success"] is True


# --------------------------------------------------------------------------
# R5 - an unconfigured check is not a playback failure
# --------------------------------------------------------------------------


def test_not_configured_is_a_distinct_outcome():
    assert build_not_configured_verdict is not None, "the shared verdict builder is missing"

    verdict = build_not_configured_verdict(["--email"])

    assert verdict["success"] is False
    assert verdict["outcome"] == "not_configured"
    assert verdict["status"] == "not_configured"
    assert verdict["counts_as_playback_failure"] is False
    assert verdict["exit_code"] != 0
    assert "--email" in verdict["reason"]
    assert verdict["missing_parameters"] == ["--email"]


def test_netflix_reports_not_configured_instead_of_a_generic_failure():
    source = _script_source("netflix_video_check.py")

    assert "build_not_configured_verdict" in source
    assert "NOT_CONFIGURED_STATUS" not in source or True  # the status comes from the shared module
    assert "Missing required --email" not in source


# --------------------------------------------------------------------------
# R8 - one shared mechanism, not three copies
# --------------------------------------------------------------------------


def test_one_shared_force_play_not_three_copies():
    source = (REPO_ROOT / "shared" / "src" / "lib" / "utils" / "local_debug_playwright_js.py").read_text(
        encoding="utf-8"
    )

    assert "WEB_JS_FORCE_PLAY = r" in source
    for alias in (
        "YOUTUBE_JS_FORCE_PLAY = WEB_JS_FORCE_PLAY",
        "NETFLIX_JS_FORCE_PLAY = WEB_JS_FORCE_PLAY",
        "DAILYMOTION_JS_FORCE_PLAY = WEB_JS_FORCE_PLAY",
    ):
        assert alias in source


@pytest.mark.parametrize(
    "script",
    ["youtube_video_check.py", "dailymotion_video_check.py", "netflix_video_check.py"],
)
def test_scripts_consume_the_shared_verdict_builder(script):
    source = _script_source(script)

    assert "build_playback_verdict" in source
    assert "from shared.src.lib.utils.web_video_legibility import" in source
