# QA chaos scripts

Playwright-driven chaos tools for the VirtualPyTest web app. They talk to the
**live** app (`https://virtualpytest.angelstreet.io`) with the auto-sign token,
so nothing has to be deployed to run them.

| Script | What it does |
|---|---|
| `chaos_sweep.py` | Walks a fixed list of routes at one viewport/theme and records console errors, uncaught exceptions, failed requests, HTTP >= 400, blank pages, stuck spinners, horizontal overflow and clipped text. |
| `chaos_nav.py` | Opens every top-level navigation menu, enumerates every item, clicks each one and checks the landing page. |
| `chaos_walk.py` | Seeded random walk: random clicks, random route jumps, back/forward, reload, a second tab, viewport resize and a few seconds of browser-offline. Destructive controls are never clicked. |

## Browser evidence for a fix

These run against a **worktree build**, not the live app: the CORS forwarder in front of the live
backend plus the worktree's Vite dev server (the recipe is in
`docs/agent/validation/TESTING.md`). The screenshots land in `docs/tasks/qa-evidence/fix/`.

| Script | What it does |
|---|---|
| `check_fixes_browser.py` | Opens every fixed page and writes one screenshot per fix. |
| `diag_nav_editor.py` | Prints what the browser actually sees on the navigation editor: the network answers, the console errors and the session storage. For a page that does not behave. |
| `shot_dark_nav_editor.py` | The same page in the dark theme. |
| `shot_desktop_fixes.py` | Retakes the desktop-width shots (the phone viewport leaks into the shots taken after it). |
| `shot_bug0795_missing_interface.py` | Answers the unknown-screens call with the 404 the new server route returns, so the page's answer can be seen before the server half is deployed. |

They read the token with `scripts/agent/auto_sign_token.sh` and never print it.

## Check a fix on the deployed app

`verify_deployed_fixes.py` opens the deployed app (https://virtualpytest.angelstreet.io), checks
that every fixed page behaves, and prints a pass/fail line per check:

```
python3 scripts/qa/verify_deployed_fixes.py
```

Use it after a deploy: it is the same list of checks the QA sweep found broken, so a green run
means the fixes are live and not only in the branch.

## Token

All three scripts read the auto-sign token from `/tmp/vpt_qa_chaos.token`.
Create it with:

```
T=$(scripts/agent/auto_sign_token.sh) && printf '%s' "$T" > /tmp/vpt_qa_chaos.token && chmod 600 /tmp/vpt_qa_chaos.token
```

The token is never printed and never written to the repo.

## Running

```
python3 scripts/qa/chaos_sweep.py --viewport desktop --theme dark --out /tmp/pass-desktop-dark.json
python3 scripts/qa/chaos_nav.py   --viewport desktop --theme dark --out /tmp/nav-desktop-dark.json
python3 scripts/qa/chaos_walk.py  --seed my-seed --viewport phone --theme dark \
        --steps 240 --out /tmp/walk.json --prefix walk
```

Screenshots land in `docs/tasks/qa-evidence/chaos/`. Every walk records its
seed, so a finding can be replayed exactly.

## Safety

`chaos_walk.py` never clicks a control whose accessible name matches the
destructive list (delete, remove, reset, restart, deploy, publish, promote,
rotate, revoke, uninstall, stop, kill, discard, purge, truncate, deactivate,
save, apply, submit, create, add, edit, update, run, rerun, start, execute,
take control, record, stream, capture, import, export, install, connect,
enable, disable, move, copy, clone, rename, schedule, assign, …). A confirm
dialog that still opens is cancelled with Escape, and links that leave the app
are skipped. Device and host actions need a lease:

```
ssh proxmox '~/bin/vpt-lease claim node1-vpt host-clone-1 --agent codebox:<you> \
      --provider <you> --purpose "..." --kind host --ttl 10 --priority P2'
ssh proxmox '~/bin/vpt-lease release <lease-id>'
```
