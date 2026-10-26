"""
Uplink usage of the proxy/server machine, for the Status page.

Live rate comes from psutil NIC counters (delta between two calls). The 24h peak
comes from vnstat's 5-minute buckets when vnstat is installed (installed by
setup/local/linux/reverse_proxy/install_nginx.sh), else from an in-memory ring.
"""

import json
import shutil
import subprocess
import threading
import time
from collections import deque
from typing import Dict, Any, Optional

import psutil

_lock = threading.Lock()
_last: Optional[tuple] = None  # (timestamp, rx_bytes, tx_bytes, nic)
_ring: deque = deque(maxlen=2880)  # 24h at one sample / 30s
_RING_MIN_GAP = 30


def _primary_nic() -> Optional[str]:
    """Busiest non-virtual interface that is up (the one carrying viewer traffic)."""
    stats = psutil.net_if_stats()
    counters = psutil.net_io_counters(pernic=True)
    skip = ('lo', 'docker', 'br-', 'veth', 'tailscale', 'virbr', 'tun', 'utun', 'awdl', 'llw', 'bridge', 'wg')
    best, best_bytes = None, -1
    for name, st in stats.items():
        if not st.isup or name.startswith(skip) or name not in counters:
            continue
        total = counters[name].bytes_recv + counters[name].bytes_sent
        if total > best_bytes:
            best, best_bytes = name, total
    return best


def _vnstat_peak_mbit(nic: str) -> Optional[Dict[str, float]]:
    if not shutil.which('vnstat'):
        return None
    try:
        out = subprocess.run(['vnstat', '-i', nic, '--json', 'f', '288'],
                             capture_output=True, text=True, timeout=5)
        if out.returncode != 0:
            return None
        iface = json.loads(out.stdout)['interfaces'][0]
        entries = iface['traffic'].get('fiveminute', [])
        if not entries:
            return None
        rx = max(e['rx'] for e in entries) * 8 / 300 / 1e6
        tx = max(e['tx'] for e in entries) * 8 / 300 / 1e6
        return {'rx': round(rx, 1), 'tx': round(tx, 1)}
    except Exception:
        return None


def get_uplink_stats() -> Dict[str, Any]:
    """Return uplink_* fields; empty dict when there is no usable NIC."""
    global _last
    try:
        nic = _primary_nic()
        if not nic:
            return {}
        c = psutil.net_io_counters(pernic=True)[nic]
        now = time.time()
        speed = psutil.net_if_stats()[nic].speed  # Mbit/s, 0 when unknown

        rx_mbit = tx_mbit = None
        with _lock:
            if _last and _last[3] == nic and now - _last[0] >= 1:
                dt = now - _last[0]
                rx_mbit = max(0.0, (c.bytes_recv - _last[1]) * 8 / dt / 1e6)
                tx_mbit = max(0.0, (c.bytes_sent - _last[2]) * 8 / dt / 1e6)
                if not _ring or now - _ring[-1][0] >= _RING_MIN_GAP:
                    _ring.append((now, rx_mbit, tx_mbit))
            if not _last or now - _last[0] >= 1:
                _last = (now, c.bytes_recv, c.bytes_sent, nic)
            cutoff = now - 86400
            ring = [s for s in _ring if s[0] >= cutoff]

        peak = _vnstat_peak_mbit(nic)
        peak_source = 'vnstat'
        if peak is None and ring:
            peak = {'rx': round(max(s[1] for s in ring), 1), 'tx': round(max(s[2] for s in ring), 1)}
            peak_source = 'since restart'
        elif peak is None:
            peak_source = None

        stats: Dict[str, Any] = {'uplink_nic': nic, 'uplink_link_mbit': speed or None}
        if rx_mbit is not None:
            stats['uplink_rx_mbit'] = round(rx_mbit, 1)
            stats['uplink_tx_mbit'] = round(tx_mbit, 1)
        if peak:
            stats['uplink_peak_rx_mbit'] = peak['rx']
            stats['uplink_peak_tx_mbit'] = peak['tx']
            stats['uplink_peak_source'] = peak_source
        return stats
    except Exception:
        return {}
