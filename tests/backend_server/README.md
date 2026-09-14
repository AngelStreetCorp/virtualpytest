# backend_server tests

Live HTTP pytest coverage for backend-server routes.

## Run

```bash
SERVER_URL=https://<origin-ip> TEAM_ID=team_123 API_KEY=... \
  pytest tests/backend_server -v
```

Optional authenticated auth test:

```bash
AUTH_TEST_JWT=<valid_supabase_jwt> pytest tests/backend_server/test_auth.py -v
```

Use `AUTH_TEST_JWT` only when frontend JWT auth is enabled in the target environment.

Role tokens (`ADMIN_/TESTER_/VIEWER_/RUNNER_TEST_JWT`, plus `AUTH_TEST_JWT` = admin) come from
`scripts/setup_test_accounts.py` (fixed `*.test@vpt.local` users, login banned, 1-year HS256 tokens
signed with the target server's `SUPABASE_JWT_SECRET`). CI passes them from GitHub secrets
(`regression.yml`, backend job) — minted 2026-09-07, refresh before 2027-09-07.
