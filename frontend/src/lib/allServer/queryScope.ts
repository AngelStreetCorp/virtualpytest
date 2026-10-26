/**
 * TASK-113 — PR-B: Frontend-only federation query layer.
 *
 * The single place that fans a request out across the eligible set of
 * configured servers. Architectural invariant: no `?peer=true`, no
 * `discover_peers`, no `peers:` discovery, no `post_to_peer`, no
 * `cross_server_token`, no shared database. The browser is the only
 * client of every configured server.
 *
 * Properties guaranteed by the implementation (per the rewrite §5.2):
 *  - `Promise.allSettled`-equivalent: one peer failure never empties
 *    the page.
 *  - Bounded per-peer parallelism (default 4 in flight).
 *  - Per-peer timeout (default 10s, matching the existing
 *    `ServerManagerProvider.tsx:384` baseline).
 *  - Per-server error classification matching `ServerResult['status']`.
 *  - Targets come from the trusted `eligibleServers` argument, NEVER
 *    from a row field.
 */
import type {
  ServerConnection,
  ServerResult,
  ServerScope,
} from '../../types/allServer/AllServer_Types';

/** The signal is forwarded to every per-peer load so a parent abort cancels all in flight. */
export interface QueryScopeOptions {
  /** Max concurrent per-peer loads. Default 4. */
  concurrency?: number;
  /** Per-peer timeout in ms. Default 10_000. */
  timeoutMs?: number;
}

const DEFAULTS = {
  concurrency: 4,
  timeoutMs: 10_000,
} as const;

/**
 * Filter the eligible set to the active scope.
 *
 * `'single'` returns at most one connection. If the named server is not
 * in the eligible set (no session, excluded, etc.), the result is `[]`
 * — the caller surfaces an empty page rather than a wrong-server fetch.
 */
export const targetsForScope = (
  scope: ServerScope,
  eligibleServers: ServerConnection[],
): ServerConnection[] => {
  if (scope.kind === 'all') return eligibleServers;
  return eligibleServers.filter((s) => s.serverId === scope.serverId);
};

/**
 * Combine an arbitrary list of AbortSignals into one. `AbortSignal.any`
 * is the standardized form but is not available in the jsdom test env
 * (Node 19+, jsdom < 25) — this small implementation is correct in
 * every env that supports AbortController.
 */
const combineSignals = (signals: ReadonlyArray<AbortSignal>): AbortSignal => {
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
 * Bounded-concurrency runner. Each task is given a per-peer
 * AbortSignal that combines the parent signal with a manual
 * timeout. Tasks that exceed the timeout fail with status `offline`.
 */
const runBounded = async <T>(
  items: Array<(signal: AbortSignal) => Promise<T>>,
  parentSignal: AbortSignal,
  concurrency: number,
  timeoutMs: number,
): Promise<Array<{ ok: true; value: T } | { ok: false; error: unknown }>> => {
  const results: Array<{ ok: true; value: T } | { ok: false; error: unknown }> = new Array(
    items.length,
  );
  let cursor = 0;

  const worker = async (): Promise<void> => {
    while (true) {
      const i = cursor++;
      if (i >= items.length) return;
      // Per-peer signal: parent abort OR timeout. We use a manual
      // AbortController + setTimeout instead of `AbortSignal.timeout(ms)`
      // because the latter's underlying timer is not observable across
      // every test env (and the returned signal's abort() is not
      // always callable). A 50ms vs 5_000ms timing is well outside
      // any timer firing skew in either Node or jsdom.
      const timeoutController = new AbortController();
      const timeoutHandle = setTimeout(() => timeoutController.abort(), timeoutMs);
      const perPeerSignal = combineSignals([parentSignal, timeoutController.signal]);
      try {
        const value = await items[i](perPeerSignal);
        results[i] = { ok: true, value };
      } catch (error) {
        results[i] = { ok: false, error };
      } finally {
        clearTimeout(timeoutHandle);
      }
    }
  };

  const laneCount = Math.min(concurrency, items.length);
  await Promise.all(Array.from({ length: laneCount }, () => worker()));
  return results;
};

/** Failure variant statuses only — the success branch is 'ok'. */
type FailureStatus = 'unauthorized' | 'offline' | 'error' | 'incompatible';

/**
 * Classify a thrown error into a failure status. The classification
 * is the only piece of `queryScope` that knows about fetch / HTTP semantics.
 * Keeping it isolated means the rest of the helper is transport-agnostic.
 */
const classifyError = (error: unknown): FailureStatus => {
  // An abort surfaces as a DOMException named "AbortError" in the browser
  // and as a plain Error with `name: 'AbortError'` from libraries that
  // re-throw. Match on name to cover both.
  if (typeof error === 'object' && error !== null) {
    const name = (error as { name?: unknown }).name;
    if (name === 'AbortError') {
      // Both a parent abort and a per-peer timeout surface as AbortError;
      // mark anything aborted as `offline` — the caller's `signal.reason`
      // is the disambiguator.
      return 'offline';
    }
  }
  if (error instanceof TypeError) {
    // Fetch network errors: DNS, connection refused, CORS preflight rejection
    // (browser reports these as a TypeError on the original request).
    return 'offline';
  }
  if (typeof error === 'object' && error !== null) {
    const status = (error as { status?: unknown }).status;
    if (status === 401 || status === 403) return 'unauthorized';
    if (typeof status === 'number' && status >= 400 && status < 500) {
      return 'error';
    }
    if (typeof status === 'number' && status >= 500) return 'error';
    // Schema drift signals: a 200 with an unexpected body shape; left to
    // the caller's `load` to detect and reject with `{ status: 'incompatible' }`.
  }
  return 'error';
};

/**
 * Fan-out across the eligible servers in scope. Returns one
 * `ServerResult<T>` per target. The order of the output matches the
 * order of the eligible set passed in.
 */
export const queryScope = async <T>(
  scope: ServerScope,
  eligibleServers: ServerConnection[],
  load: (server: ServerConnection, signal: AbortSignal) => Promise<T>,
  signal: AbortSignal,
  options: QueryScopeOptions = {},
): Promise<ServerResult<T>[]> => {
  const { concurrency, timeoutMs } = { ...DEFAULTS, ...options };
  const targets = targetsForScope(scope, eligibleServers);
  if (targets.length === 0) return [];

  const now = Date.now();
  const tasks = targets.map(
    (server) => (perPeerSignal: AbortSignal): Promise<ServerResult<T>> =>
      load(server, perPeerSignal).then(
        (value): ServerResult<T> => ({
          serverId: server.serverId,
          status: 'ok',
          value,
          fetchedAt: now,
        }),
      ),
  );

  const results = await runBounded(tasks, signal, concurrency, timeoutMs);

  return results.map<ServerResult<T>>((r, i) => {
    const server = targets[i];
    if (r.ok) return r.value;
    const status = classifyError(r.error);
    return {
      serverId: server.serverId,
      status,
      error: r.error instanceof Error ? r.error.message : String(r.error),
    };
  });
};
