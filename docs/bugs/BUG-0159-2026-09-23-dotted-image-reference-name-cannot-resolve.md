# BUG-0159 — Dotted image reference names fail verification

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0159                                                     |
| Reported  | 2026-09-23                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium                                                       |
| Area      | image verification, reference editor                         |
| Fixed in  | Unreleased                                                   |
| Commit    | `ecb053038c`                                                 |

---

## Symptom

An image reference with a dotted name, such as `home_red_5.30`, displayed its image and
saved search area in the editor, but Test failed with `Reference area not found in database`.

## Root cause

The image verification controller removed the extension for its database lookup by splitting
the name at the first dot. That changed `home_red_5.30` into `home_red_5`, so the exact
reference row was never found.

## Fix

Strip only a recognized image extension (`.jpg`, `.jpeg`, or `.png`) in the backend lookup.
The editor now rejects dots in reference names for both image and text references, explains
the restriction beside the field and in its tooltip, and suggests underscores instead.

## Verification

Previously saved dotted references such as `home_red_5.30` should resolve from the database
when tested. Attempting to save an image or text reference whose name contains a dot should
show the inline explanation and be refused; underscore names should save normally.
