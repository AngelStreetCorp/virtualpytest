/**
 * TASK-113 — PR-D: the action-dispatch helper.
 *
 * The single place that turns a `ResourceRef` (a row's `{ serverId,
 * resourceType, localId }`) into a network call to the home server.
 * Replaces the existing pattern where every action call used
 * `buildServerUrl(...)` (the currently selected server) with one
 * that uses `buildServerUrlForServer(ref.serverId, ...)` (the row's
 * home server).
 *
 * Architectural invariant (binding): the action goes to the row's
 * home server ONLY. The currently selected server (the one serving
 * the UI) sees no traffic from the action. No inter-server call.
 *
 * The helper resolves the trusted `ServerConnection` from the
 * `eligibleServers` argument (the same list `queryScope` filters).
 * It refuses to dispatch if `ref.serverId` is not in the eligible
 * set — a row that says "I belong to server X" is honored only if
 * the registry says server X is in the eligible set. This is the
 * spec rule "targets come from the trusted registry, never from a
 * row field".
 *
 * The per-server JWT is picked through the existing
 * `getAccessTokenForRequest` (TASK-18) on the URL the action hits.
 * No token forwarding; no shared credential.
 */
import { buildServerUrlForServer } from '../../utils/buildUrlUtils';
import { getAccessTokenForRequest } from '../../lib/serverIdentity';
import type {
  ResourceRef,
  ServerConnection,
} from '../../types/allServer/AllServer_Types';

export interface DispatchOptions {
  /** Per-server timeout in ms. Default 10_000. */
  timeoutMs?: number;
  /** Optional AbortSignal from the caller. */
  signal?: AbortSignal;
}

const DEFAULT_TIMEOUT_MS = 10_000;

/**
 * Build a fetch-like call bound to the home server of a `ResourceRef`.
 * Throws if the row's server is not in the eligible set — the caller
 * must never see a network request for an ineligible peer.
 */
export const dispatchForRow = async <T>(
  ref: ResourceRef,
  eligibleServers: ServerConnection[],
  call: (server: ServerConnection, signal: AbortSignal) => Promise<T>,
  options: DispatchOptions = {},
): Promise<T> => {
  const { timeoutMs = DEFAULT_TIMEOUT_MS, signal: parentSignal } = options;
  const server = eligibleServers.find((s) => s.serverId === ref.serverId);
  if (!server) {
    throw Object.assign(
      new Error(
        `dispatchForRow: server ${ref.serverId} is not in the eligible set`,
      ),
      { code: 'ineligible-server', serverId: ref.serverId },
    );
  }
  const timeoutController = new AbortController();
  const timeoutHandle = setTimeout(() => timeoutController.abort(), timeoutMs);
  const perCallSignal = parentSignal
    ? anySignal([parentSignal, timeoutController.signal])
    : timeoutController.signal;
  try {
    return await call(server, perCallSignal);
  } finally {
    clearTimeout(timeoutHandle);
  }
};

/** Small AbortSignal combinator for environments without AbortSignal.any. */
const anySignal = (signals: ReadonlyArray<AbortSignal>): AbortSignal => {
  const controller = new AbortController();
  for (const s of signals) {
    if (s.aborted) {
      controller.abort(s.reason);
      break;
    }
    s.addEventListener(
      'abort',
      () => controller.abort(s.reason),
      { once: true, signal: controller.signal },
    );
  }
  return controller.signal;
};

/**
 * Build a per-server URL for a `ResourceRef`. This is the URL the
 * action fetch goes to. The JWT for the URL's target server is
 * resolved by `installFetchAuth`'s interceptor (TASK-18) — the
 * per-server authentication is automatic.
 */
export const urlForRef = (ref: ResourceRef, endpoint: string): string =>
  buildServerUrlForServer(ref.serverId, endpoint);

/** Eagerly resolve the access token for a row's home server. */
export const accessTokenForRef = async (ref: ResourceRef): Promise<string | null> =>
  getAccessTokenForRequest(urlForRef(ref, '/server/auth/check'));
