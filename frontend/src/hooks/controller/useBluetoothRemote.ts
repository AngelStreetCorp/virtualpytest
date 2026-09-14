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
  pairPhase: PairPhase;
  pairError: string | null;
  lastAction: string;
  layoutConfig: BluetoothRemoteConfig;
  status: BluetoothPairingStatus | null;
  // True when a Resume call has elapsed RESUME_ESCALATE_MS without the
  // status poll observing connected=true. Surfaces a Re-pair escape
  // hatch in the UI so the user isn't stuck cycling Resume forever.
  resumeFailed: boolean;
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
// Max time to wait for the STB to reconnect after a proactive wake. The
// daemon's wake_on_press uses WAKE_TIMEOUT_S=8s of ADV_DIRECT_IND, so
// allow a small margin for the STB to complete its SMP handshake.
// Matches the daemon's WAKE_TIMEOUT_S (8 s) plus a small grace for the
// status poll to observe Connected=True. After this elapses without a
// reconnect we drop isWaking so the existing disconnected-state UI
// (Resume button) takes over — no separate "wake failed" state needed.
// Aligned to the daemon's WAKE_TIMEOUT_S (15 s since BLUETOOTH.md §6.7.24 —
// low-duty ADV_DIRECT_IND reconnects can run past 8 s) plus a ~0.5 s grace for
// the status poll to observe Connected=True. Dropping isWaking before the
// daemon's own window expires would flip the UI off "Waking STB…" prematurely.
const WAKE_WAIT_MS = 15500;
// Deep/cold-standby wake (Broadcom WoBLE) is much slower than the active-
// standby ADV_DIRECT_IND wake: the daemon broadcasts the WoBLE pattern
// (WOBLE_BROADCAST_S=3s) then waits up to COLD_WAKE_TIMEOUT_S=20s for the
// host to boot from S2/S3 and reconnect. Give the UI a margin over that.
const COLD_WAKE_WAIT_MS = 25000;
// How long we'll wait after a user-initiated Resume before deciding
// it didn't recover the link. resume.sh itself takes ~5 s, the STB
// usually pops back within another ~10 s. 20 s gives a comfortable
// margin without leaving the user staring at "STB disconnected" + a
// dead Resume button forever.
const RESUME_ESCALATE_MS = 20000;

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
  const [lastAction, setLastAction] = useState('');
  const [status, setStatus] = useState<BluetoothPairingStatus | null>(null);
  // Debounced view of `status` for display (anti-flicker, see
  // STATUS_DEMOTE_DEBOUNCE_MS). The raw `status` drives all internal logic
  // (polling stop, wake/resume effects) for immediacy; `displayStatus` is what
  // the panel renders, so transient mid-handshake rungs don't flip screens.
  const [displayStatus, setDisplayStatus] = useState<BluetoothPairingStatus | null>(null);
  // Tracks an in-flight downgrade: the lower rank we've seen and when it
  // started, so a sustained regression commits after the debounce window
  // while a brief blip (replaced by a healthier poll) never does.
  const demoteRef = useRef<{ rank: number; since: number } | null>(null);
  const [logsSince, setLogsSince] = useState<string | null>(null);
  const [resumeFailed, setResumeFailed] = useState(false);

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
  // Tracks the post-Resume escalation timer (see RESUME_ESCALATE_MS).
  const resumeTimerRef = useRef<number | null>(null);

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
    status.connected;

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
  }, [executeRemoteCommand]);

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
    setLogsSince(new Date().toISOString());
    setLastAction('Starting BLE pairing — STB must be in pair-new-remote mode');
    // Blank the cached status so the UI doesn't keep showing stale
    // "paired=true / adapter_mac=<old>" from the previous bond while start.sh
    // is wiping it. Without this the status panel reads as already-paired
    // during the 15-25s start.sh window, which contradicts the "Waiting for
    // STB to pair…" overlay and confuses the user. Fresh status arrives on
    // the next poll iteration below.
    setStatus(null);
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
      // 60s ceiling — start.sh completes in ~15s on a working setup. If we
      // haven't seen MAC rotation + paired+hid_ready by 60s the script has
      // either failed or hung; longer waits just hide bugs.
      while (Date.now() - start < 60000) {
        await new Promise((resolve) => setTimeout(resolve, 1500));
        const s = (await executeRemoteCommand<{ success: boolean; status?: BluetoothPairingStatus }>(
          'get_pairing_status',
          {},
          { remote_type: 'bluetooth_remote' },
          { includeDeviceId: true },
        )).status;
        if (s) setStatus(s);
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
      setPairError('STB did not complete handshake within 60 seconds. Ensure the STB is in pair-new-remote mode and retry.');
      setLastAction('Pairing timeout (60 s)');
    } catch (error) {
      const msg = error instanceof Error ? error.message : 'Pair failed';
      setPairPhase('failed');
      setPairError(msg);
      setLastAction(`Pair failed: ${msg}`);
      console.error(`[@hook:useBluetoothRemote] startPairing: ${msg}`);
    } finally {
      setIsPairing(false);
    }
  }, [executeRemoteCommand, refreshStatus]);

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
    setLastAction('Resuming BLE daemon…');
    // Arm the escalation timer BEFORE the API call. resume.sh itself
    // returns quickly ("launched in background"); the STB reconnect
    // happens asynchronously and we observe it via the 2 s status poll.
    setResumeFailed(false);
    if (resumeTimerRef.current !== null) {
      window.clearTimeout(resumeTimerRef.current);
    }
    resumeTimerRef.current = window.setTimeout(() => {
      // The cleanup effect below resets this if the STB reconnects.
      // If the timer fires, resume didn't recover the link in time —
      // the panel will surface a Re-pair button.
      setResumeFailed(true);
      resumeTimerRef.current = null;
    }, RESUME_ESCALATE_MS);
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
      setLastAction('Resume complete — daemon back up');
      await refreshStatus();
    } catch (error) {
      const msg = error instanceof Error ? error.message : 'Resume failed';
      setLastAction(`Resume failed: ${msg}`);
      console.error(`[@hook:useBluetoothRemote] resume: ${msg}`);
    } finally {
      setIsLoading(false);
    }
  }, [executeRemoteCommand, refreshStatus]);

  // Clear the post-Resume escalation as soon as the STB is connected,
  // and also when the user kicks off a re-pair (handled by isPairing).
  // Without this, a successful late reconnect would leave resumeFailed
  // stuck true and the UI would still nag the user to re-pair.
  useEffect(() => {
    if (status?.connected || isPairing) {
      if (resumeTimerRef.current !== null) {
        window.clearTimeout(resumeTimerRef.current);
        resumeTimerRef.current = null;
      }
      if (resumeFailed) setResumeFailed(false);
    }
  }, [status?.connected, isPairing, resumeFailed]);

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
    wakeTimerRef.current = window.setTimeout(() => {
      setIsWaking(false);
      wakeTimerRef.current = null;
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
      if (isWaking) setIsWaking(false);
      wakeAttemptedRef.current = false;
      return;
    }
    if (wakeAttemptedRef.current) return;
    if (!status.daemon_active || !status.bond_present) return;
    wakeAttemptedRef.current = true;
    setIsWaking(true);
    void wake();
    wakeTimerRef.current = window.setTimeout(() => {
      setIsWaking(false);
      wakeTimerRef.current = null;
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
      if (resumeTimerRef.current !== null) {
        window.clearTimeout(resumeTimerRef.current);
        resumeTimerRef.current = null;
      }
    };
  }, []);

  return {
    session,
    isLoading,
    isPairing,
    isWaking,
    pairPhase,
    pairError,
    lastAction,
    layoutConfig,
    // Expose the DEBOUNCED status to consumers (anti-flicker). All internal
    // hook logic above uses the raw `status` for immediacy; the panel renders
    // this smoothed view so transient mid-handshake rungs don't flip screens.
    status: displayStatus,
    resumeFailed,
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
