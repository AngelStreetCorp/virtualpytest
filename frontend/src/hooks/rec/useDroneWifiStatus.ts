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
 * The drone is named after its AP (TELLO-C5B142 -> Tello-C5B142): the host renames
 * the device on pair. Once a slot holds a drone the automatic scan only ever re-joins
 * THAT drone — another Tello switched on nearby is ignored. Only the Scan button looks
 * for a different one. Once paired, the overlay steps aside for the camera video.
 * A pair that fails or takes longer than PAIR_TIMEOUT_MS stops the automatic scan and
 * asks for a Rescan, instead of spinning on "found" forever.
 *
 * Battery, temperature and speed come from the same status route (the host keeps the
 * drone's state datagrams while it is paired) and are refreshed every TELEMETRY_MS
 * while connected. A `passive` caller (the stream modal header) only reads that status
 * and never scans or pairs; the tile and the remote panel are the active ones, and
 * only one check per host + device runs at a time across all of them.
 *
 * It joins on its own, but only while it is mounted — and it is only mounted
 * inside the open device preview, so merely browsing /device-control never
 * changes the host's network. Joining moves the host's wlan onto the drone's AP,
 * which costs a Wi-Fi-only host its uplink for a moment.
 */
import { useCallback, useEffect, useRef, useState } from 'react';

import { api } from '../../utils/apiClient';
import { buildHostServerUrl } from '../../utils/buildUrlUtils';
import { Host, Device } from '../../types/common/Host_Types';

export type DroneLinkState =
  | 'unknown'
  | 'ap-not-found'
  | 'connecting'
  | 'connected'
  | 'error';

/** Fields of the Tello state datagram the UI shows. Speeds are dm/s, as the drone sends them. */
export interface DroneTelemetry {
  bat?: number;
  templ?: number;
  temph?: number;
  h?: number;
  tof?: number;
  vgx?: number;
  vgy?: number;
  vgz?: number;
}

export interface DroneWifiStatus {
  state: DroneLinkState;
  /** The SSID we are on or joining, when known. */
  ssid: string | null;
  /** The drone's name from its SSID (Tello-C5B142), when known. */
  droneName: string | null;
  /** Scan signal strength of that SSID, when known. */
  signal: number | null;
  /** One line the preview can show under the headline. */
  detail: string | null;
  /** Paired and the host is writing fresh video segments: the player can start. */
  videoLive: boolean;
  /** Last state datagram while paired (empty until the host has one). */
  telemetry: DroneTelemetry;
  /** The drone is flying. */
  airborne: boolean;
  /** A scan or pair request is in flight right now. */
  busy: boolean;
  /** Not found or failed: automatic scans are stopped until the Scan button. */
  paused: boolean;
  /** The Scan button: scan now, and take a different drone if one is in range. */
  rescan: () => void;
}

/**
 * A host scan is not cheap: the host rescan alone sleeps ~2s before listing, and
 * a pair attempt joins an access point. 20s keeps a parked drone responsive
 * without hammering the radio.
 */
const POLL_MS = 20000;

/**
 * Longest a whole check (status + scan + pair) may take. The host's pair alone is
 * nmcli join (up to 30s) + 3s DHCP settle + 5s link check; past this it is stuck.
 */
const PAIR_TIMEOUT_MS = 45000;

/**
 * Last known "paired with live video", per host + device, so a page refresh opens
 * straight on the stream instead of the placeholder first. Per-browser convenience
 * only: the first status check confirms or clears it.
 */
const LINK_CACHE_TTL_MS = 10 * 60 * 1000;

function linkCacheKey(hostName: string, deviceId: string): string {
  return `virtualpytest:drone-link:${hostName}:${deviceId}`;
}

function readLinkCache(hostName?: string, deviceId?: string): string | null {
  if (!hostName || !deviceId) return null;
  try {
    const raw = window.localStorage.getItem(linkCacheKey(hostName, deviceId));
    const cached = raw ? (JSON.parse(raw) as { ssid?: string; ts?: number }) : null;
    if (cached?.ssid && cached.ts && Date.now() - cached.ts < LINK_CACHE_TTL_MS) return cached.ssid;
  } catch {
    // Storage blocked or corrupt: no cache, the first poll decides.
  }
  return null;
}

function writeLinkCache(hostName: string, deviceId: string, ssid: string | null): void {
  try {
    const key = linkCacheKey(hostName, deviceId);
    if (ssid) window.localStorage.setItem(key, JSON.stringify({ ssid, ts: Date.now() }));
    else window.localStorage.removeItem(key);
  } catch {
    // Storage blocked: the tile simply starts from the placeholder.
  }
}

/** One Scan press (and the first automatic scan) keeps looking this long before "not found". */
export const SCAN_WINDOW_MS = 20000;
/** Pause between two host scans inside that window (each host scan itself takes ~4 s). */
const SCAN_RETRY_MS = 1000;
/** Upper bound on host scans per window, whatever the clock says. */
const SCAN_MAX_ATTEMPTS = 6;

/** How often a paired drone is checked for its first video segments. */
const VIDEO_CHECK_MS = 2000;

/** How often a paired drone with live video refreshes battery / temperature / speed. */
const TELEMETRY_MS = 5000;

/** host:device keys with a scan or pair in flight -> the hook instance running it. Shared by
 *  every mounted hook; an instance gives its key back when it unmounts mid-check. */
const checksInFlight = new Map<string, object>();

function withTimeout<T>(promise: Promise<T>, ms: number): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const timer = window.setTimeout(() => reject(new Error('timed out')), ms);
    promise.then(
      (v) => { window.clearTimeout(timer); resolve(v); },
      (e) => { window.clearTimeout(timer); reject(e); }
    );
  });
}

interface TelloAp {
  ssid: string;
  signal: number | null;
}

interface StatusResponse {
  success?: boolean;
  linked?: boolean;
  /** The real link: host Wi-Fi on the drone AND fresh state datagrams (or airborne). */
  connected?: boolean;
  /** The drone this slot holds (remembered by the host across restarts). */
  ssid?: string | null;
  /** The host's Wi-Fi is on that drone right now — it is still paired. */
  associated?: boolean;
  /** The host is writing fresh HLS segments for this device. */
  video_live?: boolean;
  airborne?: boolean;
  telemetry?: DroneTelemetry;
  last_error?: string | null;
}

interface ScanResponse {
  success?: boolean;
  tellos?: TelloAp[];
}

interface PairResponse {
  success?: boolean;
  device_name?: string;
  ssid?: string;
  error?: string;
  stage?: string;
}

/**
 * Is the drone really there? Only the host's `connected` counts (Wi-Fi on its AP and fresh
 * state datagrams). `linked` stays true after the drone is switched off, and `associated`
 * alone is true for a silent drone, so neither may keep the tile on "Starting video…".
 * A slot pinned by its name only counts its own drone.
 */
export function statusIsConnected(
  status: { connected?: boolean; ssid?: string | null } | null | undefined,
  pinned: string | null
): boolean {
  if (!status?.connected) return false;
  return !pinned || status.ssid === pinned;
}

/** Consecutive quiet-check answers of "not connected" before a connected tile gives up. */
export const LINK_LOST_CHECKS = 2;

const DEFAULT_DRONE_IP = '192.168.10.1';

/**
 * The drone a slot is pinned to by its card name: DEVICE{i}_NAME=Tello-F014A0 means
 * "this slot is TELLO-F014A0", and the tile never pairs any other Tello — another
 * one in range may well be paired to a different host. Any other name = no pin.
 */
export function pinnedSsidFromName(deviceName: string | null | undefined): string | null {
  const m = /^tello-([0-9a-f]{6})$/i.exec((deviceName || '').trim());
  return m ? `TELLO-${m[1].toUpperCase()}` : null;
}

/** TELLO-C5B142 -> Tello-C5B142. */
export function telloDisplayName(ssid: string): string {
  const suffix = ssid.includes('-') ? ssid.slice(ssid.indexOf('-') + 1) : ssid;
  return `Tello-${suffix.toUpperCase()}`;
}

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
  // Shown only until the first video segments exist; then the video replaces it.
  connected: 'Starting video…',
  error: 'Could not pair the drone',
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
  // Short on purpose: it shares one line with the Rescan chip on a narrow card.
  error: 'Power on the drone',
};

/** The headline, naming the drone once its AP is known. */
export function droneHeadline(
  state: DroneLinkState,
  droneName: string | null,
  deviceName?: string | null
): string {
  // Name the drone only when it is not the one already in the card title.
  const other =
    droneName && droneName.toLowerCase() !== (deviceName || '').toLowerCase() ? droneName : null;
  if (state === 'connecting') return other ? `${other} found` : 'Drone found';
  if (state === 'ap-not-found') return other ? `${other} not found` : 'Drone not found';
  if (state === 'error') return other ? `Could not pair ${other}` : 'Could not pair the drone';
  return DRONE_WIFI_HEADLINE[state];
}

/**
 * The line under the headline — or '' when there is nothing honest to say.
 *
 * A failed poll leaves `error` in place until the NEXT poll settles, so the
 * "cannot be reached" hint used to sit on the tile for up to 20s while the scan
 * was already back in flight. A stale complaint about a request that is already
 * being retried is worse than no line at all, so `busy` suppresses it.
 */
export function droneHintLine(state: DroneLinkState, busy: boolean): string {
  // While a scan runs the chip alone says so ("Scanning ⟳"); a hint beside it made
  // the row wrap to three lines and flash on every poll.
  if (busy) return '';
  // Never the SSID: the headline already names the drone ("Tello-F014A0 found").
  return DRONE_WIFI_HINT[state];
}

export function useDroneWifiStatus(
  host: Host | null | undefined,
  device: Device | null | undefined,
  enabled: boolean,
  options: { passive?: boolean } = {}
): DroneWifiStatus {
  const passive = Boolean(options.passive);
  // Seeded from the refresh cache: a drone that was paired with live video a moment
  // ago opens on its stream at once; the first poll corrects it if that changed.
  const pinned = pinnedSsidFromName(device?.device_name);
  const [cachedSsid] = useState(() => {
    const cached = enabled ? readLinkCache(host?.host_name, device?.device_id) : null;
    return cached && (!pinned || cached === pinned) ? cached : null;
  });
  const [state, setState] = useState<DroneLinkState>(cachedSsid ? 'connected' : 'unknown');
  const [ssid, setSsid] = useState<string | null>(cachedSsid);
  // The drone this slot holds. Seeded from the host (it remembers the last pair),
  // set on every successful pair. The automatic scan only re-joins this one.
  const heldSsid = useRef<string | null>(cachedSsid ?? pinned);
  // Latest state, read inside poll without making poll depend on it.
  const stateRef = useRef<DroneLinkState>('unknown');
  stateRef.current = state;
  const [signal, setSignal] = useState<number | null>(null);
  const [detail, setDetail] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [videoLive, setVideoLive] = useState(Boolean(cachedSsid));
  const [paused, setPaused] = useState(false);
  const pausedRef = useRef(false);
  const [telemetry, setTelemetry] = useState<DroneTelemetry>({});
  const [airborne, setAirborne] = useState(false);
  const lostChecks = useRef(0);

  // Guards against overlapping polls: a scan can outlast the interval, and a
  // second scan while one is running makes the host re-associate for nothing.
  const inFlight = useRef(false);
  const rescanNonce = useRef(0);
  const mounted = useRef(true);
  const owner = useRef({});
  const heldKey = useRef<string | null>(null);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      const key = heldKey.current;
      if (key && checksInFlight.get(key) === owner.current) checksInFlight.delete(key);
    };
  }, []);

  const fail = useCallback((message: string) => {
    setState('error');
    setDetail(message);
    pausedRef.current = true;
    setPaused(true);
  }, []);

  const poll = useCallback(async (manual = false) => {
    if (inFlight.current) return;
    if (pausedRef.current && !manual) return;
    pausedRef.current = false;
    setPaused(false);
    const hostName = host?.host_name;
    const deviceId = device?.device_id;
    if (!hostName || !deviceId) return;
    const checkKey = `${hostName}:${deviceId}`;
    // Another mounted hook (tile, remote panel) is already scanning or pairing this drone.
    if (checksInFlight.has(checkKey)) return;

    inFlight.current = true;
    checksInFlight.set(checkKey, owner.current);
    heldKey.current = checkKey;
    setBusy(true);
    try {
      // 1. Are we already talking to the drone? If so there is nothing to scan
      //    for — a landed drone can also drop off its AP and come back, so this
      //    is re-checked every tick rather than latched.
      const status = await withTimeout(api.get<StatusResponse>(
        buildHostServerUrl(host, 
          `/server/drone/tello/status?host_name=${encodeURIComponent(hostName)}` +
            `&device_id=${encodeURIComponent(deviceId)}`
        )
      ), PAIR_TIMEOUT_MS);

      if (status?.ssid && !heldSsid.current) heldSsid.current = status.ssid;
      // Still on the drone's Wi-Fi = still paired. Re-pairing it every poll sent a
      // second `command` the Tello often leaves unanswered, which failed the tile.
      if (statusIsConnected(status, pinned) && !manual) {
        if (status.ssid) setSsid(status.ssid);
        setVideoLive(Boolean(status.video_live));
        setTelemetry(status.telemetry ?? {});
        setAirborne(Boolean(status.airborne));
        setState('connected');
        setDetail(null);
        return;
      }
      setTelemetry({});
      setAirborne(false);
      if (passive) {
        // Read-only caller: say what is true, leave scanning to the tile.
        setState('ap-not-found');
        return;
      }

      // 2. Not linked: is the AP even in range? One host scan often misses a Tello that
      //    just powered on or has a weak beacon, so keep scanning for SCAN_WINDOW_MS
      //    (about 4 host scans) before saying "not found".
      const held = heldSsid.current;
      // Order to try. Automatic: the drone already held, then — only if it is in
      // range but will not pair (a scan can still list a drone that was just
      // switched off) — the other Tellos. Scan button: other drones first, falling
      // back to the same drone when it is the only one in range.
      const pick = (aps: TelloAp[]): TelloAp[] => {
        const others = aps.filter((a) => a.ssid !== held);
        const heldAp = aps.find((a) => a.ssid === held);
        return pinned
          ? aps.filter((a) => a.ssid === pinned) // pinned by name: that drone or none
          : !held
            ? aps
            : manual
              ? [...others, ...(heldAp ? [heldAp] : [])]
              : heldAp
                ? [heldAp, ...others]
                : [];
      };
      const scanUntil = Date.now() + SCAN_WINDOW_MS;
      let candidates: TelloAp[] = [];
      for (let attempt = 1; attempt <= SCAN_MAX_ATTEMPTS; attempt++) {
        const scan = await withTimeout(api.post<ScanResponse>(buildHostServerUrl(host, '/server/drone/tello/scan'), {
          host_name: hostName,
        }), PAIR_TIMEOUT_MS);
        candidates = pick(scan?.tellos ?? []);
        if (candidates.length > 0 || Date.now() + SCAN_RETRY_MS >= scanUntil || !mounted.current) break;
        await new Promise((resolve) => window.setTimeout(resolve, SCAN_RETRY_MS));
      }

      if (candidates.length === 0) {
        // Stop here: scanning on a loop for a drone that is off kept the tile
        // busy forever. The Scan button looks again once it is switched on.
        setState('ap-not-found');
        setSsid(held);
        setSignal(null);
        setDetail(null);
        pausedRef.current = true;
        setPaused(true);
        return;
      }

      // 3. Join it. The drone IS the access point, so there is nothing to confirm.
      //    A landed drone is re-paired on every tick (its UDP link only opens on the
      //    first command), so the held drone stays connected instead of flickering.
      let lastError = 'Could not join the drone Wi-Fi';
      for (const ap of candidates) {
        const repair = stateRef.current === 'connected' && held === ap.ssid;
        setSsid(ap.ssid);
        setSignal(ap.signal ?? null);
        if (!repair) setState('connecting');
        setDetail(null);
        try {
          const paired = await withTimeout(api.post<PairResponse>(buildHostServerUrl(host, '/server/drone/tello/pair'), {
            host_name: hostName,
            device_id: deviceId,
            ssid: ap.ssid,
            tello_ip: DEFAULT_DRONE_IP,
            state_port: 8890,
            video_port: 11111,
            cmd_port: 8889,
          }), PAIR_TIMEOUT_MS);
          if (paired?.success) {
            heldSsid.current = ap.ssid;
            setVideoLive(false);
            setState('connected');
            setDetail(null);
            return;
          }
          lastError = paired?.error || lastError;
        } catch (e: any) {
          lastError = e?.message || lastError;
        }
      }
      fail(lastError);
    } catch (e: any) {
      // A timeout, a host that is down, or a device the server does not know yet:
      // stop retrying on our own and let the user ask for a Rescan.
      fail(e?.message || 'Could not reach the host');
    } finally {
      inFlight.current = false;
      if (checksInFlight.get(checkKey) === owner.current) checksInFlight.delete(checkKey);
      heldKey.current = null;
      if (mounted.current) setBusy(false);
    }
  }, [host?.host_name, host?.server_url, device?.device_id, fail, pinned, passive]);

  const rescan = useCallback(() => {
    rescanNonce.current += 1;
    void poll(true);
  }, [poll]);

  // Reset when we stop being a drone preview, so re-opening does not show the
  // previous device's SSID while the first scan is still running.
  useEffect(() => {
    if (!enabled) {
      setState('unknown');
      setSsid(null);
      setVideoLive(false);
      heldSsid.current = pinned;
      pausedRef.current = false;
      setPaused(false);
      setSignal(null);
      setDetail(null);
      setTelemetry({});
      setAirborne(false);
    }
  }, [enabled, pinned]);

  useEffect(() => {
    if (!enabled || !host?.host_name || !device?.device_id) return undefined;
    void poll();
    const timer = window.setInterval(() => {
      void poll();
    }, POLL_MS);
    return () => window.clearInterval(timer);
  }, [enabled, host?.host_name, device?.device_id, poll, rescanNonce.current]);

  // Paired: a quiet status check (no scan, no busy chip). Every 2 s until the first
  // frames exist, so the video replaces the placeholder at once; then every 5 s for
  // battery, temperature and speed.
  useEffect(() => {
    if (!enabled || state !== 'connected') return undefined;
    const hostName = host?.host_name;
    const deviceId = device?.device_id;
    if (!hostName || !deviceId) return undefined;
    const timer = window.setInterval(async () => {
      try {
        const status = await api.get<StatusResponse>(
          buildHostServerUrl(host, 
            `/server/drone/tello/status?host_name=${encodeURIComponent(hostName)}` +
              `&device_id=${encodeURIComponent(deviceId)}`
          )
        );
        if (!mounted.current) return;
        if (!statusIsConnected(status, pinned)) {
          // The drone was switched off or the host's Wi-Fi left it: show the real state
          // (not found + Scan chip) instead of "Starting video…" on a dead link.
          lostChecks.current += 1;
          if (lostChecks.current >= LINK_LOST_CHECKS) {
            lostChecks.current = 0;
            setTelemetry({});
            setAirborne(false);
            setVideoLive(false);
            setState('ap-not-found');
            setDetail(null);
            pausedRef.current = true;
            setPaused(true);
          }
          return;
        }
        lostChecks.current = 0;
        if (status?.video_live) setVideoLive(true);
        setTelemetry(status?.telemetry ?? {});
        setAirborne(Boolean(status?.airborne));
      } catch {
        // The 20 s poll reports a host that is down; this check only refreshes readings.
      }
    }, videoLive ? TELEMETRY_MS : VIDEO_CHECK_MS);
    return () => window.clearInterval(timer);
  }, [enabled, state, videoLive, pinned, host?.host_name, host?.server_url, device?.device_id]);

  // Keep the refresh cache in step: remember a drone streaming live, forget it the
  // moment it is not found or fails.
  useEffect(() => {
    const hostName = host?.host_name;
    const deviceId = device?.device_id;
    if (!enabled || !hostName || !deviceId) return;
    if (state === 'connected' && videoLive && ssid) writeLinkCache(hostName, deviceId, ssid);
    else if (state === 'ap-not-found' || state === 'error') writeLinkCache(hostName, deviceId, null);
  }, [enabled, state, videoLive, ssid, host?.host_name, device?.device_id]);

  const droneName = ssid ? telloDisplayName(ssid) : null;
  return { state, ssid, droneName, signal, detail, videoLive, telemetry, airborne, busy, paused, rescan };
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
