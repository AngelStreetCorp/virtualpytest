import { useCallback } from 'react';

import { Host } from '../../types/common/Host_Types';
import { buildServerUrl } from '../../utils/buildUrlUtils';
import { api } from '../../utils/apiClient';

type JsonValue = string | number | boolean | null | undefined | Record<string, unknown> | unknown[];

type Payload = Record<string, JsonValue>;

interface PostOptions {
  includeDeviceId?: boolean;
  deviceIdOverride?: string | null;
}

/**
 * Shared API helper for controller hooks.
 * Keeps host/device payload wiring consistent across remote command hooks.
 */
export function useControllerApi(host: Host | null | undefined, deviceId?: string | null) {
  const hostName = host?.host_name ?? null;

  const getHostName = useCallback((): string => {
    if (!hostName) {
      throw new Error('No host selected');
    }
    return hostName;
  }, [hostName]);

  const withHostPayload = useCallback(
    (payload: Payload = {}, options?: PostOptions): Payload => {
      const hostPayload: Payload = {
        host_name: getHostName(),
        ...payload,
      };

      const shouldAttachDeviceId = options?.includeDeviceId ?? false;
      const resolvedDeviceId = options?.deviceIdOverride ?? deviceId;

      if (shouldAttachDeviceId && resolvedDeviceId) {
        hostPayload.device_id = resolvedDeviceId;
      }

      return hostPayload;
    },
    [deviceId, getHostName],
  );

  const postToHost = useCallback(
    async <T = any>(path: string, payload: Payload = {}, options?: PostOptions): Promise<T> => {
      return api.post<T>(buildServerUrl(path), withHostPayload(payload, options));
    },
    [withHostPayload],
  );

  const executeRemoteCommand = useCallback(
    async <T = any>(
      command: string,
      params: Record<string, unknown> = {},
      extras: Payload = {},
      options?: PostOptions,
    ): Promise<T> => {
      return postToHost<T>(
        '/server/remote/executeCommand',
        {
          ...extras,
          command,
          params,
        },
        options,
      );
    },
    [postToHost],
  );

  return {
    getHostName,
    withHostPayload,
    postToHost,
    executeRemoteCommand,
  };
}
