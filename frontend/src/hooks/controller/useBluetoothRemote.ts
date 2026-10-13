import { useState, useCallback, useEffect, useRef } from 'react';

import { bluetoothRemoteConfig, BluetoothRemoteConfig } from '../../config/remote/bluetoothRemote';
import { Host } from '../../types/common/Host_Types';

import { useControllerApi } from './useControllerApi';

// Live state of the bonded STB peer and the daemon. Mirrors the dict
// returned by BluetoothRemoteController.get_pairing_status() on the host.
export interface BluetoothPairingStatus {
  daemon_active: boolean;
  // True while start.sh/resume.sh is still running on the host. During that
  // window the daemon is intentionally stopped to reconfigure the adapter,
  // so daemon_active=false is EXPECTED, not a crash. See §6.7.23-followup-3.
  script_running?: boolean;
  resume_state?: 'idle' | 'running' | 'ready' | 'failed';
  resume_error?: string | null;
  pair_error?: string | null;
  advertising: boolean;
  adapter_mac: string | null;
  bond_present: boolean;
  stb_mac: string | null;
  paired: boolean;
  connected: boolean;
  trusted: boolean;
  services_resolved: boolean;
  hid_ready: boolean;
}

interface BluetoothRemoteSession {
  connected: boolean;
  connecting: boolean;
  error: string | null;
}

export type PairPhase = 'idle' | 'pairing' | 'success' | 'timeout' | 'failed';

// How long the panel waits for the STB to finish pairing after Start Pairing.
// The STB can take ~2 min to find and pair the remote; at 60 s the panel
// reported a timeout while the pairing still completed shortly after (§6.7.33).
export const BLE_PAIR_WAIT_S = 120;
// start.sh (adapter reset, MAC, advertising) takes ~15-30 s before the remote
// can be paired. The BLE_PAIR_WAIT_S countdown starts only once it is ready.
export const BLE_PAIR_PREP_MAX_S = 90;

// BLE daemon unit names are per-adapter on multi-instance hosts
// (`hid-remote-${hci}.service`, `hid-agent-${hci}.service`,
// `vpt-ble-remote@${hci}.service`). The controller's get_logs() returns
// a dict keyed by whatever units belong to THIS adapter, plus a
// pairing_status entry. The frontend discovers the unit keys dynamically
// from Object.keys(logs).filter(k => k !== 'pairing_status') so it
// doesn't need to know the adapter at type-time.
export interface BluetoothLogs {
  [unitName: string]: string | BluetoothPairingStatus | undefined;
  pairing_status?: BluetoothPairingStatus;
}

interface UseBluetoothRemoteReturn {
  session: BluetoothRemoteSession;
  isLoading: boolean;
  isPairing: boolean;
  isWaking: boolean;
  // Live countdown of the active wake window, in milliseconds. 0 when
  // not waking. Panel reads these to show "Ns / totalS elapsed" + a
  // progress bar so the operator sees the wait elapsing instead of a
  // frozen "waiting up to 30s" string.
  wakeRemainingMs: number;
  wakeTotalMs: number;
  pairPhase: PairPhase;
  pairError: string | null;
  // True once start.sh has finished and the remote is advertising: the moment
  // to put the STB in "Add new remote" mode.
  pairReady: boolean;
  lastAction: string;
  layoutConfig: BluetoothRemoteConfig;
  status: BluetoothPairingStatus | null;
  // True when a Resume call has elapsed RESUME_ESCALATE_MS without the
  // status poll observing connected=true. Surfaces a Re-pair escape
  // hatch in the UI so the user isn't stuck cycling Resume forever.
  resumeFailed: boolean;
  // True while resume_state === 'running' (the backend is mid-resume.sh).
  // Panel hides Re-pair during this window so the operator can't race a
  // bond-wipe against an in-flight recovery script.
  resumeRunning: boolean;
  refreshStatus: () => Promise<void>;
  handleConnect: () => Promise<void>;
  handleDisconnect: () => Promise<void>;
  handleRemoteCommand: (command: string, params?: any) => Promise<void>;
  startPairing: () => Promise<void>;
  resume: () => Promise<void>;
  wake: () => Promise<void>;
  coldWake: () => Promise<void>;
  getLogs: (lines?: number) => Promise<BluetoothLogs | null>;
  logsSince: string | null;
  clearLogsSince: () => void;
}

const STATUS_POLL_INTERVAL_MS = 2000;
const PAIR_DAEMON_FAILURE_GRACE_MS = 5000;
const PAIR_DAEMON_FAILURE_POLLS = 2;
// Match hid_remote.py's 30 s low-duty ADV_DIRECT_IND window, plus one status
// poll of grace. A shorter browser timer makes a still-running daemon wake
// look like failure and exposes Resume/Re-pair too early.
const WAKE_WAIT_MS = 32000;
// Deep/cold-standby wake (Broadcom WoBLE) is much slower than the active-
// standby ADV_DIRECT_IND wake: the daemon broadcasts the WoBLE pattern
// (WOBLE_BROADCAST_S=3s) then waits up to COLD_WAKE_TIMEOUT_S=20s for the
// host to boot from S2/S3 and reconnect. Give the UI a margin over that.
const COLD_WAKE_WAIT_MS = 25000;

// Status-display debounce (anti-flicker). get_pairing_status is polled every
// 2s and the raw flags genuinely walk through transient rungs during a re-pair
// (paired -> reconnecting -> connected&!hid_ready -> ready). Rendering each
// rung flips the panel between screens. We smooth this with HYSTERESIS: a
// healthier state shows instantly (good news is never delayed), but a less-
// healthy state must persist this long before it replaces the displayed one —
// so a 2s blip mid-handshake doesn't paint a red "No pairing" / amber
// "not responding" screen. A genuine regression (stable > this) still surfaces.
const STATUS_DEMOTE_DEBOUNCE_MS = 4000;

// Rank a pairing status by health, high = better. Used only for the display
// debounce above: upgrades (>= current) apply immediately, downgrades wait.
const statusHealthRank = (s: BluetoothPairingStatus | null): number => {
  if (!s) return -1;
  if (!s.daemon_active) return 0;                                   // daemon down
  if (!s.bond_present) return 1;                                    // no pairing
  if (!s.connected) return 2;                                       // bonded, disconnected
  if (!s.hid_ready) return 3;                                       // connected, battery-only trap
  return 4;                                                         // fully ready
};

// Last status seen per host+device, kept for the browser session. Opening the
// panel (or re-taking control) starts from it, so a connected STB shows its
// remote at once instead of "Loading BLE status…" for a host round trip; one
// background refresh confirms it, and a real drop still surfaces through the
// normal demote debounce above.
const lastStatusCache = new Map<string, BluetoothPairingStatus>();
const statusCacheKey = (hostName?: string, deviceId?: string) => `${hostName ?? ''}|${deviceId ?? ''}`;

export const useBluetoothRemote = (
  host: Host,
  deviceId?: string,
  isConnected?: boolean,
): UseBluetoothRemoteReturn => {
  const [session, setSession] = useState<BluetoothRemoteSession>({
    connected: false,
    connecting: false,
    error: null,
  });
  const [isLoading, setIsLoading] = useState(false);
  const [isPairing, setIsPairing] = useState(false);
  const [isWaking, setIsWaking] = useState(false);
  const [pairPhase, setPairPhase] = useState<PairPhase>('idle');
  const [pairError, setPairError] = useState<string | null>(null);
  const [pairReady, setPairReady] = useState(false);
  const [lastAction, setLastAction] = useState('');
  const cacheKey = statusCacheKey(host?.host_name, deviceId);
  const [status, setStatus] = useState<BluetoothPairingStatus | null>(
    () => lastStatusCache.get(cacheKey) ?? null,
  );
  // Debounced view of `status` for display (anti-flicker, see
  // STATUS_DEMOTE_DEBOUNCE_MS). The raw `status` drives all internal logic
  // (polling stop, wake/resume effects) for immediacy; `displayStatus` is what
  // the panel renders, so transient mid-handshake rungs don't flip screens.
  const [displayStatus, setDisplayStatus] = useState<BluetoothPairingStatus | null>(
    () => lastStatusCache.get(cacheKey) ?? null,
  );
  // Tracks an in-flight downgrade: the lower rank we've seen and when it
  // started, so a sustained regression commits after the debounce window
  // while a brief blip (replaced by a healthier poll) never does.
  const demoteRef = useRef<{ rank: number; since: number } | null>(null);
  const [logsSince, setLogsSince] = useState<string | null>(null);
  const [resumeFailed, setResumeFailed] = useState(false);
  // True while the backend is mid-resume.sh (resume_state === 'running').
  // The panel hides Re-pair while this is set — Re-pair wipes the bond,
  // and wiping it mid-resume would race the in-flight resume.sh script
  // (which is trying to recover the existing bond). Re-pair only becomes
  // useful AFTER resume.sh has either succeeded (resume_state === 'ready',
  // fullyConnected → no Re-pair needed) or given up (resume_state ===
  // 'failed', resumeFailed=true → Re-pair surfaces as the escape hatch).
  const [resumeRunning, setResumeRunning] = useState(false);

  const { executeRemoteCommand } = useControllerApi(host, deviceId);
  const layoutConfig = bluetoothRemoteConfig;

  const pollTimerRef = useRef<number | null>(null);
  // Tracks whether we've already fired a proactive wake for this mount /
  // take-control cycle. Without it, we'd re-fire wake on every status
  // poll that still shows !connected, flooding the FIFO.
  const wakeAttemptedRef = useRef(false);
  // Kept on a ref so the 8.5 s wake timeout survives effect re-runs
  // triggered by the 2 s status poll. Without this the cleanup function
  // would cancel the timer every poll tick and isWaking would never
  // flip back to false, leaving the UI stuck on "Waking STB…" forever.
  const wakeTimerRef = useRef<number | null>(null);
  // When the current wake window started + its total length, so the UI can
  // show a live "Ns / 30s elapsed" ticker instead of a frozen "waiting up
  // to 30s" string. Updated on each wake (coldWake / auto-wake) and cleared
  // on every terminal path (timeout, reconnect, error, unmount).
  const wakeStartRef = useRef<number | null>(null);
  const wakeTotalRef = useRef<number>(0);
  // Live remaining time in ms — the panel renders this to display a
  // ticking countdown under the "Waking STB…" headline. 0 = not waking.
  const [wakeRemainingMs, setWakeRemainingMs] = useState<number>(0);

  // Fully-healthy steady state: daemon up, bonded, paired, HID subscribed,
  // and the STB is currently connected. Once we've observed this once, the
  // panel's body is already showing the remote — further polling has nothing
  // to report, so the interval halts until the user explicitly re-opens /
  // re-triggers something that could change state.
  const fullyConnected =
    status !== null &&
    status.daemon_active &&
    status.bond_present &&
    status.paired &&
    status.hid_ready &&
    status.connected &&
    status.resume_state !== 'running';

  // ---- Display debounce ----
  // Derive `displayStatus` from `status` with hysteresis: a same-or-healthier
  // rank applies instantly (good news, and steady state, never delayed); a
  // less-healthy rank only replaces the displayed status once it has persisted
  // for STATUS_DEMOTE_DEBOUNCE_MS. Driven by the 2s poll (each poll yields a
  // fresh `status` object, so this re-runs and re-checks the elapsed time).
  useEffect(() => {
    const newRank = statusHealthRank(status);
    const curRank = statusHealthRank(displayStatus);
    if (newRank >= curRank) {
      demoteRef.current = null;
      setDisplayStatus(status); // upgrade/steady → show immediately (no-op if same ref)
      return;
    }
    // downgrade: hold the healthier display until the lower rank has persisted
    // STATUS_DEMOTE_DEBOUNCE_MS. Each 2s poll re-runs this and re-checks the
    // elapsed time; a healthier poll in between resets via the branch above.
    const now = Date.now();
    if (!demoteRef.current || demoteRef.current.rank !== newRank) {
      demoteRef.current = { rank: newRank, since: now };
    }
    if (now - demoteRef.current.since >= STATUS_DEMOTE_DEBOUNCE_MS) {
      demoteRef.current = null;
      setDisplayStatus(status); // regression sustained → commit it
    }
    // else: transient dip — leave displayStatus on the healthier value
  }, [status, displayStatus]);

  // ---- Status polling ----
  // Fetches get_pairing_status until we confirm the fully-connected steady
  // state, then stops. Pauses when the document is hidden so we don't burn
  // cycles in background tabs.
  const refreshStatus = useCallback(async () => {
    try {
      const result = await executeRemoteCommand<{ success: boolean; status?: BluetoothPairingStatus; error?: string }>(
        'get_pairing_status',
        {},
        { remote_type: 'bluetooth_remote' },
        { includeDeviceId: true },
      );
      if (result.success && result.status) {
        lastStatusCache.set(cacheKey, result.status);
        setStatus(result.status);
        if (result.status.paired && result.status.bond_present) {
          setPairPhase((prev) => (prev === 'pairing' ? 'success' : prev));
          setIsPairing(false);
        }
      } else if (result.error) {
        console.warn(`[@hook:useBluetoothRemote] get_pairing_status returned error: ${result.error}`);
      }
    } catch (e) {
      console.warn(`[@hook:useBluetoothRemote] refreshStatus failed: ${e}`);
    }
  }, [executeRemoteCommand, cacheKey]);

  // Started from a cached fully-connected status: the polling effect below
  // skips while fullyConnected, so confirm it once against the host.
  useEffect(() => {
    if (host?.host_name && deviceId && lastStatusCache.has(cacheKey)) {
      refreshStatus();
    }
  }, [cacheKey]);

  useEffect(() => {
    if (!host?.host_name || !deviceId) {
      return;
    }
    // Once fully connected the previous run's cleanup clears the interval
    // and we never start a new one — nothing to gain from continued polling
    // while the remote body is displayed.
    if (fullyConnected) {
      return;
    }
    refreshStatus();

    const start = () => {
      if (pollTimerRef.current !== null) return;
      pollTimerRef.current = window.setInterval(() => {
        if (!document.hidden) {
          refreshStatus();
        }
      }, STATUS_POLL_INTERVAL_MS);
    };
    const stop = () => {
      if (pollTimerRef.current !== null) {
        window.clearInterval(pollTimerRef.current);
        pollTimerRef.current = null;
      }
    };

    start();
    const onVisibility = () => {
      if (document.hidden) {
        stop();
      } else {
        refreshStatus();
        start();
      }
    };
    document.addEventListener('visibilitychange', onVisibility);
    return () => {
      stop();
      document.removeEventListener('visibilitychange', onVisibility);
    };
  }, [host?.host_name, deviceId, refreshStatus, fullyConnected]);

  // ---- Connection lifecycle (mirrors useInfraredRemote pattern) ----
  useEffect(() => {
    if (isConnected) {
      setSession({ connected: true, connecting: false, error: null });
      setLastAction('Connected via external control');
    } else {
      setSession({ connected: false, connecting: false, error: null });
      setLastAction('Disconnected via external control');
    }
  }, [isConnected, host?.host_name, deviceId]);

  const handleConnect = useCallback(async () => {
    setSession((prev) => ({ ...prev, connecting: true, error: null }));
    setIsLoading(true);
    try {
      await new Promise((resolve) => setTimeout(resolve, 500));
      setSession({ connected: true, connecting: false, error: null });
      setLastAction('Connected to BLE remote');
    } catch (error) {
      const msg = error instanceof Error ? error.message : 'Connection failed';
      setSession({ connected: false, connecting: false, error: msg });
      setLastAction(`Connection failed: ${msg}`);
    } finally {
      setIsLoading(false);
    }
  }, []);

  const handleDisconnect = useCallback(async () => {
    setIsLoading(true);
    try {
      setSession({ connected: false, connecting: false, error: null });
      setLastAction('Disconnected from BLE remote');
    } finally {
      setIsLoading(false);
    }
  }, []);

  // ---- Key press ----
  const handleRemoteCommand = useCallback(
    async (command: string, params?: any) => {
      if (!session.connected) {
        console.warn(`[@hook:useBluetoothRemote] Cannot send command - not connected`);
        return;
      }
      setIsLoading(true);
      try {
        const result = await executeRemoteCommand<{ success: boolean; error?: string }>(
          'press_key',
          { key: command, ...params },
          { remote_type: 'bluetooth_remote' },
          { includeDeviceId: true },
        );
        if (!result.success) {
          throw new Error(result.error || 'Command failed');
        }
        setLastAction(`Sent BLE command: ${command}`);
      } catch (error) {
        const msg = error instanceof Error ? error.message : 'Command failed';
        setLastAction(`Command failed: ${msg}`);
        console.error(`[@hook:useBluetoothRemote] ${msg}`);
      } finally {
        setIsLoading(false);
      }
    },
    [session.connected, executeRemoteCommand],
  );

  // ---- Pair management ----
  const startPairing = useCallback(async () => {
    if (isPairing) return;
    setIsPairing(true);
    setPairPhase('pairing');
    setPairError(null);
    setPairReady(false);
    setLogsSince(new Date().toISOString());
    setLastAction('Starting BLE pairing — STB must be in pair-new-remote mode');
    // Blank the cached status so the UI doesn't keep showing stale
    // "paired=true / adapter_mac=<old>" from the previous bond while start.sh
    // is wiping it. Without this the status panel reads as already-paired
    // during the 15-25s start.sh window, which contradicts the "Waiting for
    // STB to pair…" overlay and confuses the user. Fresh status arrives on
    // the next poll iteration below.
    setStatus(null);
    lastStatusCache.delete(cacheKey);
    try {
      // Snapshot the pre-start baseline BEFORE kicking off start.sh.
      // start.sh begins destroying state (btmgmt power off, MAC rotate,
      // bluetoothd restart) the moment the backend launches it, so a
      // baseline taken afterwards can already reflect the post-destroy
      // state — which would set bondCleared=true on iteration zero and
      // let the loop falsely trust the OLD bond as "success" before the
      // re-pair actually happened. Taking it first guarantees we capture
      // the bond the user is replacing.
      const baselineStatus = (await executeRemoteCommand<{ success: boolean; status?: BluetoothPairingStatus }>(
        'get_pairing_status',
        {},
        { remote_type: 'bluetooth_remote' },
        { includeDeviceId: true },
      )).status ?? null;
      const hadBondAtStart = baselineStatus?.bond_present === true;
      const initialAdapterMac = baselineStatus?.adapter_mac ?? null;

      const result = await executeRemoteCommand<{ success: boolean; error?: string; output?: string }>(
        'start_pairing',
        {},
        { remote_type: 'bluetooth_remote' },
        { includeDeviceId: true },
      );
      if (!result.success) {
        throw new Error(result.error || 'start_pairing failed');
      }
      setLastAction('start.sh launched — polling for pair completion…');
      // Pair loop: before accepting "paired + bond_present + hid_ready"
      // as success, require evidence that start.sh wiped the old bond
      // (bond_present drops) or rotated the adapter MAC (which start.sh
      // always does). Otherwise the first iterations would see the
      // untouched OLD bond and exit success immediately.
      let bondCleared = !hadBondAtStart;
      let daemonDownPolls = 0;
      const start = Date.now();
      // Two phases: start.sh prepares the adapter (up to BLE_PAIR_PREP_MAX_S),
      // then the STB gets BLE_PAIR_WAIT_S to pair, counted from the moment
      // the remote is ready. Longer waits just hide bugs.
      let readyAt: number | null = null;
      while (
        readyAt === null
          ? Date.now() - start < BLE_PAIR_PREP_MAX_S * 1000
          : Date.now() - readyAt < BLE_PAIR_WAIT_S * 1000
      ) {
        await new Promise((resolve) => setTimeout(resolve, 1500));
        const s = (await executeRemoteCommand<{ success: boolean; status?: BluetoothPairingStatus }>(
          'get_pairing_status',
          {},
          { remote_type: 'bluetooth_remote' },
          { includeDeviceId: true },
        )).status;
        if (s) setStatus(s);
        if (!s?.script_running && s?.pair_error) throw new Error(s.pair_error);
        if (readyAt === null && s && !s.script_running && s.daemon_active && !s.bond_present
            && Date.now() - start >= PAIR_DAEMON_FAILURE_GRACE_MS) {
          readyAt = Date.now();
          setPairReady(true);
          setLastAction('Remote ready — put the STB in "Add new remote" mode');
        }
        // start.sh intentionally STOPS the daemon to reconfigure the adapter
        // (power-off → MAC spoof → raw-HCI adv, ~10s) and relaunches it near
        // the end — so daemon_active=false is EXPECTED for the whole run. The
        // host reports script_running=true for that window; only once the
        // script has finished (script_running=false) AND the daemon is still
        // down do we treat it as a crash. The old time-only grace (5s + 2
        // polls ≈ 8s) tripped before the daemon's ~10s relaunch, falsely
        // reporting "hid-remote service exited during pairing" on a healthy
        // run. See BLUETOOTH.md §6.7.23-followup-3.
        if (!s?.daemon_active) {
          if (!s?.script_running && Date.now() - start >= PAIR_DAEMON_FAILURE_GRACE_MS) {
            daemonDownPolls += 1;
            if (daemonDownPolls >= PAIR_DAEMON_FAILURE_POLLS) {
              throw new Error(
                'hid-remote service exited during pairing. Check BLE debug logs on the HID-REMOTE tab.',
              );
            }
          } else {
            daemonDownPolls = 0;
          }
          continue;
        }
        daemonDownPolls = 0;
        if (!bondCleared) {
          // Old bond is considered cleared when either (a) bond_present
          // drops, or (b) adapter MAC rotates (proves start.sh finished
          // its reset even if a fast re-bond happened between polls).
          if (!s?.bond_present) {
            bondCleared = true;
          } else if (
            s?.adapter_mac &&
            initialAdapterMac &&
            s.adapter_mac !== initialAdapterMac
          ) {
            bondCleared = true;
          } else {
            continue;
          }
        }
        if (s?.paired && s?.bond_present && s?.hid_ready) {
          setStatus(s);
          setPairPhase('success');
          setLastAction(`Paired and HID ready: ${s.stb_mac}`);
          return;
        }
      }
      setPairPhase('timeout');
      if (readyAt === null) {
        setPairError(`The remote was not ready to pair after ${BLE_PAIR_PREP_MAX_S} seconds. Check the start-resume log tab.`);
        setLastAction('Pairing setup timeout');
      } else {
        setPairError(`STB did not complete handshake within ${BLE_PAIR_WAIT_S} seconds. Ensure the STB is in pair-new-remote mode and retry.`);
        setLastAction(`Pairing timeout (${BLE_PAIR_WAIT_S} s)`);
      }
    } catch (error) {
      const msg = error instanceof Error ? error.message : 'Pair failed';
      setPairPhase('failed');
      setPairError(msg);
      setLastAction(`Pair failed: ${msg}`);
      console.error(`[@hook:useBluetoothRemote] startPairing: ${msg}`);
    } finally {
      setIsPairing(false);
      setPairReady(false);
    }
  }, [executeRemoteCommand, refreshStatus, cacheKey]);

  const getLogs = useCallback(
    async (lines: number = 200): Promise<BluetoothLogs | null> => {
      try {
        const params: Record<string, any> = { lines };
        if (logsSince) params.since = logsSince;
        const result = await executeRemoteCommand<{ success: boolean; logs?: BluetoothLogs; error?: string }>(
          'get_logs',
          params,
          { remote_type: 'bluetooth_remote' },
          { includeDeviceId: true },
        );
        if (!result.success) {
          console.warn(`[@hook:useBluetoothRemote] get_logs error: ${result.error}`);
          return null;
        }
        return result.logs ?? null;
      } catch (e) {
        console.warn(`[@hook:useBluetoothRemote] get_logs exception: ${e}`);
        return null;
      }
    },
    [executeRemoteCommand, logsSince],
  );

  const resume = useCallback(async () => {
    setIsLoading(true);
    setLastAction('Recovering BLE remote…');
    setResumeFailed(false);
    try {
      const result = await executeRemoteCommand<{ success: boolean; error?: string }>(
        'resume',
        {},
        { remote_type: 'bluetooth_remote' },
        { includeDeviceId: true },
      );
      if (!result.success) {
        throw new Error(result.error || 'resume failed');
      }
      setLastAction('Resume recovery started…');
      await refreshStatus();
    } catch (error) {
      const msg = error instanceof Error ? error.message : 'Resume failed';
      setLastAction(`Resume failed: ${msg}`);
      console.error(`[@hook:useBluetoothRemote] resume: ${msg}`);
    } finally {
      setIsLoading(false);
    }
  }, [executeRemoteCommand, refreshStatus]);

  // The backend owns the complete Resume state machine (script + directed
  // wake + readiness gate). Reflect its final verdict instead of racing it
  // with a shorter browser timer.
  useEffect(() => {
    setResumeRunning(status?.resume_state === 'running');
    if (isPairing || status?.resume_state === 'ready') {
      setResumeFailed(false);
      if (status?.resume_state === 'ready') {
        setLastAction('Resume complete — BLE link ready');
      }
    } else if (status?.resume_state === 'failed') {
      setResumeFailed(true);
      setLastAction(`Resume failed: ${status.resume_error ?? 'STB did not reconnect'}`);
    }
  }, [status?.resume_state, status?.resume_error, isPairing]);

  // Proactively ask the daemon to emit ADV_DIRECT_IND at the bonded STB.
  // Non-blocking on the backend (FIFO write); status polling observes the
  // reconnect. Caller manages isWaking + timeout.
  const wake = useCallback(async () => {
    setLastAction('Waking STB…');
    try {
      const result = await executeRemoteCommand<{ success: boolean; error?: string }>(
        'wake',
        {},
        { remote_type: 'bluetooth_remote' },
        { includeDeviceId: true },
      );
      if (!result.success) {
        throw new Error(result.error || 'wake failed');
      }
    } catch (error) {
      const msg = error instanceof Error ? error.message : 'Wake failed';
      setLastAction(`Wake failed: ${msg}`);
      console.warn(`[@hook:useBluetoothRemote] wake: ${msg}`);
    }
  }, [executeRemoteCommand]);

  // User-driven wake from deep/COLD standby (Broadcom WoBLE). Unlike the
  // automatic wake() (ADV_DIRECT_IND, active standby), this asks the daemon
  // to broadcast the undirected 0x000F/"WAKEUP" pattern that a box with its
  // host CPU off (S2/S3) requires. Drives the "Waking STB…" UI via isWaking
  // with the longer COLD_WAKE_WAIT_MS window; the connected-clear effect
  // below drops isWaking the moment the STB reconnects.
  const coldWake = useCallback(async () => {
    setLastAction('Waking STB from deep standby…');
    setIsWaking(true);
    if (wakeTimerRef.current !== null) {
      window.clearTimeout(wakeTimerRef.current);
    }
    // Record start + total so the panel can render a live "Ns / 25s
    // elapsed" ticker instead of a static "waiting up to 30s" (which was
    // also wrong for cold wake — its window is 25s).
    wakeStartRef.current = Date.now();
    wakeTotalRef.current = COLD_WAKE_WAIT_MS;
    setWakeRemainingMs(COLD_WAKE_WAIT_MS);
    wakeTimerRef.current = window.setTimeout(() => {
      setIsWaking(false);
      wakeTimerRef.current = null;
      wakeStartRef.current = null;
      wakeTotalRef.current = 0;
    }, COLD_WAKE_WAIT_MS);
    try {
      const result = await executeRemoteCommand<{ success: boolean; error?: string }>(
        'cold_wake',
        {},
        { remote_type: 'bluetooth_remote' },
        { includeDeviceId: true },
      );
      if (!result.success) {
        throw new Error(result.error || 'cold_wake failed');
      }
    } catch (error) {
      const msg = error instanceof Error ? error.message : 'Cold wake failed';
      setIsWaking(false);
      if (wakeTimerRef.current !== null) {
        window.clearTimeout(wakeTimerRef.current);
        wakeTimerRef.current = null;
      }
      wakeStartRef.current = null;
      wakeTotalRef.current = 0;
      setLastAction(`Cold wake failed: ${msg}`);
      console.warn(`[@hook:useBluetoothRemote] coldWake: ${msg}`);
    }
  }, [executeRemoteCommand]);

  // Auto-wake: when the panel takes control with bond_present but the STB
  // currently disconnected, fire one WAKE. Only happens once per
  // mount / take-control cycle. Cleared automatically when polling
  // observes connected=true or when WAKE_WAIT_MS elapses.
  //
  // The timer is on a ref so it survives effect re-runs from status
  // polling — if we used a local `const t = setTimeout(...)` with a
  // `return () => clearTimeout(t)` cleanup, the cleanup would fire on
  // every 2 s poll and cancel the 8.5 s timer before it could set
  // isWaking=false, leaving the UI stuck on "Waking STB…" forever.
  useEffect(() => {
    if (!status) return;
    if (status.connected) {
      // Reconnected: clear the pending timer + state.
      if (wakeTimerRef.current !== null) {
        window.clearTimeout(wakeTimerRef.current);
        wakeTimerRef.current = null;
      }
      wakeStartRef.current = null;
      wakeTotalRef.current = 0;
      if (isWaking) setIsWaking(false);
      wakeAttemptedRef.current = false;
      return;
    }
    if (wakeAttemptedRef.current) return;
    if (!status.daemon_active || !status.bond_present) return;
    wakeAttemptedRef.current = true;
    setIsWaking(true);
    // Record start + total so the panel can render a live "Ns / 32s
    // elapsed" ticker (the ADV_DIRECT_IND window is 30 s on the daemon
    // + one status-poll of grace; the UI displays the rounded 30 s).
    wakeStartRef.current = Date.now();
    wakeTotalRef.current = WAKE_WAIT_MS;
    setWakeRemainingMs(WAKE_WAIT_MS);
    void wake();
    wakeTimerRef.current = window.setTimeout(() => {
      setIsWaking(false);
      wakeTimerRef.current = null;
      wakeStartRef.current = null;
      wakeTotalRef.current = 0;
    }, WAKE_WAIT_MS);
  }, [status, isWaking, wake]);

  // Cancel the wake + resume timers on unmount so we don't flip state
  // on an unmounted component.
  useEffect(() => {
    return () => {
      if (wakeTimerRef.current !== null) {
        window.clearTimeout(wakeTimerRef.current);
        wakeTimerRef.current = null;
      }
      wakeStartRef.current = null;
      wakeTotalRef.current = 0;
    };
  }, []);

  // While isWaking is true, tick wakeRemainingMs every 250 ms so the UI
  // shows a live "Ns / 30s elapsed" ticker instead of a static "waiting
  // up to 30s" string. Refs (wakeStartRef/wakeTotalRef) are set by the
  // coldWake() and auto-wake paths above; cleared by the timer
  // expiration / reconnect / error / unmount paths in the same change.
  useEffect(() => {
    if (!isWaking) {
      setWakeRemainingMs(0);
      return undefined;
    }
    const tick = () => {
      if (wakeStartRef.current === null || wakeTotalRef.current === 0) {
        return;
      }
      const remaining = Math.max(
        0,
        wakeTotalRef.current - (Date.now() - wakeStartRef.current),
      );
      setWakeRemainingMs(remaining);
    };
    tick();
    const t = window.setInterval(tick, 250);
    return () => window.clearInterval(t);
  }, [isWaking]);

  return {
    session,
    isLoading,
    isPairing,
    isWaking,
    wakeRemainingMs,
    wakeTotalMs: wakeTotalRef.current,
    pairPhase,
    pairError,
    pairReady,
    lastAction,
    layoutConfig,
    // Expose the DEBOUNCED status to consumers (anti-flicker). All internal
    // hook logic above uses the raw `status` for immediacy; the panel renders
    // this smoothed view so transient mid-handshake rungs don't flip screens.
    status: displayStatus,
    resumeFailed,
    resumeRunning,
    refreshStatus,
    handleConnect,
    handleDisconnect,
    handleRemoteCommand,
    startPairing,
    resume,
    wake,
    coldWake,
    getLogs,
    logsSince,
    clearLogsSince: () => setLogsSince(null),
  };
};
