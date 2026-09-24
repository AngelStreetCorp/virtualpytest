"""Team-scoped TestRail mappings and campaign result publishing."""

from __future__ import annotations

import json
import os
import re
import threading
from datetime import datetime, timezone
from pathlib import Path

from backend_server.src.integrations import testrail_client

_CONFIG_PATH = Path(__file__).parents[2] / 'config' / 'integrations' / 'testrail.json'
_LOCK = threading.RLock()


def normalize_vpt_key(value: str) -> str:
    return re.sub(r'\s+', ' ', str(value or '').strip()).casefold()


def load_config(team_id: str) -> dict:
    if not team_id:
        return {}
    with _LOCK:
        try:
            stored = json.loads(_CONFIG_PATH.read_text())
            teams = stored.get('teams', {}) if isinstance(stored, dict) else {}
            config = teams.get(team_id, {}) if isinstance(teams, dict) else {}
            return dict(config) if isinstance(config, dict) else {}
        except (OSError, ValueError):
            return {}


def save_config(team_id: str, config: dict) -> None:
    if not team_id:
        raise ValueError('team_id is required')
    with _LOCK:
        try:
            stored = json.loads(_CONFIG_PATH.read_text())
        except FileNotFoundError:
            stored = {'teams': {}}
        except ValueError as exc:
            raise ValueError('TestRail configuration is unreadable.') from exc
        teams = stored.get('teams', {}) if isinstance(stored, dict) else {}
        if not isinstance(teams, dict):
            teams = {}
        teams[team_id] = config
        _CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        temp_path = _CONFIG_PATH.with_suffix('.tmp')
        temp_path.write_text(json.dumps({'teams': teams}))
        os.chmod(temp_path, 0o600)
        os.replace(temp_path, _CONFIG_PATH)


def list_cases(config: dict, search: str = '') -> list[dict]:
    suites = testrail_client.get_suites(config)
    cases = []
    for suite in suites:
        offset = 0
        while True:
            page = testrail_client.get_cases(config, suite_id=suite['id'], limit=250, offset=offset, filter_text=search)
            cases.extend({**case, 'suite_id': case.get('suite_id') or suite['id'], 'suite_name': suite['name']} for case in page)
            if len(page) < 250 or offset >= 2000:
                break
            offset += len(page)
    return cases


def save_mapping(team_id: str, vpt_key: str, case_id: int) -> dict:
    config = load_config(team_id)
    if not config.get('api_key'):
        raise ValueError('Connect TestRail before linking cases.')
    case = testrail_client.get_case(config, int(case_id))
    suite_id = case.get('suite_id')
    if not suite_id:
        raise ValueError('TestRail case has no suite and cannot be used in a run.')
    suite = next((s for s in testrail_client.get_suites(config) if int(s['id']) == int(suite_id)), None)
    if suite is None:
        raise ValueError('Choose a TestRail case from the connected project.')
    key = normalize_vpt_key(vpt_key)
    if not key:
        raise ValueError('VirtualPyTest case name is required.')
    mappings = config.setdefault('case_mappings', {})
    conflicting = next((entry for existing_key, entry in mappings.items()
                        if existing_key != key and int(entry.get('case_id', -1)) == int(case_id)), None)
    if conflicting:
        raise ValueError(f"TestRail case C{case_id} is already linked to '{conflicting.get('vpt_key', 'another VPT case')}'.")
    mapping = {'case_id': int(case_id), 'title': str(case.get('title') or ''), 'suite_id': int(suite_id),
               'suite_name': suite.get('name', ''), 'vpt_key': str(vpt_key)}
    mappings[key] = mapping
    save_config(team_id, config)
    return mapping


def save_mappings(team_id: str, requested: list[dict]) -> list[dict]:
    """Validate a reviewed set of links and persist them in one config write."""
    config = load_config(team_id)
    if not config.get('api_key'):
        raise ValueError('Connect TestRail before linking cases.')
    if not requested:
        raise ValueError('Choose at least one TestRail case to link.')
    cases = {int(case['id']): case for case in list_cases(config)}
    mappings = dict(config.get('case_mappings') or {})
    prepared = []
    seen_keys = set()
    seen_case_ids = {}
    for item in requested:
        key_text = str(item.get('vpt_key') or '').strip()
        key = normalize_vpt_key(key_text)
        case_id = int(item.get('case_id'))
        case = cases.get(case_id)
        if not key or not case:
            raise ValueError('Every row needs a VirtualPyTest case and a case from the connected TestRail project.')
        if key in seen_keys:
            raise ValueError(f"VirtualPyTest case '{key_text}' appears more than once in this batch.")
        if case_id in seen_case_ids and seen_case_ids[case_id] != key:
            raise ValueError(f'TestRail case C{case_id} is selected for more than one VirtualPyTest case.')
        seen_keys.add(key)
        seen_case_ids[case_id] = key
        prepared.append((key, key_text, case))

    for existing_key, existing in mappings.items():
        if existing_key not in seen_keys and int(existing.get('case_id', -1)) in seen_case_ids:
            raise ValueError(f"TestRail case C{existing.get('case_id')} is already linked to '{existing.get('vpt_key', 'another VPT case')}'.")
    output = []
    for key, key_text, case in prepared:
        suite_id = int(case['suite_id'])
        mapping = {'case_id': int(case['id']), 'title': str(case.get('title') or ''),
                   'suite_id': suite_id, 'suite_name': str(case.get('suite_name') or ''),
                   'vpt_key': key_text}
        mappings[key] = mapping
        output.append(mapping)
    config['case_mappings'] = mappings
    save_config(team_id, config)
    return output


def remove_mapping(team_id: str, vpt_key: str) -> bool:
    config = load_config(team_id)
    mappings = config.get('case_mappings') or {}
    existed = mappings.pop(normalize_vpt_key(vpt_key), None) is not None
    if existed:
        config['case_mappings'] = mappings
        save_config(team_id, config)
    return existed


def mappings_for_team(team_id: str) -> dict:
    config = load_config(team_id)
    return config.get('case_mappings') or {}


def publication_statuses(team_id: str) -> dict:
    config = load_config(team_id)
    return config.get('publications') or {}


def publish_campaign(team_id: str, campaign_id: str, campaign_name: str, execution_id: str,
                     execution_result: dict, host_name: str = '', device_name: str = '') -> dict:
    """Create one TestRail run per suite and add the mapped campaign results once."""
    config = load_config(team_id)
    if not config.get('auto_publish'):
        return {'status': 'disabled'}
    scripts = execution_result.get('script_executions') or []
    mappings = config.get('case_mappings') or {}
    eligible = []
    skipped = []
    for index, result in enumerate(scripts):
        result_status = str(result.get('status') or '').casefold()
        if (result.get('skipped') or result.get('success') is None
                or result_status in {'running', 'pending', 'cancelled', 'canceled', 'incomplete'}):
            skipped.append({'script_name': result.get('script_name', ''), 'status': 'skipped'})
            continue
        script_name = result.get('script_name') or ''
        testcase_id = result.get('testcase_id') or ''
        mapping = mappings.get(normalize_vpt_key(script_name)) or mappings.get(normalize_vpt_key(testcase_id))
        if not mapping:
            skipped.append({'script_name': script_name, 'status': 'unmapped'})
            continue
        result_id = str(result.get('script_result_id') or f'{execution_id}:{index}:{script_name}')
        eligible.append({'source_id': result_id, 'script_name': script_name, 'result': result, 'mapping': mapping})

    publications = config.setdefault('publications', {})
    prior = publications.get(str(execution_id))
    # Callback delivery may be retried. Once a publication attempt starts, never
    # create another run for the same execution; retain its state for reporting.
    if prior:
        return prior
    if not eligible:
        record = {'status': 'partial' if skipped else 'empty', 'skipped': skipped, 'runs': [], 'completed_at': _now()}
        publications[str(execution_id)] = record
        save_config(team_id, config)
        return record

    by_suite = {}
    for item in eligible:
        by_suite.setdefault(int(item['mapping']['suite_id']), []).append(item)

    run_records = []
    per_result = []
    # Save before the first external write so a process restart or repeated host
    # callback cannot silently duplicate TestRail runs.
    publications[str(execution_id)] = {
        'status': 'publishing', 'runs': [], 'results': [], 'skipped': skipped,
        'started_at': _now(),
    }
    save_config(team_id, config)
    for suite_id, suite_items in by_suite.items():
        suite_name = suite_items[0]['mapping'].get('suite_name') or f'Suite {suite_id}'
        run_name = f'VPT {campaign_name or campaign_id} · {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")} · {suite_name}'[:250]
        case_ids = list(dict.fromkeys(int(item['mapping']['case_id']) for item in suite_items))
        try:
            run = testrail_client.add_run(config, suite_id, run_name, case_ids,
                                          f'Automatically published from VirtualPyTest campaign execution {execution_id}.')
        except Exception as exc:
            per_result.extend({'source_id': item['source_id'], 'script_name': item['script_name'],
                               'case_id': int(item['mapping']['case_id']), 'status': 'failed',
                               'error': str(exc)[:500]} for item in suite_items)
            record = {'status': 'failed', 'runs': run_records, 'results': per_result,
                      'skipped': skipped, 'error': str(exc)[:500], 'completed_at': _now()}
            publications[str(execution_id)] = record
            save_config(team_id, config)
            return record
        run_id = int(run['id'])
        results = []
        for item in suite_items:
            value = item['result']
            status_id = 1 if bool(value.get('success')) else 5
            duration_ms = value.get('execution_time_ms')
            elapsed = f'{max(1, round(float(duration_ms) / 1000))}s' if duration_ms is not None else None
            comment_parts = [f'VirtualPyTest execution: {execution_id}', f'Case: {item["script_name"]}']
            if host_name:
                comment_parts.append(f'Host: {host_name}')
            if device_name:
                comment_parts.append(f'Device: {device_name}')
            if value.get('error'):
                comment_parts.append(f'Failure: {str(value["error"])[:1000]}')
            report_url = value.get('html_report_r2_url') or value.get('report_url')
            if report_url:
                comment_parts.append(f'Report: {report_url}')
            logs_url = value.get('logs_r2_url') or value.get('logs_url')
            if logs_url:
                comment_parts.append(f'Logs: {logs_url}')
            result_body = {'case_id': int(item['mapping']['case_id']), 'status_id': status_id,
                           'comment': '\n'.join(comment_parts)}
            if elapsed:
                result_body['elapsed'] = elapsed
            results.append(result_body)
        try:
            response_results = testrail_client.add_results_for_cases(config, run_id, results)
        except Exception as exc:
            run_url = f"{config['base_url']}/index.php?/runs/view/{run_id}"
            run_records.append({'run_id': run_id, 'name': run_name, 'suite_id': suite_id, 'url': run_url})
            per_result.extend({'source_id': item['source_id'], 'script_name': item['script_name'],
                               'case_id': int(item['mapping']['case_id']), 'run_id': run_id,
                               'status': 'failed', 'url': run_url} for item in suite_items)
            record = {'status': 'failed', 'runs': run_records, 'results': per_result,
                      'skipped': skipped, 'error': str(exc)[:500], 'completed_at': _now()}
            publications[str(execution_id)] = record
            save_config(team_id, config)
            return record
        result_by_case = {int(row['case_id']): row for row in response_results if row.get('case_id') is not None}
        for item in suite_items:
            remote = result_by_case.get(int(item['mapping']['case_id']), {})
            per_result.append({'source_id': item['source_id'], 'script_name': item['script_name'],
                               'case_id': int(item['mapping']['case_id']), 'run_id': run_id,
                               'result_id': remote.get('id'), 'status': 'published',
                               'url': f"{config['base_url']}/index.php?/runs/view/{run_id}"})
        run_records.append({'run_id': run_id, 'name': run_name, 'suite_id': suite_id,
                            'url': f"{config['base_url']}/index.php?/runs/view/{run_id}"})

    record = {'status': 'published' if not skipped else 'partial', 'runs': run_records,
              'results': per_result, 'skipped': skipped, 'completed_at': _now()}
    publications[str(execution_id)] = record
    save_config(team_id, config)
    return record


def publication_statuses_by_source(team_id: str) -> dict:
    """Index stored publication outcomes by VirtualPyTest script result id."""
    statuses = {}
    for publication in publication_statuses(team_id).values():
        for result in publication.get('results') or []:
            statuses[str(result.get('source_id'))] = result
    return statuses


def has_mapping(team_id: str, script_name: str) -> bool:
    return normalize_vpt_key(script_name) in mappings_for_team(team_id)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
