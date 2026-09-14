import { useMemo } from 'react';

import { Host, Device } from '../../types/common/Host_Types';
import { useHostControl } from '../useHostManager';
import { useRunningScriptName } from './useRunningScriptName';

/**
 * Derives the running script/deployment label from the device lock itself
 * (owner_type + lock_reason), falling back to the live running.log script name.
 *
 * `hasNamedScript` is true whenever an execution lock exists — the label always
 * resolves (worst case to a generic kind label), so the lock icon can never be
 * hidden by an unparseable lock_reason. That was a real bug: scheduler locks
 * (`deployment_execute:<uuid>`) and campaign locks (`campaign_execute:<uuid>`)
 * matched none of the old prefixes and running.log is only polled for
 * scheduler runs (`has_running_deployment`), so ad-hoc campaigns showed no
 * lock at all and scheduled runs only showed one once the ping cycle caught up.
 *
 * A script launched while a user holds the device runs *under* that manual lock
 * (owner_type stays `manual_control`), so its name lives in `active_script_reason`
 * instead of `lock_reason` — without it we showed the user and lost the script.
 *
 * `scriptOwnerName` is who launched the run, when the lock carries it, so callers
 * can show owner and script together rather than one or the other.
 *
 * lock_reason examples:
 *   - script_execute:gw/superping
 *   - deployment:my_deployment_name
 *   - campaign_execute:<uuid>       (falls back to running.log / kind label)
 */
const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

const KIND_LABELS: Record<string, string> = {
  script_execution: 'script',
  deployment_execution: 'deployment',
};

/** Pull the display part out of a "<kind>:<value>" lock reason. */
const parseLockReason = (reason: string): string | null => {
  const sep = reason.indexOf(':');
  if (sep <= 0) return null;
  // UUID values (campaign/deployment ids) are noise as a display label.
  const value = reason.slice(sep + 1).trim();
  return value && !UUID_RE.test(value) ? value : null;
};

export const useDeviceScriptLabel = (
  host: Host,
  device?: Device,
): { scriptLabel: string | null; hasNamedScript: boolean; scriptOwnerName: string | null } => {
  const { getDeviceLockInfo } = useHostControl();
  const runningScriptName = useRunningScriptName(host, device);

  const deviceId = device?.device_id || 'device1';
  const lockInfo = getDeviceLockInfo(host, deviceId);
  const ownerType = lockInfo?.owner_type;
  const lockReason = typeof lockInfo?.lock_reason === 'string' ? lockInfo.lock_reason : '';
  const activeScriptReason =
    typeof lockInfo?.active_script_reason === 'string' ? lockInfo.active_script_reason : '';
  const ownerUserName =
    typeof lockInfo?.owner_user_name === 'string' ? lockInfo.owner_user_name : '';

  return useMemo(() => {
    const kindLabel = ownerType ? KIND_LABELS[ownerType] : undefined;

    const lockReasonScriptName = parseLockReason(lockReason);
    // Script running under a manual_control lock — the annotation, not the reason.
    const subordinateScriptName = parseLockReason(activeScriptReason);

    const scriptLabel =
      lockReasonScriptName ||
      subordinateScriptName ||
      runningScriptName?.trim() ||
      kindLabel ||
      null;
    const hasNamedScript = Boolean(scriptLabel) && Boolean(kindLabel || subordinateScriptName);

    return {
      scriptLabel,
      hasNamedScript,
      scriptOwnerName: ownerUserName || null,
    };
  }, [lockReason, activeScriptReason, ownerType, ownerUserName, runningScriptName]);
};
