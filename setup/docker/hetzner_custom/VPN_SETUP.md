# Optional VPN Setup for VirtualPyTest

Use a VPN to route traffic through different countries (useful for geo-restricted content testing).

## Quick Setup (3 minutes)

### 1. Get Free WireGuard Config

**ProtonVPN (Free tier available):**
1. Go to [protonvpn.com](https://protonvpn.com)
2. Sign up for free account
3. Navigate to: **Downloads → WireGuard configuration**
4. Select country: US, Netherlands, Japan, etc.
5. Download the `.conf` file (e.g., `proton-nl-123.conf`)

**Other providers:**
- Mullvad VPN
- IVPN
- Any WireGuard-compatible VPN

### 2. Upload Config to Server

**From your local machine:**
```bash
# Upload to your Hetzner server
scp ~/Downloads/proton-nl-123.conf root@YOUR_SERVER_IP:~/vpn.conf
```

**Or download directly on server:**
```bash
# If you have the direct download link
wget -O ~/vpn.conf "https://your-vpn-provider.com/download/config"
```

### 3. Install Config

```bash
# On your Hetzner server
sudo mkdir -p /etc/wireguard
sudo cp ~/vpn.conf /etc/wireguard/wg0.conf
sudo chmod 600 /etc/wireguard/wg0.conf
```

### 4. Enable in config.env

Edit `setup/docker/hetzner_custom/config.env`:

```bash
# Change this line:
USE_VPN=false

# To:
USE_VPN=true
```

### 5. Run Setup

```bash
cd setup/docker/hetzner_custom
./setup.sh
```

The setup script will automatically:
- Install WireGuard (if not already installed)
- Detect your config at `/etc/wireguard/wg0.conf`
- Start VPN connection
- Enable VPN on boot
- Show your new public IP

Done! ✅

## Verify VPN is Working

```bash
# Check VPN status
sudo wg show

# Check public IP (should be VPN country)
curl ifconfig.me

# Check connection
ping -c 3 8.8.8.8
```

## Management

### Start VPN Manually
```bash
sudo wg-quick up wg0
```

### Stop VPN
```bash
sudo wg-quick down wg0
```

### Check VPN Status
```bash
# Show interface status
ip link show wg0

# Show WireGuard details
sudo wg show wg0
```

### Change VPN Country
```bash
# Stop current VPN
sudo wg-quick down wg0

# Replace config with new country
sudo cp ~/Downloads/new-country.conf /etc/wireguard/wg0.conf

# Start VPN
sudo wg-quick up wg0
```

## Troubleshooting

### VPN Won't Connect

**Check DNS:**
```bash
# Edit wg0.conf
sudo nano /etc/wireguard/wg0.conf

# Add/modify DNS line:
DNS = 1.1.1.1, 1.0.0.1
```

**Check firewall:**
```bash
# Allow WireGuard port (usually 51820)
sudo ufw allow 51820/udp
```

### Still Using Local IP

```bash
# Verify routing
ip route show

# Check if VPN is actually up
sudo wg show

# Restart VPN
sudo wg-quick down wg0
sudo wg-quick up wg0
```

### DNS Leaks

Test at: [dnsleaktest.com](https://dnsleaktest.com)

If leaking, force DNS in wg0.conf:
```
DNS = 1.1.1.1
```

## Disable VPN

### Temporary (until reboot)
```bash
sudo wg-quick down wg0
```

### Permanent
Edit `config.env`:
```bash
USE_VPN=false
```

Then disable systemd service:
```bash
sudo systemctl disable wg-quick@wg0
```

## Performance Impact

- **Latency**: +10-50ms depending on VPN server
- **Bandwidth**: Minimal impact with WireGuard (very efficient)
- **CPU**: Negligible on modern systems
- **RAM**: ~5MB per connection

## Free VPN Providers

| Provider | Free Tier | Speed | Privacy |
|----------|-----------|-------|---------|
| ProtonVPN | Yes | Medium | Excellent |
| Windscribe | 10GB/month | Good | Good |
| Hide.me | 10GB/month | Good | Good |

**Note:** Free tiers have bandwidth limits but are fine for testing.

## Advanced: Multiple VPN Configs

To use different VPNs for different hosts:

```bash
# Setup multiple configs
sudo cp us-vpn.conf /etc/wireguard/wg0.conf     # Default
sudo cp nl-vpn.conf /etc/wireguard/wg1.conf     # Alternative

# Start specific VPN
sudo wg-quick up wg1
```

Then modify docker-compose.yml to route specific containers through specific VPN interfaces.

## Security Notes

- WireGuard is more secure than OpenVPN
- Config file contains private key - keep it secure
- VPN hides your IP from external services
- Server provider (Hetzner) can still see encrypted traffic
- For maximum privacy, choose VPN provider outside your jurisdiction

