# BUG-0163 — `docker-compose.yml`'s Supabase include can't find its env file (path doubles)

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0163                                                     |
| Reported  | 2026-09-26                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | High                                                         |
| Area      | setup/docker, CI (release-images.yml)                        |
| Fixed in  | build 9369                                                   |
| Commit    | 60a20d7d17                                                    |

---

## Symptom

`AngelStreetCorp/virtualpytest`'s `Release artifacts` workflow has failed its `Standalone
bundle stands alone` and `Published images bring the stack up` (`verify`) jobs on every run
since at least 2026-09-24, both with:

```
stat .../setup/docker/setup/docker/.env: no such file or directory
```

`bundle` fails resolving the extracted bundle's compose config; `verify` fails inside
`launch.sh` after pulling the published images — so neither job has actually exercised a
published release end-to-end in weeks, even though the images themselves published fine
(image publish and verify are independent steps in the same job).

## Root cause

`setup/docker/docker-compose.yml`'s `include:` block:

```yaml
include:
  - path: supabase/docker-compose.yml
    env_file: setup/docker/.env
```

`env_file` here is a *different* setting from the `--env-file` CLI flag some CI steps also
pass — it tells the **included** sub-project (`supabase/docker-compose.yml`) which env file to
load for its own variable substitution. **Different Compose versions resolve that path
differently**: this session's local Compose (v5.0.0) resolves it relative to the directory of
the file declaring the `include:` (`setup/docker/`), so `setup/docker/.env` there doubles to
`setup/docker/setup/docker/.env`; the self-hosted CI runners' Compose version resolves the
identical string relative to **CWD** instead, where it's correct. Neither pool is "wrong" —
they're just different Compose releases disagreeing on a feature (`include`) that's newer and
less settled than the rest of the spec. **No single path string satisfies both.**

This line had already been fought over twice without resolving it — commit `84c695fca6` first
set it to an absolute path for a similar reason, `3a0084da3d` changed it to `.env` ("resolve
compose env path in release checks"), `3bdd7fefa4` changed it back to `setup/docker/.env`
("restore absolute include env_file path") — because each fix was verified against only one
runner pool at a time and happened to break the other. `3bdd7fefa4`'s revert kept
`regression.yml`'s self-hosted job passing (BUG-0162's investigation confirmed
`Docker stack builds and starts` is green today) while leaving the public repo's
GitHub-hosted jobs (`bundle`, `verify`) broken the whole time — the two runner pools
apparently never got compared side by side before; nothing narrower than "both green" was ever
checked at once. Whichever behavior 3bdd7fefa4 observed, `.env` is the value the compose-spec
rule (declaring-file-relative) and this session's direct testing both agree on.

The unrelated `--env-file setup/docker/.env` flag on `regression.yml`'s pre-pull step (CWD-
relative, correct as written) is untouched — conflating the two is exactly how this regressed
twice already.

## Fix, revised

The first fix (`env_file: setup/docker/.env` → `env_file: .env`) made the GitHub-hosted jobs
pass but broke the self-hosted one (`Docker stack builds and starts`, CI run 36239404078):
`Couldn't find env file: <workspace-root>/.env`. That self-hosted runner's Compose version
resolves `include.env_file` relative to **CWD**, not the declaring file's directory — the
opposite rule from what this session's local testing (a newer Compose) showed, and the
opposite of what GitHub-hosted `ubuntu-latest` does. **No single string value satisfies both**
— this is a genuine cross-version disagreement in how Compose resolves `include.env_file`,
which is exactly why this line had already been fought over twice (`3a0084da3d` /
`3bdd7fefa4`) without it sticking.

The actual fix: **delete the `env_file:` line under `include:` entirely.** The top-level
project's own `.env` — loaded via the ordinary CWD-relative `--env-file`/`COMPOSE_ENV_FILE`
mechanism every Compose version already agrees on (proven by the service-level `env_file: .env`
lines at `backend_server`/`backend_host`, which have never had this problem) — supplies the
same variables to the included Supabase file in the same substitution pass. Verified locally:
`docker compose ... config` with and without the `include.env_file` line produces **byte-
identical output**. Removing the line removes the only place this ambiguity could bite.

## Verification

- `docker compose config` (full output, not just `--services`) is byte-identical with and
  without `include.env_file: .env` present, across every `-f`/CWD/`COMPOSE_ENV_FILE`
  combination tested (both absolute and relative, single and dual `-f`).
- `python3 -c "import yaml; yaml.safe_load(...)"` confirms the file still parses.
- CI on `virtualpytest-internal` (`Docker stack builds and starts`, self-hosted, the runner
  pool this exact change broke on the first attempt) and a `workflow_dispatch` of
  `Release artifacts` on the public repo (`bundle` + `verify`, GitHub-hosted) are the real
  end-to-end confirmation that both runner pools agree now — pending on this commit.
