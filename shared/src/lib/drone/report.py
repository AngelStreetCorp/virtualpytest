"""
Game reports. HtmlReporter writes a self-contained folder (frames/*.jpg + index.html) for local
runs; PlatformReporter (platform_io.py) records the same steps through the script context.
"""

import html
import json
import os
import threading
import time
from typing import List, Optional, Protocol

import cv2
import numpy as np

from ..utils.report_theme import report_theme_head
from shared.src.lib.utils import cv2_io

THUMB_W = 480


class Reporter(Protocol):
    def step(self, drone: str, message: str, success: bool, frame: Optional[np.ndarray] = None,
             details: Optional[dict] = None, kind: str = "turn") -> None: ...

    def finish(self, summary: dict) -> Optional[str]: ...


class HtmlReporter:
    def __init__(self, out_dir: str):
        self.out_dir = out_dir
        self.frames_dir = os.path.join(out_dir, "frames")
        os.makedirs(self.frames_dir, exist_ok=True)
        self._lock = threading.Lock()
        self._t0 = time.time()
        self._steps: List[dict] = []

    def step(self, drone: str, message: str, success: bool, frame: Optional[np.ndarray] = None,
             details: Optional[dict] = None, kind: str = "turn") -> None:
        with self._lock:
            n = len(self._steps)
            rel = None
            if frame is not None:
                rel = f"frames/{n:04d}_{kind}_{drone}.jpg"
                img = frame
                if kind != "winner" and frame.shape[1] > THUMB_W:
                    img = cv2.resize(frame, (THUMB_W, int(frame.shape[0] * THUMB_W / frame.shape[1])))
                cv2_io.imwrite(os.path.join(self.out_dir, rel), img, [cv2.IMWRITE_JPEG_QUALITY, 85])
            self._steps.append({"t": time.time() - self._t0, "drone": drone, "message": message,
                                "success": success, "frame": rel, "details": details or {}, "kind": kind})

    def finish(self, summary: dict) -> Optional[str]:
        with self._lock:
            path = os.path.join(self.out_dir, "index.html")
            with open(path, "w") as f:
                f.write(self._render(summary))
            return path

    def _render(self, summary: dict) -> str:
        e = html.escape
        drones: List[str] = []
        for s in self._steps:
            if s["kind"] in ("turn", "info") and s["drone"] not in drones:
                drones.append(s["drone"])
        rows = "".join(f"<tr><th>{e(str(k))}</th><td>{e(json.dumps(v) if isinstance(v, (dict, list)) else str(v))}</td></tr>"
                       for k, v in summary.items())
        winner = next((s for s in reversed(self._steps) if s["kind"] == "winner"), None)
        win_html = ""
        if winner:
            img = f'<img src="{winner["frame"]}" style="max-width:100%">' if winner["frame"] else ""
            win_html = f"<h2>Winner</h2><p><b>{e(winner['message'])}</b></p>{img}"
        cols = max(1, len(drones))
        body = []
        for s in self._steps:
            cls = "ok" if s["success"] else "bad"
            img = f'<img src="{s["frame"]}">' if s["frame"] else ""
            det = e(json.dumps(s["details"])) if s["details"] else ""
            cell = (f'<div class="step {cls}"><div class="m"><span class="t">{s["t"]:.1f}s</span> '
                    f'<b>{e(s["drone"])}</b> {e(s["message"])}</div>{img}<div class="d">{det}</div></div>')
            if s["kind"] in ("turn", "info") and s["drone"] in drones:
                col = drones.index(s["drone"]) + 1
                body.append(f'<div style="grid-column:{col}">{cell}</div>')
            else:
                body.append(f'<div style="grid-column:1 / span {cols}">{cell}</div>')
        return f"""<!doctype html><html><head><meta charset="utf-8">{report_theme_head()}<title>Drone report</title><style>
body{{font-family:sans-serif;margin:16px;background:var(--vpt-page);color:var(--vpt-text)}}
table{{border-collapse:collapse}}th,td{{border:1px solid var(--vpt-border);padding:3px 8px;text-align:left;font-size:13px}}
.grid{{display:grid;grid-template-columns:repeat({cols},1fr);gap:8px;align-items:start}}
.step{{border:1px solid var(--vpt-border);background:var(--vpt-surface);padding:4px;border-left:4px solid var(--vpt-success)}}
.step.bad{{border-left-color:var(--vpt-error)}}.step img{{max-width:100%}}.d{{font-size:11px;color:var(--vpt-text-2);word-break:break-all}}
.t{{color:var(--vpt-muted)}}
</style></head><body><h1>Drone report</h1><table>{rows}</table>{win_html}<h2>Timeline</h2>
<div class="grid">{''.join(body)}</div></body></html>"""
