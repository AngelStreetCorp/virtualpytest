"""Video timeline for a test run (TASK-94): the whole execution video as one contact sheet.

A 3-minute or 10-minute test video becomes ONE compressed JPEG (about 100 tiles, one per N seconds,
each labelled with its time, a coloured bar under it for the step running at that moment) plus a
self-contained `timeline.html` (the sheet inline, the video player, a clickable step list). A reader
sees what happened without playing the video; a click on a tile or a step jumps the player there.

Built from the LOCAL video before it is cleaned up, in one ffmpeg pass. Never raises: any problem
returns None and the report is generated without a timeline.
"""

import base64
import html
import json
import math
import os
import shutil
import subprocess
import tempfile
from typing import Dict, List, Optional

MAX_TILES = 100
NICE_STEPS = (1, 2, 3, 5, 6, 10, 15, 30, 60)
TILE_W = 192
JPEG_QUALITY = 60
COLS = 10
GAP = 4
MARGIN = 8
LABEL_H = 16
BAR_H = 5

_OK = (34, 139, 34)
_KO = (200, 40, 40)
_NONE = (70, 70, 76)
_BG = (24, 24, 28)
_TXT = (235, 235, 235)


def pick_step(duration_s: float, max_tiles: int = MAX_TILES) -> int:
    """Smallest 'nice' seconds-per-tile that keeps the sheet within `max_tiles` (3 min -> 2 s, 10 min -> 6 s)."""
    need = max(1.0, duration_s / float(max_tiles))
    for step in NICE_STEPS:
        if step >= need:
            return step
    return int(math.ceil(need / 60.0) * 60)


def _probe_duration(path: str) -> float:
    r = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', path],
                       capture_output=True, text=True, timeout=30)
    return float(r.stdout.strip())


def _fmt(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 60}:{s % 60:02d}" if s < 3600 else f"{s // 3600}:{(s % 3600) // 60:02d}:{s % 60:02d}"


def steps_for_video(step_results: List[Dict], video_start_epoch: float) -> List[Dict]:
    """[{number, start, end, ok, label}] in video seconds. A step's `timestamp` is when it was recorded (its
    end); `execution_time_ms` its length. Steps with no usable timing are left out."""
    out = []
    if not video_start_epoch:
        return out
    for i, st in enumerate(step_results or []):
        ts, ms = st.get('timestamp'), st.get('execution_time_ms')
        if not isinstance(ts, (int, float)) or not isinstance(ms, (int, float)):
            continue
        end = ts - video_start_epoch
        start = end - ms / 1000.0
        label = (st.get('message') or '').strip()
        if not label and st.get('from_node') and st.get('to_node'):
            label = f"{st['from_node']} → {st['to_node']}"
        out.append({'number': st.get('step_number', i + 1), 'start': max(0.0, start), 'end': max(0.0, end),
                    'ok': bool(st.get('success', False)), 'label': label})
    return out


def _step_at(steps: List[Dict], t: float) -> Optional[Dict]:
    for st in steps:
        if st['start'] <= t < max(st['end'], st['start'] + 0.001):
            return st
    return None


def _load_font(size: int):
    from PIL import ImageFont
    for name in ('DejaVuSans-Bold.ttf', 'DejaVuSans.ttf', 'Arial.ttf', 'Helvetica.ttc'):
        try:
            return ImageFont.truetype(name, size)
        except Exception:
            continue
    try:
        return ImageFont.load_default(size=size)
    except Exception:
        return ImageFont.load_default()


def build_video_timeline(video_path: str, output_path: str, steps: Optional[List[Dict]] = None,
                         tile_w: int = TILE_W, quality: int = JPEG_QUALITY) -> Optional[Dict]:
    """Write the contact sheet JPEG to `output_path`; return its geometry (needed to map a click to a time)
    or None when there is no video, no ffmpeg or no Pillow."""
    try:
        from PIL import Image, ImageDraw
    except Exception as e:
        print(f"[@report_timeline] Pillow unavailable, skipping timeline: {e}")
        return None
    if not video_path or not os.path.isfile(video_path) or not shutil.which('ffmpeg'):
        return None
    tmp = tempfile.mkdtemp(prefix='vpt_timeline_')
    try:
        duration = _probe_duration(video_path)
        if duration < 1:
            return None
        step = pick_step(duration)
        count = int(duration // step) + 1
        r = subprocess.run(
            ['ffmpeg', '-v', 'error', '-y', '-an', '-i', video_path,
             '-vf', f'fps=1/{step}:round=down,scale={tile_w}:-2:flags=fast_bilinear', '-q:v', '5',
             os.path.join(tmp, 't_%04d.jpg')],
            capture_output=True, text=True, timeout=180)
        frames = sorted(f for f in os.listdir(tmp) if f.endswith('.jpg'))
        if r.returncode != 0 or not frames:
            print(f"[@report_timeline] ffmpeg failed: {r.stderr.strip()[-200:]}")
            return None
        frames = frames[:count]
        with Image.open(os.path.join(tmp, frames[0])) as probe:
            tile_h = probe.height
        cols = min(COLS, len(frames))
        rows = (len(frames) + cols - 1) // cols
        cell_w, cell_h = tile_w, tile_h + BAR_H + LABEL_H
        width = MARGIN * 2 + cols * cell_w + (cols - 1) * GAP
        height = MARGIN * 2 + rows * cell_h + (rows - 1) * GAP
        canvas = Image.new('RGB', (width, height), _BG)
        draw = ImageDraw.Draw(canvas)
        font, small = _load_font(12), _load_font(11)
        steps = steps or []
        seen_first = set()
        for i, name in enumerate(frames):
            x = MARGIN + (i % cols) * (cell_w + GAP)
            y = MARGIN + (i // cols) * (cell_h + GAP)
            t = i * step
            with Image.open(os.path.join(tmp, name)) as img:
                canvas.paste(img.convert('RGB'), (x, y))
            st = _step_at(steps, t)
            bar = _NONE if st is None else (_OK if st['ok'] else _KO)
            draw.rectangle([x, y + tile_h, x + cell_w - 1, y + tile_h + BAR_H - 1], fill=bar)
            draw.text((x + 3, y + tile_h + BAR_H + 1), _fmt(t), fill=_TXT, font=small)
            if st is not None and st['number'] not in seen_first:
                seen_first.add(st['number'])
                badge = str(st['number'])
                w = int(draw.textlength(badge, font=font)) + 8
                draw.rectangle([x, y, x + w, y + 16], fill=bar)
                draw.text((x + 4, y + 1), badge, fill=(255, 255, 255), font=font)
        os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)
        canvas.save(output_path, 'JPEG', quality=quality, optimize=True, progressive=True)
        size = os.path.getsize(output_path)
        print(f"[@report_timeline] {len(frames)} tiles ({step}s each) {width}x{height} -> {output_path} ({size // 1024} KB)")
        return {'path': output_path, 'width': width, 'height': height, 'tiles': len(frames), 'cols': cols,
                'rows': rows, 'step_s': step, 'duration_s': round(duration, 1), 'cell_w': cell_w,
                'cell_h': cell_h, 'margin': MARGIN, 'gap': GAP, 'bytes': size, 'steps': steps}
    except Exception as e:
        print(f"[@report_timeline] Failed to build timeline: {e}")
        return None
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


_HTML = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
:root{--bg:#1a1a1a;--card:#242424;--text:#f0f0f0;--mut:#9a9a9a;--line:#383838;--acc:#d4a574;--ok:#22c55e;--ko:#ef4444}
@media (prefers-color-scheme: light){:root{--bg:#f2f0ec;--card:#fff;--text:#1f1f1f;--mut:#5a5a5a;--line:#d8d4cc;--acc:#a8742f;--ok:#15803d;--ko:#dc2626}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:14px/1.4 system-ui,sans-serif;padding:16px;max-width:1500px;margin:auto}
h1{font-size:1.3rem;margin:0 0 4px}.sub{color:var(--mut);margin-bottom:12px}
.card{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:12px;margin-bottom:12px}
video{width:100%;max-height:340px;background:#000;border-radius:6px;display:block}
#sheet{width:100%;height:auto;display:block;cursor:pointer;border-radius:4px}
.hint{color:var(--mut);font-size:12px;margin-top:6px}
.row{display:flex;gap:12px;align-items:center;justify-content:space-between;flex-wrap:wrap}.row .sub{margin:0}
button{background:transparent;color:var(--mut);border:1px solid var(--line);border-radius:6px;padding:4px 12px;font:inherit;cursor:pointer}
#pcard{display:none}#pcard.on{display:block}
.steps{list-style:none;margin:0;padding:0}.steps li{display:flex;gap:10px;padding:5px 0;border-bottom:1px solid var(--line);cursor:pointer}
.steps li:last-child{border:0}.t{font-variant-numeric:tabular-nums;color:var(--mut);min-width:48px}
.ok{color:var(--ok);font-weight:600}.ko{color:var(--ko);font-weight:600}
</style></head><body>
<h1>__TITLE__</h1><div class="row"><div class="sub" id="sub"></div><button id="ptoggle" type="button"></button></div>
<div class="card"><img id="sheet" alt="" src="data:image/jpeg;base64,__IMG__"><div class="hint" id="hint"></div></div>
__VIDEO__
<div class="card"><ul class="steps" id="steps"></ul></div>
<script>
var G=__GEOM__, STR=__STRINGS__, steps=G.steps||[];
function fmt(s){s=Math.floor(s);return Math.floor(s/60)+':'+('0'+s%60).slice(-2)}
var lang=(location.hash.match(/lang=(\\w+)/)||[])[1]||(function(){try{return localStorage.getItem('virtualpytest:language')}catch(e){return null}})()||'en';
var S=STR[lang]||STR.en; function tt(k){return S[k]||STR.en[k]||k}
document.documentElement.lang=lang;
document.getElementById('sub').textContent=fmt(G.duration_s)+' · '+G.tiles+' × '+G.step_s+' s';
document.getElementById('hint').textContent=tt('timeline.hint');
var v=document.getElementById('player'),pc=document.getElementById('pcard'),pt=document.getElementById('ptoggle');
function pref(){try{return localStorage.getItem('virtualpytest:timeline-player')==='1'}catch(e){return false}}
function setPlayer(on,save){if(!pc)return;pc.classList.toggle('on',on);pt.textContent=tt(on?'timeline.hide_player':'timeline.show_player');if(!on&&v)v.pause();if(save){try{localStorage.setItem('virtualpytest:timeline-player',on?'1':'0')}catch(e){}}}
if(pc){pt.onclick=function(){setPlayer(!pc.classList.contains('on'),true)};setPlayer(pref(),false)}else{pt.style.display='none'}
function seek(t){if(!v)return;setPlayer(true,false);v.currentTime=t;v.play().catch(function(){});pc.scrollIntoView({block:'nearest'})}
document.getElementById('sheet').onclick=function(e){
 var r=this.getBoundingClientRect(),k=this.naturalWidth/r.width,x=(e.clientX-r.left)*k,y=(e.clientY-r.top)*k;
 var c=Math.floor((x-G.margin)/(G.cell_w+G.gap)),rw=Math.floor((y-G.margin)/(G.cell_h+G.gap));
 if(c<0||rw<0||c>=G.cols)return;var i=rw*G.cols+c;if(i>=G.tiles)return;seek(i*G.step_s)};
var ul=document.getElementById('steps');
if(!steps.length){ul.parentNode.style.display='none'}
steps.forEach(function(s){var li=document.createElement('li');
 li.innerHTML='<span class="t">'+fmt(s.start)+'</span><span class="'+(s.ok?'ok':'ko')+'">'+tt(s.ok?'timeline.ok':'timeline.fail')+'</span><span>'+s.number+' '+(s.label||'').replace(/</g,'&lt;')+'</span>';
 li.onclick=function(){seek(s.start)};ul.appendChild(li)});
</script></body></html>
"""


def build_timeline_html(info: Dict, video_url: str, title: str, strings: Dict[str, Dict[str, str]]) -> str:
    """Self-contained page: the sheet inline (base64), the player on `video_url`, a clickable step list."""
    with open(info['path'], 'rb') as fh:
        img_b64 = base64.b64encode(fh.read()).decode('ascii')
    geom = {k: info[k] for k in ('tiles', 'cols', 'rows', 'step_s', 'cell_w', 'cell_h', 'margin', 'gap', 'duration_s')}
    geom['steps'] = [{'number': s['number'], 'start': round(s['start'], 1), 'ok': s['ok'], 'label': s['label']}
                     for s in info.get('steps', [])]
    video = (f'<div class="card" id="pcard"><video id="player" controls preload="metadata" src="{html.escape(video_url, quote=True)}"></video></div>'
             if video_url else '')
    page = (_HTML.replace('__TITLE__', html.escape(title)).replace('__VIDEO__', video).replace('__IMG__', img_b64)
            .replace('__GEOM__', json.dumps(geom).replace('</', '<\\/'))
            .replace('__STRINGS__', json.dumps(strings, ensure_ascii=False).replace('</', '<\\/')))
    return page


def timeline_strings() -> Dict[str, Dict[str, str]]:
    """{lang: {timeline.* key: text}} from the platform report files (en/fr/de)."""
    from ..i18n.report_i18n import load_platform_strings
    return {code: {k: v for k, v in strs.items() if k.startswith('timeline.')}
            for code, strs in load_platform_strings().items()}
