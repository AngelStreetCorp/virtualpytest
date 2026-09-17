# Emulator VMs

> **Purpose**: Create the VM for each device type and configure it to run VirtualPyTest.
> **Audience**: Whoever provisions the lab.

One VM per device type. Mobile, tablet and TV run an Android emulator; web runs Chromium.
All numbers are measured on our lab, not vendor minimums.

---

## 1. Pick the size

| Type | vCPU | RAM | Disk | CPU type | Runs | Measured (avg / peak CPU, RAM) |
|---|---|---|---|---|---|---|
| **Mobile** | 8 | 12 GB | **50 GB** | `host` | Android emulator | 2.6 / 3.7 cores · 11.5 GB |
| **Tablet** | 8 | 12 GB | **50 GB** | `host` | Android emulator | 3.3 / 4.6 cores · 11.5 GB |
| **TV** | 8 | 12 GB | **50 GB** | `host` | Android emulator | 2.5 / 3.7 cores · 11.4 GB |
| **Web** | 4 | 8 GB | 40 GB | any | Chromium + Playwright | 1.9 / 3.3 cores · 7.1 GB |

Three rules behind the table:

- **Android needs `--cpu host`.** Any other CPU type hides the virtualization flags, `/dev/kvm` never appears, and the emulator falls back to software emulation. Web does not need it.
- **Do not cut RAM.** The emulator process alone holds 7–8.5 GB resident. At 12 GB our mobile VM still runs with under 100 MB free, and there is no swap.
- **Do not cut disk.** One Android system image is 8.2 GB; the emulator's writable userdata grows over time. A full host should use **50 GB**; 30 GB hosts can cross the emulator startup free-space check after normal userdata growth.

---

## 2. Pick the emulator

| | Mobile | Tablet | TV | Web |
|---|---|---|---|---|
| AVD name | `vpt_mobile` | `vpt_tablet` | `android_tv` | — |
| Device profile | `pixel_6` | `pixel_tablet` | `tv_1080p` | — |
| Resolution | 1080 × 2400 | 1600 × 2560 | 1920 × 1080 | 1920 × 1080 (VNC `:1`) |
| Density | 420 | 320 | 320 | — |
| Orientation | portrait | portrait | landscape | landscape |
| System image | `android-33/google_apis/x86_64` | `android-33/google_apis/x86_64` | `android-36/android-tv/x86_64` | — |
| Guest RAM (`-memory`) | 3072 MB | 3072 MB | 3072 MB | — |
| `HOST_TYPE` | `android_mobile` | `android_tablet` | `android_tv` | `host_vnc` |

Two traps: Android TV has **no x86_64 image below API 36** (API ≤ 34 is 32-bit x86 or arm64 only), and the service's `-memory` flag **overrides** `hw.ramSize` in `config.ini` — keep them in sync. Below 3 GB the guest ANRs constantly.

---

## 3. Create the VM

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

Verify inside the guest before going further:

```bash
grep -cE "vmx|svm" /proc/cpuinfo   # > 0
ls /dev/kvm                        # exists
mount | grep "on / "               # rw, not ro
```

---

## 4. Configure it for VirtualPyTest

```bash
# Android types — installs the SDK, creates the AVD, installs vpt-emulator.service
bash /opt/virtualpytest/setup/proxmox/vm/runner/install_android_emulator.sh --avd-type <mobile|tablet|tv>
sudo usermod -aG kvm vpt_user

# All types — the host service stack
./setup/local/linux/backend_host/install_host.sh
```

Then set the identity and device in `/opt/virtualpytest/backend_host/src/.env`:

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

Finally, on Android types only:

```bash
bash /opt/virtualpytest/setup/proxmox/vm/backend-host/optimize_emulator.sh   # kills animations and ANR sources
```

Do **not** disable PulseAudio on an Android type: the emulator plays into `vpt-pulse.service`
(`-audio pa` in `vpt-emulator.service`) and the capture records it from there, which is what gives the
device an audio track and audio-loss detection. A host installed before 2026-09-16 gets it with
`sudo bash /opt/virtualpytest/setup/proxmox/vm/runner/enable_emulator_audio.sh`.

---

## 5. Verify

```bash
adb devices                          # emulator-5554  device   (Android types)
systemctl list-units 'vpt-*' --all   # all critical services active
pactl -s unix:/run/vpt-pulse/native list short clients | grep qemu   # Android types: the emulator is on vpt-pulse
free -m                              # >500 MB available
df -h /                              # <80 % used
```

The host then self-registers and appears on the Devices page.

---

## How many fit on one machine

RAM runs out first. Budget **12 GB per Android VM, 8 GB per web VM**, and do not overcommit RAM — a host that swaps will freeze its guests. CPU can be overcommitted ~2:1.

**Emulators ≈ (total RAM − 20 GB for the platform) ÷ 12 GB**, capped by `threads ÷ 3`. A 32 GB mini PC fits one; 64 GB fits three or four.

Troubleshooting: the in-repo runbook `docs/android-emulator-troubleshooting.md` lists every failure mode we have hit, with the fix.

---

**See also:** [Hardware](hardware.md) for sizing the machine underneath · [Proxmox](proxmox.md) for creating the VM
