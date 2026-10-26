# BUG-0538 — A docs link with a #section opens at the top of the page instead of that section

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0538                                                     |
| Reported  | 2026-10-15                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Low                                                          |
| Area      | frontend / docs viewer                                       |
| Fixed in  | build 90145 |
| Commit    | see `git log` for `fix(docs): scroll to the #anchor`         |

---

## Symptom

On the Platform update page, a step's **How this step works** link opens
`/docs/user-guide/platform-update#step-0` in a new tab, but the guide loads at the
top instead of at the `step-0` section.

## Root cause

Two layers. (1) The viewer fetches the markdown after mount, so the browser's own hash scroll
runs against an empty page; the first fix added a scroll effect after render. (2) That effect
found nothing, because **the ids never reached the DOM**: the shared `a` renderer in
`components/docs/markdownComponents.tsx` only passed `href`/`children`, so the guide's raw
`<a id="step-3"></a>` anchors (parsed by rehype-raw, no href) were rendered without their id,
and the `h1`-`h4` renderers set no ids at all, so `#some-heading` links could not work either.
Live evidence: `querySelectorAll('[id*=step]')` was empty on `/docs/user-guide/platform-update#step-3`.

## Fix

- `a` without href but with `id`/`name` renders `<span id=...>`; real links are unchanged.
- `h1`-`h4` get GitHub-style slug ids (`slugifyHeading`, no new dependency).
- The scroll effect from the first fix (behavior `auto`, 80 px margin) is unchanged; it re-runs
  when the markdown arrives or changes, so it now finds the element.

## Verification

Unit test `frontend/src/components/docs/markdownComponents.test.tsx` renders ReactMarkdown with the real components and asserts `id="step-3"`, `name` anchors and heading slugs appear. `tsc --noEmit` and eslint clean on touched files.
