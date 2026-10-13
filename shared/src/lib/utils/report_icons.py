"""One icon set for the HTML reports: small monochrome line icons (16 px, 1.75 stroke, currentColor), drawn
inline so a report stays a single self-contained file and the icons follow the light/dark theme.

Use `icon('logs')`. Emoji in script output and language strings are drawn with this set too, at render
time (`iconify_html`, plus the page script after a language switch), so every report uses one set
whatever the language."""

import json
import re

_PATHS = {
    # document with lines
    'logs': '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5"/><path d="M9 13h6M9 17h6"/>',
    # stacked disks
    'metadata': '<ellipse cx="12" cy="5.5" rx="7" ry="2.5"/><path d="M5 5.5v13c0 1.4 3.1 2.5 7 2.5s7-1.1 7-2.5v-13"/><path d="M5 12c0 1.4 3.1 2.5 7 2.5s7-1.1 7-2.5"/>',
    # clipboard with check
    'review': '<rect x="6" y="4" width="12" height="17" rx="2"/><path d="M9 4.5V3h6v1.5"/><path d="m9 13 2 2 4-4"/>',
    # magnifier
    'ui_dumps': '<circle cx="11" cy="11" r="6"/><path d="m20 20-4.3-4.3"/>',
    # code brackets
    'code': '<path d="m9 8-4 4 4 4M15 8l4 4-4 4"/>',
    # screen
    'zap': '<rect x="3" y="5" width="18" height="12" rx="2"/><path d="M8 21h8M12 17v4"/>',
    # screen with subtitle lines
    'subtitle': '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="M7 13h4M13 13h4M7 16h7"/>',
    # 2x2 grid
    'mosaic': '<rect x="4" y="4" width="7" height="7" rx="1"/><rect x="13" y="4" width="7" height="7" rx="1"/><rect x="4" y="13" width="7" height="7" rx="1"/><rect x="13" y="13" width="7" height="7" rx="1"/>',
    # globe
    'dom': '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c2.5 2.7 3.8 5.7 3.8 9s-1.3 6.3-3.8 9c-2.5-2.7-3.8-5.7-3.8-9S9.5 5.7 12 3z"/>',
    # tag
    'version': '<path d="M3 12V4h8l9 9-8 8z"/><circle cx="7.5" cy="8.5" r="1.3"/>',
    # compass
    'edge': '<circle cx="12" cy="12" r="9"/><path d="m15.5 8.5-2 5-5 2 2-5z"/>',
    # alert circle
    'error': '<circle cx="12" cy="12" r="9"/><path d="M12 7.5v5.5M12 16.5h.01"/>',
    # arrow out of a box
    'open': '<path d="M14 4h6v6M20 4l-9 9"/><path d="M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5"/>',
    # arrow down into a tray
    'download': '<path d="M12 4v11M7.5 10.5 12 15l4.5-4.5"/><path d="M5 19h14"/>',
    # share: three linked dots
    'share': '<circle cx="6" cy="12" r="2.2"/><circle cx="17" cy="6" r="2.2"/><circle cx="17" cy="18" r="2.2"/><path d="m8 11 7-4M8 13l7 4"/>',
    # play in a circle
    'trigger': '<circle cx="12" cy="12" r="9"/><path d="m10 8.5 5 3.5-5 3.5z"/>',
    # theme switch
    'sun': '<circle cx="12" cy="12" r="4"/><path d="M12 2.5v2M12 19.5v2M4.6 4.6 6 6M18 18l1.4 1.4M2.5 12h2M19.5 12h2M4.6 19.4 6 18M18 6l1.4-1.4"/>',
    'moon': '<path d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z"/>',
    'monitor': '<rect x="3" y="4" width="18" height="12" rx="2"/><path d="M8 20h8M12 16v4"/>',
    # status and summary marks (the emoji map below)
    'check_circle': '<circle cx="12" cy="12" r="9"/><path d="m8 12.5 2.7 2.7L16 9.8"/>',
    'x_circle': '<circle cx="12" cy="12" r="9"/><path d="m9 9 6 6M15 9l-6 6"/>',
    'alert_triangle': '<path d="M10.3 4.2 2.6 17.5A2 2 0 0 0 4.3 20.5h15.4a2 2 0 0 0 1.7-3L13.7 4.2a2 2 0 0 0-3.4 0z"/><path d="M12 9.5v4M12 17h.01"/>',
    'check': '<path d="m5 12.5 4.5 4.5L19 7.5"/>',
    'x': '<path d="m6.5 6.5 11 11M17.5 6.5l-11 11"/>',
    'target': '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1.2"/>',
    'clock': '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    'bar_chart': '<path d="M4 20h16"/><path d="M7 16v-5M12 16V6M17 16v-8"/>',
    'clipboard': '<rect x="6" y="4" width="12" height="17" rx="2"/><path d="M9 4.5V3h6v1.5"/><path d="M9 11h6M9 15h4"/>',
    'camera': '<path d="M4 8h3l1.5-2.5h7L17 8h3a1 1 0 0 1 1 1v9a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V9a1 1 0 0 1 1-1z"/><circle cx="12" cy="13" r="3.5"/>',
    'link': '<path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1"/><path d="M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1"/>',
    'info': '<circle cx="12" cy="12" r="9"/><path d="M12 11v5.5M12 7.5h.01"/>',
    'skip': '<path d="m5 6 7 6-7 6zM13 6l7 6-7 6"/><path d="M20 6v12"/>',
    'refresh': '<path d="M20 11a8 8 0 0 0-14.3-4.9L4 8"/><path d="M4 4v4h4"/><path d="M4 13a8 8 0 0 0 14.3 4.9L20 16"/><path d="M20 20v-4h-4"/>',
}


def icon(name: str, size: int = 16) -> str:
    """Inline SVG for `name` (empty string for an unknown name)."""
    body = _PATHS.get(name)
    if not body:
        return ''
    return (f'<svg class="r-icon" width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
            f'stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{body}</svg>')


# --------------------------------------------------------------------------- emoji -> icon
# Script output and a few language strings carry emoji ("✅ Online host found", "📊 Checks: 4").
# The report draws them with the icon set above instead, at render time only: logs, printed text
# and i18n keys keep their emoji. An emoji not listed here is left as it is.
# tone: 'ok' / 'fail' / 'warn' colour the icon from the report palette, None = main text colour.
EMOJI_ICONS = {
    '\u2705': ('check_circle', 'ok'),      # ✅
    '\u2714': ('check', 'ok'),             # ✔
    '\u2713': ('check', 'ok'),             # ✓
    '\u274c': ('x_circle', 'fail'),        # ❌
    '\u2718': ('x', 'fail'),               # ✘
    '\u2717': ('x', 'fail'),               # ✗
    '\u26a0': ('alert_triangle', 'warn'),  # ⚠
    '\U0001f3af': ('target', None),        # 🎯
    '\U0001f310': ('dom', None),           # 🌐
    '\U0001f4fa': ('monitor', None),       # 📺
    '\u23f1': ('clock', None),             # ⏱
    '\u231a': ('clock', None),             # ⌚
    '\U0001f4ca': ('bar_chart', None),     # 📊
    '\U0001f4cb': ('clipboard', None),     # 📋
    '\U0001f4f8': ('camera', None),        # 📸
    '\U0001f517': ('link', None),          # 🔗
    '\u2139': ('info', None),              # ℹ
    '\U0001f50d': ('ui_dumps', None),      # 🔍
    '\u23ed': ('skip', 'warn'),            # ⏭
    '\U0001f504': ('refresh', None),       # 🔄
    '\u2197': ('open', None),              # ↗
}

# the emoji plus an optional variation selector (U+FE0F: "⚠️" vs "⚠")
EMOJI_RE = re.compile('(' + '|'.join(re.escape(k) for k in EMOJI_ICONS) + ')\ufe0f?')


def emoji_icon(emoji: str) -> str:
    """Inline SVG standing in for `emoji` (sized in em so it follows the text it sits in)."""
    name, tone = EMOJI_ICONS[emoji]
    tone_class = f' tone-{tone}' if tone else ''
    return (f'<svg class="r-icon r-emoji{tone_class}" role="img" aria-label="{emoji}" width="16" height="16" '
            f'viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" '
            f'stroke-linejoin="round">{_PATHS[name]}</svg>')


_TAG_RE = re.compile(r'(<[^>]*>)')
_RAW_TEXT_TAGS = ('script', 'style', 'textarea', 'title')


def iconify_html(page: str) -> str:
    """Swap mapped emoji for icons in the TEXT of an HTML page (never in tags, attributes,
    <script>, <style>, <textarea> or <title>)."""
    if not page or not EMOJI_RE.search(page):
        return page
    parts = _TAG_RE.split(page)
    skip_until = None
    for i, part in enumerate(parts):
        if i % 2:  # a tag
            low = part[:12].lower()
            if skip_until:
                if low.startswith('</' + skip_until):
                    skip_until = None
            else:
                for name in _RAW_TEXT_TAGS:
                    if low.startswith('<' + name) and not part.endswith('/>'):
                        skip_until = name
                        break
        elif not skip_until and part:
            parts[i] = EMOJI_RE.sub(lambda m: emoji_icon(m.group(1)), part)
    return ''.join(parts)


def emoji_icons_script_tag() -> str:
    """The emoji -> SVG map for the page script, which redraws icons after a language switch."""
    data = json.dumps({k: emoji_icon(k) for k in EMOJI_ICONS}, ensure_ascii=True, separators=(',', ':'))
    return f'<script id="vpt-emoji-icons" type="application/json">{data}</script>'
