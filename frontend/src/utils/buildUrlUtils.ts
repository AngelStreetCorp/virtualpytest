/**
 * Centralized URL Building Utilities (Frontend)
 *
 * Single source of truth for all URL construction patterns.
 * Mirrors the Python buildUrlUtils.py for consistency.
 *
 * CRITICAL: Always use these functions for URL building to ensure:
 * - Environment-specific configuration (dev vs prod)
 * - Consistent URL patterns across the application
 * - Easy maintenance and debugging
 * - Proper routing in different deployment scenarios
 *
 * URL Building Categories:
 * 1. Server URLs - Backend API endpoints (buildServerUrl)
 * 2. Host URLs - Direct device communication (buildHostUrl)
 * 3. Image URLs - Static assets and captures (buildHostImageUrl, buildCloudImageUrl)
 * 4. Stream URLs - Live video streams (buildStreamUrl)
 */

import { getEnv, APP_CONFIG, SERVER_CONFIG, STORAGE_KEYS } from '../config/constants';

// =====================================================
// SERVER URL BUILDING (Frontend to Backend Server)
// =====================================================

// =====================================================
// LOCAL PATH NORMALIZATION (Windows + Linux)
// =====================================================
const normalizeLocalPathToStreamUrl = (path: string): string => {
  if (!path) return '';
  const normalized = path.replace(/\\/g, '/');

  // If already looks like a stream path, keep it
  if (normalized.startsWith('/stream/')) {
    return normalized;
  }

  // Linux absolute path
  if (normalized.startsWith('/var/www/html/')) {
    return normalized.replace('/var/www/html', '');
  }

  // Windows absolute path (e.g., C:\virtualpytest\stream\capture\captures)
  const streamIdx = normalized.toLowerCase().indexOf('/stream/');
  if (streamIdx >= 0) {
    return normalized.slice(streamIdx);
  }

  // Fallback: ensure leading slash
  return normalized.startsWith('/') ? normalized : `/${normalized}`;
};

/**
 * Get the base server URL (without endpoint)
 * In development mode with Vite proxy: returns empty string for relative URLs
 * In production: reads from localStorage or falls back to default
 * Used for Socket.IO connections and base URL extraction
 */
/**
 * Normalize server URL by stripping /server from the end
 * This prevents duplicate /server/server/... when building URLs
 * Only handles the obvious case where users accidentally include /server in VITE_SERVER_URL
 */
const normalizeServerUrl = (url: string): string => {
  if (!url || url.trim() === '') return url;

  const trimmed = url.trim();

  // Only strip /server from the end to prevent duplicate /server/server/...
  if (trimmed.endsWith('/server')) {
    return trimmed.slice(0, -7); // Remove '/server' (7 characters)
  }

  return trimmed;
};

/** One value per page load: stable across re-renders (so the iframe is not reloaded on every
 *  render) but never reused across sessions. */
const VNC_SESSION_TAG = Date.now().toString(36);

export const withVncCacheBust = (url: string): string =>
  `${url}${url.includes('?') ? '&' : '?'}_vpt=${VNC_SESSION_TAG}`;

export const getServerBaseUrl = (): string => {
  // Use localStorage selection or fall back to configured URL
  try {
    const selectedServer = localStorage.getItem(STORAGE_KEYS.SELECTED_SERVER);
    return normalizeServerUrl(selectedServer || SERVER_CONFIG.DEFAULT_URL);
  } catch {
    return normalizeServerUrl(SERVER_CONFIG.DEFAULT_URL);
  }
};

export const buildServerUrl = (endpoint: string): string => {
  const serverUrl = getServerBaseUrl();
  const cleanEndpoint = endpoint.startsWith('/') ? endpoint.slice(1) : endpoint;
  const url = `${serverUrl}/${cleanEndpoint}`;
  
  // Always add team_id to all server URLs
  return `${url}${url.includes('?') ? '&' : '?'}team_id=${APP_CONFIG.DEFAULT_TEAM_ID}`;
};

// Mirrors backend_server/src/routes/server_host_session_routes.py:_GATED_HOST_PATH — any
// path the proxy's auth_request actually gates. Kept in sync manually; a path added to one
// side with no matching change on the other either mints a useless cookie (harmless) or lets
// a real request through ungated (a hole), so treat drift here as a security review item.
const GATED_HOST_PATH_RE =
  /\/host\/([^/]+)\/(?:vnc_lite\.html|websockify|vnc\/|core\/|vendor\/|include\/|app\/|utils\/|stream\/)/;

/** Whether `url` is proxied through a path the proxy's auth_request gate covers. */
export const isGatedHostPath = (url: string | null | undefined): boolean =>
  !!url && GATED_HOST_PATH_RE.test(url);

/**
 * Mint the short-lived HttpOnly host-session cookie (BUG-0107 step 2) before a
 * VNC iframe or HLS player navigates to a proxied `/host/<name>/...` URL. The
 * proxy's `auth_request` gate rejects that navigation without this cookie, so
 * callers must await this and only use the URL on success. A no-op (resolves
 * true, no network call) for URLs the gate does not cover.
 *
 * VNC only needs this once, at the initial websocket handshake — the
 * connection then persists independent of cookie expiry. HLS is not a single
 * persistent connection: the player re-fetches segments for as long as
 * playback continues, so a long-running view needs this re-called
 * periodically (see the `useHostSession` hook) or it will 401 mid-stream once
 * the cookie's short TTL elapses.
 */
export const ensureHostSession = async (url: string): Promise<boolean> => {
  const match = GATED_HOST_PATH_RE.exec(url);
  if (!match) return true;
  const hostName = match[1];

  try {
    const response = await fetch(buildServerUrl('/server/host-session/session'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ host_name: hostName }),
    });
    return response.ok;
  } catch {
    return false;
  }
};

/**
 * Build a URL against the PRIMARY (main) server, ignoring the currently
 * selected server. Use for resources that only ever live on the main server
 * regardless of the server-picker selection (e.g. CI/CD reports, runners).
 */
export const buildPrimaryServerUrl = (endpoint: string): string => {
  const primaryUrl = getAllServerUrls()[0] || SERVER_CONFIG.DEFAULT_URL;
  return buildServerUrlForServer(primaryUrl, endpoint);
};

/**
 * Build a server URL with additional query parameters
 * Centralized function to handle URL construction with params
 * Handles both absolute and relative URLs (behind nginx proxy)
 * 
 * @param endpoint - API endpoint (e.g., '/server/navigation/preview/123')
 * @param params - Object with query parameters (supports string, string[], or undefined)
 * @returns Complete URL string with all parameters
 */
export const buildServerUrlWithParams = (
  endpoint: string, 
  params: Record<string, string | string[] | undefined>
): string => {
  const baseUrl = buildServerUrl(endpoint);
  
  // Use URL API with window.location.origin as base for relative URLs
  const url = new URL(baseUrl, window.location.origin);
  
  // Add provided params (skip undefined values, handle arrays)
  Object.entries(params).forEach(([key, value]) => {
    if (value === undefined) return;
    
    if (Array.isArray(value)) {
      // Append each array item as separate param (e.g., node_ids=1&node_ids=2)
      value.forEach(v => url.searchParams.append(key, v));
    } else {
      url.searchParams.append(key, value);
    }
  });
  
  // Return relative path if using relative URLs, otherwise full URL
  const serverBase = getServerBaseUrl();
  if (serverBase === '') {
    // Relative URL - return pathname + search
    return url.pathname + url.search;
  }
  
  return url.toString();
};

/**
 * Parse URL list from various formats
 * Handles: comma-separated strings, JSON arrays, stringified arrays, single URLs
 * 
 * Examples:
 *   "url1,url2,url3" -> ["url1", "url2", "url3"]
 *   '["url1", "url2"]' -> ["url1", "url2"]
 *   "['url1', 'url2']" -> ["url1", "url2"]
 *   "url1" -> ["url1"]
 *   '[]' -> []
 */
const parseUrlList = (value: string | string[]): string[] => {
  // Already an array
  if (Array.isArray(value)) {
    return value.map(u => u.trim()).filter(u => u);
  }
  
  if (!value || typeof value !== 'string') {
    return [];
  }
  
  const trimmed = value.trim();
  
  // Empty or invalid patterns
  if (!trimmed || trimmed === '[]' || trimmed === '{}' || trimmed === 'null' || trimmed === 'undefined') {
    return [];
  }
  
  // Try to parse as JSON array first (handles '["url1", "url2"]')
  if (trimmed.startsWith('[') && trimmed.endsWith(']')) {
    try {
      // Try direct JSON parse
      const parsed = JSON.parse(trimmed);
      if (Array.isArray(parsed)) {
        return parsed.map(u => String(u).trim()).filter(u => u);
      }
    } catch {
      // Not valid JSON, try to extract URLs from stringified array
      // Handle cases like "['url1', 'url2']" or '["url1", "url2"]'
      const urlMatch = trimmed.match(/\[(.*)\]/);
      if (urlMatch) {
        const inner = urlMatch[1];
        // Split by comma and clean up quotes
        return inner
          .split(',')
          .map(u => u.trim().replace(/^["']|["']$/g, ''))
          .filter(u => u);
      }
    }
  }
  
  // Comma-separated string (handles "url1,url2,url3")
  if (trimmed.includes(',')) {
    return trimmed.split(',').map(u => u.trim()).filter(u => u);
  }
  
  // Single URL
  return [trimmed];
};

/**
 * Validate if a string is a valid server URL
 */
const isValidServerUrl = (url: string): boolean => {
  if (!url || !url.trim()) return false;
  const trimmed = url.trim();
  // Reject common invalid patterns
  if (trimmed === '[]' || trimmed === '{}' || trimmed === 'null' || trimmed === 'undefined') {
    return false;
  }
  // Reject if still contains brackets (malformed)
  if (trimmed.includes('[') || trimmed.includes(']')) {
    return false;
  }
  // Must have at least a domain or localhost
  if (trimmed.includes('localhost') || trimmed.includes('.') || trimmed.match(/^\d+\.\d+\.\d+\.\d+/)) {
    return true;
  }
  return false;
};

/**
 * Get all configured server URLs (primary + slaves)
 * Reads VITE_SERVER_URL and VITE_SLAVE_SERVER_URL
 * 
 * Smart parsing handles multiple formats:
 * - Comma-separated: "url1,url2"
 * - JSON array: ["url1", "url2"]
 * - Stringified array: '["url1", "url2"]' or "['url1', 'url2']"
 * - Single URL: "url1"
 */
export const getAllServerUrls = (): string[] => {
  const urls: string[] = [];

  // Parse primary URL from env
  const primaryUrl = getEnv('VITE_SERVER_URL');
  if (primaryUrl) {
    const parsedPrimary = parseUrlList(primaryUrl);
    const normalizedPrimary = parsedPrimary.map(url => normalizeServerUrl(url));
    urls.push(...normalizedPrimary.filter(url => isValidServerUrl(url)));
  }

  // Parse slave URLs (supports all formats)
  const slaveUrls = getEnv('VITE_SLAVE_SERVER_URL');
  if (slaveUrls) {
    const parsedSlaves = parseUrlList(slaveUrls);
    const normalizedSlaves = parsedSlaves.map(url => normalizeServerUrl(url));
    urls.push(...normalizedSlaves.filter(url => isValidServerUrl(url)));
  }

  // Fall back to default if no URLs configured
  if (urls.length === 0 && SERVER_CONFIG.DEFAULT_URL) {
    urls.push(normalizeServerUrl(SERVER_CONFIG.DEFAULT_URL));
  }

  return urls;
};

/**
 * Build URL for specific server with team_id
 * @param serverUrl - The server base URL
 * @param endpoint - API endpoint
 * @returns Complete URL with team_id
 */
export const buildServerUrlForServer = (serverUrl: string, endpoint: string): string => {
  // Validate serverUrl
  if (!serverUrl) {
    const error = `[buildServerUrlForServer] Invalid serverUrl: "${serverUrl}" - check VITE_SERVER_URL environment variable`;
    console.error(error);
    throw new Error(error);
  }
  
  // Ensure serverUrl has protocol (http:// or https://)
  let normalizedServerUrl = serverUrl;
  if (!serverUrl.match(/^https?:\/\//)) {
    normalizedServerUrl = `http://${serverUrl}`;
    console.log(`[buildServerUrlForServer] Added protocol: ${serverUrl} -> ${normalizedServerUrl}`);
  }

  // Normalize URL to prevent duplicate /server/server/...
  normalizedServerUrl = normalizeServerUrl(normalizedServerUrl);
  
  const cleanEndpoint = endpoint.startsWith('/') ? endpoint.slice(1) : endpoint;
  const url = `${normalizedServerUrl}/${cleanEndpoint}`;
  
  // Always add team_id to all server URLs
  return `${url}${url.includes('?') ? '&' : '?'}team_id=${APP_CONFIG.DEFAULT_TEAM_ID}`;
};

/**
 * Build URL using a specific selected server
 * @param endpoint - API endpoint
 * @param selectedServerUrl - The currently selected server URL
 * @returns Complete URL with team_id
 */
export const buildSelectedServerUrl = (endpoint: string, selectedServerUrl: string): string => {
  return buildServerUrlForServer(selectedServerUrl, endpoint);
};

// =====================================================
// HOST URL BUILDING (Frontend to Device Hosts)
// =====================================================

/**
 * Build host URL for direct host communication (Frontend to host)
 * Core implementation for all host-based URL building
 */
const internalBuildHostUrl = (host: any, endpoint: string): string => {
  if (!host) {
    throw new Error('Host information is required for buildHostUrl');
  }

  const cleanEndpointRaw = endpoint.startsWith('/') ? endpoint.slice(1) : endpoint;
  const cleanEndpoint = normalizeHostStreamPath(host, cleanEndpointRaw);

  // Use host_url if available (most efficient)
  if (host.host_url) {
    let hostUrl = resolveHostUrlOrigin(host);
    let finalEndpoint = cleanEndpoint;

    // When host_url is a proxy path (e.g., /host/host-clone-2), the "host/" prefix
    // in endpoints is redundant — strip it to avoid doubled paths like
    // /host/host-clone-2/host/host-clone-2/stream/...
    //
    // Test the host's registered PATH, not `hostUrl`: once resolveHostUrlOrigin has
    // prefixed another server's origin, the resolved value no longer starts with
    // '/host/', this check silently stopped firing, and every cross-server stream URL
    // came out doubled — which is precisely the case the prefixing exists to fix.
    const hostPath: string = host.host_url;
    if (hostPath.startsWith('/host/') && finalEndpoint.startsWith('host/')) {
      finalEndpoint = finalEndpoint.slice('host/'.length);
    }

    // For static files (images, streams), strip port ONLY for direct local IP addresses
    // This logic is not needed when hosts register with proper nginx proxy URLs
    if (endpoint.includes('host/stream/') || endpoint.includes('host/captures/')) {
      const isDirectLocalIp = hostUrl.match(/^https?:\/\/(192\.168\.|10\.|127\.0\.0\.1)/);
      if (isDirectLocalIp && hostUrl.includes(':')) {
        hostUrl = hostUrl.replace(/:\d+$/, '');
      }
    }

    return `${hostUrl}/${finalEndpoint}`;
  }

  throw new Error('Host must have either host_url or both host_ip and host_port');
};

/**
 * Resolve a host's base URL against the server that owns it.
 *
 * Hosts register a RELATIVE host_url (`/host/<name>`) because normally the frontend and the
 * host's proxy are the same origin. With several servers in the selector that stops being
 * true: viewing a host of server B from server A's frontend resolved `/host/<name>` against
 * A's proxy, which either 404s or — when A happens to have a stale map entry for that name —
 * 502s on an upstream that is not the host at all.
 *
 * `server_url` (stamped in ServerManagerProvider) is that server's public base URL, so
 * prefixing with it produces the URL the host is actually reachable at. Same-origin and
 * absolute host_urls are untouched.
 */
const resolveHostUrlOrigin = (host: any): string => {
  const hostUrl = host?.host_url || '';
  if (!hostUrl.startsWith('/')) return hostUrl; // already absolute

  const serverUrl = host?.server_url;
  if (!serverUrl || !/^https?:\/\//.test(serverUrl)) return hostUrl;

  try {
    const serverOrigin = new URL(serverUrl).origin;
    if (typeof window !== 'undefined' && serverOrigin === window.location.origin) {
      return hostUrl; // same origin — relative path is correct and keeps working offline of DNS
    }
    return `${serverOrigin}${hostUrl}`;
  } catch {
    return hostUrl;
  }
};

/**
 * Ensure stream paths include host identifier for nginx routing.
 * Nginx expects: /host/<host_identifier>/stream/...
 * Some callers build /host/stream/... from local paths (/var/www/html/stream/...),
 * which results in missing host identifier and 404s.
 */
const normalizeHostStreamPath = (host: any, endpoint: string): string => {
  if (!host?.host_name) return endpoint;

  // If host_url already contains the host identifier path (e.g., /host/host-clone-2),
  // don't insert it again — internalBuildHostUrl will prepend host_url
  if (host.host_url?.includes(`/host/${host.host_name}`)) return endpoint;

  // Only adjust if endpoint starts with host/stream/ (missing host identifier)
  if (endpoint.startsWith('host/stream/')) {
    return `host/${host.host_name}/${endpoint.slice('host/'.length)}`;
  }

  return endpoint;
};

/**
 * Build URL for live screenshot captures
 * Supports device-specific capture paths for multi-device hosts
 */
export const buildCaptureUrl = (host: any, timestamp: string, deviceId?: string): string => {
  if (!deviceId) {
    throw new Error('deviceId is required for buildCaptureUrl');
  }
  // Get device-specific capture path
  const capturePath = getDeviceCaptureUrlPath(host, deviceId);
  return internalBuildHostUrl(host, `host${capturePath}/capture_${timestamp}.jpg`);
};

/**
 * Build URL for an ARCHIVED full-res still kept by the hot/cold archiver for 24h
 * (only present when ARCHIVE_CAPTURES is enabled on the host). Mirrors
 * buildMetadataChunkUrl's hour-folder layout: captures/{hour}/capture_{seq}.jpg,
 * where seq = (seconds since midnight) * 5 — the native 5fps sequence space the
 * archiver names cold stills in. nginx serves captures/{hour}/ (cold→hot try_files).
 *
 * Example: buildArchivedCaptureUrl(host, 'device1', 15, 277225)
 *   -> "http://host/stream/capture1/captures/15/capture_277225.jpg"
 */
export const buildArchivedCaptureUrl = (
  host: any,
  deviceId: string,
  hour: number,
  seq: number,
): string => {
  if (!deviceId) {
    throw new Error('deviceId is required for buildArchivedCaptureUrl');
  }
  const capturePath = getDeviceCaptureUrlPath(host, deviceId);
  const seqStr = String(seq).padStart(6, '0');
  return internalBuildHostUrl(host, `host${capturePath}/${hour}/capture_${seqStr}.jpg`);
};

/**
 * Build URL for cropped images
 * Supports device-specific capture paths for multi-device hosts
 */
export const buildCroppedImageUrl = (host: any, filename: string, deviceId?: string): string => {
  if (!deviceId) {
    throw new Error('deviceId is required for buildCroppedImageUrl');
  }
  // Get device-specific capture path
  const capturePath = getDeviceCaptureUrlPath(host, deviceId);
  return internalBuildHostUrl(host, `host${capturePath}/cropped/${filename}`);
};

/**
 * Build URL for reference images
 */
export const buildReferenceImageUrl = (
  host: any,
  deviceModel: string,
  filename: string,
  deviceId?: string,
): string => {
  if (!deviceId) {
    throw new Error('deviceId is required for buildReferenceImageUrl');
  }
  // Get device-specific capture path as base for resources
  const capturePath = getDeviceCaptureUrlPath(host, deviceId);
  return internalBuildHostUrl(host, `host${capturePath}/resources/${deviceModel}/${filename}`);
};

/**
 * Build URL for verification result images
 */
export const buildVerificationResultUrl = (host: any, resultsPath: string): string => {
  // Convert local path to URL path
  const urlPath = resultsPath.replace('/var/www/html/', '');
  // Add host/ prefix like other image URLs (cropping, captures, etc.)
  return internalBuildHostUrl(host, `host/${urlPath}`);
};

/**
 * Build URL for HLS stream
 * Supports device-specific stream paths for multi-device hosts
 */
export const buildStreamUrl = (host: any, deviceId?: string, mode: 'live' | 'archive' = 'live'): string => {
  console.log('[buildStreamUrl] Starting stream URL construction', {
    hostName: host?.host_name,
    hostUrl: host?.host_url,
    hostIp: host?.host_ip,
    hostPort: host?.host_port,
    deviceId,
    devicesCount: host?.devices?.length || 0
  });

  if (!deviceId) {
    console.error('[buildStreamUrl] deviceId is required but not provided');
    throw new Error('deviceId is required for buildStreamUrl');
  }

  try {
    // Check if this is a VNC device - return VNC URL directly (no HLS suffix)
    // Cache-busted per session: a stale entry here is not a slow picture, it is a dead
    // iframe. If this URL ever answers from somewhere other than the proxy's vnc_lite
    // location — as it did while the mobile app's own navigation bug sent it elsewhere — the
    // WebView caches that response, security headers included, and replays it on every later
    // load: X-Frame-Options: SAMEORIGIN, ERR_BLOCKED_BY_RESPONSE, "Webpage not available",
    // permanently and invisibly. The page is a live console, so there is nothing worth
    // keeping across sessions anyway.
    const devices = host?.devices || [];
    const device = devices.find((d: any) => d?.device_id === deviceId);
    if (device?.device_model === 'host_vnc' && mode === 'live') {
      const vncPath = device?.video_stream_path;
      if (!vncPath) {
        throw new Error(`VNC device ${deviceId} has no video_stream_path configured`);
      }
      // Full URL: return as-is
      if (vncPath.startsWith('http://') || vncPath.startsWith('https://')) {
        return withVncCacheBust(vncPath);
      }
      // Relative path (nginx proxy mode): build full URL via host
      if (vncPath.startsWith('/')) {
        const finalUrl = withVncCacheBust(internalBuildHostUrl(host, vncPath.slice(1)));
        console.log('[buildStreamUrl] VNC URL constructed', { deviceId, vncPath, finalUrl });
        return finalUrl;
      }
      // Path without leading slash: direct mode via websockify port 6080
      const hostIp = host?.host_ip;
      if (!hostIp) {
        throw new Error('host_ip is required to build VNC URL for direct mode');
      }
      const finalUrl = withVncCacheBust(`https://${hostIp}:6080/${vncPath}`);
      console.log('[buildStreamUrl] VNC direct URL constructed', { deviceId, finalUrl });
      return finalUrl;
    }

    // For regular devices: get stream path and append HLS manifest path
    const streamPath = getDeviceStreamUrlPath(host, deviceId);
    console.log('[buildStreamUrl] Device stream path resolved', {
      deviceId,
      streamPath
    });

    // Manifest is in segments/ subfolder (hot/cold architecture)
    const fullEndpoint = `host${streamPath}/segments/output.m3u8`;
    const finalUrl = internalBuildHostUrl(host, fullEndpoint);

    console.log('[buildStreamUrl] Stream URL constructed successfully', {
      deviceId,
      streamPath,
      fullEndpoint,
      finalUrl
    });

    return finalUrl;
  } catch (error) {
    console.error('[buildStreamUrl] Failed to construct stream URL', {
      deviceId,
      hostName: host?.host_name,
      error: error instanceof Error ? error.message : error
    });
    throw error;
  }
};

/**
 * Build URL for host API endpoints (Flask routes)
 */
export const buildHostUrl = (host: any, endpoint: string): string => {
  return internalBuildHostUrl(host, endpoint);
};

/**
 * Build URL for any image stored on the host (nginx-served)
 * This replaces the scattered local buildImageUrl functions
 */
export const buildHostImageUrl = (host: any, imagePath: string): string => {
  if (!imagePath) return '';

  // If it's already a complete URL, return as is
  if (imagePath.startsWith('http://') || imagePath.startsWith('https://')) {
    return imagePath;
  }

  // Handle absolute paths by converting to relative
  let cleanPath = imagePath;
  const normalizedStreamPath = normalizeLocalPathToStreamUrl(cleanPath);
  if (normalizedStreamPath.startsWith('/stream/')) {
    cleanPath = normalizedStreamPath.replace(/^\/+/, '');
  } else if (cleanPath.startsWith('/var/www/html/')) {
    cleanPath = cleanPath.replace('/var/www/html/', '');
  }

  // Ensure path doesn't start with / for buildHostUrl
  cleanPath = cleanPath.startsWith('/') ? cleanPath.slice(1) : cleanPath;

  // Use buildHostUrl for relative URLs
  if (host?.host_name) {
    return internalBuildHostUrl(host, `host/${cleanPath}`);
  }

  // Fallback if no host selected
  return imagePath;
};

/**
 * Normalize image source into a host-accessible URL for API payloads and previews.
 * Supports absolute URLs, nginx-style paths, local paths, and bare filenames.
 */
export const resolveImageSourceUrl = (host: any, imageSource: string, deviceId?: string): string => {
  if (!imageSource) return '';

  // Already absolute URL
  if (imageSource.startsWith('http://') || imageSource.startsWith('https://')) {
    return imageSource;
  }

  // Nginx-style absolute path
  if (imageSource.startsWith('/host/') || imageSource.startsWith('/stream/')) {
    // If the path already includes the host identifier (e.g. /host/host3/stream/...),
    // it is already a complete proxy-relative URL — return it untouched. Re-running it
    // through internalBuildHostUrl re-prepends host_url and doubles the host segment
    // (/host/host3/host3/stream/...), which 404s the image.
    if (host?.host_name && imageSource.startsWith(`/host/${host.host_name}/`)) {
      return imageSource;
    }
    return internalBuildHostUrl(host, imageSource.slice(1));
  }

  // Bare filename fallback (e.g., verification_source.jpg)
  if (!imageSource.includes('/') && !imageSource.includes('\\') && host && deviceId) {
    try {
      const capturePath = getDeviceCaptureUrlPath(host, deviceId);
      return internalBuildHostUrl(host, `host${capturePath}/${imageSource}`);
    } catch {
      // Fall through to generic image builder
    }
  }

  return buildHostImageUrl(host, imageSource);
};

/**
 * Build URL for images stored in cloud storage (R2, S3, etc.)
 */
export const buildCloudImageUrl = (
  bucketName: string,
  imagePath: string,
  baseUrl: string,
): string => {
  // Clean the image path
  const cleanPath = imagePath.startsWith('/') ? imagePath.slice(1) : imagePath;

  return `${baseUrl.replace(/\/$/, '')}/${bucketName}/${cleanPath}`;
};

// =====================================================
// MULTI-DEVICE HELPER FUNCTIONS (Frontend)
// =====================================================

/**
 * Get device-specific stream URL path from host configuration.
 * Mirrors the Python _get_device_stream_path function.
 */
const getDeviceStreamUrlPath = (host: any, deviceId: string): string => {
  if (!host) {
    throw new Error('Host information is required for device stream path resolution');
  }

  if (!deviceId) {
    throw new Error('deviceId is required - no fallbacks allowed');
  }

  // Get devices configuration from host
  const devices = host?.devices || [];
  if (!devices.length) {
    throw new Error(`No devices configured in host configuration for device_id: ${deviceId}`);
  }

  // Find the specific device
  for (const device of devices) {
    if (device?.device_id === deviceId) {
      const streamPath = device?.video_stream_path;
      if (!streamPath) {
        throw new Error(`Device ${deviceId} has no video_stream_path configured`);
      }

      // Special case: VNC devices have VNC URL in video_stream_path (for live iframe)
      // For HLS recordings, use video_capture_path instead (converted to stream path)
      if (device?.device_model === 'host_vnc') {
        const capturePath = getDeviceCaptureUrlPath(host, deviceId);
        const streamPathFromCapture = capturePath.replace('/captures', '');
        return streamPathFromCapture;
      }

      // Remove '/host' prefix if present and ensure starts with /
      const cleanPath = streamPath.replace('/host', '').replace(/^\/+/, '/');
      return cleanPath;
    }
  }

  const availableDevices = devices.map((d: any) => d?.device_id).filter(Boolean);
  throw new Error(
    `Device ${deviceId} not found in host configuration. Available devices: ${availableDevices.join(', ')}`,
  );
};

/**
 * Get device-specific capture URL path from host configuration.
 * Uses video_capture_path from device configuration.
 */
const getDeviceCaptureUrlPath = (host: any, deviceId: string): string => {
  if (!host) {
    throw new Error('Host information is required for device capture path resolution');
  }

  if (!deviceId) {
    throw new Error('deviceId is required - no fallbacks allowed');
  }

  // Get devices configuration from host
  const devices = host?.devices || [];
  if (!devices.length) {
    throw new Error(`No devices configured in host configuration for device_id: ${deviceId}`);
  }

  // Find the specific device
  for (const device of devices) {
    if (device?.device_id === deviceId) {
      const capturePath = device?.video_capture_path;
      if (!capturePath) {
        throw new Error(`Device ${deviceId} has no video_capture_path configured`);
      }

      // Convert local path to URL path (Windows + Linux)
      let urlPath = normalizeLocalPathToStreamUrl(capturePath).replace(/^\/+/, '/');
      
      // Add /captures suffix if not already present
      if (!urlPath.endsWith('/captures')) {
        urlPath = `${urlPath}/captures`;
      }
      
      return urlPath;
    }
  }

  const availableDevices = devices.map((d: any) => d?.device_id).filter(Boolean);
  throw new Error(
    `Device ${deviceId} not found in host configuration. Available devices: ${availableDevices.join(', ')}`,
  );
};

// =====================================================
// METADATA CHUNK UTILITIES (Archive Mode)
// =====================================================

/**
 * Build URL for metadata chunk JSON file (direct file access).
 * Chunks contain metadata for 10 minutes of recording (up to 3000 frames at 5fps).
 * 
 * IMPORTANT: Chunk location calculation is done in useArchivePlayer.ts (hour * 3600 + chunk_index * 600)
 * This ensures consistency with video playback timeline. DO NOT duplicate the calculation here!
 * 
 * @param host - Host object
 * @param deviceId - Device ID
 * @param hour - Hour (0-23) - from useArchivePlayer's globalCurrentTime
 * @param chunkIndex - Chunk index within hour (0-5) - from useArchivePlayer's globalCurrentTime
 * @returns URL to metadata chunk file
 * 
 * Example:
 *   buildMetadataChunkUrl(host, 'device1', 15, 0)
 *   -> "http://host/stream/capture1/metadata/15/chunk_10min_0.json"
 */
export const buildMetadataChunkUrl = (
  host: any,
  deviceId: string,
  hour: number,
  chunkIndex: number
): string => {
  if (!deviceId) {
    throw new Error('deviceId is required for buildMetadataChunkUrl');
  }
  
  // Get device capture path and convert to metadata path
  const capturePath = getDeviceCaptureUrlPath(host, deviceId);
  // Remove /captures suffix and add /metadata/{hour}/chunk_10min_{chunkIndex}.json
  const basePath = capturePath.replace('/captures', '');
  const chunkPath = `${basePath}/metadata/${hour}/chunk_10min_${chunkIndex}.json`;
  
  return internalBuildHostUrl(host, `host${chunkPath}`);
};

// =====================================================
// AUDIO/TRANSCRIPT UTILITIES
// =====================================================

/**
 * Build URL for original MP3 audio file (10-minute chunk)
 * @param host - Host object
 * @param deviceId - Device ID
 * @param hour - Hour (0-23)
 * @param chunkIndex - Chunk index within hour (0-5)
 * @returns URL to original MP3 file
 */
export const buildAudioMp3Url = (
  host: any,
  deviceId: string,
  hour: number,
  chunkIndex: number
): string => {
  if (!deviceId) {
    throw new Error('deviceId is required for buildAudioMp3Url');
  }
  
  // Get device stream path for audio
  const streamPath = getDeviceStreamUrlPath(host, deviceId);
  const audioPath = `${streamPath}/audio/${hour}/chunk_10min_${chunkIndex}.mp3`;
  
  return internalBuildHostUrl(host, `host${audioPath}`);
};

/**
 * Build URL for dubbed audio file (10-minute chunk with language)
 * @param host - Host object
 * @param deviceId - Device ID
 * @param hour - Hour (0-23)
 * @param chunkIndex - Chunk index within hour (0-5)
 * @param language - Target language code (e.g., 'es', 'fr')
 * @returns URL to dubbed MP3 file
 */
export const buildDubbedAudioUrl = (
  host: any,
  deviceId: string,
  hour: number,
  chunkIndex: number,
  language: string
): string => {
  if (!deviceId) {
    throw new Error('deviceId is required for buildDubbedAudioUrl');
  }
  
  // Get device stream path for audio
  const streamPath = getDeviceStreamUrlPath(host, deviceId);
  const audioPath = `${streamPath}/audio/${hour}/chunk_10min_${chunkIndex}_${language}.mp3`;
  
  return internalBuildHostUrl(host, `host${audioPath}`);
};

/**
 * Build URL for temporary 1-minute dubbed audio file
 * @param host - Host object
 * @param deviceId - Device ID
 * @param minute - Minute within chunk (0-9)
 * @param language - Target language code (e.g., 'es', 'fr')
 * @returns URL to temporary 1-minute MP3 file
 */
export const buildDubbedAudio1MinUrl = (
  host: any,
  deviceId: string,
  minute: number,
  language: string
): string => {
  if (!deviceId) {
    throw new Error('deviceId is required for buildDubbedAudio1MinUrl');
  }
  
  // Get device stream path for audio
  const streamPath = getDeviceStreamUrlPath(host, deviceId);
  const audioPath = `${streamPath}/audio/temp/1min_${minute}_${language}.mp3`;
  
  return internalBuildHostUrl(host, `host${audioPath}`);
};

/**
 * Build URL for transcript chunk JSON file
 * @param host - Host object
 * @param deviceId - Device ID
 * @param hour - Hour (0-23)
 * @param chunkIndex - Chunk index within hour (0-5)
 * @param language - Language code (optional, 'original' if not specified)
 * @returns URL to transcript JSON file
 */
export const buildTranscriptChunkUrl = (
  host: any,
  deviceId: string,
  hour: number,
  chunkIndex: number,
  language: string = 'original'
): string => {
  if (!deviceId) {
    throw new Error('deviceId is required for buildTranscriptChunkUrl');
  }
  
  // Get device stream path for transcript
  const streamPath = getDeviceStreamUrlPath(host, deviceId);
  const langSuffix = language === 'original' ? '' : `_${language}`;
  const transcriptPath = `${streamPath}/transcript/${hour}/chunk_10min_${chunkIndex}${langSuffix}.json`;
  
  return internalBuildHostUrl(host, `host${transcriptPath}`);
};

/**
 * Build URL for transcript manifest JSON file
 * @param host - Host object
 * @param deviceId - Device ID
 * @returns URL to transcript manifest
 */
export const buildTranscriptManifestUrl = (
  host: any,
  deviceId: string
): string => {
  if (!deviceId) {
    throw new Error('deviceId is required for buildTranscriptManifestUrl');
  }
  
  // Get device stream path for transcript manifest
  const streamPath = getDeviceStreamUrlPath(host, deviceId);
  const manifestPath = `${streamPath}/transcript/transcript_manifest.json`;
  
  return internalBuildHostUrl(host, `host${manifestPath}`);
};

/**
 * Build URL for script running log file (hot storage)
 * @param host - Host object
 * @param deviceId - Device ID
 * @returns URL to running.log file
 */
export const buildRunningLogUrl = (
  host: any,
  deviceId: string
): string => {
  if (!deviceId) {
    throw new Error('deviceId is required for buildRunningLogUrl');
  }
  
  // Get device stream path for running log
  const streamPath = getDeviceStreamUrlPath(host, deviceId);
  const runningLogPath = `${streamPath}/hot/running.log`;
  
  return internalBuildHostUrl(host, `host${runningLogPath}`);
};

// =====================================================
// STREAM UTILITIES (Quality Changes & Captures)
// =====================================================

/**
 * Read the current HLS media sequence for a device's live stream.
 * Returns -1 if the manifest is missing/unparseable. Used to capture a
 * baseline before a quality switch so the restarted stream can be detected
 * regardless of FFmpeg's segment-numbering mode (see pollForFreshStream).
 */
export const getStreamMediaSequence = async (host: any, deviceId: string): Promise<number> => {
  try {
    const manifestUrl = buildStreamUrl(host, deviceId);
    const response = await fetch(`${manifestUrl}?_t=${Date.now()}`, {
      method: 'GET',
      cache: 'no-store',
      headers: { 'Cache-Control': 'no-cache, no-store, must-revalidate', Pragma: 'no-cache' },
    });
    if (!response.ok) return -1;
    const text = await response.text();
    const match = text.match(/#EXT-X-MEDIA-SEQUENCE:(\d+)/);
    return match ? parseInt(match[1], 10) : -1;
  } catch {
    return -1;
  }
};

/**
 * Poll for fresh stream after quality change.
 * Returns cleanup function to cancel polling.
 *
 * A soft quality switch recycles the device's FFmpeg without resetting the HLS
 * media sequence: run_ffmpeg.sh deliberately resumes segment numbering from
 * max(existing)+1 so the sequence jumps FORWARD on restart (keeps HLS.js and
 * capture_monitor from mis-reading a rewind — see run_ffmpeg.sh next_start_number).
 * So "fresh" cannot be detected by an absolute-low sequence; instead we detect the
 * restart itself: the manifest briefly goes away (segments pruned/regenerating),
 * and/or the media sequence diverges from the pre-switch baseline.
 *
 * @param baselineSequence media sequence captured BEFORE the switch (-1 if unknown)
 */
export const pollForFreshStream = (
  host: any,
  deviceId: string,
  onReady: () => void,
  onTimeout: (error: string) => void,
  baselineSequence: number = -1
): (() => void) => {
  // Use proper buildStreamUrl to handle all host-specific paths (e.g., /pi2/, /pi3/, etc.)
  const manifestUrl = buildStreamUrl(host, deviceId);
  console.log(
    `[@utils:buildUrlUtils] Starting manifest polling for fresh stream: ${manifestUrl} (baseline sequence: ${baselineSequence})`
  );

  let pollCount = 0;
  let sawRestartGap = false; // manifest became unavailable -> FFmpeg recycle in progress
  const maxPolls = 15; // 15 seconds max (1000ms * 15)
  const requiredSegments = 3; // Need at least 3 segments in manifest
  // Forward jump that unambiguously marks a restart (resumes at old_max+1, ~window
  // size) vs the old stream merely advancing a few segments while it drains.
  const freshSequenceJump = 20;

  const pollingInterval = setInterval(async () => {
    pollCount++;

    // Check timeout FIRST before polling
    if (pollCount > maxPolls) {
      console.warn(
        `[@utils:buildUrlUtils] Polling timeout after ${maxPolls} attempts for ${host.host_name}-${deviceId}`
      );
      clearInterval(pollingInterval);
      onTimeout('Stream restart took longer than expected');
      return;
    }

    console.log(
      `[@utils:buildUrlUtils] Polling attempt ${pollCount}/${maxPolls} for ${host.host_name}-${deviceId}`
    );

    try {
      // Add timestamp to prevent caching
      const cacheBustUrl = `${manifestUrl}?_t=${Date.now()}`;
      const response = await fetch(cacheBustUrl, {
        method: 'GET',
        cache: 'no-store', // Stronger than no-cache
        headers: {
          'Cache-Control': 'no-cache, no-store, must-revalidate',
          Pragma: 'no-cache',
        },
      });

      if (!response.ok) {
        sawRestartGap = true; // manifest gone -> recycle underway
        console.log(
          `[@utils:buildUrlUtils] Manifest not ready yet (status: ${response.status}) for ${host.host_name}-${deviceId}`
        );
        return;
      }

      const manifestText = await response.text();
      console.log(
        `[@utils:buildUrlUtils] Manifest received for ${host.host_name}-${deviceId}, length: ${manifestText.length} bytes`
      );

      // Check if manifest has proper header
      if (!manifestText.includes('#EXTM3U')) {
        sawRestartGap = true; // manifest being rewritten -> recycle underway
        console.log(
          `[@utils:buildUrlUtils] Invalid manifest for ${host.host_name}-${deviceId} - no #EXTM3U header. First 100 chars:`,
          manifestText.substring(0, 100)
        );
        return;
      }

      // Count segments in manifest by counting #EXTINF lines
      const segmentCount = (manifestText.match(/#EXTINF/g) || []).length;

      // Extract media sequence to detect the restart relative to the pre-switch baseline
      const mediaSequenceMatch = manifestText.match(/#EXT-X-MEDIA-SEQUENCE:(\d+)/);
      const mediaSequence = mediaSequenceMatch ? parseInt(mediaSequenceMatch[1], 10) : -1;

      console.log(
        `[@utils:buildUrlUtils] Manifest valid for ${host.host_name}-${deviceId}! Has ${segmentCount} segments (need ${requiredSegments}), media sequence: ${mediaSequence}`
      );

      // The restarted stream is identified by EITHER the manifest having gone away
      // mid-poll (segments pruned/regenerating), OR the media sequence diverging from
      // the baseline: a reset to 0 (sequence dropped) or a forward jump (numbering
      // resumed at old_max+1). Without a baseline, fall back to the gap signal alone.
      const sequenceRestarted =
        baselineSequence >= 0 &&
        (mediaSequence < baselineSequence || mediaSequence >= baselineSequence + freshSequenceJump);
      const restarted = sawRestartGap || sequenceRestarted;

      if (segmentCount >= requiredSegments && restarted) {
        console.log(
          `[@utils:buildUrlUtils] ✅ Fresh stream ready for ${host.host_name}-${deviceId}! ${segmentCount} segments, sequence ${mediaSequence} (gap=${sawRestartGap}, seqRestart=${sequenceRestarted})`
        );
        clearInterval(pollingInterval);
        onReady();
      } else if (segmentCount >= requiredSegments) {
        console.log(
          `[@utils:buildUrlUtils] ⏳ Manifest for ${host.host_name}-${deviceId} has ${segmentCount} segments but no restart detected yet (sequence ${mediaSequence}, baseline ${baselineSequence}) - waiting`
        );
      }
    } catch (error) {
      console.log(
        `[@utils:buildUrlUtils] Manifest check failed for ${host.host_name}-${deviceId}: ${error}`
      );
    }
  }, 1000); // 1 second interval

  // Return cleanup function
  return () => {
    console.log(`[@utils:buildUrlUtils] Cleaning up polling for ${host.host_name}-${deviceId}`);
    clearInterval(pollingInterval);
  };
};

/**
 * Get capture URL from stream segment (calls backend to copy hot->cold)
 * Backend handles: segment→capture calculation, hot→cold copy, URL building
 */
export const getCaptureUrlFromStream = async (
  streamUrl: string,
  device?: any,
  host?: any
): Promise<string | null> => {
  if (!streamUrl || !device || !host) {
    console.warn('[@utils:buildUrlUtils] Missing required parameters:', {
      streamUrl: !!streamUrl,
      device: !!device,
      host: !!host,
    });
    return null;
  }

  try {
    // Extract segment number from stream URL (e.g., segment_000078741.ts)
    const segmentMatch = streamUrl.match(/segment_(\d+)\.ts/);
    if (!segmentMatch) {
      console.warn('[@utils:buildUrlUtils] Could not extract segment number from URL:', streamUrl);
      return null;
    }

    const segmentNumber = parseInt(segmentMatch[1], 10);
    const fps = device.video_fps || 5;

    console.log(`[@utils:buildUrlUtils] Requesting capture: segment=${segmentNumber}, fps=${fps}`);

    // Call backend to get capture (handles hot→cold copy)
    const response = await fetch(buildServerUrl('/server/av/getSegmentCapture'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        host_name: host.host_name,
        device_id: device.device_id,
        segment_number: segmentNumber,
        fps: fps,
      }),
    });

    if (!response.ok) {
      console.error('[@utils:buildUrlUtils] Backend request failed:', response.status);
      return null;
    }

    const result = await response.json();
    if (result.success && result.capture_url) {
      console.log(`[@utils:buildUrlUtils] Got capture URL (COLD): ${result.capture_url}`);
      return result.capture_url;
    }

    console.error('[@utils:buildUrlUtils] Backend returned error:', result.error);
    return null;
  } catch (error) {
    console.error('[@utils:buildUrlUtils] Failed to get capture URL:', error);
    return null;
  }
};
