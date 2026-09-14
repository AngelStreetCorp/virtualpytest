# Migrate a UserInterface to another Supabase + MinIO

Tooling to move **one UserInterface definition** (its navigation trees, nodes, edges,
a named variant, and verification references — plus the reference images in object
storage) from a **source** Supabase/MinIO to a **destination** on a different network.

Built for `example_tv` + the `stb` variant, but parameterised (`UI_NAME`, `VARIANT`).

> **Definition only.** This does NOT move run history: `execution_results`,
> `edge_metrics`, `node_metrics`, `script_results`, `heatmaps`,
> `navigation_trees_history`. Those are dev-run data and reference dead report URLs.

---

## What moves

Starting from `userinterfaces.name = 'example_tv'`, the closure is (FK / load order):

| # | Table | Filter |
|---|-------|--------|
| 1 | `userinterfaces` | `name = 'example_tv'` |
| 2 | `navigation_trees` | `userinterface_id = <UI_ID>` (root tree **+ all subtrees**) |
| 3 | `navigation_nodes` | `tree_id IN (those trees)` |
| 4 | `navigation_edges` | `tree_id IN (those trees)` |
| 5 | `userinterface_variants` | `userinterface_id = <UI_ID> AND name = 'stb'` |
| 6 | `verifications_references` | `userinterface_name='example_tv' OR userinterface_id=<UI_ID>` |

Plus the **MinIO objects** that `verifications_references.r2_path` points at, under
`reference-images/example_tv/` and `text-references/example_tv/`.

### Key assumptions (the migration was designed around these)
- **Same `team_id`** on both sides (`7fdeb4bb-3639-4ec3-959f-b54769a219ce`, "Default
  Team"). The destination must already have that `teams` row — it's an FK target.
  If not, seed it first, or switch to a `team_id` remap (not implemented yet).
- **UUIDs are preserved** → foreign keys stay intact and re-running the import is
  idempotent (it deletes the prior copy of this UI first).
- **`r2_url` is stored RELATIVE** (identical to `r2_path`, e.g.
  `reference-images/example_tv/home.jpg`) — the app builds the absolute URL at runtime
  from the prod MinIO env. So a different prod endpoint needs **no DB rewrite**; only the
  object bytes have to be re-uploaded under the same `r2_path`. (The import only rewrites
  rows that happen to hold an absolute `http(s)://` URL.)
- **Object bytes are now bundled** in `out/blobs/` by the export, so the destination has
  everything to re-push (no live link to the source MinIO needed).

---

## Files

```
export_ui.sh   Run on your Mac. Reaches the SOURCE dev DB via ssh -> docker exec -> psql
               for the rows, AND mirrors the MinIO objects (via the storage VM) into
               out/blobs/ so the bundle is self-contained. --dry-run previews counts only.
import_ui.sh   Run on the DESTINATION side. Loads out/ into the prod DB (direct psql),
               keeping UUIDs + team_id. Leaves relative r2_url as-is (see note below).
push_blobs.sh  Run on the DESTINATION side. mc cp --recursive out/blobs/ into the prod MinIO,
               preserving the reference-images/<ui>/... paths so r2_path resolves.
out/           Self-contained bundle:
                 <table>.csv / <table>.cols   the 6 tables + real column order
                 manifest.env                 UI_ID / TEAM_ID / UI_NAME / VARIANT
                 r2_paths.txt                 distinct r2_path values (DB view)
                 blobs/reference-images/<ui>/ the actual image bytes (incl. _binary/
                                              _greyscale companion variants)
README.md      This file.
```

Why CSV + a separate `.cols` file: the column list is pulled live from
`information_schema` on each side, so the scripts survive schema-column drift as long
as both DBs ran the same migrations.

---

## Procedure

### 1. Export from the source (your Mac)

The dev Supabase only answers via `ssh database -> docker exec supabase_db_supabase`,
so `export_ui.sh` uses that path. `$SUDO_PASSWORD` must be set (it is, via
`.claude/settings.local.json`).

```bash
cd setup/db/migrate_ui

# Preview scope — writes nothing:
SUDO_PASSWORD="$SUDO_PASSWORD" ./export_ui.sh --dry-run

# Real export -> out/
SUDO_PASSWORD="$SUDO_PASSWORD" ./export_ui.sh
```

Override targets if needed: `UI_NAME=other_ui VARIANT=somevariant ./export_ui.sh`.
Other knobs: `SSH_ALIAS` (default `database`), `CONTAINER`
(default `supabase_db_supabase`), `OUTDIR` (default `./out`).

Verify `out/` row counts equal the dry-run counts before trusting it.

The export already mirrored the objects into `out/blobs/` (whole `reference-images/<ui>/`
prefix, incl. `_binary`/`_greyscale` companions). Text references are DB-only (their text
lives in the row's `area.text`), so there are no `text-references/` objects to carry.

Knobs (defaults shown): `STORAGE_ALIAS=storage` (ssh host with `mc` + bucket access),
`MC_ALIAS=local` (preconfigured mc alias on it), `MINIO_BUCKET=virtualpytest`.

### Recommended: run steps 2–3 ON a destination VM that has the deployment `.env`

A VirtualPyTest deployment keeps its `.env` with a direct Postgres URI (`SUPABASE_DB_URI`)
and object-store creds (`MINIO_*` or `CLOUDFLARE_R2_*`). The **storage VM is ideal** — it
has `psql` and `mc` installed and reaches both the DB and MinIO. So: scp the bundle there,
unzip, and just run the scripts — they **auto-detect the `.env`**:

```bash
# on the destination storage VM, in the unzipped bundle dir:
OUTDIR=./out ./push_blobs.sh   # objects
OUTDIR=./out ./import_ui.sh    # DB rows
```

Auto-detection searches `ENV_CANDIDATES` (default
`/opt/virtualpytest/.env /shared/code/virtualpytest/.env ./.env`) and is **content-aware**:
it picks the first readable file that actually holds the key the step needs — so it falls
back to `/shared/code/virtualpytest/.env` when `/opt` is absent, and `push_blobs.sh` skips
an env whose object-store creds are unset placeholders (`your_…`). Override anytime with
`ENV_FILE=/path/.env`, or `ENV_CANDIDATES="…"`.

> ⚠️ **The `.env` must be the DESTINATION's.** Reusing the *source* deployment's `.env`
> re-imports into the environment the data came from, not a different one.

### 2. Push the objects to the destination object store

`push_blobs.sh` takes credentials from ONE of:
- `ENV_FILE=/opt/virtualpytest/.env` — reads `MINIO_*`, falling back to `CLOUDFLARE_R2_*`.
- `MC_ALIAS=<name>` — reuse an already-configured `mc` alias (e.g. `local`) +
  `MINIO_BUCKET=<bucket>`.
- discrete `PROD_MINIO_ENDPOINT` / `PROD_MINIO_ACCESS` / `PROD_MINIO_SECRET` / `PROD_BUCKET`.

It runs `mc cp --recursive out/blobs/ <alias>/<bucket>/`, preserving paths so they match
`r2_path`. (Uses `cp`, not `mirror` — mirror's destination diff-scan can stall on some
MinIO setups even when single uploads work fine.)

### 3. Import the DB rows into the destination

`import_ui.sh` takes a connection from ONE of:
- `ENV_FILE=/opt/virtualpytest/.env` — reads `SUPABASE_DB_URI`.
- `PG_URI='postgresql://user:pass@host:5432/postgres'`.
- discrete `DST_HOST` / `DST_PORT` / `DST_USER` / `PGPASSWORD` (+ optional `DST_DB`).

It:
1. Preflights that the `teams` row (`TEAM_ID` from manifest) exists — aborts if not.
2. Deletes any prior copy of this UI (idempotent re-run).
3. Bulk-loads the 6 tables with `session_replication_role = replica` so the
   `navigation_trees` self-FK, CHECK constraints, and triggers don't fight load order.
4. Leaves relative `r2_url` untouched (the norm); only rewrites absolute `http(s)://`
   rows, and only if `PROD_MINIO_PUBLIC_URL` is supplied.
5. Prints final row counts.

`import_ui.sh` uses client-side `\copy`, so it needs `psql` on the run host and a reachable
Postgres port (the dev DB exposes `54322`).

> **If prod is also only reachable via `ssh -> docker exec`** (like dev), `import_ui.sh`
> needs an SSH variant: `\copy` runs client-side, so the CSVs must be `docker cp`'d into
> the container first. Not written yet — ask if you need it.

After import on a self-hosted Supabase, reload PostgREST so the REST API sees the rows:
`NOTIFY pgrst, 'reload schema';` (or `docker restart supabase_rest_<project>`).

---

## Caveats

- **Shared references.** A reference with `shared=true` whose `userinterface_name` is a
  *different* UI but which these trees use won't be caught by the filter. The export
  scans node/edge JSON and writes any such names to
  `out/unresolved_reference_names.txt` (when present) — review it.
- **Verification lookup key** is the `image_path` value in a verification object, not
  `reference_name` (which is just a label). e.g. the `stb` override's `no_signal_image`
  resolves to the reference actually named `no_signal`.
- **Schema parity required.** Both DBs must have run the same migrations (notably
  `034_node_edge_variant_overrides.sql`), or the per-table column sets won't match.

---

## Last verified export (source = dev DB, VM .102)

| Object | Count |
|--------|-------|
| userinterfaces | 1 |
| navigation_trees | 22 |
| navigation_nodes | 83 |
| navigation_edges | 71 |
| userinterface_variants (`stb`) | 1 |
| verifications_references | 81 (59 image + 22 text) |
| MinIO objects bundled in `out/blobs/` | 168 (incl. `_binary`/`_greyscale`), ~1.9 MB |

- `example_tv` UI id: `6b481457-5ee8-4e9a-819b-d56533e93c11`
- team_id: `7fdeb4bb-3639-4ec3-959f-b54769a219ce` ("Default Team")
- `r2_url` values are relative (== `r2_path`); text refs hold their text in `area.text`.
