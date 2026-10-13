"""Explicit Jira push and authenticated refresh for test-result defects.

Credentials stay in the existing server-side Jira integration store
(``jira_instances.json`` managed by ``/server/integrations/jira/instances``).
The store is server-global, so an instance is usable only by the teams listed
in its ``teamIds``; push and refresh are refused for any other team.
API calls go through its ``call_jira_api`` (domain validation, basic auth,
tokens never reach the browser). This domain is separate from support /
customer issue tracking.

Push is idempotent across retries and timeouts:

1. ``rm_claim_defect_jira_push`` durably records the attempt (state pending,
   attempt counter, lease) BEFORE any external call. A concurrent push sees the
   lease and is refused; a push for an already created issue returns it.
2. Every issue is created with the correlation label ``vpt-defect-<defect id>``.
   A retry after an earlier attempt first searches Jira for that label and
   adopts an existing issue instead of creating a second one.
3. A definite Jira refusal releases the lease; an unknown outcome (timeout,
   connection reset, 5xx) keeps it until it expires, so an immediate retry
   cannot race Jira's search indexing.

Inbound sync: Jira Cloud webhooks registered by an admin carry no per-request
signature this server could verify, so no webhook receiver is exposed.
``refresh`` pulls the issue with server credentials instead, validates the
project/issue mapping, maps the status category through an allowlist and
ignores snapshots older than the last one applied.
"""

from __future__ import annotations

import urllib.parse
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional

from shared.src.lib.database import run_defects_db

LEASE_SECONDS = 120
ISSUE_TYPE = 'Bug'
# Jira status categories are fixed ('new', 'indeterminate', 'done'); status names are
# workflow-specific, so only the category is mapped.
STATUS_CATEGORY_MAP = {'new': 'open', 'indeterminate': 'in_progress', 'done': 'resolved'}
SEVERITY_PRIORITY = {'critical': 'Highest', 'high': 'High', 'medium': 'Medium', 'low': 'Low'}


class JiraOutcomeUnknown(Exception):
    """The request may or may not have reached Jira (timeout, reset, 5xx)."""


class JiraRefused(Exception):
    """Jira answered with a definite client error."""


@dataclass
class JiraInstance:
    id: str
    domain: str
    email: str
    api_token: str
    project_key: str

    @property
    def browse_base(self) -> str:
        return f'https://{self.domain}/browse/'


ApiCaller = Callable[..., Dict[str, Any]]


def _default_api_caller() -> ApiCaller:
    from backend_server.src.routes.server_integrations_routes import call_jira_api
    return call_jira_api


class JiraNotAvailable(Exception):
    """No Jira instance may be used for this team (HTTP status + message)."""

    def __init__(self, message: str, status: int = 409) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


def instance_allows_team(instance: Dict[str, Any], team_id: str) -> bool:
    """An instance serves only the teams its config lists in ``teamIds``.

    The store is server-global; without an explicit allowlist an instance is
    not usable by any team's defects.
    """
    team_ids = instance.get('teamIds')
    return isinstance(team_ids, list) and str(team_id) in {str(t) for t in team_ids}


def load_instance(instance_id: Optional[str], team_id: str) -> JiraInstance:
    """The Jira instance a team's defect may be pushed to / refreshed from.

    With ``instance_id`` that instance must exist and list the team. Without
    one, the team's single allowed instance is used; zero or several allowed
    instances is a refusal. Raises JiraNotAvailable.
    """
    from backend_server.src.routes.server_integrations_routes import load_jira_instances
    instances = [i for i in (load_jira_instances() or []) if isinstance(i, dict)]
    if instance_id:
        chosen = next((i for i in instances if i.get('id') == instance_id), None)
        if chosen is None:
            raise JiraNotAvailable(f'Jira instance {instance_id!r} is not configured', 409)
        if not instance_allows_team(chosen, team_id):
            raise JiraNotAvailable(f'Jira instance {instance_id!r} is not enabled for this team '
                                   '(an admin must add the team to the instance teamIds)', 403)
    else:
        allowed = [i for i in instances if instance_allows_team(i, team_id)]
        if not allowed:
            raise JiraNotAvailable('no Jira instance is enabled for this team '
                                   '(an admin must add the team to an instance teamIds)', 409)
        if len(allowed) > 1:
            raise JiraNotAvailable('several Jira instances are enabled for this team; pass instance_id', 409)
        chosen = allowed[0]
    if not chosen.get('projectKey'):
        raise JiraNotAvailable(f'Jira instance {chosen.get("id")!r} has no project key', 409)
    return JiraInstance(id=chosen['id'], domain=chosen['domain'], email=chosen['email'],
                        api_token=chosen['apiToken'], project_key=chosen['projectKey'])


class JiraClient:
    """Minimal Jira REST v3 client over the integration store's caller."""

    def __init__(self, instance: JiraInstance, api_caller: Optional[ApiCaller] = None) -> None:
        self.instance = instance
        self._call = api_caller or _default_api_caller()

    def _request(self, endpoint: str, method: str = 'GET', data: Optional[Dict[str, Any]] = None):
        try:
            return self._call(self.instance.domain, endpoint, self.instance.email,
                              self.instance.api_token, method=method, data=data)
        except Exception as e:
            status = getattr(getattr(e, 'response', None), 'status_code', None)
            if status is not None and 400 <= status < 500:
                raise JiraRefused(f'Jira refused the request (HTTP {status})') from e
            if status is None and isinstance(e, ValueError):
                raise JiraRefused(f'Jira request not sent: {e}') from e
            raise JiraOutcomeUnknown(f'Jira request outcome unknown: {type(e).__name__}') from e

    def find_by_label(self, label: str) -> Optional[Dict[str, Any]]:
        jql = f'project = "{self.instance.project_key}" AND labels = "{label}" ORDER BY created ASC'
        endpoint = f'/search/jql?jql={urllib.parse.quote(jql)}&maxResults=2&fields=summary,status,updated,project'
        result = self._request(endpoint) or {}
        issues = result.get('issues') or []
        return issues[0] if issues else None

    def create_issue(self, fields: Dict[str, Any]) -> Dict[str, Any]:
        return self._request('/issue', method='POST', data={'fields': fields}) or {}

    def get_issue(self, key: str) -> Dict[str, Any]:
        return self._request(f'/issue/{urllib.parse.quote(key)}?fields=status,updated,project') or {}


def _adf(text: str) -> Dict[str, Any]:
    return {'type': 'doc', 'version': 1, 'content': [
        {'type': 'paragraph', 'content': [{'type': 'text', 'text': text or ' '}]}]}


def _issue_fields(instance: JiraInstance, defect: Dict[str, Any], label: str, evidence_count: int) -> Dict[str, Any]:
    description = (defect.get('description') or '').strip()
    summary_line = f'VirtualPyTest defect {defect["id"]} - {evidence_count} linked execution result(s).'
    return {
        'project': {'key': instance.project_key},
        'summary': defect['title'][:250],
        'issuetype': {'name': ISSUE_TYPE},
        'labels': [label],
        'description': _adf(f'{description}\n\n{summary_line}' if description else summary_line),
    }


def push(team_id: str, defect: Dict[str, Any], instance: JiraInstance, *, evidence_count: int,
         client: Optional[JiraClient] = None) -> Dict[str, Any]:
    """Run one explicit push. Returns ``{'status': <http status>, 'body': {...}}``."""
    defect_id = defect['id']
    if defect.get('integration') == 'jira' and defect.get('external_key'):
        return {'status': 200, 'body': {'state': 'created', 'idempotent': True,
                                        'external_key': defect['external_key'],
                                        'external_url': defect.get('external_url')}}
    claim = run_defects_db.claim_jira_push(team_id, defect_id, instance.id, instance.project_key, LEASE_SECONDS)
    if not claim.get('claimed'):
        reason = claim.get('reason')
        if reason == 'already_created':
            # The issue exists but the defect link was not written; finish it.
            run_defects_db.complete_jira_push(team_id, defect_id, claim['external_key'], claim.get('external_url') or '')
            return {'status': 200, 'body': {'state': 'created', 'idempotent': True,
                                            'external_key': claim['external_key'],
                                            'external_url': claim.get('external_url')}}
        if reason == 'not_found':
            return {'status': 404, 'body': {'error': 'defect not found'}}
        if reason == 'target_mismatch':
            return {'status': 409, 'body': {'error': 'an earlier push targeted a different Jira instance or project',
                                            'instance_id': claim.get('instance_id'),
                                            'project_key': claim.get('project_key')}}
        return {'status': 409, 'body': {'error': 'a push for this defect is already in progress',
                                        'retry_after': claim.get('lease_until')}}

    jira = client or JiraClient(instance)
    label = claim['correlation_label']
    try:
        issue = jira.find_by_label(label) if claim.get('reconcile') else None
        reconciled = issue is not None
        if issue is None:
            issue = jira.create_issue(_issue_fields(instance, defect, label, evidence_count))
        key = issue.get('key')
        if not key:
            raise JiraOutcomeUnknown('Jira response carried no issue key')
    except JiraRefused as e:
        run_defects_db.fail_jira_push(team_id, defect_id, str(e), release_lease=True)
        return {'status': 502, 'body': {'error': str(e), 'state': 'failed', 'retryable': True}}
    except JiraOutcomeUnknown as e:
        run_defects_db.fail_jira_push(team_id, defect_id, str(e), release_lease=False)
        return {'status': 504, 'body': {'error': str(e), 'state': 'unknown',
                                        'retryable': True, 'retry_after_seconds': LEASE_SECONDS}}

    url = instance.browse_base + key
    run_defects_db.complete_jira_push(team_id, defect_id, key, url)
    return {'status': 201, 'body': {'state': 'created', 'idempotent': reconciled,
                                    'external_key': key, 'external_url': url}}


def _parse_jira_time(value: Any) -> Optional[datetime]:
    if not value:
        return None
    text = str(value)
    # Jira: 2026-10-03T08:15:30.123+0000
    if len(text) > 5 and text[-5] in '+-' and text[-3] != ':':
        text = text[:-2] + ':' + text[-2:]
    try:
        parsed = datetime.fromisoformat(text.replace('Z', '+00:00'))
    except ValueError:
        return None
    return parsed.astimezone(timezone.utc) if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def refresh(team_id: str, defect: Dict[str, Any], push_state: Optional[Dict[str, Any]],
            instance: Optional[JiraInstance], client: Optional[JiraClient] = None) -> Dict[str, Any]:
    """Pull the linked issue's status and apply it to this defect only."""
    key = defect.get('external_key')
    if defect.get('integration') != 'jira' or not key or not push_state:
        return {'status': 409, 'body': {'error': 'defect is not linked to a Jira issue'}}
    if instance is None or instance.id != push_state.get('instance_id'):
        return {'status': 409, 'body': {'error': 'the Jira instance this defect was pushed to is not available'}}
    jira = client or JiraClient(instance)
    try:
        issue = jira.get_issue(key)
    except (JiraRefused, JiraOutcomeUnknown) as e:
        return {'status': 502, 'body': {'error': str(e)}}
    fields = issue.get('fields') or {}
    project_key = (fields.get('project') or {}).get('key')
    if issue.get('key') != key or project_key != push_state.get('project_key'):
        return {'status': 409, 'body': {'error': 'Jira returned an issue that does not match the recorded mapping'}}
    status = fields.get('status') or {}
    category = ((status.get('statusCategory') or {}).get('key') or '').lower()
    mapped = STATUS_CATEGORY_MAP.get(category)
    if mapped is None:
        return {'status': 422, 'body': {'error': f'unmapped Jira status category {category!r}'}}
    updated = _parse_jira_time(fields.get('updated'))
    if updated is None:
        return {'status': 422, 'body': {'error': 'Jira issue has no usable updated timestamp'}}
    stamp = updated.strftime('%Y-%m-%dT%H:%M:%S.%fZ')
    applied = run_defects_db.apply_jira_refresh(
        team_id, defect['id'], status=mapped, external_status=str(status.get('name') or '')[:100],
        external_updated_at=stamp)
    return {'status': 200, 'body': {'applied': applied, 'status': mapped,
                                    'external_status': status.get('name'),
                                    'external_updated_at': stamp,
                                    'stale': not applied}}
