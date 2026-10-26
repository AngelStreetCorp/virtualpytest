# Content filtering for lab devices

Keep browsers, emulators and Android devices in the lab away from adult and malicious sites.

<div data-technical>

> **Purpose**: Keep browsers, emulators and Android devices in a VirtualPyTest lab away from adult and malicious sites, so that a guest or a test never lands the lab (and its recordings) on content you do not want to store or show  
> **Audience**: System Administrators, DevOps

</div>

---

## Why

Anyone who can control a device can open a browser on it, and every screen is captured and stored.
VirtualPyTest cannot reliably check URLs itself, so the filter sits in the network, where every device
passes through it.

## Block list or allow list?

| Approach | What it does | Use it for |
|----------|--------------|------------|
| **Block list** (recommended) | Allows everything except known adult and malware sites | Working test labs. Apps under test need CDNs, analytics, login providers, app stores and the platform's own services. An allow list breaks them one by one. |
| **Allow list** | Allows only a short list of sites, and blocks everything else | A locked-down showcase device that only ever needs a handful of sites. You keep adding sites as the demo changes. |

The block list is the default. An allow-list recipe is at the end, for showcase devices.

## The resolver

We use [Cloudflare for Families](https://one.one.one.one/family/): a free public DNS service, with no
account or software needed.

- **Malware only:** blocks malware sites.
- **Malware and adult content:** blocks malware and adult sites. Use this one.

Blocked sites show a connection error.

<div data-technical>

| Level | IPv4 | IPv6 |
|-------|------|------|
| Malware only | `1.1.1.2`, `1.0.0.2` | `2606:4700:4700::1112`, `::1002` |
| **Malware + adult content** | `1.1.1.3`, `1.0.0.3` | `2606:4700:4700::1113`, `::1003` |

Blocked names resolve to `0.0.0.0`, so the browser shows a connection error. Chromium and Firefox keep
the filter even when they switch to DNS-over-HTTPS, because they use the same provider's family endpoint.

</div>

## Lab on Proxmox (one change for every VM and emulator)

On Proxmox, one small DNS forwarder serves every VM and emulator, so one change filters the whole lab.

<div data-technical>

The forwarder is `dnsmasq`, listening on `192.168.x.1` for the VM LAN. Android emulators inherit the
DNS of their VM, so changing its upstream filters the whole lab.

</div>

### Check first: can the node reach a public resolver over UDP?

Some hosting providers block UDP replies from outside resolvers. Test both before you choose a recipe.

<div data-technical>

```bash
dig +short @1.1.1.3 youtube.com        # UDP
dig +short +tcp @1.1.1.3 youtube.com   # TCP
```

Hosting providers with a stateless firewall (Hetzner's incoming firewall, for one) drop UDP replies
from external resolvers while TCP goes through. If the first command times out and the second answers,
use the **DNS-over-TLS** recipe. If both answer, the **direct** recipe is enough.

</div>

If UDP works, use the direct recipe. If it does not, use the DNS-over-TLS recipe. Both are below.

### Recipe A: direct upstream (UDP works)

Point the forwarder at the family resolver.

<div data-technical>

Replace the upstream servers in the dnsmasq drop-in, on the reference node `/etc/dnsmasq.d/vm-dns.conf`:

```
interface=vmbr0
bind-interfaces
no-resolv
server=1.1.1.3
server=1.0.0.3
```

`no-resolv` matters. Without it, dnsmasq also uses the node's own `/etc/resolv.conf` resolvers and spreads
queries across every upstream, so an unfiltered one answers part of the time. Check every file under
`/etc/dnsmasq.d/` and `/etc/dnsmasq.conf` for other `server=` lines for the same reason.

</div>

### Recipe B: DNS-over-TLS stub (UDP blocked, what the reference node runs)

A small client, `stubby`, sends encrypted queries to the family resolver. The forwarder uses it.

<div data-technical>

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

The two extra servers are the hosting provider's resolvers. They are a fallback, so the lab keeps DNS
if `stubby` is down. `strict-order` makes dnsmasq try the servers in the listed order, and move on only
when one fails to answer. A blocked name is a normal answer (`0.0.0.0`), so the fallback is never used
for it. Never list an unfiltered upstream without `strict-order`.

</div>

### Validate and verify

Restart the forwarder, then test from any VM. A blocked site should not resolve; a normal site should.

<div data-technical>

```bash
sudo dnsmasq --test
sudo systemctl restart dnsmasq
```

From any VM on the LAN:

```bash
dig +short pornhub.com        # expect 0.0.0.0 (blocked)
dig +short youtube.com        # expect a normal address
```

</div>

Inside an Android emulator, a blocked site shows as `127.0.0.1`. The change takes effect at once.

## Standalone box (Docker or native install on one machine)

On a single machine, set its own DNS to the family resolver.

<div data-technical>

On a Debian or Ubuntu box with `systemd-resolved`:

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

</div>

## Real devices on their own network

Phones, tablets and set-top boxes get their DNS from the network router, not from the lab's VMs. Either:

- **Router or DHCP server:** give clients the family resolver. This covers the whole network.
- **One Android 9 device or newer:** set Private DNS to the family hostname.


<div data-technical>

The router or DHCP server hands out `1.1.1.3` and `1.0.0.3`. For a single Android device: Settings,
Network, Private DNS, hostname `family.cloudflare-dns.com`.

</div>

## Allow list for a showcase device

For a device that must reach only a fixed set of sites, run a separate forwarder that resolves only
the sites you list. Expect a few rounds of adding domains before a page fully works.

<div data-technical>

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

Modern sites pull assets from many other domains (`ytimg.com`, `googlevideo.com`, `fbcdn.net`,
`gstatic.com`). Add them as you find them in the browser's network tab.

</div>

## What this does not cover

Filtering DNS is strong, but a few routes go around it:

- **Raw IP addresses** skip DNS.
- **VPN or proxy apps** on a device skip the network's DNS. Do not let guests install apps on lab devices.
- **Browsers with their own DNS-over-HTTPS** can skip the resolver. Set the family endpoint in the browser policy.
- **Who may take control** is a separate control. Keep external guests on the viewer role, and give demo accounts a role limited to one demo device.

<div data-technical>

Specifically: applications with hard-coded DNS-over-HTTPS bypass the resolver. Cloudflare's family DoH
endpoint, `https://family.cloudflare-dns.com/dns-query`, can be set in the browser policy. Viewers have no
`device_control:execute` permission. See `technical/permissions/`.

</div>

Content filtering reduces what a guest can put on a screen. Role restriction reduces who can put
anything on a screen at all. Use both.
