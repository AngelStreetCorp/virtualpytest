/**
 * TASK-113 — PR-F: lightweight observability for the federation layer.
 *
 * The dispatch / query / cross-server-control paths emit a single
 * structured log line per operation, with these fields:
 *
 *   { op, scope, serverId, status, durationMs, error? }
 *
 * Where:
 *   - `op`        is one of: 'query', 'action', 'stream-prime', 'control-connect'.
 *   - `scope`     is 'single' or 'all'.
 *   - `serverId`  is the home server (for 'single' or per-peer in 'all').
 *   - `status`    is 'ok' | 'unauthorized' | 'offline' | 'error' | 'incompatible'.
 *   - `durationMs` is wall time from the call entry to its outcome.
 *   - `error`     is the message when status is not 'ok'.
 *
 * The log is just a `console.debug` (or `console.warn` on error).
 * Production deployments can wire a custom sink by replacing
 * `setAllServerLogSink`. This is intentionally low-cost — no
 * telemetry network calls, no PII capture, no aggregation — so it
 * stays safe to leave on in dev.
 */
import type {
  ServerConnection,
  ServerResult,
  ServerScope,
} from '../../types/allServer/AllServer_Types';

export type AllServerLogOp =
  | 'query'
  | 'action'
  | 'stream-prime'
  | 'control-connect'
  | 'control-disconnect'
  | 'socket-error';

export interface AllServerLogEvent {
  op: AllServerLogOp;
  scope: ServerScope['kind'];
  serverId: string;
  status: 'ok' | 'unauthorized' | 'offline' | 'error' | 'incompatible';
  durationMs: number;
  error?: string;
  /** Optional path / endpoint the log refers to. */
  path?: string;
}

type Sink = (event: AllServerLogEvent) => void;

const DEFAULT_SINK: Sink = (event) => {
  const tag = `[allServer] ${event.op} ${event.scope} ${event.serverId} → ${event.status} (${event.durationMs}ms${event.path ? `, ${event.path}` : ''})`;
  if (event.status === 'ok') {
    console.debug(tag);
  } else {
    console.warn(`${tag}${event.error ? ` — ${event.error}` : ''}`);
  }
};

let currentSink: Sink = DEFAULT_SINK;

/** Replace the log sink (test harness, custom aggregator, etc.). */
export const setAllServerLogSink = (sink: Sink | null): void => {
  currentSink = sink ?? DEFAULT_SINK;
};

/** Time a function and emit a single log event on completion. */
export const traceAllServer = async <T>(
  op: AllServerLogOp,
  scope: ServerScope['kind'],
  server: ServerConnection,
  path: string | undefined,
  fn: () => Promise<T>,
): Promise<T> => {
  const start = Date.now();
  try {
    const result = await fn();
    currentSink({
      op,
      scope,
      serverId: server.serverId,
      status: 'ok',
      durationMs: Date.now() - start,
      path,
    });
    return result;
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    const status: AllServerLogEvent['status'] =
      err && typeof err === 'object' && 'status' in err
        ? (err as { status?: number }).status === 401 || (err as { status?: number }).status === 403
          ? 'unauthorized'
          : 'error'
        : 'error';
    currentSink({
      op,
      scope,
      serverId: server.serverId,
      status,
      durationMs: Date.now() - start,
      error: message,
      path,
    });
    throw err;
  }
};

/**
 * Per-call wrapper that maps a single server result into a log event.
 * Used by `queryScope` consumers that want to know which peers
 * failed without unwrapping the result themselves.
 */
export const summarizeResults = (results: ReadonlyArray<ServerResult<unknown>>): string => {
  const counts: Record<string, number> = {};
  for (const r of results) {
    counts[r.status] = (counts[r.status] ?? 0) + 1;
  }
  return Object.entries(counts)
    .map(([k, v]) => `${k}=${v}`)
    .join(' ');
};
