"""Support-ticket provider interface (TASK-96).

A provider talks to an external helpdesk (Zammad first; Jira / GitLab Issues later).
The thread lives in the provider; VirtualPyTest only keeps an index row per ticket
(``support_tickets``). Providers hold no team logic: routes scope every call by team_id
through the index before touching a provider.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from features.zammad.lib.model import STATUS_CLOSED, STATUS_NEW  # noqa: F401  (re-exported for providers)


class SupportError(Exception):
    """Provider call failed (network, auth, unexpected response)."""

    def __init__(self, message: str, status: Optional[int] = None) -> None:
        super().__init__(message)
        self.status = status


class SupportNotConfigured(SupportError):
    """The provider has no URL / token configured on this server."""


@dataclass
class Attachment:
    filename: str
    data_b64: str
    mime_type: str = 'application/octet-stream'


@dataclass
class TicketFields:
    """The ticket model's classification, already validated (see model.py)."""
    ticket_type: str
    family: str
    category: str
    frequency: str
    priority: str = 'P1'
    severity: Optional[str] = None
    target_id: Optional[str] = None
    target_label: Optional[str] = None


@dataclass
class TicketRef:
    external_id: str
    number: Optional[str] = None
    status: str = STATUS_NEW
    title: str = ''


@dataclass
class Article:
    id: str
    author: str
    body: str
    created_at: Optional[str] = None
    from_customer: bool = False
    internal: bool = False
    attachments: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'author': self.author,
            'body': self.body,
            'created_at': self.created_at,
            'from_customer': self.from_customer,
            'attachments': self.attachments,
        }


class SupportProvider(ABC):
    name = 'base'

    @abstractmethod
    def create_ticket(self, *, title: str, body: str, fields: TicketFields, requester_email: str,
                      attachments: Optional[List[Attachment]] = None) -> TicketRef:
        """Open a ticket on behalf of ``requester_email``; ``body`` is the first article."""

    @abstractmethod
    def get_ticket(self, external_id: str) -> TicketRef:
        """Current title / status of one ticket."""

    def list_tickets(self, external_ids: List[str]) -> List[TicketRef]:
        """Optional bulk read; default loops get_ticket and skips failures."""
        refs: List[TicketRef] = []
        for ext in external_ids:
            try:
                refs.append(self.get_ticket(ext))
            except SupportError:
                continue
        return refs

    @abstractmethod
    def list_articles(self, external_id: str) -> List[Article]:
        """Public articles of the thread, oldest first (internal notes are never returned)."""

    @abstractmethod
    def add_reply(self, external_id: str, *, body: str, author_email: str,
                  attachments: Optional[List[Attachment]] = None) -> Article:
        """Add a customer reply to the thread."""

    @abstractmethod
    def close(self, external_id: str) -> TicketRef:
        """Close the ticket."""
