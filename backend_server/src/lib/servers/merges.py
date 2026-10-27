"""Merge functions for ``@supports_all_servers`` routes (TASK-179 P3): one row per server in ``servers``."""

from typing import Any, Callable, Dict, List, Optional

from backend_server.src.lib.servers.fanout import ServerResult


def _absolute(origin: str, value: Any) -> Any:
    """Put the owning server's origin in front of a root-relative URL (BUG-0106: ``/host/<name>`` resolved against
    the wrong origin opens a different machine with the same host name)."""
    if isinstance(value, str) and value.startswith('/') and not value.startswith('//'):
        return origin.rstrip('/') + value
    return value


def _summary(name: str, url: str, ok: bool, status: Optional[int], error: Optional[str], latency_ms: int,
             **counts: int) -> Dict[str, Any]:
    return {'name': name, 'url': url, 'ok': ok, 'status': status, 'error': error, 'latency_ms': latency_ms, **counts}


def _merge(local: Dict[str, Any], self_row: Dict[str, Any], results: List[ServerResult], field: str,
           take: Callable[[Any, str, str], Any], count: Callable[[Any], Dict[str, int]]) -> Dict[str, Any]:
    """Shared skeleton: ``take(payload, name, origin)`` returns the tagged rows of one server, ``count`` the
    per-server counters of the summary. A peer whose payload lacks the field becomes ``bad response``."""
    rows: Any = None
    summary: List[Dict[str, Any]] = []
    sources = [(self_row['name'], self_row['url'], True, 200, None, self_row.get('latency_ms', 0), local)]
    sources += [(r.server, r.url, r.ok, r.status, r.error, r.latency_ms, r.data) for r in results]
    for name, url, ok, status, error, latency, payload in sources:
        if ok and not (isinstance(payload, dict) and isinstance(payload.get(field), (list, dict))):
            ok, error = False, 'bad response'
        if not ok:
            summary.append(_summary(name, url, False, status, error, latency, **count(None)))
            continue
        tagged = take(payload[field], name, url)
        rows = tagged if rows is None else (rows + tagged if isinstance(rows, list) else {**rows, **tagged})
        summary.append(_summary(name, url, True, status, None, latency, **count(tagged)))
    return {**local, field: rows if rows is not None else [], 'servers': summary}


def merge_hosts(local: Dict[str, Any], self_row: Dict[str, Any], results: List[ServerResult]) -> Dict[str, Any]:
    """``getAllHosts``: concatenate ``hosts``; each gets ``server`` / ``server_url`` and an absolute ``host_url``."""
    def take(hosts: List[Dict[str, Any]], name: str, origin: str) -> List[Dict[str, Any]]:
        out = []
        for host in hosts:
            host = {**host, 'server': name, 'server_url': origin, 'host_url': _absolute(origin, host.get('host_url'))}
            # Per-device report links (screenshots, video) are root-relative on some deployments.
            devices = []
            for device in host.get('devices') or []:
                device = dict(device)
                for key in ('device_info_report', 'gateway_info_report'):
                    if isinstance(device.get(key), dict):
                        device[key] = {k: _absolute(origin, v) if k.endswith('_url') else v
                                       for k, v in device[key].items()}
                devices.append(device)
            if 'devices' in host:
                host['devices'] = devices
            out.append(host)
        return out

    def count(hosts: Optional[List[Dict[str, Any]]]) -> Dict[str, int]:
        hosts = hosts or []
        return {'host_count': len(hosts),
                'device_count': sum(h['device_count'] if isinstance(h.get('device_count'), int)
                                    else len(h.get('devices') or []) for h in hosts)}

    return _merge(local, self_row, results, 'hosts', take, count)


def merge_locked_devices(local: Dict[str, Any], self_row: Dict[str, Any], results: List[ServerResult]) -> Dict[str, Any]:
    """``lockedDevices``: ``locked_devices`` stays a dict, keyed ``<server>:<device_key>``; each lock gets ``server``."""
    def take(locks: Dict[str, Dict[str, Any]], name: str, origin: str) -> Dict[str, Dict[str, Any]]:
        return {f'{name}:{key}': {**lock, 'server': name, 'server_url': origin} for key, lock in locks.items()}

    return _merge(local, self_row, results, 'locked_devices', take,
                  lambda locks: {'lock_count': len(locks or {})})
