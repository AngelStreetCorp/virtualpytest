# VirtualPyTest Proxmox Firewall Configuration

This guide explains how to configure firewall rules at the Proxmox level for VirtualPyTest VMs. Firewall management is centralized at the hypervisor level for better security, monitoring, and management.

## Overview

VirtualPyTest uses a **zone-based security model** with Proxmox firewall:

- **External Zone**: Proxmox host interface (internet-facing)
- **Internal Zone**: VM network (192.168.x.0/24) - trusted communication
- **DMZ Zone**: Reverse proxy VM (192.168.x.107) - controlled external access

## Prerequisites

- Proxmox VE with firewall enabled
- VirtualPyTest VMs created and assigned to bridge network
- VM IP addresses assigned (192.168.x.100-192.168.x.106, 192.168.x.140+)

## Enable Proxmox Firewall

### 1. Enable Firewall Globally
```
# Access Proxmox web interface
# Navigate to: Datacenter → Firewall → Options
# Set "Firewall" to "Yes"
```

### 2. Enable Firewall on Network Bridge
```
# Navigate to: Proxmox Host → Network → vmbr0
# Set "Firewall" to "Yes"
```

## Security Zones Configuration

### External Zone (Proxmox Host)

**Purpose**: Protect the Proxmox host itself and allow management access.

**Rules** (applied to vmbr0 interface):
```
# Allow SSH from management networks only
IN SSH(ACCEPT) -i vmbr0 -source 192.168.1.0/24,10.0.0.0/8 -log nolog

# Allow Proxmox web interface from management networks
IN Proxmox Web(ACCEPT) -i vmbr0 -source 192.168.1.0/24,10.0.0.0/8 -log nolog

# Allow ICMP (ping) for troubleshooting
IN Ping(ACCEPT) -i vmbr0 -log nolog

# Drop all other inbound traffic
IN DROP -i vmbr0 -log nolog
```

### Internal Zone (192.168.x.0/24)

**Purpose**: Allow trusted communication between VirtualPyTest VMs.

**Rules** (applied to vmbr0 interface):
```
# Allow all traffic between VMs in the internal network
IN ACCEPT -i vmbr0 -source 192.168.x.0/24 -dest 192.168.x.0/24 -log nolog

# Allow DHCP from VMs
IN DHCP(ACCEPT) -i vmbr0 -source 192.168.x.0/24 -log nolog
```

### DMZ Zone (Reverse Proxy VM - 192.168.x.107)

**Purpose**: Control external access to VirtualPyTest services through the reverse proxy.

**VM-Specific Rules** (applied to VM 192.168.x.107):
```
# Allow HTTP and HTTPS from anywhere
IN HTTP(ACCEPT) -dest 192.168.x.107 -log nolog
IN HTTPS(ACCEPT) -dest 192.168.x.107 -log nolog

# Allow SSH from management networks only
IN SSH(ACCEPT) -dest 192.168.x.107 -source 192.168.1.0/24,10.0.0.0/8 -log nolog

# Allow ICMP for troubleshooting
IN Ping(ACCEPT) -dest 192.168.x.107 -log nolog
```

## VM-Specific Firewall Rules

### Storage VM (192.168.x.100)

**Required Ports** (internal network access only):
```
# NFS Server
IN NFS_TCP(ACCEPT) -dest 192.168.x.100 -source 192.168.x.0/24 -dport 2049 -log nolog
IN NFS_UDP(ACCEPT) -dest 192.168.x.100 -source 192.168.x.0/24 -dport 2049 -log nolog
IN RPC_TCP(ACCEPT) -dest 192.168.x.100 -source 192.168.x.0/24 -dport 111 -log nolog
IN RPC_UDP(ACCEPT) -dest 192.168.x.100 -source 192.168.x.0/24 -dport 111 -log nolog

# Redis Cache
IN Redis(ACCEPT) -dest 192.168.x.100 -source 192.168.x.0/24 -dport 6379 -log nolog

# MinIO S3 Storage
IN MinIO_API(ACCEPT) -dest 192.168.x.100 -source 192.168.x.0/24 -dport 9000 -log nolog
IN MinIO_UI(ACCEPT) -dest 192.168.x.100 -source 192.168.x.0/24 -dport 9001 -log nolog

# Block all other inbound traffic
IN DROP -dest 192.168.x.100 -log nolog
```

### Database VM (192.168.x.102)

**Required Ports** (internal network access only):
```
# PostgreSQL Database
IN PostgreSQL(ACCEPT) -dest 192.168.x.102 -source 192.168.x.0/24 -dport 5432 -log nolog

# Supabase API
IN Supabase_API(ACCEPT) -dest 192.168.x.102 -source 192.168.x.0/24 -dport 54321 -log nolog

# Supabase Studio UI
IN Supabase_UI(ACCEPT) -dest 192.168.x.102 -source 192.168.x.0/24 -dport 54322 -log nolog

# Block all other inbound traffic
IN DROP -dest 192.168.x.102 -log nolog
```

### Backend Server VM (192.168.x.103)

**Required Ports** (internal network access only):
```
# Flask API Server
IN Backend_API(ACCEPT) -dest 192.168.x.103 -source 192.168.x.0/24 -dport 5109 -log nolog

# Block all other inbound traffic
IN DROP -dest 192.168.x.103 -log nolog
```

### Backend Host VMs (192.168.x.140+)

**Required Ports** (internal network access only):
```
# Backend Host API (each VM gets unique IP)
IN Host_API(ACCEPT) -dest 192.168.x.140 -source 192.168.x.0/24 -dport 6109 -log nolog
IN Host_API(ACCEPT) -dest 192.168.x.141 -source 192.168.x.0/24 -dport 6109 -log nolog
IN Host_API(ACCEPT) -dest 192.168.x.142 -source 192.168.x.0/24 -dport 6109 -log nolog
# Add more rules for additional host VMs...

# VNC Remote Desktop (each VM gets unique IP)
IN VNC(ACCEPT) -dest 192.168.x.140 -source 192.168.x.0/24 -dport 5901 -log nolog
IN VNC(ACCEPT) -dest 192.168.x.141 -source 192.168.x.0/24 -dport 5901 -log nolog
IN VNC(ACCEPT) -dest 192.168.x.142 -source 192.168.x.0/24 -dport 5901 -log nolog
# Add more rules for additional host VMs...

# noVNC Web Interface (each VM gets unique IP)
IN noVNC(ACCEPT) -dest 192.168.x.140 -source 192.168.x.0/24 -dport 6080 -log nolog
IN noVNC(ACCEPT) -dest 192.168.x.141 -source 192.168.x.0/24 -dport 6080 -log nolog
IN noVNC(ACCEPT) -dest 192.168.x.142 -source 192.168.x.0/24 -dport 6080 -log nolog
# Add more rules for additional host VMs...

# Block all other inbound traffic
IN DROP -dest 192.168.x.140 -log nolog
IN DROP -dest 192.168.x.141 -log nolog
IN DROP -dest 192.168.x.142 -log nolog
# Add DROP rules for additional host VMs...
```

### Frontend VM (192.168.x.105)

**Required Ports** (internal network access only):
```
# Frontend Production Server
IN Frontend(ACCEPT) -dest 192.168.x.105 -source 192.168.x.0/24 -dport 5073 -log nolog

# Block all other inbound traffic
IN DROP -dest 192.168.x.105 -log nolog
```

### Monitoring VM (192.168.x.106)

**Required Ports** (internal network access only):
```
# Grafana Dashboard
IN Grafana(ACCEPT) -dest 192.168.x.106 -source 192.168.x.0/24 -dport 3000 -log nolog

# InfluxDB API
IN InfluxDB_API(ACCEPT) -dest 192.168.x.106 -source 192.168.x.0/24 -dport 8086 -log nolog

# InfluxDB Admin
IN InfluxDB_Admin(ACCEPT) -dest 192.168.x.106 -source 192.168.x.0/24 -dport 8088 -log nolog

# Block all other inbound traffic
IN DROP -dest 192.168.x.106 -log nolog
```

## Firewall Rule Templates

### Create Reusable Security Groups

**Proxmox allows creating security groups for reusable rules:**

1. **Navigate to**: Datacenter → Firewall → Security Group
2. **Create groups for common patterns**:
   - `internal-services`: Rules for internal VM communication
   - `external-access`: Rules for internet-facing services
   - `management-access`: Rules for SSH and admin access

### Example Security Group: internal-services
```
# Allow common internal service ports
IN ACCEPT -dport 2049 -log nolog  # NFS
IN ACCEPT -dport 5432 -log nolog  # PostgreSQL
IN ACCEPT -dport 6379 -log nolog  # Redis
IN ACCEPT -dport 9000 -log nolog  # MinIO
IN ACCEPT -dport 3000 -log nolog  # Grafana
```

## Implementation Steps

### Step 1: Configure Global Firewall
1. Enable firewall at datacenter level
2. Enable firewall on network bridge (vmbr0)
3. Create security groups for common rules

### Step 2: Configure External Zone
1. Apply restrictive rules to vmbr0 interface
2. Allow only necessary management access
3. Enable logging for security monitoring

### Step 3: Configure Internal Zone
1. Allow full communication within 192.168.x.0/24
2. Ensure DHCP works for VM IP assignment
3. Allow ICMP for network troubleshooting

### Step 4: Configure VM-Specific Rules
1. Apply rules to each VM's virtual network interface
2. Use IP-specific rules for precise control
3. Include DROP rules to block unwanted traffic

### Step 5: Test Configuration
1. Verify VM connectivity within the network
2. Test external access through reverse proxy
3. Check firewall logs for blocked traffic
4. Validate service accessibility

## Monitoring and Maintenance

### View Firewall Logs
```
# Access Proxmox web interface
# Navigate to: Datacenter → Firewall → Log
# Monitor blocked connections and security events
```

### Update Rules
- **Regular Review**: Audit firewall rules quarterly
- **Change Management**: Document all rule changes
- **Backup**: Firewall configuration is included in Proxmox backups

### Troubleshooting
- **Check Rule Order**: Rules are processed top-to-bottom
- **Verify IP Addresses**: Ensure VM IPs match firewall rules
- **Test Connectivity**: Use `telnet` or `nc` to test port accessibility
- **Review Logs**: Check firewall logs for blocked connections

## Security Best Practices

1. **Principle of Least Privilege**: Only open required ports
2. **Network Segmentation**: Keep internal and external traffic separate
3. **Regular Audits**: Review firewall rules and logs regularly
4. **Fail-Safe Defaults**: Drop traffic by default, allow explicitly
5. **Logging**: Enable logging for security monitoring
6. **Backup Rules**: Include firewall config in regular backups

## Quick Reference

| VM | IP | Required Ports | Access Level |
|----|----|----------------|--------------|
| Storage | 192.168.x.100 | 2049, 6379, 9000, 9001 | Internal |
| Reverse Proxy | 192.168.x.107 | 80, 443, 22 | External |
| Database | 192.168.x.102 | 5432, 54321, 54322 | Internal |
| Backend Server | 192.168.x.103 | 5109 | Internal |
| Host VMs | 192.168.x.140+ | 5901, 6080, 6109 | Internal |
| Frontend | 192.168.x.105 | 5073 | Internal |
| Monitoring | 192.168.x.106 | 3000, 8086, 8088 | Internal |

---

**Note**: This firewall configuration provides defense-in-depth security while maintaining VirtualPyTest functionality. All services remain accessible within the internal network, with controlled external access through the reverse proxy VM.