#!/usr/bin/env python3
"""Render vitest's JSON reporter output as a self-contained HTML report.

Used by the `frontend-component-tests` CI job (regression.yml). Each test row expands to
show *what the test did*: the file it lives in, the source of its `it(...)` block (so a
reviewer can check the assertion without opening the repo), and vitest's failure messages.
Console output is not part of vitest's JSON reporter, so the raw runner output is appended
in full at the bottom of the page instead of per test.

    python3 tests/frontend/vitest_html_report.py \
        --results vitest-results.json --output vitest-report/index.html \
        --status success|failure [--raw-output /tmp/vitest-output.txt] [--repo-root .]
"""

from __future__ import annotations

import argparse
import datetime as _dt
import html
import json
import pathlib
import re
import sys


def extract_test_source(test_file: pathlib.Path, title: str) -> str:
    """Return the `it('<title>', ...)` / `test('<title>', ...)` block from a test file.

    Finds the line that opens the block with this exact title, then walks forward until
    the brace/paren depth of that opener returns to zero. Good enough for the way these
    suites are written (one `it` per block, template/quoted titles); returns '' when the
    title is not found so the report degrades to "no source" rather than failing.
    """
    try:
        lines = test_file.read_text(encoding='utf-8').splitlines()
    except OSError:
        return ''
    opener = re.compile(r"^\s*(?:it|test)(?:\.(?:only|skip|each|concurrent))?\(\s*(['\"`])"
                        + re.escape(title) + r"\1")
    start = next((i for i, line in enumerate(lines) if opener.match(line)), None)
    if start is None:
        return ''
    depth = 0
    seen_open = False
    for end in range(start, len(lines)):
        for ch in lines[end]:
            if ch in '({[':
                depth += 1
                seen_open = True
            elif ch in ')}]':
                depth -= 1
        if seen_open and depth <= 0:
            return '\n'.join(lines[start:end + 1])
    return '\n'.join(lines[start:])


def build_rows(data: dict, repo_root: pathlib.Path) -> tuple[list[str], int, int, int, int]:
    rows: list[str] = []
    total = passed = failed = skipped = 0
    idx = 0
    for suite in data.get('testResults', []):
        suite_path = pathlib.Path(suite.get('name', '?'))
        try:
            rel = suite_path.relative_to(repo_root)
        except ValueError:
            rel = suite_path
        suite_name = html.escape(suite_path.name)
        suite_msg = suite.get('message') or ''
        for t in suite.get('assertionResults', []):
            idx += 1
            total += 1
            status = t.get('status', 'unknown')
            if status == 'passed':
                passed += 1
            elif status in ('skipped', 'pending', 'todo', 'disabled'):
                skipped += 1
            else:
                failed += 1
            ok = status == 'passed'
            skip = status in ('skipped', 'pending', 'todo', 'disabled')
            icon = '–' if skip else ('✔' if ok else '✘')
            icon_color = '#9e9e9e' if skip else ('#2e7d32' if ok else '#c62828')
            row_color = '#f5f5f5' if skip else ('#e8f5e9' if ok else '#ffebee')
            detail_color = '#eeeeee' if skip else ('#f1f8e9' if ok else '#fff3e0')
            title = t.get('title', '')
            tname = html.escape(' > '.join(t.get('ancestorTitles', []) + [title]))
            duration = t.get('duration', 0) or 0
            failures = t.get('failureMessages') or []
            err_short = html.escape((failures[0].splitlines()[0] if failures else '')[:160])
            source = extract_test_source(suite_path, title)
            source_html = html.escape(source) if source else '<i>source block not found — title may be dynamic</i>'
            failures_html = ''
            if failures:
                failures_html = ('<div class="lbl">Failure</div><pre class="err">'
                                 + html.escape('\n\n'.join(failures)) + '</pre>')
            detail_id = f'd{idx}'
            rows.append(f'''<tr style="background:{row_color};cursor:pointer" onclick="tg('{detail_id}')">
  <td style="color:{icon_color};text-align:center">{icon}</td>
  <td style="font-size:.78rem;color:#888">{suite_name}</td>
  <td style="font-size:.85rem">{tname} <span style="color:#aaa;font-size:.7em">▼</span></td>
  <td style="text-align:right;font-size:.8rem">{duration:.0f}ms</td>
  <td style="color:#c62828;font-size:.78rem">{err_short}</td>
</tr>
<tr id="{detail_id}" style="display:none;background:{detail_color}"><td></td><td colspan="4" style="padding:10px 12px">
  <div class="lbl">File</div><code style="font-size:.8rem">{html.escape(str(rel))}</code>
  <div class="lbl" style="margin-top:8px">Test source</div><pre class="src">{source_html}</pre>
  {failures_html}
</td></tr>''')
        if not suite.get('assertionResults') and suite_msg:
            # A suite that failed to load has no tests but carries the load error.
            idx += 1
            failed += 1
            total += 1
            rows.append(f'''<tr style="background:#ffebee"><td style="color:#c62828;text-align:center">✘</td>
  <td style="font-size:.78rem;color:#888">{suite_name}</td><td style="font-size:.85rem">suite failed to run</td><td></td>
  <td style="color:#c62828;font-size:.78rem"><pre class="err" style="margin:0">{html.escape(suite_msg[:2000])}</pre></td></tr>''')
    return rows, total, passed, failed, skipped


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--results', default='vitest-results.json')
    ap.add_argument('--output', default='vitest-report/index.html')
    ap.add_argument('--status', default='unknown', help="job outcome: success|failure (from steps.<id>.outcome)")
    ap.add_argument('--raw-output', default='/tmp/vitest-output.txt', help='runner stdout to append (console.log etc.)')
    ap.add_argument('--repo-root', default='.', help='paths under it are shown relative')
    ap.add_argument('--title', default='Frontend Component Tests')
    args = ap.parse_args()

    repo_root = pathlib.Path(args.repo_root).resolve()
    results_file = pathlib.Path(args.results)
    raw_file = pathlib.Path(args.raw_output)
    raw = raw_file.read_text(encoding='utf-8', errors='replace') if raw_file.exists() else ''

    if results_file.exists():
        data = json.loads(results_file.read_text(encoding='utf-8'))
        rows, total, passed, failed, skipped = build_rows(data, repo_root)
    else:
        data, rows, total, passed, failed, skipped = {}, [], 0, 0, 0, 0
        rows = [f'<tr><td colspan="5"><b>No {results_file} produced</b> — runner output below.</td></tr>']

    overall_ok = args.status == 'success'
    color = '#2e7d32' if overall_ok else '#c62828'
    label = 'PASSED' if overall_ok else 'FAILED'
    ts = _dt.datetime.now(_dt.timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
    suites = len(data.get('testResults', []))

    page = f'''<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><title>{html.escape(args.title)}</title>
<style>
body{{font-family:system-ui,sans-serif;margin:0;padding:24px;background:#fafafa;color:#212121}}
h1{{margin:0 0 4px;font-size:1.5rem}}.meta{{color:#666;font-size:.85rem;margin-bottom:16px}}
.summary{{display:flex;gap:12px;margin-bottom:20px;flex-wrap:wrap}}
.kpi{{background:#fff;border:1px solid #e0e0e0;border-radius:8px;padding:10px 18px}}
.kpi-label{{font-size:.72rem;color:#888;text-transform:uppercase}}.kpi-value{{font-size:1.6rem;font-weight:700;line-height:1.1}}
table{{width:100%;border-collapse:collapse;background:#fff;border-radius:8px;overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,.1)}}
th{{background:#37474f;color:#fff;padding:9px 12px;text-align:left;font-size:.78rem;text-transform:uppercase}}
td{{padding:7px 12px;border-bottom:1px solid #f0f0f0;vertical-align:top}}tr:last-child td{{border-bottom:none}}
.lbl{{font-size:.72rem;text-transform:uppercase;color:#888;margin-bottom:4px}}
pre.src,pre.err,pre.raw{{margin:0;background:#263238;color:#eceff1;padding:10px;border-radius:6px;font-size:.78rem;overflow-x:auto;white-space:pre-wrap;max-height:420px}}
pre.err{{background:#3e2723}}
details{{margin-top:24px}}summary{{cursor:pointer;font-weight:600}}
</style>
<script>function tg(id){{var e=document.getElementById(id);e.style.display=e.style.display==='none'?'table-row':'none';}}</script>
</head><body>
<h1>{html.escape(args.title)}</h1><div class="meta">{ts} · {suites} suite files · click a row for its source</div>
<div class="summary">
  <div class="kpi"><div class="kpi-label">Overall</div><div class="kpi-value" style="color:{color}">{label}</div></div>
  <div class="kpi"><div class="kpi-label">Passed</div><div class="kpi-value" style="color:#2e7d32">{passed}</div></div>
  <div class="kpi"><div class="kpi-label">Failed</div><div class="kpi-value" style="color:#c62828">{failed}</div></div>
  <div class="kpi"><div class="kpi-label">Skipped</div><div class="kpi-value" style="color:#9e9e9e">{skipped}</div></div>
  <div class="kpi"><div class="kpi-label">Total</div><div class="kpi-value">{total}</div></div>
</div>
<table><thead><tr><th></th><th>Suite</th><th>Test</th><th>Time</th><th>Error</th></tr></thead>
<tbody>{"".join(rows)}</tbody></table>
<details><summary>Runner output ({len(raw.splitlines())} lines — console.log / warnings from every test)</summary>
<pre class="raw" style="max-height:none;margin-top:8px">{html.escape(raw[-200000:]) if raw else 'not captured'}</pre></details>
</body></html>'''

    out = pathlib.Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding='utf-8')
    print(f'{out} written ({total} tests, {passed} passed, {failed} failed, {skipped} skipped)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
