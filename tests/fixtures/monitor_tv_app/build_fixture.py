"""Build tests/fixtures/monitor_tv_app/captures from raw full-size capture frames.

    python3 tests/fixtures/monitor_tv_app/build_fixture.py <dir with >=450 capture_*.jpg>

The raw frames were copied read-only from vpt-pi1 capture3 (a live camera, 2026-10-13); they are not
committed. Timeline (600 frames = 2 min at 5 fps, sequence numbers contiguous from FIRST_SEQ):
    0-199    live            raw frames 0-199
    200-249  black           synthetic all-black frames (a blackscreen)
    250-399  live            raw frames 200-349
    400-499  frozen          raw frame 349 repeated (a freeze)
    500-599  live            raw frames 350-449
Frames are downscaled to 320x180 so the whole fixture stays small; the replay test copies each frame to
<device>/thumbnails/<name>_thumbnail.jpg (the thumbnail IS the downscaled frame).
Extension (main's no_signal / blackscreen-priority change, BUG-0504): `python3 build_fixture.py --extend` appends 190 synthetic frames to
the existing 600 (no raw frames needed; it reuses fixture frames and draws the rest), the first 600 stay byte-identical:
    600-639  frozen          fixture frame 599 repeated (a freeze that is then taken over by no_signal: the reclassify path)
    640-689  nosignal        a smooth, fully saturated gradient that matches the detector's no-signal profile (SMPTE bars themselves do not at
                             320x180: high edge density): no_signal outranks freeze
    690-729  live            fixture frames 500-539 again
    730-769  nearblack       black with a bright strip over the top 15 %: 85 % dark, a DARK LIVE SCENE since the 15 % strip is
                             above the 2 % lit-pixel limit (BUG-0661). NOT a blackscreen — exercises the "dark live scene" path.
    770-789  nearblack_bs    black with a single bright row at the top (0.56 % lit pixels, under the 2 % limit): IS a blackscreen,
                             restores the "near-black that IS a blackscreen" case that BUG-0661 removed from the fixture.
audio_status.json is a fixed snapshot. Regenerate the expected output with
`python3 tests/backend_host/test_monitor_replay.py --record` (see that file).
"""
import json
import os
import sys

import cv2
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
FIRST_SEQ = 1000
TIMELINE = [('live', 0, 200), ('black', 0, 50), ('live', 200, 150), ('frozen', 349, 100), ('live', 350, 100)]


def main(raw_dir):
    raws = sorted(f for f in os.listdir(raw_dir) if f.startswith('capture_') and f.endswith('.jpg'))
    assert len(raws) >= 450, f'need 450 raw frames, found {len(raws)}'
    caps = os.path.join(HERE, 'captures')
    os.makedirs(caps, exist_ok=True)
    seq = FIRST_SEQ
    timeline = []
    for kind, start, count in TIMELINE:
        timeline.append({'kind': kind, 'first_seq': seq, 'frames': count})
        for i in range(count):
            if kind == 'black':
                img = np.zeros((180, 320, 3), np.uint8)
            else:
                idx = start if kind == 'frozen' else start + i
                src = cv2.imread(os.path.join(raw_dir, raws[idx]))
                img = cv2.resize(src, (320, 180), interpolation=cv2.INTER_AREA)
            name = f'capture_{seq:09d}.jpg'
            cv2.imwrite(os.path.join(caps, name), img, [cv2.IMWRITE_JPEG_QUALITY, 60])
            seq += 1
    with open(os.path.join(HERE, 'audio_status.json'), 'w') as f:
        json.dump({'audio': True, 'mean_volume_db': -33.9, 'timestamp': '2026-10-13T08:36:16.597567',
                   'segment_file': 'segment_000719946.ts', 'transcription': False}, f)
    with open(os.path.join(HERE, 'timeline.json'), 'w') as f:
        json.dump({'first_seq': FIRST_SEQ, 'fps': 5, 'segments': timeline}, f, indent=1)


def extend():
    """Append the synthetic stretches described in the docstring to the existing captures (idempotent: skips segments already present)."""
    caps = os.path.join(HERE, 'captures')
    timeline_path = os.path.join(HERE, 'timeline.json')
    with open(timeline_path) as f:
        timeline = json.load(f)
    present = {seg['kind'] for seg in timeline['segments']}
    seq = FIRST_SEQ + sum(seg['frames'] for seg in timeline['segments'])

    def write(img):
        nonlocal seq
        cv2.imwrite(os.path.join(caps, f'capture_{seq:09d}.jpg'), img, [cv2.IMWRITE_JPEG_QUALITY, 60])
        seq += 1

    def segment(kind, count):
        timeline['segments'].append({'kind': kind, 'first_seq': seq, 'frames': count})

    if 'frozen' not in present:
        last = cv2.imread(os.path.join(caps, f'capture_{FIRST_SEQ + 599:09d}.jpg'))
        segment('frozen', 40)
        for _ in range(40):
            write(last)
    if 'nosignal' not in present:
        hue = np.tile(np.linspace(0, 60, 320, dtype=np.float32), (180, 1))
        value = np.tile(np.linspace(40, 255, 320, dtype=np.float32), (180, 1))
        nosignal = cv2.cvtColor(np.dstack([hue, np.full_like(hue, 255), value]).astype(np.uint8), cv2.COLOR_HSV2BGR)
        segment('nosignal', 50)
        for _ in range(50):
            write(nosignal)
    # Bridge live + nearblack only when nearblack is missing (old single-shot run).
    if 'nosignal' in present and 'nearblack' not in present:
        segment('live', 40)
        for i in range(40):
            write(cv2.imread(os.path.join(caps, f'capture_{FIRST_SEQ + 500 + i:09d}.jpg')))
    if 'nearblack' not in present:
        near = np.zeros((180, 320, 3), np.uint8)
        near[0:27, :] = 200
        segment('nearblack', 40)
        for _ in range(40):
            write(near)
    # BUG-0661: a dark live scene is not a blackscreen. The 15% strip above makes the
    # preceding segment a dark live scene (lit pixels > 2%). This second stretch keeps
    # the bright area under the 2% limit (1 row out of 180 = ~0.56% lit) so those
    # frames ARE classified as blackscreen — restores the "near-black that IS a
    # blackscreen" case that BUG-0661 removed from the fixture.
    if 'nearblack_bs' not in present:
        near_bs = np.zeros((180, 320, 3), np.uint8)
        near_bs[0:1, :] = 200
        segment('nearblack_bs', 20)
        for _ in range(20):
            write(near_bs)
    with open(timeline_path, 'w') as f:
        json.dump(timeline, f, indent=1)


if __name__ == '__main__':
    if sys.argv[1:] == ['--extend']:
        extend()
    else:
        main(sys.argv[1])
