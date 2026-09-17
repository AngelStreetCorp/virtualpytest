# BUG-0066 — Script display names / TC prefixes in the UI came from a stale platform file, never from the customer's identity map

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                                       |
|-----------|-----------------------------------------------------------------------------|
| ID        | BUG-0066                                                                    |
| Reported  | 2026-09-09                                                                  |
| Status    | Fixed (pending deploy — next customer release)                              |
| Severity  | Medium (wrong / missing `TCnnn` prefixes and display names on Run Tests, reports, campaign tables) |
| Area      | frontend/public/data/script_identity_map.json · setup/proxmox/node/{deploy_customer,update_core}.sh · overlay `frontend/public/data/` |
| Fixed in  | build 8887                                                                  |
| Commit    | this commit                                                                 |

---

## Symptom

The customer asked for their `test_scripts/script_identity_map.json` (16 scripts, `TC000`…`TC054`)
to be "added to git for the next release" because the UI did not show those names. The overlay
repo already held that exact file — but it never reached the browser:

- `frontend/src/utils/identityMapCache.ts` fetches **only** the static
  `/data/script_identity_map.json` shipped in the frontend bundle (the backend route
  `/server/script/identity-map`, which serves `test_scripts/script_identity_map.json`, is not
  used by the UI at all).
- `frontend/public/data/script_identity_map.json` is a **platform-tracked** file, untouched since
  the 2026-06-24 snapshot, pushed by every deploy. Versus the customer's map it had 3 entries
  with different prefixes (`gw/email_imap_login`, `gw/superping`,
  `gw/windows_networkassessmenttools`), 7 entries missing (`vpt/smoke_*`, `web/*`) and 8 stale
  ones nobody runs any more.
- Meanwhile every push **excluded** `test_scripts/script_identity_map.json` ("hosts keep their
  own copy"), and `deploy_customer.sh` applied the same exclude to the overlay stage — so the
  overlay's copy was not even in the release bundle (`release-2026.09.08` verified: only the
  `.example` and the stale public copy are inside).

Net effect: the map the customer maintains feeds the server (report naming) but the UI shows
the platform's June file, and no release could change that.

## Root cause

Two copies of one piece of customer configuration, with different owners: the browser copy was
treated as platform code (tracked, pushed, never customer-specific), the server copy as
untouchable site data (excluded everywhere, including from the bundle). Neither path let the
overlay — the declared owner of "identity maps" (overlay README) — deliver the file.

## Fix

Identity maps are **customer configuration**, handled exactly like the frontend config
(`FRONTEND_CONFIG_PATHS`) in all three deploy scripts (`deploy_customer.sh`, `update_core.sh`,
the customer's `update_core.local.sh`):

- `frontend/public/data/{script,campaign}_identity_map.json` and
  `test_scripts/{script,campaign}_identity_map.json` are excluded from a plain-checkout push
  (targets keep their copies) and re-included when the stage/bundle carries them (overlay /
  bundle mode).
- The platform's `frontend/public/data/script_identity_map.json` is reset to the generic
  `{"version": 1, "scripts": {}}` (same as the `.example`): no customer script names in the
  platform tree, and a no-overlay deploy no longer overwrites a target's map.
- The overlay gains `frontend/public/data/script_identity_map.json` = its `test_scripts` copy;
  its unused, misspelt `test_campaign/campaign_identiy_map.json` (empty; the backend reads
  `test_scripts/campaign_identity_map.json`) is removed.
- `DEPLOY_CUSTOMER.md` "Customer frontend configuration" documents the two pairs and the
  "keep both copies identical" rule; the old "ownership undecided" quirk note is replaced.

Not changed: `identityMapCache.ts` keeps reading the static file — one fetch, works without a
server round-trip; the server copy stays for report naming.

## Verification

- Bundle rebuilt from a fresh clone with the patched scripts + overlay: the archive now carries
  `frontend/public/data/script_identity_map.json` and `test_scripts/script_identity_map.json`,
  both 16 entries; the platform's empty copy is not inside.
- `update_core.local.sh` filters, local `rsync -ani` dry run: bundle mode lists both files as
  pushed; plain-tree mode lists neither (targets keep their own).
- Not yet deployed anywhere; ships with the next customer release (the `release-2026.09.08`
  bundle predates this fix — on that delivery the UI keeps showing the June names, as today).
