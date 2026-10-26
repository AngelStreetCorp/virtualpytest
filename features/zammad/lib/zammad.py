"""Zammad implementation of SupportProvider (TASK-96).

Config: `features.zammad.lib.config.effective()` (the page's form, else env ZAMMAD_URL / ZAMMAD_API_TOKEN);
`ZammadProvider(base_url, token)` takes them explicitly so it can be tested and probed before saving.
Token auth: ``Authorization: Token token=<token>``. Tickets are created for the customer
``guess:<email>`` (Zammad finds or creates the customer), so Zammad email replies reach them.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import requests

from features.zammad.lib.base import (
    Article, Attachment, SupportError, SupportNotConfigured, SupportProvider, TicketFields, TicketRef,
)
from features.zammad.lib.model import STATUS_CLOSED, STATUS_TO_ZAMMAD_STATE, ZAMMAD_PRIORITY_ID, group_for, map_status

REQUEST_TIMEOUT_S = 20
PENDING_REMINDER_DAYS = 7


class ZammadProvider(SupportProvider):
    name = 'zammad'

    def __init__(self, base_url: str = '', token: str = '',
                 session: Optional[requests.Session] = None) -> None:
        self.base_url = (base_url or '').strip().rstrip('/')
        self._token = (token or '').strip()
        self._http = session or requests.Session()

    def whoami(self) -> Dict[str, Any]:
        """GET /users/me - the cheapest authenticated call; used to test a connection."""
        return self._request('GET', '/users/me')

    # ------------------------------------------------------------------ http
    def _request(self, method: str, path: str, *, json: Optional[dict] = None,
                 params: Optional[dict] = None) -> Any:
        if not self.base_url or not self._token:
            raise SupportNotConfigured('Zammad URL and API token are not configured on this server')
        try:
            resp = self._http.request(
                method, f'{self.base_url}/api/v1{path}', json=json, params=params,
                headers={'Authorization': f'Token token={self._token}', 'Accept': 'application/json'},
                timeout=REQUEST_TIMEOUT_S,
            )
        except requests.RequestException as e:
            raise SupportError(f'Zammad unreachable: {type(e).__name__}') from e
        if resp.status_code >= 400:
            # The body can echo request data; keep only a short, token-free hint.
            raise SupportError(f'Zammad {method} {path} failed with HTTP {resp.status_code}', resp.status_code)
        try:
            return resp.json()
        except ValueError as e:
            raise SupportError('Zammad returned a non-JSON response', resp.status_code) from e

    @staticmethod
    def _attachments_payload(attachments: Optional[List[Attachment]]) -> List[Dict[str, str]]:
        return [{'filename': a.filename, 'data': a.data_b64, 'mime-type': a.mime_type}
                for a in (attachments or [])]

    @staticmethod
    def _ref(ticket: Dict[str, Any]) -> TicketRef:
        return TicketRef(external_id=str(ticket.get('id')), number=ticket.get('number'),
                         status=map_status(ticket.get('state')), title=ticket.get('title') or '')

    # ------------------------------------------------------------------ interface
    @staticmethod
    def custom_attributes(fields: TicketFields) -> Dict[str, str]:
        """The vpt_* Object Manager attributes (created by setup_zammad.py); empty ones are left out."""
        target = fields.target_label or fields.target_id or ''
        if fields.target_label and fields.target_id and fields.target_label != fields.target_id:
            target = f'{fields.target_label} ({fields.target_id})'
        values = {
            'vpt_type': fields.ticket_type, 'vpt_family': fields.family, 'vpt_category': fields.category,
            'vpt_target': target, 'vpt_severity': fields.severity or '', 'vpt_frequency': fields.frequency,
        }
        return {k: v for k, v in values.items() if v}

    def create_ticket(self, *, title: str, body: str, fields: TicketFields, requester_email: str,
                      attachments: Optional[List[Attachment]] = None) -> TicketRef:
        try:
            group = group_for(fields.family, fields.category)
        except ValueError as e:
            raise SupportError(str(e)) from e
        article: Dict[str, Any] = {
            'subject': title, 'body': body, 'type': 'web', 'sender': 'Customer',
            'internal': False, 'content_type': 'text/plain',
        }
        files = self._attachments_payload(attachments)
        if files:
            article['attachments'] = files
        data = self._request('POST', '/tickets', params={'expand': 'true'}, json={
            'title': title, 'group': group, 'priority_id': ZAMMAD_PRIORITY_ID[fields.priority],
            'customer_id': f'guess:{requester_email}', 'article': article,
            **self.custom_attributes(fields),
        })
        return self._ref(data)

    def get_ticket(self, external_id: str) -> TicketRef:
        return self._ref(self._request('GET', f'/tickets/{external_id}', params={'expand': 'true'}))

    def list_articles(self, external_id: str) -> List[Article]:
        rows = self._request('GET', f'/ticket_articles/by_ticket/{external_id}', params={'expand': 'true'})
        articles: List[Article] = []
        for row in rows or []:
            if row.get('internal'):
                continue
            articles.append(Article(
                id=str(row.get('id')),
                author=row.get('from') or row.get('created_by') or '',
                body=row.get('body') or '',
                created_at=row.get('created_at'),
                from_customer=(row.get('sender') == 'Customer'),
                attachments=[{'id': a.get('id'), 'filename': a.get('filename'), 'size': a.get('size')}
                             for a in (row.get('attachments') or [])],
            ))
        return articles

    def add_reply(self, external_id: str, *, body: str, author_email: str,
                  attachments: Optional[List[Attachment]] = None) -> Article:
        payload: Dict[str, Any] = {
            'ticket_id': int(external_id), 'body': body, 'type': 'web', 'sender': 'Customer',
            'internal': False, 'content_type': 'text/plain', 'from': author_email,
        }
        files = self._attachments_payload(attachments)
        if files:
            payload['attachments'] = files
        row = self._request('POST', '/ticket_articles', json=payload)
        return Article(id=str(row.get('id')), author=author_email, body=row.get('body') or body,
                       created_at=row.get('created_at'), from_customer=True)

    def set_status(self, external_id: str, status: str) -> TicketRef:
        """Move a ticket to a workflow status. Zammad's pending states need a pending_time, so `need_info`
        is set with a reminder PENDING_REMINDER_DAYS ahead."""
        state = STATUS_TO_ZAMMAD_STATE.get(status)
        if not state:
            raise SupportError(f'unknown status: {status}')
        payload: Dict[str, Any] = {'state': state}
        if status == 'need_info':
            payload['pending_time'] = (datetime.now(timezone.utc) + timedelta(days=PENDING_REMINDER_DAYS)).isoformat()
        return self._ref(self._request('PUT', f'/tickets/{external_id}', params={'expand': 'true'}, json=payload))

    def close(self, external_id: str) -> TicketRef:
        data = self._request('PUT', f'/tickets/{external_id}', params={'expand': 'true'},
                             json={'state': STATUS_TO_ZAMMAD_STATE[STATUS_CLOSED]})
        return self._ref(data)
