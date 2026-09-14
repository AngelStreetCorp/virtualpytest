# Troubleshooting

**Common issues and solutions.** Install-time problems for each path are at the end of its
guide ([Docker](../get-started/docker.md#troubleshooting), [one VM](../get-started/proxmox.md#day-two));
this page is about a platform that is installed and misbehaving.

---

## 🚀 **Quick checks**

```bash
# Docker stack
./setup/docker/launch.sh --logs                    # every container, live
docker ps --format '{{.Names}}\t{{.Status}}'        # vpt-server / vpt-host / vpt-frontend / vpt-supabase-* / vpt-grafana / vpt-minio / vpt-redis
curl -s http://localhost:5109/server/health        # server
curl -s http://localhost:6109/host/health          # host

# VM install
sudo systemctl status vpt-server vpt-host vpt-frontend-prod supabase grafana-server minio redis-server
sudo journalctl -u vpt-server -f                   # or vpt-host, vpt-stream, vpt-monitor
```

### Web UI loads but every action fails
The browser cannot reach the server API. Open `http://<PUBLIC_HOST>:5109/server/health` from
the same browser. If it fails, `PUBLIC_HOST` (Docker: `setup/docker/.env`; VM:
`VITE_SERVER_URL` in `frontend/.env`) is not the address the browser uses, or a firewall
blocks 5109 — fix, then `./setup/docker/launch.sh --rebuild` / re-run `install_frontend.sh`.

### Every API call returns 401
The server is closed and nothing authenticates the browser: see the posture table in
[Supabase and authentication](../get-started/supabase.md#authentication-open-mode-or-login).
Fresh installs are open (`SERVER_OPEN_MODE=true`).

### Host missing from *Devices*
```bash
docker logs vpt-host --tail 50        # or: sudo journalctl -u vpt-host -n 50
```
The host registers itself with `SERVER_URL` using `API_KEY`; both must match the server's
(`backend_host/src/.env`). A host that starts and exits at once has no capture path
(`HOST_VIDEO_CAPTURE_PATH`) or a `DEVICEn_VIDEO=/dev/videoX` that does not exist on the
machine.

### Scripts fail to run from the command line
```bash
cd /opt/virtualpytest && source venv/bin/activate      # Docker: docker exec -it vpt-host bash
python test_scripts/goto.py --host <host-name> --node home
```
Scripts take `--host` (and `--device` for multi-device hosts); the script's own `--help`
lists its parameters. There is no `-v` / `--debug` flag: the host log above has the detail.

---

## 🔧 **Installation-time problems**

| Symptom | Where to look |
|---|---|
| `launch.sh` waits forever for `/server/health` | [docker.md troubleshooting](../get-started/docker.md#troubleshooting) — usually `vpt-db-init` (schema) or `vpt-server` logs |
| `permission denied … docker.sock` | your user is not in the `docker` group yet: `newgrp docker` |
| `install_all.sh` stops in a role installer | re-run it: installers skip what is done; the failing step is the last one printed |
| Port already in use | `sudo ss -tlnp \| grep -E ':(5073\|5109\|6109\|3000\|54321\|9000)'` — stop the other service or change the port in the compose file / `.env` |

---

## 📱 **Device Connection Issues**

### Android Device Not Found
**Problem**: ADB can't see your device

**Solution**:
1. Enable **Developer Options** on Android device
2. Enable **USB Debugging**
3. Connect via USB and accept debugging prompt
4. Verify connection:
```bash
# Check ADB connection
adb devices

# If empty, restart ADB
adb kill-server
adb start-server
adb devices
```

### iOS Device Not Responding
**Problem**: Appium can't control iOS device

**Solution**:
1. Install **Xcode** and **iOS developer tools**
2. Trust the computer on iOS device
3. Verify **WebDriverAgent** is installed
4. Check device connection:
```bash
# List connected iOS devices
idevice_id -l

# Check if device is accessible
ideviceinfo
```

### STB/TV Remote Not Working
**Problem**: IR commands not reaching device

**Solution**:
1. **Check IR Hardware**: Ensure IR transmitter is connected
2. **Verify Line of Sight**: Clear path between transmitter and device
3. **Test IR Codes**: Use correct codes for your device model
4. **Check Configuration**: Verify device model in settings

---

## 🧪 **Test Execution Problems**

### Tests Fail Immediately
**Symptoms**: Tests stop at first step

**Common causes**:
1. **Device not ready**: Wait for device to fully boot
2. **Wrong device model**: Check userinterface_name parameter
3. **Navigation tree missing**: Verify navigation configuration

**Solution**:
```bash
# Run with debug mode to see details
python test_scripts/goto.py --host <host-name> --node home

# Check device status first
python test_scripts/validation.py --host <host-name>
```

### Screenshots Not Captured
**Problem**: No images saved in /captures folder

**Solution**:
1. **Check Permissions**: Ensure write access to captures directory
```bash
mkdir -p captures
chmod 755 captures
```

2. **Verify HDMI Capture**: Check video device connection
```bash
# List video devices
ls -la /dev/video*

# Test video capture
ffmpeg -f v4l2 -i /dev/video0 -t 5 test.mp4
```

### Navigation Fails
**Problem**: "No path found" or "Navigation failed"

**Solution**:
1. **Check Navigation Tree**: Verify target node exists
2. **Device State**: Ensure device is on correct screen
3. **Update Tree**: Navigation may have changed

```bash
# List available nodes
python test_scripts/goto.py --help

# Test basic navigation first
python test_scripts/goto.py --node home
```

---

## 📊 **Monitoring Issues**

### Grafana Dashboard Empty
**Problem**: No data showing in charts

**Solution**:
1. **Check Database Connection**:
```bash
# Test database connectivity
curl http://localhost:5109/server/health
```

2. **Verify Data Source**: Go to Grafana → Configuration → Data Sources
3. **Check Time Range**: Ensure time range includes test data
4. **Run Some Tests**: Generate data first

### Alerts Not Firing
**Problem**: No notifications despite issues

**Solution**:
1. **Test Notification Channel**: Send test alert
2. **Check Alert Rules**: Verify conditions are correct
3. **Review Logs**: Check Grafana logs for errors
4. **Verify Thresholds**: Ensure alert conditions can be met

### Heatmap Stops Processing
**Problem**: Heatmap page stops updating or `vpt-heatmap` logs show `OSError: [Errno 28] No space left on device`

**Important**:
1. This often means `/tmp` is full, not `/`
2. On some hosts `/tmp` is a `tmpfs`, so it can reach 100% while the main disk still has plenty of free space

**Check**:
```bash
df
df -h /tmp
ls -lh /tmp/heatmap.log
sudo journalctl -u vpt-heatmap -n 100 --no-pager
```

**Typical cause**:
1. `backend_server/scripts/heatmap_processor.py` writes `/tmp/heatmap.log`
2. The heatmap processor also creates temporary JPG/JSON files in `/tmp`
3. If `/tmp/heatmap.log` grows too large, `vpt-heatmap` can fail on log flush or temp file creation

**Fix**:
```bash
sudo truncate -s 0 /tmp/heatmap.log
sudo find /tmp -maxdepth 1 -type f -name 'tmp*.jpg' -delete
sudo find /tmp -maxdepth 1 -type f -name 'tmp*.json' -delete
sudo systemctl restart vpt-heatmap
```

---


---

## 🎥 **Linux Host Streaming / RAM Hot Storage**

### Streams Writing To SD Instead Of RAM
**Symptoms**:
- `vpt-stream.service` logs `No RAM hot storage found at /var/www/html/stream/captureX/hot`
- live outputs are written under `/var/www/html/stream/captureX/segments` and `/captures` instead of `/hot/...`
- `vpt-archiver.service` logs `Segments folder not found: /var/www/html/stream/captureX/hot/segments`
- Raspberry Pi load stays elevated and SD wear risk increases

**Check**:
```bash
mount | grep '/var/www/html/stream/.*/hot'
grep '/var/www/html/stream/capture[0-9]/hot' /etc/fstab
sudo journalctl -u vpt-stream.service -n 80 --no-pager | grep -E 'RAM hot storage|No RAM hot storage'
sudo journalctl -u vpt-archiver.service -n 80 --no-pager | grep -E 'Segments folder not found|FAST LOOP'
```

**Expected**:
- each active capture has a `tmpfs` mount at `/var/www/html/stream/captureX/hot`
- `vpt-stream.service` logs `RAM hot storage detected`
- `vpt-archiver.service` reads from `/hot/segments` without warnings

**Fix**:
```bash
cd /opt/virtualpytest
sudo systemctl stop vpt-stream.service vpt-archiver.service
sudo ./setup/local/linux/backend_host/setup_permissions.sh
sudo ./setup/local/linux/backend_host/setup_ram_hot_storage.sh
sudo systemctl restart vpt-stream.service vpt-archiver.service
```

**Verify**:
```bash
mount | grep '/var/www/html/stream/.*/hot'
find /var/www/html/stream/capture1/hot -maxdepth 2 -type d | sort
sudo journalctl -u vpt-stream.service --since '2 min ago' --no-pager | grep -E 'RAM hot storage detected|Using RAM mode'
ls /var/www/html/stream/capture1/hot/segments | head
```

The hot directory must contain:
- `captures`
- `thumbnails`
- `segments`
- `metadata`

If `/etc/fstab` contains stale hot entries with the wrong owner/group, rerun `setup_ram_hot_storage.sh`. It rewrites active hot-storage entries for the devices configured in `backend_host/src/.env`.

### Archiver CPU High On Raspberry Pi
**Symptoms**:
- `vpt-archiver.service` uses noticeable CPU even when streams are idle
- logs repeat every 15s in the fast loop
- logs show missing hot segment folders or large cold cleanup batches

**Check**:
```bash
ps -eo pid,ppid,pcpu,pmem,args --sort=-pcpu | grep hot_cold_archiver.py
sudo journalctl -u vpt-archiver.service -n 120 --no-pager
```

**Interpretation**:
- `Segments folder not found` means RAM hot storage is broken; fix mounts first
- `Cold captures(root): Batching ...` means the archiver is cleaning an on-disk backlog and CPU will stay elevated until the backlog shrinks

**Fix order**:
1. Restore RAM hot storage with `setup_permissions.sh` then `setup_ram_hot_storage.sh`
2. Restart `vpt-stream.service` and `vpt-archiver.service`
3. Recheck that live HLS segments are under `/hot/segments`
4. Wait for the cold backlog to drain if the archiver is still deleting old batches

### FFmpeg Supervisor Loop Burns CPU
**Symptoms**:
- a `run_ffmpeg.sh` shell process reaches very high CPU
- logs show repeated stall detection and restarts
- FFmpeg is alive, but the supervisor keeps restarting devices

**Cause**:
- old watchdog logic treated missing metadata JSON as a hard stall signal
- on Linux hosts, metadata JSON is not the correct health signal for FFmpeg

**Fix**:
- deploy the current `backend_host/scripts/run_ffmpeg.sh`
- restart `vpt-stream.service`

**Verify**:
```bash
systemctl show -p MainPID --value vpt-stream.service
ps -eo pid,ppid,pcpu,args --sort=-pcpu | head -n 20
sudo journalctl -u vpt-stream.service --since '5 min ago' --no-pager | grep -E 'Stall detected|capture_hard_stale|ffmpeg_pid_dead'
```

Expected result:
- one low-CPU supervisor shell
- one FFmpeg worker per active device
- no new `Stall detected` log lines
```
The MinIO credentials are in `/etc/default/minio` on the storage VM.

---

## 🔌 **Hardware Problems**

### HDMI Capture Not Working
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

### Power Control Not Working
**Problem**: Smart plugs not responding

**Solution**:
1. **Check Network**: Ensure plugs are on same network
2. **Verify Credentials**: Check Tapo account settings
3. **Test Manually**: Use Tapo app to control plugs
4. **Check Configuration**: Verify plug IP addresses

---


---

## 🌐 **Network Issues**

### Frontend cannot reach the server, or the server cannot reach a host
Every address is configured, nothing is discovered: `VITE_SERVER_URL` (browser → server),
`HOST_API_URL` (server → host), `SERVER_URL` in the host's `.env` (host → server),
`HOST_URL` (browser → host). The [configuration reference](../get-started/configuration.md)
says which file each lives in. After changing a `VITE_*` value the frontend must be rebuilt.

### Remote access
Open 5073, 5109, 6109, 6080 (and 3000 for Grafana) towards the browsers that use the
platform, and access it by the machine's address — never `localhost` from another machine.
Exposure beyond a LAN: [docker.md — before exposing](../get-started/docker.md#before-exposing-it-beyond-the-lan).

---

## 📝 **Log Analysis**

### Finding Useful Logs
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

### Understanding Error Messages

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

---


---

## 🔄 **Recovery Procedures**

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

Database backups: `docker exec vpt-supabase-db pg_dump -U postgres postgres > backup.sql`
(Docker) or the daily dumps in `/data/backups/` (VM, `/etc/cron.d/vpt-db-backup`).

---

## 🆘 **Getting Help**

### Before Asking for Help
1. **Check this guide** for your specific issue
2. **Review logs** for error messages
3. **Try basic troubleshooting** steps
4. **Document the problem** with screenshots/logs

### Where to Get Support
- **GitHub Issues**: Bug reports and technical problems
- **GitHub Discussions**: General questions and community help
- **Documentation**: Check other guides in this documentation

### Providing Good Bug Reports
Include:
- **System Information**: OS, Docker version, hardware
- **Steps to Reproduce**: Exact commands/actions taken
- **Error Messages**: Full error text and logs
- **Screenshots**: Visual evidence of the problem
- **Configuration**: Relevant config files (remove sensitive data)

---

