"""Frame sources: a local .mkv (subtitle track burnt in by libass) or a host capture folder."""
import glob
import os
import re
import subprocess
from typing import List, Optional, Sequence

import cv2
import numpy as np
from shared.src.lib.utils import cv2_io


def probe(mkv: str) -> dict:
    import json
    out = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration:stream=index,codec_type,codec_name,width,height:stream_tags=language',
                          '-of', 'json', mkv], capture_output=True, text=True, check=True).stdout
    info = json.loads(out)
    subs = [s for s in info['streams'] if s['codec_type'] == 'subtitle']
    video = next((s for s in info['streams'] if s['codec_type'] == 'video'), {})
    return {'duration': float(info['format']['duration']), 'subtitle_langs': [s.get('tags', {}).get('language') for s in subs],
            'width': video.get('width'), 'height': video.get('height')}


class MkvFrames:
    """Frame at time t with subtitle track `track` (0-based among subtitle streams) burnt in.
    -copyts is required: without it the subtitles filter sees t restart at 0 after the seek and draws nothing."""

    def __init__(self, mkv: str, track: int):
        self.mkv, self.track = mkv, track

    def frame(self, t: float) -> Optional[np.ndarray]:
        esc = self.mkv.replace('\\', '\\\\').replace(':', '\\:').replace("'", "\\'")
        cmd = ['ffmpeg', '-v', 'error', '-copyts', '-ss', f'{max(t - 0.0, 0):.3f}', '-i', self.mkv,
               '-vf', f"subtitles='{esc}':si={self.track}", '-frames:v', '1', '-f', 'image2pipe', '-vcodec', 'png', '-']
        r = subprocess.run(cmd, capture_output=True)
        if r.returncode != 0 or not r.stdout:
            return None
        return cv2.imdecode(np.frombuffer(r.stdout, np.uint8), cv2.IMREAD_COLOR)

    def scene_times(self, thresh: float = 0.4) -> List[float]:
        r = subprocess.run(['ffmpeg', '-v', 'info', '-i', self.mkv, '-an', '-sn', '-vf',
                            f"select='gt(scene,{thresh})',showinfo", '-f', 'null', '-'], capture_output=True, text=True)
        return [float(m) for m in re.findall(r'pts_time:([\d.]+)', r.stderr)]


class CaptureFrames:
    """Frames from a vpt-host capture folder (hot/captures/capture_*.jpg, 5 fps). Film time t = file mtime - t0.
    The folder only keeps ~3 min, so frames are taken as playback reaches them (live), never afterwards."""

    def __init__(self, capture_dir: str, t0: float, live: bool = True):
        self.dir = os.path.join(capture_dir, 'hot', 'captures') if os.path.isdir(os.path.join(capture_dir, 'hot', 'captures')) else capture_dir
        self.t0, self.live = t0, live

    def _listing(self):
        out = []
        for e in os.scandir(self.dir):
            if e.name.startswith('capture_') and e.name.endswith('.jpg'):
                try:
                    out.append((e.stat().st_mtime, e.path))
                except FileNotFoundError:
                    pass
        return out

    def frame(self, t: float) -> Optional[np.ndarray]:
        import time
        target = self.t0 + t
        wait = target + 0.3 - time.time()
        if wait > 0 and self.live:
            time.sleep(wait)
        files = self._listing()
        if not files:
            return None
        mt, f = min(files, key=lambda x: abs(x[0] - target))
        if abs(mt - target) > 0.5:
            return None
        return cv2_io.imread(f)

    def newest(self):
        files = self._listing()
        if not files:
            return None, None
        mt, f = max(files)
        return mt, cv2_io.imread(f)


def calibrate_t0(capture_dir: str, cues, lang: str, read_subtitle, cer, timeout: float = 150.0, need: int = 4, history: bool = False):
    """Playback start (epoch s) of the film in a capture folder: poll the newest frame, note when each of the
    first cues first shows, and take the median of (first seen - cue start). Needs the film to have just started."""
    import statistics
    import time
    cf = CaptureFrames(capture_dir, 0.0, live=False)
    first = {}
    end = time.time() + timeout
    last_mt = 0.0
    # history=True: also scan frames already in the folder (oldest first, every 2nd). Off by default: a restart
    # keeps the folder, so old frames of a previous playback would be taken for this one.
    for mt, f in sorted(cf._listing())[::2]:
        if len(first) >= need:
            break
        img = cv2_io.imread(f)
        r = read_subtitle(img, lang) if img is not None else None
        if r and r.text:
            for c in cues[:8]:
                if c.index not in first and cer(c.text, r.text) <= 0.25:
                    first[c.index] = mt - c.start
    while time.time() < end and len(first) < need:
        mt, img = cf.newest()
        if img is None or mt == last_mt:
            time.sleep(0.1)
            continue
        last_mt = mt
        r = read_subtitle(img, lang)
        if r.text:
            for c in cues[:10]:
                if c.index not in first and cer(c.text, r.text) <= 0.25:
                    est = mt - c.start
                    # all estimates must agree within 1 s; a disagreement means the film restarted meanwhile
                    if first and abs(est - statistics.median(first.values())) > 1.0:
                        first.clear()
                    first[c.index] = est
        time.sleep(0.15)
    if len(first) < need:
        raise RuntimeError(f'calibration failed: only {len(first)} consistent cues of the first 10 seen in {timeout:.0f}s '
                           f'(is the film playing from 0 with the subtitle burnt in?)')
    return statistics.median(first.values()), first
