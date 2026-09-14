import { Device, Host } from '../../types/common/Host_Types';
import { useRunningLog } from './useRunningLog';

/**
 * Returns current running script name. Uses centralized useRunningLog polling.
 */
export const useRunningScriptName = (host: Host, device?: Device): string | null => {
  const isPollingEnabled = Boolean(device?.has_running_deployment && device?.device_id);
  const { scriptName } = useRunningLog(
    host,
    device?.device_id,
    isPollingEnabled
  );
  return scriptName;
};
