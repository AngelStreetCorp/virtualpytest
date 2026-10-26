"""Zammad feature lib: support-ticket provider, instance config and the team-scoped ticket index."""

from features.zammad.lib.base import (
    Article, Attachment, SupportError, SupportNotConfigured, SupportProvider, TicketFields, TicketRef,
)
