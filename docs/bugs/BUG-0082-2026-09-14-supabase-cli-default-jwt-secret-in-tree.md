# BUG-0082 — Self-hosted installer shipped Supabase's public default JWT secret

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0082                                                     |
| Reported  | 2026-09-14                                                   |
| Status    | Fixed (pending deploy) — rotation on existing installs still open |
| Severity  | Critical                                                     |
| Area      | setup / database / security                                 |
| Fixed in  | build 8887                                                   |
| Commit    | `this commit`                                                |

---

> **Redacted for publication.** This report is published at `/docs/bugs` and ships in customer bundles. The reproduction steps, the credential values and the inventory of which file held which secret have been removed: they are an attack recipe, not an engineering record. The full account is in this repository's history and in the internal task notes.

## Symptom

A `service_role` JWT signed with the Supabase CLI's publicly documented local-dev default
secret was accepted by the production Supabase REST API: full admin access with RLS
bypassed, without any credential ever being stolen — the installer had baked that
well-known string in as the instance's real signing secret.

Confirmed root cause on the live host: SHA-256 of the deployed `GOTRUE_JWT_SECRET` equals the
SHA-256 of that known default string.

## Root cause

`setup/local/linux/database/install_supabase.sh` generates `supabase/config.toml` from a
heredoc that hard-codes `jwt_secret` to the Supabase CLI's published local-dev default
verbatim (this is *not* a Supabase CLI limitation — the CLI reads whatever `config.toml` says).
`extract_supabase_config()` then compounded it: rather than reading the secret the install
actually produced, it independently hard-coded the same default string as a fallback ("JWT
secret - not shown in new format, use default") — so even a hand-edited `config.toml` would
have had its real secret silently overwritten back to the public value in every generated
`.env`/`.env.local`.

Every self-hosted install (lab, `.102`, and by the same script every customer install) got the
identical, publicly-known secret unless someone thought to rotate it by hand afterward.

## Fix

- `setup_supabase_project()`: a fresh install now generates its own `jwt_secret` with
  `openssl rand -hex 32` before writing `config.toml`, substituted in after the heredoc (the
  heredoc itself has no `$`-expansion, so nothing else needed escaping). An existing install
  (config.toml already present) is left alone, but the script now detects if it's still on the
  public default and prints an explicit rotation warning with the exact steps.
- `extract_supabase_config()`: reads `jwt_secret` back out of `config.toml` instead of
  hard-coding the default, so the value written to every `.env` always matches what's actually
  running — whether freshly generated or previously rotated by hand.
- End-of-install summary: a new "Security" section states the Postgres superuser
  (`postgres`/`postgres`) is the Supabase CLI's own fixed local-dev credential with no
  `config.toml` override, and gives the `ALTER ROLE` command to rotate it before the box is
  reachable beyond a trusted LAN.
- `install_grafana.sh`: the datasource-provisioning step now warns when it's about to write a
  `postgres`/`postgres` datasource — every Grafana Editor+ user gets full SQL through it.

**Scope of this change:** it stops new installs from shipping the well-known secret. Rotating
any install created before it is tracked in the internal task notes.

## Verification

- `bash -n` on both scripts — clean.
- Traced the live exploit end-to-end against `.102` before the fix: forged token → `200 []` on
  `/rest/v1/device`. `.102` itself is not yet rotated (see "Not fixed" above); this bug covers
  the installer only.
- `docker exec` (via `sudo`) into the `.102` auth container and hashed `GOTRUE_JWT_SECRET` —
  matches the known default's hash exactly, confirming the mechanism.
- Reviewed the full `config.toml` heredoc for `$` characters before switching to unquoted
  substitution via `sed`; none present, so the heredoc's own quoting (`'EOF'`, unexpanded) is
  unaffected.
