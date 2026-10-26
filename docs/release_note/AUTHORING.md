# Authoring the release notes

## When to update `README.md`

- **Not on every commit.** Skip `chore` / `docs` / `refactor` / internal-only changes.
- Finished a **user-facing feature**? Add one line under **`## Unreleased` → Features** (or, if it only polishes an existing feature, under **Improvements**) — see *Entry kinds and areas* below.
- Finished a **user-facing fix**? Log it in the [bug tracker](../bugs/README.md) first, then add
  one line under **`## Unreleased` → Bug fixes** with its `[BUG-XXXX]` link. Features and fixes
  stay in separate lists — never mix them.
- **Cutting a build?** Rename `## Unreleased` → `## build <NNNN> — <YYYY-MM-DD>`, start a fresh
  empty `## Unreleased` above it, and set the fixed-in build on those bugs in the tracker.
- **Every build section ends with `### Upgrade`**: what an operator has to do to run this
  build — database migrations to
  apply, new `.env` keys, which services restart (and which the deploy script does *not*
  restart), proxy / Grafana files to hand-deploy, and the exact deploy commands with their
  parameters. That block is generated, not remembered:
  `python3 scripts/release/upgrade_notes.py [<previous-tag>]` reads the git diff since the last
  build and prints both headings; paste them, then write the plain-words paragraph. Keep the
  Unreleased section's copy current when a change adds a migration or a new key, so the block
  is never written from memory at cut time.
- **Feature needs a DB migration?** The entry **must** flag it by ending with
  ` · 🗄 DB migration \`<file>\`` — the dated file in `setup/db/migrations/` (or the feature's own
  `db/` dir, e.g. `features/cicd/db/`). `update_core.sh` deploys code but does **not** apply
  migrations, so shipping the code without running the migration first breaks the feature; the flag
  is the reminder to apply it on the DB before/with the deploy. When several entries share one
  migration, flag only the entry that introduces it.
  **The marker is per-database, not per-release.** A migration run on our own deployment is *not*
  done — it must be applied to every database the release reaches, including each customer install
  and any second environment. Treat a flagged entry as outstanding until every one of them has had
  it run.

Format each line as `- **Short title** — short clause · [BUG-XXXX](../bugs/BUG-XXXX-<date>-<slug>.md) · \`shortHash\` · 🗄 DB migration \`<file>\``
— a bug fix links to **its own bug file**, not the index. Drop the `[BUG-XXXX]` link for features
(which have no bug entry), and the `🗄 DB migration` marker for anything that doesn't touch the
schema. Entries that exist only on this branch (`feat/demo`) sit at the end of each list.

## Build numbers

A deployed version tag such as `main-2026.10.14-87931` maps to the section whose heading number equals the tag's last segment (`## build 87931 — 2026-10-14`). Cut a build in the same step as stamping `VERSION.txt`, so every release tag has a section. A version with no section of its own resolves to the newest section at or below its number.

## Entry kinds and areas

Every `## ` list (Unreleased and each build) uses these headings, each **once**, in this order:
`### Features`, `### Improvements`, `### Bug fixes`, `### Security`, `### Internal`, `### Upgrade`.
`scripts/release/check_release_notes.py` runs in CI and in the pre-push gate and fails on a second
heading, an unknown heading, or a missing area.

| Kind | Test | Examples |
|---|---|---|
| **Feature** | A customer could name it in a sales call or a support ticket; it has its own page, panel, mod or workflow. | `**GitLab** — Connect your own GitLab and browse it like a GitHub repo home. · area: integrations` · `**Mods** — Add-ons you switch on. · area: platform` · `**Timeline** — A device's whole day as thumbnails. · TASK-37 · area: monitoring` |
| **Improvement** | Makes an existing feature nicer, faster or clearer; nobody would name it on its own. | Timeline empty state · the Ask AI glow pulse · the Screenshots page loads faster (each ends with `· area: <slug>`) |
| **Bug fix** | Something that was wrong now works; always has a `[BUG-nnnn]` link. | `**The tile stayed black after the drone was switched off** · [BUG-0519](../bugs/BUG-0519-….md)` |
| **Security** | Closes an exposure. | a stale pin could be delivered in a customer bundle |
| **Internal** | Only an operator or developer notices it: libraries, payload fields, ops agents, infra. No area. The customer view hides it. | numpy 2 / OpenCV 4.13 · two malloc arenas · the Masterchief agent |

A Feature or Improvement ends with ` · area: <slug>`. The list is fixed at seven; a new area needs an
owner decision, so it cannot sprawl:

| Slug | Name shown | Holds |
|---|---|---|
| `device-control` | Device control & streaming | Take Control, remotes, group control, device page layouts, streams, WebRTC, favorites |
| `monitoring` | Monitoring & alerts | monitoring profiles, alerts, screen memory, heatmap, timeline, maintenance windows, caption playback |
| `testing` | Test automation | scripts, Run Tests, test cases, reports, CI/CD |
| `ai` | AI | Localize, AI usage and budgets, agents, Ask AI |
| `integrations` | Integrations | GitLab, Postman, Zammad tickets, Grafana, Slack |
| `platform` | Platform & admin | Platform update, settings, themes, mods, widgets, docs |
| `entertainment` | Games & entertainment | Clash of Clans, Pokémon, drone (Tello) |

**Update the entry, don't add one.** A feature is one line. When a later round improves a feature
that is already in Unreleased (another GitLab screen, one more AI-usage tab), edit that feature's
sentence and keep its TASK / BUG / migration references; do not add a second line. Add a new
Improvement only when it is polish on a feature from an *earlier* build. Write the Feature sentence for
the customer: what they can now do, in one plain sentence, with a `[Docs](…)` or video link when one exists.

### Manual steps in `### Upgrade`

Besides the generated **Database**, **Settings** and **Services** lines, write every other step an
operator must do by hand (hand-deployed Grafana or nginx files, a sudoers install, a MinIO or database
change) as its own line `**Manual:** <what to do>`. The Release Notes page shows only what needs a
hand (migrations, new `.env` keys, services to restart, manual steps) and links to Platform update;
a build with none of them says "Nothing to do by hand."
