#!/usr/bin/env python3
"""
Arrival-day check of one Tello (TASK-32 runbook steps 3 and 4). No VirtualPyTest host needed.

Without --hover nothing spins: it connects, reads the SDK version, battery and temperature, starts the
video, saves one frame and measures the command round trip. With --hover the drone takes off, holds for
--hold_s seconds, turns 90° and back, and lands. Ctrl-C at any point lands it.

    python3 test_scripts/drone/local/tello_check.py --drone 1                    # netns layout, drone 1
    python3 test_scripts/drone/local/tello_check.py --ip 192.168.10.1 --hover    # host joined the Tello's Wi-Fi directly
    python3 test_scripts/drone/local/tello_check.py --sim --hover                # against the simulator
    python3 test_scripts/drone/local/tello_check.py --drone 1 --markers          # which ArUco ids are in view
"""
import argparse
import os
import statistics
import sys
import time

current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.abspath(os.path.join(current_dir, "..", "..", ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

import cv2

from shared.src.lib.drone.tello import TelloClient, TelloError, tello_endpoints
from shared.src.lib.drone.video import FrameGrabber

BAT_TAKEOFF = 40
TEMP_MAX = 85


def report_markers(grabber: FrameGrabber, frames: int = 10) -> None:
    """ArUco ids seen in the next frames, with the tag's side in pixels (range test, runbook step 6)."""
    detector = cv2.aruco.ArucoDetector(cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50))
    seen = {}
    for _ in range(frames):
        frame = grabber.wait_frame(newer_than=time.time(), timeout_s=3)
        if frame is None:
            continue
        corners, ids, _ = detector.detectMarkers(frame)
        for c, i in zip(corners, [] if ids is None else ids.ravel()):
            seen.setdefault(int(i), []).append(abs(cv2.contourArea(c)) ** 0.5)
    if not seen:
        print(f"  markers: none in {frames} frames")
    for i, sides in sorted(seen.items()):
        print(f"  marker {i}: in {len(sides)}/{frames} frames, ~{statistics.median(sides):.0f} px wide")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--drone", type=int, default=1, help="index in the netns layout (10.200.<i>.2)")
    p.add_argument("--ip", help="drone address (overrides --drone)")
    p.add_argument("--state_port", type=int)
    p.add_argument("--video_port", type=int)
    p.add_argument("--sim", action="store_true", help="start a simulator for this drone first")
    p.add_argument("--hover", action="store_true", help="take off, hold, turn, land")
    p.add_argument("--hold_s", type=float, default=5.0)
    p.add_argument("--markers", action="store_true", help="report the ArUco ids (DICT_4X4_50) in the frame and their size")
    p.add_argument("--out", default="/tmp/tello_check.jpg")
    a = p.parse_args()

    ep = tello_endpoints(a.drone)
    ip = a.ip or ep["ip"]
    state_port = a.state_port or ep["state_port"]
    video_port = a.video_port or ep["video_port"]

    sim = None
    if a.sim:
        from shared.src.lib.drone.sim.tello_sim import TelloSim
        from shared.src.lib.drone.sim.world import default_room
        ip = f"127.0.0.1{a.drone}"
        sim = TelloSim(default_room(), a.drone, ip, state_port=state_port, video_port=video_port)
        sim.start()

    client = TelloClient(ip, state_port=state_port, name=f"drone{a.drone}")
    grabber = FrameGrabber(f"udp://0.0.0.0:{video_port}")
    airborne = False
    try:
        client.connect()
        print(f"connected to {ip} (state :{state_port}, video :{video_port})")
        print(f"  sdk: {client.send('sdk?')}")
        bat = int(client.send("battery?"))
        deadline = time.time() + 3
        while not client.state() and time.time() < deadline:   # first state datagram (~10 Hz)
            time.sleep(0.1)
        if not client.state():
            print(f"  ⚠️ no state datagram on :{state_port} (telemetry gates will not work)")
        temp = client.state().get("temph")
        print(f"  battery: {bat} %   temperature: {temp} °C")

        rtts = []
        for _ in range(5):
            t = time.time()
            client.send("battery?")
            rtts.append((time.time() - t) * 1000)
        print(f"  command round trip: median {statistics.median(rtts):.0f} ms")

        grabber.start()
        t = time.time()
        client.send_ok("streamon")
        frame = grabber.wait_frame(newer_than=t, timeout_s=10)
        if frame is None:
            print("❌ no video frame within 10 s: check that nothing else listens on the video port")
            return 1
        cv2.imwrite(a.out, frame)
        print(f"  first frame after {time.time() - t:.1f} s, {frame.shape[1]}x{frame.shape[0]} -> {a.out}")
        if a.markers:
            report_markers(grabber)

        if not a.hover:
            print("✅ link, telemetry and video OK (no flight: add --hover)")
            return 0
        if bat < BAT_TAKEOFF or (temp is not None and temp >= TEMP_MAX):
            print(f"❌ not taking off: battery {bat} % (floor {BAT_TAKEOFF}) / temperature {temp} °C (max {TEMP_MAX})")
            return 1

        for s in range(3, 0, -1):
            print(f"  takeoff in {s}...")
            time.sleep(1)
        airborne = True
        client.start_keepalive()
        for cmd, timeout in (("takeoff", 20), ("cw 90", 10), ("ccw 90", 10)):
            ok = client.send_ok(cmd, timeout_s=timeout)
            print(f"  {cmd}: {'ok' if ok else 'FAILED'}   height {client.state().get('h')} cm")
            if not ok:
                return 1
            if cmd == "takeoff":
                time.sleep(a.hold_s)
        print("✅ hover test passed")
        return 0
    except TelloError as e:
        print(f"❌ {e}")
        return 1
    except KeyboardInterrupt:
        print("interrupted")
        return 1
    finally:
        if airborne:
            try:
                print(f"  land: {client.send('land', timeout_s=20)}")
            except TelloError as e:
                print(f"❌ land failed: {e} — land it by hand")
        client.stop_keepalive()
        grabber.stop()
        client.close()
        if sim:
            sim.stop()


if __name__ == "__main__":
    sys.exit(main())
