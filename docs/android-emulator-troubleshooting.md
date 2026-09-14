# Android Emulator Troubleshooting Guide

## Quick Diagnosis

| Symptom | Likely Cause | Fix |
|---------|--------------|-----|
| ADB shows no devices | Emulator not running | Start emulator |
| `FFmpeg=stuck(0s)` | No video source | Check emulator + vpt-emulator-fifo |
| Status: degraded | A critical service reporting stuck/unknown | Check all `vpt-*` services |
| `Monitor=stuck(0s)` but FFmpeg active | Monitor watches `hot/captures/` which doesn't exist | Symlink hot/captures → captures (§8) |
| Stream image stretched (portrait shows as landscape) | vpt-stream started before emulator was ready | `sudo systemctl restart vpt-stream` |
| Stream is black but frames are fresh and services healthy | Emulator booted with the display composing nothing | SLEEP+WAKEUP the guest display (§9) |
| "Host is not online" on devices page | Host not registered with backend server | `sudo systemctl restart vpt-host` |

## Service Overview

All services run as `vpt_user`. This is critical — if the emulator runs as a different user (e.g. `jndoye`), ADB screencap loses connection on emulator restart.

Each android host VM runs these `vpt-*` services:

| Service | Role | Critical | User |
|---------|------|----------|------|
| `vpt-host` | Host API — registers with server, serves device info | Yes | vpt_user |
| `vpt-stream` | FFmpeg capture — HLS stream + JPG captures + thumbnails | Yes | vpt_user |
| `vpt-monitor` | Capture monitor — watches for new frames | Yes | vpt_user |
| `vpt-emulator` | Android emulator process | Yes (android) | vpt_user |
| `vpt-emulator-fifo` | ADB screencap loop → latest.png for FFmpeg | Yes (android) | vpt_user |
| `vpt-archiver` | Hot/cold frame archiver | Yes |
| `vpt-kpi` | KPI measurement executor | Yes |
| `vpt-vnc` | TigerVNC server | Optional |
| `vpt-websockify` | noVNC websockify bridge | Yes |
| `vpt-transcript` | Audio detection & transcription | Depends on device |

**Check all services:**
```bash
sudo systemctl list-units 'vpt-*' --all
```

**Status logic (from `system_info_utils.py`):**
- `online` — all critical services active
- `degraded` — a critical service is `stuck` or `unknown`
- `error` — a critical service is `error`, `stopped`, or `not_installed`

## Common Issues

### 0. All Streams Show Mobile (Same Device on Mobile/Tablet/TV)

**Symptoms:**
- Devices page shows 3 streams but all display a mobile phone UI
- All host VMs stream the same resolution

**Root cause:**
All VMs were cloned from the same template with an identical `pixel_6` AVD (1080x2400, density 420, portrait). The AVD config wasn't updated after cloning.

**Diagnosis:**
```bash
# Check AVD config on a host VM
grep -E "hw.lcd.(width|height|density)|hw.device.name|hw.initialOrientation" \
  /home/jndoye/.android/avd/pixel6.avd/config.ini
# If all VMs show pixel_6 / 1080x2400 — that's the bug
```

**Fix — set correct AVD profiles per device type:**
```bash
# TV host — 1080p landscape
sed -i "\
s/hw.lcd.width = 1080/hw.lcd.width = 1920/;\
s/hw.lcd.height = 2400/hw.lcd.height = 1080/;\
s/hw.lcd.density = 420/hw.lcd.density = 320/;\
s/hw.device.name = pixel_6/hw.device.name = tv_1080p/;\
s/hw.initialOrientation = portrait/hw.initialOrientation = landscape/" \
  /home/jndoye/.android/avd/pixel6.avd/config.ini

# Tablet host — 10" tablet portrait
sed -i "\
s/hw.lcd.width = 1080/hw.lcd.width = 1600/;\
s/hw.lcd.height = 2400/hw.lcd.height = 2560/;\
s/hw.lcd.density = 420/hw.lcd.density = 320/;\
s/hw.device.name = pixel_6/hw.device.name = pixel_tablet/" \
  /home/jndoye/.android/avd/pixel6.avd/config.ini

# Then restart emulator + streaming
sudo systemctl restart vpt-emulator vpt-stream vpt-emulator-fifo
```

**Expected profiles:**

| Role | Resolution | Density | Orientation | Device |
|------|-----------|---------|-------------|--------|
| Mobile | 1080x2400 | 420 | portrait | pixel_6 |
| TV | 1920x1080 | 320 | landscape | tv_1080p |
| Tablet | 1600x2560 | 320 | portrait | pixel_tablet |

**Prevention:** When cloning a new emulator VM from template, always update the AVD config.ini to match the target device type before starting the emulator.

### 0b. Stream Image Stretched (Wrong Aspect Ratio)

**Symptoms:**
- Mobile stream appears squashed/stretched into landscape 16:9
- Thumbnail is 320x180 instead of 180x320 for portrait devices

**Root cause:**
`run_ffmpeg.sh` detects orientation from the source image **once at startup**. If `vpt-stream` starts before the emulator has produced its first frame, detection fails and defaults to landscape. All ffmpeg scaling then uses landscape dimensions even for portrait emulators.

**Diagnosis:**
```bash
# Check what scaling ffmpeg is actually using
ps aux | grep ffmpeg | grep -v grep | grep -v bash | grep -o "scale=[0-9:]*"
# Expected: scale=180:320 (portrait) or scale=320:180 (landscape)

# Check source image dimensions
identify /var/www/html/stream/emulator_frames/latest.png
# Should show 1080x2400 for mobile
```

**Fix:**
```bash
# Restart vpt-stream — it will re-detect orientation from the now-available source
sudo systemctl restart vpt-stream

# Verify after 10 seconds
ps aux | grep ffmpeg | grep -v grep | grep -v bash | grep -o "scale=[0-9:]*"
```

**Prevention:** This is a boot race condition. The proper fix would be for `run_ffmpeg.sh` to wait for a valid source image before detecting orientation.

### 0c. "Host is not online" on Devices Page

**Symptoms:**
- Devices page shows host as offline/unavailable

**Root cause:**
`vpt-host` registers with the backend server on startup. If the server was unreachable during boot, registration fails.

**Fix:**
```bash
sudo systemctl restart vpt-host
```

### 1. Emulator Won't Start (No ADB Devices)

**Symptoms:**
- `adb devices` returns empty list
- Status shows "degraded"
- FFmpeg stuck at 0s

**Diagnosis:**
```bash
# Check AVD config
cat /mnt/avd-storage/.android/avd/<avd-name>.ini

# Check system image exists
ls /mnt/avd-storage/android-sdk/system-images/
```

**Fix — AVD points to deleted system image:**
```bash
# 1. Update AVD ini file — change target to match installed image
sudo nano /mnt/avd-storage/.android/avd/<avd-name>.ini

# 2. Update AVD config.ini
sudo sed -i "s|android-28|android-33|g" /mnt/avd-storage/.android/avd/<avd-name>.avd/config.ini

# 3. Start emulator
emulator -avd <avd-name> -wipe-data &
```

### 2. Disk Full

**Symptoms:**
- Disk usage >90%
- Emulator fails to start

**Fix:**
```bash
# Delete old backup directories
sudo rm -rf /var/tmp/virtualpytest_backups/*

# Clean journal logs
sudo journalctl --vacuum-time=7d

# Clean apt cache
sudo apt-get clean

# Delete unused system images (check AVD config first!)
sudo rm -rf /mnt/avd-storage/android-sdk/system-images/android-28/
```

### 3. Emulator Running but ADB Can't See It

**Symptoms:**
- `ps aux | grep emulator` shows process
- `adb devices` is empty

**Fix:**
```bash
# Kill stale emulator processes
pkill -f emulator

# Restart ADB server
adb kill-server
adb start-server

# Start emulator fresh
emulator -avd pixel6 -no-snapshot-load &
```

### 4. Screencap Service Not Working

**Symptoms:**
- `/var/www/html/stream/emulator_frames/latest.png` not updating

**Fix:**
```bash
# Check service status
systemctl status vpt-emulator-fifo

# Restart service
sudo systemctl restart vpt-emulator-fifo

# Check if ADB device is available
adb devices
```

### 5. FFmpeg Stuck (Captures Not Producing JPGs)

**Symptoms:**
- `FFmpeg=stuck(0s)` in vpt-host logs
- `/var/www/html/stream/capture1/captures/` has no recent JPG files
- `latest.png` is 0 bytes or hours old

**Root cause — user mismatch (fixed 2026-03-27):**
If the emulator runs as a different user than `vpt-emulator-fifo`, ADB screencap loses connection on emulator restart. Both must run as `vpt_user`. This was fixed on all VMs (380/381/382) — `vpt-emulator.service` now uses `User=vpt_user` with AVD at `/var/lib/vpt_user/.android/avd/`.

If you see this issue on a new VM, check `vpt-emulator.service` — if `User=jndoye`, migrate per the procedure below.

**Diagnosis:**
```bash
# 1. Check source image (0 bytes or stale = screencap broken)
ls -lt /var/www/html/stream/emulator_frames/latest.png

# 2. Check vpt_user ADB (likely empty or offline)
sudo -u vpt_user adb devices

# 3. Check screencap logs
sudo journalctl -u vpt-emulator-fifo --no-pager -n 10
# Look for: "error: device offline" or "error: device not found"

# 4. Check captures (no recent JPGs = ffmpeg stuck)
ls -lt /var/www/html/stream/capture1/captures/ | head -5
```

**Fix:**
```bash
# 1. Reconnect vpt_user's ADB to the emulator
sudo -u vpt_user adb kill-server
sudo -u vpt_user adb connect 127.0.0.1:5555
sudo -u vpt_user adb devices  # should show "device"

# 2. Restart capture pipeline in order
sudo systemctl restart vpt-emulator-fifo
sleep 5
# Verify source is now non-zero
ls -l /var/www/html/stream/emulator_frames/latest.png

# 3. Restart stream
sudo systemctl restart vpt-stream

# 4. Verify after 10 seconds
ls -lt /var/www/html/stream/capture1/captures/ | head -5
```

### 6. Emulator Crash-Looping (Lock Files)

**Symptoms:**
- `vpt-emulator` keeps restarting (check `systemctl status vpt-emulator`)
- Logs show: `FATAL | Running multiple emulators with the same AVD`
- No ADB devices visible

**Root cause:** Stale lock files from a previous emulator instance that didn't shut down cleanly.

**Fix:**
```bash
# Stop emulator and kill any zombie processes
sudo systemctl stop vpt-emulator
sudo pkill -9 -f qemu-system

# Clear lock files (AVD name may vary: pixel6, android_tablet, android_tv)
find ~/.android/avd/ -name '*.lock' -delete
rm -rf ~/.android/avd/<avd-name>.avd/running/

# Restart
sudo systemctl start vpt-emulator

# Wait 60-90s for boot, then verify
sleep 60 && adb devices
```

### 7. Service Health Shows "degraded" Despite Everything Running

**Symptoms:**
- Dashboard shows Emulator=stopped, Screencap=stopped, Stream=stuck
- But `systemctl list-units 'vpt-*'` shows all services active

**Root cause (fixed 2026-03-27):** `check_ffmpeg_status()` and `check_monitor_status()` in `system_info_utils.py` queried systemd service names `stream` and `monitor` instead of `vpt-stream` and `vpt-monitor`. This caused uptime to always be 0 → health check reported stuck.

**Additional cause:** Gunicorn worker crash (exit code 255) on android hosts — the second worker process dies after startup, disrupting the health ping cycle. This is a pre-existing VPT bug in the gunicorn startup code.

### 8. Monitor Stuck — hot/captures Directory Missing (Hot/Cold Path Mismatch)

**Symptoms:**
- `FFmpeg=active` but `Monitor=stuck(0s)` (or both stuck)
- Monitor log shows: `Directory not found: /var/www/html/stream/capture1/hot/captures`
- Monitor says `Waiting for FFmpeg to write new frames...` forever
- FFmpeg IS writing captures to `/var/www/html/stream/capture1/captures/` (verify with `ls -lt`)

**Root cause:** The `hot/` directory exists (created by archiver or manually), so `is_ram_mode()` in `storage_path_utils.py` returns `True`. The monitor then resolves its watch path to `hot/captures/` — but FFmpeg writes to `captures/` (the cold path). The monitor watches an empty/non-existent directory and never sees any frames.

This commonly happens after:
- Archiver creates `hot/` with only `metadata/` subdirectory (no `captures/`)
- Services are restarted individually (monitor restarts, picks up RAM mode, but stream still writes to cold path)
- VM was cloned and `hot/` existed in the template

**Diagnosis:**
```bash
# 1. Confirm FFmpeg writes to cold path
ps aux | grep ffmpeg | grep -v grep | grep -o '/var/www[^ ]*captures[^ ]*'
# Shows: /var/www/html/stream/capture1/captures/capture_%09d.jpg

# 2. Confirm hot/ exists (triggers RAM mode)
ls -la /var/www/html/stream/capture1/hot/
# Shows: metadata/ but NO captures/

# 3. Confirm monitor watches hot path
sudo journalctl -u vpt-monitor --no-pager -n 10 | grep -E 'Monitoring|Directory|Watching'
# Shows: Monitoring [HOT (RAM)]: .../hot/captures
```

**Fix — create symlink from hot/captures to captures:**
```bash
# If hot/captures is an empty directory, remove it first
sudo rmdir /var/www/html/stream/capture1/hot/captures 2>/dev/null

# Create symlink so monitor's inotify resolves to the real captures dir
sudo -u vpt_user ln -s /var/www/html/stream/capture1/captures /var/www/html/stream/capture1/hot/captures

# Restart monitor to pick up the symlinked directory
sudo systemctl restart vpt-monitor

# Verify — should see FILE ARRIVED events within seconds
sudo journalctl -u vpt-monitor --no-pager -n 10 | grep 'FILE ARRIVED'

# Also restart vpt-host to refresh health reporting
sudo systemctl restart vpt-host
```

**Note:** Host 380 (mobile) avoided this issue because its monitor was started before `hot/` was created — so `is_ram_mode()` returned False at startup and it watches `captures/` directly. Any monitor restart after `hot/` exists will hit this bug.

### 9. Stream Is Black but Everything Reports Healthy

**Symptoms:**
- The Devices page shows a black picture, but `vpt-stream`, `vpt-host`, `vpt-emulator` and
  `vpt-emulator-fifo` are all `active`
- `latest.png` updates every 200ms, ffmpeg writes captures, HLS segments roll
- Every capture JPG is byte-identical and tiny (~24 KB for 1080p; a live frame is ~110 KB)
- `adb devices` shows the emulator, `dumpsys power` says `mWakefulness=Awake`, the launcher holds focus

**Root cause:** the guest display is composing nothing. The emulator finishes booting with every
SurfaceFlinger layer hidden while WindowManager still believes the screen is visible — the app
keeps rendering (logcat is full of HWUI `Davey!` lines), the frames just never reach the display.
It is a race in display init and it hits roughly half of emulator starts.

**Diagnosis:**
```bash
# 1. Is the black coming from the guest itself (not our pipeline)?
adb shell screencap -p /sdcard/t.png && adb pull /sdcard/t.png /tmp/t.png
python3 -c "from PIL import Image; print(Image.open('/tmp/t.png').convert('RGB').getextrema())"
# ((0, 0), (0, 0), (0, 0)) = the guest screen is black, the capture chain is fine

# 2. Confirm SurfaceFlinger composes nothing
adb shell dumpsys SurfaceFlinger | sed -n '/Composition list/,/Input list/p'
# Empty composition list + layers "invisible reason=hidden by parent or layer flag" = this bug
```

**Fix (manual):**
```bash
adb shell input keyevent KEYCODE_SLEEP; sleep 2; adb shell input keyevent KEYCODE_WAKEUP
```
The display power cycle forces SurfaceFlinger to re-evaluate layer visibility; the picture returns
within a couple of seconds. No service restart needed.

**Fix (automatic):** `backend_host/scripts/emulator_screencap.sh` — the screencap loop behind
`vpt-emulator-fifo.service` — samples the frame every 30s and performs that power cycle after two
consecutive all-black samples, so a bad boot self-heals in ~60s. It only acts while the device
reports `Awake`, so a deliberately slept device is left alone. If a host still needs the manual
fix, check that its unit actually calls the script:
```bash
grep ExecStart /etc/systemd/system/vpt-emulator-fifo.service
```
An inline `bash -c 'while true; …'` there is the old version with no blackness check — reinstall
the unit from `backend_host/config/services/linux/emulator-fifo.service`.

Full write-up: [BUG-0086](bugs/BUG-0086-2026-09-14-android-emulator-boots-with-black-display.md).

## Template for Cloning

### Available Templates

Templates live on **node 1** (proxmox). Each device type has its own template with the correct AVD profile, VPT services, and systemd units pre-configured.

| Template VMID | Type | AVD Profile | Resolution | Location | Notes |
|---------------|------|-------------|------------|----------|-------|
| **997** | host-android-mobile-template | pixel_6 | 1080x2400, portrait | node 1 | Fixed: vpt_user, sudoers, fstab |
| **998** | host-android-tv-template | tv_1080p | 1920x1080, landscape | node 1 | Fixed: vpt_user, sudoers, fstab |
| **996** | host-android-tablet-template | pixel_tablet | 1600x2560, portrait | node 1 | Fixed: vpt_user, sudoers, fstab |
| 168 | runner-android-mobile-template | vpt_mobile | 1080x2400, portrait | node 1 | |
| 169 | runner-android-tablet-template | vpt_tablet | 1600x2560, portrait | node 1 | |
| 170 | runner-android-tv-template | vpt_tv | 1920x1080, landscape | node 1 | |
| ~~137~~ | ~~host-android-mobile-template~~ | | | node 1 | OLD — use 997 instead |
| ~~138~~ | ~~host-android-tv-template~~ | | | node 1 | OLD — use 998 instead |
| ~~175~~ | ~~host-android-tablet-template~~ | | | node 1 | OLD — use 996 instead |

### Cloning to node 3 (quick procedure ~10 min)

Templates 996/997/998 already have: `User=vpt_user`, passwordless sudo, fstab fixed.
Only 3 things need fixing when moving to node 3: **gateway**, **resolv.conf**, **SSH key**.

```bash
# === STEP 1: Clone on node 1 and transfer disk (~5 min) ===

ssh proxmox "sudo qm clone <template-vmid> <new-vmid> --name <hostname> --full"
# Wait for clone to finish, then transfer disk:
ssh proxmox "sudo cat /var/lib/vz/images/<vmid>/vm-<vmid>-disk-0.qcow2" > /tmp/vm-<vmid>.qcow2
# Delete clone on node 1 (frees the VMID):
ssh proxmox "sudo qm destroy <vmid> --purge"

# === STEP 2: Create VM on node 3 ===

sudo mkdir -p /var/lib/vz/images/<vmid>
sudo qm create <vmid> --name <hostname> --memory 8192 --cores 4 --cpu host \
  --sockets 1 --ostype l26 --net0 virtio,bridge=vmbr0,firewall=0 \
  --scsihw virtio-scsi-single --ide2 none,media=cdrom --boot order=scsi0 --numa 0
sudo cp /tmp/vm-<vmid>.qcow2 /var/lib/vz/images/<vmid>/vm-<vmid>-disk-0.qcow2
sudo qm set <vmid> --scsi0 local:<vmid>/vm-<vmid>-disk-0.qcow2,iothread=1
rm /tmp/vm-<vmid>.qcow2

# === STEP 3: Mount disk, fix gateway + SSH key (~1 min) ===

sudo qemu-nbd --connect=/dev/nbd0 /var/lib/vz/images/<vmid>/vm-<vmid>-disk-0.qcow2
sleep 1 && sudo mount /dev/nbd0p1 /mnt/vmfix

# Fix gateway (node 1=.1, node 3=.3)
sudo sed -i 's/gateway 192.168.x.1$/gateway 192.168.x.3/' /mnt/vmfix/etc/network/interfaces
sudo sed -i 's/dns-nameservers 192.168.x.1$/dns-nameservers 192.168.x.3/' /mnt/vmfix/etc/network/interfaces

# Fix resolv.conf (broken symlink after clone)
sudo rm -f /mnt/vmfix/etc/resolv.conf
echo "nameserver 192.168.x.3" | sudo tee /mnt/vmfix/etc/resolv.conf > /dev/null

# Add SSH key
cat ~/.ssh/id_ed25519.pub | sudo tee -a /mnt/vmfix/home/jndoye/.ssh/authorized_keys > /dev/null

# Regenerate machine-id
sudo rm /mnt/vmfix/etc/machine-id && sudo systemd-machine-id-setup --root=/mnt/vmfix

# Unmount and start
sudo umount /mnt/vmfix && sudo qemu-nbd --disconnect /dev/nbd0
sudo qm start <vmid>

# === STEP 4: Post-boot (~2 min, wait 60s for emulator boot) ===

sleep 60
ssh jndoye@192.168.0.<VMID> "ip route | head -1"  # verify gateway is .3

# Update VPT code (VMs have no GitHub deploy key)
rsync -az --delete --exclude='.git' --exclude='venv' --exclude='node_modules' \
  --exclude='__pycache__' /opt/virtualpytest/ jndoye@192.168.0.<VMID>:/tmp/vpt_update/
ssh jndoye@192.168.0.<VMID> "sudo rsync -a /tmp/vpt_update/ /opt/virtualpytest/ \
  --exclude='.env' --exclude='backend_host/src/.env' && rm -rf /tmp/vpt_update \
  && sudo systemctl restart vpt-host"
```

> **What's already in templates (996/997/998) — no need to fix:**
> - Emulator runs as `vpt_user` (no ADB user mismatch)
> - AVD at `/var/lib/vpt_user/.android/avd/` owned by vpt_user
> - Passwordless sudo for jndoye (`/etc/sudoers.d/jndoye`)
> - fstab: swap and NFS mount already commented out
> - All 10 VPT services pre-configured and enabled

### Updating templates on node 1

Templates are read-only. To edit, clone → fix → re-template:

```bash
# 1. Clone template to temp VM
ssh proxmox "sudo qm clone <template-vmid> <temp-vmid> --name temp-fix --full"

# 2. Start (remove network first to avoid IP conflicts with node 3)
ssh proxmox "sudo qm set <temp-vmid> --delete net0"
ssh proxmox "sudo qm set <temp-vmid> --net0 virtio,bridge=vmbr0,firewall=0"
ssh proxmox "sudo qm start <temp-vmid>"
# Wait ~90s for boot (fstab NFS timeout)

# 3. SSH via node 1 and fix. The lab sudo password is NOT in this repo — put it in your
#    shell first (it expands locally, the remote never sees the literal):
#      export SUDO_PASSWORD='...'
ssh proxmox "sshpass -p '$SUDO_PASSWORD' ssh -o StrictHostKeyChecking=no jndoye@<vm-ip> \
  'echo $SUDO_PASSWORD | sudo -S bash -c \"<your fix commands>\"'"

# 4. Stop, rename, convert to template
ssh proxmox "sudo qm stop <temp-vmid>"
ssh proxmox "sudo qm set <temp-vmid> --name <template-name>"
ssh proxmox "sudo qm set <temp-vmid> --template 1"
```

### Known gotchas when cloning across nodes

| Issue | Symptom | Cause | Still needed with new templates? |
|-------|---------|-------|--------------------------------|
| VM boots but no network | ARP FAILED, ping timeout | Gateway `.1` (node 1) vs `.3` (node 3) | **YES** — fix in Step 3 |
| DNS not working | Can't resolve hosts | `/etc/resolv.conf` is broken symlink | **YES** — fix in Step 3 |
| SSH key rejected | Permission denied (publickey) | Key not in authorized_keys | **YES** — fix in Step 3 |
| Emulator won't start | No KVM | VM created without `cpu: host` | **YES** — must use `--cpu host` in Step 2 |
| NIC name mismatch | ens18 doesn't exist | PCI layout differs from template | **YES** — must include `--ide2 none,media=cdrom` in Step 2 |
| Boot hangs 90s+ | VM unreachable for minutes | fstab swap/NFS | **NO** — fixed in templates 996/997/998 |
| `sudo` needs password | Commands fail remotely | No NOPASSWD in sudoers | **NO** — fixed in templates |
| ADB user mismatch | FFmpeg stuck after emulator restart | Emulator ran as jndoye, screencap as vpt_user | **NO** — fixed in templates |
| GitHub access denied | `git fetch origin` fails | No deploy key on VM | Expected — use rsync from node 3 |

## Useful Commands

```bash
# Check all VPT services
sudo systemctl list-units 'vpt-*' --all

# Check disk
df -h /

# Check ADB devices
adb devices

# List AVDs
avdmanager list avd

# Check emulator processes
ps aux | grep emulator

# View VPT host logs
journalctl -u vpt-host -f

# Check what FFmpeg is doing
ps aux | grep ffmpeg | grep -v grep

# Check recent captures
ls -lt /var/www/html/stream/capture1/captures/ | head -5
```
