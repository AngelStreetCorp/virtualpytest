# BUG-0945 — The frontend dependency tree shipped a URI parser with four known parsing flaws

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0945                                                     |
| Reported  | 2026-10-26                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium                                                       |
| Area      | frontend / infrastructure                                    |
| Fixed in  | build 90145 |
| Commit    | TBD                                                          |

---

## Symptom

GitHub's dependency scanner reported **four** open advisories against `fast-uri`, all of them
transitive and all of them inside the frontend's dependency tree:

| Advisory                     | Severity | What it is                                                              |
|------------------------------|----------|-------------------------------------------------------------------------|
| `GHSA-wjr9-j795-jxcr`        | medium   | host confusion via unchecked WHATWG host canonicalization               |
| `GHSA-w74x-v6f9-j3xg`        | medium   | URI scheme spoofing via percent-encoded scheme decoding                 |
| `GHSA-333x-w4r6-6crp`        | low      | scheme injection via an unescaped first-segment colon in suffix refs   |
| `GHSA-xhq7-xmqj-769h`        | low      | improper path equivalence in relative reference normalization          |

`fast-uri` is not named in `frontend/package.json`. It arrives with `ajv@8.18.0`, which `serve@14.2.6`
pulls in, and `ajv` uses it to resolve `$ref` URIs while compiling a JSON Schema.

## Root cause

The lockfile pinned `fast-uri@3.1.8`. Every one of the four advisories covers `3.0.0 <= v < 3.1.9`,
so the pinned version is inside all four vulnerable ranges at once.

The path that puts it there is `serve` → `ajv` → `fast-uri`. `serve` is the static file server: the
frontend's own `npm start` runs `./node_modules/.bin/serve -s dist`, and the production image
installs `serve@14` globally in its runtime stage (`frontend/Dockerfile`).

The exposure is limited, and it was worth saying so before touching anything: the `fast-uri` flaws
are in URI *resolution* during schema compilation, so reaching them needs a schema whose `$ref` the
attacker controls. `serve` compiles its own fixed config schema, and the platform never accepts a
schema from a caller. The lockfile entry is also marked `"dev": true`. So this was never an
exploitable path in the running platform — it was a known-bad version of a parser sitting in the
tree, reported four times over by the scanner on every push.

## Fix

`frontend/package-lock.json`: `fast-uri` `3.1.8` → `3.1.9`, the version that closes all four
advisories at once (`3.1.9` for the 3.x line; upstream also published `2.4.8` and `4.2.3` for the
other two lines).

The change is three lines in the lockfile — version, resolved URL, integrity hash — and nothing
else. `ajv@8.18.0` asks for `fast-uri@^3.0.1`, so `3.1.9` is inside the range it already declares:
no dependency is added, removed, or moved, and `package.json` is untouched.

No `package-lock` regeneration was done by hand: `npm update fast-uri --package-lock-only` produced
exactly this diff.

## Verification

1. The tree installs from the new lockfile and the scanner has nothing left to report:

   ```
   cd frontend && npm ci --no-audit --no-fund && npm audit --package-lock-only
   # found 0 vulnerabilities
   ```

   Before the bump the same audit reported the four `fast-uri` advisories.

2. The lockfile resolves to the fixed version:

   ```
   python3 -c "import json;print(json.load(open('frontend/package-lock.json'))['packages']['node_modules/fast-uri']['version'])"
   # 3.1.9
   ```

3. The build is unaffected — the CI jobs `Frontend Lint`, `Check translations (i18n)` and the
   frontend build inside "Docker stack builds and starts" all run `npm ci` against this lockfile
   and are green.

## Left open on purpose

The sixth open alert, `GHSA-379c-qx7v-6h59` (`datasets`, medium), is **not** fixed here, and this
is a decision, not an oversight. `training/requirements.txt` already records it as residual #66:
`unsloth 2026.10.3` requires `datasets <5.0.0`, and the patched version is `5.0.1`, so bumping it
breaks the training venv. The platform itself never imports `datasets` — it is only installed in
the training venv on a rented GPU box — and the advisory needs a dataset whose `file_name` metadata
is attacker-controlled, which is not a path the platform walks. It stays open until `unsloth`
relaxes its constraint.
