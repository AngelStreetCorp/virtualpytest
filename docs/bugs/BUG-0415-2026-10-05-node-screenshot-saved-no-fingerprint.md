# BUG-0415 — Saving a node screenshot stored no Localize fingerprint

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0415                                                     |
| Reported  | 2026-10-05                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium                                                       |
| Area      | backend_host / navigation screenshots, MCP |
| Fixed in  | build 90145 |
| Commit    | TBD                                                          |

---

## Symptom

On host-clone-1 (web, `youtube-web`) every node screenshot saved fine but no node got a fingerprint, so Localize had nothing to match. `POST /server/av/saveScreenshot` returned `fingerprint: null`.

## Root cause

`POST /host/av/saveScreenshot` uploaded the capture to R2 first and read the file afterwards. The uploader deletes a cold `capture_*.jpg` once it is uploaded, so the read returned nothing and the best-effort fingerprint step silently produced `None`. The MCP tool `save_node_screenshot` also dropped the fingerprint the route returns.

## Fix

The route reads the frame before the upload, and logs when the fingerprint is `None`. `save_node_screenshot` stores the returned fingerprint on the node, as the editor camera button does.

## Verification

- After deploy: save a node screenshot on host-clone-1; the response and `navigation_nodes.data.fingerprint` carry `v: 6`.
