# BUG-0288 — dns_lookuptime failed hourly: hostname passed as the DNS server

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0288                                                     |
| Reported  | 2026-10-04                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium                                                       |
| Area      | test_scripts/gw                                              |
| Fixed in  | build 90145 |
| Commit    | 276cae858                                                    |

---

## Symptom

`dns_lookuptime` failed every hour on host-clone-1 from 2026-09-02 (751 failures to 2026-10-04):
first `DNS lookup timeout after 10s` (09-02..09-07), then
`nslookup: couldn't get address for 'epg.prod.ch.dmdsdp.com': not found`. It looked like our lab
DNS could not resolve the customer EPG name.

## Root cause

Not DNS. Commit f4d37923b (2026-09-02) split the script arguments: `--url` is the name to resolve,
`--dns` the server to ask (it used to be the name). The hourly deployment of campaign
"TP_001 sanity" (`:18 * * * *`) kept `--dns epg.prod.ch.dmdsdp.com`, so the script ran
`nslookup google.com epg.prod.ch.dmdsdp.com` — nslookup first has to resolve that hostname to find a
server, and fails. 275 of 330 failures since 2026-09-20 carry that exact command line.
Independently, `epg.prod.ch.dmdsdp.com` is a CNAME to `wp-5c4e730000000000.id.cdn.upcbroadband.com`
and that target is NXDOMAIN at 1.1.1.1/8.8.8.8/9.9.9.9/Hetzner and at the authoritative `ns3.cdn.upcbroadband.com`
itself, so that name is dead from our lab whatever the resolver.

## Fix

- The deployment's step parameters were set to `dns: system` (resolves `google.com` through the lab
  resolver; passing again since 2026-10-04 08:18 UTC).
- `test_scripts/gw/dns_lookuptime.py`: `validate_dns_server()` rejects a non-IP `--dns` up front with
  "Invalid --dns ... use --url <hostname>" instead of the misleading nslookup error.
- Test: `tests/test_scripts/test_dns_lookuptime_args.py`.

## Verification

`pytest tests/test_scripts/test_dns_lookuptime_args.py`; `script_results` rows with
`metadata.parameters` = `--dns system ...` succeed; a run with `--dns <hostname>` fails with the
"Invalid --dns" message.
