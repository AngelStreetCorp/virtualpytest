"""
The whole game as a series of runs (TASK-33 phase 4d): each run of the long game is kept as one
segment, `<stamp>.webm` (the game screen) + `<stamp>.json` (video start / end, summary, events), in the
private game folder. The game report plays them back to back, the way the stream player chains TS files,
with one timeline for the whole game.

The segments stay private: the footage is the game's, and the events folder sits next to the ROM and
the saves. Watch them through the viewer, bound to 127.0.0.1 (from another machine, over an SSH tunnel):

    sudo -u vpt_user python3 -m shared.src.lib.game.pokemon.series --runs /var/lib/vpt-private/pokemon/runs
    ssh -L 8795:127.0.0.1:8795 <host>   # then open http://127.0.0.1:8795/
"""

import argparse
import glob
import http.server
import json
import os
import re
import shutil
import subprocess
from typing import Dict, List, Optional

from . import report

PORT = 8795
NAME = re.compile(r"^\d{8}-\d{6}\.(webm|json)$")


def finalize_video(path: str) -> bool:
    """Remux a MediaRecorder WebM (no duration, no cues) so players know its length and can seek in it."""
    if not os.path.exists(path) or not shutil.which("ffmpeg"):
        return False
    tmp = path + ".tmp.webm"
    r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", path, "-c", "copy", tmp],
                       capture_output=True, timeout=300)
    if r.returncode != 0 or not os.path.exists(tmp):
        if os.path.exists(tmp):
            os.remove(tmp)
        return False
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)
    return True


def save_run(runs_dir: str, stamp: str, events: List[Dict], rec: Dict, summary: Dict, save: str = "latest") -> str:
    """Keep one run as a segment of the game: finalize its video, write its events (mode 600)."""
    video = os.path.join(runs_dir, f"{stamp}.webm")
    finalize_video(video)
    path = os.path.join(runs_dir, f"{stamp}.json")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump({"video": os.path.basename(video), "video_start": rec.get("start"), "video_end": rec.get("end"),
                   "save": save, "summary": summary, "events": events}, f)
    return path


def load_runs(runs_dir: str, save: Optional[str] = None) -> List[Dict]:
    runs = []
    for path in sorted(glob.glob(os.path.join(runs_dir, "*.json"))):
        if not NAME.match(os.path.basename(path)):
            continue
        with open(path) as f:
            run = json.load(f)
        if save and run.get("save", "latest") != save:
            continue
        if run.get("video_start") and os.path.exists(os.path.join(runs_dir, run.get("video", ""))):
            run["stamp"] = os.path.basename(path)[:-5]
            runs.append(run)
    return runs


def build_series(runs: List[Dict], title: str = "Pokémon Blue — the whole game") -> str:
    """The game report over every run; each segment's video and events are fetched when it plays."""
    segments, events, offset = [], [], 0.0
    for run in runs:
        seg = report.segment(run["events"], run["video"], run["video_start"], run.get("video_end"), run["summary"],
                             offset=offset, events_url=f"{run['stamp']}.json", name=run["stamp"])
        segments.append(seg)
        events += run["events"]
        offset += seg["dur"]
    first, last = (runs[0]["summary"], runs[-1]["summary"]) if runs else ({}, {})
    summary = {**last, "start_milestone": first.get("start_milestone"), "duration_s": offset}
    return report.page(segments, summary, report.totals(events), title)


class SeriesServer(http.server.ThreadingHTTPServer):
    """Private viewer: `/` is the game report (rebuilt per request, so new runs appear), and the
    segment files are served with byte ranges so the player can seek inside a video."""

    def __init__(self, runs_dir: str, port: int = PORT, save: Optional[str] = None):
        self.runs_dir, self.save = runs_dir, save
        super().__init__(("127.0.0.1", port), _Handler)


class _Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code: int, body: bytes, ctype: str, extra: Optional[Dict] = None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Accept-Ranges", "bytes")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        name = self.path.split("?")[0].lstrip("/")
        if name in ("", "index.html"):
            page = build_series(load_runs(self.server.runs_dir, self.server.save))
            return self._send(200, page.encode(), "text/html; charset=utf-8")
        if not NAME.match(name):
            return self._send(404, b"not found", "text/plain")
        path = os.path.join(self.server.runs_dir, name)
        if not os.path.exists(path):
            return self._send(404, b"not found", "text/plain")
        ctype = "video/webm" if name.endswith(".webm") else "application/json"
        size = os.path.getsize(path)
        m = re.match(r"bytes=(\d*)-(\d*)", self.headers.get("Range", ""))
        with open(path, "rb") as f:
            if not m or (not m.group(1) and not m.group(2)):
                return self._send(200, f.read(), ctype)
            if m.group(1):
                start = int(m.group(1))
                end = min(int(m.group(2)) if m.group(2) else size - 1, size - 1)
            else:   # "bytes=-N": the last N bytes
                start, end = max(0, size - int(m.group(2))), size - 1
            if start >= size:
                return self._send(416, b"", ctype, {"Content-Range": f"bytes */{size}"})
            f.seek(start)
            return self._send(206, f.read(end - start + 1), ctype, {"Content-Range": f"bytes {start}-{end}/{size}"})


def main():
    ap = argparse.ArgumentParser(description="Watch the whole game: every run back to back, with the AI's decisions.")
    ap.add_argument("--runs", required=True, help="the private runs folder (…/pokemon/runs)")
    ap.add_argument("--port", type=int, default=PORT)
    ap.add_argument("--save", default=None, help="only the runs of this save name")
    a = ap.parse_args()
    runs = load_runs(a.runs, a.save)
    print(f"{len(runs)} runs, {sum(r['summary'].get('duration_s') or 0 for r in runs) / 3600:.2f} h — "
          f"http://127.0.0.1:{a.port}/  (Ctrl-C to stop)")
    with SeriesServer(a.runs, a.port, a.save) as srv:
        try:
            srv.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
