import { useState, useEffect, useRef, useCallback } from 'react';

import { Host } from '../../types/common/Host_Types';

import { CACHE_CONFIG } from '../../config/constants';
import { useControllerApi } from './useControllerApi';

// ============================================================================
// 24-HOUR CACHE FOR STREAM URLs
// ============================================================================
interface StreamUrlCache {
  url: string;
  timestamp: number;
}

const streamUrlCache = new Map<string, StreamUrlCache>();

function getCachedStreamUrl(host_name: string, device_id: string): string | null {
  const cacheKey = `${host_name}:${device_id}`;
  const cached = streamUrlCache.get(cacheKey);
  if (cached && (Date.now() - cached.timestamp) < CACHE_CONFIG.LONG_TTL) {
    return cached.url;
  }
  if (cached) {
    streamUrlCache.delete(cacheKey); // Remove expired
  }
  return null;
}

function setCachedStreamUrl(host_name: string, device_id: string, url: string) {
  const cacheKey = `${host_name}:${device_id}`;
  streamUrlCache.set(cacheKey, { url, timestamp: Date.now() });
}

interface UseStreamProps {
  host: Host | null; // Can be null when no device is selected
  device_id: string; // Can be empty string when no device is selected
}

interface UseStreamReturn {
  streamUrl: string | null;
  isLoadingUrl: boolean;
  urlError: string | null;
  refetchStreamUrl: () => void; // Add manual refetch function
}


/**
 * Hook for fetching stream URLs from hosts
 *
 * Simple, single-stream management with caching:
 * - Always requires host and device_id
 * - Auto-fetches on mount when host/device_id changes (only if not cached)
 * - Caches stream URLs per device to prevent duplicate requests
 * - One stream at a time per user
 * - No cleanup functions - React handles lifecycle
 * - Automatically handles HTTP-to-HTTPS proxy conversion
 * - Provides manual refetch function for force refresh
 *
 * Flow: Client → Server → Host → buildStreamUrl(host_info, device_id) → HTTP/HTTPS processing
 */
export const useStream = ({ host, device_id }: UseStreamProps): UseStreamReturn => {
  const [streamUrl, setStreamUrl] = useState<string | null>(null);
  const [isLoadingUrl, setIsLoadingUrl] = useState(false);
  const [urlError, setUrlError] = useState<string | null>(null);

  // Cache to track which devices we've already fetched URLs for
  const fetchedDevicesRef = useRef<Set<string>>(new Set());

  // Track the current device to detect changes
  const currentDeviceRef = useRef<string | null>(null);
  const { postToHost } = useControllerApi(host, device_id);

  const fetchStreamUrl = useCallback(
    async (force: boolean = false) => {
      if (!host || !device_id || device_id.trim() === '') return;

      const deviceKey = `${host.host_name}-${device_id}`;

      // Check 24h cache first
      if (!force) {
        const cachedUrl = getCachedStreamUrl(host.host_name, device_id);
        if (cachedUrl) {
          console.log(
            `[@hook:useStream] Cache HIT: Stream URL for ${host.host_name}/${device_id} (24h cache)`,
          );
          setStreamUrl(cachedUrl);
          setUrlError(null);
          fetchedDevicesRef.current.add(deviceKey);
          return;
        }
      }

      setIsLoadingUrl(true);
      setUrlError(null);

      try {
        console.log(
          `[@hook:useStream] Fetching stream URL for host: ${host.host_name}, device: ${device_id}`,
        );

        const result = await postToHost<{ success?: boolean; stream_url?: string; error?: string }>(
          '/server/av/getStreamUrl',
          {},
          { includeDeviceId: true },
        );

        if (result.success && result.stream_url) {
          console.log(`[@hook:useStream] Stream URL received: ${result.stream_url}`);

          let processedUrl = result.stream_url;
          if (!processedUrl.startsWith('http')) {
            const normalizedPath = processedUrl.startsWith('/') ? processedUrl : `/${processedUrl}`;
            const hostAwarePath = normalizedPath.startsWith('/host/')
              ? normalizedPath
              : host?.host_name
                ? `/host/${host.host_name}${normalizedPath}`
                : normalizedPath;
            const frontendOrigin = typeof window !== 'undefined' ? window.location?.origin : undefined;
            const cleanHostUrl = host?.host_url?.replace(/\/$/, '');

            if (cleanHostUrl) {
              // host_url can be absolute (https://...) or relative (/host/<name>).
              // hostAwarePath already includes /host/<name>/..., so avoid double-prefixing.
              if (cleanHostUrl.startsWith('http://') || cleanHostUrl.startsWith('https://')) {
                processedUrl = `${cleanHostUrl}${hostAwarePath}`;
              } else if (frontendOrigin) {
                processedUrl = `${frontendOrigin}${hostAwarePath}`;
              } else {
                processedUrl = hostAwarePath;
              }
              console.log(`[@hook:useStream] Resolved relative stream URL via host_url: ${processedUrl}`);
            } else if (frontendOrigin) {
              processedUrl = `${frontendOrigin}${hostAwarePath}`;
              console.log(`[@hook:useStream] Resolved relative stream URL against frontend origin: ${processedUrl}`);
            } else {
              processedUrl = hostAwarePath;
              console.log(`[@hook:useStream] Using normalized path for relative stream URL: ${processedUrl}`);
            }
          }

          console.log(
            `[@hook:useStream] Stream URL processed: ${result.stream_url} -> ${processedUrl}`,
          );

          setStreamUrl(processedUrl);
          setUrlError(null);

          // Store in 24h cache
          setCachedStreamUrl(host.host_name, device_id, processedUrl);

          // Mark this device as fetched
          fetchedDevicesRef.current.add(deviceKey);
        } else {
          const errorMessage = result.error || 'Failed to get stream URL';
          console.error(`[@hook:useStream] Failed to get stream URL:`, errorMessage);
          setUrlError(errorMessage);
          setStreamUrl(null);
        }
      } catch (error: any) {
        const errorMessage = error.message || 'Network error: Failed to communicate with server';
        console.error(`[@hook:useStream] Error getting stream URL:`, error);
        setUrlError(errorMessage);
        setStreamUrl(null);
      } finally {
        setIsLoadingUrl(false);
      }
    },
    [host?.host_name, device_id, postToHost], // Only depend on host_name, not entire host object
  );

  // Manual refetch function for force refresh
  const refetchStreamUrl = useCallback(() => {
    console.log(`[@hook:useStream] Manual refetch requested for device: ${device_id}`);
    fetchStreamUrl(true);
  }, [device_id, fetchStreamUrl]);

  // Auto-fetch stream URL when host_name or device_id changes
  useEffect(() => {
    // Only process if we have a valid device_id
    if (!device_id || device_id.trim() === '') {
      // Clear stream data when no device is selected
      setStreamUrl(null);
      setUrlError(null);
      currentDeviceRef.current = null;
      return;
    }

    const deviceKey = `${host?.host_name}-${device_id}`;

    // Check if device changed
    if (currentDeviceRef.current !== deviceKey) {
      console.log(
        `[@hook:useStream] Device changed from ${currentDeviceRef.current} to ${deviceKey}`,
      );
      currentDeviceRef.current = deviceKey;

      // Fetch for new device (will check cache internally)
      // Don't clear the URL here - let the fetch handle it to avoid flicker
      fetchStreamUrl();
    }
  }, [host?.host_name, device_id, fetchStreamUrl]); // Only depend on host_name, not entire host object

  return {
    streamUrl,
    isLoadingUrl,
    urlError,
    refetchStreamUrl,
  };
};
