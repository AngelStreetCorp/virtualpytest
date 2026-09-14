# Ookla Speedtest (`ookla_speedtest`)

## Purpose

Measures internet download/upload bandwidth, latency, jitter, packet loss, server details, ISP details, and interface selection using Ookla Speedtest CLI.

## Target Environment

- Host-targeted network diagnostic.
- Runs from the host perspective.
- Requires Ookla Speedtest CLI for full metrics. Python `speedtest-cli` fallback may provide limited metrics.

## Usage

```bash
# Automatic server and connectivity-based interface selection
python test_scripts/gw/ookla_speedtest.py

# Specific server
python test_scripts/gw/ookla_speedtest.py --server 12345

# Specific interface
python test_scripts/gw/ookla_speedtest.py --interface eth0

# Specific server and interface
python test_scripts/gw/ookla_speedtest.py --server 12345 --interface wlan0

# Compare servers on the same interface
python test_scripts/gw/ookla_speedtest.py --server 12345 --interface eth0
python test_scripts/gw/ookla_speedtest.py --server 67890 --interface eth0

# List available Ookla servers
speedtest --servers
```

## Parameters

| Parameter | Type | Default | Description |
|---|---|---|---|
| `--server` | string | `auto` | Ookla server ID or `auto` for automatic selection |
| `--interface` | string | `auto` | Interface name or `auto` for connectivity-based selection |

## Behavior

1. Selects an interface:
   - `auto` tries the default-route interface first, then other IPv4 interfaces, and selects the first interface that can ping `8.8.8.8`.
   - Explicit interfaces are validated before running Speedtest.
2. Finds the Speedtest executable.
3. Runs Speedtest with JSON output and license/GDPR acceptance flags.
4. Parses bandwidth, latency, jitter, packet loss, server, ISP, external IP, result URL, duration, and interface details.

Common interface names:

- Linux Ethernet: `eth0`, `eth1`
- Linux Wi-Fi: `wlan0`, `wlp2s0`
- macOS: `en0`, `en1`
- Windows: `Ethernet`, `Wi-Fi`

## Outputs and Metadata

Core metadata:

| Field | Description |
|---|---|
| `download_mbps`, `upload_mbps` | Download and upload bandwidth |
| `ping_latency_ms`, `ping_jitter_ms` | Idle ping latency and jitter |
| `download_latency_ms`, `upload_latency_ms` | Latency during download/upload tests |
| `packet_loss_percent` | Packet loss percentage |
| `server_id`, `server_name`, `server_location`, `server_country`, `server_host`, `server_sponsor` | Server details |
| `server_selection` | Requested server parameter |
| `result_url`, `result_id` | Speedtest result reference |
| `isp`, `external_ip` | Network/provider details |
| `interface_name`, `interface_selection`, `interface_used`, `interface_attempts` | Interface details |
| `duration_seconds` | Test duration |

Example metadata:

```json
{
  "timestamp": "2026-02-16T12:00:00Z",
  "host_name": "host1",
  "download_mbps": 245.67,
  "upload_mbps": 89.12,
  "ping_latency_ms": 12.34,
  "ping_jitter_ms": 1.23,
  "download_latency_ms": 11.45,
  "upload_latency_ms": 13.67,
  "packet_loss_percent": 0,
  "server_id": 12345,
  "server_name": "Server Name",
  "server_location": "City, Country",
  "server_country": "Country",
  "server_host": "speedtest.example.com",
  "server_sponsor": "Server Name",
  "server_selection": "auto",
  "result_url": "https://www.speedtest.net/result/xxxxx",
  "result_id": "xxxxx",
  "isp": "Your ISP Name",
  "external_ip": "123.45.67.89",
  "interface_selection": "auto",
  "interface_used": "eth0",
  "duration_seconds": 15.23
}
```

Interpretation:

- Good: plan-matching download/upload speed, ping `< 50ms`, jitter `< 10ms`, packet loss `< 1%`, consistent results.
- Warning: speed `50-80%` of plan, latency `50-100ms`, jitter `10-50ms`, packet loss `1-5%`, or highly variable results.
- Critical: speed `< 50%` of plan, latency `> 100ms`, jitter `> 50ms`, packet loss `> 5%`, or repeated test failures.

## Dashboard

Grafana dashboard:

- UID: `ookla-speedtest-v2`
- URL: `/grafana/d/ookla-speedtest-v2/ookla-speedtest`

Dashboard content:

- Total tests, failed tests, download performance, upload performance, success rate, latency, jitter, packet loss.
- Time series for download, upload, packet loss, and latency.
- Server results table with timestamp, server ID/name/location, speeds, latency, jitter, loss, result URL, and color-coded cells.
- Server performance comparison with tests, failures, success rate, average speeds, average latency/jitter/loss, and source hosts.

Variables:

- Host filter.
- Server filter.
- Time range.

## Troubleshooting

### Network unreachable or connect timeout

Speedtest servers may be blocked by firewall or network restrictions. Verify:

```bash
curl -I https://www.speedtest.net
speedtest --accept-license --accept-gdpr
nslookup speedtest.net
ping 8.8.8.8
```

Try a different server with `--server <id>`.

### `speedtest command not found`

Install Ookla Speedtest CLI.

Debian/Ubuntu:

```bash
curl -s https://packagecloud.io/install/repositories/ookla/speedtest-cli/script.deb.sh | sudo bash
sudo apt-get install speedtest
```

Fedora/CentOS/RHEL:

```bash
curl -s https://packagecloud.io/install/repositories/ookla/speedtest-cli/script.rpm.sh | sudo bash
sudo yum install speedtest
```

macOS:

```bash
brew tap teamookla/speedtest
brew install speedtest
```

Direct download:

- `https://www.speedtest.net/apps/cli`

### Python `speedtest-cli` fallback

If the script detects Python `speedtest-cli`, it may still run, but jitter, packet loss, and server detail metrics can be limited. Install official Ookla CLI for full results.

### Test returns `0.0 Mbps`

Check the internet connection, Speedtest CLI version, firewall rules, server reachability, and stderr logs.

### Test times out

Try a different server, check congestion, and verify Speedtest works manually.

### Failed to parse output

Update the Speedtest CLI and verify JSON output manually:

```bash
speedtest --format=json
```

## Prerequisites

Ookla Speedtest requires outbound TCP connectivity:

- TCP `80`, `443`, and `8080`.
- TCP `5000-65000` for individual Speedtest servers when using broad auto-selection.

Example UFW rules:

```bash
sudo ufw allow out to any port 80
sudo ufw allow out to any port 443
sudo ufw allow out to any port 8080
sudo ufw allow out 5000:65000/tcp
```

To restrict exposure, use fixed server IDs and whitelist the actual server IP/port discovered from firewall logs.

## Related Documentation

- [Superping](./superping.md)
- [DNS Lookup Time](./dns_lookuptime.md)
