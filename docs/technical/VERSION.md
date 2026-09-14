# Versioning System

## Format

```
current:<branch>-YYYY.MM.DD-build
previous:<branch>-YYYY.MM.DD-previousBuild-shortHash
```

Example:

```txt
current:debug-2026.03.27-8075
previous:debug-2026.03.27-8074-f755735
```

| Part | Description |
|------|-------------|
| `debug` | Current branch name |
| `2026.03.27` | Date the version was updated |
| `8075` | Human-managed build number shown in the UI |
| `f755735` | Previous known git anchor for traceability |

## How It Works

**VERSION.txt is a tracked file committed to the repo.**

It is updated intentionally when cutting a new version label:

1. Increment the `current:` build label
2. Set `previous:` to the prior version label plus the prior known git hash
3. Commit `VERSION.txt` with the code changes
4. Frontend serves the same file as `/version.txt`

This makes the displayed version stable across git clones, ZIP installs, and deployed VMs.

## Tradeoff

The file does not claim to know the exact current commit hash. Instead, it exposes:

- `current:` the human-facing release label
- `previous:` the last known git-based anchor for debugging

## VERSION.txt Contents

```
current:debug-2026.03.27-8075
previous:debug-2026.03.27-8074-f755735
```

## Frontend

The footer shows the `current:` value from `VERSION.txt`. The same file is emitted into the frontend build as `/version.txt` so the running UI can read it reliably at runtime.
