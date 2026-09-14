import { useState, useEffect, useRef, useCallback } from 'react';

import { Host } from '../types/common/Host_Types';
import { buildServerUrl } from '../utils/buildUrlUtils';

const IDLE_TIMEOUT_MS = 3 * 60 * 1000; // 3 minutes
const COUNTDOWN_SECONDS = 10;
const CHECK_INTERVAL_MS = 10_000; // check every 10 seconds
const ACTIVITY_THROTTLE_MS = 1000; // throttle activity events to 1 per second

interface UseIdleLockMonitorProps {
  activeLocks: Map<string, string>;
  remoteLocks: Map<string, any>;
  releaseControl: (host: Host, device_id?: string, sessionId?: string) => Promise<any>;
  availableHosts: Host[];
  sessionId: string;
  userId: string;
}

interface UseIdleLockMonitorReturn {
  idleDialogOpen: boolean;
  idleCountdown: number;
  handleIdleDismiss: () => void;
}

/**
 * Monitors user activity and shows "Are you still there?" dialog
 * when manual control locks are held for too long without interaction.
 */
export const useIdleLockMonitor = ({
  activeLocks,
  remoteLocks,
  releaseControl,
  availableHosts,
  sessionId,
  userId,
}: UseIdleLockMonitorProps): UseIdleLockMonitorReturn => {
  const [idleDialogOpen, setIdleDialogOpen] = useState(false);
  const [idleCountdown, setIdleCountdown] = useState(COUNTDOWN_SECONDS);

  const lastActivityRef = useRef(Date.now());
  const countdownIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const checkIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Snapshot refs for use in cleanup/callbacks
  const activeLocksRef = useRef(activeLocks);
  const remoteLocksRef = useRef(remoteLocks);
  const availableHostsRef = useRef(availableHosts);
  const releaseControlRef = useRef(releaseControl);
  const hadManualLocksRef = useRef(false);
  activeLocksRef.current = activeLocks;
  remoteLocksRef.current = remoteLocks;
  availableHostsRef.current = availableHosts;
  releaseControlRef.current = releaseControl;

  const isCurrentSessionManualLock = useCallback(
    (lockInfo: any): boolean => {
      if (!lockInfo || lockInfo.owner_type !== 'manual_control') return false;
      const ownerSessionId =
        lockInfo.owner_session_id || lockInfo.session_id || lockInfo.ownerSessionId;
      return ownerSessionId === sessionId;
    },
    [sessionId]
  );

  // Check if user has any manual control locks
  const hasManualLocks = (() => {
    for (const [deviceKey] of activeLocks) {
      const remote = remoteLocks.get(deviceKey);
      if (isCurrentSessionManualLock(remote)) {
        return true;
      }
    }
    return false;
  })();

  // Get list of manual control locks owned by this session
  const getManualLockDevices = useCallback(() => {
    const devices: Array<{ hostName: string; deviceId: string }> = [];
    for (const [deviceKey] of activeLocksRef.current) {
      const remote = remoteLocksRef.current.get(deviceKey);
      if (isCurrentSessionManualLock(remote)) {
        const [hostName, deviceId] = deviceKey.split(':');
        if (hostName && deviceId) {
          devices.push({ hostName, deviceId });
        }
      }
    }
    return devices;
  }, [isCurrentSessionManualLock]);

  // Release all manual control locks
  const releaseAllManualLocks = useCallback(async () => {
    const devices = getManualLockDevices();
    const hosts = availableHostsRef.current;
    const release = releaseControlRef.current;

    for (const { hostName, deviceId } of devices) {
      const host = hosts.find((h) => h.host_name === hostName);
      if (host) {
        try {
          await release(host, deviceId);
        } catch (error) {
          console.error(`[useIdleLockMonitor] Failed to release lock for ${hostName}:${deviceId}:`, error);
        }
      }
    }
  }, [getManualLockDevices]);

  // Send heartbeat for all manual locks
  const sendHeartbeat = useCallback(async () => {
    const devices = getManualLockDevices();
    if (devices.length === 0) return;

    try {
      await fetch(buildServerUrl('/server/control/heartbeat'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          devices: devices.map((d) => ({ host_name: d.hostName, device_id: d.deviceId })),
          session_id: sessionId,
          user_id: userId,
        }),
      });
    } catch (error) {
      console.error('[useIdleLockMonitor] Heartbeat failed:', error);
    }
  }, [getManualLockDevices, sessionId, userId]);

  // Stop the countdown timer
  const stopCountdown = useCallback(() => {
    if (countdownIntervalRef.current) {
      clearInterval(countdownIntervalRef.current);
      countdownIntervalRef.current = null;
    }
  }, []);

  // Handle user dismissing the idle dialog
  const handleIdleDismiss = useCallback(() => {
    setIdleDialogOpen(false);
    stopCountdown();
    setIdleCountdown(COUNTDOWN_SECONDS);
    lastActivityRef.current = Date.now();
    sendHeartbeat();
  }, [stopCountdown, sendHeartbeat]);

  // Start countdown when dialog opens
  useEffect(() => {
    if (!idleDialogOpen) return;

    setIdleCountdown(COUNTDOWN_SECONDS);
    let remaining = COUNTDOWN_SECONDS;

    countdownIntervalRef.current = setInterval(() => {
      remaining -= 1;
      setIdleCountdown(remaining);

      if (remaining <= 0) {
        // Auto-release all locks
        setIdleDialogOpen(false);
        stopCountdown();
        setIdleCountdown(COUNTDOWN_SECONDS);
        releaseAllManualLocks();
      }
    }, 1000);

    return () => stopCountdown();
  }, [idleDialogOpen, stopCountdown, releaseAllManualLocks]);

  // Activity tracking and idle check — only when we have manual locks
  useEffect(() => {
    // Start idle timer from "manual lock acquired in this session", not from app startup.
    if (hasManualLocks && !hadManualLocksRef.current) {
      lastActivityRef.current = Date.now();
      if (idleDialogOpen) {
        setIdleDialogOpen(false);
        stopCountdown();
        setIdleCountdown(COUNTDOWN_SECONDS);
      }
    }
    hadManualLocksRef.current = hasManualLocks;

    if (!hasManualLocks) {
      // No manual locks: reset state
      if (idleDialogOpen) {
        setIdleDialogOpen(false);
        stopCountdown();
        setIdleCountdown(COUNTDOWN_SECONDS);
      }
      return;
    }

    // Throttled activity handler
    let lastThrottle = 0;
    const handleActivity = () => {
      const now = Date.now();
      if (now - lastThrottle < ACTIVITY_THROTTLE_MS) return;
      lastThrottle = now;
      lastActivityRef.current = now;
    };

    const events: Array<keyof DocumentEventMap> = ['mousemove', 'mousedown', 'keydown', 'touchstart', 'scroll'];
    events.forEach((evt) => document.addEventListener(evt, handleActivity, { passive: true }));

    // Periodic idle check
    checkIntervalRef.current = setInterval(() => {
      const idleMs = Date.now() - lastActivityRef.current;
      if (idleMs >= IDLE_TIMEOUT_MS && !idleDialogOpen) {
        setIdleDialogOpen(true);
      }
    }, CHECK_INTERVAL_MS);

    return () => {
      events.forEach((evt) => document.removeEventListener(evt, handleActivity));
      if (checkIntervalRef.current) {
        clearInterval(checkIntervalRef.current);
        checkIntervalRef.current = null;
      }
    };
  }, [hasManualLocks, idleDialogOpen, stopCountdown]);

  return {
    idleDialogOpen,
    idleCountdown,
    handleIdleDismiss,
  };
};
