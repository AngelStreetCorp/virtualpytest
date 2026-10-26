# BUG-0924 — The Virtual Scripts page could not typecheck, and the nightly check had never run

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0924                                                     |
| Reported  | 2026-10-26                                                   |
| Status    | Fixed                                                        |
| Severity  | Medium                                                       |
| Area      | frontend / virtual scripts / CI                              |
| Fixed in  | build 90145 |
| Commit    | see branch `fix/ci-virtual-scripts-typecheck`                |

---

## Symptom

The regression suite on `main` failed in the job **Frontend Typecheck** with one error:

```
../features/virtual-scripts/frontend/VirtualScripts.tsx(447,41): error TS2345: Argument of type
'VirtualScriptMeta' is not assignable to parameter of type '{ name: string; folder?: string | undefined; }'.
  Types of property 'folder' are incompatible.
    Type 'string | null | undefined' is not assignable to type 'string | undefined'.
      Type 'null' is not assignable to type 'string | undefined'.
```

Nothing was broken for a user: the page worked, because the code that reads the folder already treats
"no folder" as an empty one. What was broken was the **gate**: `main` was red, so every branch that
came after it inherited a red nightly check.

And the error was not new. The heavy suite only runs inside the **00:00-07:00 UTC night window**
(the "night gate" in `.github/workflows/regression.yml`); a push outside that window skips every job
and the run is reported green without testing anything. Every push to `main` on the evening of
2026-10-25 landed between 21:37 and 22:22 UTC, and every one of those runs reported
`Regression Tests: success` with all the jobs **skipped**. The run of 00:55 UTC on 2026-10-26 was the
first one that actually executed the typecheck, and it failed.

## Root cause

**The helper asked for a folder the interface does not promise.**

The server answers `/server/virtual-script/list` with `folder: null` for a script that has no folder,
so the interface declares it as nullable
([features/virtual-scripts/frontend/hooks/useVirtualScripts.ts](../../../features/virtual-scripts/frontend/hooks/useVirtualScripts.ts)):

```ts
export interface VirtualScriptMeta {
  id: string;
  name: string;
  ...
  folder?: string | null;      // null means "no folder"
}
```

The helper that hides the system scripts took a narrower type
([features/virtual-scripts/frontend/VirtualScripts.tsx](../../../features/virtual-scripts/frontend/VirtualScripts.tsx)):

```ts
const isSystemScript = (s: { name: string; folder?: string }) =>
  s.name.startsWith('_') || s.name.startsWith('utils_') || (s.folder || '').startsWith('_') || s.folder === 'utils';
```

`folder?: string` means `string | undefined`, and under `strictNullChecks` a `string | null` is not
assignable to it. Passing a `VirtualScriptMeta` to the helper was therefore a type error, while the
body was already null-safe (`(s.folder || '')`). The typecheck is the only gate that sees this class
of mistake: `vite build` uses esbuild, which strips types without checking them, and eslint does not
type-check either.

## Fix

The helper takes the folder the interface actually has:

```ts
const isSystemScript = (s: { name: string; folder?: string | null }) =>
```

One line, in the one place that knew the folder was a string.

## Verification

Reproduced on a worktree of `origin/main` before the fix and re-run after it, with the same command
the CI job runs (`cd frontend && ./node_modules/.bin/tsc --noEmit -p tsconfig.json`):

| | exit | output |
|---|---|---|
| before | 2 | the TS2345 above, on `VirtualScripts.tsx(447,41)` |
| after | 0 | none |

The same error, with the same line and column, was in the CI log of the failing run
(`Regression Tests` run 40251699468, job "Frontend Typecheck").
