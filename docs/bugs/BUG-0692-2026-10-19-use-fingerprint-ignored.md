# BUG-0692 — "Use fingerprint" was ignored when a node had verifications

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0692                                                     |
| Reported  | 2026-10-19                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Low                                                          |
| Area      | backend_host / frontend                                      |
| Fixed in  | build 90145 |
| Commit    | TBD                                                          |

---

## Symptom

In Edit node, ticking "Use fingerprint for verification" on a node that also had authored
verifications changed nothing: navigation and the dialog's Run button still ran the authored
verifications. The fingerprint was only used when the node had no verifications at all.

## Root cause

`VerificationExecutor.verify_node` (`backend_host/src/services/verifications/verification_executor.py`)
only read `use_fingerprint_for_verification` inside `if not verifications:`. The dialog's Run
button made the same choice (`hasVerifications ? handleTest : fingerprint`).

## Fix

- `verify_node`: when the node opts in and has a fingerprint (`__fingerprint.dhash`), the
  fingerprint check (`match_fingerprint`) replaces the authored verifications. They are kept in the
  node, just not run.
- Edit node dialog: the switch is now "Use fingerprint". When it is on, the verification list is
  greyed out with a note ("kept but skipped"), and Run runs the fingerprint check.

## Verification

Open a node with verifications and a fingerprint, switch "Use fingerprint" on and press Run: the
result is the fingerprint match, not the authored checks. Navigate to the node: the host log
shows `Executing 1 verifications` with `match_fingerprint`.
