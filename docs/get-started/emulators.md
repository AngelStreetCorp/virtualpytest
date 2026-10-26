# Emulator VMs

> **Purpose**: Create the VM for each device type and configure it to run VirtualPyTest.
> **Audience**: Whoever provisions the lab.

Each device type gets its own VM. Mobile, tablet and TV run an Android emulator. Web runs a browser.
The sizes below are what our lab measured, not the vendor minimums.

---

## 1. Pick the size

| Type | vCPU | RAM | Disk |
|---|---|---|---|
| **Mobile** | 8 | 12 GB | **50 GB** |
| **Tablet** | 8 | 12 GB | **50 GB** |
| **TV** | 8 | 12 GB | **50 GB** |
| **Web** | 4 | 8 GB | 40 GB |

- **Android VMs need the real CPU type passed through.** Without it the emulator runs very slowly. Web does not need this.
- **Do not give less RAM.** The emulator alone uses 7 to 8.5 GB. There is no swap to fall back on, so a smaller VM freezes.
- **Do not give less disk.** One Android system image is 8.2 GB, and the emulator's data grows over time. A 30 GB disk can run out of space at startup.

<div data-technical>

Measured on our lab (average / peak CPU, RAM):

| Type | CPU type | Measured |
|---|---|---|
| Mobile | `host` | 2.6 / 3.7 cores · 11.5 GB |
| Tablet | `host` | 3.3 / 4.6 cores · 11.5 GB |
| TV | `host` | 2.5 / 3.7 cores · 11.4 GB |
| Web | any | 1.9 / 3.3 cores · 7.1 GB |

Android must use `--cpu host`. Any other CPU type hides the virtualization flags, `/dev/kvm` never appears, and the emulator falls back to software emulation. Web does not need it.

The emulator process alone holds 7–8.5 GB resident. At 12 GB our mobile VM still runs with under 100 MB free, and there is no swap. One Android system image is 8.2 GB and the emulator's writable userdata grows over time. A full host should use **50 GB**; 30 GB hosts can cross the emulator startup free-space check after normal userdata growth.

</div>

---

## 2. Pick the emulator

| | Mobile | Tablet | TV | Web |
|---|---|---|---|---|
| Resolution | 1080 × 2400 | 1600 × 2560 | 1920 × 1080 | 1920 × 1080 |
| Orientation | portrait | portrait | landscape | landscape |

- **Android TV needs the newest image (API 36).** Older Android TV images do not come in the 64-bit x86 version the lab uses.
- **Give each Android VM at least 3 GB of guest memory.** Less and the guest freezes constantly.

<div data-technical>

| | Mobile | Tablet | TV | Web |
|---|---|---|---|---|
| AVD name | `vpt_mobile` | `vpt_tablet` | `android_tv` | — |
| Device profile | `pixel_6` | `pixel_tablet` | `tv_1080p` | — |
| Density | 420 | 320 | 320 | — |
| System image | `android-33/google_apis/x86_64` | `android-33/google_apis/x86_64` | `android-36/android-tv/x86_64` | — |
| Guest RAM (`-memory`) | 3072 MB | 3072 MB | 3072 MB | — |
| `HOST_TYPE` | `android_mobile` | `android_tablet` | `android_tv` | `host_vnc` |

Web's display is VNC `:1`.

Android TV has **no x86_64 image below API 36** (API ≤ 34 is 32-bit x86 or arm64 only). The service's `-memory` flag **overrides** `hw.ramSize` in `config.ini`, so keep the two in sync. Below 3 GB the guest ANRs constantly.

</div>

---

## 3. Create the VM

Create each VM from the template, set the sizes from section 1, and start it.

<div data-technical>

**Proxmox:**

```bash
qm clone <TEMPLATE> <VMID> --name <name> --full 1
qm set  <VMID> --cores 8 --memory 12288 --cpu host --onboot 1 --agent 1   # web: --cores 4 --memory 8192
qm resize <VMID> scsi0 50G
qm start <VMID>
```

**Any other hypervisor** — the only hard requirement for Android is that the guest sees hardware virtualization:

| Hypervisor | Setting |
|---|---|
| Proxmox / KVM | `--cpu host`, and `/sys/module/kvm_*/parameters/nested` = `1` on the host |
| VMware | VM → CPU → *Expose hardware assisted virtualization to the guest OS* |
| VirtualBox | `VBoxManage modifyvm <vm> --nested-hw-virt on` |
| Hyper-V | `Set-VMProcessor <vm> -ExposeVirtualizationExtensions $true` |
| Bare metal / cloud | Any instance type with nested virtualization (GCP `nested-virt`, AWS `*.metal`) |

</div>

On another hypervisor, turn on hardware virtualization for the guest, or Android will not start. The setting name depends on the product; the technical details list them.

Before you go on, check that the VM can run Android. The guest must see hardware virtualization, and its disk must be writable.

<div data-technical>

Verify inside the guest:

```bash
grep -cE "vmx|svm" /proc/cpuinfo   # > 0
ls /dev/kvm                        # exists
mount | grep "on / "               # rw, not ro
```

</div>

---

## 4. Configure it for VirtualPyTest

Run the setup commands. On Android VMs they install the Android SDK, create the emulator and install its service. On every VM they install the host services.

Then give the host its settings:

- **Name and addresses:** the host's name, its own address, and the server's address.
- **Device:** the device type from the table in section 2. Use the matching host type. The three emulator types must include `android` in it, which makes the dashboard treat the emulator as critical instead of optional.

On Android VMs, run the optimize script. It turns off animations and the sources of freezes, and it keeps the screen on.

The emulator screen must never turn off. A sleeping emulator streams a black picture, and nothing wakes it up by itself.

On Android VMs, do not turn off PulseAudio. The emulator's sound goes through it, which is how the device gets sound and how we notice when the sound stops.

<div data-technical>

Setup commands:

```bash
# Android types — installs the SDK, creates the AVD, installs vpt-emulator.service
bash /opt/virtualpytest/setup/proxmox/vm/runner/install_android_emulator.sh --avd-type <mobile|tablet|tv>
sudo usermod -aG kvm vpt_user

# All types — the host service stack
./setup/local/linux/backend_host/install_host.sh
```

Settings in `/opt/virtualpytest/backend_host/src/.env`:

```
HOST_NAME=<name>
HOST_API_URL=http://<this-vm-ip>:6109
SERVER_URL=http://<server-ip>:5109
HOST_TYPE=android_mobile                                    # see the table in §2
DEVICE1_MODEL=android_mobile
DEVICE1_IP=127.0.0.1
DEVICE1_ADB_PORT=5554
DEVICE1_VIDEO=/var/www/html/stream/emulator_frames/latest.png
DEVICE1_VIDEO_AUDIO=default        # Android types: the emulator's sound, via the host's PulseAudio
```

`HOST_TYPE` must contain `android` on the three emulator types — that is what makes the dashboard treat the emulator services as critical instead of optional.

Optimize script, Android types only:

```bash
bash /opt/virtualpytest/setup/proxmox/vm/backend-host/optimize_emulator.sh   # kills animations and ANR sources, screen never sleeps
```

The screencap watchdog deliberately leaves a sleeping device alone, so nothing wakes it. Scripts from before 2026-09-27 set a 30-minute screen timeout. On such a host, run once:

```bash
adb shell settings put system screen_off_timeout 2147483647
adb shell input keyevent KEYCODE_WAKEUP
```

PulseAudio: the emulator plays into `vpt-pulse.service` (`-audio pa` in `vpt-emulator.service`), and the capture records it from there. That is what gives the device an audio track and audio-loss detection. A host installed before 2026-09-16 gets it with:

```bash
sudo bash /opt/virtualpytest/setup/proxmox/vm/runner/enable_emulator_audio.sh
```

</div>

---

## 5. Verify

When it works, the device shows up on the Devices page with live video and sound. The host registers itself, so you do not add it by hand.

<div data-technical>

Checklist:

```bash
adb devices                          # emulator-5554  device   (Android types)
systemctl list-units 'vpt-*' --all   # all critical services active
pactl -s unix:/run/vpt-pulse/native list short clients | grep qemu   # Android types: the emulator is on vpt-pulse
adb shell settings get system screen_off_timeout   # 2147483647 (never sleeps)
adb shell dumpsys power | grep mWakefulness        # mWakefulness=Awake
free -m                              # >500 MB available
df -h /                              # <80 % used
```

</div>

---

## How many fit on one machine

RAM runs out first. Budget **12 GB per Android VM and 8 GB per web VM**. Do not give the VMs more RAM in total than the machine has: a machine that swaps freezes its VMs. CPU can be overcommitted about 2 to 1.

A machine fits this many emulators: (total RAM − 20 GB for the platform) ÷ 12 GB, and never more than threads ÷ 3. A 32 GB mini PC fits one; 64 GB fits three or four.

If something breaks, see the emulator troubleshooting guide. It lists every failure we have hit, with the fix.

<div data-technical>

Troubleshooting path: `docs/android-emulator-troubleshooting.md`.

</div>

---

**See also:** [Hardware](hardware.md) for sizing the machine underneath · [Proxmox](proxmox.md) for creating the VM
