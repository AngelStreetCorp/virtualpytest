#!/usr/bin/env python3
"""Local demo of the drone profile's telemetry path, no hardware, no host (TASK-90 goal 12).

  bridge writer  ->  <out>/telemetry_status.json (+ telemetry_hud.txt)  ->  TelemetryAnalyzer  ->  <out>/frame.json (what the monitor puts in a frame JSON)

`--source sim`      a Tello simulator on loopback flown through the real TelloRemoteController (the controller writes the status file itself)
`--source scripted` a scripted flight written through the same writer: takeoff, cruise, battery draining to 18 %, temperature rising, a GPS fix
                    appearing, then a radio dropout while flying (telemetry_lost), then recovery and landing. `--speed 10` plays it 10x faster.

Every `--frame-every` seconds the analyzer's result for the newest reading is written to <out>/frame.json (the document the mock host serves to
the stream modal) and appended to <out>/timeline.jsonl. Usage:
  python3 scripts/drone_telemetry_demo.py --out .local-data/drone/run1 --source scripted --speed 10
"""
import argparse
import json
import os
import socket
import sys
import time

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
for p in (os.path.join(ROOT, 'backend_host', 'scripts'), ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)

from monitor.analyzers.telemetry import TelemetryAnalyzer  # noqa: E402
from monitor.profiles import load_profile  # noqa: E402
from shared.src.lib.drone import telemetry_status as ts  # noqa: E402


def scripted_state(t):
    """(state dict, flying, gps or None, silent) of the scripted flight at second t."""
    flying = 4 <= t < 118
    air = max(0.0, min(1.0, (t - 4) / 6.0)) if t < 100 else max(0.0, 1.0 - (t - 100) / 12.0)
    bat = max(15, 100 - int(t * 0.75))
    state = {'bat': bat, 'templ': 50 + int(t / 6), 'temph': min(86, 54 + int(t / 3)), 'h': int(130 * air) if flying else 0,
             'vgx': int(8 * air * (1 + (t % 12) / 12)) if flying else 0, 'vgy': int(3 * air) if flying else 0, 'vgz': 0,
             'yaw': int((t * 9) % 360) - 180, 'time': int(max(0, t - 4))}
    gps = {'lat': 47.37691 + t * 2e-6, 'lon': 8.54169 + t * 1e-6, 'fix': 3} if 60 <= t < 118 else None
    silent = 84 <= t < 96          # a radio dropout while flying
    return state, flying, gps, silent


def replay_to(args):
    """Deterministic: play the scripted flight up to second `args.at` on a virtual clock (1 s steps, no sleeping) through the real writer's
    record and the analyzer, and leave that moment in <out>/frame.json and telemetry_status.json. For screenshots of one moment."""
    os.makedirs(args.out, exist_ok=True)
    analyzer = TelemetryAnalyzer(None, load_profile('drone'), metadata_dir_fn=lambda f: args.out)
    analyzer.register_device('capture1')
    base = 1_000_000.0
    last_good = None
    result = None
    for sec in range(0, int(args.at) + 1):
        t = float(sec)
        state, flying, gps, silent = scripted_state(t)
        if not silent:
            last_good = (base + t, ts.build_status(state, {'x': 100 + t * 3, 'y': 100 + t * 2}, flying=flying, source='scripted', gps=gps, now=base + t))
        status, age = (last_good[1], base + t - last_good[0]) if last_good else (None, None)
        result = analyzer.process_status('capture1', status, age, base + t)
    frame = {'analyzed': True, 'filename': 'capture_000000001.jpg', 'timestamp': time.strftime('%Y-%m-%dT%H:%M:%S'), 'profile': 'drone', **result}
    with open(os.path.join(args.out, 'frame.json'), 'w') as f:
        json.dump(frame, f)
    if last_good:
        ts.write_atomic(os.path.join(args.out, ts.STATUS_FILE), json.dumps(last_good[1]))
        ts.write_atomic(os.path.join(args.out, ts.HUD_FILE), ts.hud_text(last_good[1] if age is not None and age <= ts.TELEMETRY_MAX_AGE_S else None))
    print(json.dumps({k: frame[k] for k in ('telemetry', 'events', 'incidents', 'kpis') if k in frame}))


def run(args):
    if args.at is not None:
        return replay_to(args)
    os.makedirs(args.out, exist_ok=True)
    profile = load_profile('drone')
    analyzer = TelemetryAnalyzer(None, profile, metadata_dir_fn=lambda f: args.out)
    analyzer.register_device('capture1')
    stop = []
    sim = ctrl = writer = None
    t0 = time.time()
    clock = lambda: (time.time() - t0) * args.speed       # noqa: E731  (seconds of the scripted flight)

    if args.source == 'sim':
        from backend_host.src.controllers.remote.tello import TelloRemoteController
        from shared.src.lib.drone.sim.tello_sim import TelloSim
        from shared.src.lib.drone.sim.world import Pose, default_room

        def free():
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.bind(('127.0.0.1', 0))
            port = s.getsockname()[1]
            s.close()
            return port
        cmd, state_port = free(), free()
        sim = TelloSim(default_room(), 3, '127.0.0.1', cmd_port=cmd, state_port=state_port, video_port=free(), drift=0.0, seed=1,
                       start_pose=Pose(100, 100, 0, 0))
        sim.start()
        os.environ['DEVICE1_TELEMETRY_BURN_IN'] = '1' if args.burn_in else '0'
        ctrl = TelloRemoteController(tello_ip='127.0.0.1', cmd_port=cmd, state_port=state_port, local_ip='127.0.0.1', local_cmd_port=free(),
                                     name='demo', telemetry_status_dir=args.out, device_id='device1')
        ctrl.connect()
        ctrl.execute_command('takeoff')
        steps = [('move', {'direction': 'forward', 'cm': 150}), ('rotate', {'direction': 'cw', 'deg': 90}), ('move', {'direction': 'up', 'cm': 60}),
                 ('move', {'direction': 'forward', 'cm': 100}), ('land', {})]
        step = [0, time.time()]
    else:
        def sample():
            t = clock()
            state, flying, gps, silent = scripted_state(t)
            if silent:
                return None                                  # nothing fresh to say: the file ages into "no telemetry"
            return ts.build_status(state, {'x': 100 + t * 3, 'y': 100 + t * 2}, flying=flying, source='scripted', gps=gps)
        writer = ts.TelemetryStatusWriter(args.out, sample, burn_in=args.burn_in)
        writer.start()

    last_frame = 0.0
    try:
        while True:
            now = time.time()
            if args.source == 'sim' and now - step[1] > 1.5 and step[0] < len(steps):
                ctrl.execute_command(*steps[step[0]])
                step[0] += 1
                step[1] = now
            if args.source == 'scripted' and clock() > args.seconds:
                break
            if args.source == 'sim' and step[0] >= len(steps) and now - step[1] > 3:
                break
            status, age = ts.read_status(args.out)
            result = analyzer.process_status('capture1', status, age, now)
            if now - last_frame >= args.frame_every:
                last_frame = now
                frame = {'analyzed': True, 'filename': 'capture_000000001.jpg', 'timestamp': time.strftime('%Y-%m-%dT%H:%M:%S'), 'profile': 'drone', **result}
                tmp = os.path.join(args.out, 'frame.json.tmp')
                with open(tmp, 'w') as f:
                    json.dump(frame, f)
                os.replace(tmp, os.path.join(args.out, 'frame.json'))
                with open(os.path.join(args.out, 'timeline.jsonl'), 'a') as f:
                    f.write(json.dumps({'t': round(clock() if args.source == 'scripted' else now - t0, 1), 'telemetry': result['telemetry'],
                                        'events': sorted(result['events']), 'incidents': {k: v['active'] for k, v in result.get('incidents', {}).items()},
                                        'kpis': result['kpis']}) + '\n')
            time.sleep(0.1)
    except KeyboardInterrupt:
        pass
    finally:
        if writer:
            writer.stop(final=lambda st: dict(st, flying=False))
        if ctrl:
            ctrl.disconnect()
        if sim:
            sim.stop()


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--out', required=True, help='the device metadata folder to write into (created)')
    ap.add_argument('--source', choices=('scripted', 'sim'), default='scripted')
    ap.add_argument('--speed', type=float, default=1.0, help='scripted flight: times real time')
    ap.add_argument('--seconds', type=float, default=130.0, help='scripted flight: length in flight seconds')
    ap.add_argument('--at', type=float, default=None, help='scripted flight: write the moment at this flight second and exit (virtual clock)')
    ap.add_argument('--frame-every', type=float, default=0.5)
    ap.add_argument('--burn-in', action='store_true', help='also keep telemetry_hud.txt for the burn-in')
    run(ap.parse_args())
