/**
 * useDroneWifiStatus — is the Tello's Wi-Fi AP in range, and are we on it?
 *
 * A Tello is its own access point and only broadcasts while it is powered on, so
 * "no stream" on a drone has two very different causes that the generic player
 * cannot tell apart: the drone is off, or the drone is on but landed (a landed
 * Tello sends no HLS at all). This hook separates them from real host data and
 * is what lets RecHostPreview say something true instead of "stream restart
 * required".
 *
 * The three states, and what the user does in each:
 *   ap-not-found  — no TELLO-* SSID in the host's scan. Nothing to connect to.
 *   connecting    — an SSID appeared; the page joins it (the AP is the drone's).
 *   connected     — paired and the controller is bound to the drone.
 *
 * It joins on its own, but only while it is mounted — and it is only mounted
 * inside the open device preview, so merely browsing /device-control never
 * changes the host's network. Joining moves the host's wlan onto the drone's AP,
 * which costs a Wi-Fi-only host its uplink for a moment.
 */
import { useCallback, useEffect, useRef, useState } from 'react';

import { api } from '../../utils/apiClient';
import { buildServerUrl } from '../../utils/buildUrlUtils';
import { Host, Device } from '../../types/common/Host_Types';

export type DroneLinkState =
  | 'unknown'
  | 'ap-not-found'
  | 'connecting'
  | 'connected'
  | 'error';

export interface DroneWifiStatus {
  state: DroneLinkState;
  /** The SSID we are on or joining, when known. */
  ssid: string | null;
  /** Scan signal strength of that SSID, when known. */
  signal: number | null;
  /** One line the preview can show under the headline. */
  detail: string | null;
  /** Seconds until the next automatic scan (counts down from POLL_MS/1000). */
  secondsToNextScan: number;
  /** A scan or pair request is in flight right now. */
  busy: boolean;
  /** Ask for an immediate re-scan instead of waiting for the next tick. */
  rescan: () => void;
}

/**
 * A host scan is not cheap: the host rescan alone sleeps ~2s before listing, and
 * a pair attempt joins an access point. 20s keeps a parked drone responsive
 * without hammering the radio.
 */
const POLL_MS = 20000;

interface TelloAp {
  ssid: string;
  signal: number | null;
}

interface StatusResponse {
  success?: boolean;
  linked?: boolean;
  last_error?: string | null;
}

interface ScanResponse {
  success?: boolean;
  tellos?: TelloAp[];
}

interface PairResponse {
  success?: boolean;
  ssid?: string;
  error?: string;
  stage?: string;
}

const DEFAULT_DRONE_IP = '192.168.10.1';

/**
 * What the preview says about a drone, per state. `connected` is deliberately
 * absent from the overlay: once the drone is on its AP the tile is expected to
 * go quiet until it flies, and a "connected" banner over a black frame is noise.
 *
 * Two lines, not one sentence. The earlier single headline carried the whole
 * explanation ("Can't find Tello Wi-Fi — please power on the drone") and the
 * server's raw error text underneath it, which made the tile read like a stack
 * trace. The headline says what is true, the hint says what to do, and the raw
 * error never reaches the tile — it is a diagnostic, not a message.
 *
 * Lives here, beside the state type, so the wording and the state machine cannot
 * drift apart and so `droneHintLine` below is testable without the component.
 */
export const DRONE_WIFI_HEADLINE: Record<DroneLinkState, string> = {
  unknown: 'Checking…',
  'ap-not-found': 'AP unavailable',
  connecting: 'Connecting…',
  connected: 'Connected',
  error: 'AP check failed',
};

/** The "what do I do about it" line. Empty when there is nothing to add. */
export const DRONE_WIFI_HINT: Record<DroneLinkState, string> = {
  unknown: '',
  'ap-not-found': 'Power on the drone',
  connecting: '',
  connected: '',
  // Host-agnostic on purpose. This line also covers a pair that failed AFTER a
  // successful scan — the host was demonstrably reachable then, so naming it
  // ("vpt-pi4 cannot be reached") blamed the wrong machine, and it lingered for
  // up to 20s while the retry was already under way.
  error: 'Could not reach the drone',
};

/**
 * The line under the headline — or '' when there is nothing honest to say.
 *
 * A failed poll leaves `error` in place until the NEXT poll settles, so the
 * "cannot be reached" hint used to sit on the tile for up to 20s while the scan
 * was already back in flight. A stale complaint about a request that is already
 * being retried is worse than no line at all, so `busy` suppresses it.
 */
export function droneHintLine(
  state: DroneLinkState,
  busy: boolean,
  ssid: string | null,
  signal: number | null
): string {
  if (busy && state === 'error') return '';
  return (
    DRONE_WIFI_HINT[state] ||
    ssid ||
    (signal != null ? `signal ${signal}%` : '')
  );
}

export function useDroneWifiStatus(
  host: Host | null | undefined,
  device: Device | null | undefined,
  enabled: boolean
): DroneWifiStatus {
  const [state, setState] = useState<DroneLinkState>('unknown');
  const [ssid, setSsid] = useState<string | null>(null);
  const [signal, setSignal] = useState<number | null>(null);
  const [detail, setDetail] = useState<string | null>(null);
  // Countdown to the next automatic poll, so the tile can show that it is
  // refreshing on its own instead of looking frozen between checks.
  const [secondsToNextScan, setSecondsToNextScan] = useState(POLL_MS / 1000);
  const [busy, setBusy] = useState(false);

  // Guards against overlapping polls: a scan can outlast the interval, and a
  // second scan while one is running makes the host re-associate for nothing.
  const inFlight = useRef(false);
  const rescanNonce = useRef(0);
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const poll = useCallback(async () => {
    if (inFlight.current) return;
    const hostName = host?.host_name;
    const deviceId = device?.device_id;
    if (!hostName || !deviceId) return;

    inFlight.current = true;
    setBusy(true);
    setSecondsToNextScan(POLL_MS / 1000);
    try {
      // 1. Are we already talking to the drone? If so there is nothing to scan
      //    for — a landed drone can also drop off its AP and come back, so this
      //    is re-checked every tick rather than latched.
      const status = await api.get<StatusResponse>(
        buildServerUrl(
          `/server/drone/tello/status?host_name=${encodeURIComponent(hostName)}` +
            `&device_id=${encodeURIComponent(deviceId)}`
        )
      );

      if (status?.linked) {
        setState('connected');
        setDetail(null);
        return;
      }

      // 2. Not linked: is the AP even in range?
      const scan = await api.post<ScanResponse>(buildServerUrl('/server/drone/tello/scan'), {
        host_name: hostName,
      });
      const aps = scan?.tellos ?? [];
      const ap = aps[0];

      if (!ap) {
        setState('ap-not-found');
        setSsid(null);
        setSignal(null);
        setDetail(null);
        return;
      }

      setSsid(ap.ssid);
      setSignal(ap.signal ?? null);

      // 3. The AP is there — join it. The drone IS the access point, so there is
      //    nothing to choose and nothing to confirm.
      setState('connecting');
      setDetail(null);
      const paired = await api.post<PairResponse>(buildServerUrl('/server/drone/tello/pair'), {
        host_name: hostName,
        device_id: deviceId,
        ssid: ap.ssid,
        tello_ip: DEFAULT_DRONE_IP,
        state_port: 8890,
        video_port: 11111,
        cmd_port: 8889,
      });

      if (paired?.success) {
        setState('connected');
        setDetail(null);
      } else {
        setState('error');
        setDetail(paired?.error || 'Could not join the drone Wi-Fi');
      }
    } catch (e: any) {
      // A host that is down, or a device the server does not know yet, is not a
      // drone fault. Say so plainly instead of claiming the drone is off.
      setState('error');
      setDetail(e?.message || 'Could not reach the host');
    } finally {
      inFlight.current = false;
      if (mounted.current) setBusy(false);
    }
  }, [host?.host_name, device?.device_id]);

  const rescan = useCallback(() => {
    rescanNonce.current += 1;
    void poll();
  }, [poll]);

  // Reset when we stop being a drone preview, so re-opening does not show the
  // previous device's SSID while the first scan is still running.
  useEffect(() => {
    if (!enabled) {
      setState('unknown');
      setSsid(null);
      setSignal(null);
      setDetail(null);
      setSecondsToNextScan(POLL_MS / 1000);
    }
  }, [enabled]);

  // 1s ticker behind the countdown. Independent of the poll interval so the
  // number visibly moves; a poll resets it, which keeps the two from drifting.
  useEffect(() => {
    if (!enabled) return undefined;
    const ticker = window.setInterval(() => {
      setSecondsToNextScan((s) => (s > 1 ? s - 1 : POLL_MS / 1000));
    }, 1000);
    return () => window.clearInterval(ticker);
  }, [enabled]);

  useEffect(() => {
    if (!enabled || !host?.host_name || !device?.device_id) return undefined;
    void poll();
    const timer = window.setInterval(() => {
      void poll();
    }, POLL_MS);
    return () => window.clearInterval(timer);
  }, [enabled, host?.host_name, device?.device_id, poll, rescanNonce.current]);

  return { state, ssid, signal, detail, secondsToNextScan, busy, rescan };
}

export default useDroneWifiStatus;
/**
 * Is this device a drone?
 *
 * Two independent signals, either of which is enough — keep both.
 *
 * 1. `device_model`. `/server/devices/getAllDevices` returns `device_model: null`
 *    for every row (that endpoint does not SELECT the column), but the Device
 *    grid is fed by `/server/system/getAllHosts`, which does. Verified live
 *    2026-10-12 against the registry that actually owns the drone (vpt-pi4's
 *    own backend on 127.0.0.1:5109): `device_model: 'tello'` for device3.
 * 2. `device_capabilities.remote`. `get_device_capabilities()` in
 *    shared/src/lib/config/device_capabilities.py returns
 *    `mapping['remote'][0]` — a bare STRING, not a list, so `'tello'` rather
 *    than `['tello']`. Confirmed live: `remote: "tello"`.
 *
 * The capability check is the load-bearing one: it survives a payload that
 * omits the model, which is exactly how the drone used to slip past the gate.
 */
export function isDroneDevice(device: Device | null | undefined): boolean {
  if (!device) return false;
  if (device.device_model === 'tello') return true;
  const remote = (device as { device_capabilities?: { remote?: unknown } }).device_capabilities?.remote;
  if (Array.isArray(remote)) return remote.includes('tello');
  if (typeof remote === 'string') return remote === 'tello';
  return false;
}
