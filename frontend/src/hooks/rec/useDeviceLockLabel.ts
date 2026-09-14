import { useMemo } from 'react';

import { Host, Device } from '../../types/common/Host_Types';
import { useHostControl } from '../useHostManager';
import { useAuthContext } from '../../contexts/auth';

/**
 * Returns a display label when a device is under manual user control (not a script).
 * - Lock carries the owner's name (owner_user_name) → that name, whoever is viewing
 * - Authenticated user with our lock → profile full_name
 * - Unknown user → "take-control"
 * - No manual lock → null
 */
export const useDeviceLockLabel = (host: Host, device?: Device): string | null => {
  const { hasActiveLock, getDeviceLockInfo } = useHostControl();
  const { isAuthenticated, profile } = useAuthContext();

  return useMemo(() => {
    if (device?.has_running_deployment) return null;

    const deviceId = device?.device_id || 'device1';
    const deviceKey = `${host.host_name}:${deviceId}`;
    const lockInfo = getDeviceLockInfo(host, deviceId);
    const remoteOwnerType = lockInfo?.owner_type;

    const isOurLock = hasActiveLock(deviceKey);
    const isOtherManualLock = !isOurLock && remoteOwnerType === 'manual_control';

    // REC label should represent manual control only, not script/deployment execution locks.
    if (!isOurLock && !isOtherManualLock) return null;

    // Server-stored owner name (sent on takeControl) — works for every viewer,
    // not just the browser that holds the lock.
    if (lockInfo?.owner_user_name) {
      return lockInfo.owner_user_name;
    }

    if (isAuthenticated && isOurLock && profile?.full_name) {
      return profile.full_name;
    }

    return 'take-control';
  }, [host, device, hasActiveLock, getDeviceLockInfo, isAuthenticated, profile?.full_name]);
};
