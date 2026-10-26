# BUG-0568 — `localStorage` rehydration drops the `__all__` ALL_SERVERS_SENTINEL

- **When**: TASK-113 PR-A / PR-C shipped 2026-10-15. The rehydration
  guard `availableServers.includes(saved)` in `ServerManagerProvider`
  (frontend `selectedServer` slot) accepted only URLs that were in the
  configured list. `__all__` is not in the list (the picker row sets
  it, but `availableServers[]` is only the configured URLs), so on
  reload the loader fell back to `availableServers[0]` and the picker
  silently flipped back to the first configured server.

- **Visible to**: anyone who picked "All servers", reloaded, and
  expected the ALL mode to persist. The PoC at `/tmp/t113-poc.js`
  caught it as T16 (reload → chip still shows single server, not
  "All servers"); the rehydration test in
  `tests/frontend/ServerManagerProvider.test.tsx` now pins it.

- **Why it shipped broken**: the rehydration check was written before
  the `ALL_SERVERS_SENTINEL` concept existed (TASK-113 PR-A). The
  `selectedServer: string` slot was assumed to be a configured URL.
  PR-C added the sentinel but did not touch the rehydration guard
  because the rehydration check is in the loader, not in the picker
  setter — and the setter that wrote `__all__` to `localStorage`
  succeeded, so the value was on disk; the loader just refused to
  read it back.

- **Fix**: TASK-113 PR-C extension on main, 2026-10-16. The
  rehydration loader now special-cases the sentinel:

  ```ts
  const saved = localStorage.getItem('selectedServer');
  if (saved === ALL_SERVERS_SENTINEL) return ALL_SERVERS_SENTINEL;
  return saved && availableServers.includes(saved)
    ? saved
    : availableServers[0] || '';
  ```

  T16 (Playwright) and the unit test in
  `ServerManagerProvider.test.tsx` (a fresh `data-testid="selected"`
  on the `Probe`) now pin the contract. `__all__` survives reload;
  real URLs are still validated against `availableServers`; an
  empty save still falls back to the first configured server.

- **Tests**: `tests/frontend/ServerManagerProvider.test.tsx` adds a
  case under the "ALL-scope rehydration (T16)" describe block that
  writes `__all__` to `localStorage` and asserts the `selected`
  testid shows the sentinel verbatim. The full
  `tests/frontend/allServer/` suite is 71/71 green.

- **i18n**: none — pure localStorage rehydration.

- **Live PoC**: `/tmp/t113-poc.js` re-run on the next deploy of the
  rehydration fix. Until then, picking "All servers" and reloading
  silently returns the user to the first configured server.