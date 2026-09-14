import { useState, useCallback, useEffect } from 'react';

import { infraredRemoteConfig } from '../../config/remote/infraredRemote';
import { getInfraredRemoteConfig } from '../../config/remote/infraredRemoteFactory';
import { InfraredRemoteConfig } from '../../config/remote/infraredRemoteBase';
import { Host } from '../../types/common/Host_Types';

import { useControllerApi } from './useControllerApi';
interface InfraredRemoteSession {
  connected: boolean;
  connecting: boolean;
  error: string | null;
}

// Mirrors IRRemoteController.get_ir_health() (backend_host/.../remote/infrared.py).
export interface InfraredStatus {
  ir_path: string;
  ir_type: string;
  device_present: boolean;
  tx_probe_ok: boolean;
  probe_error: string | null;
  last_send_ok: boolean | null;
  last_send_error: string | null;
  last_send_ts: number;
  healthy: boolean;
  detail: string;
}

interface UseInfraredRemoteReturn {
  session: InfraredRemoteSession;
  status: InfraredStatus | null;
  isLoading: boolean;
  lastAction: string;
  layoutConfig: InfraredRemoteConfig;
  handleConnect: () => Promise<void>;
  handleDisconnect: () => Promise<void>;
  handleRemoteCommand: (command: string, params?: any) => Promise<void>;
}

export const useInfraredRemote = (
  host: Host,
  deviceId?: string,
  isConnected?: boolean,
): UseInfraredRemoteReturn => {
  // Get IR type from device configuration
  const device = host?.devices?.find(d => d.device_id === deviceId);
  const irType = device?.ir_type;

  // Get the appropriate config based on IR type
  const layoutConfig = irType ? getInfraredRemoteConfig(irType) : infraredRemoteConfig;
  
  const [session, setSession] = useState<InfraredRemoteSession>({
    connected: false,
    connecting: false,
    error: null,
  });
  const [status, setStatus] = useState<InfraredStatus | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [lastAction, setLastAction] = useState('');
  const { executeRemoteCommand } = useControllerApi(host, deviceId);

  console.log(`[@hook:useInfraredRemote] IR Type: ${irType || 'none'}, Config: ${layoutConfig.remote_info.name}`);

  // Update session based on external connection status
  useEffect(() => {
    if (isConnected) {
      setSession({
        connected: true,
        connecting: false,
        error: null,
      });
      setLastAction('Connected via external control');
      console.log(
        `[@hook:useInfraredRemote] Connected via external control: ${host.host_name}, deviceId: ${deviceId}`,
      );
    } else {
      setSession({
        connected: false,
        connecting: false,
        error: null,
      });
      setLastAction('Disconnected via external control');
      console.log(
        `[@hook:useInfraredRemote] Disconnected via external control: ${host.host_name}, deviceId: ${deviceId}`,
      );
    }
  }, [isConnected, host.host_name, deviceId]);

  // ---- Status probe (drives the Take Control status dot) ----
  // One-shot, non-destructive host-side health probe (ir-ctl --features) run
  // once when the IR panel mounts — enough to confirm lirc can be reached.
  // Deliberately NOT polled: a mid-session IR-Toy wedge is surfaced by the
  // next real key press failing (backend records last_send_ok), so a periodic
  // background poll only added server/host noise. See docs/agent/devices/INFRARED.md §5.
  const refreshStatus = useCallback(async () => {
    try {
      const result = await executeRemoteCommand<{
        success: boolean;
        status?: InfraredStatus;
        error?: string;
      }>('get_pairing_status', {}, { remote_type: 'ir_remote' }, { includeDeviceId: true });
      if (result.success && result.status) {
        setStatus(result.status);
      } else if (result.error) {
        console.warn(`[@hook:useInfraredRemote] get_pairing_status returned error: ${result.error}`);
      }
    } catch (e) {
      console.warn(`[@hook:useInfraredRemote] refreshStatus failed: ${e}`);
    }
  }, [executeRemoteCommand]);

  useEffect(() => {
    if (!host?.host_name || !deviceId) {
      return;
    }
    refreshStatus();
  }, [host?.host_name, deviceId, refreshStatus]);

  const handleConnect = useCallback(async () => {
    setSession((prev) => ({ ...prev, connecting: true, error: null }));
    setIsLoading(true);

    try {
      console.log(`[@hook:useInfraredRemote] Attempting to connect to IR remote: ${host.host_name}`);

      // For IR remote, we assume it's always available since it's hardware-based
      // In a real implementation, this might check if the IR device is accessible
      await new Promise((resolve) => setTimeout(resolve, 1000)); // Simulate connection delay

      setSession({
        connected: true,
        connecting: false,
        error: null,
      });
      setLastAction('Connected to IR remote');

      console.log(`[@hook:useInfraredRemote] Successfully connected to IR remote: ${host.host_name}`);
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : 'Connection failed';
      setSession({
        connected: false,
        connecting: false,
        error: errorMessage,
      });
      setLastAction(`Connection failed: ${errorMessage}`);
      console.error(`[@hook:useInfraredRemote] Connection failed: ${errorMessage}`);
    } finally {
      setIsLoading(false);
    }
  }, [host.host_name]);

  const handleDisconnect = useCallback(async () => {
    setIsLoading(true);

    try {
      console.log(`[@hook:useInfraredRemote] Disconnecting from IR remote: ${host.host_name}`);

      setSession({
        connected: false,
        connecting: false,
        error: null,
      });
      setLastAction('Disconnected from IR remote');

      console.log(`[@hook:useInfraredRemote] Successfully disconnected from IR remote: ${host.host_name}`);
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : 'Disconnect failed';
      console.error(`[@hook:useInfraredRemote] Disconnect failed: ${errorMessage}`);
    } finally {
      setIsLoading(false);
    }
  }, [host.host_name]);

  const handleRemoteCommand = useCallback(
    async (command: string, params?: any) => {
      if (!session.connected) {
        console.warn(`[@hook:useInfraredRemote] Cannot send command - not connected`);
        return;
      }

      setIsLoading(true);

      try {
        console.log(`[@hook:useInfraredRemote] Sending IR command: ${command}`, params);

        // Use the same server proxy pattern as Android TV remote
        const result = await executeRemoteCommand(
          'press_key',
          { key: command, ...params },
          { remote_type: 'ir_remote' },
          { includeDeviceId: true },
        );
        
        if (!result.success) {
          throw new Error(result.error || 'Command failed');
        }

        setLastAction(`Sent IR command: ${command}`);
        console.log(`[@hook:useInfraredRemote] Successfully sent IR command: ${command}`, result);
      } catch (error) {
        const errorMessage = error instanceof Error ? error.message : 'Command failed';
        setLastAction(`Command failed: ${errorMessage}`);
        console.error(`[@hook:useInfraredRemote] Command failed: ${errorMessage}`);
        
        // Don't disconnect on command failure for IR remote
        // IR commands might fail due to hardware issues but connection should remain
      } finally {
        setIsLoading(false);
      }
    },
    [session.connected, host.host_name, deviceId],
  );

  return {
    session,
    status,
    isLoading,
    lastAction,
    layoutConfig,
    handleConnect,
    handleDisconnect,
    handleRemoteCommand,
  };
};
