# Nintendo Switch: pairing and control

A stock Nintendo Switch is controlled by a host that acts as a wireless **Pro Controller** over
Bluetooth. Nothing needs changing on the Switch. Only its dock's HDMI output is plugged in, and it
is captured like any other device.

## Pair once

1. Open the device's remote panel ("Nintendo Switch") and click **Pair**. The status shows
   *pairing* for a short time, about 3 minutes.
2. On the Switch, open **Controllers → Change Grip/Order** and stay on that screen.
3. Within a few seconds the controller appears on the Switch, and the panel status turns
   **connected**. Close the Switch screen.

After that, the host reconnects by itself, after a Switch reboot, a dropped link or a host restart.
You do not need to pair again.

## Use

Click the buttons on the controller picture: A, B, X and Y, the D-pad, + and −, Home, Capture, both
sticks, and L, ZL, R and ZR at the top. To push a stick in one direction, click its edge. To press
it, click its centre. Tests and the AI agent use the same buttons.

<div data-technical>

The commands look like `press:a` and `stick:left,up`.

</div>

## If it doesn't connect

- **Status "disconnected":** wake the Switch by pressing its power button or a button on a Joy-Con.
  The host retries every 15 s.
- **The Switch shows an error, or refuses the controller:** on the Switch, go to **System
  Settings → Controllers and Sensors → Disconnect Controllers**. Your Joy-Cons pair again when you
  attach them to the console. Then do *Pair once* again.
- **Nothing appears on Change Grip/Order:** click **Pair** again. The window lasts 3 min. Keep the
  Switch within a few metres of the host that has the Bluetooth controller.

Setup and internals (for operators): `docs/agent/devices/NINTENDO_SWITCH.md`.
