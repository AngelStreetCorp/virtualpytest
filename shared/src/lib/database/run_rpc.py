"""Shared helpers for the TASK-42 run-services database modules.

The run-services SQL functions (``rm_*``) raise ``P0001`` errors whose message
starts with a stable ``rm:<code>`` prefix. ``call_rpc`` turns those into
``RunDbError(code, detail)`` so routes can map them to HTTP statuses; any other
database error propagates unchanged.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, Optional, Sequence

from shared.src.lib.utils.supabase_utils import get_supabase_client


_RM_ERROR_RE = re.compile(r'rm:(?P<code>[a-z_]+)\s*(?P<detail>[^"\'}]*)')


class RunDbError(Exception):
    """A business-rule refusal raised by an ``rm_*`` SQL function."""

    def __init__(self, code: str, detail: str = '') -> None:
        super().__init__(f'{code}: {detail}' if detail else code)
        self.code = code
        self.detail = detail.strip()


def get_supabase():
    return get_supabase_client()


def call_rpc(name: str, params: Dict[str, Any], client: Optional[Any] = None) -> Any:
    supabase = client or get_supabase()
    try:
        return supabase.rpc(name, params).execute().data
    except Exception as e:
        match = _RM_ERROR_RE.search(str(e))
        if match:
            raise RunDbError(match.group('code'), match.group('detail')) from e
        raise


def json_field(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (ValueError, TypeError):
            return value
    return value


def normalize_row(row: Dict[str, Any], uuid_keys: Sequence[str],
                  json_keys: Sequence[str] = ()) -> Dict[str, Any]:
    for key in uuid_keys:
        if row.get(key) is not None:
            row[key] = str(row[key])
    for key in json_keys:
        if key in row:
            row[key] = json_field(row[key])
    return row
