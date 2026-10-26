#!/usr/bin/env python3
"""Browser adapter for the content-surface suite (radio / replay / VOD / recording).

The web platform is a TV web app driven through Playwright on a `host_vnc`
device. This adapter owns the mechanics only: it opens the screens, picks an
item, starts playback and says what it saw. The harness prints the result
line; this file never does.

Three rules shape the code:

* Cause attribution. A surface that was reached and behaved wrongly is a
  product defect (`CAUSE_PRODUCT`). A surface that does not exist in this UI is
  a coverage gap (`CAUSE_COVERAGE`, reported as a skip). A condition of the
  environment is `CAUSE_INFRA`. A surface that IS in the tree and still cannot
  be opened is a product defect, not a coverage gap: `surface_failure` tells
  the two apart. A caught exception is attributed by `exception_cause`: a
  programming error is `infra`, anything else is `product`.
* What the test could not reach, it cannot judge. A catalogue whose tile did
  not open an item AND whose tree route could not be resolved is INFRA (our
  interaction, the tree the host loaded): the case never held an item, so it
  cannot say the catalogue offers none. The same goes for a Record action on a
  programme panel that was never positively identified.
* The geo-block. Live and replay playback is geo-blocked outside Switzerland:
  the player opens and says so. That is an environment condition, never a
  product defect, and it is named in the reason.
* No credentials. The dispatcher signs the browser in before the script runs;
  the adapter only checks that the session is there. It never asks for, stores
  or prints a credential.

Navigation never hardcodes a URL: the screens are addressed by their
language-neutral path and the platform resolves the path against the page it
is on, so the app's own language and host are kept.

Arguments this adapter reads on top of the ones the suite already declares
(all through `ctx.arg`):

    --record_enabled:bool       record in the recording case (default true)
    --probe_interval_s:float    seconds between two playback samples (default 2)
    --nav_timeout_s:float       page-load timeout of a navigation (default 30)
    --settle_ms:int             pause after a navigation or a click (default 800)
    --player_refusal_cause:str  cause for a player refusal message (default infra)
"""

import json

from test_scripts.content._harness import (
    Adapter,
    CaseContext,
    CaseOutcome,
    CAUSE_COVERAGE,
    CAUSE_INFRA,
    CAUSE_PRODUCT,
    STATUS_PASS,
    capture,
    exception_cause,
    navigate_to,
    sleep,
    surface_failure,
    verification_mismatch,
    web_action,
)
from shared.src.lib.utils.local_debug_playwright_js import (
    WEB_JS_AUDIO_STATE,
    WEB_JS_VIDEO_STATUS,
)
from shared.src.lib.utils.localize_identity import (
    current_locale,
    resolve_app_url,
    url_matches,
    url_path,
)
from shared.src.lib.utils.web_video_playback import calc_playback_progress


# --------------------------------------------------------------------------
# the screens, by their language-neutral path
# --------------------------------------------------------------------------

PATH_HOME = "/home"
PATH_SEARCH = "/home/search/empty"
PATH_TV_GUIDE = "/epg/initial"
PATH_RECORDINGS = "/recordings"
PATH_REPLAY_CATALOG = "/replaycatalog/0"
PATH_VOD_CATALOG = "/vod/0"
# The app's own settings, where the language of the app is chosen.
PATH_SETTINGS = "/settings"

# The item pages, by their language-free path. A catalogue tile that opens a
# category page is not the item: these paths say whether the programme itself
# was reached.
PATH_REPLAY_DETAIL = "/replaycatalog/0/details/"
PATH_VOD_DETAIL = "/vod/0/details/"
PATH_VOD_PLAYER = "/vod/0/replay/"

# The tree's node labels, used when a step needs the platform's own recipe
# (the programme panel of the TV Guide, the detail pages of the catalogues).
NODE_HOME = "home"
NODE_SEARCH = "search"
NODE_TV_GUIDE = "tv_guide"
NODE_TV_GUIDE_PROGRAMME = "tv_guide_programme"
NODE_REPLAY_DETAIL = "replay_detail"
NODE_VOD_DETAIL = "vod_detail"
NODE_VOD_PLAYER = "vod_player"


# --------------------------------------------------------------------------
# the phrases that decide the cause
# --------------------------------------------------------------------------

# The player opens and refuses because the run is outside Switzerland. An
# environment condition, never a product defect.
GEO_BLOCK_PHRASES = (
    "only available within switzerland",
    "only available in switzerland",
    "within switzerland",
    "nur in der schweiz",
    "uniquement en suisse",
    "solo in svizzera",
)

# The reference tree records this text as the VOD player's own identity, so a
# player that refuses with it behaves as the app is documented to behave. The
# cause stays switchable (`--player_refusal_cause`).
PLAYER_REFUSAL_PHRASES = (
    "cannot be played at this time",
    "can not be played at this time",
    "the video cannot be played",
    "video cannot be played",
    "kann derzeit nicht abgespielt werden",
)

# The app's own sign-in bypass, in every language the app ships. It needs no
# credential: the app keeps working as a guest when it is used.
SKIP_LOGIN_LABELS = (
    "skip login",
    "anmeldung überspringen",
    "ignorer la connexion",
    "salta login",
)

# The app speaks the language of the browser profile, and a fresh profile
# starts in GERMAN — which is also the language the reference tree was built
# in (its entry edge opens /de/home). The suite therefore speaks the app's
# language: every label it presses is listed in every language the app ships,
# and the one the app publishes is the one that matches.
CATALOGUE_TILE_LABELS = {
    "replay": ("all shows", "alle sendungen"),
    "vod": ("popular movies to rent", "neue filme zum mieten"),
}

PLAY_ACTION_LABELS = (
    "watch", "play", "watch now", "watch episode", "play episode", "start watching",
    "schauen", "ansehen", "jetzt ansehen", "episode ansehen", "abspielen",
)

# The cookie banner (OneTrust), in every language the app ships. It lies over
# the app, so a press can land on it instead of on the control underneath.
COOKIE_BANNER_LABELS = (
    "reject all",
    "alle ablehnen",
    "tout refuser",
    "rifiuta tutto",
)

# The app's own sign-in prompt, in every language the app ships. It appears
# on the pages that play content when the session covers the catalogue only.
SIGN_IN_PHRASES = (
    "anmeldung",
    "melde dich bitte mit deinen zugangsdaten an",
    "sign in",
    "log in",
    "se connecter",
    "accedi",
)

# Never pressed: the operator's cast button, the recording editor, the
# destructive actions and the offer that costs money.
NEVER_PRESS = (
    "watch on tv",
    "edit recording",
    "remove",
    "delete",
    "rent now",
    "streaming channels only",
    "personalise line-up",
)

# The resolver's own words when the navigation graph the host loaded does not
# carry the node the test asked for. The tree is ours: a node that is not in
# it is never a defect of the product, so such a navigation is INFRA.
GRAPH_MISSING_MARKERS = (
    "not found in navigation graph",
    "could not resolve target_node_label",
)


# --------------------------------------------------------------------------
# the browser probes
# --------------------------------------------------------------------------

def app_account(state) -> str:
    """The account the app shows, read from the page and never assumed.

    The app stores it in `flutter.username` as a JSON string, so a guest
    carries the quoted empty string (`""`) — which is not an account. Reading
    it as one would tell the report that a guest session played the content.
    """
    value = str((state or {}).get("username") or "").strip()
    if value.startswith('"') and value.endswith('"') and len(value) >= 2:
        value = value[1:-1]
    return value.strip()


def app_language(state) -> str:
    """The language the app shows, read from the page and never assumed.

    The app stores it in `flutter.language` as a JSON string, so the value
    arrives quoted ("de"). An unknown value is an empty string: the caller
    then treats the app as "not English" and tries the switch.
    """
    value = str((state or {}).get("language") or "").strip()
    if value.startswith('"') and value.endswith('"') and len(value) >= 2:
        value = value[1:-1]
    return value.strip().lower()

# Flutter draws its web app on a canvas. With the accessibility tree off, the
# page carries NO elements for the tiles: the only thing in the DOM is the
# placeholder that asks the user to switch accessibility on. Clicking that
# placeholder makes the app publish its semantics tree (the tiles, the labels,
# the roles), and every element-based step of this adapter can then address the
# app's own controls instead of guessing at coordinates.
_JS_ENABLE_ACCESSIBILITY = r"""
(() => {
  const ph = document.querySelector('flt-semantics-placeholder');
  if (!ph) {
    return {enabled: false, reason: 'the page has no accessibility placeholder'};
  }
  try {
    ph.click();
  } catch (e) {
    return {enabled: false, reason: 'the placeholder refused the click: ' + String(e)};
  }
  return {enabled: true, reason: 'the accessibility tree was switched on'};
})()
"""

# The page state: where we are, which account is logged in, which language the
# app shows. Read once per step, never a hardcoded value.
_JS_PAGE_STATE = r"""
(() => {
  const ls = (k) => { try { return localStorage.getItem(k); } catch (e) { return null; } };
  const state = {href: '', path: '', origin: '', username: null, language: null};
  try {
    state.href = location.href || '';
    state.path = location.pathname || '';
    state.origin = location.origin || '';
  } catch (e) {}
  state.username = ls('flutter.username');
  state.language = ls('flutter.language');
  return state;
})()
"""

# Everything the page says, in the shapes a canvas-rendered app uses: the body
# text, the aria labels of the semantics tree and the semantics text itself.
_JS_PAGE_TEXT = r"""
(() => {
  const parts = [];
  try {
    const body = document.body;
    if (body) {
      if (body.innerText) parts.push(body.innerText);
      if (body.textContent) parts.push(body.textContent);
    }
  } catch (e) {}
  try {
    const labelled = document.querySelectorAll('[aria-label]');
    for (let i = 0; i < labelled.length; i++) {
      const v = labelled[i].getAttribute('aria-label');
      if (v) parts.push(v);
    }
  } catch (e) {}
  try {
    const semantics = document.querySelectorAll('flt-semantics');
    for (let i = 0; i < semantics.length; i++) {
      const t = semantics[i].textContent;
      if (t) parts.push(t);
    }
  } catch (e) {}
  const seen = new Set();
  const out = [];
  for (let i = 0; i < parts.length; i++) {
    const s = String(parts[i]).replace(/\s+/g, ' ').trim();
    if (!s || seen.has(s)) continue;
    seen.add(s);
    out.push(s);
  }
  return out.join(' | ').slice(0, 8000);
})()
"""

# Press the first visible element whose accessible name matches one of the
# labels. A Flutter app needs a pointer sequence, not a bare click.
_JS_PRESS_LABEL = r"""
(() => {
  const cfg = __CFG__;
  const norm = (s) => String(s || '').replace(/\s+/g, ' ').trim().toLowerCase();
  const LABELS = (cfg.labels || []).map(norm).filter(Boolean);
  const EXCLUDE = (cfg.exclude || []).map(norm).filter(Boolean);
  const SKIP_ROLES = ['textbox', 'searchbox', 'combobox', 'listbox', 'option', 'menuitem'];

  function visible(el) {
    try { return el.getClientRects().length > 0; } catch (e) { return false; }
  }
  function accName(el) {
    let v = '';
    try { v = el.getAttribute('aria-label') || ''; } catch (e) {}
    if (!v) { try { v = el.innerText || el.textContent || ''; } catch (e) {} }
    return String(v).replace(/\s+/g, ' ').trim();
  }
  function matches(name) {
    for (let i = 0; i < EXCLUDE.length; i++) {
      if (name.indexOf(EXCLUDE[i]) >= 0) return false;
    }
    for (let i = 0; i < LABELS.length; i++) {
      const l = LABELS[i];
      if (name === l) return true;
      if (name.startsWith(l + ' ') || name.startsWith(l + ',') ||
          name.startsWith(l + ':') || name.startsWith(l + '-')) return true;
    }
    return false;
  }

  const nodes = document.querySelectorAll(
    '[role="button"], button, a, [role="link"], [role="tab"], flt-semantics');
  const cands = [];
  for (let i = 0; i < nodes.length; i++) {
    const el = nodes[i];
    const role = (el.getAttribute('role') || '').toLowerCase();
    if (SKIP_ROLES.indexOf(role) >= 0) continue;
    const tag = (el.tagName || '').toLowerCase();
    if (tag === 'input' || tag === 'textarea' || tag === 'option') continue;
    const name = norm(accName(el));
    if (!name || !matches(name)) continue;
    if (!visible(el)) continue;
    const r = el.getBoundingClientRect();
    if (r.width <= 0 || r.height <= 0) continue;
    cands.push({el: el, name: name, r: r});
  }

  // the most specific node wins: a real button before a container, then the
  // smallest one on screen (a label and the group that carries it).
  cands.sort((a, b) => {
    const roleA = (a.el.getAttribute('role') === 'button' || a.el.tagName === 'BUTTON') ? 0 : 1;
    const roleB = (b.el.getAttribute('role') === 'button' || b.el.tagName === 'BUTTON') ? 0 : 1;
    if (roleA !== roleB) return roleA - roleB;
    const areaA = a.r.width * a.r.height, areaB = b.r.width * b.r.height;
    return areaA - areaB;
  });

  const pick = cands[cfg.index || 0];
  if (!pick) {
    return {pressed: false, reason: 'no visible element matches ' + JSON.stringify(cfg.labels || [])};
  }
  const r = pick.r;
  const x = r.left + r.width / 2, y = r.top + r.height / 2;
  const base = {bubbles: true, cancelable: true, composed: true,
                clientX: x, clientY: y, button: 0, view: window};
  const target = pick.el;
  try {
    target.dispatchEvent(new PointerEvent('pointerdown',
      Object.assign({}, base, {pointerId: 1, isPrimary: true, buttons: 1})));
  } catch (e) {}
  try { target.dispatchEvent(new MouseEvent('mousedown', Object.assign({}, base, {buttons: 1}))); } catch (e) {}
  try {
    target.dispatchEvent(new PointerEvent('pointerup',
      Object.assign({}, base, {pointerId: 1, isPrimary: true, buttons: 0})));
  } catch (e) {}
  try { target.dispatchEvent(new MouseEvent('mouseup', Object.assign({}, base, {buttons: 0}))); } catch (e) {}
  try { target.dispatchEvent(new MouseEvent('click', base)); } catch (e) {}
  return {pressed: true, label: pick.name, x: Math.round(x), y: Math.round(y)};
})()
"""

# Press a catalogue tile: the tiles carry no title, so the named ones are tried
# first and the first tile of the main area is the structural fallback (the
# sidebar is a column of links, the tiles are buttons).
_JS_PRESS_TILE = r"""
(() => {
  const cfg = __CFG__;
  const norm = (s) => String(s || '').replace(/\s+/g, ' ').trim().toLowerCase();
  const LABELS = (cfg.labels || []).map(norm).filter(Boolean);

  function visible(el) {
    try { return el.getClientRects().length > 0; } catch (e) { return false; }
  }
  function accName(el) {
    let v = '';
    try { v = el.getAttribute('aria-label') || ''; } catch (e) {}
    if (!v) { try { v = el.innerText || el.textContent || ''; } catch (e) {} }
    return String(v).replace(/\s+/g, ' ').trim();
  }

  const vw = window.innerWidth || 1920;
  const vh = window.innerHeight || 1080;
  const nodes = document.querySelectorAll('[role="button"], button, flt-semantics[role="button"]');

  const named = [];
  const structural = [];
  for (let i = 0; i < nodes.length; i++) {
    const el = nodes[i];
    if (!visible(el)) continue;
    const r = el.getBoundingClientRect();
    if (r.width <= 0 || r.height <= 0) continue;
    const name = norm(accName(el));
    if (LABELS.length) {
      let hit = false;
      for (let j = 0; j < LABELS.length; j++) {
        const l = LABELS[j];
        if (name === l || name.startsWith(l + ' ') || name.startsWith(l + ',')) { hit = true; break; }
      }
      if (hit) { named.push({el: el, name: name, r: r}); continue; }
    }
    if (el.closest('a')) continue;
    if (r.width < 40 || r.height < 40) continue;
    if (r.left < vw * 0.10 || r.top < vh * 0.06) continue;
    structural.push({el: el, name: name, r: r});
  }

  let pick = named[0];
  if (!pick) {
    structural.sort((a, b) => (a.r.top - b.r.top) || (a.r.left - b.r.left));
    pick = structural[0];
  }
  if (!pick) {
    return {pressed: false, reason: 'no tile found in the main area'};
  }
  const r = pick.r;
  const x = r.left + r.width / 2, y = r.top + r.height / 2;
  const base = {bubbles: true, cancelable: true, composed: true,
                clientX: x, clientY: y, button: 0, view: window};
  const target = pick.el;
  try {
    target.dispatchEvent(new PointerEvent('pointerdown',
      Object.assign({}, base, {pointerId: 1, isPrimary: true, buttons: 1})));
  } catch (e) {}
  try { target.dispatchEvent(new MouseEvent('mousedown', Object.assign({}, base, {buttons: 1}))); } catch (e) {}
  try {
    target.dispatchEvent(new PointerEvent('pointerup',
      Object.assign({}, base, {pointerId: 1, isPrimary: true, buttons: 0})));
  } catch (e) {}
  try { target.dispatchEvent(new MouseEvent('mouseup', Object.assign({}, base, {buttons: 0}))); } catch (e) {}
  try { target.dispatchEvent(new MouseEvent('click', base)); } catch (e) {}
  return {pressed: true, label: pick.name, x: Math.round(x), y: Math.round(y)};
})()
"""

# Press the cell of the TV Guide grid that sits at the centre of the grid,
# where the "now" line runs.
_JS_PRESS_GRID_CENTRE = r"""
(() => {
  function visible(el) {
    try { return el.getClientRects().length > 0; } catch (e) { return false; }
  }
  const vw = window.innerWidth || 1920;
  const vh = window.innerHeight || 1080;
  const nodes = document.querySelectorAll('[role="button"], button, flt-semantics[role="button"]');
  const cands = [];
  for (let i = 0; i < nodes.length; i++) {
    const el = nodes[i];
    if (!visible(el)) continue;
    if (el.closest('a')) continue;
    const r = el.getBoundingClientRect();
    if (r.width < 30 || r.height < 18) continue;
    if (r.left < vw * 0.08 || r.top < vh * 0.12) continue;
    cands.push({el: el, r: r});
  }
  if (!cands.length) return {pressed: false, reason: 'no grid cell found'};
  const cx = vw / 2, cy = vh / 2;
  cands.sort((a, b) => {
    const da = Math.abs((a.r.left + a.r.width / 2) - cx) + Math.abs((a.r.top + a.r.height / 2) - cy);
    const db = Math.abs((b.r.left + b.r.width / 2) - cx) + Math.abs((b.r.top + b.r.height / 2) - cy);
    return da - db;
  });
  const pick = cands[0];
  const r = pick.r;
  const x = r.left + r.width / 2, y = r.top + r.height / 2;
  const base = {bubbles: true, cancelable: true, composed: true,
                clientX: x, clientY: y, button: 0, view: window};
  const target = pick.el;
  try {
    target.dispatchEvent(new PointerEvent('pointerdown',
      Object.assign({}, base, {pointerId: 1, isPrimary: true, buttons: 1})));
  } catch (e) {}
  try { target.dispatchEvent(new MouseEvent('mousedown', Object.assign({}, base, {buttons: 1}))); } catch (e) {}
  try {
    target.dispatchEvent(new PointerEvent('pointerup',
      Object.assign({}, base, {pointerId: 1, isPrimary: true, buttons: 0})));
  } catch (e) {}
  try { target.dispatchEvent(new MouseEvent('mouseup', Object.assign({}, base, {buttons: 0}))); } catch (e) {}
  try { target.dispatchEvent(new MouseEvent('click', base)); } catch (e) {}
  return {pressed: true, x: Math.round(x), y: Math.round(y)};
})()
"""

# The labels the page shows, one per visible element: the tiles of a
# catalogue, the entries of a list.
_JS_LIST_ITEMS = r"""
(() => {
  const out = [];
  const seen = new Set();
  const nodes = document.querySelectorAll(
    '[role="button"], button, a, [role="listitem"], [role="tab"], li, flt-semantics');
  for (let i = 0; i < nodes.length; i++) {
    const el = nodes[i];
    let name = '';
    try { name = (el.getAttribute('aria-label') || el.innerText || el.textContent || '').trim(); } catch (e) {}
    if (!name) continue;
    try { if (el.getClientRects().length === 0) continue; } catch (e) { continue; }
    const key = name.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(name);
  }
  return out.slice(0, 300);
})()
"""

# The programme panel is the group whose label holds " - " (channel and
# programme).
_JS_PANEL_TITLES = r"""
(() => {
  const out = [];
  const nodes = document.querySelectorAll('[role="group"], flt-semantics');
  for (let i = 0; i < nodes.length; i++) {
    let name = '';
    try { name = (nodes[i].getAttribute('aria-label') || '').trim(); } catch (e) {}
    if (!name || name.indexOf(' - ') < 0) continue;
    out.push(name);
  }
  return out;
})()
"""

# Type into the first visible field (the search box).
_JS_FILL_FIELD = r"""
(() => {
  const cfg = __CFG__;
  const fields = document.querySelectorAll('input, textarea');
  let el = null;
  for (let i = 0; i < fields.length; i++) {
    try { if (fields[i].getClientRects().length === 0) continue; } catch (e) { continue; }
    el = fields[i];
    break;
  }
  if (!el) return {filled: false, reason: 'no visible input field'};
  try { el.focus(); } catch (e) {}
  try { el.value = cfg.text || ''; } catch (e) {}
  try { el.dispatchEvent(new Event('input', {bubbles: true})); } catch (e) {}
  try { el.dispatchEvent(new Event('change', {bubbles: true})); } catch (e) {}
  return {filled: true};
})()
"""

# The media element of an audio-only surface (radio): the same pick as the
# shared audio state, plus the position that says whether it advances.
_JS_AUDIO_PROGRESS = r"""
(() => {
  const medias = document.querySelectorAll('video, audio');
  if (!medias.length) return {found: false};
  const score = (v) => {
    let area = 0;
    try { const r = v.getClientRects(); if (r.length) area = r[0].width * r[0].height; } catch (e) {}
    const active = (!v.paused && !v.ended && v.readyState >= 2) ? 1e12 : 0;
    return active + area;
  };
  const list = Array.from(medias).slice().sort((a, b) => score(b) - score(a));
  const v = list[0];
  let volume = null;
  try { volume = v.volume; } catch (e) {}
  return {
    found: true,
    tag: v.tagName.toLowerCase(),
    currentTime: v.currentTime,
    paused: v.paused,
    ended: v.ended,
    readyState: v.readyState,
    muted: !!v.muted,
    volume: volume,
    count: list.length
  };
})()
"""


def _norm(text):
    """A comparable form of a label: lower case, single spaces."""
    return " ".join(str(text or "").split()).strip().lower()


def _classify_phrase(text):
    """What the page says about the stream: ('geo' | 'refusal' | None, phrase)."""
    haystack = _norm(text)
    if not haystack:
        return None, ""
    for phrase in GEO_BLOCK_PHRASES:
        if phrase in haystack:
            return "geo", phrase
    for phrase in PLAYER_REFUSAL_PHRASES:
        if phrase in haystack:
            return "refusal", phrase
    return None, ""


def _graph_missing(detail: str) -> bool:
    """Did the resolver not find the node in the navigation graph?

    The tree the host loaded is ours. A node that is not in it is a gap in
    what we can drive, never a defect of the product.
    """
    haystack = _norm(detail)
    return any(marker in haystack for marker in GRAPH_MISSING_MARKERS)


class WebAdapter(Adapter):
    """The content cases on the browser."""

    platform = "web"

    # Which session the run drove: an account, or the app's own guest route.
    _session = "account"

    # The language the app shows itself in (read from the page, never assumed).
    _language = ""

    # The page the last navigation landed on.
    _last_landed = ""

    # -- lifecycle ---------------------------------------------------------

    def prepare(self, ctx: CaseContext) -> None:
        if ctx.controller("web") is None:
            ctx.log("no web controller on this device: it is not a browser device")
            return
        ctx.log(f"browser page: {self._page_url(ctx) or 'unknown'}")

    def finish(self, ctx: CaseContext) -> None:
        """Leave the browser on the app's home screen for whoever runs next."""
        try:
            if ctx.controller("web") is None:
                return
            self._goto(ctx, PATH_HOME)
        except Exception as exc:                                   # noqa: BLE001
            ctx.log(f"could not go back home: {exc}")

    # -- the four cases ----------------------------------------------------

    def run_replay(self, ctx: CaseContext) -> CaseOutcome:
        """Open the replay catalogue, pick a programme, play it."""
        try:
            ready, reason = self._ready(ctx)
            if not ready:
                return CaseOutcome.skipped(reason, cause=CAUSE_INFRA)
            evidence = {"session": self._session}

            opened, detail = self._goto(ctx, PATH_REPLAY_CATALOG, expect=PATH_REPLAY_CATALOG)
            if not opened:
                return CaseOutcome.failed(
                    f"could not open the replay catalogue: {detail}", cause=CAUSE_INFRA, evidence=evidence)
            evidence["catalogue_url"] = self._page_url(ctx)
            capture(ctx, "web_replay_catalogue")

            picked = self._open_catalogue_item(ctx, PATH_REPLAY_CATALOG,
                                               list(CATALOGUE_TILE_LABELS["replay"]),
                                               node=NODE_REPLAY_DETAIL,
                                               expect_paths=(PATH_REPLAY_DETAIL,))
            if not picked["opened"]:
                return self._catalogue_outcome(picked, evidence, "a replay programme")
            evidence["item"] = picked.get("title", "")
            evidence["detail_url"] = self._page_url(ctx)
            capture(ctx, "web_replay_detail")

            started, start_detail = self._start_playback(ctx)
            if not started:
                # the app answers a catalogue session with its own sign-in box
                # on the pages that play content: that is a session problem
                prompt = self._sign_in_prompt(ctx)
                if prompt:
                    return CaseOutcome.failed(
                        f"the app asks for a sign-in to play this content ({prompt}): "
                        f"the session of this run covers the catalogue, not the playback",
                        cause=CAUSE_INFRA, evidence=evidence)
                if self._session == "guest":
                    # No account, no play action. The app offers the playback
                    # to a signed-in user only, so a guest session that finds
                    # no play button is the session, not a defect of the app.
                    return CaseOutcome.failed(
                        f"the replay programme offers no play action ({start_detail}): the "
                        f"session of this run is a guest session, and the app offers the "
                        f"playback to a signed-in user only",
                        cause=CAUSE_INFRA, evidence=evidence)
                return CaseOutcome.failed(
                    f"the replay programme offers no play action: {start_detail}",
                    cause=CAUSE_PRODUCT, evidence=evidence)
            evidence["player_url"] = self._page_url(ctx)
            capture(ctx, "web_replay_player")

            return self._confirm_playback(ctx, evidence, audio=False)
        except Exception as exc:                                   # noqa: BLE001
            cause = exception_cause(exc)
            ctx.log(f"the replay case raised: {exc}")
            return CaseOutcome.failed(
                f"{cause}: the replay case raised {type(exc).__name__}", cause=cause)

    def run_vod(self, ctx: CaseContext) -> CaseOutcome:
        """Open the movies and series catalogue, pick a title, play it."""
        try:
            ready, reason = self._ready(ctx)
            if not ready:
                return CaseOutcome.skipped(reason, cause=CAUSE_INFRA)
            evidence = {"session": self._session}

            opened, detail = self._goto(ctx, PATH_VOD_CATALOG, expect=PATH_VOD_CATALOG)
            if not opened:
                return CaseOutcome.failed(
                    f"could not open the movies and series catalogue: {detail}",
                    cause=CAUSE_INFRA, evidence=evidence)
            evidence["catalogue_url"] = self._page_url(ctx)
            capture(ctx, "web_vod_catalogue")

            picked = self._open_catalogue_item(ctx, PATH_VOD_CATALOG,
                                               list(CATALOGUE_TILE_LABELS["vod"]),
                                               node=NODE_VOD_PLAYER,
                                               expect_paths=(PATH_VOD_DETAIL, PATH_VOD_PLAYER))
            if not picked["opened"]:
                return self._catalogue_outcome(picked, evidence, "a title")
            evidence["item"] = picked.get("title", "")
            evidence["detail_url"] = self._page_url(ctx)

            # A tile can open the player at once or the detail page of the
            # title. The tree's own route to the player (a Continue Watching
            # tile plays at once) is preferred over a button on the detail
            # page, which may only offer the pay per view.
            if not self._looks_like_player(self._page_url(ctx)):
                ok, route_detail = navigate_to(ctx, NODE_VOD_PLAYER)
                if not (ok and self._looks_like_player(self._page_url(ctx))):
                    started, start_detail = self._start_playback(ctx)
                    if not started:
                        prompt = self._sign_in_prompt(ctx)
                        if prompt:
                            # the app answers a catalogue session with its own
                            # sign-in box on the pages that play content
                            return CaseOutcome.failed(
                                f"the app asks for a sign-in to play this content ({prompt}): "
                                f"the session of this run covers the catalogue, not the playback",
                                cause=CAUSE_INFRA, evidence=evidence)
                        if not ok:
                            # the tree's route to the player did not work, so
                            # the detail page's own button is no authority:
                            # the test cannot conclude the title is unplayable
                            cause, why = self._route_cause(ctx, NODE_VOD_PLAYER, route_detail)
                            return CaseOutcome.failed(
                                f"the title offers no play action: {start_detail} — the tree route "
                                f"to '{NODE_VOD_PLAYER}' failed ({route_detail}): {why}",
                                cause=cause, evidence=evidence)
                        if self._session == "guest":
                            # No account, no play action: the app offers the
                            # playback to a signed-in user only.
                            return CaseOutcome.failed(
                                f"the title offers no play action ({start_detail}): the session "
                                f"of this run is a guest session, and the app offers the "
                                f"playback to a signed-in user only",
                                cause=CAUSE_INFRA, evidence=evidence)
                        return CaseOutcome.failed(
                            f"the title offers no play action: {start_detail}",
                            cause=CAUSE_PRODUCT, evidence=evidence)
            evidence["player_url"] = self._page_url(ctx)
            capture(ctx, "web_vod_player")

            return self._confirm_playback(ctx, evidence, audio=False)
        except Exception as exc:                                   # noqa: BLE001
            cause = exception_cause(exc)
            ctx.log(f"the vod case raised: {exc}")
            return CaseOutcome.failed(
                f"{cause}: the vod case raised {type(exc).__name__}", cause=cause)

    def run_radio(self, ctx: CaseContext) -> CaseOutcome:
        """Radio is not in this web tree: look for it, and say so when it is not there."""
        try:
            ready, reason = self._ready(ctx)
            if not ready:
                return CaseOutcome.skipped(reason, cause=CAUSE_INFRA)
            evidence = {"discovery": []}

            source, detail, failure = self._discover_radio(ctx, evidence)
            if not source:
                if failure is not None:
                    # A radio node that IS in the tree could not be opened:
                    # the surface is there and it did not work.
                    failure.evidence = evidence
                    return failure
                return CaseOutcome.skipped(
                    "no radio surface in this web UI: the navigation tree has no radio node and "
                    f"the discovery found no radio entry point ({detail})",
                    cause=CAUSE_COVERAGE, evidence=evidence)
            evidence["radio_url"] = self._page_url(ctx)
            capture(ctx, "web_radio_player")

            return self._confirm_playback(ctx, evidence, audio=True)
        except Exception as exc:                                   # noqa: BLE001
            cause = exception_cause(exc)
            ctx.log(f"the radio case raised: {exc}")
            return CaseOutcome.failed(
                f"{cause}: the radio case raised {type(exc).__name__}", cause=cause)

    def run_recording(self, ctx: CaseContext) -> CaseOutcome:
        """Record a live programme, then prove it is listed and plays back."""
        try:
            if not self._record_enabled(ctx):
                return CaseOutcome.skipped(
                    "recording is switched off for this run (record_enabled is off)",
                    cause=CAUSE_COVERAGE)
            ready, reason = self._ready(ctx)
            if not ready:
                return CaseOutcome.skipped(reason, cause=CAUSE_INFRA)
            evidence = {"session": self._session}

            # what the recordings list holds before the recording
            opened, detail = self._goto(ctx, PATH_RECORDINGS, expect=PATH_RECORDINGS)
            if not opened:
                landed = str(self._last_landed or "")
                if "/login" in landed:
                    # the app sent the recordings area to its own sign-in page:
                    # the session of this run covers the catalogue, not the
                    # recordings. A lab/account fact, never a product defect.
                    return CaseOutcome.failed(
                        f"could not open the recordings list: the app asks for a fresh "
                        f"sign-in on that screen ({landed}) - the session of this run "
                        f"covers the catalogue, not the recordings area",
                        cause=CAUSE_INFRA, evidence=evidence)
                return CaseOutcome.failed(
                    f"could not open the recordings list: {detail}", cause=CAUSE_INFRA, evidence=evidence)
            before = self._items(ctx)
            evidence["labels_before"] = len(before)
            evidence["session"] = self._session

            # the TV Guide and the panel of the programme that is on now
            opened, detail = self._goto(ctx, PATH_TV_GUIDE, expect=PATH_TV_GUIDE)
            if not opened:
                return CaseOutcome.failed(
                    f"could not open the TV Guide: {detail}", cause=CAUSE_INFRA, evidence=evidence)
            panel, panel_detail = self._open_programme_panel(ctx)
            if not panel:
                return CaseOutcome.failed(
                    f"the record step failed: the test never reached a programme panel, so the "
                    f"presence of a Record action was not established ({panel_detail})",
                    cause=CAUSE_INFRA, evidence=evidence)
            title = self._programme_title(ctx)
            evidence["programme"] = title
            capture(ctx, "web_recording_panel")

            # the record action itself
            pressed = self._press(ctx, ["record", "aufnahme"],
                                  exclude=NEVER_PRESS + ("recording", "recordings", "cancel", "play", "watch"))
            if not pressed.get("pressed"):
                if not title:
                    # no programme was named, so no panel was really reached:
                    # the Record action was never looked at
                    return CaseOutcome.failed(
                        f"the record step failed: the test never reached a programme panel, so the "
                        f"presence of a Record action was not established "
                        f"({pressed.get('reason', 'no match')})",
                        cause=CAUSE_INFRA, evidence=evidence)
                return CaseOutcome.failed(
                    f"the record step failed: the programme panel has no Record action "
                    f"({pressed.get('reason', 'no match')})",
                    cause=CAUSE_PRODUCT, evidence=evidence)
            evidence["record_pressed"] = pressed.get("label", "")
            capture(ctx, "web_recording_pressed")

            # the recording has to show up in the list
            listed, item, list_detail = self._wait_for_recording(ctx, before, title)
            if not listed:
                return CaseOutcome.failed(
                    f"the record step failed: the recording never appeared in the recordings list "
                    f"({list_detail})",
                    cause=CAUSE_PRODUCT, evidence=evidence)
            evidence["recording"] = item
            capture(ctx, "web_recording_listed")

            # and it has to play back
            labels = [item]
            if title and len(title.split(" - ")[-1]) > 3:
                labels.append(title.split(" - ")[-1])
            opened = self._press(ctx, labels, exclude=NEVER_PRESS)
            if not opened.get("pressed"):
                return CaseOutcome.failed(
                    f"the playback step failed: the recording is listed but could not be opened "
                    f"({opened.get('reason', 'no match')})",
                    cause=CAUSE_PRODUCT, evidence=evidence)
            self._settle(ctx)
            evidence["player_url"] = self._page_url(ctx)

            outcome = self._confirm_playback(ctx, evidence, audio=False)
            if outcome.status == STATUS_PASS or outcome.cause == CAUSE_INFRA:
                # it plays back, or the player refused for an environment reason
                return outcome
            # playback did not start: say which step failed
            return CaseOutcome.failed(
                f"the playback step failed: the recording is listed ({item}) but does not play back "
                f"({outcome.reason})",
                cause=outcome.cause, evidence=evidence)
        except Exception as exc:                                   # noqa: BLE001
            cause = exception_cause(exc)
            ctx.log(f"the recording case raised: {exc}")
            return CaseOutcome.failed(
                f"{cause}: the recording case raised {type(exc).__name__}", cause=cause)

    # -- readiness ---------------------------------------------------------

    def _ready(self, ctx: CaseContext):
        """(ok, reason): the browser is attached and the app can be driven."""
        if ctx.controller("web") is None:
            return False, "no web controller on this device: the browser is not attached"
        state = self._page_state(ctx)
        if not self._app_is_open(state):
            # the browser may still sit on the sign-in page: open the app first
            ok, detail = navigate_to(ctx, NODE_HOME)
            if ok:
                state = self._page_state(ctx)
            else:
                ctx.log(f"could not open the app: {detail}")
        if not state.get("username") and not self._app_is_open(state):
            # the app's own way in: its sign-in page offers a skip control and
            # the app keeps working as a guest, which is enough to browse the
            # catalogue and needs no credential at all
            if self._skip_login(ctx):
                state = self._page_state(ctx)
        if not state.get("username"):
            # The app can put its sign-in box OVER the page it just opened: the
            # URL is the app's own page, so "the app is open" is true — and
            # every navigation after that lands on the sign-in box instead of
            # the screen that was asked for. The box is only visible in the
            # page itself, so it is looked for there.
            prompt = self._sign_in_prompt(ctx)
            if prompt:
                ctx.log(f"the app shows its own sign-in over the page ({prompt})")
                if self._skip_login(ctx):
                    state = self._page_state(ctx)
        self._session = "account" if app_account(state) else "guest"
        if not self._app_is_open(state):
            return False, ("no web session: the browser is not logged in and the app "
                           "did not open")
        self._ensure_accessibility(ctx)
        self._language = app_language(self._page_state(ctx))
        ctx.log(f"the app shows itself in '{self._language or 'an unknown language'}'")
        return True, ""

    def _dismiss_cookie_banner(self, ctx) -> bool:
        """Close the cookie banner, when it is there.

        The banner lies over the app: a press can land on it instead of on the
        control underneath. It carries a "reject all" button in every language
        the app ships, and it is gone once it has been dismissed.
        """
        value = self._press(ctx, list(COOKIE_BANNER_LABELS), exclude=NEVER_PRESS)
        if not value.get("pressed"):
            return False
        ctx.log("the cookie banner was dismissed")
        self._settle(ctx)
        return True

    def _app_is_open(self, state: dict) -> bool:
        """True when the browser shows the app itself, not a sign-in page.

        The app keeps working without an account (that is what its own
        sign-in bypass is for), so "no account" is not a reason to skip a
        case: what matters is that the app is there to be driven. A browser
        that sits on the sign-in page of the identity provider is not.
        """
        path = str((state or {}).get("path") or "")
        href = str((state or {}).get("href") or "")
        if not path and not href:
            return False
        if not self._is_app_page(href):
            # a blank new tab is not the app: the browser has to open it first
            return False
        low = f"{path} {href}".lower()
        for marker in ("sso", "login", "signin", "auth", "realms", "protocol"):
            if marker in low:
                return False
        return True

    def _skip_login(self, ctx) -> bool:
        """Press the app's own sign-in bypass.

        The sign-in page carries a "skip" control in every language the app
        ships. The app keeps working without an account, so this is the
        platform's own route into the app and it needs no credential.
        """
        pressed = self._press(ctx, list(SKIP_LOGIN_LABELS), exclude=NEVER_PRESS)
        if not pressed.get("pressed"):
            ctx.log(f"the app offers no sign-in bypass ({pressed.get('reason', 'no match')})")
            return False
        self._settle(ctx)
        state = self._page_state(ctx)
        if app_account(state):
            return True
        if not self._sign_in_prompt(ctx):
            # the box is gone: the app let us in as a guest
            ctx.log("the app was entered through its own sign-in bypass")
            return True
        path = url_path(str(state.get("href") or ""))
        if path and "sso" not in path and "login" not in path:
            ctx.log(f"the app was entered through its own sign-in bypass ({path})")
            return True
        ctx.log("the sign-in bypass did not open the app")
        return False

    def _ensure_accessibility(self, ctx: CaseContext) -> bool:
        """Switch the app's accessibility tree on, when the page asks for it.

        Without it the page holds no elements at all (the app draws on a
        canvas), so no tile can be addressed and no label can be read. The
        platform's own `activate_semantic` does this (it also handles the
        shadow-DOM case); clicking the placeholder is the fallback.
        """
        ok, detail, _ = web_action(ctx, "activate_semantic", {})
        if ok:
            ctx.log("the app's accessibility tree was switched on")
            self._settle(ctx)
            return True
        value = self._js(ctx, _JS_ENABLE_ACCESSIBILITY)
        if isinstance(value, dict) and value.get("enabled"):
            ctx.log("the app's accessibility tree was switched on (via the placeholder)")
            self._settle(ctx)
            return True
        ctx.log(f"the accessibility tree could not be switched on: {detail}")
        return False

    # -- navigation --------------------------------------------------------

    def _goto(self, ctx: CaseContext, path: str, expect: str = ""):
        """Open an app screen by its path.

        The platform resolves a relative path against the page it is on, so the
        app's own host and language are kept and nothing is hardcoded here.
        When the browser is not on an app page at all (a fresh profile opens a
        blank new tab), the app's address comes from the tree's own entry edge
        — the platform knows where the app lives.
        """
        current = self._page_url(ctx)
        base = current if self._is_app_page(current) else (self._app_base_url(ctx) or current)
        candidates = []
        resolved = resolve_app_url(path, base)
        if resolved and resolved != path:
            candidates.append(resolved)
        candidates.append(path)
        self._last_landed = ""

        detail = ""
        for url in candidates:
            ok, err, _payload = web_action(ctx, "navigate_to_url", {
                "url": url,
                "page_load_timeout": self._nav_timeout_ms(ctx),
            })
            if not ok:
                detail = err or "the browser refused the navigation"
                continue
            self._settle(ctx)
            # every page load starts with the accessibility tree off again
            self._ensure_accessibility(ctx)
            landed = self._page_url(ctx)
            self._last_landed = landed
            if expect and not url_matches(landed, expect):
                locale = current_locale(landed)
                where = f" (language segment '{locale}')" if locale else ""
                return False, f"the app opened {landed}{where} instead of {expect}"
            return True, ""
        return False, detail

    def _is_app_page(self, url: str) -> bool:
        """True when the browser shows a page of the app (not a blank tab)."""
        text = str(url or "")
        if not text.startswith("http"):
            return False
        low = text.lower()
        if "new-tab-page" in low or "newtab" in low:
            return False
        return True

    def _app_base_url(self, ctx) -> str:
        """The app's own address, read from the tree's entry edge.

        The tree knows where the app lives: its entry edge opens the app's
        home page. The browser may be anywhere — a fresh profile opens a
        blank new tab, and a path resolved against that is nonsense — so the
        address comes from the tree, never from this file.
        """
        executor = getattr(ctx.device, "navigation_executor", None)
        graph = getattr(executor, "unified_graph", None) if executor else None
        if graph is None:
            return ""
        try:
            edges = list(graph.edges(data=True))
        except Exception:                                          # noqa: BLE001
            return ""
        for _source, _target, data in edges:
            for action_set in (data.get("action_sets") or []):
                actions = list(action_set.get("actions") or [])
                actions += list(action_set.get("retry_actions") or [])
                for action in actions:
                    if not isinstance(action, dict):
                        continue
                    if str(action.get("command") or "") != "navigate_to_url":
                        continue
                    url = str((action.get("params") or {}).get("url") or "")
                    if url.startswith("http"):
                        return url
        return ""

    def _open_catalogue_item(self, ctx: CaseContext, catalogue_path: str,
                             names, node: str = "", expect_paths=()):
        """Open one item of a catalogue.

        Returns a dict:

            opened  did an item open?
            detail  what happened, in words
            cause   the attribution when nothing opened (None when it did)
            title   the name of the item, when the page gave one

        The catalogue page is a surface we reached, but the ITEM is only
        reached when one opens. When the tile did not open an item and the
        tree route could not be resolved either, the test never held an item:
        it cannot say the catalogue offers none, so the case is INFRA (our
        interaction, the tree the host loaded), never a product defect.

        `expect_paths` are the language-free paths of the item's own page (the
        replay detail page, the VOD detail page, the player). A tile that opens
        a CATEGORY page (the catalogue shows its categories first) is not the
        item: the URL changed, but the programme was never held, so the press
        does not count and the tree's own route takes over.
        """
        before = url_path(self._page_url(ctx))
        reason = "no item found"
        pressed = self._press_tile(ctx, names)
        if pressed.get("pressed"):
            self._settle(ctx)
            after = url_path(self._page_url(ctx))
            if after != before:
                if not expect_paths or any(part in after for part in expect_paths):
                    return {"opened": True, "detail": "", "cause": None,
                            "title": self._item_title(ctx, pressed)}
                # a category page: the programme is one press further, and the
                # app's own way there is the first tile of the category list
                reason = (f"the tile opened {after}, which is a category page and not "
                          f"the item (the item page is one of "
                          f"{', '.join(expect_paths)})")
                if self._press_item(ctx, expect_paths):
                    return {"opened": True, "detail": "", "cause": None,
                            "title": self._item_title(ctx, {})}
                reason = (f"the tile opened {after}, which is a category page and not "
                          f"the item, and no tile of that page opened the item either")
            else:
                reason = f"the tile did not open an item (still on {after}, expected {catalogue_path})"
        else:
            reason = pressed.get("reason", reason)

        # the platform's own recipe for this catalogue
        if node:
            ok, detail = navigate_to(ctx, node)
            if not ok and "verification failed" in str(detail):
                # the app's tiles are drawn in; a route that starts too early
                # clicks nothing and fails its own check. Wait and try once more.
                self._settle(ctx)
                ok, retry_detail = navigate_to(ctx, node)
                if ok:
                    return {"opened": True, "detail": "", "cause": None,
                            "title": self._item_title(ctx, {})}
                detail = f"{detail}; and again: {retry_detail}"
            if ok:
                return {"opened": True, "detail": "", "cause": None,
                        "title": self._item_title(ctx, {})}
            cause, why = self._route_cause(ctx, node, detail)
            return {"opened": False,
                    "detail": f"{reason}; the tree route failed too ({detail}) — {why}",
                    "cause": cause,
                    "title": ""}
        # the tile was the only way in and it did not open an item: the test
        # could not drive the catalogue, so it cannot judge it
        return {"opened": False, "detail": reason, "cause": CAUSE_INFRA, "title": ""}

    def _press_item(self, ctx, expect_paths) -> bool:
        """Press a tile of the current page and keep it when it opens the item.

        The app draws its catalogue as a canvas: the tiles have no title, so
        the first tile of the main area is the one the app shows first. The
        page it opens is checked against the item's own paths, so a tile that
        opens something else is not taken for the item.
        """
        before = url_path(self._page_url(ctx))
        pressed = self._press_tile(ctx, [])
        if not pressed.get("pressed"):
            return False
        self._settle(ctx)
        after = url_path(self._page_url(ctx))
        if after == before:
            return False
        if expect_paths and not any(part in after for part in expect_paths):
            return False
        return True

    def _route_cause(self, ctx: CaseContext, node: str, detail: str):
        """(cause, why) for a tree route that could not be opened.

        The resolver could not find the node in the graph the host loaded:
        that tree is ours, so the navigation is INFRA and never a product
        defect. For the other failures the harness knows the three cases
        (the screen does not match the tree's picture → infra, the node is in
        the tree and the route failed → product, the node is not in this UI →
        coverage).
        """
        if _graph_missing(detail):
            return CAUSE_INFRA, (f"the navigation graph the host loaded does not carry the "
                                 f"'{node}' node, so this run cannot conclude anything "
                                 f"about the product")
        outcome = surface_failure(ctx, node, detail,
                                  reason=f"the tree route to '{node}' failed")
        if verification_mismatch(detail):
            why = ("the screen does not match the tree's reference picture, so this run "
                   "cannot conclude anything about the product")
        elif outcome.cause == CAUSE_PRODUCT:
            why = f"the '{node}' node is in the tree and the route to it failed"
        else:
            why = f"the '{node}' surface is not in this UI's navigation tree"
        return outcome.cause, why

    def _catalogue_outcome(self, pick: dict, evidence: dict, what: str) -> CaseOutcome:
        """The outcome for a catalogue the test could not pick an item from."""
        reason = f"the test could not open {what} to play: {pick.get('detail', '')}"
        cause = pick.get("cause") or CAUSE_INFRA
        if cause == CAUSE_COVERAGE:
            return CaseOutcome.skipped(reason, cause=CAUSE_COVERAGE, evidence=evidence)
        return CaseOutcome.failed(reason, cause=cause, evidence=evidence)

    def _item_title(self, ctx: CaseContext, pressed: dict) -> str:
        """The name of the item we opened, when the page gives one.

        A tile that carries no text has no name of its own: the page it
        opened may still name the item. An empty title means the item was
        never positively identified. The name is bounded: a page can say
        thousands of characters and the report wants the name.
        """
        label = str((pressed or {}).get("label") or "").strip()
        if label:
            return label[:120]
        text = self._page_text(ctx)
        for part in text.split("|"):
            part = part.strip()
            if part:
                return part[:120]
        return ""

    def _open_programme_panel(self, ctx: CaseContext):
        """Open the panel of the programme that is on now. Returns (ok, detail)."""
        ok, detail = navigate_to(ctx, NODE_TV_GUIDE_PROGRAMME)
        if ok:
            return True, ""
        pressed = self._press_grid_centre(ctx)
        if not pressed.get("pressed"):
            reason = pressed.get("reason", "no programme cell found")
            return False, (f"{reason}; the tree route to '{NODE_TV_GUIDE_PROGRAMME}' "
                           f"failed too ({detail})")
        self._settle(ctx)
        return True, ""

    def _start_playback(self, ctx: CaseContext):
        """Press the play action of the page. Returns (ok, detail)."""
        pressed = self._press(ctx, list(PLAY_ACTION_LABELS),
                              exclude=NEVER_PRESS + ("trailer", "watch live"))
        if not pressed.get("pressed"):
            return False, pressed.get("reason", "no play action on the page")
        self._settle(ctx)
        return True, ""

    def _sign_in_prompt(self, ctx) -> str:
        """The app's own sign-in prompt, when the page carries one.

        The app answers a session that covers the catalogue with a sign-in
        box on the pages that play content. When that box is there, the page
        has no play action because the app refuses to play it for this
        session — a session problem, never a product defect.
        """
        text = self._page_text(ctx)
        if not text:
            return ""
        low = text.lower()
        for phrase in SIGN_IN_PHRASES:
            if phrase in low:
                return phrase
        return ""

    # -- the browser -------------------------------------------------------

    def _js(self, ctx: CaseContext, script: str):
        """Run one snippet in the page and return its value (None on failure)."""
        ok, _detail, payload = web_action(ctx, "execute_javascript", {"script": script})
        if not ok:
            return None
        value = payload.get("result") if isinstance(payload, dict) else None
        return value

    def _page_state(self, ctx: CaseContext) -> dict:
        value = self._js(ctx, _JS_PAGE_STATE)
        return value if isinstance(value, dict) else {}

    def _page_url(self, ctx: CaseContext) -> str:
        return str(self._page_state(ctx).get("href") or "")

    def _page_text(self, ctx: CaseContext) -> str:
        value = self._js(ctx, _JS_PAGE_TEXT)
        return value if isinstance(value, str) else ""

    def _items(self, ctx: CaseContext) -> list:
        value = self._js(ctx, _JS_LIST_ITEMS)
        if isinstance(value, list):
            return [str(v) for v in value]
        return []

    def _press(self, ctx: CaseContext, labels, exclude=(), index: int = 0) -> dict:
        before = self._fingerprint(ctx)
        script = _JS_PRESS_LABEL.replace("__CFG__", json.dumps({
            "labels": list(labels), "exclude": list(exclude), "index": index}))
        value = self._js(ctx, script)
        if not isinstance(value, dict):
            return {"pressed": False, "reason": "the browser did not answer"}
        self._press_fallbacks(ctx, value, before, labels)
        return value

    def _press_tile(self, ctx: CaseContext, labels=()) -> dict:
        before = self._fingerprint(ctx)
        script = _JS_PRESS_TILE.replace("__CFG__", json.dumps({"labels": list(labels)}))
        value = self._js(ctx, script)
        if not isinstance(value, dict):
            return {"pressed": False, "reason": "the browser did not answer"}
        self._press_fallbacks(ctx, value, before, labels)
        return value

    def _fingerprint(self, ctx: CaseContext) -> str:
        """What the page shows, in one line: its URL and its text.

        Two equal fingerprints mean the page did not react to the press.
        """
        text = " ".join(self._page_text(ctx).split())
        return f"{self._page_url(ctx)}|{text[:400]}"

    def _press_fallbacks(self, ctx: CaseContext, value: dict, before: str, labels=()) -> bool:
        """Make the press happen, in the order this app actually answers.

        The page script dispatches untrusted MouseEvents, and a canvas-drawn
        app ignores them. The platform's own `click_element` — a native click
        on the element of the semantics tree — is what the app answers, and
        the browser controller's `tap_x_y` is the last resort. Each step runs only
        when the previous one changed NOTHING on the page, so a press that
        already worked is never repeated (a second press on a Record button
        would undo the first one).

        The platform's click also finds what the page script cannot see: the
        page script presses only what is on screen, while the platform dumps
        the whole semantics tree. The app's language option is one of those
        (it sits in a dropdown), so the click is tried even when the page
        script pressed nothing at all.
        """
        if not value.get("pressed"):
            return self._press_by_platform(ctx, labels, before)
        x, y = value.get("x"), value.get("y")
        label = str(value.get("label") or "").strip()
        self._settle(ctx)
        if self._fingerprint(ctx) != before:
            return True

        # 1. the platform's own click, by the label the app publishes
        candidates = [part for part in (label.split(",")[0].strip(), label) if part]
        candidates.extend(str(part) for part in labels)
        if self._press_by_platform(ctx, candidates, before):
            return True

        # 2. the controller's real click at the coordinates the page gave
        if x is not None and y is not None:
            ok, detail, _ = web_action(ctx, "tap_x_y", {"x": int(x), "y": int(y)})
            if not ok:
                ctx.log(f"the real click at ({x}, {y}) was refused: {detail}")
            else:
                self._settle(ctx)
                return True
        return False

    def _press_by_platform(self, ctx: CaseContext, labels, before: str) -> bool:
        """The platform's own click, by label: the press this app answers.

        Every candidate is tried in turn and the first one that changes the
        page wins. A label the platform does not know is not an error: the
        next candidate is tried.
        """
        for candidate in labels:
            candidate = str(candidate or "").strip()
            if not candidate:
                continue
            ok, detail, _ = web_action(ctx, "click_element", {"text": candidate})
            if not ok:
                ctx.log(f"the click on {candidate!r} was refused: {detail}")
                continue
            self._settle(ctx)
            if self._fingerprint(ctx) != before:
                ctx.log(f"the click on {candidate!r} opened the item")
                return True
        return False

    def _press_grid_centre(self, ctx: CaseContext) -> dict:
        value = self._js(ctx, _JS_PRESS_GRID_CENTRE)
        return value if isinstance(value, dict) else {"pressed": False, "reason": "the browser did not answer"}

    def _programme_title(self, ctx: CaseContext) -> str:
        value = self._js(ctx, _JS_PANEL_TITLES)
        if isinstance(value, list) and value:
            return str(value[0])
        return ""

    def _looks_like_player(self, url: str) -> bool:
        path = url_path(url or "")
        # the live player and the VOD player (the catalogue and the detail
        # pages carry other paths, the replay catalogue for instance)
        return "player" in path or PATH_VOD_PLAYER in path

    # -- playback ----------------------------------------------------------

    def _confirm_playback(self, ctx: CaseContext, evidence: dict, audio: bool = False) -> CaseOutcome:
        """Watch the player and say what the playback meant."""
        window_s = max(0.0, float(ctx.arg("play_seconds", 12) or 12))
        interval = max(0.5, float(ctx.arg("probe_interval_s", 2.0) or 2.0))

        samples = []
        block = None
        phrase = ""
        elapsed = 0.0
        while True:
            sample = self._media_status(ctx, audio)
            if sample:
                samples.append(sample)
            kind, found = _classify_phrase(self._page_text(ctx))
            if kind:
                block, phrase = kind, found
                break
            elapsed += interval
            if elapsed >= window_s:
                break
            sleep(ctx, interval)

        progress, playing = calc_playback_progress(samples)
        evidence["progress_s"] = round(progress, 2)
        evidence["samples"] = len(samples)
        evidence["window_s"] = round(elapsed, 1)
        if audio:
            state = self._js(ctx, WEB_JS_AUDIO_STATE)
            if isinstance(state, dict):
                evidence["media_tag"] = state.get("tag", "")
                evidence["muted"] = state.get("muted")
        shot = capture(ctx, "web_playback_probe")
        if shot:
            evidence["screenshot"] = shot

        if block == "geo":
            evidence["block"] = "geo-block"
            return CaseOutcome.failed(
                f"playback is geo-blocked outside Switzerland: the player says '{phrase}' "
                f"(environment condition, not a product defect)",
                cause=CAUSE_INFRA, evidence=evidence)
        if block == "refusal":
            evidence["block"] = "player refusal"
            return CaseOutcome.failed(
                f"the player opened but refused the stream: '{phrase}' "
                f"(the player surface is up, the content is not served from here)",
                cause=self._refusal_cause(ctx), evidence=evidence)
        if playing:
            return CaseOutcome.passed(
                f"playback confirmed: the media advanced {progress:.1f}s over {elapsed:.0f}s "
                f"({len(samples)} samples)",
                evidence=evidence)
        return CaseOutcome.failed(
            f"playback did not start: the media element stayed paused for {elapsed:.0f}s "
            f"({len(samples)} samples, {progress:.1f}s of progress)",
            cause=CAUSE_PRODUCT, evidence=evidence)

    def _media_status(self, ctx: CaseContext, audio: bool):
        """One playback sample. The video probe is the shared one."""
        if audio:
            value = self._js(ctx, _JS_AUDIO_PROGRESS)
        else:
            value = self._js(ctx, WEB_JS_VIDEO_STATUS)
        return value if isinstance(value, dict) else None

    # -- radio discovery ---------------------------------------------------

    def _discover_radio(self, ctx: CaseContext, evidence: dict):
        """Look for a radio surface. Returns (opened, detail, failure).

        `failure` is a CaseOutcome when a node that IS in the tree could not
        be opened: the surface is there and it did not work, which is a
        product defect and not a missing surface. The discovery conclusion
        itself (no radio entry point anywhere) stays a coverage gap.
        """
        failure = None
        # when the run names the nodes to probe, the tree is the source
        probe_nodes = self._radio_probe_nodes(ctx)
        if probe_nodes:
            evidence["discovery"].append(f"probing the nodes {', '.join(probe_nodes)}")
            for node in probe_nodes:
                ok, detail = navigate_to(ctx, node)
                if not ok:
                    evidence["discovery"].append(f"{node}: {detail}")
                    outcome = surface_failure(
                        ctx, node, detail,
                        reason=f"the radio surface '{node}' could not be opened")
                    if outcome.cause == CAUSE_PRODUCT and failure is None:
                        failure = outcome
                    continue
                hits = [i for i in self._items(ctx) if "radio" in _norm(i)]
                evidence["discovery"].append(f"{node}: {len(hits)} entries with 'radio'")
                if hits:
                    pressed = self._press(ctx, ["radio"], exclude=NEVER_PRESS)
                    if pressed.get("pressed"):
                        self._settle(ctx)
                        return True, f"found in {node} ({hits[0]})", failure
            return False, f"no radio entry point on {', '.join(probe_nodes)}", failure

        # 1. the search
        opened, detail = self._goto(ctx, PATH_SEARCH)
        evidence["discovery"].append(f"search: {'opened' if opened else detail}")
        if opened:
            typed = self._type(ctx, "radio")
            if typed:
                self._settle(ctx)
                items = self._items(ctx)
                hits = [i for i in items if "radio" in _norm(i)]
                evidence["discovery"].append(f"search results with 'radio': {len(hits)}")
                if hits:
                    pressed = self._press(ctx, ["radio"], exclude=NEVER_PRESS)
                    if pressed.get("pressed"):
                        self._settle(ctx)
                        return True, f"found in the search ({hits[0]})", failure
                    evidence["discovery"].append("the radio result could not be opened")

        # 2. the home screen
        opened, detail = self._goto(ctx, PATH_HOME)
        evidence["discovery"].append(f"home: {'opened' if opened else detail}")
        if opened:
            hits = [i for i in self._items(ctx) if "radio" in _norm(i)]
            evidence["discovery"].append(f"home entries with 'radio': {len(hits)}")
            if hits:
                pressed = self._press(ctx, ["radio"], exclude=NEVER_PRESS)
                if pressed.get("pressed"):
                    self._settle(ctx)
                    return True, f"found on the home screen ({hits[0]})", failure

        # 3. the TV Guide (a radio channel in the grid)
        opened, detail = self._goto(ctx, PATH_TV_GUIDE)
        evidence["discovery"].append(f"tv guide: {'opened' if opened else detail}")
        if opened:
            hits = [i for i in self._items(ctx) if "radio" in _norm(i)]
            evidence["discovery"].append(f"tv guide entries with 'radio': {len(hits)}")
            if hits:
                pressed = self._press(ctx, ["radio"], exclude=NEVER_PRESS)
                if pressed.get("pressed"):
                    self._settle(ctx)
                    return True, f"found in the TV Guide ({hits[0]})", failure

        return False, ("no radio entry point on the search, the home screen or the "
                       "TV Guide"), failure

    def _type(self, ctx: CaseContext, text: str) -> bool:
        """Type into the first visible field and submit."""
        ok, detail, _payload = web_action(ctx, "input_text", {
            "selector": "input",
            "text": text,
            "press_enter": True,
        })
        if ok:
            return True
        script = _JS_FILL_FIELD.replace("__CFG__", json.dumps({"text": text}))
        value = self._js(ctx, script)
        if isinstance(value, dict) and value.get("filled"):
            web_action(ctx, "press_key", {"key": "Enter"})
            return True
        ctx.log(f"could not type into the search field: {detail}")
        return False

    # -- the recording -----------------------------------------------------

    def _wait_for_recording(self, ctx: CaseContext, before: list, title: str):
        """Wait for the recording to show up in the list. Returns (listed, item, detail)."""
        wait_s = float(ctx.arg("record_wait_s", 45) or 45)
        poll_s = max(2.0, float(ctx.arg("record_poll_s", 5) or 5))
        waited = 0.0
        items = []
        while True:
            opened, _detail = self._goto(ctx, PATH_RECORDINGS, expect=PATH_RECORDINGS)
            if opened:
                items = self._items(ctx)
                item = self._find_recording(items, title, before)
                if item:
                    return True, item, f"listed after {waited:.0f}s"
            waited += poll_s
            if waited > wait_s:
                break
            sleep(ctx, poll_s)
        return False, "", (f"waited {waited:.0f}s; the list holds {len(items)} entries "
                          f"and none of them is the recording")

    def _find_recording(self, items: list, title: str, before: list):
        """The recording in the list: by its title, else the entry that is new."""
        if title:
            name = _norm(title.split(" - ")[-1])
            if len(name) > 3:
                for item in items:
                    if name in _norm(item):
                        return item
        known = {_norm(i) for i in before}
        for item in items:
            if _norm(item) not in known:
                return item
        return ""

    # -- small helpers -----------------------------------------------------

    def _record_enabled(self, ctx: CaseContext) -> bool:
        value = ctx.arg("record_enabled", True)
        if isinstance(value, str):
            return value.strip().lower() not in ("0", "false", "no", "off")
        return bool(value)

    def _radio_probe_nodes(self, ctx: CaseContext) -> list:
        """The nodes the run wants the radio probe to walk (empty: the built-in probe)."""
        raw = str(ctx.arg("radio_probe_nodes", "") or "")
        return [node.strip() for node in raw.split(",") if node.strip()]

    def _refusal_cause(self, ctx: CaseContext) -> str:
        value = str(ctx.arg("player_refusal_cause", CAUSE_INFRA) or CAUSE_INFRA).strip().lower()
        if value == CAUSE_PRODUCT:
            return CAUSE_PRODUCT
        return CAUSE_INFRA

    def _nav_timeout_ms(self, ctx: CaseContext) -> int:
        return int(float(ctx.arg("nav_timeout_s", 30) or 30) * 1000)

    def _settle(self, ctx: CaseContext) -> None:
        sleep(ctx, float(ctx.arg("settle_ms", 800) or 800) / 1000.0)
