# BUG-0429 — The Switch controller daemon took the first Bluetooth adapter, not its own

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0429                                                     |
| Reported  | 2026-10-06                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium                                                       |
| Area      | backend_host / switch controller (vpt-procon)                |
| Fixed in  | Unreleased                                                   |
| Commit    | `a13b056b2`                                                  |

---

## Symptom

Found before it bit, while moving the Nintendo Switch's Pro Controller from vpt-pi1's onboard
adapter to a USB dongle on vpt-pi3. vpt-pi3's onboard `hci0` runs stb4's BLE remote; the
dongle is `hci1`. Installed as it was, `install_procon.sh --adapter hci1` would have:

- disabled `vpt-ble-remote.service`, which resumes **every** BLE STB remote at boot, so stb4
  on `hci0` would lose its remote at the next reboot;
- started a daemon whose Pro Controller sits on whatever adapter nxbt finds first (likely
  `hci0`), taking stb4's adapter.

## Root cause

- `procon_daemon.py` called `nx.create_controller(nxbt.PRO_CONTROLLER)` without
  `adapter_path`. nxbt then uses `usable_adapters[0]`, ignoring `PROCON_ADAPTER`.
- `bonded_switches()` used `nx.get_switch_addresses()`, which lists Switches bonded to any
  adapter on the host.
- `install_procon.sh` put the host-wide `vpt-ble-remote.service` in the per-adapter unit list.

All three assumed one Bluetooth adapter per host.

## Fix

- `backend_host/src/controllers/switch/procon/procon_daemon.py`: `ADAPTER_PATH =
  /org/bluez/$PROCON_ADAPTER`, passed to both `create_controller` calls. Bonded Switches are
  only those whose D-Bus path is under that adapter.
- `setup/local/linux/backend_host/install_procon.sh`: `vpt-ble-remote.service` is disabled
  only when no other adapter still has a `DEVICE<n>_BLE_ADAPTER_HCI` in `.env`. Otherwise the
  installer logs `kept vpt-ble-remote.service: BLE STB remote still on hciN`.

## Verification

On vpt-pi3, 2026-10-06 (`install_procon.sh --adapter hci1`):
- the installer kept `vpt-ble-remote.service`; `/status` reported `adapter hci1`
  (`00:0A:CD:45:C6:7C`, class `0x002508`); `hci0` kept its address and is not discoverable;
- the Switch paired through Change Grip/Order (opened with vpt-pi1's controller), and
  `POST /host/av/switch/command` `press:down` / `press:right` moved the Home menu focus;
- stb4's remote on `hci0` re-registered GATT after the bluetoothd restart, and `CHANNEL_UP`
  changed its channel from itv3 to itv4.
