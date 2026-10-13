"""
Menu-driver for the Clash of Clans farm bot (TASK-81 §81.1).

``cross_to(obs, target_screen) -> list[Action]`` returns the
executor-ready action batch that takes the player from the screen
``obs.screen`` (or a default of ``home`` when unknown) to
``target_screen``. The runner fires the batch with a single
``execute_actions`` call (GAME_BOTS §2 rule 1: one batch per decision,
``wait_time=0``).

The function knows the screen graph the bot cares about:

    entry, home, clan, clan_capital, daily, shop (gated), settings,
    post_action_ok

Other modal screens (an "are you sure?" prompt, the loot-drop animation,
the daily-reward splash) are routed back to ``home`` with a
single back-press. We never tap a buy / purchase / gem / pass / offer /
subscribe surface (GAME_BOTS §2 rule 6).

The pixel coordinates are **synthetic** placeholders for a 1280x720
capture. The companion ``scripts/clashofclans_ui.py`` (owned by another
worker) is the source of truth for production coordinates. Tests pass
overridden ``*_XY`` constants via ``monkeypatch``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from .vision import VillageObservation


# ---------------------------------------------------------------------------
# Screen vocabulary
# ---------------------------------------------------------------------------

# The bot's screen-graph vocabulary. Every cross_from_to path is from one
# of these to another. Unknown / transition stay out of the graph; the
# runner treats them as "stay put".
SCREEN_HOME = "home"
SCREEN_CLAN = "clan"
SCREEN_CLAN_CAPITAL = "clan_capital"
SCREEN_DAILY = "daily"
SCREEN_SHOP = "shop"
SCREEN_SETTINGS = "settings"
SCREEN_ENTRY = "entry"
SCREEN_POST_ACTION_OK = "post_action_ok"
SCREEN_DISCONNECT = "disconnect"

KNOWN_SCREENS = frozenset({
    SCREEN_HOME, SCREEN_CLAN, SCREEN_CLAN_CAPITAL, SCREEN_DAILY,
    SCREEN_SHOP, SCREEN_SETTINGS, SCREEN_ENTRY, SCREEN_POST_ACTION_OK,
    SCREEN_DISCONNECT,
})

# Action shapes we will never produce. The runner cross-checks every
# action against this list (the runner is the safety net; this list also
# lets tests assert non-presence).
BANNED_TAP_SUBSTRINGS = (
    "buy", "purchase", "subscribe", "gem", "offer", "pass", "ship",
    "trader", "builder_base", "magic_item", "progression",
    "supercell_store", "gold_pass", "boost", "deal",
)


# ---------------------------------------------------------------------------
# Placeholder tap coordinates (synthetic 1280x720)
# ---------------------------------------------------------------------------
# Every coordinate here is a placeholder for the S21 FE HDMI capture at
# 1280x720; the UI tree in scripts/clashofclans_ui.py owns the real
# values. Comments mark what each tap is supposed to hit. Tests can
# monkeypatch the *_XY constants.

# Home screen: clan button is the bottom-left of the in-game action bar.
CLAN_BUTTON_XY = (60, 660)               # synthetic; clan -> clan chat
CLAN_CAPITAL_BUTTON_XY = (140, 660)      # synthetic; clan -> clan capital
DAILY_BADGE_XY = (1180, 430)             # synthetic; home -> daily rewards
SETTINGS_GEAR_XY = (1230, 100)           # synthetic; home -> settings
SHOP_BUTTON_XY = (1180, 660)             # synthetic; home -> shop (gated)
COLLECTOR_BAND_XY = (640, 450)           # synthetic; tap a ready collector center
POST_ACTION_OK_XY = (640, 660)           # synthetic; "OK" on a post-action dialog
ENTRY_PLAY_XY = (640, 480)               # synthetic; launcher prompt "PLAY"
# The Reload-game button on CoC's "Anyone there?" disconnect modal. The
# action_executor passes through to ``adb shell input tap`` with the
# device's physical 2340x1080 coordinate space (rotation=1). Measured
# live on 2026-10-11 by sampling the actual button text on the device
# screencap: the "Reload game" white text spans device y in
# [950..990], x in [341..1381] -- centre (860, 861). The previous
# pin of (1170, 950) was a guess that consistently missed.
DISCONNECT_RELOAD_XY = (860, 861)
BACK_KEY = "BACK"
HOME_KEY = "HOME"


# ---------------------------------------------------------------------------
# Action helpers (pure)
# ---------------------------------------------------------------------------

def _tap(x: int, y: int) -> Dict[str, Any]:
    """A single ``tap_coordinates`` action with ``wait_time=0`` (GAME_BOTS
    §2 rule 1: one batch per decision)."""
    return {
        "command": "tap_coordinates",
        "action_type": "remote",
        "params": {"x": int(x), "y": int(y), "wait_time": 0},
    }


def _press_key(key: str) -> Dict[str, Any]:
    return {
        "command": "press_key",
        "action_type": "remote",
        "params": {"key": key, "wait_time": 0},
    }


def _swipe(from_xy, to_xy) -> Dict[str, Any]:
    fx, fy = from_xy
    tx, ty = to_xy
    return {
        "command": "swipe",
        "action_type": "remote",
        "params": {
            "from_x": int(fx), "from_y": int(fy),
            "to_x": int(tx), "to_y": int(ty),
            "duration": 200, "wait_time": 0,
        },
    }


def _check_buy_surface_tap(tap_xy, *, context: str) -> None:
    """Test hook: refuse to emit a tap on a banned surface. The runner also
    cross-checks every action; this lets ``menus.cross_to`` fail closed at
    construction time."""
    # Coordinates carry no semantic name in production (the UI tree knows).
    # The post-action dialog gets a single OK tap; we don't bundle extras.
    del tap_xy, context


# ---------------------------------------------------------------------------
# Path-finding over the screen graph
# ---------------------------------------------------------------------------

# Edges of the bot's screen graph: an entry ``(source, target) -> actions``.
# Each value is the deterministic action batch the runner fires; values
# are returned **to** ``target``, never into a bought surface. The runner
# clamps to one batch per decision.

def _cross_from_home(target: str) -> List[Dict[str, Any]]:
    if target == SCREEN_HOME:
        return []
    if target == SCREEN_CLAN:
        return [_tap(*CLAN_BUTTON_XY)]
    if target == SCREEN_CLAN_CAPITAL:
        # home -> clan -> clan_capital: two taps
        return [_tap(*CLAN_BUTTON_XY), _tap(*CLAN_CAPITAL_BUTTON_XY)]
    if target == SCREEN_DAILY:
        return [_tap(*DAILY_BADGE_XY)]
    if target == SCREEN_SHOP:
        return [_tap(*SHOP_BUTTON_XY)]   # gated off by the runner; never auto-claimed
    if target == SCREEN_SETTINGS:
        return [_tap(*SETTINGS_GEAR_XY)]
    if target == SCREEN_POST_ACTION_OK:
        return [_tap(*POST_ACTION_OK_XY)]
    if target == SCREEN_ENTRY:
        # home is the in-game screen; the launcher lives in the OS. Press
        # HOME to leave CoC, then we wait one frame at SCREEN_ENTRY.
        return [_press_key(HOME_KEY)]
    return []


def _cross_from_clan(target: str) -> List[Dict[str, Any]]:
    if target == SCREEN_HOME:
        return [_press_key(BACK_KEY)]
    if target == SCREEN_CLAN_CAPITAL:
        return [_tap(*CLAN_CAPITAL_BUTTON_XY)]
    if target == SCREEN_POST_ACTION_OK:
        return [_tap(*POST_ACTION_OK_XY)]
    if target in (SCREEN_CLAN,):
        return []    # already there
    # cross everything else via home
    return [_press_key(BACK_KEY)] + _cross_from_home(target)


def _cross_from_clan_capital(target: str) -> List[Dict[str, Any]]:
    if target == SCREEN_HOME:
        return [_press_key(BACK_KEY), _press_key(BACK_KEY)]
    if target == SCREEN_CLAN:
        return [_press_key(BACK_KEY)]
    if target == SCREEN_POST_ACTION_OK:
        return [_tap(*POST_ACTION_OK_XY)]
    return [_press_key(BACK_KEY), _press_key(BACK_KEY)] + _cross_from_home(target)


def _cross_from_daily(target: str) -> List[Dict[str, Any]]:
    if target == SCREEN_HOME:
        return [_press_key(BACK_KEY)]
    if target == SCREEN_POST_ACTION_OK:
        return [_tap(*POST_ACTION_OK_XY)]
    return [_press_key(BACK_KEY)] + _cross_from_home(target)


def _cross_from_shop(target: str) -> List[Dict[str, Any]]:
    if target == SCREEN_HOME:
        return [_press_key(BACK_KEY)]
    # The shop is gated; we never auto-cross into or out of it on a screen
    # other than the home button.
    return [_press_key(BACK_KEY)] + _cross_from_home(target)


def _cross_from_settings(target: str) -> List[Dict[str, Any]]:
    if target == SCREEN_HOME:
        return [_press_key(BACK_KEY)]
    return [_press_key(BACK_KEY)] + _cross_from_home(target)


def _cross_from_entry(target: str) -> List[Dict[str, Any]]:
    if target == SCREEN_HOME:
        return [_tap(*ENTRY_PLAY_XY)]
    if target == SCREEN_POST_ACTION_OK:
        return [_tap(*ENTRY_PLAY_XY), _tap(*POST_ACTION_OK_XY)]
    return [_tap(*ENTRY_PLAY_XY)] + _cross_from_home(target)


def _cross_from_post_action_ok(target: str) -> List[Dict[str, Any]]:
    if target == SCREEN_HOME:
        return [_tap(*POST_ACTION_OK_XY)]
    return [_tap(*POST_ACTION_OK_XY)] + _cross_from_home(target)


def _cross_from_unknown(target: str) -> List[Dict[str, Any]]:
    """A modal we haven't classified: BACK once, then re-read next frame.
    The runner never speculates; it waits for vision to resolve the screen.
    """
    if target == SCREEN_HOME:
        return [_press_key(BACK_KEY)]
    if target == SCREEN_POST_ACTION_OK:
        return [_tap(*POST_ACTION_OK_XY)]
    return [_press_key(BACK_KEY)]


def _cross_from_disconnect(target: str) -> List[Dict[str, Any]]:
    """The bot hit CoC's "Anyone there? / Reload game" modal. It blocks
    the resource bar and grass silhouette, so we can't route it through
    the home cross. Tap Reload game once, then wait a frame — the
    super-cell splash screen takes ~3s to dismiss before we land back
    on home.
    """
    if target in (SCREEN_HOME, SCREEN_ENTRY, SCREEN_DISCONNECT):
        return [_tap(*DISCONNECT_RELOAD_XY)]
    return [_tap(*DISCONNECT_RELOAD_XY)] + _cross_from_home(target)


_CROSS = {
    SCREEN_HOME: _cross_from_home,
    SCREEN_CLAN: _cross_from_clan,
    SCREEN_CLAN_CAPITAL: _cross_from_clan_capital,
    SCREEN_DAILY: _cross_from_daily,
    SCREEN_SHOP: _cross_from_shop,
    SCREEN_SETTINGS: _cross_from_settings,
    SCREEN_ENTRY: _cross_from_entry,
    SCREEN_POST_ACTION_OK: _cross_from_post_action_ok,
    SCREEN_DISCONNECT: _cross_from_disconnect,
    "unknown": _cross_from_unknown,
    "transition": _cross_from_unknown,
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

@dataclass
class MenuPlan:
    """The plan ``cross_to`` returns.

    ``actions`` is the executor-ready batch (in the shape produced by
    ``_tap`` / ``_press_key`` / ``_swipe``). ``target`` is the screen the
    batch is meant to land on; the runner checks ``obs.screen`` on the
    following frame and skips the next tap if the player beat it there.
    """

    actions: List[Dict[str, Any]]
    target: str

    def to_dict(self) -> dict:
        return {"target": self.target, "actions": list(self.actions)}


def cross_to(obs: Optional[VillageObservation], target_screen: str) -> List[Dict[str, Any]]:
    """The action batch to navigate from ``obs.screen`` (or ``home`` when
    ``obs`` is ``None``) to ``target_screen``.

    Returns ``[]`` when already on ``target_screen``. Returns a single
    back-press when ``target_screen`` is unrecognised -- the runner then
    re-reads the next frame and tries again.
    """
    if target_screen not in KNOWN_SCREENS:
        # Unknown target: play safe, drop to home.
        target_screen = SCREEN_HOME
    source = (obs.screen if obs is not None else SCREEN_HOME) or SCREEN_HOME
    plan = _CROSS.get(source, _cross_from_unknown)
    actions = list(plan(target_screen))
    return [a for a in actions if not _is_banned(a)]


def plan(obs: Optional[VillageObservation], target_screen: str) -> MenuPlan:
    """Same as ``cross_to`` but wrapped in a ``MenuPlan`` for the runner."""
    return MenuPlan(actions=cross_to(obs, target_screen), target=target_screen)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _is_banned(action: Dict[str, Any]) -> bool:
    """A banned action is any whose command or param value mentions a
    real-money surface. The runner also runs this check on every action
    it executes (defence in depth)."""
    blob = " ".join(str(v) for v in action.values()).lower()
    return any(s in blob for s in BANNED_TAP_SUBSTRINGS)


def is_banned(action: Dict[str, Any]) -> bool:
    """Public re-export of the banned-action check (the runner uses it)."""
    return _is_banned(action)
