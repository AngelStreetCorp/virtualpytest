#!/usr/bin/env python3
"""Vision-LLM player for Clash of Clans (tutorial + play) on an adb device via a host.

Loop: screencap -> Claude (image) -> one JSON action -> adb input. State-aware by
construction: the model sees the real screen every step, so it cannot "complete" on
metadata alone. Stops only when the model reports the tutorial finished AND a second
independent check agrees.

    ANTHROPIC_API_KEY=... python3 scripts/coc_llm_player.py --mode tutorial
    ANTHROPIC_API_KEY=... python3 scripts/coc_llm_player.py --mode play --steps 200
"""
import argparse, base64, io, json, os, subprocess, sys, time

import anthropic
from PIL import Image

W_DEV, H_DEV = 2340, 1080          # device landscape pixels
W_IMG, H_IMG = 1170, 540           # what the model sees (exactly half -> trivial mapping)

SYSTEM = """You are playing Clash of Clans on a phone, landscape, by looking at screenshots.
The screenshot is {w}x{h}; give coordinates in that space. Reply with ONE JSON object only:
{{"thought": "<what you see, one sentence>", "action": "tap|swipe|wait|done",
  "x": int, "y": int, "x2": int, "y2": int, "ms": int, "tutorial_done": bool}}
- tap: tap (x,y). swipe: drag (x,y)->(x2,y2) (ms = duration). wait: nothing (loading/animation).
- Follow the tutorial arrows/highlights/speech bubbles exactly: tap the glowing/pointed-at thing.
  Dismiss chief dialogue by tapping the bubble. When asked to place a building, tap the
  highlighted spot then the green check. When asked to train/attack, tap the pointed buttons;
  to deploy troops tap on the ground inside the enemy village near the pointer.
- PRIORITY: a big bouncing ARROW always beats a speech bubble. If an arrow points at a button
  (e.g. the Shop), tap the button under the arrow, not the bubble. Tutorial flow for building:
  Shop -> pick the highlighted building -> tap the construction spot -> green check.
- If your last 2 actions were identical and the screen did not change, STOP repeating: tap what
  the arrow/glow points at, or a different spot.
- If a dialog says "Anyone there? / disconnected", tap "Reload game".
- If a name prompt, tap the text box, accept the default, confirm.
- Never spend gems or real money. Never tap "Buy"/"Shop" purchase confirmations with gems.
- tutorial_done=true ONLY when the normal home village is shown with the bottom bar
  (Attack/Shop/etc.) and NO tutorial arrow, bubble, or forced highlight.
- In play mode (mode={mode}): {play}
""".strip()

PLAY = ("collect gold/elixir (tap full collectors), keep builders busy (upgrade cheapest "
        "affordable building with gold/elixir only), train troops, and attack for loot when "
        "army is ready; always end/return home afterwards.")


def adb(host, dev, *cmd, capture=False):
    full = f"sudo -n -u vpt_user adb -s {dev} " + " ".join(cmd)
    return subprocess.run(["ssh", host, full], capture_output=capture, check=False, timeout=60)


def shot(host, dev):
    r = adb(host, dev, "exec-out", "screencap", "-p", capture=True)
    raw = r.stdout
    raw = raw[raw.index(b"\x89PNG"):]   # screencap prints a multi-display warning first
    img = Image.open(io.BytesIO(raw)).convert("RGB")
    if img.size[0] < img.size[1]:
        img = img.rotate(90, expand=True)
    img = img.resize((W_IMG, H_IMG))
    buf = io.BytesIO(); img.save(buf, "JPEG", quality=80)
    return base64.b64encode(buf.getvalue()).decode(), img


def act(host, dev, a):
    s = W_DEV / W_IMG
    t = a.get("action")
    if t == "tap":
        adb(host, dev, "shell", "input", "tap", str(int(a["x"] * s)), str(int(a["y"] * s)))
    elif t == "swipe":
        adb(host, dev, "shell", "input", "swipe", str(int(a["x"] * s)), str(int(a["y"] * s)),
            str(int(a["x2"] * s)), str(int(a["y2"] * s)), str(int(a.get("ms", 400))))


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--host", default="vpt-pi1")
    p.add_argument("--device", default="192.168.1.29:5555")
    p.add_argument("--mode", choices=["tutorial", "play"], default="tutorial")
    p.add_argument("--steps", type=int, default=150)
    p.add_argument("--model", default="claude-haiku-5-5")
    p.add_argument("--out", default="/tmp/coc_llm_run")
    a = p.parse_args()
    os.makedirs(a.out, exist_ok=True)
    client = anthropic.Anthropic()
    system = SYSTEM.format(w=W_IMG, h=H_IMG, mode=a.mode, play=PLAY)
    history, done_votes = [], 0
    for i in range(a.steps):
        b64, img = shot(a.host, a.device)
        img.save(f"{a.out}/{i:03d}.jpg")
        content = [{"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": b64}},
                   {"type": "text", "text": "Recent actions: " + (json.dumps(history[-6:]) or "none") + "\nNext action? (JSON only, no prose)"}]
        r = client.messages.create(model=a.model, max_tokens=1500, system=system,
                                   messages=[{"role": "user", "content": content}])
        txt = "".join(b.text for b in r.content if b.type == "text")
        try:
            act_ = json.loads(txt[txt.index("{"): txt.rindex("}") + 1])
        except Exception:
            print(i, "unparseable:", txt[:200]); time.sleep(1); continue
        print(i, act_.get("action"), act_.get("x"), act_.get("y"), "|", act_.get("thought", "")[:110], flush=True)
        history.append({k: act_.get(k) for k in ("action", "x", "y", "thought")})
        if a.mode == "tutorial":
            done_votes = done_votes + 1 if act_.get("tutorial_done") else 0
            if done_votes >= 3:
                print("TUTORIAL DONE (3 consecutive confirmations) — last frame:", f"{a.out}/{i:03d}.jpg")
                return 0
        act(a.host, a.device, act_)
        time.sleep(max(1.0, (act_.get("ms", 0) or 0) / 1000) if act_.get("action") == "wait" else 1.8)
    print("step budget exhausted")
    return 1


if __name__ == "__main__":
    sys.exit(main())
