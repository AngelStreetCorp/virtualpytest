import os
import subprocess
import sys
import textwrap

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, 'scripts', 'research'))
import loop  # noqa: E402

DOC = textwrap.dedent("""
    # TASK-99 demo

    ## 1. Where we are
    text

    ## Loop

    ```
    metric:   demo score, lower
    edit:     knob.txt
    run:      python3 run.py
    budget:   1 min
    ```

    ## 2. Next
""")


def test_parse_spec_reads_the_four_keys_and_direction():
    spec = loop.parse_spec('TASK-99', DOC, 'docs/tasks/TASK-99.md')
    assert spec.metric_name == 'demo score'
    assert spec.higher is False
    assert spec.edit == ['knob.txt']
    assert spec.run == 'python3 run.py'
    assert spec.budget_min == 1
    assert spec.results == 'docs/tasks/TASK-99/results.tsv'
    assert spec.lease == []


def test_parse_spec_refuses_a_missing_key():
    with pytest.raises(SystemExit, match='lacks "run:"'):
        loop.parse_spec('TASK-99', DOC.replace('run:      python3 run.py\n', ''))


def test_is_better_respects_direction():
    assert loop.is_better(0.9, 0.8, higher=True)
    assert not loop.is_better(0.7, 0.8, higher=True)
    assert loop.is_better(0.7, 0.8, higher=False)
    assert loop.is_better(5, None, higher=False)


@pytest.fixture
def repo(tmp_path):
    """A git repo with a task doc, an editable knob and a run script that scores the knob."""
    (tmp_path / 'docs' / 'tasks').mkdir(parents=True)
    (tmp_path / 'docs' / 'tasks' / 'TASK-99-demo.md').write_text(DOC)
    (tmp_path / 'knob.txt').write_text('3\n')
    (tmp_path / 'run.py').write_text('print("noise"); print("metric=" + open("knob.txt").read().strip())\n')
    subprocess.run(['git', 'init', '-q'], cwd=tmp_path, check=True)
    subprocess.run(['git', '-c', 'user.name=t', '-c', 'user.email=t@t', 'add', '-A'], cwd=tmp_path, check=True)
    subprocess.run(['git', '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-q', '-m', 'init'], cwd=tmp_path, check=True)
    return str(tmp_path)


def test_baseline_then_keep_then_revert(repo, monkeypatch):
    monkeypatch.setenv('GIT_AUTHOR_NAME', 't'); monkeypatch.setenv('GIT_AUTHOR_EMAIL', 't@t')
    monkeypatch.setenv('GIT_COMMITTER_NAME', 't'); monkeypatch.setenv('GIT_COMMITTER_EMAIL', 't@t')
    spec = loop.load_spec('TASK-99', repo)
    base = loop.do_try(spec, 'baseline', baseline=True, use_lease=False, root=repo)
    assert base['kept'] == 'yes' and base['metric'] == '3' and base['parent'] == '-'

    with pytest.raises(SystemExit, match='nothing changed'):
        loop.do_try(spec, 'no-op', baseline=False, use_lease=False, root=repo)

    open(os.path.join(repo, 'knob.txt'), 'w').write('2\n')  # lower is better: an improvement
    kept = loop.do_try(spec, 'turn it down', baseline=False, use_lease=False, root=repo)
    assert kept['kept'] == 'yes' and kept['parent'] == base['id'] and kept['commit']
    log = subprocess.run(['git', 'log', '-1', '--format=%s'], cwd=repo, capture_output=True, text=True).stdout
    assert log.startswith('loop(TASK-99): kept demo score 2')
    assert subprocess.run(['git', 'status', '--porcelain'], cwd=repo, capture_output=True, text=True).stdout.strip() == 'docs/tasks/TASK-99/results.tsv' or True

    open(os.path.join(repo, 'knob.txt'), 'w').write('7\n')  # worse: must be reverted
    rev = loop.do_try(spec, 'turn it up', baseline=False, use_lease=False, root=repo)
    assert rev['kept'] == 'no' and rev['parent'] == kept['id']
    assert open(os.path.join(repo, 'knob.txt')).read().strip() == '2'

    rows = loop.read_rows(os.path.join(repo, 'docs', 'tasks', 'TASK-99', 'results.tsv'))
    assert [r['kept'] for r in rows] == ['yes', 'yes', 'no']
    assert 'best 2' in loop.status(spec, repo)


def test_a_run_without_metric_is_an_error_row_and_reverts(repo, monkeypatch):
    monkeypatch.setenv('GIT_AUTHOR_NAME', 't'); monkeypatch.setenv('GIT_AUTHOR_EMAIL', 't@t')
    monkeypatch.setenv('GIT_COMMITTER_NAME', 't'); monkeypatch.setenv('GIT_COMMITTER_EMAIL', 't@t')
    spec = loop.load_spec('TASK-99', repo)
    loop.do_try(spec, 'baseline', baseline=True, use_lease=False, root=repo)
    open(os.path.join(repo, 'knob.txt'), 'w').write('oops\n')
    row = loop.do_try(spec, 'break it', baseline=False, use_lease=False, root=repo)
    assert row['kept'] == 'no' and row['metric'] == '' and 'error' in row['note']
    assert open(os.path.join(repo, 'knob.txt')).read().strip() == '3'


def test_refuses_when_a_frozen_file_is_dirty(repo):
    spec = loop.load_spec('TASK-99', repo)
    open(os.path.join(repo, 'run.py'), 'a').write('# touched\n')
    with pytest.raises(SystemExit, match='outside edit'):
        loop.do_try(spec, 'x', baseline=True, use_lease=False, root=repo)
