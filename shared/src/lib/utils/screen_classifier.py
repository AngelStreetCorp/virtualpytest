"""Screen classifiers for an abstained screen.

**Default: Qwen-only open-set naming** (`classify_open`). The benchmark
(2026-10-17, 50 samples) found Jev loses to Qwen-only on unknown screens
(60 % vs 90 % hybrid accuracy), false-matches 30 % of foreign screens and is
1/10 on a 60-option STB tree, at ~6.8x the cost; Qwen-only is therefore the
product's default unknown-screen classifier.

**Experimental/advisory: two-stage Jev closed-choice + Qwen open-set**
(`classify_screen`), selected explicitly by the scheduler's
``--classifier hybrid``. The Jev stage pins the ``jev-router`` profile, so the
``vision.classify`` route (which points at ``qwen3-vl-8b``) cannot silently
change the experimental model; the Jev node choice is never used by the
default path.

`classify_open` pins the VL profile (``qwen3-vl-8b``) and is used by the
default scheduler path. The hybrid's Qwen fallback uses the same profile.

Verified 2026-10-17: `typesafe/jev-router` accepts an image through the chat
API and answers a two-option question correctly (`$0.00057`/call). The
decisions API itself is text-only, so the Jev stage uses the chat path, not
`decisions.py`.

The router is a reasoning model: at the original 32-token cap its reasoning
filled the budget and the response ended with `finish_reason=max_tokens` and
no content (`empty_answer`, retried 3x). `OPTIONS_MAX_TOKENS = 128` leaves
room for 60-92 reasoning tokens plus the one-word id (still tight for 60-option
node-id answers; see TASK-67 Future Optimizations).
"""
from __future__ import annotations

import base64
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

USAGE_KEY = 'vision.classify'
# The Jev closed choice is the experimental mode: pin it, never the route.
DEFAULT_ROUTER_PROFILE: Optional[str] = 'jev-router'
# The default unknown-screen classifier is Qwen3-VL open-set naming.
DEFAULT_OPEN_PROFILE = 'qwen3-vl-8b'
# The closed-choice model is a reasoning model: it spends 60-92 completion
# tokens reasoning before the one-word answer, so a 32-token cap ends the
# response with finish_reason=max_tokens and empty content (empty_answer).
# 128 leaves room for the reasoning plus the answer; a 60-option prompt was
# measured at 78-93 tokens and finished with stop 3/3 at this cap.
OPTIONS_MAX_TOKENS = 128
OPEN_PROMPT = ("Describe this device screen as a short lowercase slug of 2-5 words, "
               "for example 'settings_profiles' or 'apps_grid'. Reply with the slug only.")
OPTIONS_PROMPT = ("You are shown one device screen. Choose exactly one option id from the list below, "
                  "or 'none' if the screen matches none of them. Reply with the id only.\n\nOptions:\n")


def _slug(text: Optional[str]) -> str:
    words = [w for w in re.split(r'[^a-z0-9]+', (text or '').lower()) if w]
    return '_'.join(words[:6])


def _image(path: str):
    p = Path(path)
    media_type = 'image/png' if p.suffix.lower() == '.png' else 'image/jpeg'
    return base64.b64encode(p.read_bytes()).decode('ascii'), media_type


def _call(profile: Optional[str], prompt: str, image_path: str, team_id: Optional[str],
          max_tokens: int = 64) -> Dict[str, Any]:
    """One vision call (route or pinned profile); never raises."""
    from shared.src.lib.ai import gateway, router
    try:
        if profile:
            resolution = router.resolve_profile(profile, USAGE_KEY, team_id=team_id)
        else:
            resolution = router.resolve(USAGE_KEY, team_id=team_id)
    except Exception as e:  # noqa: BLE001
        return {'ok': False, 'error': f'router {profile or USAGE_KEY}: {e}'}
    try:
        image_b64, media_type = _image(image_path)
    except Exception as e:  # noqa: BLE001
        return {'ok': False, 'error': f'image: {e}'}
    out = gateway.execute(resolution, prompt, image_b64=image_b64, media_type=media_type,
                          max_tokens=max_tokens, temperature=None)
    if not out.get('success'):
        return {'ok': False, 'error': out.get('error') or 'call failed'}
    return {'ok': True, 'content': out.get('content') or '', 'model': out.get('model'),
            'profile': out.get('profile'), 'usage': out.get('usage')}


def _options_prompt(options: List[Dict[str, Any]]) -> str:
    lines = [f"- {o['id']}: {o.get('description') or o['id']}" for o in options]
    return OPTIONS_PROMPT + "\n".join(lines)


def _aliases(options: List[Dict[str, Any]]) -> Dict[str, str]:
    """Unique label → node id. A label shared by two nodes is ambiguous and dropped.

    The model usually answers the option id, but a real node label is a valid
    answer too; mapping it here keeps that a *real* node, never an invented id.
    """
    seen: Dict[str, List[str]] = {}
    for o in options:
        label = _slug(o.get('description'))
        if label:
            seen.setdefault(label, []).append(o['id'])
    return {label: ids[0] for label, ids in seen.items() if len(ids) == 1}


def _parse_choice(text: str, ids: List[str],
                  aliases: Optional[Dict[str, str]] = None) -> Optional[str]:
    lowered = (text or '').strip().lower()
    for candidate in ids:
        if lowered == candidate.lower():
            return candidate
    aliases = aliases or {}
    # Labels arrive as slugs; normalise "Settings Profiles" to settings_profiles.
    normalized = _slug(lowered)
    for label, node_id in aliases.items():
        if normalized == label:
            return node_id
    for candidate in ids:
        if re.search(rf'(?<![a-z0-9_]){re.escape(candidate.lower())}(?![a-z0-9_])', lowered):
            return candidate
    for label, node_id in aliases.items():
        if re.search(rf'(?:^|_){re.escape(label)}(?:_|$)', normalized):
            return node_id
    return None


def classify_with_options(image_path: str, options: List[Dict[str, Any]], team_id: Optional[str],
                          profile: Optional[str] = DEFAULT_ROUTER_PROFILE) -> Dict[str, Any]:
    """Jev closed choice over ``options`` (plus ``none``)."""
    ids = [o['id'] for o in options] + ['none']
    out = _call(profile, _options_prompt(options), image_path, team_id,
                max_tokens=OPTIONS_MAX_TOKENS)
    if not out['ok']:
        return {'ok': False, 'source': 'jev', 'error': out.get('error')}
    choice = _parse_choice(out['content'], ids, _aliases(options))
    if choice is None:
        return {'ok': False, 'source': 'jev', 'error': f'unparsed: {out["content"][:80]}',
                'raw': out['content']}
    return {'ok': True, 'source': 'jev', 'choice': choice, 'raw': out['content'],
            'model': out.get('model')}


def classify_open(image_path: str, team_id: Optional[str],
                  profile: str = DEFAULT_OPEN_PROFILE) -> Dict[str, Any]:
    """Default unknown-screen classifier: Qwen open-set naming."""
    out = _call(profile, OPEN_PROMPT, image_path, team_id, max_tokens=32)
    if not out['ok']:
        return {'ok': False, 'source': 'qwen', 'error': out.get('error')}
    label = _slug(out['content'])
    return {'ok': bool(label), 'source': 'qwen', 'label': label, 'raw': out['content'],
            'model': out.get('model')}


def classify_screen(image_path: str, team_id: Optional[str],
                    options: Optional[List[Dict[str, Any]]] = None,
                    router_profile: Optional[str] = DEFAULT_ROUTER_PROFILE,
                    open_profile: str = DEFAULT_OPEN_PROFILE) -> Dict[str, Any]:
    """Experimental hybrid: Jev closed choice, then Qwen on ``none``/error.

    Not the default path. The Jev profile is pinned (``jev-router``); only an
    explicit caller/``--classifier hybrid`` reaches this function.
    """
    jev = None
    if options:
        jev = classify_with_options(image_path, options, team_id, profile=router_profile)
        if jev.get('ok') and jev.get('choice') != 'none':
            return jev
    opened = classify_open(image_path, team_id, profile=open_profile)
    if jev is not None:
        opened['jev'] = jev
    return opened
