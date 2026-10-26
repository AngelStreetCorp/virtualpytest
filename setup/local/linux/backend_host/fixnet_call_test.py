#!/usr/bin/env python3
"""
fixnet_call_test.py — place and receive calls on the FX lines of a PFR.

Self-contained on purpose: it imports NOTHING from this repository. The client
PFR's checkout may be behind main, and this script has to work the moment you
drop it on the box. Only pyserial is required (apt: python3-serial).

It also does not need /dev/fx1..fx4 to exist. If those names are missing it
finds each modem by its USB topology port and tells you what it used, because
cdc_acm's /dev/ttyACM numbering is unstable and the port is not.

    python3 fixnet_call_test.py selftest
    python3 fixnet_call_test.py call --modem 3 --number 5551234
    python3 fixnet_call_test.py ring  --modem 4
    python3 fixnet_call_test.py dtmf  --modem 3 --modem 4

    --modem N    1-based line number. N maps to USB port 5-N on a full rack.
                 Repeat the flag to test several lines in one run.
    --list       show what was found and exit

    call and ring never dial anything by default: `call` refuses to run without
    an explicit --number, so a typo cannot dial.
"""

import argparse
import glob
import os
import re
import sys
import time

MODEM_VID = "0572"   # Conexant Systems (Rockwell)
MODEM_PID = "1349"   # CX9300x family
COUNTRY_CODE = os.environ.get("FIXNET_GCI", "A6")   # T.35: A6 = Switzerland
BAUD = 115200

GREEN, RED, YELLOW, CYAN, OFF = "\033[32m", "\033[31m", "\033[33m", "\033[36m", "\033[0m"
if not sys.stdout.isatty():
    GREEN = RED = YELLOW = CYAN = OFF = ""


# ---------------------------------------------------------------------------
# finding the modems
# ---------------------------------------------------------------------------

def usb_parent(path):
    """Walk sysfs up to the USB device node (the one with idVendor)."""
    p = os.path.realpath(path)
    for _ in range(12):
        if p == "/" or not p:
            break
        if os.path.isfile(os.path.join(p, "idVendor")):
            return p
        p = os.path.dirname(p)
    return None


def modem_ports():
    """[(usb_port, /dev/ttyACM*)] for every 0572:1349, in ascending port order."""
    found = []
    for d in glob.glob("/sys/bus/usb/devices/*/"):
        vid = os.path.join(d, "idVendor")
        if not os.path.isfile(vid):
            continue
        try:
            if open(vid).read().strip() != MODEM_VID:
                continue
            if open(os.path.join(d, "idProduct")).read().strip() != MODEM_PID:
                continue
        except OSError:
            continue
        port = os.path.basename(d.rstrip("/"))
        node = os.path.realpath(d)
        for t in glob.glob("/sys/class/tty/ttyACM*"):
            parent = usb_parent(os.path.join(t, "device"))
            if parent and os.path.realpath(node) == parent:
                found.append((port, f"/dev/{os.path.basename(t)}"))
                break
        else:
            found.append((port, None))   # claimed, but cdc_acm bound nothing
    found.sort(key=lambda x: [int(p) if p.isdigit() else p
                              for p in re.split(r"[-.:]", x[0])])
    return found


def resolve(modem_no):
    """Line N (1-based) -> a usable device path, preferring /dev/fxN."""
    fx = f"/dev/fx{modem_no}"
    if os.path.exists(fx):
        return fx, f"/dev/fx{modem_no} (udev)"
    alt = f"/dev/fixnet/modem{modem_no - 1}"
    ports = modem_ports()
    if modem_no - 1 < len(ports):
        port, tty = ports[modem_no - 1]
        if os.path.exists(alt):
            return alt, f"{alt} -> USB port {port}"
        if tty:
            return tty, f"{tty} -> USB port {port}  (NO udev name yet)"
        return None, f"USB port {port} present but cdc_acm bound no tty node"
    if os.path.exists(alt):
        return alt, alt
    return None, (f"line {modem_no} does not exist -- only {len(ports)} "
                  f"modem(s) found on this host")


# ---------------------------------------------------------------------------
# AT channel
# ---------------------------------------------------------------------------

class ATError(Exception):
    pass


class AT:
    def __init__(self, port, timeout=3.0):
        try:
            import serial
        except ImportError:
            sys.exit("pyserial missing.  sudo apt-get install -y python3-serial")
        self.port = port
        self.timeout = timeout
        self.s = serial.Serial(port, BAUD, timeout=0.2, write_timeout=2)
        time.sleep(0.3)
        self._drain()
        # The modem boots on the US line profile (B5), which makes it call a
        # Swiss FXS loop a digital line ("DIGITAL LINE DETECTED") and refuse
        # it. Set the country on every open; it does not survive ATZ.
        self.try_cmd(f"AT+GCI={COUNTRY_CODE}")

    def close(self):
        try:
            self.s.close()
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()

    def _drain(self, seconds=0.4):
        end = time.time() + seconds
        while time.time() < end:
            try:
                line = self.s.readline()
            except Exception:
                break
            if not line:
                continue
            t = line.decode(errors="replace").strip()
            if t in ("OK", "ERROR"):
                break

    def cmd(self, command, timeout=None):
        timeout = timeout or self.timeout
        self.s.reset_input_buffer()     # drop URCs/strays: this read must see
        self.s.write((command + "\r\n").encode())   # only this command's reply
        self.s.flush()
        end = time.time() + timeout
        lines = []
        while time.time() < end:
            raw = self.s.readline()
            if not raw:
                continue
            line = raw.decode(errors="replace").strip()
            if line.upper() == command.upper():
                continue                      # firmware echo
            if line in ("OK", "ERROR"):
                if line == "ERROR":
                    raise ATError(f"{command} -> ERROR")
                return "\n".join(lines).strip()
            if line.startswith("+CME ERROR"):
                raise ATError(f"{command} -> {line}")
            if line in ("NO CARRIER", "BUSY", "NO ANSWER", "NO DIALTONE", "CONNECT"):
                return "\n".join(lines + [line]).strip()
            if line:
                lines.append(line)
        raise ATError(f"{command} -> no reply within {timeout}s")

    def try_cmd(self, command, timeout=None):
        try:
            return True, self.cmd(command, timeout)
        except ATError as e:
            return False, str(e)
        except Exception as e:
            return False, f"{type(e).__name__}: {e}"

    def wait_for(self, pattern, timeout):
        rx = re.compile(pattern, re.I)
        end = time.time() + timeout
        seen = []
        while time.time() < end:
            raw = self.s.readline()
            if not raw:
                continue
            line = raw.decode(errors="replace").strip()
            if not line:
                continue
            seen.append(line)
            if rx.search(line):
                return line, seen
        return None, seen

    def dial(self, number, timeout):
        """ATDT...; then read until the call resolves.

        This cannot go through cmd(): the modem answers a dial with CONNECT or
        NO CARRIER, and cmd() would consume that line as its own reply -- which
        would then leave wait_for() with nothing to find and report a connected
        call as a failed one.
        """
        self.s.reset_input_buffer()
        self.s.write(f"ATDT{number};\r\n".encode())
        self.s.flush()
        return self.wait_for(DIAL_OUTCOMES, timeout)


# ---------------------------------------------------------------------------
# per-line actions
# ---------------------------------------------------------------------------

def selftest(port):
    with AT(port, 3.0) as at:
        rows = []
        for name, cmd in (("AT", "AT"), ("firmware", "ATI3"),
                          ("FCLASS offers 8", "AT+FCLASS=?"),
                          ("enter voice mode", "AT+FCLASS=8"),
                          ("VLS reads back", "AT+VLS?"),
                          ("VSM codecs", "AT+VSM=?"),
                          ("VNH hangup", "AT+VNH?")):
            if name == "VLS reads back":
                # a fresh modem reports line 0 (none selected); select line 1
                # first, as place_call() does, then check it stuck
                sel_ok, sel_detail = at.try_cmd("AT+VLS=1")
                ok, detail = at.try_cmd(cmd) if sel_ok else (False, sel_detail)
                ok = ok and detail.strip() == "1"
            else:
                ok, detail = at.try_cmd(cmd)
            if name == "VSM codecs":
                detail = f"{len([l for l in detail.splitlines() if l.strip()])} codec line(s)"
            rows.append((name, ok, detail.replace("\n", " ")[:56]))
    return rows


DTMF_CANDIDATES = [
    ("digit index", "AT+VTS=1"),
    ("digit braced", "AT+VTS={1}"),
    ("tone pair bracketed", "AT+VTS=[697,1209,50]"),
    ("tone pair bare", "AT+VTS=697,1209,50"),
    ("tone pair + flag", "AT+VTS=697,1209,50,0"),
    ("freq + duration", "AT+VTS=697,1209,200"),
    ("Conexant VDTMF", "AT+VDTMF=1"),
    ("VDTMF braced", "AT+VDTMF={1}"),
    ("VTS query", "AT+VTS=?"),
]


def dtmf(port):
    with AT(port, 3.0) as at:
        at.try_cmd("AT+FCLASS=8")
        at.try_cmd("AT+VLS=1")
        out = []
        for label, cmd in DTMF_CANDIDATES:
            ok, detail = at.try_cmd(cmd, 4.0)
            out.append((label, cmd, ok, detail.split("->")[-1].strip()))
    return out


DIAL_OUTCOMES = r"^(CONNECT|NO CARRIER|BUSY|NO ANSWER|NO DIALTONE)"


def place_call(port, number, hold=2.0):
    """Dial in plain data mode (ATX4 checks dial tone), the path proven on the
    rack. Voice-mode ATDT..; answers OK without saying whether anything
    happened. The far end proves the call: run `ring` there. A call nobody
    answers stays "ringing" until `hold` seconds are up, then we hang up."""
    log = []
    with AT(port, 3.0) as at:
        log.append(("reset", *at.try_cmd("ATZ")))
        log.append(("country", *at.try_cmd(f"AT+GCI={COUNTRY_CODE}")))
        log.append(("dial tone check", *at.try_cmd("ATX4")))
        at.s.reset_input_buffer()
        at.s.write(f"ATDT{number}\r\n".encode())
        at.s.flush()
        line, seen = at.wait_for(DIAL_OUTCOMES, max(hold, 3.0) + 8.0)
        bad = bool(line) and re.match(r"^(NO CARRIER|BUSY|NO ANSWER|NO DIALTONE)", line)
        ringing = line is None             # nothing refused it: far end is ringing
        ok = not bad
        log.append((f"dial {number}", ok,
                    "ringing (no answer yet)" if ringing else line))
        log.append(("hang up", *at.try_cmd("ATH")))
        return ok, log, seen


def wait_ring(port, timeout):
    with AT(port, 3.0) as at:
        at.s.reset_input_buffer()
        line, seen = at.wait_for(r"^RING", timeout)
        return line, seen          # the matched line itself, not a bool


# ---------------------------------------------------------------------------

def main():
    p = argparse.ArgumentParser(description="Call and receive on the FX lines.")
    p.add_argument("command", choices=["list", "selftest", "dtmf", "call", "ring"])
    p.add_argument("--modem", type=int, action="append",
                   help="1-based line number; repeat for several")
    p.add_argument("--number", help="number to dial (required for call)")
    p.add_argument("--timeout", type=float, default=60.0, help="ring wait seconds")
    p.add_argument("--hold", type=float, default=2.0)
    args = p.parse_args()

    print(f"\n{CYAN}== FX modems on this host =={OFF}")
    ports = modem_ports()
    if not ports:
        print(f"  {RED}no {MODEM_VID}:{MODEM_PID} modem found on any USB port{OFF}")
        print("  Check: lsusb | grep -i 0572")
        return 2
    for i, (port, tty) in enumerate(ports, start=1):
        print(f"  line {i}  USB port {port:<6} {tty or '(cdc_acm bound nothing)'}")

    if args.command == "list":
        return 0

    lines = args.modem or [1]
    if args.command == "call" and not args.number:
        print(f"\n  {RED}refusing to dial without --number{OFF}")
        return 2

    rc = 0
    for n in lines:
        port, how = resolve(n)
        print(f"\n{CYAN}== line {n} =={OFF}")
        if not port:
            print(f"  {RED}not usable: {how}{OFF}")
            rc = 1
            continue
        print(f"  using {port}   ({how})")

        if args.command == "selftest":
            rows = selftest(port)
            w = max(len(r[0]) for r in rows)
            for name, ok, detail in rows:
                print(f"  [{GREEN}ok  {OFF}] {name.ljust(w)}  {detail}" if ok
                      else f"  [{RED}FAIL{OFF}] {name.ljust(w)}  {detail}")
            bad = [r for r in rows if not r[1]]
            print(f"  {len(rows)-len(bad)}/{len(rows)} passed")
            rc |= 1 if bad else 0

        elif args.command == "dtmf":
            rows = dtmf(port)
            w = max(len(r[0]) for r in rows)
            ok_n = 0
            for label, cmd, ok, detail in rows:
                if ok:
                    ok_n += 1
                print(f"  [{GREEN}ok {OFF}]" if ok else f"  [{RED}no {OFF}]",
                      f" {label.ljust(w)}  {cmd.ljust(24)} {detail}")
            print(f"\n  {ok_n} form(s) accepted.")
            print(f"  {YELLOW}ACCEPTED IS NOT VERIFIED{OFF} — a digit must be heard")
            print("  at the far end before goal 2 is done.")

        elif args.command == "call":
            connected, log, seen = place_call(port, args.number, args.hold)
            for name, ok, detail in log:
                print(f"  [{GREEN}ok  {OFF}] {name.ljust(20)} {detail}" if ok
                      else f"  [{RED}FAIL{OFF}] {name.ljust(20)} {detail}")
            for s in seen[-8:]:
                print(f"    < {s}")
            if connected:
                print(f"  {GREEN}dialled — check the other terminal for RING on the called line{OFF}")
            else:
                print(f"  {RED}dial refused{OFF}")
                print("      The loop closed (it dialled), so check the far end, SIP")
                print("      registration, and relay insertion loss through the switch.")
                rc = 1

        elif args.command == "ring":
            print(f"  waiting up to {args.timeout:.0f}s for RING — place a call to this line NOW")
            got, seen = wait_ring(port, args.timeout)
            for s in seen[-8:]:
                print(f"    < {s}")
            if got:
                print(f"  {GREEN}RING detected: {got}{OFF}")
            else:
                print(f"  {RED}no RING in {args.timeout:.0f}s{OFF}")
                print("      Is the far end ringing? Is the gateway registered to SIP?")
                print("      Does the FXS port have loop current?")
                rc = 1
    return rc


if __name__ == "__main__":
    sys.exit(main())