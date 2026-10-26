# Troubleshooting

**Common problems and how to fix them.** Install problems are at the end of each install guide ([Docker](../get-started/docker.md#troubleshooting), [one VM](../get-started/proxmox.md#day-two)).

---

## Quick checks

Start here to see whether each part is running.

<div data-technical>

```bash
# Docker stack
./setup/docker/launch.sh --logs                    # every container, live
docker ps --format '{{.Names}}\t{{.Status}}'        # vpt-server / vpt-host / vpt-frontend / vpt-supabase-* / vpt-grafana / vpt-minio / vpt-redis
curl -s http://localhost:5109/server/health        # server
curl -s http://localhost:6109/host/health          # host

# VM install
sudo systemctl status vpt-server vpt-host vpt-frontend-prod supabase grafana-server minio redis-server
sudo journalctl -u vpt-server -f                   # or vpt-host, vpt-stream, vpt-monitor-img
```

</div>

### The web page loads, but every action fails

The browser cannot reach the server. Check the server address, then rebuild the frontend.

<div data-technical>

Open `http://<PUBLIC_HOST>:5109/server/health` from the same browser. `PUBLIC_HOST` is set in `setup/docker/.env` (Docker), or as `VITE_SERVER_URL` in `frontend/.env` (VM). If it fails, `PUBLIC_HOST` is not the address the browser uses, or a firewall blocks 5109. Fix it, then run `./setup/docker/launch.sh --rebuild` or re-run `install_frontend.sh`.

</div>

### Every API call returns 401

The server is locked and the browser is not signed in. See [Supabase and authentication](../get-started/supabase.md#authentication-open-mode-or-login).

<div data-technical>

Posture table: [Supabase and authentication](../get-started/supabase.md#authentication-open-mode-or-login). Fresh installs are open (`SERVER_OPEN_MODE=true`).

</div>

### `curl` returns 401, but the web page works

This is expected. Command-line calls still need the server key.

<div data-technical>

`SERVER_OPEN_MODE` waives the browser login, not the server API key: a direct call has to present the key from the server's `.env`.

```bash
curl -H "X-API-Key: $API_KEY" http://<server>:5109/server/system/info
```

</div>

### A run starts, then the page waits until it times out

The test usually finished, but the result did not reach the page.

<div data-technical>

It covers the host status, the callback, then the live connection, and lists the checks that look empty for the wrong reason. Read [Async executions: why the UI waits](../technical/async-execution-troubleshooting.md) _(internal-only — not in the public snapshot)_.

</div>

### The host is missing from Devices

The host did not register. Check its log and the API key.

<div data-technical>

```bash
docker logs vpt-host --tail 50        # or: sudo journalctl -u vpt-host -n 50
```

The host registers with `SERVER_URL` using `API_KEY`. Both must match the server's settings (`backend_host/src/.env`). A host that starts and exits at once has no capture path (`HOST_VIDEO_CAPTURE_PATH`), or a `DEVICEn_VIDEO=/dev/videoX` that does not exist on the machine.

</div>

### Scripts fail when run from the command line

Give the host name, and the device name if there are several.

<div data-technical>

```bash
cd /opt/virtualpytest && source venv/bin/activate      # Docker: docker exec -it vpt-host bash
python test_scripts/goto.py --host <host-name> --node home
```

Scripts take `--host` (and `--device` for multi-device hosts). The script's own `--help` lists its parameters. There is no `-v` / `--debug` flag: the host log above has the detail.

</div>

---

## Installation problems

These problems happen while installing. Each row says where to look.

| Symptom | Where to look |
|---|---|
| The launcher waits forever for the server health check | The troubleshooting section of the Docker guide. |
| "Permission denied" on the Docker socket | Your user is not in the docker group yet. |
| The install script stops in one of its role installers | Run it again. The last step printed is the one that failed. |
| A port is already in use | Stop the other service, or change the port. |

<div data-technical>

- `launch.sh` waits forever for `/server/health`: see [docker.md troubleshooting](../get-started/docker.md#troubleshooting). Usually `vpt-db-init` (schema) or `vpt-server` logs.
- `permission denied … docker.sock`: `newgrp docker`.
- `install_all.sh` stops in a role installer: re-run it. The installers skip what is already done. The failing step is the last one printed.
- Port in use: `sudo ss -tlnp \| grep -E ':(5073\|5109\|6109\|3000\|54321\|9000)'`, then stop the other service or change the port in the compose file / `.env`.

</div>

---

## Device connection problems

### Android device not found

The computer cannot see the Android phone or TV.

1. Turn on **Developer Options** and **USB Debugging** on the Android device.
2. Connect the device by USB and accept the debugging prompt on the device.
3. If the device is still not listed, restart the ADB service.

<div data-technical>

```bash
# Check ADB connection
adb devices

# If empty, restart ADB
adb kill-server
adb start-server
adb devices
```

</div>

### iOS device not responding

Appium cannot control the iPhone or iPad.

1. Install **Xcode** and the **iOS developer tools**.
2. Trust this computer on the iOS device, and make sure **WebDriverAgent** is installed.
3. Check that the device is connected.

<div data-technical>

```bash
# List connected iOS devices
idevice_id -l

# Check if device is accessible
ideviceinfo
```

</div>

### STB or TV remote not working

The remote's commands do not reach the device. Check the IR hardware, the line of sight, the codes and the model setting.

<div data-technical>

1. **Check the IR hardware**: the IR transmitter must be connected.
2. **Check the line of sight**: nothing may block the path between the transmitter and the device.
3. **Test the IR codes**: use the codes for your device model.
4. **Check the configuration**: the device model must be right in the settings.

</div>

---

## Test execution problems

### Tests fail at the first step

The test stops straight away. Check that the device is ready, the model is right and the navigation tree exists.

<div data-technical>

1. **The device is not ready.** Wait for it to finish booting.
2. **The device model is wrong.** Check the `userinterface_name` option.
3. **The navigation tree is missing.** Check the navigation setup.

To see more, run the navigation script on the host, then the validation script.

```bash
# Run with debug mode to see details
python test_scripts/goto.py --host <host-name> --node home

# Check device status first
python test_scripts/validation.py --host <host-name>
```

</div>

### Screenshots are not captured

No images are saved. Check the captures folder and the video capture device.

<div data-technical>

1. **Check the permissions.** VirtualPyTest must be able to write to the captures folder. Create the folder if it is missing.

```bash
mkdir -p captures
chmod 755 captures
```

2. **Check the HDMI capture.** Make sure the video capture device is connected. A short test recording shows if it works.

```bash
# List video devices
ls -la /dev/video*

# Test video capture
ffmpeg -f v4l2 -i /dev/video0 -t 5 test.mp4
```

</div>

### Navigation fails

The message says "No path found" or "Navigation failed". Check the navigation tree and the device's starting screen.

<div data-technical>

```bash
# List available nodes
python test_scripts/goto.py --help

# Test basic navigation first
python test_scripts/goto.py --node home
```

</div>

---

## Monitoring problems

### The Grafana dashboard is empty

No data shows in the charts. Check the data source and the time range, and run some tests.

<div data-technical>

Test the database connection first:

```bash
# Test database connectivity
curl http://localhost:5109/server/health
```

In Grafana, go to Configuration, then Data Sources.

</div>

### Alerts do not fire

Nothing is sent. Test the notification channel and check the alert rules.

<div data-technical>

1. **Test the notification channel.** Send a test alert.
2. **Check the alert rules.** The conditions must be right.
3. **Read the logs.** Check the Grafana logs for errors.
4. **Check the thresholds.** The alert conditions must be reachable.

</div>

### The heatmap stops updating

The heatmap log shows "No space left on device". The temporary folder is full, not the main disk.

<div data-technical>

On some hosts the temporary folder is a fixed-size RAM disk. It can fill up while the main disk still has room. The error is `OSError: [Errno 28] No space left on device` in `vpt-heatmap` logs. Check `/tmp`, which may be a `tmpfs`, and not `/`.

```bash
df
df -h /tmp
ls -lh /tmp/heatmap.log
sudo journalctl -u vpt-heatmap -n 100 --no-pager
```

Typical cause: `backend_server/scripts/heatmap_processor.py` writes `/tmp/heatmap.log`, and it also creates temporary JPG and JSON files in `/tmp`. If `/tmp/heatmap.log` grows too large, `vpt-heatmap` fails when it flushes the log or creates a temporary file.

Fix:

```bash
sudo truncate -s 0 /tmp/heatmap.log
sudo find /tmp -maxdepth 1 -type f -name 'tmp*.jpg' -delete
sudo find /tmp -maxdepth 1 -type f -name 'tmp*.json' -delete
sudo systemctl restart vpt-heatmap
```

</div>

---

## Linux host streaming and RAM hot storage

Live video from a Linux host, such as a Raspberry Pi, belongs in RAM, not on the SD card.

### Streams are written to the SD card instead of RAM

The streaming service finds no RAM storage, so live files go to disk.

<div data-technical>

**Symptoms:**
- `vpt-stream.service` logs `No RAM hot storage found at /var/www/html/stream/captureX/hot`
- live outputs are written under `/var/www/html/stream/captureX/segments` and `/captures` instead of `/hot/...`
- `vpt-archiver.service` logs `Segments folder not found: /var/www/html/stream/captureX/hot/segments`

**Check:**

```bash
mount | grep '/var/www/html/stream/.*/hot'
grep '/var/www/html/stream/capture[0-9]/hot' /etc/fstab
sudo journalctl -u vpt-stream.service -n 80 --no-pager | grep -E 'RAM hot storage|No RAM hot storage'
sudo journalctl -u vpt-archiver.service -n 80 --no-pager | grep -E 'Segments folder not found|FAST LOOP'
```

**Expected:**
- each active capture has a `tmpfs` mount at `/var/www/html/stream/captureX/hot`
- `vpt-stream.service` logs `RAM hot storage detected`
- `vpt-archiver.service` reads from `/hot/segments` without warnings

**Fix:** stop the two services, run the two setup scripts, then start the services again.

```bash
cd /opt/virtualpytest
sudo systemctl stop vpt-stream.service vpt-archiver.service
sudo ./setup/local/linux/backend_host/setup_permissions.sh
sudo ./setup/local/linux/backend_host/setup_ram_hot_storage.sh
sudo systemctl restart vpt-stream.service vpt-archiver.service
```

If `/etc/fstab` contains stale hot entries with the wrong owner or group, re-run `setup_ram_hot_storage.sh`. It rewrites the active hot-storage entries for the devices in `backend_host/src/.env`.

**Verify:**

```bash
mount | grep '/var/www/html/stream/.*/hot'
find /var/www/html/stream/capture1/hot -maxdepth 2 -type d | sort
sudo journalctl -u vpt-stream.service --since '2 min ago' --no-pager | grep -E 'RAM hot storage detected|Using RAM mode'
ls /var/www/html/stream/capture1/hot/segments | head
```

The hot folder must contain four folders: `captures`, `thumbnails`, `segments` and `metadata`.

</div>

Re-run the RAM setup script, then check the mounts and logs.

### The archiver uses too much CPU on a Raspberry Pi


<div data-technical>

**Symptoms:** the archiver uses noticeable CPU even when the streams are idle. Its log repeats every 15s in the fast loop. The log shows missing hot segment folders, or large cleanup batches.

**Check:**

```bash
ps -eo pid,ppid,pcpu,pmem,args --sort=-pcpu | grep hot_cold_archiver.py
sudo journalctl -u vpt-archiver.service -n 120 --no-pager
```

**What the messages mean:**
- `Segments folder not found` means RAM hot storage is broken; fix mounts first.
- `Cold captures(root): Batching ...` means the archiver is cleaning an on-disk backlog and CPU will stay elevated until the backlog shrinks.

**Fix, in this order:**
1. Restore RAM hot storage with `setup_permissions.sh` then `setup_ram_hot_storage.sh`
2. Restart `vpt-stream.service` and `vpt-archiver.service`
3. Recheck that live HLS segments are under `/hot/segments`
4. Wait for the cold backlog to drain if the archiver is still deleting old batches

</div>

Fix broken RAM storage first. A cleanup backlog clears by itself.

### The FFmpeg supervisor loop uses too much CPU

A supervisor shell uses very high CPU and keeps restarting devices.

<div data-technical>

**Symptoms:** a `run_ffmpeg.sh` shell process reaches very high CPU. The logs show repeated stall detections and restarts. FFmpeg is running, but the supervisor keeps restarting the devices.

**Cause:** an old watchdog treated a missing metadata file as a sign of a stall. On Linux hosts, metadata JSON is not the correct health signal for FFmpeg.

**Fix:** deploy the current `backend_host/scripts/run_ffmpeg.sh`, then restart `vpt-stream.service`.

**Verify:**

```bash
systemctl show -p MainPID --value vpt-stream.service
ps -eo pid,ppid,pcpu,args --sort=-pcpu | head -n 20
sudo journalctl -u vpt-stream.service --since '5 min ago' --no-pager | grep -E 'Stall detected|capture_hard_stale|ffmpeg_pid_dead'
```

The result is right when there is one low-CPU supervisor shell, one FFmpeg worker for each active device, and no new "Stall detected" lines.

The MinIO credentials are in `/etc/default/minio` on the storage VM.

</div>

---

## Hardware problems

Check the cables, the capture card and the plugs first.

### HDMI Capture Not Working

There is no picture from the device.

<div data-technical>

**Problem**: No video feed from device

**Solution**:
1. **Check Connections**: Ensure HDMI cables are secure
2. **Verify Capture Card**: Test with different video source
3. **Check Drivers**: Ensure capture card drivers installed
```bash
# Check if capture device is detected
lsusb | grep -i capture
dmesg | grep -i video
```

</div>

### Power Control Not Working

The smart plugs do not respond. Check the network, the account and the plug addresses.

<div data-technical>

**Problem**: Smart plugs not responding

**Solution**:
1. **Check Network**: Ensure plugs are on same network
2. **Verify Credentials**: Check Tapo account settings
3. **Test Manually**: Use Tapo app to control plugs
4. **Check Configuration**: Verify plug IP addresses

</div>

---

## Network issues

### Frontend cannot reach the server, or the server cannot reach a host

Every address is set by hand. Rebuild the frontend after changing one.

<div data-technical>

Every address is configured, nothing is discovered: `VITE_SERVER_URL` (browser → server),
`HOST_API_URL` (server → host), `SERVER_URL` in the host's `.env` (host → server),
`HOST_URL` (browser → host). The [configuration reference](../get-started/configuration.md)
says which file each lives in. After changing a `VITE_*` value the frontend must be rebuilt.

</div>

### A host is unreachable but its VM is still powered on

SSH fails, but the VM shows as running. The VM has probably frozen. Power-cycle it.

<div data-technical>

SSH returns `No route to host` and the guest never answers ARP, while `qm list` shows it
`running`. Check disk and RAM first so you can rule them out, but a powered-on, ARP-dead guest
after hours of uptime is a **hung kernel**, not exhaustion.

The usual cause is a runaway capture loop: a `vpt-emulator-fifo` unit that was hand-edited into
an inline `while true; do adb …; done` with **no `sleep`** re-forks an `adb` that fails
instantly, ~423 times per second, and starves the guest's networking after ~23 hours. Its last
log lines are thousands of `error: device 'emulator-5554' not found`.

```bash
# One vCPU near 100% while the others idle = hung guest kernel
top -H -b -n1 -p <qemu-pid>

# Look at the guest screen without logging in — a live login prompt means only networking died
printf "screendump /tmp/vptdiag/<vmid>.ppm\n" | sudo qm monitor <vmid>

# Is the deployed unit still the repo script, or a hand-edited inline loop?
sudo grep -c "while true; do" /etc/systemd/system/vpt-emulator-fifo.service
```

Stop **and** disable the unit (it returns after a reboot otherwise), then power-cycle the VM:
```bash
sudo systemctl stop    vpt-emulator-fifo.service
sudo systemctl disable vpt-emulator-fifo.service
sudo qm stop <vmid> --timeout 15 && sudo qm start <vmid>
```

`vpt-emulator-fifo` is only meaningful when `HOST_TYPE` contains `android`; on a `host_vnc`
host the capture comes from the VNC display, so the unit must stay disabled. Full diagnosis:
[Android Emulator Troubleshooting](../android-emulator-troubleshooting.md).

</div>

### Remote access

Browsers on other machines must reach the platform's ports. Use the machine's address, never `localhost`.

<div data-technical>

Open 5073, 5109, 6109, 6080 (and 3000 for Grafana) towards the browsers that use the platform, and access it by the machine's address — never `localhost` from another machine.
Exposure beyond a LAN: [docker.md — before exposing](../get-started/docker.md#before-exposing-it-beyond-the-lan).

</div>

---

## Log analysis

### Finding Useful Logs

Each service keeps its own log. Start with the log of the service that failed.

<div data-technical>

```bash
# Docker container logs
docker logs virtualpytest-frontend-1
docker logs virtualpytest-backend_server-1
docker logs virtualpytest-backend_host-1

# Test execution logs
tail -f the host log (`docker logs vpt-host` / `journalctl -u vpt-host`)

# System logs (Linux)
journalctl -u docker -f
```

</div>

### Understanding Error Messages

Read the message, then follow the checks for it.

<div data-technical>

**"Device not found"**:
- Check device connection
- Verify device ID in configuration
- Ensure device is powered on

**"Navigation path not found"**:
- Update navigation tree
- Check if target node exists
- Verify device is on correct starting screen

**"Screenshot capture failed"**:
- Check video device permissions
- Verify HDMI connection
- Test video capture manually

</div>

---

## Recovery

Restart or update with the commands below. A reset erases everything.

<div data-technical>

```bash
# Docker: restart everything (data kept)
./setup/docker/launch.sh --down && ./setup/docker/launch.sh
# Docker: rebuild images after a git pull
./setup/docker/launch.sh --rebuild
# Docker: wipe everything including the database, captures, MinIO, Grafana
./setup/docker/launch.sh --reset

# VM: restart the services
sudo systemctl restart vpt-server vpt-host vpt-frontend-prod
# VM: update code in place
cd /opt/virtualpytest && git pull && ./setup/local/linux/install_all.sh
```

Database backups: `docker exec vpt-supabase-db pg_dump -U postgres postgres > backup.sql` (Docker) or the daily dumps in `/data/backups/` (VM, `/etc/cron.d/vpt-db-backup`).

</div>

Back up the database regularly.

---

## Getting help

### Before you ask for help

1. Check this guide.
2. Read the logs.
3. Note the problem, with screenshots.

### Where to get support

- **GitHub Issues**: bug reports
- **GitHub Discussions**: general questions

### Writing a good bug report

Include the steps, the error text and the logs.

<div data-technical>

- **System information**: OS, Docker version, hardware
- **Steps to reproduce**: the exact commands or actions you took
- **Error messages**: the full error text and logs
- **Screenshots**: visual evidence of the problem
- **Configuration**: the relevant config files, with sensitive data removed

</div>
