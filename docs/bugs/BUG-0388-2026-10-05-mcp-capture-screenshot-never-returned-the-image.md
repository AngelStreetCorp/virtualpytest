# BUG-0388 — MCP capture_screenshot never returned the image

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0388                                                     |
| Reported  | 2026-10-05                                                   |
| Status    | Closed                                                       |
| Severity  | High                                                         |
| Area      | backend_server / MCP                                         |
| Fixed in  | build 90145 |
| Commit    | TBD                                                          |

---

## Symptom

Every `capture_screenshot` call through the production MCP endpoint
(`/server/mcp` on the public server) answered with the URL and OCR-less text only, and the line
`⚠ Image embed failed: ConnectionError from http://localhost/host/<host>/stream/... — caller can
still GET the URL directly.` No image block reached the calling model, so it could not see the
screen.

## Root cause

`backend_server/src/mcp/tools/screenshot_tools.py` turned the relative screenshot URL
(`/host/<host_name>/stream/<device>/captures/<file>`) into `https://localhost{url}` and then
`http://localhost{url}`, assuming an nginx on the server VM that routes `/host/<name>/...` to the
host. The production server VM runs no such nginx, so both requests were refused. The OCR and VLM
sections are built from the fetched bytes, so they were skipped too.

## Fix

The screenshot is fetched from the host that holds it, through `call_host()` (contract #1):

- `shared/src/lib/utils/build_url_utils.py` — `call_host(..., raw_response=True)` returns the
  response body as bytes instead of parsing JSON; error paths still return the usual dict.
- `backend_server/src/mcp/tools/screenshot_tools.py` — new `_fetch_screenshot_bytes()`: reads the
  host name from `/host/<name>/stream/...` (falls back to the `host_name` argument), looks the host
  up in the host manager and GETs that same path from it. The host answers the nginx-shaped path
  itself (`host_stream_routes.serve_stream_file_for_host`, BUG-0171) and accepts the service key
  that `call_host()` sends. An absolute URL is still fetched as-is with TLS verification on. The
  2 MB embed cap and the "Image embed failed: …" line are unchanged; the reason now names the host
  and its HTTP status.

`backend_server/src/mcp/utils/screenshot_capture.py` (the `include_screenshot` image on
navigation/action tools) uses a different path — the public base the client called — and is not
changed here.

## Verification

- `python3 -m pytest -m unit tests/backend_server/test_mcp_screenshot_fetch.py` — the image is
  fetched with `call_host(host_info, url, method='GET', timeout=10, raw_response=True)` and
  embedded; a host 404, an oversized image and an unregistered host are reported in the text.
- After deploy: call `capture_screenshot` on the production MCP endpoint and check the response
  carries an `image` content block and an OCR section.

### Live check (2026-10-05, node1)

MCP `capture_screenshot` on labox-dongle/device1 through the public `/server/mcp`: HTTP 200 in 1.9 s, content = a text block and an `image/jpeg` block (~149 kB base64).
