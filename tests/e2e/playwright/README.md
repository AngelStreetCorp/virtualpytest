# E2E Playwright Tests

Critical-path browser/API tests for VirtualPyTest.

## Suites
- Smoke (`run_e2e_smoke.sh`)
  - UI smoke only
  - Specs:
    - `specs/ui.smoke.spec.js`
- Viewport (`run_e2e_viewport.sh`)
  - Desktop 1280x800 layout checks
  - Mobile 375x812 layout checks
  - Specs:
    - `specs/viewport.desktop.spec.js`
    - `specs/viewport.mobile.spec.js`

## Run locally

```bash
E2E_BASE_URL=https://<origin-ip> E2E_AUTO_SIGN_TOKEN=... TEAM_ID=team_123 API_KEY=... \
  tests/e2e/playwright/run_e2e_smoke.sh

E2E_BASE_URL=https://<origin-ip> E2E_AUTO_SIGN_TOKEN=... TEAM_ID=team_123 API_KEY=... \
  tests/e2e/playwright/run_e2e_viewport.sh
```

`API_KEY` is optional if your environment does not enforce auth.
`E2E_AUTO_SIGN_TOKEN` is required (token-only auth flow).

## Notes
- Config file: `tests/e2e/playwright/playwright.config.js`
- Uses Chromium headless, single worker for stability.
