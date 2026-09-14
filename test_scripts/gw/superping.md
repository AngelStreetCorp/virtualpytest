# Superping (`superping`)

## Purpose

Measures network quality and reachability to a target endpoint using ping-style probes plus traceroute/path analysis.

## Target Environment

- Host-targeted network diagnostic.
- Runs from the host perspective. Defaults to IPv4; pass `--ip_version 6` for IPv6.
- Supports ICMP, TCP, and UDP probes.
- Requires system `ping`; traceroute features require system `traceroute`.

## Usage

```bash
python test_scripts/gw/superping.py
python test_scripts/gw/superping.py --target youtube.com:443 --protocol tcp
python test_scripts/gw/superping.py --target 8.8.8.8 --protocol icmp
python test_scripts/gw/superping.py --target google.com --count 20
python test_scripts/gw/superping.py --target google.com --interface auto
python test_scripts/gw/superping.py --target google.com --interface ens19
python test_scripts/gw/superping.py --target google.com --ip_version 6
python test_scripts/gw/superping.py --target "[2001:4860:4860::8888]:443" --protocol tcp --ip_version 6

python test_scripts/gw/superping.py \
  --target example.com:443 \
  --protocol tcp \
  --count 10 \
  --max_hops 10
```

## Parameters

| Parameter | Type | Default | Description |
|---|---|---|---|
| `--target` | string | `google.com` | Target hostname/IP, optionally with `:port` (use `[addr]:port` for IPv6 literals) |
| `--protocol` | string | `icmp` | `icmp`, `tcp`, or `udp` |
| `--count` | int | `5` | Number of ping/probe attempts |
| `--max_hops` | int | `255` | Maximum traceroute hops |
| `--interface` | string | `auto` | Network interface for probes, or `auto` for connectivity-based selection (IPv4 only) |
| `--ip_version` | int | `4` | IP version: `4` (default) or `6` |

## Behavior

1. Resolves the target hostname and port for the requested `--ip_version`.
2. Selects an interface (IPv4 only):
   - `auto` checks the default-route interface first, then other IPv4 interfaces, and selects the first interface that can ping `8.8.8.8`.
   - An explicit interface is validated before the main test and fails early if it has no internet connectivity.
   - For IPv6 runs the pre-check is skipped; an explicit `--interface` is passed to `ping`/`traceroute` without source-IP binding.
3. Runs the selected protocol probe:
   - ICMP for general network latency.
   - TCP for service availability through firewalls and web/API targets.
   - UDP for UDP/streaming/policy checks.
4. Runs traceroute/path analysis using the same IP version and interface selection.
5. Computes score, status, RTT, jitter, loss, hops, and execution durations.

## Outputs and Metadata

Core metrics:

| Field | Description |
|---|---|
| `superping_score` | Quality score from `0-100` |
| `service_reachability` | Whether the target is reachable |
| `status` / `status_label` | `EXCELLENT`, `GOOD`, `DEGRADED`, `POOR`, or `DOWN` |
| `rtt_min_ms`, `rtt_avg_ms`, `rtt_max_ms` | RTT statistics |
| `rtt_values_ms` | Individual RTT samples |
| `jitter_ms` | RTT variation |
| `packets_transmitted`, `packets_received` | Packet counters |
| `packet_loss_percent` | Packet loss percentage |
| `hop_count`, `hops` | Traceroute path data |
| `ping_duration_seconds`, `trace_duration_seconds`, `total_duration_seconds` | Timing breakdown |
| `interface_selection`, `interface_used`, `interface_attempts` | Interface selection details |

Example metadata:

```json
{
  "target": "youtube.com:443",
  "hostname": "youtube.com",
  "ip": "142.250.190.78",
  "port": 443,
  "protocol": "tcp",
  "ip_version": 4,
  "interface_selection": "auto",
  "interface_used": "ens19",
  "superping_score": 87.3,
  "service_reachability": true,
  "status": "EXCELLENT",
  "rtt_min_ms": 23.45,
  "rtt_avg_ms": 25.67,
  "rtt_max_ms": 28.9,
  "rtt_values_ms": [23.45, 24.12, 25.67, 26.89, 28.9],
  "jitter_ms": 2.12,
  "packets_transmitted": 5,
  "packets_received": 5,
  "packet_loss_percent": 0.0,
  "hop_count": 12,
  "total_duration_seconds": 3.45
}
```

Score calculation:

```text
Starting score: 100
- packet loss: up to -40 points
- high RTT: up to -30 points
- high jitter: up to -20 points
- long path: up to -10 points
```

Interpretation:

| Score | Status | Meaning |
|---|---|---|
| `80-100` | `EXCELLENT` | Optimal network quality |
| `60-79` | `GOOD` | Good quality, minor issues |
| `40-59` | `DEGRADED` | Network degradation detected |
| `0-39` | `POOR` | Severe network issues |
| N/A | `DOWN` | Service unreachable |

Good indicators: score `> 80`, packet loss `< 1%`, RTT `< 50ms`, jitter `< 10ms`, and stable hop count.

Critical indicators: score `< 60`, packet loss `> 5%`, RTT `> 200ms`, jitter `> 50ms`, or service unreachable.

## Dashboard

Grafana dashboards:

- V1 UID: `superping-dashboard`, URL `/grafana/d/superping-dashboard/superping-network-quality`.
- V2 UID: `superping-dashboard-v2`, URL `/grafana/d/superping-dashboard-v2/superping-network-quality-v2`.

V2 dashboard includes:

- Total tests, failed tests, average score, success rate, packet loss, service reachable, and round-trip delay.
- RTT min/avg/max, jitter, loss, and score stats with trends.
- Time series for score, packet loss, RTT, jitter, and round-trip delay.
- Recent tests table with score/loss/RTT/success coloring.
- Latest traceroute hops table.
- Service availability timeline.
- Target performance comparison by host/target.

Variables:

- Host filter.
- Target filter.
- Time range.

## Troubleshooting

### `traceroute command not found`

Install traceroute:

```bash
sudo apt-get update && sudo apt-get install traceroute
```

Other platforms:

```bash
sudo yum install traceroute
sudo dnf install traceroute
```

macOS includes traceroute by default.

### Permission denied

Some ICMP/TCP traceroute modes may need elevated privileges:

```bash
sudo python test_scripts/gw/superping.py --target google.com
```

### High UDP packet loss

Many services do not respond to UDP probes. Compare with TCP or ICMP before treating UDP loss as a network fault.

### Traceroute shows `* * *`

Some routers do not respond to traceroute probes. This is normal if the final target is reachable.

### Timeout issues

Use a closer target or smaller count for quick checks:

```bash
python test_scripts/gw/superping.py --target 8.8.8.8 --count 3
```

## Related Documentation

- [DNS Lookup Time](./dns_lookuptime.md)
- [Ookla Speedtest](./ookla_speedtest.md)
