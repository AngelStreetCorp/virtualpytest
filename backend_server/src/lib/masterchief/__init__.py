"""Masterchief library: op registry, redaction, audit table.

TASK-71. The surface is intentionally narrow: a code-defined allow-list of ops,
an audit row per attempt, and redaction at every output boundary. Nothing here
writes to anything other than `public.masterchief_audit`.
"""
from .redaction import redact_params, redact_result, REDACT_KEYS, MAX_PARAMS_JSON, MAX_SUMMARY_CHARS
from .audit_db import (
    insert_audit_row,
    update_audit_state,
    get_audit_row,
    list_audit_rows,
    count_open_for_user,
)
from .ops import MASTERCHIEF_OPS, MasterchiefOp, OpContext, OpResult, get_op, list_ops, execute_op, platform_admin_required

__all__ = [
    'MASTERCHIEF_OPS',
    'MasterchiefOp',
    'OpContext',
    'OpResult',
    'get_op',
    'list_ops',
    'execute_op',
    'platform_admin_required',
    'redact_params',
    'redact_result',
    'REDACT_KEYS',
    'MAX_PARAMS_JSON',
    'MAX_SUMMARY_CHARS',
    'insert_audit_row',
    'update_audit_state',
    'get_audit_row',
    'list_audit_rows',
    'count_open_for_user',
]
