# BUG-0270 — A passing image verification made the testcase status answer HTTP 500 and left the device locked

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0270                                                     |
| Reported  | 2026-10-02                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | High — a passing run read as an error and kept its device locked |
| Area      | `backend_host/src/controllers/verification/`, `backend_host/src/services/verifications/verification_executor.py`, `backend_host/src/lib/utils/execution_event_utils.py`, `shared/src/lib/utils/app_utils.py` |
| Fixed in  | Unreleased                                                   |
| Commit    | `9d3bd5b79`, `5f53a098a`                                     |

---

## Symptom

A testcase whose path crosses a `waitForImageToDisappear` node with an area passed, then every
`GET /host/testcase/execution/<id>/status` answered HTTP 500
`Object of type bool_ is not JSON serializable`; MCP `execute_testcase` reported the 500. The
terminal execution event never reached the server, so the device lock taken for the run was not
released. Separately, `waitForImageToAppearThenDisappear` could never pass.

## Root cause

- The area matcher scores with `np.sum(...)/total` (an `np.float64`); comparing it to the threshold
  gives `np.bool_`, which landed in the verification details. Blackscreen/zap helpers returned
  `np.bool_`/`np.float64` the same way.
- jsonify refused it (500). `requests.post(json=payload)` in the execution-event emitter refused it
  too, raising before sending; the retry wrapper logged and dropped the error, so the terminal
  event was lost.
- `waitForImageToAppearThenDisappear` unpacked `_match_template`'s 3-tuple into two names and
  raised `ValueError` on the first readable frame.

## Fix

- `app_utils.to_native()` converts numpy scalars/arrays recursively; the Flask JSON provider uses
  it, the verification executor applies it to every controller's result, and the execution-event
  payload goes through it (non-finite floats to `null`, as `requests` encodes with
  `allow_nan=False`).
- `_match_template`, the greyscale retry and the blackscreen/zap helpers return plain types.
- `waitForImageToAppearThenDisappear` unpacks `(found, score, location)`.

## Verification

`tests/backend_host/test_image_match_json_types.py`, `tests/backend_host/test_execution_event_utils.py`.
Live: run a testcase crossing an image-disappear node with an area; its status poll answers 200
and the device is free when it ends.
