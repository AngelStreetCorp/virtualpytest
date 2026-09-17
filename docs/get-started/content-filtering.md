# Content filtering for lab devices

> **Purpose**: Keep browsers, emulators and Android devices in a VirtualPyTest lab away from adult and malicious sites, so that a guest or a test never lands the lab (and its recordings) on content you do not want to store or show  
> **Audience**: System Administrators, DevOps

---

## Why

Anyone who can take control of a device can open a browser on it. Every screen a
device shows is captured, stored (screenshots, session video, heatmap, incident
evidence) and visible to everyone watching the live stream. A single visit to an
adult or malware site therefore ends up in your storage and on your dashboards.

VirtualPyTest does not inspect URLs itself, and it could not do so reliably:
a user with device control can type any address into a browser. The filter
belongs at the network layer, where every device in the lab passes through it
regardless of how the URL was entered.

## Block list or allow list?

| Approach | What it does | Use it for |
|----------|--------------|------------|
| **Block list** (recommended) | Resolve everything except known adult and malware domains, using a filtering DNS resolver | Working test labs. Apps under test talk to CDNs, analytics, auth providers, app stores and the platform's own services (Supabase, MinIO/R2, GitHub for deploys, package mirrors). An allow list breaks them one by one. |
| **Allow list** | Resolve only a short list of domains, return nothing for everything else | A locked-down showcase device that only ever needs a handful of sites. Expect to keep adding domains as the demo evolves. |

The block list is the default described below. An allow-list recipe follows for
the showcase case.

## The resolver

[Cloudflare for Families](https://one.one.one.one/family/) is a public DNS
resolver with two flavours. No account, no software, no cost:

| Flavour | IPv4 | IPv6 |
|---------|------|------|
| Malware only | `1.1.1.2`, `1.0.0.2` | `2606:4700:4700::1112`, `::1002` |
| **Malware + adult content** | `1.1.1.3`, `1.0.0.3` | `2606:4700:4700::1113`, `::1003` |

Blocked names resolve to `0.0.0.0`, so the browser shows a connection error.
Chromium and Firefox keep the filter even when they auto-upgrade to
DNS-over-HTTPS, because they upgrade to the same provider's family endpoint.

## Lab on Proxmox (one change for every VM and emulator)

In the reference layout the Proxmox node runs `dnsmasq` as the DNS forwarder for
the VM LAN (`192.168.x.1`). Every VM points at it, and Android emulators inherit
the DNS of the VM they run on, so changing its upstream filters the whole lab.

### Check first: can the node reach a public resolver over UDP?

```bash
dig +short @1.1.1.3 youtube.com        # UDP
dig +short +tcp @1.1.1.3 youtube.com   # TCP
```

Hosting providers with a stateless firewall (Hetzner's incoming firewall, for
one) drop UDP replies from external resolvers while TCP goes through. If the
first command times out and the second answers, use the **DNS-over-TLS** recipe.
If both answer, the **direct** recipe is enough.

### Recipe A: direct upstream (UDP works)

Replace the upstream servers in the dnsmasq drop-in, on the reference node
`/etc/dnsmasq.d/vm-dns.conf`:

```
interface=vmbr0
bind-interfaces
no-resolv
server=1.1.1.3
server=1.0.0.3
```

`no-resolv` matters: without it dnsmasq also uses the node's own
`/etc/resolv.conf` resolvers and spreads queries across every upstream, so an
unfiltered one keeps answering part of the time. Check every file under
`/etc/dnsmasq.d/` and `/etc/dnsmasq.conf` for other `server=` lines for the
same reason.

### Recipe B: DNS-over-TLS stub (UDP blocked) — what the reference node runs

`stubby` is a small DNS-over-TLS client. It listens on the loopback and talks
to Cloudflare for Families over TCP 853; dnsmasq forwards to it.

```bash
sudo apt-get install -y stubby
```

`/etc/stubby/stubby.yml`:

```yaml
resolution_type: GETDNS_RESOLUTION_STUB
dns_transport_list:
  - GETDNS_TRANSPORT_TLS
tls_authentication: GETDNS_AUTHENTICATION_REQUIRED
tls_query_padding_blocksize: 128
edns_client_subnet_private: 1
round_robin_upstreams: 1
idle_timeout: 10000
listen_addresses:
  - 127.0.0.1@5453
upstream_recursive_servers:
  - address_data: 1.1.1.3
    tls_auth_name: "family.cloudflare-dns.com"
  - address_data: 1.0.0.3
    tls_auth_name: "family.cloudflare-dns.com"
```

```bash
sudo systemctl enable --now stubby
dig +short @127.0.0.1 -p 5453 pornhub.com   # expect 0.0.0.0
```

`/etc/dnsmasq.d/vm-dns.conf`:

```
interface=vmbr0
bind-interfaces
no-resolv
strict-order
server=127.0.0.1#5453
server=185.12.64.2
server=185.12.64.1
```

The two extra servers are the hosting provider's resolvers, kept as a fallback
so the lab never loses DNS if stubby is down. `strict-order` makes dnsmasq try
servers in the listed order and move on only when one fails to answer. A
blocked name is a normal answer (`0.0.0.0`), so the fallback is never consulted
for it. Never list an unfiltered upstream without `strict-order`.

### Validate and verify

```bash
sudo dnsmasq --test
sudo systemctl restart dnsmasq
```

From any VM on the LAN:

```bash
dig +short pornhub.com        # expect 0.0.0.0 (blocked)
dig +short youtube.com        # expect a normal address
```

Inside an Android emulator the blocked name shows as `127.0.0.1`; that is
Android's rendering of the same answer. VMs cache nothing beyond dnsmasq's own
cache, so the change is immediate.

## Standalone box (Docker or native install on one machine)

Point the machine's resolver at the family servers. On a Debian/Ubuntu box with
`systemd-resolved`:

```bash
sudo mkdir -p /etc/systemd/resolved.conf.d
printf '[Resolve]\nDNS=1.1.1.3 1.0.0.3\nFallbackDNS=\n' | sudo tee /etc/systemd/resolved.conf.d/family.conf
sudo systemctl restart systemd-resolved
```

With NetworkManager (Raspberry Pi OS, desktop Ubuntu):

```bash
nmcli con mod "<connection name>" ipv4.dns "1.1.1.3 1.0.0.3" ipv4.ignore-auto-dns yes
nmcli con up "<connection name>"
```

Docker containers use the host's resolver by default, so nothing else changes.

## Real devices on their own network

Phones, tablets and set-top boxes connected over Wi-Fi or Ethernet resolve DNS
through whatever the network's DHCP hands out, not through the lab's VMs. Two
options:

- **Router or DHCP server**: set the DNS servers handed to clients to
  `1.1.1.3` and `1.0.0.3`. Covers every device on that network at once.
- **Per device** (Android 9+): Settings, Network, Private DNS, hostname
  `family.cloudflare-dns.com`. Overrides the network's DNS for that device only.

## Allow list for a showcase device

For a device that must only reach a fixed set of sites, run a dedicated dnsmasq
for it (or a separate Proxmox bridge) with an explicit list and a catch-all:

```
# resolve only these (and their subdomains) through the family resolver
server=/youtube.com/1.1.1.3
server=/dailymotion.com/1.1.1.3
server=/google.com/1.1.1.3
server=/facebook.com/1.1.1.3
# the platform's own services
server=/supabase.co/1.1.1.3
server=/cloudflare.com/1.1.1.3
# everything else: no answer
address=/#/0.0.0.0
```

Modern sites pull assets from many other domains (`ytimg.com`, `googlevideo.com`,
`fbcdn.net`, `gstatic.com`), so expect a few iterations with the browser's
network tab open before a page fully works. Keep this to devices that really need
it.

## What this does not cover

- **Addresses typed as raw IPs** bypass DNS. Rare for adult content, but possible.
- **VPN or proxy apps** installed on a device bypass the network's DNS. Do not
  let guests install apps on lab devices.
- **Applications with their own hard-coded DNS-over-HTTPS** (some browsers when
  configured explicitly) bypass the resolver. Cloudflare's own family DoH
  endpoint, `https://family.cloudflare-dns.com/dns-query`, can be set in the
  browser policy instead.
- **Who may take control** is a separate control. Keep external guests on the
  `viewer` role, which has no `device_control:execute` permission, and give
  demo accounts a role limited to a designated demo device. See
  `technical/permissions/`.

Content filtering reduces what a guest can put on a screen. Role restriction
reduces who can put anything on a screen at all. Use both.
