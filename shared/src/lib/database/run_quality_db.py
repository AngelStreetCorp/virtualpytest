"""Scoped quality aggregates and report queries (TASK-42).

Thin wrappers over the ``rm_*`` SQL functions. All aggregation runs in the
database over the full scoped population (team, this server's hosts, optional
workspace device keys, time window) before any limit is applied.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence

from shared.src.lib.database.run_rpc import call_rpc, json_field


def _scope_params(team_id: str, host_names: Sequence[str], device_keys: Optional[Sequence[str]],
                  since: datetime, until: datetime) -> Dict[str, Any]:
    return {
        'p_team_id': team_id,
        'p_host_names': list(host_names),
        'p_device_keys': list(device_keys) if device_keys is not None else None,
        'p_since': since.isoformat(),
        'p_until': until.isoformat(),
    }


def flaky_identities(team_id: str, host_names: Sequence[str], device_keys: Optional[Sequence[str]],
                     since: datetime, until: datetime, min_attempts: int) -> List[Dict[str, Any]]:
    params = _scope_params(team_id, host_names, device_keys, since, until)
    params['p_min_attempts'] = min_attempts
    return list(call_rpc('rm_quality_flaky', params) or [])


def slow_identities(team_id: str, host_names: Sequence[str], device_keys: Optional[Sequence[str]],
                    since: datetime, until: datetime, min_samples: int) -> List[Dict[str, Any]]:
    params = _scope_params(team_id, host_names, device_keys, since, until)
    params['p_min_samples'] = min_samples
    return list(call_rpc('rm_quality_slow', params) or [])


def executed_script_names(team_id: str, host_names: Sequence[str], device_keys: Optional[Sequence[str]],
                          since: datetime, until: datetime) -> List[Dict[str, Any]]:
    params = _scope_params(team_id, host_names, device_keys, since, until)
    return list(call_rpc('rm_executed_script_names', params) or [])


def run_query(team_id: str, host_names: Sequence[str], device_keys: Optional[Sequence[str]],
              since: datetime, until: datetime, *, filters: Dict[str, Any], sort: str,
              descending: bool, limit: int, offset: int, chart: str,
              include_discarded: bool) -> Dict[str, Any]:
    params = _scope_params(team_id, host_names, device_keys, since, until)
    params.update({
        'p_scripts': filters.get('scripts'),
        'p_hosts': filters.get('hosts'),
        'p_devices': filters.get('devices'),
        'p_uis': filters.get('uis'),
        'p_envs': filters.get('envs'),
        'p_statuses': filters.get('statuses'),
        'p_milestone_ids': filters.get('milestone_ids'),
        'p_label_ids': filters.get('label_ids'),
        'p_flaky_only': bool(filters.get('flaky')),
        'p_include_discarded': include_discarded,
        'p_sort': sort,
        'p_desc': descending,
        'p_limit': limit,
        'p_offset': offset,
        'p_chart': chart,
    })
    data = json_field(call_rpc('rm_run_query', params))
    if isinstance(data, list):
        data = data[0] if data else {}
    return data or {'total': 0, 'counts': {'passed': 0, 'failed': 0, 'unknown': 0}, 'rows': [], 'series': []}
