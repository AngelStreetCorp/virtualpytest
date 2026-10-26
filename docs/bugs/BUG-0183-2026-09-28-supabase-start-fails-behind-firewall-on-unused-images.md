# BUG-0183 — Supabase would not start behind a firewall: it pulled two images the platform never uses

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0183                                                     |
| Reported  | 2026-09-28                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium — database VM would not come back after a restart     |
| Area      | setup / database install (Supabase CLI)                      |
| Fixed in  | build 90145 |
| Commit    | `0d582527a`                                                  |

---

## Symptom

On a database VM whose outbound access is firewalled, `supabase start` (run after editing
`config.toml`) hung and then failed:

```
✘ edge-runtime Error   Get "https://public.ecr.aws/v2/": context deadline exceeded
✘ imgproxy Error       Get "https://public.ecr.aws/v2/": net/http: request canceled ...
failed to pull docker image: ... Retrying after 4s: public.ecr.aws/supabase/edge-runtime:v1.70.0
```

Every other image was already present locally; only these two were missing, so Supabase — and
with it login and every database call — stayed down.

## Root cause

`setup/local/linux/database/install_supabase.sh` wrote `[edge_runtime] enabled = true` into
`config.toml`, and left `[storage.image_transformation]` at the CLI default (on). `supabase
start` therefore needs the `edge-runtime` and `imgproxy` images, which are hosted on
`public.ecr.aws`. Neither service is used: nothing in the platform calls `/functions/v1`
(Edge Functions) or `/storage/v1` (files live in MinIO / R2). The Docker stack
(`setup/docker/supabase/docker-compose.yml`) already drops both.

## Fix

The installer now writes both off:

```toml
[storage.image_transformation]
enabled = false

[edge_runtime]
enabled = false
```

**Existing installs** keep their old `config.toml` (the installer only writes it on install).
Add the two blocks above to `<SUPABASE_DATA_DIR>/supabase/config.toml` by hand, or start once
with `supabase start -x edge-runtime,imgproxy`.

## Verification

On the affected VM, with the two blocks set: `supabase start` no longer contacts
`public.ecr.aws` for those images, all remaining containers start, and
`curl <api>/auth/v1/health -H "apikey: <anon key>"` returns the GoTrue JSON.
