# BUG-0839 — AIC8800DC USB Wi-Fi dongles deliver every frame above ~520 bytes truncated (no Tello video)

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0839                                                     |
| Reported  | 2026-10-22                                                   |
| Status    | Fixed (pending deploy on vpt-pi4)                            |
| Severity  | High                                                         |
| Area      | setup (host Wi-Fi driver) / drones                           |
| Fixed in  | build 90145 |
| Commit    | TBD                                                          |

---

## Symptom

Two TP-Link AX300 dongles (AICSemi AIC8800DC, `3625:0110`, DKMS driver
`Kiborgik/aic8800dc-linux-patched` 6.4.3.0-patched.17) associate with the Tello APs and exchange
small datagrams (SDK replies, 8890 telemetry) fine, but every received frame larger than about 500
bytes is cut to 512 bytes of payload: `ping -s 400` works, `ping -s 600` and above is 100 % loss,
`tcpdump` shows `truncated-ip - 976 bytes missing` on the 1460-byte video datagrams (Ethernet frame
length 526) and junk frames with ethertype `0xeaeb`-style values. ffmpeg never receives a video
packet; the device tile stays on "Starting video...". Identical on vpt-pi4 (Pi 5, kernel 6.12.25) and
vpt-nipogi (x86, 6.12.107). The Pi's onboard Broadcom radio joined the same drone and passed
1400-byte pings with 0 % loss, so the drone was never the problem.

## Root cause

`usbmon` on vpt-nipogi (2026-10-22) shows what the firmware hands the host for one 1428-byte ICMP
reply: three bulk-IN completions of 606, 606 and 482 bytes, each a complete MPDU with its own RX
header, 802.11 **sequence number 17, fragment numbers 0, 1, 2, MoreFrag set on the first two**. The
Tello AP fragments every MSDU above ~520 bytes, the AIC8800 firmware does not reassemble, and the
driver's `rwnx_rxdataind_aicwf()` (`drivers/aic8800/aic8800_fdrv/rwnx_rx.c`) converts each MPDU to
802.3 and forwards it as if it were whole: fragment 0 becomes a 526-byte frame (14 + 512), fragments
1 and 2 become frames whose "ethertype" is two bytes of payload. The newer vendor driver (Radxa's
2026-01 `aic8800` package) has a `defrag_list` for exactly this; the Kiborgik tree is an older
6.4.3.0 snapshot without it. brcmfmac worked because its firmware defragments.

## Fix

`setup/scripts/aic8800dc/aic8800dc-rx-defrag.patch` ports the vendor defragmentation into the
Kiborgik tree: `struct defrag_ctrl_info` + `defrag_list`/`defrag_lock` on `rwnx_hw`
(`rwnx_defs.h`), list init in `rwnx_cfg80211_init` and drain in `rwnx_cfg80211_deinit`
(`rwnx_main.c`), and in `rwnx_rxdataind_aicwf()` fragments are collected per sta/tid/sequence
number (first fragment becomes the 802.3 head, later ones contribute their body after the MAC
header and IV, the last one is delivered through `rwnx_rx_data_skb()`), with a 40 ms timer
(`DEFRAG_MAX_WAIT`) that drops a partial frame, tailroom guards instead of `skb_put` overflows, and
debug-level logging instead of the vendor's per-fragment `printk`.
`setup/scripts/aic8800dc/install_aic8800dc.sh` clones the pinned upstream commit, applies the patch
and installs it as DKMS version `6.4.3.0-patched.17+vpt.1`. Doc:
[docs/agent/devices/TELLO_USB_WIFI.md](../agent/devices/TELLO_USB_WIFI.md).

## Verification

vpt-nipogi, dongle `wlxc03a55f0a36b` joined to `TELLO-C5B142`, before the patch:
`ping -I <host ip> -s 100 <tello ip>` 0 % loss, `-s 1400` 100 % loss, `usbmon` showing the three fragments.
After installing the patched DKMS module and rebooting: `dkms status` shows
`aic8800dc/6.4.3.0-patched.17+vpt.1`, `ping -s 1400` 0 % loss, no `truncated-ip` in `tcpdump`.
vpt-pi4 (DEVICE3 Tello-C5B142 on wlan1, DEVICE4 Tello-F014A0 on wlan2): install the same package,
reboot with the owner able to power-cycle the Pi, then both device tiles must show video.
