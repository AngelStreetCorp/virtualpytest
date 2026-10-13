"""
Report i18n (TASK-52)

Turns report text into `<span data-i18n="key" data-i18n-args='{...}'>English</span>` so the
report page can switch language in the browser. The English text is always in the page, so the
report reads correctly with JavaScript off. Nothing here calls an AI: translations are static files.

Files:
  report/<code>.json          Platform strings. en.json is the source of truth; every file in the
                              folder is an available language; `_name` is its native name.
  <script>.i18n.json          Optional, next to a script (`goto.py` -> `goto.i18n.json`):
                              {"English template with {name}": {"fr": "...", "de": "..."}}
  main._i18n = {...}          The same dict inside the script source (works for virtual scripts,
                              which have no file next to them). Wins over the file, entry by entry.

Active only inside `use_report_catalog(catalog)`. Outside it t() returns plain English and tx()
returns the escaped text, so every other report is unaffected.
"""

import contextvars
import html
import json
import os
import re
from contextlib import contextmanager
from functools import lru_cache
from typing import Dict, Iterator, List, Optional, Tuple

DEFAULT_LANGUAGE = 'en'
SCRIPT_KEY_PREFIX = 's:'
MSG_PREFIX = 'msg.'
_LANGUAGE_ORDER = ('en', 'fr', 'de')

_REPORT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'report')
_PLACEHOLDER_RE = re.compile(r'\{(\w+)\}')
_LOOP_TAG_RE = re.compile(r'^(\[\d+/\d+\] )(.+)$')

_active: contextvars.ContextVar = contextvars.ContextVar('vpt_report_catalog', default=None)


# --------------------------------------------------------------------------- loading

@lru_cache(maxsize=1)
def load_platform_strings() -> Dict[str, Dict[str, str]]:
    """{lang: {key: text}} for every report/<code>.json present (en first)."""
    result: Dict[str, Dict[str, str]] = {}
    try:
        names = sorted(n for n in os.listdir(_REPORT_DIR) if n.endswith('.json'))
    except OSError:
        names = []
    for name in names:
        code = name[:-5]
        try:
            with open(os.path.join(_REPORT_DIR, name), 'r', encoding='utf-8') as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            continue
        if isinstance(data, dict):
            result[code] = {k: v for k, v in data.items() if isinstance(v, str)}
    # Switcher order: the default first, then the listed order, then any new language by code.
    order = [c for c in _LANGUAGE_ORDER if c in result] + sorted(c for c in result if c not in _LANGUAGE_ORDER)
    return {code: result[code] for code in order}


def available_languages() -> Dict[str, str]:
    """{code: native name}, English first."""
    return {code: strings.get('_name', code) for code, strings in load_platform_strings().items()}


def load_script_strings(path: Optional[str]) -> Dict[str, Dict[str, str]]:
    """Read one `<script>.i18n.json`. Anything unreadable or malformed gives {} (never raises)."""
    if not path:
        return {}
    try:
        with open(path, 'r', encoding='utf-8') as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    return clean_script_strings(data)


def clean_script_strings(data) -> Dict[str, Dict[str, str]]:
    """Keep only well-formed `{"English template": {"fr": "...", ...}}` entries (file or `main._i18n`)."""
    if not isinstance(data, dict):
        return {}
    clean: Dict[str, Dict[str, str]] = {}
    for template, translations in data.items():
        if template.startswith('_') or not isinstance(translations, dict):
            continue
        langs = {lang: text for lang, text in translations.items() if isinstance(text, str) and text}
        if langs:
            clean[template] = langs
    return clean


def script_i18n_path(script_name: Optional[str]) -> str:
    """Path of `<script source without .py>.i18n.json`, or '' when the script ships none."""
    if not script_name:
        return ''
    try:
        from shared.src.lib.utils.script_identity_utils import normalize_script_ref, resolve_script_source_path
        source = resolve_script_source_path(normalize_script_ref(script_name))
    except Exception:
        return ''
    if not source or not source.endswith('.py'):
        return ''
    candidate = source[:-3] + '.i18n.json'
    return candidate if os.path.isfile(candidate) else ''


# --------------------------------------------------------------------------- templates

class _Template:
    """An English template with `{name}` placeholders, compiled to an anchored regex."""

    def __init__(self, text: str):
        self.text = text
        self.names: List[str] = []
        parts = []
        literal_chars = 0
        pos = 0
        for match in _PLACEHOLDER_RE.finditer(text):
            literal = text[pos:match.start()]
            parts.append(re.escape(literal))
            literal_chars += len(literal)
            parts.append('(.+?)')
            self.names.append(match.group(1))
            pos = match.end()
        tail = text[pos:]
        parts.append(re.escape(tail))
        literal_chars += len(tail)
        self.specificity = literal_chars
        self._regex = re.compile(''.join(parts))

    def match(self, value: str) -> Optional[Dict[str, str]]:
        found = self._regex.fullmatch(value)
        if not found:
            return None
        return {name: found.group(i + 1) for i, name in enumerate(self.names)}


def _substitute(template: str, args: Dict[str, object]) -> str:
    """Fill `{name}` in a template; values are HTML-escaped, unknown names are kept."""
    def repl(match):
        name = match.group(1)
        return html.escape(str(args[name]), quote=False) if name in args else match.group(0)
    return _PLACEHOLDER_RE.sub(repl, template)


def _span(key: str, args: Dict[str, object], text_html: str) -> str:
    attr = ''
    if args:
        payload = json.dumps({k: str(v) for k, v in args.items()}, ensure_ascii=False, separators=(',', ':'))
        attr = f" data-i18n-args='{html.escape(payload, quote=True)}'"
    return f'<span data-i18n="{html.escape(key, quote=True)}"{attr}>{text_html}</span>'


# --------------------------------------------------------------------------- catalog

class ReportCatalog:
    """Platform strings plus an optional script file, and the keys one report actually used."""

    def __init__(self, script_strings: Optional[Dict[str, Dict[str, str]]] = None):
        self.platform = load_platform_strings()
        self.script = dict(script_strings or {})
        self.used_platform: set = set()
        self.used_script: set = set()
        self._script_templates = self._compile(self.script)
        self._msg_templates = self._compile(
            {k: v for k, v in self.platform.get(DEFAULT_LANGUAGE, {}).items() if k.startswith(MSG_PREFIX)}
        )

    @staticmethod
    def _compile(source: Dict) -> List[Tuple[str, _Template]]:
        compiled = []
        for key, value in source.items():
            template_text = key if isinstance(value, dict) else value
            template = _Template(template_text)
            if template.specificity > 0:  # a bare "{x}" would match everything
                compiled.append((key, template))
        return compiled

    def english(self, key: str) -> Optional[str]:
        return self.platform.get(DEFAULT_LANGUAGE, {}).get(key)

    def t(self, key: str, **args) -> str:
        template = self.english(key)
        if template is None:
            return html.escape(key, quote=False)
        self.used_platform.add(key)
        return _span(key, args, _substitute(template, args))

    def _best(self, templates, text: str):
        best = None
        for key, template in templates:
            captured = template.match(text)
            if captured is not None and (best is None or template.specificity > best[1].specificity):
                best = (key, template, captured)
        return best

    def tx(self, text, escape_markup: bool = False) -> str:
        text = '' if text is None else str(text)
        if not text:
            return text
        if '<' in text:
            # Already markup: leave it as it was, unless the caller always escaped it before.
            return html.escape(text, quote=False) if escape_markup else text
        best = self._best(self._script_templates, text)
        if best:
            key, template, captured = best
            self.used_script.add(key)
            return _span(SCRIPT_KEY_PREFIX + key, captured, html.escape(text, quote=False))
        best = self._best(self._msg_templates, text)
        if best:
            key, template, captured = best
            self.used_platform.add(key)
            return _span(key, captured, html.escape(text, quote=False))
        # A step run inside a testcase loop is tagged "[k/N] <message>": keep the tag, translate the rest.
        tagged = _LOOP_TAG_RE.match(text)
        if tagged:
            return html.escape(tagged.group(1), quote=False) + self.tx(tagged.group(2))
        return html.escape(text, quote=False)

    def script_tag(self) -> str:
        """`<script type="application/json" id="vpt-i18n">` with only the keys this report used."""
        languages = available_languages()
        strings: Dict[str, Dict[str, str]] = {code: {} for code in languages}
        for code in languages:
            table = self.platform.get(code, {})
            for key in sorted(self.used_platform):
                if key in table:
                    strings[code][key] = table[key]
        for template in sorted(self.used_script):
            strings.setdefault(DEFAULT_LANGUAGE, {})[SCRIPT_KEY_PREFIX + template] = template
            for code, text in self.script.get(template, {}).items():
                if code in languages and code != DEFAULT_LANGUAGE:
                    strings[code][SCRIPT_KEY_PREFIX + template] = text
        payload = {'default': DEFAULT_LANGUAGE, 'languages': languages, 'strings': strings}
        data = json.dumps(payload, ensure_ascii=False, separators=(',', ':')).replace('</', '<\\/')
        return f'<script type="application/json" id="vpt-i18n">{data}</script>'


# --------------------------------------------------------------------------- module API

def build_catalog(script_name: Optional[str] = None, script_i18n_path_override: Optional[str] = None,
                  script_strings: Optional[Dict[str, Dict[str, str]]] = None) -> ReportCatalog:
    """Platform catalog plus the script's file (override path, then script name lookup).

    `script_strings` (a ready dict) wins over files; used by tests and harnesses.
    """
    if script_strings is None:
        path = script_i18n_path_override or script_i18n_path(script_name)
        script_strings = load_script_strings(path)
    return ReportCatalog(script_strings)


@contextmanager
def use_report_catalog(catalog: Optional[ReportCatalog]) -> Iterator[Optional[ReportCatalog]]:
    token = _active.set(catalog)
    try:
        yield catalog
    finally:
        _active.reset(token)


def active_catalog() -> Optional[ReportCatalog]:
    return _active.get()


def t(key: str, **args) -> str:
    """Platform string by key: a translatable span (active catalog) or plain escaped English."""
    catalog = _active.get()
    if catalog is not None:
        return catalog.t(key, **args)
    template = load_platform_strings().get(DEFAULT_LANGUAGE, {}).get(key)
    if template is None:
        return html.escape(key, quote=False)
    return _substitute(template, args)


def t_attr(key: str, **args) -> str:
    """Plain, attribute-safe text for `key` (a tooltip): the page script re-translates it from
    the element's `data-i18n-title`, which `t()`'s span cannot do inside an attribute."""
    return html.escape(re.sub(r'<[^>]+>', '', t(key, **args)), quote=True)


def tx(text, escape_markup: bool = False) -> str:
    """Runtime/script text: a translatable span when a template matches, else the escaped text.

    Text that already contains markup ('<') is returned untouched, unless `escape_markup` is set
    (callers that always HTML-escaped their text before).
    """
    catalog = _active.get()
    if catalog is not None:
        return catalog.tx(text, escape_markup=escape_markup)
    text = '' if text is None else str(text)
    if not text:
        return text
    if '<' in text:
        return html.escape(text, quote=False) if escape_markup else text
    return html.escape(text, quote=False)


def tx_lines(text, escape_markup: bool = False) -> str:
    """tx() on each line of a multi-line text; newlines are kept."""
    text = '' if text is None else str(text)
    return '\n'.join(tx(line, escape_markup=escape_markup) for line in text.split('\n'))


def catalog_script_tag() -> str:
    """The embedded catalog block for the active catalog ('' when none is active)."""
    catalog = _active.get()
    return catalog.script_tag() if catalog is not None else ''
