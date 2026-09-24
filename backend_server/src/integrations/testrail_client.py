"""Small, server-side TestRail Cloud API client used by the integration settings page."""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlsplit

import requests
from requests.auth import HTTPBasicAuth


class TestRailConnectionError(Exception):
    def __init__(self, category: str, message: str):
        super().__init__(message)
        self.category = category


def validate_base_url(value: str) -> str:
    """Accept a TestRail Cloud tenant origin only; reject arbitrary URL targets."""
    try:
        parsed = urlsplit((value or '').strip().rstrip('/'))
        host = (parsed.hostname or '').lower().rstrip('.')
        cloud_suffixes = ('.testrail.com', '.testrail.io', '.testrail.net')
        if (parsed.scheme != 'https' or not host.endswith(cloud_suffixes)
                or parsed.username or parsed.password
                or parsed.port not in (None, 443) or parsed.path not in ('', '/')
                or parsed.query or parsed.fragment):
            raise ValueError
        # Defense in depth against a malicious DNS answer/private endpoint.
        for record in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM):
            address = ipaddress.ip_address(record[4][0])
            if not address.is_global:
                raise ValueError
        return f'https://{host}'
    except (ValueError, OSError, socket.gaierror):
        raise TestRailConnectionError('invalid_url', 'Enter a valid TestRail Cloud URL, such as https://company.testrail.io.')


def _request(base_url: str, username: str, api_key: str, endpoint: str, *, method='GET', payload=None) -> dict:
    url = f'{base_url}/index.php?/api/v2/{endpoint}'
    try:
        request_fn = requests.get if method == 'GET' else requests.post
        response = request_fn(
            url,
            auth=HTTPBasicAuth(username, api_key),
            headers={'Accept': 'application/json'},
            json=payload if method == 'POST' else None,
            timeout=15,
            allow_redirects=False,
        )
    except requests.Timeout:
        raise TestRailConnectionError('timeout', 'TestRail did not respond within 15 seconds.')
    except requests.RequestException:
        raise TestRailConnectionError('network', 'Could not reach TestRail. Check the URL and server network access.')

    if response.status_code in (301, 302, 303, 307, 308):
        raise TestRailConnectionError('redirect', 'TestRail redirected the API request. Check the instance URL.')
    if response.status_code in (401, 403):
        raise TestRailConnectionError('authentication', 'TestRail rejected the username or API key, or the account lacks API access.')
    if response.status_code == 429:
        raise TestRailConnectionError('rate_limited', 'TestRail rate-limited the connection check. Try again shortly.')
    if response.status_code >= 500:
        raise TestRailConnectionError('unavailable', 'TestRail is temporarily unavailable. Try again later.')
    if response.status_code >= 400:
        raise TestRailConnectionError('api_error', 'TestRail rejected the API request. Check the instance URL and account access.')
    try:
        return response.json()
    except ValueError:
        raise TestRailConnectionError('api_error', 'TestRail returned an unexpected response.')


def _get(base_url: str, username: str, api_key: str, endpoint: str) -> dict:
    return _request(base_url, username, api_key, endpoint)


def get_suites(config: dict) -> list[dict]:
    response = _get(config['base_url'], config['username'], config['api_key'], f"get_suites/{config['project_id']}")
    suites = response if isinstance(response, list) else response.get('suites', [])
    return [{'id': s.get('id'), 'name': s.get('name')} for s in suites if s.get('id') is not None]


def get_cases(config: dict, *, suite_id=None, limit=250, offset=0, filter_text=None) -> list[dict]:
    endpoint = f"get_cases/{config['project_id']}"
    params = []
    if suite_id is not None:
        params.append(f'suite_id={int(suite_id)}')
    params.extend([f'limit={min(max(int(limit), 1), 250)}', f'offset={max(int(offset), 0)}'])
    if filter_text:
        from urllib.parse import quote
        params.append(f'filter={quote(str(filter_text)[:100], safe="")}')
    response = _get(config['base_url'], config['username'], config['api_key'], endpoint + '&' + '&'.join(params))
    cases = response if isinstance(response, list) else response.get('cases', [])
    return [{'id': c.get('id'), 'title': c.get('title'), 'suite_id': c.get('suite_id'), 'section_id': c.get('section_id')}
            for c in cases if c.get('id') is not None]


def get_case(config: dict, case_id: int) -> dict:
    return _get(config['base_url'], config['username'], config['api_key'], f'get_case/{int(case_id)}')


def get_suite(config: dict, suite_id: int) -> dict:
    return _get(config['base_url'], config['username'], config['api_key'], f"get_suite/{int(suite_id)}")


def add_case(config: dict, section_id: int, title: str, refs: str = '') -> dict:
    payload = {'title': title[:250]}
    if refs:
        payload['refs'] = refs[:250]
    return _request(config['base_url'], config['username'], config['api_key'], f'add_case/{int(section_id)}', method='POST', payload=payload)


def add_run(config: dict, suite_id: int, name: str, case_ids: list[int], description: str = '') -> dict:
    payload = {'suite_id': int(suite_id), 'name': name[:250], 'include_all': False, 'case_ids': [int(x) for x in case_ids]}
    if description:
        payload['description'] = description[:2000]
    return _request(config['base_url'], config['username'], config['api_key'], f"add_run/{config['project_id']}", method='POST', payload=payload)


def add_results_for_cases(config: dict, run_id: int, results: list[dict]) -> list[dict]:
    response = _request(config['base_url'], config['username'], config['api_key'],
                        f'add_results_for_cases/{int(run_id)}', method='POST', payload={'results': results})
    return response if isinstance(response, list) else response.get('results', [])


def test_connection(base_url: str, username: str, api_key: str) -> dict:
    normalized = validate_base_url(base_url)
    if not (username or '').strip() or not (api_key or '').strip():
        raise TestRailConnectionError('missing_credentials', 'Username/email and API key are required.')
    projects_data = _get(normalized, username.strip(), api_key.strip(), 'get_projects&is_completed=0')
    projects = projects_data if isinstance(projects_data, list) else projects_data.get('projects', [])
    if not isinstance(projects, list):
        projects = []
    return {
        'base_url': normalized,
        'projects': [{'id': p.get('id'), 'name': p.get('name')} for p in projects if p.get('id') is not None],
    }
