# Contributing to VirtualPyTest

Thanks for your interest in contributing! VirtualPyTest is an open platform for
perception-and-actuation testing of devices and apps (any AV source + optional
control channel), and we welcome issues, fixes, and features.

## Ways to contribute

- **Report bugs** — open an issue with steps to reproduce, expected vs. actual behavior, and your environment.
- **Request features** — open an issue describing the use case and the problem it solves.
- **Submit code** — fixes, new device controllers, detectors, or dashboards via pull requests.
- **Improve docs** — corrections and clarifications to anything under `docs/`.

## Project layout

| Path | What it is |
|------|------------|
| `backend_server/` | Orchestration API, navigation/execution, MCP server |
| `backend_host/` | Per-host device controllers (remote, AV capture, verification) |
| `frontend/` | React/TypeScript web UI |
| `shared/` | Shared Python library (models, DB, utils) |
| `setup/` | Installers and OS-specific setup scripts |
| `infra/` | Infra services by domain: `monitoring/grafana/`, `proxy/nginx/`, `database/supabase/`, `storage/minio/`, `storage/redis/` |
| `test_scripts/` · `test_campaign/` | Example test scripts and campaigns |
| `docs/` | User, developer, and API documentation |

## Getting set up

```bash
git clone https://github.com/AngelStreetCorp/virtualpytest.git
cd virtualpytest
./setup/quickstart.sh        # Docker-based quick start
```

For a local (non-Docker) developer environment, see **[docs/get-started/local-setup.md](docs/get-started/local-setup.md)**.

## Development workflow

1. **Fork** the repo and create a topic branch from `main`:
   `git checkout -b feat/short-description` (or `fix/...`, `docs/...`).
2. Make focused changes; match the style and conventions of the surrounding code.
3. Keep commits scoped and write clear messages (a short imperative summary line).
4. Run the relevant checks before pushing:
   - Python: `python -m py_compile` on changed files; run tests under `tests/` where applicable.
   - Frontend: `npm run lint && npm run build` in `frontend/`.
5. Open a **pull request against `main`**, describing what changed and why, and linking any related issue.

## Pull request guidelines

- One logical change per PR — smaller PRs are reviewed faster.
- Update docs when you change behavior or configuration.
- Don't commit secrets, credentials, or `.env` files. Configuration belongs in environment variables / `.env` (git-ignored); use the provided `*.env.example` files as templates.
- Don't commit generated artifacts, virtualenvs, or `node_modules`.

## Reporting security issues

Please do **not** open public issues for security vulnerabilities — see **[SECURITY.md](SECURITY.md)** for private disclosure.

## License

By contributing, you agree that your contributions are licensed under the same terms as the project (see [LICENSE](LICENSE)).
