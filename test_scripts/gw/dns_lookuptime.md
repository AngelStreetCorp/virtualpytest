# DNS Lookup Time (`dns_lookuptime`)

## Purpose

Measures DNS resolution time from the host system and stores resolver, address, and timing details in `script_results.metadata`.

## Target Environment

- Host-targeted gateway/network diagnostic.
- Runs from the host perspective, not from a browser or device UI.

## Usage

```bash
python test_scripts/gw/dns_lookuptime.py                       # system resolver (default '--dns system')
python test_scripts/gw/dns_lookuptime.py --url google.com
python test_scripts/gw/dns_lookuptime.py --url api.example.com

# Query a specific DNS server instead of the system resolver
python test_scripts/gw/dns_lookuptime.py --dns 8.8.8.8 --url api.example.com
python test_scripts/gw/dns_lookuptime.py --dns 2001:4860:4860::8888 --url api.example.com
```

## Parameters

| Parameter | Type | Default | Description |
|---|---|---|---|
| `--url` | string | `google.com` | Hostname to resolve |
| `--dns` | string | `system` | DNS server to query (e.g. `8.8.8.8` or `2001:4860:4860::8888`); the sentinel `system` (or empty) uses the host's system resolver |

> **Breaking change:** `--dns` previously meant the hostname to resolve — that role is now `--url`. Callers passing `--dns <hostname>` must switch to `--url <hostname>`.

## Behavior

1. Resolves the requested hostname from the host, optionally against the DNS server named in `--dns`.
2. Measures lookup duration in milliseconds.
3. Captures DNS server details, IPv4/IPv6 answers, CNAME, and queried domain.

## Outputs and Metadata

Main metadata fields:

| Field | Description |
|---|---|
| `lookup_time_ms` | DNS resolution duration |
| `requested_dns_server` | DNS server requested via `--dns` (`null` when using the system resolver) |
| `dns_server` | DNS server that answered (from the nslookup output) |
| `dns_server_port` | DNS server port |
| `ipv4_addresses` | Resolved IPv4 addresses |
| `ipv6_addresses` | Resolved IPv6 addresses |
| `canonical_name` | CNAME when present |
| `domain` | Domain queried |

Example:

```json
{
  "lookup_time_ms": 12.34,
  "requested_dns_server": "8.8.8.8",
  "dns_server": "8.8.8.8",
  "dns_server_port": "53",
  "domain": "google.com",
  "canonical_name": null,
  "ipv4_addresses": ["142.250.185.46"],
  "ipv6_addresses": ["2607:f8b0:4004:c07::71"]
}
```

## Dashboard

Grafana dashboards:

- `dns-lookup-time.json` - basic stats and last 100 lookup history.
- `dns-lookup-time-v2.json` - enhanced monitoring with total/failed tests, success rate, lookup-time trend, DNS server comparison, availability timeline, domain comparison, and history table.

Dashboard variables:

- `host`
- `time_range`

Thresholds:

| Metric | Green | Yellow | Orange | Red |
|---|---|---|---|---|
| Lookup time | `< 50ms` | `50-100ms` | `100-200ms` | `> 200ms` |
| Success rate | `>= 95%` | `90-95%` | `80-90%` | `< 80%` |

## Troubleshooting

- If lookup time is high, compare resolver performance in the DNS server dashboard panel.
- If lookups fail, verify the host DNS configuration and that the target domain resolves manually from the same host.

## Related Documentation

- [Superping](./superping.md)
- [Ookla Speedtest](./ookla_speedtest.md)
