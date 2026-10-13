import { useState, useCallback, useEffect } from 'react';

import { androidTvRemoteConfig } from '../../config/remote/androidTvRemote';
import { Host } from '../../types/common/Host_Types';

import { useControllerApi } from './useControllerApi';
interface AndroidTvSession {
  connected: boolean;
  connecting: boolean;
  error: string | null;
}

// Mirrors backend_host/.../remote/android_tv.py:get_health() (and the IR
// / Vega InfraredStatus shape). Drives the green/red LED in the Take Control
// panel header — same field names so AndroidTvRemote can reuse the same
// colour logic as InfraredRemote.
export interface AndroidTvStatus {
  adb_device: string;
  device_present: boolean;
  tx_probe_ok: boolean;
  last_send_ok: boolean | null;
  last_send_error: string | null;
  last_send_ts: number;
  healthy: boolean;
  detail: string;
}

interface UseAndroidTvReturn {
  session: AndroidTvSession;
  status: AndroidTvStatus | null;
  isLoading: boolean;
  lastAction: string;
  layoutConfig: typeof androidTvRemoteConfig;
  handleConnect: () => Promise<void>;
  handleDisconnect: () => Promise<void>;
  handleRemoteCommand: (command: string, params?: any) => Promise<void>;
}

export const useAndroidTv = (
  host: Host,
  deviceId?: string,
  isConnected?: boolean,
): UseAndroidTvReturn => {
  const [session, setSession] = useState<AndroidTvSession>({
    connected: false,
    connecting: false,
    error: null,
  });
  const [status, setStatus] = useState<AndroidTvStatus | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [lastAction, setLastAction] = useState('');
  const { executeRemoteCommand } = useControllerApi(host, deviceId);

  // ---- Status probe (drives the Take Control status dot) ----
  // One-shot, non-destructive host-side health probe (`get_pairing_status`
  // → backend `get_health()`) run once when the Android TV panel mounts —
  // enough to confirm ADB is reachable and the last press was OK. Mirrors
  // useInfraredRemote's refreshStatus so the same colour logic in
  // AndroidTvRemote can match the IR / Vega / BLE dots.
  const refreshStatus = useCallback(async () => {
    try {
      const result = await executeRemoteCommand<{
        success: boolean;
        status?: AndroidTvStatus;
        error?: string;
      }>('get_pairing_status', {}, { remote_type: 'android_tv' }, { includeDeviceId: true });
      if (result.success && result.status) {
        setStatus(result.status);
      } else if (result.error) {
        console.warn(`[@hook:useAndroidTv] get_pairing_status returned error: ${result.error}`);
      }
    } catch (e) {
      console.warn(`[@hook:useAndroidTv] refreshStatus failed: ${e}`);
    }
  }, [executeRemoteCommand]);

  useEffect(() => {
    if (!host?.host_name || !deviceId) {
      return;
    }
    refreshStatus();
  }, [host?.host_name, deviceId, refreshStatus]);

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
        `[@hook:useAndroidTv] Connected via external control: ${host.host_name}, deviceId: ${deviceId}`,
      );
    } else {
      setSession({
        connected: false,
        connecting: false,
        error: null,
      });
      setLastAction('');
      console.log(`[@hook:useAndroidTv] Disconnected: ${host.host_name}, deviceId: ${deviceId}`);
    }
  }, [isConnected, host, deviceId]);

  // Remove the old handleConnect - no longer needed for passive mode
  const handleConnect = useCallback(async () => {
    console.log(
      '[@hook:useAndroidTv] Connect requested - this should be handled by parent component',
    );
    // Legacy function kept for compatibility but does nothing in passive mode
  }, []);

  const handleDisconnect = useCallback(async () => {
    console.log(
      '[@hook:useAndroidTv] Disconnect requested - this should be handled by parent component',
    );
    // Don't actually disconnect here - let the parent component handle it
    setLastAction('Disconnect requested');
  }, []);

  const handleRemoteCommand = useCallback(
    async (command: string, _params?: any) => {
      if (!session.connected || isLoading) return;

      setIsLoading(true);
      setLastAction(`Sending ${command}...`);

      try {
        // Map TV commands to ADB key codes
        const keyMap: { [key: string]: string } = {
          POWER: 'POWER',
          UP: 'DPAD_UP',
          DOWN: 'DPAD_DOWN',
          LEFT: 'DPAD_LEFT',
          RIGHT: 'DPAD_RIGHT',
          SELECT: 'DPAD_CENTER',
          BACK: 'BACK',
          HOME: 'HOME',
          MENU: 'MENU',
          VOLUME_UP: 'VOLUME_UP',
          VOLUME_DOWN: 'VOLUME_DOWN',
          VOLUME_MUTE: 'VOLUME_MUTE',
          PLAY_PAUSE: 'MEDIA_PLAY_PAUSE',
          REWIND: 'MEDIA_REWIND',
          FAST_FORWARD: 'MEDIA_FAST_FORWARD',
        };

        const adbKey = keyMap[command] || command;

        // Use the same routing pattern as Android Mobile remote
        const requestBody: any = {
          host_name: host.host_name,
          command: 'press_key',
          params: { key: adbKey },
          remote_type: 'android_tv', // Specify Android TV remote controller
        };

        // Add deviceId if provided
        if (deviceId) {
          requestBody.device_id = deviceId;
        }

        const result = await executeRemoteCommand(
          requestBody.command,
          requestBody.params || {},
          { remote_type: requestBody.remote_type },
          { includeDeviceId: true },
        );
        if (result.success) {
          setLastAction(`Sent ${command}`);
          console.log(`[@hook:useAndroidTv] Successfully sent command: ${command}`);
        } else {
          setLastAction(`Error: ${result.error}`);
          console.error(`[@hook:useAndroidTv] Command failed:`, result.error);
        }
      } catch (error: unknown) {
        const msg = error instanceof Error ? error.message : String(error);
        setLastAction(`Error: ${msg}`);
        console.error(`[@hook:useAndroidTv] Command error:`, error);
      } finally {
        setIsLoading(false);
      }
    },
    [session.connected, isLoading, host, deviceId],
  );

  return {
    session,
    status,
    isLoading,
    lastAction,
    layoutConfig: androidTvRemoteConfig,
    handleConnect,
    handleDisconnect,
    handleRemoteCommand,
  };
};
