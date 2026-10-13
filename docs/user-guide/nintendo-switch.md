# Nintendo Switch: pairing and control

A stock Nintendo Switch is driven by a host that pretends to be a wireless **Pro
Controller** over Bluetooth. The Switch needs no modification, and nothing is plugged
into it except its dock's HDMI out (captured like any other device).

## Pair once
1. Open the device's remote panel ("Nintendo Switch") and click **Pair**. The status shows
   *pairing* for 3 minutes.
2. On the Switch, open **Controllers → Change Grip/Order** and stay on that screen.
3. Within a few seconds the controller appears on the Switch and the panel status turns
   **connected**. Close the Switch screen.

After that the host reconnects by itself (after a Switch reboot, a dropped link or a
host restart): no need to pair again.

## Use
Click the buttons on the controller picture: A/B/X/Y, D-pad, + / −, Home, Capture, both
sticks (click the edge of a stick to push it in that direction, the centre to press
it), and L / ZL / R / ZR at the top. Tests and the AI agent use the same commands
(`press:a`, `stick:left,up`, …).

## If it doesn't connect
- **Status "disconnected":** wake the Switch (press its power button or a button on a
  Joy-Con); the host retries every 15 s.
- **The Switch shows an error, or refuses the controller:** on the Switch, go to **System
  Settings → Controllers and Sensors → Disconnect Controllers** (your Joy-Cons re-pair by
  attaching them to the console), then do *Pair once* again.
- **Nothing appears on Change Grip/Order:** click **Pair** again (the window lasts 3 min),
  and make sure the Switch is within a few metres of the host that has the Bluetooth
  controller.

Setup and internals (for operators): `docs/agent/devices/NINTENDO_SWITCH.md`.
