import { useState, useCallback, useEffect } from 'react';

import { androidTvRemoteConfig } from '../../config/remote/androidTvRemote';
import { Host } from '../../types/common/Host_Types';

import { useControllerApi } from './useControllerApi';
interface AndroidTvSession {
  connected: boolean;
  connecting: boolean;
  error: string | null;
}

interface UseAndroidTvReturn {
  session: AndroidTvSession;
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
  const [isLoading, setIsLoading] = useState(false);
  const [lastAction, setLastAction] = useState('');
  const { executeRemoteCommand } = useControllerApi(host, deviceId);

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
    isLoading,
    lastAction,
    layoutConfig: androidTvRemoteConfig,
    handleConnect,
    handleDisconnect,
    handleRemoteCommand,
  };
};
