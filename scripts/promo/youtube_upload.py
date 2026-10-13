"""YouTube Data API v3 helper for the promo videos: OAuth once, then upload / update / thumbnail / delete.

Setup (owner, once): a Google Cloud project with "YouTube Data API v3" enabled, an OAuth client of type Desktop
app; its client_id / client_secret go into the repo's .env as YOUTUBE_CLIENT_ID / YOUTUBE_CLIENT_SECRET. The refresh
token is written to ~/.config/virtualpytest/youtube_token.json (chmod 600). Never printed, never committed.

  python3 youtube_upload.py auth                      # prints a sign-in link; paste back the localhost URL
  python3 youtube_upload.py auth --code '<url>'       # finishes the sign-in, stores the refresh token
  python3 youtube_upload.py whoami                    # the channel the token belongs to
  python3 youtube_upload.py upload <mp4> --meta <json> [--thumb <jpg>] [--skip-check]   # privacy from meta, default private
  python3 youtube_upload.py update <video_id> --meta <json>
  python3 youtube_upload.py thumb <video_id> <jpg>
  python3 youtube_upload.py delete <video_id>
  python3 youtube_upload.py playlist <video_id>       # add to "VirtualPyTest in action" (upload does it itself)

<json> = {"title": "...", "description": "...", "tags": [...], "privacy": "private|unlisted|public",
          "category": "28", "playlist": "<playlist id, optional>"}
Every upload runs promo_check.py first and refuses the video unless all its counters are 0. --skip-check
uploads anyway; the skip (when, and the counters it ignored) is written into the --meta json, so it stays on record.
Videos uploaded by an unaudited API project are locked private by YouTube until the project is audited.
"""
import argparse
import json
import os
import secrets
import ssl
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

import certifi

HERE = Path(__file__).resolve().parent
# Credentials live outside any worktree (a removed worktree took the old gitignored files with it, 2026-10-12):
# the OAuth client in the repo's .env (YOUTUBE_CLIENT_ID / YOUTUBE_CLIENT_SECRET), the refresh token in
# ~/.config/virtualpytest/ (override: YOUTUBE_TOKEN_FILE).
def _env_files():
    """The checkout's .env, then the main checkout's (a worktree has none of its own)."""
    import subprocess
    files = [HERE.parents[1] / ".env"]
    common = subprocess.run(["git", "-C", str(HERE), "rev-parse", "--git-common-dir"], capture_output=True, text=True)
    if common.returncode == 0:
        files.append((HERE / common.stdout.strip()).resolve().parent / ".env")
    return [f for f in files if f.exists()]


SSL = ssl.create_default_context(cafile=certifi.where())   # python.org Python on macOS ships no CA store
TOKEN = Path(os.environ.get("YOUTUBE_TOKEN_FILE") or Path.home() / ".config/virtualpytest/youtube_token.json")
SCOPES = "https://www.googleapis.com/auth/youtube.upload https://www.googleapis.com/auth/youtube"
REDIRECT = "http://localhost:8765/"
API = "https://www.googleapis.com/youtube/v3"
PLAYLIST = "PLT2zmwBUsZgk"   # "VirtualPyTest in action": every new upload goes in it (owner, 2026-10-06)


def env(name):
    if os.environ.get(name):
        return os.environ[name]
    for f in _env_files():
        for line in f.read_text().splitlines():
            if line.startswith(name + "="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit(f"{name} missing: set it in the repo's .env (see the module docstring)")


def client():
    return {"client_id": env("YOUTUBE_CLIENT_ID"), "client_secret": env("YOUTUBE_CLIENT_SECRET")}


def http(method, url, body=None, headers=None, raw=None):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    h = {"Content-Type": "application/json"} if body is not None else {}
    h.update(headers or {})
    req = urllib.request.Request(url, data=data, method=method, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=600, context=SSL) as r:
            txt = r.read().decode() or "{}"
            return json.loads(txt), r.headers
    except urllib.error.HTTPError as e:
        raise SystemExit(f"HTTP {e.code} {method} {url.split('?')[0]}: {e.read().decode()[:500]}")


def token():
    # The channel's refresh token lives in the main checkout's .env (YOUTUBE_REFRESH_TOKEN, like the client id/secret)
    # so it survives worktrees and machines; the token file only caches the short-lived access token.
    t = json.loads(TOKEN.read_text()) if TOKEN.exists() else {}
    try:
        rt = env("YOUTUBE_REFRESH_TOKEN")
    except SystemExit:
        rt = t.get("refresh_token")
    if not rt:
        raise SystemExit("no YOUTUBE_REFRESH_TOKEN in .env: run `youtube_upload.py auth` once (channel owner)")
    if t.get("refresh_token") != rt:
        t = {"refresh_token": rt}
    if t.get("expires_at", 0) - 60 > time.time():
        return t["access_token"]
    c = client()
    form = urllib.parse.urlencode({"client_id": c["client_id"], "client_secret": c["client_secret"],
                                   "refresh_token": t["refresh_token"], "grant_type": "refresh_token"}).encode()
    r, _ = http("POST", "https://oauth2.googleapis.com/token", raw=form,
                headers={"Content-Type": "application/x-www-form-urlencoded"})
    t.update(access_token=r["access_token"], expires_at=time.time() + r["expires_in"])
    TOKEN.write_text(json.dumps(t)); TOKEN.chmod(0o600)
    return t["access_token"]


def auth(code_url):
    c = client()
    if not code_url:
        q = urllib.parse.urlencode({"client_id": c["client_id"], "redirect_uri": REDIRECT, "response_type": "code",
                                    "scope": SCOPES, "access_type": "offline", "prompt": "consent",
                                    "state": secrets.token_urlsafe(8)})
        print("Open this link, sign in with the channel account, approve, then paste the localhost URL back:")
        print(f"https://accounts.google.com/o/oauth2/v2/auth?{q}")
        return
    code = urllib.parse.parse_qs(urllib.parse.urlparse(code_url).query).get("code", [code_url])[0]
    form = urllib.parse.urlencode({"code": code, "client_id": c["client_id"], "client_secret": c["client_secret"],
                                   "redirect_uri": REDIRECT, "grant_type": "authorization_code"}).encode()
    r, _ = http("POST", "https://oauth2.googleapis.com/token", raw=form,
                headers={"Content-Type": "application/x-www-form-urlencoded"})
    if "refresh_token" not in r:
        raise SystemExit("no refresh token returned; run auth again (prompt=consent)")
    TOKEN.parent.mkdir(parents=True, exist_ok=True)
    TOKEN.write_text(json.dumps({"refresh_token": r["refresh_token"], "access_token": r["access_token"],
                                 "expires_at": time.time() + r["expires_in"]}))
    TOKEN.chmod(0o600)
    main_env = next((f for f in _env_files() if f != HERE.parents[1] / ".env"), HERE.parents[1] / ".env")
    lines = [l for l in main_env.read_text().splitlines() if not l.startswith("YOUTUBE_REFRESH_TOKEN=")]
    main_env.write_text("\n".join(lines + [f"YOUTUBE_REFRESH_TOKEN={r['refresh_token']}"]) + "\n")
    print(f"signed in; refresh token saved as YOUTUBE_REFRESH_TOKEN in {main_env} (copy it to codebox's .env too)")


def auth_h():
    return {"Authorization": f"Bearer {token()}"}


def whoami():
    r, _ = http("GET", f"{API}/channels?part=snippet&mine=true", headers=auth_h())
    for ch in r.get("items", []):
        print(ch["id"], ch["snippet"]["title"], ch["snippet"].get("customUrl", ""))


def snippet(meta):
    return {"snippet": {"title": meta["title"][:100], "description": meta.get("description", "")[:5000],
                        "tags": meta.get("tags", []), "categoryId": str(meta.get("category", "28"))},
            # videos.update replaces the whole status: always send embeddable (the Videos page embeds them) and stats
            "status": {"privacyStatus": meta.get("privacy", "private"), "selfDeclaredMadeForKids": False,
                       "embeddable": True, "publicStatsViewable": True, "license": "youtube"}}


def gate(mp4, skip=False, allow_dark=()):
    """promo_check.py on the video: refuse it unless every counter is 0. Returns the record kept in the meta json.
    allow_dark: the owner's dark_tiles waiver from the meta json ("promo_check_allow_dark": ["t0-t1", ...])."""
    import promo_check
    waived = [tuple(float(x) for x in w.split("-")) for w in allow_dark]
    res, info = promo_check.check(mp4, allow_dark=waived)
    promo_check.report(res, info)
    rec = {"at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "passed": promo_check.passed(res),
           "counters": {k: len(v) for k, v in res.items()}, **({"allow_dark": list(allow_dark)} if allow_dark else {})}
    if not rec["passed"]:
        if not skip:
            raise SystemExit("promo_check failed: not uploading (fix the take, or --skip-check to override, logged)")
        rec["skipped"] = True
        print("promo_check failed: uploading anyway (--skip-check)")
    return rec


def upload_id(mp4, meta, thumb, skip_check=False):
    """promo_check gate, then upload + playlist (+ thumbnail if given; non-fatal). Returns the new video id."""
    meta["promo_check"] = gate(mp4, skip_check, meta.get("promo_check_allow_dark", ()))
    body = snippet(meta); size = Path(mp4).stat().st_size
    _, h = http("POST", "https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status",
                body=body, headers={**auth_h(), "X-Upload-Content-Type": "video/mp4", "X-Upload-Content-Length": str(size)})
    loc = h["Location"]
    r, _ = http("PUT", loc, raw=Path(mp4).read_bytes(), headers={**auth_h(), "Content-Type": "video/mp4"})
    vid = r["id"]; print(f"uploaded {vid} privacy={r['status']['privacyStatus']} https://youtu.be/{vid}")
    add_to_playlist(vid, meta.get("playlist", PLAYLIST))
    if thumb:   # last: it fails (429/403) until the owner's account is verified; the upload is already done
        try:
            set_thumb(vid, thumb)
        except SystemExit as e:
            print(f"thumbnail not set (account not verified yet, or rate limit): {str(e)[:120]}")
    return vid


def upload(mp4, meta, thumb, meta_path=None, skip_check=False):
    try:
        upload_id(mp4, meta, thumb, skip_check)
    finally:   # the check's outcome (a skip above all) stays in the meta json, even when the upload then fails
        if meta_path and "promo_check" in meta:
            Path(meta_path).write_text(json.dumps(meta, indent=1, ensure_ascii=False) + "\n")


def add_to_playlist(vid, pl=PLAYLIST):
    http("POST", f"{API}/playlistItems?part=snippet", headers=auth_h(),
         # no "position": the playlist is sorted by YouTube itself (date added, newest first), so a new video
         # shows at the top on its own; setting a position fails (400 manualSortRequired)
         body={"snippet": {"playlistId": pl, "resourceId": {"kind": "youtube#video", "videoId": vid}}})
    print("added to playlist", pl, "(shown first: the playlist sorts newest first)")


def update(vid, meta):
    body = snippet(meta); body["id"] = vid
    r, _ = http("PUT", f"{API}/videos?part=snippet,status", body=body, headers=auth_h())
    print("updated", r["id"], r["status"]["privacyStatus"])


def set_thumb(vid, jpg):
    http("POST", f"https://www.googleapis.com/upload/youtube/v3/thumbnails/set?videoId={vid}",
         raw=Path(jpg).read_bytes(), headers={**auth_h(), "Content-Type": "image/jpeg"})
    print("thumbnail set")


def delete(vid):
    http("DELETE", f"{API}/videos?id={vid}", headers=auth_h()); print("deleted", vid)


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("cmd"); ap.add_argument("args", nargs="*")
    ap.add_argument("--code"); ap.add_argument("--meta"); ap.add_argument("--thumb")
    ap.add_argument("--skip-check", action="store_true"); a = ap.parse_args()
    meta = json.loads(Path(a.meta).read_text()) if a.meta else {}
    if a.cmd == "auth": auth(a.code)
    elif a.cmd == "whoami": whoami()
    elif a.cmd == "upload": upload(a.args[0], meta, a.thumb, a.meta, a.skip_check)
    elif a.cmd == "update": update(a.args[0], meta)
    elif a.cmd == "thumb": set_thumb(a.args[0], a.args[1])
    elif a.cmd == "delete": delete(a.args[0])
    elif a.cmd == "playlist": add_to_playlist(a.args[0])
    else: sys.exit(__doc__)


if __name__ == "__main__":
    main()
