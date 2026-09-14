#!/bin/bash
# VM Diagnostic Script - Gathers all info needed for resource analysis
# Usage: ssh <vm-name> 'bash -s' < scripts/vm_diag.sh
#    or: scp scripts/vm_diag.sh <vm>:/tmp/ && ssh <vm> bash /tmp/vm_diag.sh

HOST=$(hostname)
echo "=========================================="
echo " VM DIAGNOSTIC: $HOST"
echo " Date: $(date '+%Y-%m-%d %H:%M:%S')"
echo "=========================================="

# --- SYSTEM ---
echo ""
echo "=== SYSTEM ==="
echo "Kernel: $(uname -r)"
echo "Uptime:$(uptime)"
nproc_count=$(nproc 2>/dev/null || echo "?")
echo "CPUs: $nproc_count"

# --- MEMORY ---
echo ""
echo "=== MEMORY ==="
free -h
echo ""
echo "Swap usage:"
cat /proc/swaps 2>/dev/null || echo "  (no swap)"

# --- DISK ---
echo ""
echo "=== DISK ==="
df -h / /var/www/html 2>/dev/null | sort -u
echo ""
echo "Large dirs (top 5 under /):"
du -sh /var/log /var/www /opt /home /tmp 2>/dev/null | sort -rh | head -5

# --- TOP MEMORY CONSUMERS ---
echo ""
echo "=== TOP 15 PROCESSES BY MEMORY ==="
printf "%-8s %6s %5s %5s  %s\n" "USER" "PID" "%MEM" "%CPU" "COMMAND"
echo "-----------------------------------------------"
ps aux --sort=-%mem | awk 'NR>1 && NR<=16 {printf "%-8s %6s %5s %5s  %s\n", $1, $2, $4, $3, $11}'

# --- TOP CPU CONSUMERS ---
echo ""
echo "=== TOP 10 PROCESSES BY CPU ==="
printf "%-8s %6s %5s %5s  %s\n" "USER" "PID" "%CPU" "%MEM" "COMMAND"
echo "-----------------------------------------------"
ps aux --sort=-%cpu | awk 'NR>1 && NR<=11 {printf "%-8s %6s %5s %5s  %s\n", $1, $2, $3, $4, $11}'

# --- SERVICES ---
echo ""
echo "=== SYSTEMD SERVICES (running) ==="
systemctl list-units --type=service --state=running --no-pager --no-legend 2>/dev/null | awk '{print $1}' | grep -v 'session\|user@\|getty' | sort

# --- DOCKER ---
if command -v docker &>/dev/null; then
    echo ""
    echo "=== DOCKER CONTAINERS ==="
    docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Size}}" 2>/dev/null || echo "  (docker not accessible)"
fi

# --- NETWORK LISTENERS ---
echo ""
echo "=== LISTENING PORTS ==="
ss -tlnp 2>/dev/null | awk 'NR>1 {print $4, $6}' | sed 's/users:(("/  /;s/".*//;s/,pid=/:/' | sort -t: -k1,1n

# --- MEMORY SUMMARY ---
echo ""
echo "=== MEMORY SUMMARY ==="
total_rss=$(ps aux --sort=-%mem | awk 'NR>1 {sum+=$6} END {printf "%.0f", sum/1024}')
echo "Total RSS (all processes): ${total_rss} MB"
buff_cache=$(free -m | awk '/Mem:/ {print $6}')
echo "Buff/cache: ${buff_cache} MB"
available=$(free -m | awk '/Mem:/ {print $7}')
total=$(free -m | awk '/Mem:/ {print $2}')
pct_used=$(( (total - available) * 100 / total ))
echo "Effective usage: ${pct_used}% of ${total} MB"
swap_used=$(free -m | awk '/Swap:/ {print $3}')
if [ "$swap_used" -gt 0 ] 2>/dev/null; then
    echo "WARNING: ${swap_used} MB swap in use — VM is memory-pressured"
fi

echo ""
echo "=========================================="
echo " END DIAGNOSTIC: $HOST"
echo "=========================================="
