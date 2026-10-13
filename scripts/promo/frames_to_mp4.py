"""Join a CDP-screencast frame folder into an mp4, every frame first resized to one size.

Chrome's screencast does not keep one frame size: with a 1600x900 CSS page at 1.2x most frames come at
1600x900, and some at 1920x1080 with the page drawn at 1x in the top-left corner on pure black. Joined as they are, the odd-sized frames show as the whole page jumping
smaller or bigger for a frame ("as if the browser was resized"). promo_lib's recorder calls this; it can
also re-encode an existing take, since the frames and their list.txt (durations) stay on disk.

Usage: python3 frames_to_mp4.py <frames dir with list.txt> <out.mp4> [W H]
"""
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image


def _normalize_one(args) -> bool:
    f, w, h = args
    with Image.open(f) as im:
        im = im.convert("RGB")
        # some frames come at full size but with the page drawn at 1x in the top-left corner and pure
        # black (0) around it: crop to the drawn page first
        gray = im.convert("L")
        corner = gray.crop((im.width - 40, im.height - 40, im.width, im.height))
        if corner.getextrema() == (0, 0):
            box = gray.point(lambda v: 255 if v > 0 else 0).getbbox()
            if box and box[2] < im.width - 20 and box[3] < im.height - 20:
                im = im.crop((0, 0, box[2], box[3]))
        if im.size == (w, h):
            return False
        im.resize((w, h), Image.LANCZOS).save(f, quality=92)
    return True


def _signature(f):
    with Image.open(f) as im:
        return np.asarray(im.convert("L").crop((0, 0, im.width, im.height // 8)).resize((96, 12)), dtype=np.int16)


def _pool():
    # one worker per core: every frame is independent (a 60 s take is ~1,500 JPEGs; serial took 3.5 min on codebox)
    from concurrent.futures import ProcessPoolExecutor
    return ProcessPoolExecutor(max_workers=os.cpu_count() or 4)


def normalize(frames_dir: Path, w: int, h: int) -> int:
    files = sorted(frames_dir.glob("*.jpg"))
    with _pool() as ex:
        return sum(ex.map(_normalize_one, [(f, w, h) for f in files], chunksize=16))


def flash_runs(sig) -> list:
    """Outlier runs [i, j) of one to four frames: the page header (sig[m], a small grey array per frame) differs
    from the frames around the run, while those agree - a flash of another zoom/size. Real page changes persist.
    A found run is folded into the frame before it (sig is updated), as drop_flashes does on disk."""
    d = lambda a, b: float(np.abs(sig[a] - sig[b]).mean())
    runs = []
    for i in range(1, len(sig) - 1):
        for k in (1, 2, 3, 4):                # outlier run of k frames: i .. i+k-1, neighbours i-1 and i+k
            j = i + k
            if j >= len(sig): break
            if d(i - 1, j) < 4 and all(d(i - 1, m) > 12 for m in range(i, j)):
                for m in range(i, j):
                    sig[m] = sig[i - 1]
                runs.append((i, j))
                break
    return runs


def drop_flashes(frames_dir: Path) -> int:
    """Replace each flash run (flash_runs) with the frame before it. promo_check.py runs the same test on a
    finished video."""
    files = sorted(frames_dir.glob("*.jpg"))
    with _pool() as ex:
        sig = list(ex.map(_signature, files, chunksize=16))
    n = 0
    for i, j in flash_runs(sig):
        for m in range(i, j):
            with Image.open(files[i - 1]) as im:
                im.save(files[m], quality=92)
            n += 1
    return n


def main():
    frames_dir, out = Path(sys.argv[1]), Path(sys.argv[2])
    w, h = (int(sys.argv[3]), int(sys.argv[4])) if len(sys.argv) > 4 else (1920, 1080)
    n = normalize(frames_dir, w, h)
    flashes = drop_flashes(frames_dir)
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(frames_dir / "list.txt"),
                    "-vf", "fps=30", "-c:v", "libx264", "-crf", "16", "-pix_fmt", "yuv420p", str(out)], check=True)
    print(f"{out}: {n} frames resized to {w}x{h}, {flashes} flash frames replaced")


if __name__ == "__main__":
    main()
