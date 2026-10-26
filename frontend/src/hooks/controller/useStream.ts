import { useState, useEffect, useRef, useCallback } from 'react';

import { Host } from '../../types/common/Host_Types';

import { CACHE_CONFIG } from '../../config/constants';
import { useControllerApi } from './useControllerApi';

// ============================================================================
// 24-HOUR CACHE FOR STREAM URLs
// ============================================================================
interface StreamUrlCache {
  url: string;
  audioUrl: string | null;  // audio_stream_url companion (BUG-0596, only set for host_vnc)
  timestamp: number;
}

const streamUrlCache = new Map<string, StreamUrlCache>();

/**
 * Deadline for the getStreamUrl round trip. See the call site for why 15 s: the
 * point is that `isLoadingUrl` must always fall back to false, because every
 * "Loading stream…" a user sees is gated on it.
 */
const STREAM_URL_TIMEOUT_MS = 15000;

// Host names are only unique WITHIN a server — `host-clone-1` exists on both
// VirtualPyTest and QualiAI — so the server must be part of the key or selecting one
// server serves the other's cached URL for 24h (BUG-0106).
function getCachedStreamUrl(server_url: string, host_name: string, device_id: string): StreamUrlCache | null {
  const cacheKey = `${server_url}|${host_name}:${device_id}`;
  const cached = streamUrlCache.get(cacheKey);
  if (cached && (Date.now() - cached.timestamp) < CACHE_CONFIG.LONG_TTL) {
    return cached;
  }
  if (cached) {
    streamUrlCache.delete(cacheKey); // Remove expired
  }
  return null;
}

function setCachedStreamUrl(server_url: string, host_name: string, device_id: string, url: string, audioUrl: string | null) {
  const cacheKey = `${server_url}|${host_name}:${device_id}`;
  streamUrlCache.set(cacheKey, { url, audioUrl, timestamp: Date.now() });
}

interface UseStreamProps {
  host: Host | null; // Can be null when no device is selected
  device_id: string; // Can be empty string when no device is selected
}

interface UseStreamReturn {
  streamUrl: string | null;
  /**
   * Companion audio HLS URL (only set for host_vnc devices with audio capture
   * configured, e.g. vpt-windows's Mixage stereo / Realtek Stereo Mix). The
   * `<audio>` element that consumes it lives next to the VNC iframe in
   * VNCStream.tsx; both share wall-clock timestamps from ffmpeg so they
   * stay in sync. See BUG-0596.
   */
  audioStreamUrl: string | null;
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
  const [audioStreamUrl, setAudioStreamUrl] = useState<string | null>(null);
  // Start in the loading state when there is already a device to ask about. The
  // auto-fetch effect below only runs after the first paint, so a `false` here left
  // one frame where streamUrl was null, urlError was null and isLoadingUrl was
  // false — the exact combination consumers read as "settled, nothing available".
  // That frame is what flashed "No stream available" before the request started.
  const [isLoadingUrl, setIsLoadingUrl] = useState(
    () => Boolean(host && device_id && device_id.trim() !== ''),
  );
  const [urlError, setUrlError] = useState<string | null>(null);

  // Cache to track which devices we've already fetched URLs for
  const fetchedDevicesRef = useRef<Set<string>>(new Set());

  // Track the current device to detect changes
  const currentDeviceRef = useRef<string | null>(null);
  // The device the latest request is for: an answer for any other device arrived after the
  // selection moved on and must not replace the stream (a slow answer for stb4 used to show
  // stb4's picture for a phone selected meanwhile).
  const latestRequestKeyRef = useRef<string | null>(null);
  const { postToHost } = useControllerApi(host, device_id);

  // Resolve a host-relative or fully-qualified URL against the host's owner
  // server origin. Mirrors the conversion logic the video stream_url goes
  // through below. Used by both video and audio paths so HLS.js can load the
  // playlist from the right proxy (BUG-0106 -- a wrong origin 502s).
  const resolveStreamUrl = useCallback(
    (rawUrl: string): string => {
      if (!rawUrl) return rawUrl;
      if (rawUrl.startsWith('http')) return rawUrl;
      const normalizedPath = rawUrl.startsWith('/') ? rawUrl : `/${rawUrl}`;
      const hostAwarePath = normalizedPath.startsWith('/host/')
        ? normalizedPath
        : host?.host_name
          ? `/host/${host.host_name}${normalizedPath}`
          : normalizedPath;
      const ownerOrigin = (() => {
        const ownerServerUrl = host?.server_url;
        if (ownerServerUrl && /^https?:\/\//.test(ownerServerUrl)) {
          try {
            return new URL(ownerServerUrl).origin;
          } catch {
            /* malformed server_url -- fall back to this frontend's origin */
          }
        }
        return typeof window !== 'undefined' ? window.location?.origin : undefined;
      })();
      const cleanHostUrl = host?.host_url?.replace(/\/$/, '');
      if (cleanHostUrl) {
        if (cleanHostUrl.startsWith('http://') || cleanHostUrl.startsWith('https://')) {
          return `${cleanHostUrl}${hostAwarePath}`;
        }
        if (ownerOrigin) {
          return `${ownerOrigin}${hostAwarePath}`;
        }
        return hostAwarePath;
      }
      if (ownerOrigin) {
        return `${ownerOrigin}${hostAwarePath}`;
      }
      return hostAwarePath;
    },
    [host?.host_name, host?.host_url, host?.server_url],
  );

  const fetchStreamUrl = useCallback(
    async (force: boolean = false) => {
      if (!host || !device_id || device_id.trim() === '') return;

      // Server-scoped for the same reason as the cache key: host names collide across servers.
      const deviceKey = `${host.server_url || ''}|${host.host_name}-${device_id}`;
      latestRequestKeyRef.current = deviceKey;
      const isStale = () => latestRequestKeyRef.current !== deviceKey;

      // Check 24h cache first
      if (!force) {
        const cached = getCachedStreamUrl(host.server_url || '', host.host_name, device_id);
        if (cached) {
          console.log(
            `[@hook:useStream] Cache HIT: Stream URL for ${host.host_name}/${device_id} (24h cache)`,
          );
          setStreamUrl(cached.url);
          setAudioStreamUrl(cached.audioUrl);
          setUrlError(null);
          fetchedDevicesRef.current.add(deviceKey);
          return;
        }
      }

      setIsLoadingUrl(true);
      setUrlError(null);

      try {
        const result = await postToHost<{
          success?: boolean;
          stream_url?: string;
          audio_stream_url?: string | null;
          error?: string;
        }>(
          '/server/av/getStreamUrl',
          {},
          // A stream URL is either there in a moment or the host is not going to
          // answer at all. 15 s is generous for the real cases (measured: 80 ms
          // healthy, 400 ms with the host's DB busy) and short enough that a dead
          // host shows an error instead of a spinner that outlives the outage.
          { includeDeviceId: true, timeoutMs: STREAM_URL_TIMEOUT_MS },
        );

        if (result.success && result.stream_url) {
          let processedUrl = result.stream_url;
          if (!processedUrl.startsWith('http')) {
            processedUrl = resolveStreamUrl(processedUrl);
          }

          // Same origin-aware resolution for the audio HLS, so HLS.js can load
          // it from the right proxy (BUG-0106 -- a wrong-origin URL 502s).
          // The audio_stream_url field is optional: when absent the dashboard
          // falls back to the silent VNC view.
          let processedAudioUrl: string | null = null;
          if (result.audio_stream_url) {
            processedAudioUrl = result.audio_stream_url.startsWith('http')
              ? result.audio_stream_url
              : resolveStreamUrl(result.audio_stream_url);
          }

          console.log(
            `[@hook:useStream] ${host.host_name}/${device_id}: ${result.stream_url} -> ${processedUrl}` +
              (processedAudioUrl ? ` (audio ${processedAudioUrl})` : ''),
          );

          // Store in 24h cache (valid for its device, even if the selection moved on)
          setCachedStreamUrl(host.server_url || '', host.host_name, device_id, processedUrl, processedAudioUrl);
          if (isStale()) return;

          setStreamUrl(processedUrl);
          setAudioStreamUrl(processedAudioUrl);
          setUrlError(null);

          // Mark this device as fetched
          fetchedDevicesRef.current.add(deviceKey);
        } else {
          if (isStale()) return;
          const errorMessage = result.error || 'Failed to get stream URL';
          console.error(`[@hook:useStream] Failed to get stream URL:`, errorMessage);
          setUrlError(errorMessage);
          setStreamUrl(null);
        }
      } catch (error: any) {
        if (isStale()) return;
        const errorMessage = error.message || 'Network error: Failed to communicate with server';
        console.error(`[@hook:useStream] Error getting stream URL:`, error);
        setUrlError(errorMessage);
        setStreamUrl(null);
      } finally {
        // Only the CURRENT request may clear the spinner. `isLoadingUrl` is one
        // boolean shared by every in-flight request, and a `finally` runs on the
        // stale early-returns above too: a slow answer for the device the user just
        // left would clear the flag belonging to the device they are now looking
        // at, whose own request is still pending. That is not a hang, it is the
        // mirror image — a spinner replaced by "No stream available" while a
        // perfectly healthy fetch is still running.
        //
        // Guarded with `if (!isStale())` rather than an early `return`: a return
        // inside finally swallows whatever the try block threw, which would turn a
        // real failure into a silent success (no-unsafe-finally).
        if (!isStale()) {
          setIsLoadingUrl(false);
        }
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
      // Clear stream data when no device is selected.
      // isLoadingUrl is cleared with the rest: deselecting while a fetch is in
      // flight used to leave the flag true with no request left to clear it — the
      // device was gone, so nothing would ever run that finally block. A later
      // render (or the same component reused for the next device) then showed a
      // "Loading stream..." that no request could finish.
      setStreamUrl(null);
      setAudioStreamUrl(null);
      setUrlError(null);
      setIsLoadingUrl(false);
      currentDeviceRef.current = null;
      return;
    }

    const deviceKey = `${host?.server_url || ''}|${host?.host_name}-${device_id}`;

    // Check if device changed
    if (currentDeviceRef.current !== deviceKey) {
      currentDeviceRef.current = deviceKey;

      // Fetch for new device (will check cache internally)
      // Don't clear the URL here - let the fetch handle it to avoid flicker
      fetchStreamUrl();
    }
  }, [host?.host_name, device_id, fetchStreamUrl]); // Only depend on host_name, not entire host object

  return {
    streamUrl,
    audioStreamUrl,
    isLoadingUrl,
    urlError,
    refetchStreamUrl,
  };
};
