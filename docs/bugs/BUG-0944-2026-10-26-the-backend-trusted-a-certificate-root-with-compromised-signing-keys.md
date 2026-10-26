# BUG-0944 — The backend trusted a certificate root whose signing keys are known to be compromised

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0944                                                     |
| Reported  | 2026-10-26                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Critical                                                     |
| Area      | platform / infrastructure                                    |
| Fixed in  | build 90145 |
| Commit    | TBD                                                          |

---

## Symptom

`certifi` was pinned to `2025.8.3` in `backend_server/requirements.txt`. GitHub's dependency
scanner reported one **critical** advisory against it: [GHSA-6q48-6c7w-9gw2](https://github.com/advisories/GHSA-6q48-6c7w-9gw2)
("certifi bundles emSign root CAs with compromised intermediate CA keys"), affecting every
certifi release from `2019.03.09` up to and including `2026.10.18`.

`certifi` is the trust store of the backend: `requests` (pinned at `2.33.0`) loads its CA bundle
from `certifi/cacert.pem`, and so does `httpx` (pinned at `0.28.1`) and everything else built on
`urllib3`/`ssl`. Every HTTPS call the backend makes — Supabase, the AI providers, the GitHub API,
the model hosts — validated its peer against a bundle that still contained the affected root.

Nothing in the platform fails on its own: a certificate that chains to that root keeps validating.
The failure mode is that a connection which should have been rejected is accepted.

## Root cause

`certifi` is a pinned dependency and the pin was never revisited. The advisory was raised against
the pinned version on the upstream advisory database and surfaced as one of the six open
dependabot alerts on the repository's default branch.

The pin is not cosmetic. `certifi` is the file `requests` reads at import time
(`requests.certs.where()` returns `certifi.where()`), so the version in `requirements.txt` is the
version that decides what the running backend trusts.

What the advisory says, precisely: the bundle contained the `emSign ECC Root CA - G3` root, and
**eight eMudhra intermediate CA certificates** chaining to that root had **compromised private
keys**; the CA revoked them. An attacker holding one of those keys can issue a valid-looking
certificate for any hostname, and if they are also on-path they can intercept or modify the TLS
traffic of every client that trusts the bundle — `requests`, `urllib3` and `pip` included.

The root itself is cryptographically intact, which is exactly why the bundle keeps validating it
and the problem is invisible from the outside.

Upstream fixed it in two steps: `certifi 2026.10.18` removed **all** emSign roots, and
`certifi 2026.10.19` **restored the emSign roots that are not affected**, leaving exactly the
affected one out. The advisory says to upgrade to `2026.10.19` or later **and to rebuild container
images that vendor certifi** — the bundle is baked into the image, so an image that is not rebuilt
keeps the old one.

## Fix

`backend_server/requirements.txt`: `certifi==2025.8.3` → `certifi==2026.10.19`.

The bump is exact-pinned like every other HTTP-stack dependency in that file, on purpose: this
file pins `requests`, `httpcore`, `httpx`, `h11`, `h2`, `hpack` and `hyperframe` to the versions
that work together on Linux and macOS, because a floating `certifi` would drag a different CA
bundle into a combination that was never tested (the file's own header says so).

`2026.10.19` is the version the advisory names, and the measured bundle difference confirms it is
the right one rather than the over-removing `2026.10.18`: of the four emSign roots the old bundle
carried, exactly one — `emSign ECC Root CA - G3` — is gone, and `emSign Root CA - G1`,
`emSign ECC Root CA - C3` and `emSign Root CA - C1` are still there. 145 roots before, 120 after,
plus 7 newer roots added.

No code change: `certifi` is loaded by `requests` from the bundle path, so the new bundle is
picked up by the next install of the backend image. The only behaviour change is that a
certificate chaining to the revoked eMudhra intermediates is now rejected.

## Verification

1. The pin resolves and the package installs next to the pinned `requests`:

   ```
   python3 -m venv /tmp/cert-venv
   /tmp/cert-venv/bin/pip install "certifi==2026.10.19" "requests==2.33.0"
   /tmp/cert-venv/bin/python -c "import certifi, requests; print(certifi.__version__, requests.__version__)"
   # 2026.10.19 2.33.0
   ```

2. The affected root is out of the new bundle, the three unaffected emSign roots are still in it,
   and the old bundle had all four:

   ```
   grep '^# Label:' <bundle> | grep -i emsign
   # new (2026.10.19): emSign ECC Root CA - C3, emSign Root CA - C1, emSign Root CA - G1
   # old (2025.8.3):  ... and emSign ECC Root CA - G3
   ```

3. The backend still trusts the roots it needs — the CI job "Backend deps resolve and import"
   installs `backend_server/requirements.txt` into an isolated venv, runs `pip check` and imports
   the packages whose majors have broken the platform before (`requests`, `httpx`, `httpcore`,
   `supabase`). It is green on this branch.

4. After the deploy, the running container reports the new version — this is the step that the
   advisory's "rebuild container images that vendor certifi" asks for, and it is the only way to
   prove the image was rebuilt rather than restarted:

   ```
   docker exec vpt-server python -c "import certifi; print(certifi.__version__)"
   ```
