#!/bin/bash
# runs on proxmox after reboot; read-only
s(){ echo; echo "=== $* ==="; }
s now; date -u; uptime
s boots; journalctl --list-boots 2>&1 | tail -5
s last-reboots; last -x -F reboot shutdown 2>/dev/null | head -8
s prev-boot-last-200-lines; journalctl -b -1 --no-pager -n 200 2>&1 | tail -200
s prev-boot-errors; journalctl -b -1 -p err --no-pager 2>&1 | tail -80
s oom-and-io-prev; journalctl -b -1 -k --no-pager 2>&1 | grep -iE "oom|out of memory|killed process|i/o error|blk_update|ata[0-9]|nvme|reset|hung task|blocked for more|soft lockup|hard lockup|mce|machine check|edac|thermal|throttl|zfs|btrfs|ext4.*error|md/raid" | tail -60
s sysstat; ls /var/log/sysstat 2>&1 | tail -5
s syslog-tail-before-gap; sudo -n tail -150 /var/log/syslog.1 2>&1 | tail -150; sudo -n tail -50 /var/log/syslog 2>&1
s smart; for d in /dev/nvme?n1 /dev/sd?; do [ -e $d ] && { echo "-- $d"; sudo -n smartctl -H -A $d 2>&1 | grep -iE "overall|critical|percentage|media|error|realloc|pending|temperature|power_on|unsafe" ; }; done
s mem-disk; free -h; df -hT -x tmpfs -x devtmpfs; lsblk -o NAME,SIZE,TYPE,MOUNTPOINT 2>&1 | head -30
s raid-zfs; cat /proc/mdstat 2>&1; sudo -n zpool status 2>&1 | head -20
s pve; pveversion 2>&1; sudo -n /usr/sbin/qm list 2>&1; sudo -n /usr/sbin/pct list 2>&1; systemctl --failed --no-pager 2>&1 | head -20
s cluster; sudo -n pvecm status 2>&1 | head -20
s top-mem; ps aux --sort=-rss | head -8
s ipmi-hw; ls /var/crash 2>&1 | head; dmesg -T 2>&1 | grep -iE "error|fail|mce|edac" | tail -20
