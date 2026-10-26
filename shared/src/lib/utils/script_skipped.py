#!/usr/bin/env python3
"""Whether a finished run's row counts as *skipped* instead of *failed*.

A check that never ran because it was not configured did not look at anything.
Its row must therefore not be counted as a failure: a nightly campaign that
counts it as one reports a broken video every night for a check that never
looked at a video.

The source of truth is the run's own outcome metadata -- the ``status`` /
``outcome`` / ``counts_as_playback_failure`` the verdict already carries (see
``shared/src/lib/utils/web_video_legibility.py``). Never a match on the error
text, never a guess from the script name: a run that WAS configured and then
failed is a failure, not a skip.
"""

from typing import Any, Dict, Optional

from shared.src.lib.utils.web_video_legibility import NOT_CONFIGURED_STATUS

__all__ = ['NOT_CONFIGURED_STATUS', 'is_not_configured_outcome', 'derive_skipped']


def is_not_configured_outcome(metadata: Optional[Dict[str, Any]]) -> bool:
    """True when the run's own metadata says it never ran (not configured).

    Only the outcome the run recorded counts. A configured run that failed
    carries a different outcome, so it never lands here.
    """
    if not isinstance(metadata, dict):
        return False
    for key in ('status', 'outcome'):
        value = metadata.get(key)
        if isinstance(value, str) and value.strip().lower() == NOT_CONFIGURED_STATUS:
            return True
    # The verdict's own opt-out: "this is not a playback failure". Only the
    # not-configured verdict sets it, and it sets it to False.
    return metadata.get('counts_as_playback_failure') is False


def derive_skipped(success: bool, metadata: Optional[Dict[str, Any]]) -> bool:
    """The value of ``script_results.skipped`` for a finished run.

    A run that succeeded is never skipped, whatever its metadata says.
    """
    if success:
        return False
    return is_not_configured_outcome(metadata)
