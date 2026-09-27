# BUG-0171 — Docker host: archive stream and captures never load (no nginx to answer `/host/<name>/`)

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0171                                                     |
| Reported  | 2026-09-27                                                   |
| Status    | Fixed in code, release pending                               |
| Severity  | High (every Docker install; archive, captures, thumbnails, VNC live audio) |
| Area      | backend_host (stream routes, auth guard), setup/docker       |
| Fixed in  | —                                                            |
| Commit    | —                                                            |

---

## Symptom

On the gcloud standalone VM (Docker stack behind a Cloudflare tunnel) the VNC device's
archive player fails: `HLS error: networkError manifestLoadError … url:
http://gcloudstandalone.virtualpytest.com:6109/host/vpt-gcloud-host/stream/capture/segments/output.m3u8`.
The live VNC tile works. The capture pipeline works too: ffmpeg runs, segments exist, and
`http://localhost:6109/host/stream/capture/segments/output.m3u8` answers 200 on the VM.

## Root cause — two layers

1. The Docker compose registers `HOST_URL=http://<PUBLIC_HOST>:6109`. A browser on an HTTPS
   page cannot load `http://…:6109`, and that port is not published on the tunnel.
2. The frontend always writes media URLs nginx-style: `/host/<name>/stream/…`
   (`normalizeHostStreamPath` inserts the host name whenever `host_url` does not already
   contain it). On a native install nginx strips `/host/<name>/`, forwards to the host, and
   enforces the server-minted `vpt_host_session` cookie with `auth_request`. The Docker host
   has no nginx: it only serves the bare `/host/stream/…` — deliberately unauthenticated,
   "nginx guards it" — and its API-key guard answers **401** to the name-prefixed path.

So on *every* Docker install, LAN included, the archive/captures/thumbnails of a host and the
VNC live-audio track were unreachable; only the live noVNC tile (a separate URL) worked.

## Fix

The host now behaves like "host + nginx" from the outside:

- `backend_host/src/routes/host_stream_routes.py`: `/host/<host_name>/stream/…` (file and
  directory listing) are answered by the host itself, only for its own `HOST_NAME`, and only
  when the caller presents the server-minted `vpt_host_session` cookie (claims `host` ==
  this host, HS256 with `HOST_SESSION_SECRET` → `SUPABASE_JWT_SECRET` → `FLASK_SECRET_KEY`,
  the same resolution as the server) or the service `X-API-Key` (heatmap processor, MCP).
  `backend_host/src/lib/utils/host_session.py` holds the check.
- `backend_host/src/app.py`: the global API-key guard leaves `/host/<own name>/stream/` to
  that route. The bare `/host/stream/…` is unchanged (LAN / nginx installs).
- `setup/docker/docker-compose.yml` + `docker-compose.host.yml`: `HOST_URL` overridable;
  `HOST_SESSION_SECRET` passed to the host (defaults to `JWT_SECRET`) and to the server.
- Deployment: `HOST_URL=/host/<HOST_NAME>` and a proxy/tunnel rule routing that prefix on the
  **API hostname** to `:6109` — same origin as the server, so the browser sends the cookie
  the server set for `Path=/host/<name>/`. On gcloud: cloudflared rule
  `gcloudstandalone-api.virtualpytest.com` + path `^/host/vpt-gcloud-host/` → `localhost:6109`.

Server-side readers are unaffected: `buildHostUrl` uses `host_api_url` (internal) and the
bare path.

## Verification

Pending the `virtualpytest-host` image release. Planned: anonymous fetch of
`https://gcloudstandalone-api.virtualpytest.com/host/vpt-gcloud-host/stream/capture/segments/output.m3u8`
→ 401; with `X-API-Key` → 200; archive player in the browser plays; bare
`/host/stream/…` on the host unchanged.
