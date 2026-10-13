"""Shape check for a widget layout before it is stored (user_widget_layouts.layout).

The browser sends what it has; the server only keeps a list of
{id: str, widgetId: str, settings: {str: str | bool}} and refuses anything else, so a bad
client cannot fill the row with arbitrary JSON.
"""

from typing import Any, List, Optional, Tuple

MAX_WIDGETS = 50
MAX_TEXT = 100
MAX_SETTINGS = 20
AREAS = frozenset({'dashboard'})


def _text(value: Any) -> bool:
    return isinstance(value, str) and 0 < len(value) <= MAX_TEXT


def clean_layout(layout: Any) -> Tuple[Optional[List[dict]], Optional[str]]:
    """(cleaned layout, None) or (None, why it was refused)."""
    if not isinstance(layout, list):
        return None, 'layout must be a list'
    if len(layout) > MAX_WIDGETS:
        return None, f'at most {MAX_WIDGETS} widgets'
    cleaned = []
    for item in layout:
        if not isinstance(item, dict) or not _text(item.get('id')) or not _text(item.get('widgetId')):
            return None, 'each widget needs a text id and widgetId'
        settings = item.get('settings') or {}
        if not isinstance(settings, dict) or len(settings) > MAX_SETTINGS:
            return None, 'settings must be an object'
        if not all(_text(k) and (isinstance(v, bool) or (isinstance(v, str) and len(v) <= MAX_TEXT)) for k, v in settings.items()):
            return None, 'settings values must be text or true/false'
        cleaned.append({'id': item['id'], 'widgetId': item['widgetId'], 'settings': settings})
    return cleaned, None


def valid_area(area: Optional[str]) -> bool:
    return area in AREAS
