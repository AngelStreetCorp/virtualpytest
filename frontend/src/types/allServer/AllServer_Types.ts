/**
 * TASK-113 — All-Server Decentralized Mode
 *
 * Type contracts introduced in PR-A. These are the foundation for the
 * frontend-only federation: a discriminated `ServerScope`, a per-resource
 * `ResourceRef`, a per-server `ServerResult<T>`, and the trusted
 * `ServerConnection` (the per-server record the registry hands the rest
 * of the app). The `queryScope` helper signature is a placeholder for
 * PR-B; the implementation is gated on the A7 + C8 + PoC verification.
 *
 * Architectural invariant (binding): no `?peer=true`, no `discover_peers`,
 * no `peers:` discovery, no `post_to_peer`, no `cross_server_token`, no
 * shared database. All aggregation is on the browser side. The browser
 * is the only client of every configured server.
 *
 * The `serverId` opaque token is the normalized key the registry uses
 * (`normalizeServerKey` in `frontend/src/lib/serverIdentity.ts:54-58`).
 * Server identity is URL-keyed today: a URL change is a new server. See
 * `TASK-113-feasibility-report.md` §E1 for the open question on stable
 * IDs vs URL keys.
 */

/** The active scope the user has selected in the picker. */
export type ServerScope =
  | { kind: 'single'; serverId: string }
  | { kind: 'all' };

/** A reference to a resource on its home server. */
export interface ResourceRef {
  /** Trusted registry's normalized server key. */
  serverId: string;
  /** `'host' | 'device' | 'script' | 'project' | 'run' | 'workspace' | 'user' | 'team' | 'tenant' | ...` */
  resourceType: string;
  /** The resource's id within its home server. */
  localId: string;
}

/** Per-server outcome of a `queryScope` fan-out. */
export type ServerResult<T> =
  | { serverId: string; status: 'ok'; value: T; fetchedAt: number }
  | {
      serverId: string;
      status: 'unauthorized' | 'offline' | 'error' | 'incompatible';
      error: string;
    };

/**
 * Trusted per-server record the registry hands the rest of the app.
 *
 * Sourced from the existing `serverIdentity.ts` registry and the
 * `getAllServerUrls()` build-time list (`buildUrlUtils.ts:353-384`).
 * The `serverId` is the registry's normalized key. The `url` is the
 * browser-reachable origin. The `authState` comes from TASK-18.
 *
 * `serverConnection` is the **only** valid source of a target URL for
 * any cross-server call. Resource rows MUST NOT carry a target URL
 * that overrides this — that was the spec's invariant.
 */
export interface ServerConnection {
  /** Registry-normalized key. Used in `ResourceRef.serverId`. */
  serverId: string;
  /** Browser-reachable origin (https://x or http://localhost:N). */
  url: string;
  /** Display label, from `/server/auth/check` (TASK-18). */
  name: string;
  /** Per-server auth state from `getServerAuthState`. */
  authState: 'authenticated' | 'needs-auth' | 'no-auth-required' | 'unknown';
  /** Optional Supabase identity (set when the server is in supabase mode). */
  identity?: string;
}

/**
 * The frontend-only federation helper. **Placeholder signature** for
 * PR-A; the implementation lands in PR-B. PR-A only asserts the type
 * contract and the round-trip shape.
 *
 * Properties the implementation must guarantee (per the rewrite §5.2):
 *  - `Promise.allSettled`-equivalent so one peer failure never empties
 *    the page.
 *  - Bounded per-peer parallelism.
 *  - Per-peer timeout (the 10s `AbortSignal.timeout` already in
 *    `ServerManagerProvider.tsx:384` is the seed).
 *  - Per-server error classification matching `ServerResult['status']`.
 *  - Targets come from the trusted `eligibleServers` argument, never
 *    from a row field.
 */
export type QueryScope = <T>(
  scope: ServerScope,
  eligibleServers: ServerConnection[],
  load: (server: ServerConnection, signal: AbortSignal) => Promise<T>,
  signal: AbortSignal,
) => Promise<ServerResult<T>[]>;

/**
 * The action-dispatch helper. **Placeholder signature** for PR-A; the
 * implementation lands in PR-D.
 *
 * Properties the implementation must guarantee (per the rewrite §5.3):
 *  - Resolves the trusted `ServerConnection` for `ref.serverId`.
 *  - Picks the per-server JWT through `getAccessTokenForRequest`.
 *  - Sends the action to the home server, never to a different server.
 *  - Native WebSocket paths must use `createServerSocket(homeServerUrl, ...)`
 *    to inherit the per-server handshake auth.
 */
export type DispatchForRow = <T>(
  ref: ResourceRef,
  call: (server: ServerConnection, signal: AbortSignal) => Promise<T>,
  signal: AbortSignal,
) => Promise<T>;
