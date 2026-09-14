#!/usr/bin/env python3
"""Emit SQL that loads the CI/CD database from the report directories on the reports server.

Run ON the reports server (192.168.x.103) and pipe into psql as role `cicd` (its search_path is
the `cicd` schema of the shared postgres database):
  python3 backfill_from_ci_reports.py /opt/ci-reports | psql "$CICD_DATABASE_URL" -v ON_ERROR_STOP=1

Idempotent (ON CONFLICT … DO UPDATE). Job layer follows the same mapping the workflows use:
white = lint / unit / component / contract, grey = anything driven against a deployed target.
"""
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

RUN_DIR_RE = re.compile(r'^(?:(?P<repo>[a-zA-Z0-9]+)-)?(?P<num>\d+)$')
WHITE_JOBS = {'lint', 'frontend-component-tests', 'backend-tests', 'contract', 'android-unit', 'assemble'}
REPORT_BASE = 'https://virtualpytest.angelstreet.io/server/cicd/report'


def q(v):
    return 'NULL' if v is None else "'" + str(v).replace("'", "''") + "'"


def main(root: Path):
    for d in sorted(p for p in root.iterdir() if p.is_dir() and RUN_DIR_RE.match(p.name)):
        m = RUN_DIR_RE.match(d.name)
        meta = {}
        if (d / 'meta.json').exists():
            try:
                meta = json.loads((d / 'meta.json').read_text())
            except Exception:
                meta = {}
        project = meta.get('repo') or m.group('repo') or 'virtualpytest'
        try:
            started = datetime.strptime(meta['date'], '%Y-%m-%d %H:%M UTC').replace(tzinfo=timezone.utc)
        except Exception:
            started = datetime.fromtimestamp(d.stat().st_mtime, tz=timezone.utc)
        print(
            "INSERT INTO ci_runs (project, run, run_number, branch, sha, runner, started_at, report_url) VALUES ("
            f"{q(project)}, {q(d.name)}, {int(m.group('num'))}, {q(meta.get('branch'))}, {q(meta.get('sha'))}, "
            f"{q(meta.get('runner'))}, {q(started.isoformat())}, {q(REPORT_BASE + '/' + d.name + '/')}) "
            "ON CONFLICT (project, run) DO UPDATE SET branch = EXCLUDED.branch, sha = EXCLUDED.sha, "
            "runner = COALESCE(EXCLUDED.runner, ci_runs.runner), started_at = EXCLUDED.started_at;"
        )
        jobs_dir = d / 'jobs'
        if not jobs_dir.exists():
            continue
        for jf in sorted(jobs_dir.glob('*.json')):
            try:
                job = json.loads(jf.read_text())
            except Exception:
                continue
            name = jf.stem
            layer = 'white' if name in WHITE_JOBS else 'grey'
            report = job.get('report')
            url = f"{REPORT_BASE}/{d.name}/{report}/" if report else None
            finished = datetime.fromtimestamp(jf.stat().st_mtime, tz=timezone.utc)
            print(
                "INSERT INTO ci_jobs (project, run, job, category, layer, status, report_url, finished_at) VALUES ("
                f"{q(project)}, {q(d.name)}, {q(name)}, {q(job.get('category'))}, {q(layer)}, "
                f"{q(job.get('status') or 'unknown')}, {q(url)}, {q(finished.isoformat())}) "
                "ON CONFLICT (project, run, job) DO UPDATE SET status = EXCLUDED.status, "
                "report_url = EXCLUDED.report_url, finished_at = EXCLUDED.finished_at;"
            )


if __name__ == '__main__':
    main(Path(sys.argv[1] if len(sys.argv) > 1 else '/opt/ci-reports'))
