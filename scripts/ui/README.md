# scripts/ui — light / dark visual review tools

Built for TASK-56 (every page reviewed in light and dark). Use them for any UI change: they work
headless, so they need no desktop browser pane, and they catch off-palette colours a person misses.

| File | What it does |
|---|---|
| `ui_shots.cjs` | Opens routes of a running preview in dark and light, screenshots them (and the dialogs / menus you open with `steps`), and with `AUDIT=1` prints an off-palette colour report per page |
| `ui_audit.js` | The in-page audit: every visible element whose computed colour, background, border or SVG fill is a Tailwind / MUI blue, slate / navy, MUI grey or pink; white borders in dark; `#d4a574` gold used as text in light |
| `ui_images.py` | `pair` (dark \| light side by side), `grid` (2-column contact sheet), `summary` (one line per page from the AUDIT output) — far cheaper to look at than full screenshots |
| `routes.example.json` | Spec format: routes, waits, and steps (`click`, `clickText`, `press`, `eval`, `shot`) |

## Run it

1. Preview of your worktree against live data (skill `vpt-ui-restyle`, or by hand): worktree
   `frontend/.env` with `VITE_SERVER_URL=http://localhost:5109`, the CORS forwarder
   (`~/.claude/skills/vpt-ui-restyle/cors_forwarder.mjs`), and
   `cd frontend && VITE_HTTPS=false ./node_modules/.bin/vite --port 3300`.
2. Screenshots + audit:
   ```bash
   VPT_AUTO_SIGN=<AUTO_SIGN_TOKEN from the server .env> AUDIT=1 OUT=/tmp/ui \
     node scripts/ui/ui_shots.cjs scripts/ui/routes.example.json > /tmp/ui/audit.txt
   python3 scripts/ui/ui_images.py summary /tmp/ui/audit.txt
   python3 scripts/ui/ui_images.py pair /tmp/ui logs models
   ```
   Playwright comes from `tests/e2e/playwright` (`npm ci` there) or `PLAYWRIGHT=<path to the module>`.

## Rules learned the hard way

- `?auto_signed=` on every navigation (the script does it); theme = `localStorage['theme-mode']`.
- Never script Save / Delete / Run / Take Control / Promote: the forwarder forwards writes to the live
  server. Opening a dialog and pressing Escape is fine. On Device, open a host-VNC tile, not a cloud
  device (that starts a paid session).
- Run `tsc` one at a time: several in parallel (~1 GB each) exhausted a 16 GB machine and the preview
  was killed.
- Audit hits that are fine: `?#1e1e1e` (dark `sidebarBg`), MUI switch thumbs, `<Alert severity>`
  icons, categorical handles in the navigation editor.
- Pages that need data start empty (Model Reports, Dependency Report): pick an interface first.
- Generated HTML (reports, share pages, CI/CD, docs indexes) is not a route: render the builder with
  dummy data to a file and screenshot `file://…` the same way — both themes via `theme-mode`. That
  is how TASK-56 found a heatmap `.format()` crash and a broken import before deploy. Rules for those
  pages: `docs/agent/platform/UI_STYLE.md` §8.
