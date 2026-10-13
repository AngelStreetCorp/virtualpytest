"""Fit the voice-over to a video: re-voice, read the spills, give each spilling scene that much extra time
(voice_pad.json, read by build2.render), rebuild, repeat until no line spills. Scene text and marks are untouched.

Usage: python3 voice_fit.py <key> [<key> ...]
"""
import json
import re
import subprocess
import sys
from pathlib import Path

PAD = Path(__file__).with_name("voice_pad.json")


def run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True).stdout


for key in sys.argv[1:]:
    for rnd in range(6):
        out = run([sys.executable, "voiceover.py", key])
        spills = [(int(n), float(x)) for n, x in re.findall(r"~ scene (\d+): spills ([\d.]+)s", out)]
        done = re.search(r"DONE (\S+) ([\d.]+)s", out)
        if not spills:
            print(f"{key}: ok after {rnd} round(s), {done.group(2) if done else '?'} s"); break
        pads = json.loads(PAD.read_text()) if PAD.exists() else {}
        kp = pads.setdefault(key, {})
        for n, x in spills:
            kp[str(n)] = round(kp.get(str(n), 0) + x + 0.25, 2)
        PAD.write_text(json.dumps(pads, indent=1, sort_keys=True))
        print(f"{key}: round {rnd + 1}: padding {spills}")
        run([sys.executable, "build2.py", key])
    else:
        print(f"{key}: still spilling after 6 rounds")
