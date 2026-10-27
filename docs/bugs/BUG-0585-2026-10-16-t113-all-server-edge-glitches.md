# BUG-0585 — "All servers" edge-glitch bundle (TASK-113 PR-C follow-up)

- **When**: TASK-113 PR-C shipped 2026-10-15 (mobile ServerSelector,
  desktop ScopePicker, sentinel rehydration). The PoC validated the
  happy path on a two-server fleet; a one-server fleet hit a bundle
  of three sibling glitches on every page load while the picker was
  sitting on "All servers".

- **Visible to**: anyone on a single-server deployment who clicked the
  new "All servers" row out of curiosity, or whose persisted
  `selectedServer === '__all__'` from a previous two-server run left
  the picker locked there. Three symptoms:

  1. **Slowness + WebSocket spam** —
     ```
     serverSocket.ts:70 WebSocket connection to
       'wss://__all__/socket.io/?EIO=4&transport=websocket' failed
     socket__io-client.js … WebSocket connection to
       'wss://__all__/socket.io/?EIO=4&transport=websocket' failed
     ```
     was logged on every reconnect cycle (engages the `reconnection`
     back-off loop). The page looked slow because every cycle burns
     timeout + DNS resolution + retry.
  2. **Devices page empty** — `HostManagerProvider`'s
     `allHostsFromServers` did `serverHostsData.find(s => s.server_info.server_url === selectedServer)`;
     no `server_url` ever matches the literal `'__all__'`, so the
     lookup missed, `allHostsFromServers = []`, and the Rec grid
     rendered the "No AV devices found" alert against an otherwise
     populated list.
  3. **Picker shows "All servers" even with one configured server** —
     row is rendered (and disabled when `availableServers.length === 0`,
     but always rendered with `length === 1`). One-server deployments
     have nothing to federate; the row only wastes a click.

- **Why it shipped broken**: PR-C was approved on
  `docs/tasks/TASK-113-feasibility-report.md` §14 with the explicit
  condition *"no production activation before required security and
  cross-origin tests pass"*. The two-server happy path passed on the
  PoC; the one-server edge did not get its own scenario, so the
  sentinel-vs-no-real-server paths were under-tested. The `find` in
  `HostManagerProvider` was written before the sentinel existed and
  was never revisited when PR-C introduced it.

- **Fix**: TASK-113 PR-C extension on main, 2026-10-16. Three small,
  surgical patches, all behind the same precondition (`isAllServersSentinel`
  is true or `availableServers.length <= 1`):

  1. **`ServerManagerProvider.tsx`** — the `/system` socket effect
     short-circuits when `selectedServer === ALL_SERVERS_SENTINEL` or
     `''`. Comment explains PR-E owns per-server sockets in ALL mode;
     the cached `serverHostsData` (refreshed every 30 s plus manual
     `refreshServerData()`) is the source of truth in the meantime.
     No `wss://__all__/...` attempt, no reconnect spam.
  2. **`HostManagerProvider.tsx`** — `allHostsFromServers` unions every
     server's `hosts` when the sentinel is picked. Devices are still
     keyed by `buildDeviceKey(host.host_name, device.device_id)`
     (host names are server-unique because each host registers on one
     home server only) and each host carries the home server URL stamp
     added by `ServerManagerProvider` so per-row action dispatch is
     origin-aware.
  3. **`ServerSelector.tsx` (mobile) + `ScopePicker.tsx` (desktop)** —
     the "All servers" `<MenuItem>` / `<Row>` (and the divider that
     sits between it and the per-server rows) is rendered only when
     `availableServers.length > 1`. `<=1` covers both the empty case
     and the one-server case; the user sees exactly the configured
     servers, no federate invitation, no chance to land on the sentinel.

- **Tests**:
  - `tests/frontend/ServerManagerProvider.test.tsx` already pinned the
    rehydration (T16) and now also captures the `createServerSocket`
    args directly. Two new cases: the `__all__` config asserts
    `createServerSocketMock` is **never** called; a configured URL
    asserts it is called with that URL on `/system`. The T16 case
    stays as a no-regression.
  - `tests/frontend/allServer/ScopePicker.test.tsx` updates the
    `availableServers === []` case from "row rendered, disabled" to
    "row not rendered" (matching the new behaviour) and adds a
    sibling `availableServers === [one]` case.
  - All 13 / 13 across the two files; the full
    `tests/frontend/allServer` suite stays at 71/71.

- **i18n**: none — pickers, not text. The "All servers" key (fr 1301,
  de 1301) was already in place from PR-C.

- **Live PoC**: `/tmp/t113-poc.js` against `virtualpytest.angelstreet.io`
  was re-run on the next deploy; on a single-server fleet the picker
  no longer lists the "All servers" row, the console is silent for
  WebSockets, and the Devices page renders the fleet.
