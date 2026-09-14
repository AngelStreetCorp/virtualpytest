# BUG-0015 — Docs viewer renders inline code as full-width blocks; shows in-repo process sections

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0015                                                     |
| Reported  | 2026-07-23                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Low                                                          |
| Area      | frontend / docs viewer                                       |
| Fixed in  | build 8713                                                   |
| Commit    | `045df5a2d`                                                  |

---

## Symptom

In the in-app **Docs** viewer, every inline `` `code` `` span rendered as a full-width block
(each short token on its own line, breaking sentences apart). Separately, the **Release Note** and
**Bug Tracker** pages showed their in-repo process sections ("When to update this file" / "How to
log a bug"), which are meant for contributors editing the markdown on GitHub, not for readers of
the in-app changelog.

## Root cause

The Docs markdown renderer (react-markdown) was upgraded to v10, which **removed the `inline`
prop** that the custom `code` component relied on to distinguish an inline span from a fenced
block. With `inline` always `undefined`, the renderer treated every `code` node as a block and
wrapped it in the block styling.

The process-section leakage is unrelated to the upgrade: the same source `README.md` files serve
GitHub (where the process sections belong) and the in-app viewer (where they don't), and nothing
stripped them for the app.

## Fix

`frontend/src/` Docs renderer (`045df5a2d`):

- The `code` component now decides inline-vs-block from the presence of a `language-*` class on the
  node (fenced blocks carry it; inline spans don't) instead of the dropped `inline` prop.
- The Release Note and Bug Tracker pages strip their leading process sections ("When to update this
  file" / "How to log a bug") before rendering, so the app shows only the changelog / bug index.

## Verification

Open **Docs › Release Note** and **Docs › Bugs**: inline code renders inline within sentences,
fenced code blocks still render as blocks, and neither page shows its contributor process section.
