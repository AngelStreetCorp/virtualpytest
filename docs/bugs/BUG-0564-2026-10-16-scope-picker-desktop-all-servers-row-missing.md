# BUG-0564 — Desktop scope picker was missing the "All servers" row

- **When**: TASK-113 PR-C shipped 2026-10-15. The mobile ServerSelector
  (rendered inside `MobileServerBar` for `isMobile && showsServerPicker`)
  grew an "All servers" row at the top of its dropdown. The desktop
  picker — `frontend/src/components/common/ScopePicker.tsx`, the
  three-column Server / Workspace / Project popover rendered in
  `App.tsx` on non-mobile — kept its Server column rendering only the
  configured `availableServers[]` URLs.

- **Visible to**: anyone running the deployed frontend in a desktop
  viewport (1600×1000 or anything wider). The PoC at `/tmp/t113-poc.js`
  uses that size, so the live two-server check that should have flipped
  the picker to "All servers" and asserted the per-server dashboard
  re-render failed: the picker opened, the options were host/device
  names, no "All servers" row.

- **Why it shipped broken**: TASK-113 PR-C scope assumed "the picker" was
  one component (ServerSelector). The actual frontend has two pickers
  (mobile + desktop) and the desktop one was never wired to
  `ALL_SERVERS_SENTINEL` / `isAllServersSentinel`. The doc's §5
  references `ServerSelector` only; a review of `App.tsx`'s imports
  would have caught the gap.

- **Fix**: TASK-113 PR-C extension on main, 2026-10-16. ScopePicker
  imports `ALL_SERVERS_SENTINEL` + `isAllServersSentinel`, renders an
  "All servers" row at the top of the Server column (PublicIcon +
  bold + Divider), wired through `server.handleChange(ALL_SERVERS_SENTINEL)`,
  disabled when `availableServers.length === 0`. The closed-chip label
  uses the sentinel so the user sees "All servers" instead of
  `__all__` while ALL is selected. MobileServerBar/ServerSelector
  unchanged.

- **Tests**: `tests/frontend/allServer/ScopePicker.test.tsx`, 4 cases:
  row renders, click → `handleChange(ALL_SERVERS_SENTINEL)`, chip
  shows "All servers" while ALL is selected, row disabled when no
  eligible peer. 71/71 across `tests/frontend/allServer/`.

- **i18n**: "All servers" key already present in fr.json (1301) and
  de.json (1301); PR-C added it for the mobile one, ScopePicker now
  reuses the same translation.

- **Live PoC**: `/tmp/t113-poc.js` against virtualpytest.angelstreet.io
  should now flip to "All servers" and re-render the dashboard without
  server errors; verify on the next run after deploy.