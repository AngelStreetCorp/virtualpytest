# VirtualPyTest Network Architecture

## Network Topology

```
┌─────────────────────────────────────────────────────────────┐
│                    Proxmox Host                              │
│                                                              │
│  ┌─────────────┐                          ┌──────────────┐  │
│  │  enp41s0    │ ← Public IP              │    vmbr0     │  │
│  │ (Physical)  │   <origin-ip>          │  (Virtual)   │  │
│  │             │                          │ 192.168.x.1  │  │
│  └──────┬──────┘                          └──────┬───────┘  │
│         │                                        │          │
│         │  NAT (MASQUERADE)                      │          │
│         │  iptables translates IPs               │          │
│         │  192.168.0.x → Public IP               │          │
│         └────────────────────────────────────────┘          │
│                                                              │
│         Virtual Network 192.168.x.0/24                      │
│         ┌──────┬──────┬──────┬──────┬──────┐               │
│         │      │      │      │      │      │               │
└─────────┼──────┼──────┼──────┼──────┼──────┼───────────────┘
          │      │      │      │      │      │
       ┌──▼──┐ ┌─▼───┐ ┌▼────┐ ┌▼───┐ ┌▼───┐ ┌▼────┐
       │ VM  │ │ VM  │ │ VM  │ │VM  │ │VM  │ │ VM  │
       │.140+│ │.10  │ │.11  │ │.12 │ │.13 │ │.15  │
       │Host │ │Stor-│ │Proxy│ │DB  │ │Back│ │Front│
       └─────┘ │age │ └─────┘ └────┘ └────┘ └─────┘
               └─────┘
```

## Two-Layer Network Configuration

### Layer 1: Proxmox Host (Hardware Level)

**Configuration Location**: Proxmox host `/etc/network/interfaces`

```bash
# Physical interface - public internet
auto enp41s0
iface enp41s0 inet static
    address YOUR_PUBLIC_IP/26
    gateway YOUR_GATEWAY

# Virtual bridge - private VM network
auto vmbr0
iface vmbr0 inet static
    address 192.168.x.1/24
    bridge-ports none              # Purely virtual, no physical ports
    bridge-stp off
    bridge-fd 0

# Enable NAT for VMs
iptables -t nat -A POSTROUTING -s '192.168.x.0/24' -o enp41s0 -j MASQUERADE
```

**What this does:**
- Creates virtual switch (vmbr0) for VMs
- Provides gateway at 192.168.x.1
- NAT translates VM IPs to public IP

### Layer 2: VM Guest OS (Software Level)

**Configuration Location**: Inside each VM `/etc/network/interfaces`

```bash
# Example: Storage VM (192.168.x.100)
auto ens18
iface ens18 inet static
    address 192.168.x.100
    netmask 255.255.255.0
    gateway 192.168.x.1           # Points to Proxmox vmbr0
    dns-nameservers 192.168.x.1   # Proxmox host runs dnsmasq DNS forwarder
```

**What this does:**
- Tells VM's OS its IP address
- Configures gateway for internet access
- Sets DNS for name resolution

**⚠️ Critical**: Each VM needs its own network configuration inside the guest OS. Proxmox only provides the virtual network card, not the IP configuration.

## VM IP Assignments

| VM | IP Address | Purpose | External Access |
|----|------------|---------|-----------------|
| **Proxmox Host** | 192.168.x.1 | Gateway | - |
| Reverse Proxy | 192.168.x.107 | Nginx SSL proxy | ✅ Ports 80/443 |
| Storage | 192.168.x.100 | NFS, MinIO, Redis | ❌ Internal only |
| Database | 192.168.x.102 | PostgreSQL (5432)<br/>Supabase API (54321)<br/>Supabase Studio (54323) | ❌ Internal only<br/>✅ Via reverse proxy |
| Backend Server | 192.168.x.103 | Flask API | ❌ Internal only |
| Frontend | 192.168.x.105 | React UI | ❌ Internal only |
| Monitoring | 192.168.x.106 | Grafana, InfluxDB | ❌ Internal only |
| Host VMs | 192.168.x.140+ | Device control | ❌ Internal only |

## Traffic Flow Examples

### VM to Internet (e.g., apt update)
```
VM (192.168.x.100) → vmbr0 (192.168.x.1) → NAT translation → 
enp41s0 (PUBLIC_IP) → Internet
```

### Internet to Service (e.g., web browser)
```
Internet → enp41s0 (PUBLIC_IP) → Port Forward (80/443) → 
Reverse Proxy (192.168.x.107) → Internal VMs

Examples:
  /              → Frontend (192.168.x.105:5073)
  /server/       → Backend Server (192.168.x.103:5109)
  /grafana/      → Monitoring (192.168.x.106:3000)
  /supabase/     → Database VM Supabase Studio (192.168.x.102:54323)
```

### VM to VM (e.g., API call)
```
Frontend (192.168.x.105) → vmbr0 → Backend (192.168.x.103)
```

## Security Strategy

### Defense Layers
1. **Proxmox NAT**: VMs hidden behind single public IP
2. **Reverse Proxy**: Only entry point for external traffic (ports 80/443)
3. **Firewall Rules**: Block all except required ports
4. **VM Isolation**: Internal network separate from internet

### Port Forwarding (Proxmox Host)
```bash
# Only reverse proxy is exposed
iptables -t nat -A PREROUTING -i enp41s0 -p tcp --dport 80 -j DNAT --to 192.168.x.107:80
iptables -t nat -A PREROUTING -i enp41s0 -p tcp --dport 443 -j DNAT --to 192.168.x.107:443
```

## Quick Troubleshooting

### VM cannot ping 8.8.8.8
1. **Check Proxmox vmbr0**: `ip addr show vmbr0` (should have 192.168.x.1)
2. **Check NAT rules**: `iptables -t nat -L -n -v` (MASQUERADE should exist)
3. **Check IP forwarding**: `sysctl net.ipv4.ip_forward` (should be 1)
4. **Check VM network config**: Inside VM, run `ip addr show` (should have 192.168.0.x)
5. **Check VM gateway**: Inside VM, run `ip route show` (default via 192.168.x.1)

### VM cannot SSH from Proxmox
1. **Ping test**: From Proxmox, `ping 192.168.x.100`
2. **Check VM firewall**: In Proxmox UI, disable VM firewall
3. **Check SSH service**: In VM console, `systemctl status ssh`

### VM cannot resolve domain names (ping google.com fails)
1. **Check DNS config**: `cat /etc/resolv.conf` (should have `nameserver 192.168.x.1`)
2. **Check dnsmasq on Proxmox**: `systemctl status dnsmasq` (should be active)
3. **Fix if wrong**: `echo "nameserver 192.168.x.1" > /etc/resolv.conf`

---

**Key Concept**: Proxmox provides the network infrastructure (virtual switch). Each VM must configure its own network settings inside the guest OS.