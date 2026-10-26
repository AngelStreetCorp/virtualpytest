"""
In-memory tests for TASK-65 G7 — Report integration.

What G7 ships
-------------
* `report_template_html.py` injects a `{project_badge}` slot next to
  `{script_name}` in the header.
* `report_template_css.py` adds a `.project-badge` rule (gold chip).
* `report_generation_utils.py` adds `_build_project_badge_html(type, id)`
  which lazily calls `projects_db.resolve_project_for_executable` and
  renders the badge (or an empty string when the executable has no project).
* `script_results_db._attach_projects` left-joins `executable_tags` →
  `projects_tags` → `projects` for every row and surfaces `projects` /
  `project_ids` so the Reports list shows a chip per project.
* `frontend/src/pages/TestReports.tsx` renders those chips and exposes an
  "All + include untagged" project filter.
* `shared/src/lib/i18n/report/{en,fr,de}.json` add `header.project_label`.

The tests below verify each layer against the in-memory mock without
spinning up Supabase.
"""
import os
import sys
from typing import Any, Dict, List

import pytest


HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))  # for `_supabase_mock`
sys.path.insert(0, '/home/jndoye/vpt-task65')

from _supabase_mock import (  # type: ignore  # noqa: E402
    SupabaseMock,
    apply_migration_sql,
    make_projects_seed,
    get_meta,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_supabase() -> SupabaseMock:
    """A mock with the projects migrations applied, on top of the seed."""
    mock = SupabaseMock(initial=make_projects_seed())
    for fn in [
        '20261006a_projects.sql',
        '20261006b_team_members_last_seen.sql',
        '20261006c_report_snapshots_project_ids.sql',
    ]:
        with open(os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            'setup', 'db', 'migrations', fn,
        )) as f:
            apply_migration_sql(mock, f.read())
    return mock


@pytest.fixture
def patched_pdb(mock_supabase, monkeypatch):
    """Patch `projects_db._supabase` to the mock so resolve_* sees it."""
    import importlib
    import shared.src.lib.database.projects_db as pdb
    importlib.reload(pdb)
    monkeypatch.setattr(pdb, '_supabase', lambda: mock_supabase)
    return pdb, mock_supabase


class _FakeResultQuery:
    """A tiny postgrest-like builder that handles the embed shape G7 reads.

    Real PostgREST answers ``select('tag_id, project_id, projects!inner(...)')``
    by returning one row per `projects_tags` hit with the matched project
    embedded under the `projects` key. The mock below does exactly that for
    the two specific queries `_attach_projects` issues, and falls back to a
    plain column filter for every other query (so `script_results`,
    `executable_tags`, etc. work without a full PostgREST emulator).
    """

    def __init__(self, data: Dict[str, List[Dict[str, Any]]], table: str):
        self.data = data
        self.table = table
        self.op = 'select'
        self.projection = '*'
        self.payload: Any = None
        self.filters: List[Any] = []
        self.orders: List = []
        self.limit_n: Any = None

    # chainable verbs ----------------------------------------------------
    def select(self, columns='*', count=None):
        self.projection = columns
        return self

    def eq(self, col, val):
        self.filters.append(('eq', col, val))
        return self

    def in_(self, col, vals):
        self.filters.append(('in', col, list(vals)))
        return self

    def order(self, col, desc=False):
        self.orders.append((col, desc))
        return self

    def limit(self, n):
        self.limit_n = n
        return self

    def range(self, start, end):
        # `chunked_in` pages with `.range(start, end)`; honour it via a slice
        # applied at execute() time.
        self._range = (start, end)
        return self

    def insert(self, payload):
        self.op = 'insert'; self.payload = payload
        return self

    def delete(self):
        self.op = 'delete'
        return self

    # terminal -----------------------------------------------------------
    def execute(self):
        if self.op == 'select':
            rows = list(self.data.get(self.table, []))
            # embed projects / projects!inner — both shapes the G7 helpers
            # issue (resolve_project_for_executable uses the non-inner form,
            # _attach_projects uses `!inner` to filter by team).
            if ('projects!inner(' in self.projection or 'projects(id' in self.projection) \
                    and self.table == 'projects_tags':
                projects = {p['id']: p for p in self.data.get('projects', [])}
                if 'projects!inner(' in self.projection:
                    rows = [{**r, 'projects': projects.get(r.get('project_id'))}
                            for r in rows
                            if projects.get(r.get('project_id')) is not None]
                else:
                    rows = [{**r, 'projects': projects.get(r.get('project_id'))}
                            for r in rows]
            # apply filters
            for op, col, val in self.filters:
                if op == 'eq':
                    if '.' in col:
                        embed, field = col.split('.', 1)
                        rows = [r for r in rows
                                if isinstance(r.get(embed), dict)
                                and str(r[embed].get(field)) == str(val)]
                    else:
                        rows = [r for r in rows if str(r.get(col)) == str(val)]
                elif op == 'in':
                    if '.' in col:
                        embed, field = col.split('.', 1)
                        wanted = {str(v) for v in val}
                        rows = [r for r in rows
                                if isinstance(r.get(embed), dict)
                                and str(r[embed].get(field)) in wanted]
                    else:
                        wanted = {str(v) for v in val}
                        rows = [r for r in rows if str(r.get(col)) in wanted]
            # apply order
            for col, desc in reversed(self.orders):
                rows.sort(key=lambda r, c=col: r.get(c) or '', reverse=desc)
            # NB: removed the duplicated embed block that used to live here.
            if self.limit_n is not None:
                rows = rows[:self.limit_n]
            if hasattr(self, '_range') and self._range is not None:
                start, end = self._range
                # PostgREST returns up to MAX_ROWS_PER_REQUEST rows; the
                # chunked_in loop breaks on a short page. Mirror that here.
                rows = rows[start:end + 1]
            return _Result(data=rows)
        if self.op == 'insert':
            row = dict(self.payload)
            self.data.setdefault(self.table, []).append(row)
            return _Result(data=[row])
        if self.op == 'delete':
            keep = []
            out = []
            for r in self.data.get(self.table, []):
                if all(r.get(c) == v for (k, c, v) in self.filters if k == 'eq'):
                    out.append(r)
                else:
                    keep.append(r)
            self.data[self.table] = keep
            return _Result(data=out)
        raise RuntimeError(f'unknown op {self.op}')


class _Result:
    def __init__(self, data):
        self.data = data


class _FakeSupabase:
    def __init__(self, tables: Dict[str, List[Dict[str, Any]]]):
        self.tables = tables

    def table(self, name: str) -> _FakeResultQuery:
        return _FakeResultQuery(self.tables, name)


# ---------------------------------------------------------------------------
# G7 — report integration
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestG7ProjectBadgeHtml:
    """The HTML badge macro.

    `_build_project_badge_html(type, id)` resolves the project via the G1
    helper (`projects_db.resolve_project_for_executable`), then renders a
    `<span class="project-badge">`. The text, the label i18n, and the span
    class are the three contracts the CSS, the frontend, and the
    translation check rely on.
    """

    def test_returns_empty_when_no_executable(self):
        # `None, None` must not crash (snapshots and tests pass `None`).
        from shared.src.lib.utils.report_generation_utils import _build_project_badge_html
        assert _build_project_badge_html(None, None) == ''
        assert _build_project_badge_html('script', None) == ''
        assert _build_project_badge_html(None, 'whatever') == ''

    def test_renders_badge_with_project_name(self, patched_pdb, monkeypatch):
        from shared.src.lib.utils import report_generation_utils as rgu
        _pdb, mock = patched_pdb
        # Swap in a fake supabase that handles the `projects(id, …)` embed
        # shape `_resolve_project_for_executable` reads.
        fake = _FakeSupabase(dict(mock._tables))
        monkeypatch.setattr(rgu, '_resolve_project_for_executable',
                            lambda t, i: pdb_fake_resolve(fake, t, i))
        html = rgu._build_project_badge_html('script', 's_web_1')
        assert 'project-badge' in html
        assert 'Web app' in html
        # Label is a localised key, not the project name (TASK-65 I18N rule).
        assert 'Project' in html  # English "header.project_label"
        # `<span>` is the carrier; `span class="project-badge-label"` carries the label.
        assert 'class="project-badge"' in html  # allow inline `style=""` after class
        assert 'class="project-badge-label"' in html

    def test_returns_empty_when_executable_has_no_project(self, patched_pdb, monkeypatch):
        from shared.src.lib.utils import report_generation_utils as rgu
        _pdb, mock = patched_pdb
        # 'unknown-script' is not in executable_tags (the seed).
        fake = _FakeSupabase(dict(mock._tables))
        monkeypatch.setattr(rgu, '_resolve_project_for_executable',
                            lambda t, i: pdb_fake_resolve(fake, t, i))
        html = rgu._build_project_badge_html('script', 'unknown-script')
        assert html == ''

    def test_uses_project_color_when_present(self, patched_pdb, monkeypatch):
        from shared.src.lib.utils import report_generation_utils as rgu
        _pdb, mock = patched_pdb
        # p1's color is '#d4a574' (set in the seed).
        fake = _FakeSupabase(dict(mock._tables))
        monkeypatch.setattr(rgu, '_resolve_project_for_executable',
                            lambda t, i: pdb_fake_resolve(fake, t, i))
        html = rgu._build_project_badge_html('script', 's_web_1')
        assert '#d4a574' in html


def pdb_fake_resolve(fake, executable_type, executable_id):
    """Faithful copy of `projects_db.resolve_project_for_executable` over the fake.

    The real helper is imported lazily inside `_resolve_project_for_executable`;
    the G1 unit tests cover its Supabase-shape contract. Here we want to test
    the HTML/CSS wiring, so we inline the same query against `_FakeSupabase`.
    """
    et = fake.table('executable_tags').select('tag_id') \
        .eq('executable_type', executable_type) \
        .eq('executable_id', str(executable_id)).execute().data or []
    if not et:
        return None
    tag_ids = [r['tag_id'] for r in et]
    pt = fake.table('projects_tags').select(
        'project_id, projects(id, team_id, name, color)'
    ).in_('tag_id', tag_ids).limit(1).execute().data or []
    for r in pt:
        proj = r.get('projects')
        if proj:
            return {'id': proj['id'], 'name': proj['name'], 'color': proj.get('color')}
    return None


@pytest.mark.unit
class TestG7CssRule:
    """The CSS rule `.project-badge` is the contract the gold chip follows."""

    def test_css_contains_the_rule(self):
        from shared.src.lib.utils.report_template_css import get_report_css
        css = get_report_css()
        # The rule must exist with its key selectors.
        assert '.project-badge {' in css
        assert 'border-radius' in css  # pill / chip
        # The label slot inside the chip is localised via `t('header.project_label')`,
        # but the CSS just needs to style it.
        assert '.project-badge-label' in css


@pytest.mark.unit
class TestG7HtmlTemplateSlot:
    """`{project_badge}` is substituted in the header next to `{script_name}`."""

    def test_template_has_project_badge_placeholder(self):
        from shared.src.lib.utils.report_template_html import create_themed_html_template
        tmpl = create_themed_html_template()
        assert '{project_badge}' in tmpl
        # Lives in the header (next to the script name h1).
        assert '<h1>{script_name}{project_badge}</h1>' in tmpl


@pytest.mark.unit
class TestG7I18nKeys:
    """The label key exists in all three locales (it is *not* the project name)."""

    def test_project_label_in_each_locale(self):
        import json
        for code, expected in [
            ('en', 'Project'),
            ('fr', 'Projet'),
            ('de', 'Projekt'),
        ]:
            with open(os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                'shared', 'src', 'lib', 'i18n', 'report', f'{code}.json',
            )) as f:
                data = json.load(f)
            assert data.get('header.project_label') == expected, (
                f'{code}.json missing header.project_label="{expected}"')


@pytest.mark.unit
class TestG7ReportListProjects:
    """`script_results_db._attach_projects` surfaces `project_ids` per row.

    This is the read-side of G7: the Reports list endpoint joins
    `executable_tags` → `projects_tags` → `projects` and attaches the
    project list (and the bare id list, for fast equality) onto every row.
    The test below mirrors the G5 mock setup so the new query gets verified
    end-to-end without a real database.
    """

    def _attach(self, script_results_db, fake_supabase, team_id, rows):
        """Run the real `_attach_projects` against our fake client."""
        import importlib
        importlib.reload(script_results_db)
        script_results_db._attach_projects(fake_supabase, team_id, rows)

    def test_tagged_script_surfaces_project_id(self, patched_pdb):
        import importlib
        from shared.src.lib.database import script_results_db
        _pdb, mock = patched_pdb
        meta = get_meta(mock._tables)
        # The seed already tagged 's_web_1' and 's_web_2' with tag1 (project p1).
        fake = _FakeSupabase(dict(mock._tables))
        rows = [
            {'id': 'r1', 'script_name': 's_web_1', 'team_id': meta['team_id']},
            {'id': 'r2', 'script_name': 'unknown', 'team_id': meta['team_id']},
        ]
        self._attach(script_results_db, fake, meta['team_id'], rows)
        assert rows[0]['project_ids'] == [meta['p1']]
        assert rows[0]['projects'][0]['name'] == 'Web app'
        assert rows[1]['project_ids'] == []
        assert rows[1]['projects'] == []

    def test_script_with_two_tags_surfaces_two_projects(self, patched_pdb):
        from shared.src.lib.database import script_results_db
        _pdb, mock = patched_pdb
        meta = get_meta(mock._tables)
        # Add a second tag for 's_web_1' → project p2.
        mock._tables.setdefault('executable_tags', []).append({
            'executable_type': 'script',
            'executable_id': 's_web_1',
            'tag_id': meta['tag2'],
        })
        fake = _FakeSupabase(dict(mock._tables))
        rows = [{'id': 'r1', 'script_name': 's_web_1', 'team_id': meta['team_id']}]
        self._attach(script_results_db, fake, meta['team_id'], rows)
        ids = set(rows[0]['project_ids'])
        assert ids == {meta['p1'], meta['p2']}

    def test_empty_input_does_not_crash(self, patched_pdb):
        from shared.src.lib.database import script_results_db
        _pdb, mock = patched_pdb
        meta = get_meta(mock._tables)
        fake = _FakeSupabase(dict(mock._tables))
        rows: List[Dict[str, Any]] = []
        self._attach(script_results_db, fake, meta['team_id'], rows)
        assert rows == []


@pytest.mark.unit
class TestG7ReportsFrontendType:
    """The frontend `ScriptResult` interface accepts `projects` / `project_ids`."""

    def test_script_result_interface_has_projects(self):
        # The interface is plain TS so this is a regex / structural check
        # over the source file. Drift in either field name fails G7.
        import re
        path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            'frontend', 'src', 'hooks', 'pages', 'useScriptResults.ts',
        )
        with open(path) as f:
            src = f.read()
        assert re.search(r'projects\??\s*:\s*Array<\s*\{\s*id:', src), \
            'ScriptResult.projects must be present in the TS interface'
        assert re.search(r'project_ids\??\s*:\s*string\[\]', src), \
            'ScriptResult.project_ids must be present in the TS interface'


@pytest.mark.unit
class TestG7ReportsFrontendWireUp:
    """TestReports.tsx renders the chip and wires the project filter."""

    def test_testreports_renders_project_chip(self):
        path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            'frontend', 'src', 'pages', 'TestReports.tsx',
        )
        with open(path) as f:
            src = f.read()
        assert 'data-testid="project-chip"' in src, \
            'TestReports must render a Chip with data-testid="project-chip" per project'
        assert '(result.projects ?? []).map' in src, \
            'TestReports must iterate result.projects to render one chip per project'

    def test_testreports_has_project_filter_state(self):
        path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            'frontend', 'src', 'pages', 'TestReports.tsx',
        )
        with open(path) as f:
            src = f.read()
        # G7 ships the bare-bones filter; G9 will replace it with the full picker.
        assert 'setFilterProject' in src
        assert 'setIncludeUntagged' in src
        assert 'data-testid="include-untagged"' in src
        assert 'Project' in src  # the Autocomplete label