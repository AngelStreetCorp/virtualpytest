"""Build the follow-up videos from a scene list. Reuses build.py's scene renderers.

Usage: python build2.py <video-key>   (keys defined in VIDEOS below)
"""
import json
import subprocess
import sys
from pathlib import Path

from PIL import Image

import build
from build import (RAW, WORK, OUT, FFMPEG, W, H, card, caption_overlay, still_scene, clip_scene, card_scene, check)

RAW2 = build.HERE / "raw2"
RAW5 = build.HERE / "raw5"
RAW6 = build.HERE / "raw6"
RAW7 = build.HERE / "raw7"
RAW9 = build.HERE / "raw9"
RAW10 = build.HERE / "raw10"
RAW11 = build.HERE / "raw11"
RAW12 = build.HERE / "raw12"
RAW13 = build.HERE / "raw13"
RAW14 = build.HERE / "raw14"
RAW15 = build.HERE / "raw15"
RAW16 = build.HERE / "raw16"
RAW17 = build.HERE / "raw17"
RAW18 = build.HERE / "raw18"
RAW19 = build.HERE / "raw19"
RAW20 = build.HERE / "raw20"
RAW21 = build.HERE / "raw21"
RAW22 = build.HERE / "raw22"
RAW23 = build.HERE / "raw23"
RAW24 = build.HERE / "raw24"
RAW25 = build.HERE / "raw25"


def marks_of(name, root=None):
    p = (root or RAW2) / f"{name}.marks.json"
    if not p.exists():
        return {}
    d = json.load(open(p))
    return {m["label"]: m["t"] for m in d.get("marks", [])}


def _opts(sc):
    """A scene's options dict (clips: 10th field, stills: 7th, cards: 7th, pairs: 6th), empty otherwise."""
    if sc and sc[0] == "clip" and len(sc) > 9: return sc[9]
    if sc and sc[0] == "still": return sc[6]
    if sc and sc[0] == "card" and len(sc) > 6: return sc[6]
    if sc and sc[0] == "pair" and len(sc) > 5: return sc[5]
    return {}


def _src(sc):
    """The recording a clip or pair scene plays from."""
    return sc[4][0][0] if sc[0] == "pair" else sc[4]


def _continues(a, b):
    """b stays on a's page: no fade between them (a hard cut when b skips ahead). Fades are for
    moving to another page. Same recording counts as the same page, unless b carries "page": True
    (it opens another page inside that recording); "cont": True joins b to a across recordings or
    screenshots of the same page (the AI chat)."""
    if not (a and b and a[0] != "card" and b[0] != "card"): return False
    if _opts(b).get("cont"): return True
    return bool(a[0] in ("clip", "pair") and b[0] in ("clip", "pair") and _src(a) == _src(b) and not _opts(b).get("page"))


OPENING_MAX = 3.5   # seconds: viewers drop off on a long still opening
VOICE_PAD = build.HERE / "voice_pad.json"   # {key: {scene number: extra seconds}}, written by voice_fit.py


def render(key, scenes, out_name):
    segs, srt, t = [], [], 0.0
    pad = {int(k): v for k, v in (json.load(open(VOICE_PAD)).get(key, {}) if VOICE_PAD.exists() else {}).items()}
    for i, sc in enumerate(scenes, 1):
        if i == 1 and sc[0] == "card":   # the opening card stays short in every video (owner, 2026-10-06)
            sc = (*sc[:5], min(sc[5], OPENING_MAX), *sc[6:])
        if pad.get(i):   # extra time so the voice-over line fits: cards last longer, clips play slower
            if sc[0] == "card":
                sc = (*sc[:5], sc[5] + pad[i], *sc[6:])
            elif sc[0] == "clip":
                natural = min((sc[6] - sc[5]) / sc[7], sc[8])
                sc = (*sc[:7], sc[7] * natural / (natural + pad[i]), sc[8] + pad[i], *sc[9:])
            elif sc[0] == "pair":
                natural = sum(min((e - s0) / sp, cp) for _, s0, e, sp, cp in sc[4])
                k = natural / (natural + pad[i])
                sc = (*sc[:4], [(src, s0, e, sp * k, cp + pad[i] if j == len(sc[4]) - 1 else cp)
                                for j, (src, s0, e, sp, cp) in enumerate(sc[4])], *sc[5:])
        prev_sc = scenes[i - 2] if i > 1 else None
        next_sc = scenes[i] if i < len(scenes) else None
        seg = WORK / f"{key}_s{i:02d}.mp4"
        kind = sc[0]
        if kind == "card":
            _, big, small, tags, url_, dur = sc[:6]
            png = WORK / f"{key}_card{i}.png"
            card(png, big, small, tags, url=url_, big_size=_opts(sc).get("big_size", 96))
            card_scene(png, dur, seg)
            segs.append(seg); t += dur
            continue
        if kind == "still":
            _, idx, title, caption, src, dur, opts = sc
            opts = dict(opts); opts.pop("cont", None); opts.pop("page", None)
            if _continues(prev_sc, sc): opts["fin"] = 0
            if _continues(sc, next_sc): opts["fout"] = 0
            ov = WORK / f"{key}_ov{i}.png"; caption_overlay(idx, title, caption, ov)
            if "pan_y" in opts and opts["pan_y"] == "auto":
                ih = Image.open(src).height
                opts = {**opts, "pan_y": (0, max(ih - H, 0))}
            still_scene(f"{key}{i}", Path(src), dur, ov, seg, **opts)
            segs.append(seg); srt.append((t + 0.3, t + dur - 0.3, caption)); t += dur
            continue
        if kind == "clip":
            _, idx, title, caption, src, start, end, speed, cap = sc[:9]
            opts = dict(sc[9]) if len(sc) > 9 else {}
            opts.pop("page", None); opts.pop("cont", None); opts.pop("voice", None)
            if _continues(prev_sc, sc): opts["fin"] = 0
            if _continues(sc, next_sc): opts["fout"] = 0
            ov = WORK / f"{key}_ov{i}.png"; caption_overlay(idx, title, caption, ov)
            d = clip_scene(f"{key}{i}", Path(src), start, end, speed, ov, seg, dur_cap=cap, **opts)
            segs.append(seg); srt.append((t + 0.3, t + d - 0.3, caption)); t += d
            continue
        if kind == "pair":
            _, idx, title, caption, parts = sc[:5]
            ov = WORK / f"{key}_ov{i}.png"; caption_overlay(idx, title, caption, ov)
            subs, d = [], 0.0
            for j, (src, start, end, speed, cap) in enumerate(parts):
                o = {}   # the parts of one beat join by hard cuts: no fade inside the scene
                if j == 0 and _continues(prev_sc, sc): o["fin"] = 0
                if j > 0: o["fin"] = 0
                if j < len(parts) - 1: o["fout"] = 0
                if j == len(parts) - 1 and _continues(sc, next_sc): o["fout"] = 0
                sub = WORK / f"{key}_s{i:02d}_p{j}.mp4"
                d += clip_scene(f"{key}{i}p{j}", Path(src), start, end, speed, ov, sub, dur_cap=cap, **o)
                subs.append(sub)
            lst = WORK / f"{key}_s{i:02d}_parts.txt"
            lst.write_text("".join(f"file '{q.as_posix()}'\n" for q in subs), encoding="utf-8")
            check([FFMPEG, "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", seg])
            segs.append(seg); srt.append((t + 0.3, t + d - 0.3, caption)); t += d
            continue
        raise ValueError(kind)
    lst = WORK / f"{key}_concat.txt"
    lst.write_text("".join(f"file '{p.as_posix()}'\n" for p in segs), encoding="utf-8")
    final = OUT / out_name
    check([FFMPEG, "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", "-movflags", "+faststart", final])

    def ts(x):
        h = int(x // 3600); m = int(x % 3600 // 60); s = x % 60
        return f"{h:02d}:{m:02d}:{int(s):02d},{int((s % 1) * 1000):03d}"
    with open(final.with_suffix(".srt"), "w", encoding="utf-8") as f:
        for n, (a, b, c) in enumerate(srt, 1):
            f.write(f"{n}\n{ts(a)} --> {ts(b)}\n{c}\n\n")
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(final)], capture_output=True, text=True)
    print(f"DONE {final} duration={float(r.stdout.strip()):.1f}s size={final.stat().st_size / 1e6:.1f}MB")


def video_navigation():
    m_ed = marks_of("editor"); m_go = marks_of("goto-live")
    ed = RAW2 / "editor.webm"; go = RAW2 / "goto-live.webm"
    return [
        ("card", "Map your app once", "Every screen becomes a node, every transition an edge. Every test reuses it.", ["NAVIGATION TREES"], "virtualpytest.com", 3.6),
        ("clip", 1, "Navigation tree", "The YouTube web app, mapped: home, shorts, search results, video player", ed, max(m_ed.get("loaded", 8) - 0.5, 0), m_ed.get("fit2", 30) + 1.0, 1.6, 9.0),
        ("clip", 2, "Attach a device", "Pick a real device and take control from inside the editor", ed, m_ed.get("fit2", 30) + 1.0, m_ed.get("end", 45), 1.6, 8.0),
        ("clip", 3, "goto video_player", "One command: the path is computed, the clicks happen on a real browser", go, m_go.get("goto-start", 15) + 48.0, m_go.get("goto-done", 170), 8.0, 16.0),
        ("still", 4, "Report", "Every hop is a step with timing, screenshots and the DOM it saw", RAW2 / "report-goto-full.png", 7.0, {"pan_y": "auto"}),
        ("still", 5, "Reuse", "Change a screen once. Every test that crosses it follows.", RAW2 / "editor-tidy.png", 5.0, {"zoom_from": 1.0, "zoom_to": 1.12, "focus": (0.5, 0.5)}),
        ("card", "virtualpytest.com", "Map once. Test everywhere.", "OPEN SOURCE  ·  FREE", "github.com/AngelStreetCorp/virtualpytest", 3.8),
    ]


def video_evidence():
    m_go = marks_of("goto-live"); go = RAW2 / "goto-live.webm"
    return [
        ("card", "Proof, not a checkmark", "Every run leaves evidence you can open: screenshots, video, DOM, timings.", ["EVIDENCE ON EVERY RUN"], "virtualpytest.com", 3.6),
        ("clip", 1, "The run", "A real browser, driven by the navigation tree", go, m_go.get("goto-start", 15) + 50.0, m_go.get("goto-done", 170), 10.0, 10.0),
        ("still", 2, "Before and after", "Initial state, final state and the full execution video, on every report", RAW2 / "report-goto-full.png", 6.0, {"zoom_from": 1.0, "zoom_to": 1.3, "focus": (0.5, 0.2)}),
        ("still", 3, "Step by step", "Each step passes or fails on its own, with its duration", RAW2 / "report-goto-full.png", 6.0, {"zoom_from": 1.25, "zoom_to": 1.35, "focus": (0.5, 0.92)}),
        ("still", 4, "Mosaic", "One frame per step, side by side", RAW2 / "report-goto-mosaic.png", 6.0, {"pan_y": "auto"}),
        ("still", 5, "DOM captures", "The page as the test saw it, captured at every screen", RAW2 / "report-goto-full.png", 5.5, {"zoom_from": 1.3, "zoom_to": 1.4, "focus": (0.35, 0.68)}),
        ("still", 6, "Trends", "Pass rate and run history across the whole team", RAW / "analytics-kpi.png", 5.5, {"zoom_from": 1.0, "zoom_to": 1.12, "focus": (0.5, 0.35)}),
        ("card", "virtualpytest.com", "A frame, not a claim.", "OPEN SOURCE  ·  FREE", "github.com/AngelStreetCorp/virtualpytest", 3.8),
    ]


def video_ai():
    m = marks_of("agent2"); ag = RAW2 / "agent2.webm"
    m4 = marks_of("agent4"); ag4 = RAW2 / "agent4.webm"
    # One page all along (the agent chat), two recordings and screenshots of it: "cont" joins them
    # with no fade. Only the goto report is another page (report_capture.js), so it fades in and out.
    # Each answer gets a hold at normal speed after its sped-up clip, zoomed on the answer
    # (agent2.webm: status answer 121-127 s, act answer 292-298 s, docs answer 345.6-354 s, all static).
    return [
        ("card", "Ask the AI. It acts.", "Docs, scripts and real devices, from one chat. Built-in MCP server.", ["AI-NATIVE"], "virtualpytest.com", 3.6),
        ("clip", 1, "Ask", "Plain English in. Tool calls out.", ag, m["status-sent"] - 5.0, m["status-answer"], 2.2, 9.0),
        ("clip", 1, "Ask", "The answer: every device, its health, its open incidents.", ag, m["status-answer"], m["status-answer"] + 5.0, 1.0, 5.0, {"cont": True, "crop": (80, 180, 1280, 720)}),
        ("clip", 2, "It runs a test", "Pick the device, the script, the parameters. Run it.", ag4, m4["script-sent"] - 3.0, m4["script-answer"] - 12.0, 6.0, 10.0, {"cont": True}),
        ("still", 2, "It runs a test", "And reports back, report link included.", RAW2 / "agent4-script.png", 5.0, {"cont": True, "zoom_from": 1.15, "zoom_to": 1.3, "focus": (0.35, 0.55)}),
        # the report behind that link (another page: fades in and out)
        ("still", 2, "It runs a test", "The goto report: PASS, the screen before and after, the run recorded.", RAW2 / "goto-report-top.png", 5.5, {"zoom_from": 1.1, "zoom_to": 1.3, "focus": (0.35, 0.3)}),
        ("clip", 3, "It acts on the device", "No script this time. It works the screen itself, live on the right.", ag, m["act-sent"] - 3.0, m["act-answer"] - 22.0, 6.0, 12.0),
        ("clip", 3, "It acts on the device", "And answers with what it saw.", ag, m["act-answer"] - 22.0, m["act-answer"], 2.5, 8.0, {"cont": True}),
        ("clip", 3, "It acts on the device", "YouTube loaded, searched, first result read back. Every check: PASS.", ag, m["act-answer"], m["act-answer"] + 5.0, 1.0, 5.0, {"cont": True, "crop": (80, 300, 1280, 720)}),
        ("clip", 4, "It knows the platform", "Ask about the docs. It reads them so you don't have to.", ag, m["docs-sent"] - 3.0, m["docs-answer"], 4.5, 9.0, {"cont": True}),
        ("clip", 4, "It knows the platform", "What counts as a freeze, and where to change the threshold. From the docs.", ag, m["docs-answer"], m["docs-answer"] + 5.0, 1.0, 5.0, {"cont": True, "crop": (80, 300, 1280, 720)}),
        ("still", 5, "MCP", "Every tool call visible. Same tools from Claude, Cursor or your own agent.", RAW2 / "agent2-docs.png", 4.5, {"cont": True, "zoom_from": 1.0, "zoom_to": 1.0}),
        ("card", "virtualpytest.com", "See the screen. Act on it.", "OPEN SOURCE  ·  FREE", "github.com/AngelStreetCorp/virtualpytest", 3.8),
    ]


def video_kpi():
    m_ed = marks_of("editor-kpi", RAW5); ed = RAW5 / "editor-kpi.webm"
    m_go = marks_of("goto-kpi", RAW5); go = RAW5 / "goto-kpi.webm"
    m_rp = marks_of("kpi-report", RAW5); rp = RAW5 / "kpi-report.webm"
    m_tr = marks_of("test-report", RAW5); tr = RAW5 / "test-report.webm"
    return [
        ("card", "Every navigation, timed.", "No performance test to write. Each transition measures itself, from the captured frames.", ["KPI MEASUREMENT"], "virtualpytest.com", 3.6),
        ("clip", 1, "The map", "The YouTube web app, mapped. Every edge is a transition the platform can time.", ed, max(m_ed["loaded"] - 0.5, 0), m_ed["tidy"] + 1.5, 1.3, 6.0),
        ("clip", 2, "Configure", "Open an edge. Say what \"arrived\" looks like: a text or an image the screen must show.", ed, m_ed["edge"] - 1.0, m_ed["kpi-end"], 1.7, 11.0, {"crop": (400, 120, 1520, 855)}),
        # goto-done - 30 s: home; - 16 s: blank; - 13 to - 9.5 s: results; from - 7 s the browser is closed.
        ("clip", 3, "Run", "Run any test that crosses it. The KPI is measured in the background, from the frames.", go, m_go["goto-done"] - 30.0, m_go["goto-done"] - 9.0, 2.4, 10.0),
        # report walk: one continuous recording, so these four join without fades (see _continues)
        ("clip", 4, "The number", "Back on the edge: the average, green under its 3 s budget. Click it.", rp, m_rp["edge"] - 1.0, m_rp["report"] + 0.5, 1.4, 8.0),
        ("clip", 4, "The number", "Frame before, at the action, where the results appeared. The gap is the KPI.", rp, m_rp["report"] + 0.5, m_rp["frames"], 1.0, 9.0),
        ("clip", 5, "Scan mosaic", "Every frame it scanned, in one strip. Open it: the green one is the match.", rp, m_rp["frames"], m_rp["mosaic-close"], 1.0, 10.0),
        ("clip", 6, "The reference", "Further down: what it looked for, where it found it, and the score.", rp, m_rp["mosaic-close"], m_rp["reference"] + 1.5, 1.3, 13.5),
        # dur_cap cuts the tail: keep (end - start) / speed under it so the open mosaic is reached
        ("clip", 7, "Test mosaic", "The test report keeps its own mosaic: one tile per step of the run. Click to expand.", tr, m_tr["mosaic-header"] - 3.0, m_tr["end"], 1.3, 10.5),
        ("card", "virtualpytest.com", "Timed on every run. No extra test. Next: when it does not match, the diff.", "OPEN SOURCE  ·  FREE", "github.com/AngelStreetCorp/virtualpytest", 4.2),
    ]


def video_cmp():
    m_ed = marks_of("editor-cmp", RAW6); ed = RAW6 / "editor-cmp.webm"
    m_go = marks_of("goto-cmp", RAW6); go = RAW6 / "goto-cmp.webm"
    m_rp = marks_of("cmp-report", RAW6); rp = RAW6 / "cmp-report.webm"
    return [
        ("card", "Why did it fail?", "Reference, screen and diff, side by side. One look, not a log.", ["IMAGE COMPARISON"], "virtualpytest.com", 3.6),
        ("clip", 1, "The check", "The results node checks two things: an element, and an image.", ed, m_ed["node"] - 2.5, m_ed["verification"] - 0.5, 1.6, 8.0),
        # zoom on the two verifications while the reference preview is hovered (the dialog does not move)
        ("clip", 1, "The check", "The image check and its reference: the chip row it expects to see.", ed, m_ed["verification"] - 0.5, m_ed["reference"] + 0.3, 0.9, 7.0, {"crop": (520, 410, 700, 394)}),
        # goto-done - 30 s: home; - 12 s: results; the browser closes from about - 8 s
        ("clip", 2, "Run", "Run a goto. It fails at that check, on purpose: the reference was taken on home.", go, m_go["goto-done"] - 30.0, m_go["goto-done"] - 9.0, 2.3, 10.5),
        ("clip", 3, "The report", "The test report: the run failed at step 2. Open the step.", rp, m_rp["report"] - 2.5, m_rp["steps-settled"] + 0.5, 1.8, 10.0),
        # zoom on the opened step (the page is at its bottom, the summary above stays out of frame):
        # the image check scored 65 %, then the click on the comparison link
        ("clip", 3, "The report", "The image check scored 65 %. The comparison is one click away.", rp, m_rp["link"] - 5.5, m_rp["link"] + 0.3, 0.9, 7.0, {"crop": (280, 416, 1180, 664)}),
        # same recording: a cut from the click to the loaded comparison page (its images take a few seconds)
        ("clip", 4, "The comparison", "65 % match, 80 % required. The first, best and last frame it checked.", rp, m_rp["frames"] - 2.0, m_rp["full"], 1.0, 8.0),
        ("clip", 5, "Side by side", "The chips on screen, the chips it expected, and the pixels that differ.", rp, m_rp["full"], m_rp["end"], 1.2, 11.0, {"crop": (1080, 290, 680, 383)}),
        ("card", "virtualpytest.com", "Every failure explains itself. Next: TestRail, Jira and Slack.", "OPEN SOURCE  ·  FREE", "github.com/AngelStreetCorp/virtualpytest", 4.2),
    ]


def video_zap():
    m_z = marks_of("zap", RAW7); z = RAW7 / "zap.webm"
    m_r = marks_of("zapreport", RAW7); r = RAW7 / "zapreport.webm"
    return [
        ("card", "Automatic zap detection", "Zap with the remote. The backend detects and times it. Nothing to code.", ["ZAP DETECTION"], "virtualpytest.com", 3.6),
        # The overlay's ERROR badge (3+ consecutive detections) lights up while monitoring starts and
        # during the zap's own freeze/silence: hard cuts inside the same recording step over it
        # (on at 20.5-25.0 s and 31.0-35.5 s of raw7/zap.webm, re-measure after a new take).
        ("clip", 1, "Live", "A set-top box, live. Turn on monitoring: the backend analyses every frame.", z, m_z["modal"] - 1.0, 20.4, 1.4, 6.5),
        ("clip", 1, "Live", "A set-top box, live. Turn on monitoring: the backend analyses every frame.", z, 25.1, m_z["chup"] - 1.0, 1.0, 3.0),
        ("clip", 2, "Zap", "Zap with the remote. No script, no code: the backend detects it on its own.", z, m_z["chup"] - 1.0, 30.9, 1.0, 4.5),
        ("clip", 2, "Zap", "Zap with the remote. No script, no code: the backend detects it on its own.", z, 35.6, m_z["zap-card"] + 0.5, 1.4, 5.0),
        # zoom on the zap card (bottom right of the player), then the click on its Report link
        ("clip", 2, "Zap", "Detected automatically: itv2 in 2.0 s, 0.4 s of freeze, 0.6 s of silence.", z, m_z["zap-card"] + 0.5, m_z["link"] + 0.5, 1.0, 8.0, {"crop": (1000, 690, 620, 349)}),
        ("clip", 3, "The report", "Its report: the key press, the freeze start and end, the new channel.", r, m_r["report"] - 0.5, m_r["frames"], 1.0, 10.5),
        # zoom on the measurement table
        ("clip", 4, "The numbers", "2.0 s from key press to new content. Measured on every zap, with no code.", r, m_r["frames"], m_r["end"], 1.3, 11.0, {"crop": (15, 370, 900, 506)}),
        ("card", "virtualpytest.com", "Every zap, detected automatically. Next: TestRail, Jira and Slack.", "OPEN SOURCE  ·  FREE", "github.com/AngelStreetCorp/virtualpytest", 4.2),
    ]


def video_mon():
    m = marks_of("mon", RAW9); v = RAW9 / "mon.webm"
    # raw9/mon.webm (take 3, incident stb3 on vpt-pi1 at 22:55:18): the live player runs from about 36 s,
    # "Last 24h" loads at about 75 s, the archive shows "Loading stream..." at every seek and chunk change
    # (84.5-91.5 s, 101-106.5 s): hard cuts step over those. Re-measure after a new take.
    return [
        ("card", "Automatic incident detection", "And a 24 h review buffer on every device. No script to write.", ["24H REVIEW BUFFER"], "virtualpytest.com", 3.6),
        ("clip", 1, "Heatmap", "Every device, a frame a minute, 24 h. Nothing to set up, no test running.", v, m["heatmap"], m["scrubbed"] + 0.5, 1.25, 11.0),
        # zoom on the stb3 tile (top right of the mosaic) while the cursor comes to it
        ("clip", 1, "Heatmap", "22:55: stb3 is stuck on a channel banner. Its tile turns red.", v, m["scrubbed"] + 0.5, m["tile"] + 0.2, 1.0, 4.0, {"crop": (840, 120, 640, 360)}),
        ("clip", 2, "The device", "Click the tile: stb3, live.", v, 40.0, 46.0, 1.0, 6.0),
        ("clip", 3, "Last 24h", "Last 24h: the same screen, recorded all day. Drag back to 22:54.", v, 75.5, 84.3, 1.0, 8.8),
        ("clip", 3, "Last 24h", "There it is: stuck on channel 12. Nothing moves for four and a half minutes.", v, 91.8, 100.8, 1.0, 9.0),
        ("clip", 3, "Last 24h", "Seven minutes later: back on air.", v, 106.8, 112.3, 1.0, 5.5),
        ("clip", 4, "The incident", "No script, no one watching: detected and logged on its own, 4 min 33 s.", v, 121.0, m["expanded"], 1.8, 7.0, {"page": True}),
        # zoom on the expanded row: the frames it compared and the threshold
        ("clip", 4, "The incident", "The frames it compared: diff 0.0, below the 0.5 threshold. A freeze.", v, m["expanded"], m["end"], 1.0, 10.5, {"crop": (395, 380, 760, 428)}),
        ("card", "virtualpytest.com", "Every device watched and recorded. No script. Next: phones.", "OPEN SOURCE  ·  FREE", "github.com/AngelStreetCorp/virtualpytest", 4.2),
    ]


def video_qt():
    m = marks_of("qt", RAW10); v = RAW10 / "qt.webm"
    # raw10/qt.webm: one recording of the QuickTest page, then its report in the same tab (a page change:
    # "page" keeps that fade). Take 4: the key press shows on the HDMI panel at ~57.3 s (channel banner) and
    # the next channel at ~58.7 s; the report is fully loaded ~25 s after the link click. Re-measure after
    # a new take.
    zap = 57.3
    return [
        ("card", "QuickTest Builder", "No code. Just steps: press CH+, check the picture moves.", ["NO CODE"], "virtualpytest.com", 3.6),
        ("clip", 1, "The device", "Pick a set-top box and its interface. Take control: the box, live.", v, m["page"] - 2.0, m["control"] + 1.0, 2.2, 12.0),
        # zoom on the step list while it is built (the device panel is out of frame for these seconds)
        ("clip", 2, "Two steps", "Press CH+. Check the picture moves. That is the whole test.", v, m["control"] + 1.0, m["built"] + 0.5, 1.5, 12.0, {"crop": (500, 100, 1200, 675)}),
        ("clip", 3, "Run", "Run it.", v, m["expanded"] - 1.0, zap - 1.8, 1.0, 6.0),
        # zoom on the enlarged HDMI panel (bottom left) for the zap itself
        ("clip", 3, "Run", "CH+: the box zaps to the next channel, and the backend sees the picture move.", v, zap - 1.8, zap + 3.7, 1.0, 5.5, {"crop": (0, 630, 660, 371)}),
        # zoom on the result panel (top right)
        ("clip", 4, "Passed", "Passed: both steps green, in seconds.", v, zap + 3.7, m["held"], 1.0, 7.0, {"crop": (1300, 80, 660, 371)}),
        ("clip", 5, "The report", "Its report: before and after, each step, the video. Like any other test.", v, m["link"] + 25.0, m["report"], 1.4, 12.0, {"page": True}),
        ("clip", 5, "The report", "Its report: before and after, each step, the video. Like any other test.", v, m["report"], m["end"], 1.0, 7.5),
        ("card", "virtualpytest.com", "QuickTest Builder. No code. Next: phones.", "OPEN SOURCE  ·  FREE", "github.com/AngelStreetCorp/virtualpytest", 4.2),
    ]


def video_game():
    m = marks_of("game", RAW12); v = RAW12 / "game.mp4"
    rm = marks_of("gamereport", RAW12); r = RAW12 / "gamereport.mp4"
    # raw12/game.mp4: one CDP-screencast recording (1280x720 CSS at 1.5x). Device page filtered to the two
    # devices; both runs launch at "launched"; the phone modal opens at "open"; the phone report loads at
    # "page" (a page change, keeps its fade). The grid is cropped: two tiles fill a third of the page.
    grid = (0, 120, 1000, 563)
    return [
        ("card", "Real devices driven by Agentic AI", "2048 game played simultaneously by AI on mobile and web", ["PHONE + WEB", "AGENTIC AI"], "virtualpytest.com", 4.0),
        ("clip", 1, "Two devices", "A phone and a browser. One script, started on both.", v, m["launched"] - 1.0, m["launched"] + 16.0, 2.5, 7.0, {"crop": grid}),
        ("clip", 2, "They play", "Same script, same AI: the game loads, then every move is the model's call.", v, m["launched"] + 16.0, m["open"] - 1.5, 3.5, 8.5, {"crop": grid}),
        ("clip", 3, "The phone, in big", "Click the phone: each swipe is an AI decision, live.", v, m["open"] - 1.5, m["big"], 1.5, 11.0),
        # the report beats come from raw12/gamereport.mp4 (game_capture.js report <phone report>): its summary's
        # Trigger line has the caller's IP removed and the page is zoomed 1.3x. Never cut them from game.mp4.
        ("clip", 4, "The report", "Every move is a step: the model's choice, its reason, the score.", r, rm["report"] - 0.5, rm["report"] + 5.0, 1.0, 5.5, {"page": True}),
        ("clip", 4, "The report", "Every move is a step: the model's choice, its reason, the score.", r, rm["report"] + 5.0, rm["last-step"], 3.0, 5.0),
        ("clip", 5, "The last move", "Its AI call, the swipe, and the board read before and after.", r, rm["last-step"], rm["details"], 1.4, 10.0),
        ("clip", 6, "Proof", "And the screen it played on: the board after the last move.", r, rm["screenshot"] - 1.0, rm["end"], 1.3, 9.0, {"crop": (340, 240, 1244, 700)}),
        ("card", "virtualpytest.com", "One script, any screen. Next: A/V quality, 24 h a day.", "OPEN SOURCE  ·  FREE", "github.com/AngelStreetCorp/virtualpytest", 4.2),
    ]


def video_avq():
    m = marks_of("avq", RAW13); v = RAW13 / "avq.mp4"
    # raw13/avq.mp4 (take 2026-10-04): stb4 on vpt-pi3 live (a match), then the timeline at 07:46:33 (snaps to the
    # 07:45:30 sample: black screen, chips red), then FRAMES stepped through the stills after the picture came back
    # (07:56). The player's second seek ("back") stays black in this take, so the cut goes from the incident to
    # FRAMES. Page beats are cropped to player + metrics + chips: the timeline rows show transcript tooltips
    # under the cursor. Wording (owner): simple checks, simplified MOS. Re-measure after a new take.
    tile = (120, 70, 960, 540)         # the stb4 tile, its icons and the Audio/Video Quality tooltip
    upper = (270, 85, 1380, 776)       # player + metrics panel + chips
    return [
        ("card", "Audio Video Quality", "A/V quality metrics collected for you 24/7, no scripts.", ["A/V QUALITY", "24/7"], "virtualpytest.com", 7.6),
        ("clip", 1, "The device", "A set-top box on the Device page. One click: its A/V quality.", v, m["grid"] - 3.0, m["click"] + 0.3, 1.0, 6.1, {"crop": tile}),
        ("clip", 2, "Live", "Live, all day: a simplified MOS, blur, freeze, black screen, audio level, silence.", v, m["avq"] - 1.0, m["avq"] + 9.0, 1.0, 9.3, {"page": True, "crop": upper}),
        ("clip", 3, "Last 24 h", "The last 24 hours of every check. Click a moment.", v, m["hover"] - 3.4, m["seek"] + 0.4, 1.0, 4.4),
        ("clip", 4, "The incident", "07:45: black screen. No video, no audio, every chip red.", v, m["seek-loaded"], m["back"] - 0.3, 1.0, 8.5, {"crop": upper}),
        ("clip", 5, "Frame by frame", "Frame by frame, the stills it measured: the picture is back, chips green.", v, m["frames"] + 0.5, m["end"] - 1.0, 1.4, 11.0, {"crop": upper, "page": True}),
        ("card", "virtualpytest.com", "Audio Video Quality, 24/7. No scripts.", "OPEN SOURCE  ·  FREE", "github.com/AngelStreetCorp/virtualpytest", 5.9),
    ]

def video_aigen():
    m = marks_of("aigen", RAW14); v = RAW14 / "aigen.mp4"
    g = marks_of("goto", RAW14); gv = RAW14 / "goto.mp4"
    # raw14/aigen.mp4 (take 2026-10-04 16:30): the S21x with Google TV, google-tv-mobile-ai empty (home only);
    # AI Generate -> proposals 30 s, untick the cast picker, Create, validation 8/8, node checks (a screenshot on every
    # node, home included), Save, then the editor's Auto Layout. raw14/goto.mp4: the same map opened fresh, Auto
    # Layout, then library and watchlist: Go To -> Run, the phone gets there ~30 s after Run (app restart, home, tab).
    # The Go To panel keeps "Executing..." after arrival (TASK-40 to look at): the cut leaves it before that matters.
    t0 = m["modal"] - 0.5               # the clock counts from opening AI Generate (the clip's first frame)
    zoom = (0, 60, 1700, 956)           # the phone (bottom left) and the whole modal, a little closer
    return [
        ("card", "AI builds the interface", "Point it at an app. It maps the screens, tests every path, saves the map.", ["AGENTIC AI", "ANDROID"], "virtualpytest.com", 7.4),
        ("clip", 1, "The app", "Google TV on a real phone. An empty map: only home.", v, m["editor"], m["modal"], 3.0, 4.5),
        ("clip", 2, "AI Generate", "One click: the AI reads the app's screens.", v, m["modal"] - 0.5, m["proposals"] + 0.5, 3.5, 9.0, {"badge": True, "clock": 0.0, "crop": zoom}),
        ("clip", 3, "Proposals", "Search, Shop, Library, Watchlist. Untick the cast picker. Create.", v, m["proposals"] + 0.5, m["create"] + 3.0, 1.0, 6.4, {"crop": zoom}),
        ("clip", 4, "Every path, tested", "Each screen opened and left again on the phone, both ways: 8 of 8.", v, m["click-start-validation"] - 1.0, m["click-review-node-verifications"], 10.0, 14.0, {"badge": True, "clock": m["click-start-validation"] - 1.0 - t0, "crop": zoom}),
        ("clip", 5, "Saved", "A check and a screenshot for each screen, then Save.", v, m["click-review-node-verifications"], m["click-confirm-save"] + 1.0, 2.0, 7.0, {"crop": zoom}),
        ("clip", 5, "Saved", "Auto Layout: the map the AI built, every screen with its picture.", gv, g["layout"] - 4.0, g["node-library"] - 0.5, 1.0, 5.9, {"page": True}),
        ("clip", 6, "Use it", "Click a screen, Go To: the path comes from the map.", gv, g["node-library"] - 0.5, g["run-library"] + 1.0, 1.0, 7.0),
        ("clip", 6, "Use it", "The phone goes there: the app restarts, home, then Library.", gv, g["run-library"] + 1.0, g["run-library"] + 32.0, 4.0, 7.8, {"badge": True, "clock": 1.0}),
        ("clip", 7, "Again", "Watchlist: one click, and the phone follows the map.", gv, g["node-watchlist"] - 0.5, g["run-watchlist"] + 32.0, 5.0, 8.0, {"badge": True, "clock": 0.0}),
        ("card", "virtualpytest.com", "Point the AI at an app: it maps it, tests it, and the map is ready to use.", "OPEN SOURCE  ·  FREE", "github.com/AngelStreetCorp/virtualpytest", 6.2),
    ]

def video_nipogi():
    m = marks_of("nipogi", RAW15); v = RAW15 / "nipogi.mp4"
    # raw15/nipogi.mp4 (take 2026-10-04): rpitest Device page with the 24 vpt-nipogi streams (Target: search the host,
    # Select all, done off camera), scrolled; then Clear + search-and-tick four. Right after Clear the page shows
    # every device on the server (~17-22 s: other hosts, third-party posters): the cut jumps over it to Device (1).
    # Then Tears of Steel opened in HD, then its A/V quality page. Sizing line = owner's estimate (2026-10-04).
    pick = m["few"] - 25.0                  # Device (1) onwards, after the Clear (re-measure after a new take)
    return [
        ("card", "24 streams, one host", "Every stream watched 24/7: picture, sound, quality. On one small host.", ["STREAM MONITORING", "24/7"], "virtualpytest.com", 10.5),
        ("clip", 1, "One host, 24 streams", "24 live streams, all on one host: HLS from Apple, Mux, THEO, Shaka...", v, m["grid"], m["scrolled"] + 2.0, 1.0, 10.0),
        ("clip", 2, "Pick some", "Search, tick: four of them side by side.", v, pick, m["few"] + 1.0, 2.6, 10.0, {"crop": (120, 60, 1440, 810)}),
        ("clip", 3, "Open one", "Open one: Tears of Steel, live, in HD.", v, m["stream"] - 9.0, m["stream"], 1.0, 9.0, {"page": True}),
        ("clip", 4, "Its quality", "Its A/V quality, measured all the time: MOS, freeze, black screen, sound.", v, m["avq-click"], m["end"], 1.0, 13.0, {"page": True, "crop": (270, 85, 1380, 776)}),
        ("card", "300 channels ≈ 30 hosts", "Quality, audio and subtitle checks, 24/7: about 6-8 k of hardware.", ["SIZING"], "virtualpytest.com", 6.7),
        ("card", "virtualpytest.com", "Test your streams before they reach a device. Open source.", "OPEN SOURCE  ·  FREE", "github.com/AngelStreetCorp/virtualpytest", 4.2),
    ]


def video_atlas():
    m = marks_of("atlas", RAW16); v = RAW16 / "atlas.mp4"
    # raw16/atlas.mp4 (take 2026-10-04, deployed site, RPI1-server so the device names are neutral): four questions to
    # Atlas (MiniMax), each answered in 10-24 s with an analytics panel. Answers are fast-forwarded x1.6-2 with the
    # typing; zoomed on the chat column and its panel.
    z = (280, 110, 1600, 900)
    return [
        ("card", "Ask your data", "Plain questions, real numbers: the same data and definitions as Grafana.", ["ATLAS AI", "ANALYTICS"], "virtualpytest.com", 6.5),
        ("clip", 1, "Pass rate", "Compare pass rate by device: the chart, the run counts, what stands out.", v, m["ask-1"] - 2.0, m["answer-1"] + 4.0, 1.8, 10.0, {"crop": z}),
        ("clip", 2, "KPI radar", "The KPI radar of a set-top box interface: base against a variant, every transition.", v, m["ask-2"] - 1.0, m["answer-2"] + 4.0, 2.0, 11.0, {"crop": z}),
        ("clip", 3, "Regressions", "Only the regressions over 10 %: what got slower, and by how much.", v, m["ask-3"] - 1.0, m["answer-3"] + 5.0, 2.0, 11.0, {"crop": z}),
        ("clip", 4, "A canvas", "One sentence, three panels for two boxes: pass rate, KPI averages, incidents.", v, m["ask-4"] - 1.0, m["end"], 2.2, 13.0, {"crop": z}),
        ("card", "virtualpytest.com", "Ask Atlas. Export to CSV, PNG, or a Grafana draft. Open source.", "OPEN SOURCE  ·  FREE", "github.com/AngelStreetCorp/virtualpytest", 7.1),
    ]


def video_tpzap():
    m = marks_of("tpz", RAW17); v = RAW17 / "tpz.mp4"
    # raw17/tpz.mp4 (retake 2026-10-04 22:40, after BUG-0363): Test Prompt on stb3 (vpt-pi1), box first tuned to an
    # HD channel. Fresh prompt "Live zap check", Run graph: the AI compiles home -> live -> (CHANNEL_UP + motion
    # check) x3, the box zaps (a western, South Park, MTV...), Passed; Save as testcase; Run again: "Replays ...", no
    # AI call, Passed. The box's home screen (operator UI) is blurred whole during Entry -> home (~77-84 s and
    # ~180-187 s). The false-pass take is kept as raw17/tpz_falsepass.mp4. Re-measure after a new take.
    panel = (0, 660, 1320, 420)                                  # the enlarged stream panel, bottom left (redesigned page)
    hide = [(*panel, 64.5, 75.5), (*panel, 159.5, 169.5)]   # box home screen (operator UI) in run 1 and run 2
    return [
        ("card", "AI Test Prompting", "Use natural language to generate a test, save and replay without AI.", ["TEST PROMPT", "AGENTIC AI"], "virtualpytest.com", 7.0),
        ("clip", 1, "The sentence", "A new prompt: go to live TV, zap 3 times, check the picture moves.", v, m["stream"], m["typed"] + 1.0, 2.5, 9.0),
        ("clip", 2, "The AI writes it", "Run: the AI writes the test — three zaps, a motion check after each.", v, m["run-1"] - 0.5, m["compiled"] + 6.0, 3.0, 9.5, {"badge": True, "clock": 0.0, "blur": hide}),
        ("clip", 2, "The AI writes it", "Each zap, a new channel; each time the picture is checked for motion.", v, m["compiled"] + 6.0, m["passed-1"] + 1.5, 3.0, 13.5, {"badge": True, "clock": m["compiled"] + 6.0 - m["run-1"] + 0.5}),
        ("clip", 3, "Save", "Passed. Save: it is a testcase now.", v, m["save-click"] - 3.0, m["saved"] + 1.0, 1.6, 8.0),
        ("clip", 4, "Again, no AI", "Run it again: it replays the saved test. No AI call.", v, m["run-2"] - 0.5, m["passed-2"] + 1.5, 6.0, 12.5, {"badge": True, "clock": 0.0, "blur": hide}),
        ("clip", 5, "Same steps, every time", "Passed. Replayed testcase: the same steps on every run.", v, m["details"] - 1.0, m["released"], 1.0, 5.9),
        ("card", "virtualpytest.com", "Generate a test in natural language. Save it, replay it without AI.", "OPEN SOURCE  ·  FREE", "github.com/AngelStreetCorp/virtualpytest", 5.3),
    ]

def video_cicd():
    m = marks_of("cicd", RAW11); v = RAW11 / "cicd.mp4"
    crm = marks_of("creport", RAW11); cr = RAW11 / "creport.mp4"   # campaign_report_capture.js: report, rows expanded, a test report, its log (keys and IPs masked)
    # raw11/cicd.mp4 (take 2026-10-04, cicd_capture.js, main site): Build Campaign "Smoke: youtube-web" (goto
    # youtube-web home, superping, dns_lookuptime) on host-clone-1; the real API call (raw11/curl.txt, key as
    # $VPT_API_KEY) rendered as raw11/curl_card.png; Monitor Tests: the run appears, runs ~62 s, history row expanded
    # (3 PASS), then the campaign report. The first ~2 s of Build Campaign show other campaigns: the cut starts after.
    page = (240, 50, 1440, 810)           # the page content, centered: zoom on it
    low = (240, 280, 1440, 810)           # the run history (lower on the page) with the expanded PASS rows
    return [
        ("card", "Create and run a campaign", "Pick your tests, save, run. The results come back on their own.", ["CAMPAIGNS"], "virtualpytest.com", 6.6),
        ("clip", 1, "A campaign", "Name it, pick the tests, save.", v, m["build"] + 2.5, m["saved"] + 1.5, 2.0, 11.0, {"crop": page}),
        ("clip", 2, "Run it", "Run it: the tests start straight away.", v, m["run-visible"] - 1.0, m["done"], 6.0, 8.0, {"crop": page, "badge": True}),
        ("clip", 3, "All green", "Done: every test passed.", v, m["history"], m["report"] - 0.5, 1.0, 9.0, {"crop": low}),
        ("clip", 4, "The report", "One report for the whole campaign, every test in it.", cr, crm["report"], crm["expanded"] + 1.0, 1.3, 7.0, {"page": True}),
        ("clip", 5, "Each test", "Open any test: its own report, screenshots and video.", cr, crm["script-report"] - 3.0, crm["script-report"] + 2.5, 1.0, 5.5, {"page": True}),
        ("clip", 6, "Its log", "And its full log.", cr, crm["script-logs"] - 3.0, crm["end"], 1.0, 4.7, {"page": True}),
        ("card", "virtualpytest.com", "Build a campaign in seconds, run it anytime.", "OPEN SOURCE  ·  FREE", "github.com/AngelStreetCorp/virtualpytest", 4.2),
    ]


def video_vscript():
    m = marks_of("vscript", RAW18); v = RAW18 / "vscript.mp4"
    # raw18/vscript.mp4 (take 2026-10-05, vscript_capture.js, RPI1-server): Virtual Scripts builder, new script
    # smoke_goto_live, goto_live pasted, Save, target stb3 (vpt-pi1) / stb_tv, Control, Run -> Passed (~14 s),
    # release, report (summary, mosaic). stb3 was already on live TV: no operator home screen anywhere, no blur.
    end = m["end"] - 1.2
    return [
        ("card", "Write a script in the browser", "Paste a test, save it, run it on a real device. Nothing to install.", ["VIRTUAL SCRIPTS"], "virtualpytest.com", 7.7),
        ("clip", 1, "A new script", "A new script, named smoke_goto_live.", v, m["new-script"] - 0.5, m["named"] + 1.0, 1.0, 5.5),
        ("clip", 2, "Paste and save", "Paste the code — here, go to live TV — and save.", v, m["named"] + 1.0, m["saved"] + 1.5, 1.6, 7.5),
        ("clip", 3, "Pick a device", "Pick a set-top box and its interface.", v, m["target"] - 3.5, m["control"] + 1.0, 1.0, 5.0),
        ("clip", 4, "Run it", "Run: the box is driven live, right there.", v, m["run"] - 0.5, m["passed"] + 2.0, 1.4, 12.5, {"badge": True}),
        ("clip", 5, "The report", "Passed. Its report: before and after, the video, every step.", v, m["report"] - 0.5, end, 1.0, 13.0, {"page": True}),
        ("card", "virtualpytest.com", "Write it, save it, run it. All in the browser.", "OPEN SOURCE  ·  FREE", "github.com/AngelStreetCorp/virtualpytest", 4.2),
    ]


def video_grafana():
    m = marks_of("grafana", RAW20); v = RAW20 / "grafana.mp4"
    # raw20/grafana.mp4 (retake 2026-10-05 10:08, grafana_capture.js, main site, after BUG-0405/0410): Atlas, Target
    # host-clone-1, "Build a canvas for my selected devices: pass rate by device, duration trend and incidents over the
    # last 7 days" (MiniMax, ~17 s); the canvas note "Limited to your selected device host-clone-1_Host"; its "Open in
    # Grafana" draft link followed: the draft opens with Host host-clone-1 / Device host-clone-1_Host preset, two
    # tooltips. The page change leaves a black gap (~45.8-47.3 s): the Grafana clip starts after it. First take
    # (prompt naming host-clone-1, old scope note) kept as raw20/grafana_v1.*, the Host=All one as grafana_v2.*.
    g0 = m["open-click"] + 2.9
    return [
        ("card", "From a question to a Grafana dashboard", "Ask Atlas in one sentence. Open the result in Grafana.", ["ATLAS AI", "GRAFANA"], "virtualpytest.com", 7.3),
        ("clip", 1, "Ask", "Pick a device, ask for a canvas in one sentence.", v, m["page"] + 1.0, m["ask"] + 0.5, 2.0, 7.5),
        ("clip", 2, "The canvas", "Atlas queries the data and draws three panels: pass rate, duration, incidents.", v, m["ask"] + 0.5, m["canvas"] - 1.5, 2.0, 9.0, {"badge": True}),
        ("clip", 3, "Open in Grafana", "One click: the same panels as a Grafana draft.", v, m["canvas"] - 1.5, m["open-click"] + 0.6, 1.0, 4.0),
        ("clip", 4, "A real dashboard", "A real Grafana dashboard, already filtered to the device. Edit it, keep it, share it.", v, g0, m["end"], 1.4, 13.0, {"page": True}),
        ("card", "virtualpytest.com", "Ask a question, get a dashboard. Open source.", "OPEN SOURCE  ·  FREE", "github.com/AngelStreetCorp/virtualpytest", 4.2),
    ]


def video_mcp():
    m = marks_of("mcp", RAW19); v = RAW19 / "mcp.mp4"
    # raw19/mcp.mp4 (take 2026-10-05 11:54, mcp_capture.js, main site, after BUG-0411/0413/0414): left the device
    # modal of host-clone-1 (YouTube in Chromium), right a ttyd terminal running Claude Code with the VirtualPyTest MCP
    # server. Five prompts: devices, open search results, back home, what's on screen, verify home. Claude Code prints
    # the account's usage limit at ~41-48.5 s: the cut starts after it, on the ready prompt.
    s0 = m["claude-ready"] - 7.0
    return [
        ("card", "Your AI drives real devices", "Claude Code, connected to VirtualPyTest over MCP.", ["MCP", "CLAUDE CODE"], "virtualpytest.com", 7.4),
        ("clip", 1, "Which devices?", "Claude Code with the VirtualPyTest MCP server: which devices can you use?", v, s0, m["answered-1"] + 2.0, 2.0, 12.5),
        ("clip", 2, "Open a page", "Open YouTube's search results: navigate_to_node, the browser follows.", v, m["answered-1"] + 2.0, m["answered-2"] + 1.5, 2.5, 14.5, {"badge": True}),
        ("clip", 3, "Back home", "Now go to the home page: the path comes from the interface's map.", v, m["answered-2"] + 1.5, m["answered-3"] + 1.5, 2.0, 11.5, {"badge": True}),
        ("clip", 4, "What's on screen?", "What's on the screen now? It takes a screenshot and describes it.", v, m["answered-3"] + 1.5, m["answered-4"] + 1.5, 1.6, 9.5, {"badge": True}),
        ("clip", 5, "Verify", "Verify we are on home: verify_node runs the node's check. Passed.", v, m["answered-4"] + 1.5, m["end"], 1.5, 10.0, {"badge": True}),
        ("card", "virtualpytest.com", "Plug your AI into real devices with MCP. Open source.", "OPEN SOURCE  ·  FREE", "github.com/AngelStreetCorp/virtualpytest", 4.8),
    ]


def video_whatsnew():
    m = marks_of("whatsnew", RAW22); v = RAW22 / "whatsnew.mp4"
    g = marks_of("grafana", RAW20); gv = RAW20 / "grafana.mp4"   # video 20's take: Atlas canvas -> Grafana draft
    a = marks_of("analytics", RAW22); av = RAW22 / "analytics.mp4"   # analytics_capture.js: the Analytics page tabs
    # raw22/whatsnew.mp4 (take 2026-10-05, whatsnew_capture.js, main site): restyled pages (Run Tests, Coverage,
    # Virtual Scripts, Test Reports), Settings -> dark theme, French, German, back; a passed goto report (host-clone-1,
    # youtube-web) in FR then DE; its Share icon -> Share dialog -> Create link; the snapshot opened from the link;
    # Shared links tab -> Revoke -> Confirm revoke. Host IPs / version stamps blanked, failed rows hidden as they render.
    return [
        ("card", "What's new in VirtualPyTest", "A new look, your language, shareable reports, AI analytics.", ["NEW", "UI", "EN · FR · DE", "ANALYTICS"], "virtualpytest.com", 7.1),
        ("clip", 1, "A new look", "A glow-up: one clean style on every page, from Run Tests to Coverage and Reports.", v, m["tour-tests"] - 0.5, m["dash-again"], 1.8, 11.0),
        ("clip", 2, "Your language", "Light or dark, and the app in English, French or German. One click.", v, m["menu"] - 1.0, m["back-en"], 1.7, 11.0),
        ("clip", 3, "Reports too", "Test reports switch language too: Français, Deutsch.", v, m["report"] - 0.8, m["report-de"] + 2.0, 1.25, 11.0, {"page": True}),
        ("clip", 4, "Share it", "Share a report as a link: it expires, with a password if you want.", v, m["share-click"] - 1.0, m["created"] + 2.5, 1.3, 11.0, {"page": True}),
        ("clip", 5, "A snapshot", "Anyone with the link sees the report, screenshots and video. No account needed.", v, m["created"] + 2.5, m["snapshot"] + 0.3, 0.7, 8.5, {"page": True}),
        ("clip", 6, "Revoke it", "One click revokes the link: the copy is deleted at once.", v, m["links"] - 1.0, m["end"], 1.5, 10.5, {"page": True}),
        ("clip", 7, "Analytics", "Analytics, tab by tab: the fleet, devices, test KPIs, alerts, even the project itself.", av, 0.0, a["end"], 2.3, 12.0, {"page": True}),
        ("clip", 8, "Ask your data", "Analytics: ask Atlas for a canvas in one sentence, for the device you picked.", gv, g["ask"] - 3.0, g["canvas"] - 1.0, 2.5, 9.0, {"page": True}),
        ("clip", 9, "In Grafana", "One click: the same panels as a Grafana dashboard, already filtered to the device.", gv, g["open-click"] + 2.9, g["end"], 1.6, 9.0, {"page": True}),
        ("card", "virtualpytest.com", "A new look, three languages, shareable reports, AI analytics. Open source.", "OPEN SOURCE  ·  FREE", "github.com/AngelStreetCorp/virtualpytest", 8.0),
    ]


def video_subqa():
    m = marks_of("subqa", RAW21); v = RAW21 / "subqa.mp4"
    # raw21/subqa.mp4 (take 2026-10-05, subqa_capture.js, main site on the RPI1 server): Run Tests, vpt-pi4 local
    # video device, subtitle_qa on a 2:25 cut of Tears of Steel (CC BY 3.0, Blender Foundation) with its English
    # subtitle track burnt in; the stream tile (enlarged by CSS) shows the film until ~242 s, then the page collapses it
    # while the run finishes (~357 s, passed); run report -> subtitle report (2 of 34 cues flagged: 2 late, 1 wrong text;
    # "not counted" = OCR misreads checked against the source file; cue timing). The report's text is small at 1080p:
    # its beats are cropped to the report column. Initial-state thumbnail = Big Buck Bunny (CC BY, the idle source).
    p0 = m["playing"] + 7.0
    rep = (40, 0, 1480, 810)          # the report column, 1.33x
    return [
        ("card", "Automatic Subtitle Analysis", "Compare the subtitles a device displays against a provided source.", ["SUBTITLES", "END TO END"], "virtualpytest.com", 5.9),
        ("clip", 1, "Pick and run", "Pick the device under test and the subtitle analysis, then Run.", v, m["page"] + 1.0, m["run"] + 1.5, 4.0, 10.5),
        ("clip", 2, "The device plays", "The device displays the programme and its subtitles, exactly as a viewer sees them.", v, m["playing"] - 1.0, p0, 1.0, 8.0),
        ("clip", 2, "The device plays", "Each subtitle on screen is read and compared with the provided subtitle source.", v, p0, 241.0, 16.0, 12.0, {"badge": True}),
        ("clip", 3, "The report", "Done: 274 frames read, none missed. The subtitle report opens.", v, m["report"] - 0.5, m["subreport"] + 1.0, 1.6, 8.0, {"page": True}),
        ("clip", 4, "Cue by cue", "2 of 34 subtitles flagged, each with the frames that show it.", v, m["subreport"] + 1.0, 390.5, 1.6, 9.0, {"page": True, "crop": rep}),
        ("clip", 5, "Not the device", "A reading error? Checked against the source, not blamed on the device.", v, 391.5, 398.0, 1.0, 7.0, {"crop": rep}),
        ("card", "virtualpytest.com", "Film: Tears of Steel, (CC) Blender Foundation, mango.blender.org", "OPEN SOURCE  ·  FREE", "github.com/AngelStreetCorp/virtualpytest", 7.2),
    ]


def video_localize():
    m = marks_of("localize", RAW23); v = RAW23 / "localize.mp4"
    # raw23/localize.mp4 (take 2026-10-05, localize_capture.js, main site): Navigation Editor of sauce-demo (6 screens)
    # on host-clone-1; Localize -> home 100% (5 of 6 excluded); Go To cart -> Localize -> cart 100%; cart's Edit Node
    # dialog: "fingerprint" pill, Verifications EMPTY (no image/text reference); off camera (78.4-90.9) the browser is
    # sent to example.com; Localize -> "No confident match" (6 of 6 excluded); Go To home -> home 100%.
    # Owner wording: the two terms "Localize" and "Fingerprint" are named and explained; image/text references are
    # no longer required (the Fingerprint is computed from the screenshot on its own).
    dlg = (400, 95, 1520, 725)        # the Edit Node dialog, 1.7x
    f0 = m["fingerprint"] - 4.0; f1 = m["fingerprint"] + 1.0
    return [
        ("card", "Localize your screen with Fingerprint", "Which screen is the device on? One click tells you.", ["LOCALIZE", "FINGERPRINT"], "virtualpytest.com", 6.0),
        ("clip", 1, "The map", "An app's map: six screens. Which one is the device on right now?", v, m["editor"] + 0.5, m["control"] + 1.0, 1.2, 7.5),
        ("clip", 2, "Localize", "Localize: one click names the screen. Home, 100%, the other five ruled out.", v, m["localize-1"] - 3.0, m["localize-1"] + 4.0, 1.0, 7.0),
        ("clip", 3, "Localize again", "Go To cart: the browser moves. Localize again: cart.", v, m["goto"] - 1.0, m["localize-2"] + 4.0, 2.0, 11.0, {"badge": True}),
        ("clip", 4, "Fingerprint", "Fingerprint: a visual signature, made on its own from each screen's screenshot.", v, f0, f1, 0.75, 6.9, {"crop": dlg}),
        ("clip", 5, "No references", "No image or text reference on this screen. The Fingerprint alone recognised it.", v, f1, m["cut-start"], 0.65, 6.0, {"crop": dlg}),
        ("card", "Why references are not needed", "It compares the whole screen, its key areas and its title.", ["AUTOMATIC"], "virtualpytest.com", 4.5),
        ("clip", 6, "Not on the map", "A page that is not on the map? Localize says no confident match. It never guesses.", v, m["offmap"] - 1.5, m["offmap"] + 5.0, 1.0, 6.5, {"page": True}),
        ("clip", 7, "Why it matters", "Exploring an app, an AI can tell a new screen from one it already knows.", v, m["back-home"] - 1.0, m["end"], 1.0, 9.0),
        ("card", "virtualpytest.com", "Localize your screen with Fingerprint. No references to maintain.", "OPEN SOURCE  ·  FREE", "github.com/AngelStreetCorp/virtualpytest", 6.0),
    ]


def video_consoles():
    sm = marks_of("switch", RAW24); sv = RAW24 / "switch.mp4"
    fm = marks_of("firetv", RAW24); fv = RAW24 / "firetv.mp4"
    # raw24/switch.mp4 (retake 2026-10-06, dark mode, switch_capture.js, RPI1-server): switch1 on vpt-pi3, Bluetooth Pro
    # Controller via vpt-procon; Take Control -> Home menu -> Xenoverse 2 (logos ~38-82 s, then its intro animation
    # 82-104.5 s: Trunks, Goku vs Raditz) -> Super Kirby Clash village -> A presses advance an NPC dialogue (155-182 s).
    # raw24/firetv.mp4 (retake 2026-10-06, dark mode, firetv_capture.js): FireTv on Vega OS (Fire TV was already
    # supported; Vega OS is the new part) via adb; Take Control with YouTube already focused -> YouTube -> Search
    # (typed via input_text) -> "Big Buck Bunny 60fps 4K - Official Blender Foundation" (CC BY) plays.
    return [
        ("card", "Now compatible", "Nintendo Switch, and Fire TV on its new system: Vega OS.", ["NINTENDO SWITCH", "FIRE TV VEGA OS"], "virtualpytest.com", 7.2),
        ("clip", 1, "Nintendo Switch", "A Nintendo Switch: take control, VirtualPyTest is the controller.", sv, sm["page"] + 0.5, sm["home"], 2.4, 8.0),
        ("clip", 2, "The Home menu", "The Home menu: move between the games.", sv, sm["home"], sm["xeno-launch"], 3.0, 6.0),
        ("clip", 3, "Launch a game", "Launch a game: Dragon Ball Xenoverse 2.", sv, sm["xeno-launch"], sm["xeno-anim"], 6.0, 7.5, {"badge": True}),
        ("clip", 3, "Launch a game", "Its intro plays, live from the console.", sv, sm["xeno-anim"], sm["xeno-end"], 1.7, 13.5),
        ("clip", 4, "Another game", "Switch to another game: Super Kirby Clash.", sv, sm["xeno-end"], sm["kirby-a"], 6.0, 8.5, {"badge": True}),
        ("clip", 5, "In the game", "Press A: the game answers, inside the game too.", sv, sm["kirby-a"], sm["kirby-end"], 2.6, 10.5),
        ("clip", 6, "Fire TV Vega OS", "Fire TV already worked. Now its new system too: Vega OS. Here is the remote.", fv, fm["control"] - 1.0, fm["youtube"] + 1.5, 1.0, 8.0, {"page": True}),
        ("clip", 7, "Search", "Into YouTube: search and pick a video.", fv, fm["youtube"] + 1.5, fm["video-start"], 10.0, 7.5, {"badge": True}),
        ("clip", 8, "It plays", "Big Buck Bunny plays: the Fire TV is driven like any viewer would.", fv, fm["video-start"], fm["playing"] + 1.0, 1.8, 8.5),
        ("card", "virtualpytest.com", "Consoles, TV sticks, set-top boxes, phones, web. Open source.", "OPEN SOURCE  ·  FREE", "github.com/AngelStreetCorp/virtualpytest", 6.6),
    ]


def video_layouts():
    # Storyboard 25a (validated 2026-10-12). Each beat's menu pick and hold are two cut parts of one recording
    # ("pair"): [menu mark, picked = the option click] then [loaded, hold end + 0.5]; the tile wait between them is cut.
    m = marks_of("layouts", RAW25); v = RAW25 / "layouts.mp4"
    return [
        ("card", "Device view showing from 1 to 48 devices", "New layouts on the Device page", ["DEVICE PAGE", "VIEW MENU"], None, 3.5,
         {"voice": "New in VirtualPyTest: the Device view shows from one to forty-eight devices.", "big_size": 80}),
        ("clip", 1, "24 per page", "24 live streams, one page", v, m["beat1-loaded"], m["beat1-grid24"] + 0.5, 1.0, 4.5,
         {"voice": "The Device page shows twenty-four live streams at once."}),
        ("pair", 2, "12 per page", "12 per page: bigger tiles", [
            (v, m["beat2-menu"], m["beat2-picked"], 1.0, 12.0),
            (v, m["beat2-loaded"], m["beat2-grid12"] + 0.5, 1.0, 6.0)],
         {"voice": "Open the View menu and pick twelve per page for bigger tiles."}),
        ("pair", 3, "48 per page", "48 per page, scroll for more", [
            (v, m["beat3-menu"], m["beat3-picked"] - 0.6, 1.0, 12.0),   # cut before the 48-tile reload shows
            (v, m["beat3-loaded"], m["beat3-48"] + 0.5, 1.0, 10.0)],
         {"voice": "Or forty-eight per page, and scroll through the rest of the fleet."}),
        ("pair", 4, "Side by side", "Side by side", [
            (v, m["beat4-menu"], m["beat4-picked"], 1.0, 12.0),
            (v, m["beat4-loaded"], m["beat4-side"] + 0.5, 1.0, 6.0)],
         {"voice": "Side by side puts two streams next to each other."}),
        ("pair", 5, "Grid 2×2", "Grid 2×2: four at once", [
            (v, m["beat5-menu"], m["beat5-picked"], 1.0, 12.0),
            (v, m["beat5-loaded"], m["beat5-grid2x2"] + 0.5, 1.0, 6.0)],
         {"voice": "The two-by-two grid watches four at once."}),
        ("pair", 6, "One full", "One full: one stream, whole page", [
            (v, m["beat6-menu"], m["beat6-picked"], 1.0, 12.0),
            (v, m["beat6-loaded"], m["beat6-one"] + 0.5, 1.0, 6.0)],
         {"voice": "One full gives a single stream the whole page."}),
        ("pair", 7, "One full", "Click to open it in big", [
            (v, m["beat7-click"], m["beat7-open"] + 0.5, 1.0, 10.0),
            (v, m["beat7-loaded"], m["beat7-end"] + 0.5, 1.0, 8.0)],
         {"voice": "Click it to open the stream in big."}),
        ("pair", 8, "One full", "Close it: back to your layout", [
            (v, m["beat8-click"], m["beat8-closed"] + 0.5, 1.0, 10.0),
            (v, m["beat8-loaded"], m["beat8-end"] + 0.5, 1.0, 8.0)],
         {"voice": "Close it, and you are back to your layout."}),
        ("card", "virtualpytest.com", "Open source", "OPEN SOURCE  ·  FREE", "github.com/AngelStreetCorp/virtualpytest", 4.0,
         {"voice": "VirtualPyTest is open source, at virtualpytest dot com."}),
    ]


def video_group():
    # Storyboard 25b v5 (validated 2026-10-12). Each beat: the action (sped up) then the hold, cut parts of one recording.
    m = marks_of("group", RAW25); v = RAW25 / "group.mp4"
    return [
        ("card", "Group control: one remote, two phones", "Drive several devices at once from the Device page", ["DEVICE PAGE", "GROUP CONTROL"], None, 3.5,
         {"voice": "Group control: one remote drives two phones at once.", "big_size": 80}),
        ("clip", 1, "Device page", "Two phones, live", v, m["beat1-start"], m["beat1-end"], 1.0, 3.5,
         {"voice": "Two Android phones, live on the Device page."}),
        ("pair", 2, "Group control", "Turn on group control", [
            (v, m["beat2-action"], m["beat2-loaded"], 2.0, 4.0),
            (v, m["beat2-loaded"], m["beat2-end"] + 0.5, 1.0, 4.0)],
         {"voice": "Turn on group control."}),
        ("pair", 3, "Pick the phones", "Pick the phones to drive", [
            (v, m["beat3-S21x-action"], m["beat3-loaded"], 2.0, 6.0),
            (v, m["beat3-loaded"], m["beat3-end"] + 0.5, 1.0, 4.0)],
         {"voice": "Pick the phones to drive: the S21 and the S7."}),
        ("pair", 4, "One remote", "One remote for the group", [
            (v, m["beat4-action"], m["beat4-loaded"], 2.0, 6.0),
            (v, m["beat4-loaded"], m["beat4-end"] + 0.5, 1.0, 4.0)],
         {"voice": "One remote for the whole group."}),
        ("pair", 5, "Home", "Home: both move", [
            (v, m["beat5-action"], m["beat5-loaded"], 1.5, 5.0),
            (v, m["beat5-loaded"], m["beat5-end"] + 0.5, 1.0, 4.0)],
         {"voice": "Press Home, and both phones move together."}),
        ("pair", 6, "Chrome", "Open Chrome on both", [
            (v, m["beat6-action"], m["beat6-loaded"], 2.0, 6.0),
            (v, m["beat6-loaded"], m["beat6-end"] + 0.5, 1.0, 5.0)],
         {"voice": "Open Chrome on both phones at once."}),
        ("pair", 7, "virtualpytest.com", "Type once, both phones get it", [
            (v, m["beat7-action"], m["beat7-entered"] + 0.8, 1.5, 8.0),
            (v, m["beat7-loaded"], m["beat7-end"] + 0.5, 1.0, 6.0)],
         {"voice": "Type the address once: both phones get it."}),
        ("pair", 8, "Scroll", "Scroll both at once", [
            (v, m["beat8-1-action"], m["beat8-1-end"] + 0.5, 1.0, 6.0),
            (v, m["beat8-2-action"], m["beat8-2-end"] + 0.5, 1.0, 6.0)],
         {"voice": "Scroll down, and both pages follow."}),
        ("pair", 9, "Release", "Release them in one click", [
            (v, m["beat9-action"], m["beat9-loaded"], 2.0, 6.0),
            (v, m["beat9-loaded"], m["beat9-end"] + 0.5, 1.0, 4.0)],
         {"voice": "Back home, and release both in one click."}),
        ("card", "virtualpytest.com", "Open source", "OPEN SOURCE  ·  FREE", None, 4.0,
         {"voice": "VirtualPyTest is open source, at virtualpytest dot com."}),
    ]

VIDEOS = {
    "group": (video_group, "virtualpytest_25b_group.mp4"),
    "navigation": (video_navigation, "virtualpytest_02_navigation_tree.mp4"),
    "evidence": (video_evidence, "virtualpytest_03_evidence.mp4"),
    "ai": (video_ai, "virtualpytest_04_ai_agent.mp4"),
    "kpi": (video_kpi, "virtualpytest_05_kpi.mp4"),
    "cmp": (video_cmp, "virtualpytest_06_comparison.mp4"),
    "zap": (video_zap, "virtualpytest_07_zap.mp4"),
    "mon": (video_mon, "virtualpytest_09_monitoring.mp4"),
    "qt": (video_qt, "virtualpytest_10_quicktest.mp4"),
    "game": (video_game, "virtualpytest_12_2048.mp4"),
    "avq": (video_avq, "virtualpytest_13_avq.mp4"),
    "aigen": (video_aigen, "virtualpytest_14_ai_interface.mp4"),
    "nipogi": (video_nipogi, "virtualpytest_15_streams.mp4"),
    "atlas": (video_atlas, "virtualpytest_16_atlas_analytics.mp4"),
    "tpzap": (video_tpzap, "virtualpytest_17_test_prompt.mp4"),
    "cicd": (video_cicd, "virtualpytest_11_campaign.mp4"),
    "vscript": (video_vscript, "virtualpytest_18_virtual_script.mp4"),
    "mcp": (video_mcp, "virtualpytest_19_mcp_claude_code.mp4"),
    "consoles": (video_consoles, "virtualpytest_24_switch_firetv.mp4"),
    "localize": (video_localize, "virtualpytest_23_fingerprint.mp4"),
    "subqa": (video_subqa, "virtualpytest_21_subtitle_qa.mp4"),
    "whatsnew": (video_whatsnew, "virtualpytest_22_whats_new.mp4"),
    "grafana": (video_grafana, "virtualpytest_20_atlas_grafana.mp4"),
    "layouts": (video_layouts, "virtualpytest_25a_layouts.mp4"),
}

if __name__ == "__main__":
    key = sys.argv[1]
    fn, name = VIDEOS[key]
    render(key, fn(), name)
