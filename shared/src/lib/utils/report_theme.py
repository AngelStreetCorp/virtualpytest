"""
Report theme — the web app's palette for every HTML page the backend generates.

One source for standalone report pages (KPI, zap, restart video, heatmap, subtitle QA, game
and drone reports, DOM / graph reports, share pages, CI/CD pages, security dashboard): the
same tokens as the web app (frontend/src/constants/agentChatTheme.ts, docs/agent/platform/
UI_STYLE.md), a light and a dark set, and the app's theme choice.

    from shared.src.lib.utils.report_theme import report_theme_head
    html = f"<head>{report_theme_head()}<style>body {{ background: var(--vpt-page); }}</style></head>"

- Colours: only `var(--vpt-*)` in page CSS; no hex.
- Theme: `data-theme` on <html> follows localStorage 'theme-mode' (the app's key; reports are
  served from the app's origin) — light / dark / system, default system. Without JS the page
  follows the OS. A theme change in the app reaches open pages (storage event).
- `color-scheme: light dark` tells browsers the page does its own dark theme, so auto-dark
  (Chrome "Auto Dark Mode", Dark Reader) leaves it alone (BUG-0426).

The main script/campaign report (report_template_css.py) keeps its own variable names; its
values are the same palette.
"""

# name: (light, dark) — keep in step with frontend/src/constants/agentChatTheme.ts
REPORT_PALETTE = {
    'page': ('#f2f0ec', '#0a0a0a'),         # page background
    'surface': ('#ffffff', '#242424'),      # cards, panels, table body
    'subtle': ('#ebe7e0', '#2a2a2a'),       # table header, row hover, inset, track
    'rail': ('#ffffff', '#1e1e1e'),         # side rails / nav panels
    'text': ('#141414', '#f0f0f0'),
    'text-2': ('#4a4a4a', '#9a9a9a'),       # supporting text
    'muted': ('#6e6e6e', '#666666'),        # hints, captions, meta
    'border': ('#d9d4cc', '#383838'),       # every hairline
    'accent': ('#d4a574', '#d4a574'),       # selection, focus, the one filled action
    'accent-text': ('#8f5f2e', '#d4a574'),  # gold as text / icon / link
    'on-accent': ('#1a1a1a', '#1a1a1a'),    # text on a filled gold button
    'success': ('#16a34a', '#22c55e'),
    'error': ('#dc2626', '#ef4444'),
    'warning': ('#b45309', '#f59e0b'),
    'steel': ('#3f6f8f', '#7aa6c2'),        # categorical 2 (series[1])
    'purple': ('#6f5596', '#a98bc7'),       # categorical 3 (series[2])
    'rose': ('#9a4f4f', '#c98b8b'),         # categorical 4 (series[3])
    'sage': ('#4f7f5f', '#8fbf9f'),         # categorical 5 (series[4])
    'shadow': ('0 1px 3px rgba(60,50,30,0.08)', '0 2px 8px rgba(0,0,0,0.3)'),
}


def _vars(index: int) -> str:
    return '\n'.join(f'  --vpt-{name}: {values[index]};' for name, values in REPORT_PALETTE.items())


def report_theme_css() -> str:
    """CSS: the palette as --vpt-* variables, light by default, dark under data-theme / OS."""
    light, dark = _vars(0), _vars(1)
    return (
        f':root {{\n  color-scheme: light dark;\n{light}\n}}\n'
        f'[data-theme="dark"] {{\n{dark}\n}}\n'
        f'@media (prefers-color-scheme: dark) {{\n  :root:not([data-theme="light"]) {{\n{dark}\n  }}\n}}\n'
        # Tints: status / accent at ~12% for pill fills and selected rows.
        ':root { --vpt-success-tint: color-mix(in srgb, var(--vpt-success) 12%, transparent);'
        ' --vpt-error-tint: color-mix(in srgb, var(--vpt-error) 12%, transparent);'
        ' --vpt-warning-tint: color-mix(in srgb, var(--vpt-warning) 12%, transparent);'
        ' --vpt-accent-tint: color-mix(in srgb, var(--vpt-accent) 15%, transparent); }\n'
    )


REPORT_THEME_JS = """(function () {
  var KEY = 'theme-mode';
  function mode() {
    try { var m = localStorage.getItem(KEY); if (m === 'light' || m === 'dark' || m === 'system') return m; } catch (e) {}
    return 'system';
  }
  function apply(m) {
    var dark = m === 'dark' || (m === 'system' && window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches);
    document.documentElement.setAttribute('data-theme', dark ? 'dark' : 'light');
  }
  apply(mode());
  window.addEventListener('storage', function (e) { if (e.key === KEY) apply(mode()); });
  if (window.matchMedia) window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', function () { apply(mode()); });
  window.addEventListener('beforeprint', function () { document.documentElement.setAttribute('data-theme', 'light'); });
  window.addEventListener('afterprint', function () { apply(mode()); });
})();"""


def report_theme_head() -> str:
    """Everything a generated page puts in <head> for the palette and the app's theme.

    Plain string (no format braces to escape): concatenate it, don't pass it through str.format().
    """
    return (
        '<meta name="color-scheme" content="light dark">\n'
        f'<style>\n{report_theme_css()}</style>\n'
        f'<script>{REPORT_THEME_JS}</script>\n'
    )
