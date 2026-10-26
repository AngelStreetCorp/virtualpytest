#!/usr/bin/env python3
"""Shared legibility layer for the web video checks.

A video check that fails must be able to say WHY it failed. Until now the
verdict could only say "it did not play", and the reason - a blocked autoplay,
a DRM-protected source, a player that lives in an iframe, a page that never
loaded a player at all, or a check that was never configured with an account -
was silently dropped.

This module is the single place where that reason is assembled. The browser
side (the shared probe and the shared force-play in
``local_debug_playwright_js.py``) collects the evidence; this module turns the
evidence into a verdict the recorded result can carry:

    verdict = build_playback_verdict(samples, play_attempts=attempts)
    verdict["stage"]        # which stage failed: navigation/consent/ad/playback
    verdict["reason"]       # human-readable why
    verdict["play_outcome"] # resolved / rejected / pending / threw / ...
    verdict["diagnostics"]  # what the probe saw (host of src only, never the URL)

An unconfigured check is NOT a playback failure: ``build_not_configured_verdict``
gives it its own outcome, so a nightly campaign cannot count "no account" as a
broken video.
"""

from typing import Any, Dict, Iterable, List, Optional, Sequence

from shared.src.lib.utils.web_video_playback import calc_playback_progress

# The stages a web video check goes through, in order.
VIDEO_CHECK_STAGES = ("navigation", "consent", "ad", "playback")

# A check that never ran because it lacks configuration. Not a playback failure.
NOT_CONFIGURED_STATUS = "not_configured"
NOT_CONFIGURED_EXIT_CODE = 2

# What the browser side can report about a play() attempt.
PLAY_OUTCOMES = (
    "resolved",
    "rejected",
    "pending",
    "threw",
    "no_promise",
    "no_video_element",
    "not_attempted",
)

# The probe fields worth keeping in a recorded result. The media src is reported
# by HOST only: the full URL can carry a token and must never be recorded.
_DIAGNOSTIC_KEYS = (
    "videoCount",
    "elementIndex",
    "readyState",
    "networkState",
    "error",
    "buffered",
    "totalVideoFrames",
    "droppedVideoFrames",
    "paused",
    "ended",
    "duration",
    "currentTime",
    "srcHost",
    "iframeCount",
    "playerLikeIframes",
    "consentWallLikely",
    "reason",
)


def diagnostics_from_sample(sample: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Return the diagnostic fields of one probe sample.

    Only the fields the probe actually reported are kept, so a caller can tell
    "the browser did not report this" from "the browser reported zero".
    """
    if not sample:
        return {}
    out: Dict[str, Any] = {}
    for key in _DIAGNOSTIC_KEYS:
        if key in sample and sample[key] is not None:
            out[key] = sample[key]
    return out


def normalize_play_attempt(attempt: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Normalize one force-play result into (outcome, error, element index).

    Understands both the legacy shape (found/attempted/played/hasPromise) and
    the outcome-carrying shape (playOutcome/playError/elementIndex). A legacy
    result cannot tell a rejected play() from a resolved one, so it is reported
    as ``unknown`` rather than as a success - never as a resolved play.
    """
    if not attempt:
        return {"outcome": "not_attempted", "error": None, "error_name": None, "element_index": None}

    outcome = attempt.get("playOutcome") or attempt.get("play_outcome")
    error = attempt.get("playError") or attempt.get("play_error") or attempt.get("error")
    error_name = attempt.get("playErrorName") or attempt.get("play_error_name")
    element_index = attempt.get("elementIndex", attempt.get("element_index"))

    if not outcome:
        # Legacy shape: attempted is not a resolved play.
        if attempt.get("found") is False:
            outcome = "no_video_element"
        elif attempt.get("played") is True:
            outcome = "resolved"
        elif attempt.get("attempted"):
            outcome = "unknown"
        else:
            outcome = "not_attempted"

    if outcome == "rejected" and not error:
        error = "play() was rejected (no reason reported)"

    return {
        "outcome": outcome,
        "error": error,
        "error_name": error_name,
        "element_index": element_index,
    }


def _latest_attempt(attempts: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Pick the most informative attempt: the last one, but a rejection wins."""
    normalized = [normalize_play_attempt(a) for a in (attempts or [])]
    if not normalized:
        return {"outcome": "not_attempted", "error": None, "error_name": None, "element_index": None}
    last = normalized[-1]
    for candidate in normalized:
        if candidate["outcome"] in ("rejected", "threw"):
            last = candidate
    return last


def build_playback_verdict(
    samples: Optional[Iterable[Dict[str, Any]]] = None,
    play_attempts: Optional[Iterable[Dict[str, Any]]] = None,
    playing: bool = False,
    monitor_error: Optional[str] = None,
    navigation_ok: bool = True,
    consent_ok: Optional[bool] = None,
    ad_ok: Optional[bool] = None,
    stages_completed: Optional[Iterable[str]] = None,
    probe_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Turn probe samples and play attempts into a legible verdict.

    ``playing`` is the caller's own "did it play" boolean, so the pass/fail
    decision stays exactly where it was: this function only explains it.
    """
    sample_list = [s for s in (samples or []) if s]
    found_samples = [s for s in sample_list if s.get("found")]
    attempts = list(play_attempts or [])
    stages = list(stages_completed or [])

    progress_seconds, progressing = calc_playback_progress(sample_list)
    confirmed = bool(playing or progressing or progress_seconds > 1.0)

    last_sample = found_samples[-1] if found_samples else (sample_list[-1] if sample_list else None)
    diagnostics = diagnostics_from_sample(last_sample)
    if not found_samples and probe_context:
        # No video was ever seen: the probe's "what I did see" report is the
        # only evidence there is (iframes, player-like frames, consent wall).
        diagnostics = diagnostics_from_sample(probe_context)

    attempt = _latest_attempt(attempts)
    play_outcome = attempt["outcome"]
    play_error = attempt["error"]

    # Which stage failed. Reported from what the check observed, never guessed.
    if not navigation_ok:
        stage = "navigation"
        reason = "the page never reached the video page"
    elif consent_ok is False:
        stage = "consent"
        reason = "the consent step did not complete, so the check never reached the player"
    elif ad_ok is False:
        stage = "ad"
        reason = "the ad step did not complete, so the check never reached the content"
    elif not found_samples:
        stage = "pre_monitoring"
        reason = "no video element was ever observed: the check never reached the playback stage"
    else:
        stage = "playback"
        reason = "a video element was found but it never started playing"

    if monitor_error:
        reason = f"{reason} (monitoring interrupted: {monitor_error})"

    # The element that was played vs the element that was watched (R3).
    watched_index = diagnostics.get("elementIndex")
    played_index = attempt["element_index"]
    if watched_index is not None and played_index is not None and watched_index != played_index:
        diagnostics["elementMismatch"] = True
        diagnostics["watchedElementIndex"] = watched_index
        diagnostics["playedElementIndex"] = played_index

    # Hypotheses are marked as such and are never presented as measurements.
    hypotheses: List[str] = []
    if play_outcome == "rejected" and play_error:
        hypotheses.append(
            "play() was rejected by the browser; an autoplay policy, a DRM-protected "
            "source or an unsupported media type would all reject it the same way"
        )
    if play_outcome == "pending":
        hypotheses.append("play() did not settle within the probe timeout")
    if not found_samples and diagnostics.get("playerLikeIframes"):
        hypotheses.append(
            "the page contains frames that look like a player; a player inside a frame "
            "is not visible to a top-document probe and was not verified here"
        )
    if not found_samples and diagnostics.get("consentWallLikely"):
        hypotheses.append("the page looks like a consent wall; the check never confirmed this")
    if found_samples and play_outcome in ("not_attempted", "unknown"):
        hypotheses.append("no play() outcome was recorded for this run")

    verdict: Dict[str, Any] = {
        "success": confirmed,
        "stage": stage,
        "reason": reason,
        "play_outcome": play_outcome,
        "play_error": play_error,
        "play_error_name": attempt["error_name"],
        "diagnostics": diagnostics,
        "sample_count": len(sample_list),
        "video_found_count": len(found_samples),
        "progress_seconds": progress_seconds,
        "stages_completed": stages,
        "monitor_error": monitor_error,
        "hypotheses": hypotheses,
    }
    if not confirmed:
        verdict["outcome"] = "playback_failed"
    else:
        verdict["outcome"] = "playback_confirmed"
    return verdict


def build_not_configured_verdict(missing: Optional[Iterable[str]] = None) -> Dict[str, Any]:
    """Verdict for a check that could not run because it lacks configuration.

    A check with no account has not found a broken video - it has not looked.
    It gets its own outcome, status and exit code so a campaign that counts
    failures does not count it as one.
    """
    missing_list = [str(m) for m in (missing or []) if m]
    detail = ", ".join(missing_list) if missing_list else "required parameters"
    return {
        "success": False,
        "outcome": NOT_CONFIGURED_STATUS,
        "status": NOT_CONFIGURED_STATUS,
        "stage": "configuration",
        "reason": f"the check is not configured: missing {detail}",
        "missing_parameters": missing_list,
        "counts_as_playback_failure": False,
        "exit_code": NOT_CONFIGURED_EXIT_CODE,
        "play_outcome": "not_attempted",
        "play_error": None,
        "diagnostics": {},
        "sample_count": 0,
        "video_found_count": 0,
        "progress_seconds": 0.0,
        "stages_completed": [],
        "monitor_error": None,
        "hypotheses": [],
    }


def format_legibility_lines(verdict: Optional[Dict[str, Any]]) -> List[str]:
    """Render a verdict as short human-readable lines for a report/summary."""
    if not verdict:
        return []
    lines = [
        f"stage: {verdict.get('stage')}",
        f"reason: {verdict.get('reason')}",
    ]
    play_outcome = verdict.get("play_outcome")
    if play_outcome:
        line = f"play(): {play_outcome}"
        if verdict.get("play_error"):
            line = f"{line} ({verdict['play_error']})"
        lines.append(line)
    diagnostics = verdict.get("diagnostics") or {}
    if diagnostics:
        rendered = ", ".join(f"{k}={diagnostics[k]}" for k in sorted(diagnostics))
        lines.append(f"diagnostics: {rendered}")
    for hypothesis in verdict.get("hypotheses") or []:
        lines.append(f"hypothesis (not verified): {hypothesis}")
    return lines
