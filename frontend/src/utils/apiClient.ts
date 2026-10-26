/**
 * API Client with Automatic JWT Authentication
 *
 * Phase 1: Standardized request layer for all backend server API calls.
 * Use apiClient or api.* instead of raw fetch() for buildServerUrl() endpoints.
 *
 * Wraps fetch() to automatically include Supabase JWT token in Authorization header.
 * Use this for all API calls to backend_server that require user authentication.
 *
 * The token is the one for the TARGET server's Supabase identity (TASK-18,
 * `lib/serverIdentity`) — servers in the picker may authenticate against different
 * Supabase instances.
 *
 * Usage:
 *   import { apiClient, api } from '@/utils/apiClient';
 *   import { buildServerUrl } from '@/utils/buildUrlUtils';
 *
 *   // Raw Response (when you need response.ok, status, etc.)
 *   const response = await apiClient(buildServerUrl('/server/devices'), {
 *     method: 'POST',
 *     body: JSON.stringify({ ... })
 *   });
 *
 *   // JSON parsed (api.get, api.post, etc.)
 *   const data = await api.get(buildServerUrl('/server/devices'));
 */

import { isAuthEnabled } from '../lib/supabase';
import { getAutoSignHeaderToken } from '../lib/autoSign';
import { getAccessTokenForRequest } from '../lib/serverIdentity';
import { HTTP_CONFIG } from '../config/constants';

export interface ApiClientOptions extends Omit<RequestInit, 'headers'> {
  headers?: Record<string, string>;
  skipAuth?: boolean; // Skip adding Authorization header
  /**
   * Deadline for this request, in ms. Defaults to HTTP_CONFIG.LONG_TIMEOUT (60 s).
   *
   * Why this exists: `fetch()` with no AbortSignal waits forever. A server that
   * accepts the connection and then stalls — a wedged worker, a proxy that never
   * answers, a device host that drops mid-request — left every caller's
   * `isLoading` true indefinitely, which is how "Loading stream…" / "Loading…"
   * screens outlived the outage that caused them. Every request now has a deadline,
   * so the failure is a catchable error the caller can render.
   *
   * Why 60 s and not HTTP_CONFIG.DEFAULT_TIMEOUT (30 s): this client fronts
   * LLM-backed endpoints too (`/server/agent/voice/command`,
   * `/server/action/execute`) whose backend work legitimately outlasts 30 s. The
   * deadline here is a hang-catcher, not a latency budget — it must never be the
   * reason a working call is cut off. Callers that know their endpoint is fast
   * should pass a tighter `timeoutMs` (useStream does, at 15 s) and callers whose
   * work is genuinely unbounded should pass `timeoutMs: 0` to opt out.
   *
   * A caller-supplied `signal` always wins and is left untouched.
   */
  timeoutMs?: number;
}

let hasLoggedMissingSession = false;
let hasLoggedAuthDisabled = false;
let hasLoggedAuthEnabled = false;
let hasLoggedJwtAttached = false;

/**
 * Enhanced fetch with automatic JWT authentication
 */
export async function apiClient(
  url: string,
  options: ApiClientOptions = {}
): Promise<Response> {
  const { skipAuth = false, headers = {}, timeoutMs, ...fetchOptions } = options;

  // Prepare headers (omit Content-Type for FormData - browser sets boundary)
  const requestHeaders: Record<string, string> = { ...headers };
  if (!(fetchOptions.body instanceof FormData) && !requestHeaders['Content-Type']) {
    requestHeaders['Content-Type'] = 'application/json';
  }

  // Deadline. A caller-supplied signal is authoritative (ServerManagerProvider
  // passes a shorter per-server budget for the "All servers" round), so only add
  // ours when there is none. timeoutMs: 0 disables the deadline entirely.
  const effectiveTimeout = timeoutMs ?? HTTP_CONFIG.LONG_TIMEOUT;
  let deadlineSignal: AbortSignal | undefined;
  if (!fetchOptions.signal && effectiveTimeout > 0) {
    deadlineSignal = AbortSignal.timeout(effectiveTimeout);
  }

  // Add Authorization header with JWT token when auth is enabled.
  if (!skipAuth && !isAuthEnabled) {
    if (!hasLoggedAuthDisabled) {
      console.warn(
        '[@apiClient][SECURITY][OPEN_MODE] Frontend authentication is disabled. ' +
          'API calls to backend_server are unauthenticated until Supabase auth is configured.'
      );
      hasLoggedAuthDisabled = true;
    }
  }

  if (!skipAuth && isAuthEnabled && !hasLoggedAuthEnabled) {
    console.info(
      '[@apiClient][SECURITY] Supabase auth is enabled. JWT will be attached when user session is available.'
    );
    hasLoggedAuthEnabled = true;
  }

  if (!skipAuth && isAuthEnabled) {
    try {
      // TASK-18: pick the session by the request's target server. apiClient sets the
      // header itself, and installFetchAuth never overwrites an Authorization that is
      // already present — so getting this wrong here could not be corrected downstream.
      // Time-bounded: this await runs BEFORE the request, so an identity whose Supabase
      // is unreachable used to hold the call (and its AbortSignal) for supabase-js's full
      // ~30 s refresh-retry window instead of letting it fail fast.
      const accessToken = await getAccessTokenForRequest(url);

      if (accessToken) {
        requestHeaders['Authorization'] = `Bearer ${accessToken}`;
        if (!hasLoggedJwtAttached) {
          console.info('[@apiClient][SECURITY] JWT Authorization header attached for frontend -> server API calls.');
          hasLoggedJwtAttached = true;
        }
      } else {
        if (!hasLoggedMissingSession) {
          console.warn(
            '[@apiClient] Supabase auth is enabled but no active user session was found. ' +
              'Requests will be unauthenticated until login succeeds.'
          );
          hasLoggedMissingSession = true;
        }
      }
    } catch (error) {
      console.error('[@apiClient] Error getting session:', error);
      // Continue without auth header
    }
  }

  const autoSignToken = getAutoSignHeaderToken();
  if (!skipAuth && autoSignToken) {
    requestHeaders['X-Auto-Sign'] = autoSignToken;
  }

  // Make the request
  try {
    return await fetch(url, {
      ...fetchOptions,
      headers: requestHeaders,
      ...(deadlineSignal ? { signal: deadlineSignal } : {}),
    });
  } catch (error) {
    // AbortSignal.timeout rejects with a DOMException named 'TimeoutError', whose
    // `message` is a fixed browser string. Callers surface error.message, so give
    // them one that names the request and the budget they waited for.
    if (deadlineSignal?.aborted && (error as Error)?.name === 'TimeoutError') {
      throw new Error(`Request timed out after ${effectiveTimeout} ms: ${url}`);
    }
    throw error;
  }
}

/**
 * API Client with JSON parsing
 * Convenience method that parses JSON response automatically
 */
export async function apiClientJson<T = any>(
  url: string,
  options: ApiClientOptions = {}
): Promise<T> {
  const response = await apiClient(url, options);

  if (!response.ok) {
    const error = await response.json().catch(() => ({ error: response.statusText }));
    throw new Error(error.error || error.message || `HTTP ${response.status}`);
  }

  return response.json();
}

/**
 * Typed API Client Methods
 */
export const api = {
  /**
   * GET request with auth
   */
  get: async <T = any>(url: string, options?: ApiClientOptions): Promise<T> => {
    return apiClientJson<T>(url, { ...options, method: 'GET' });
  },

  /**
   * POST request with auth
   */
  post: async <T = any>(url: string, data?: any, options?: ApiClientOptions): Promise<T> => {
    return apiClientJson<T>(url, {
      ...options,
      method: 'POST',
      body: data ? JSON.stringify(data) : undefined,
    });
  },

  /**
   * PUT request with auth
   */
  put: async <T = any>(url: string, data?: any, options?: ApiClientOptions): Promise<T> => {
    return apiClientJson<T>(url, {
      ...options,
      method: 'PUT',
      body: data ? JSON.stringify(data) : undefined,
    });
  },

  /**
   * DELETE request with auth
   */
  delete: async <T = any>(url: string, options?: ApiClientOptions): Promise<T> => {
    return apiClientJson<T>(url, { ...options, method: 'DELETE' });
  },
};

/**
 * Example Usage:
 * 
 * // Simple GET
 * const devices = await api.get(buildServerUrl('/server/devices/getAllDevices'));
 * 
 * // POST with data
 * const result = await api.post(buildServerUrl('/server/devices/control'), {
 *   device_id: 'device1',
 *   action: 'restart'
 * });
 * 
 * // Skip auth for public endpoints
 * const publicData = await api.get(buildServerUrl('/server/health'), { skipAuth: true });
 * 
 * // Custom headers
 * const data = await api.get(url, {
 *   headers: { 'X-Custom-Header': 'value' }
 * });
 */
