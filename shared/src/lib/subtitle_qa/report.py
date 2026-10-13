"""Self-contained HTML report (images inlined as base64).

Laid out for someone who reads it to decide: verdict and numbers first, then the issues grouped by cue
(each group expandable), the error mosaic (one tile per problem cue, same tiles as the platform's step
mosaic), the count per issue type, the timeline, and only then the full sample list (collapsed, filterable).
Collapsible blocks are <details> elements, so they work without JavaScript."""
import base64
import html
from collections import Counter, OrderedDict
from typing import Dict, List, Optional, Sequence

import cv2

from ..utils.report_theme import report_theme_head
from .judge import ISSUE_TYPES

ISSUE_HELP = {
    'missing_subtitle': 'A cue is active but no subtitle text is on screen.',
    'unexpected_subtitle': 'Subtitle text is on screen where no cue is defined.',
    'stuck_subtitle': 'A finished cue is still on screen, or an old cue shows over a new one.',
    'wrong_text': 'Text differs from the cue (character error rate above 20%).',
    'truncated_line': 'Only the start or end of the expected line is shown.',
    'late_cue': 'The cue appears later than the speech (or the SRT) by more than the tolerance.',
    'early_cue': 'The cue appears earlier than the speech (or the SRT) by more than the tolerance.',
    'wrong_language': 'The subtitle text is in another language than the track.',
    'overlap': 'Two cues are on screen at the same time.',
    'unreadable_contrast': 'Text is on screen but its contrast against the background is below 3:1.',
}
GLOSSARY = [
    ('cue', 'Cue', 'One subtitle line from the SRT file: a text with a start time and an end time. Cue 4 is the 4th line of the file.'),
    ('srt', 'SRT', 'The subtitle file used as the truth: what should be on screen, and when.'),
    ('track', 'Subtitle track', 'The subtitles stored inside the video file (.mkv), one per language. The device draws the chosen track onto the picture.'),
    ('sample', 'Sample', 'One frame taken from the video at a planned moment and checked. There are more samples around the moments a cue starts or ends, fewer elsewhere.'),
    ('ocr', 'OCR', 'Optical character recognition: software (here tesseract) that reads the text in the picture.'),
    ('cer', 'CER', 'Character error rate: how different the text read on screen is from the expected cue, as the number of characters to add, remove or change divided by the length of the cue. 0% = identical; above 20% the text is counted as wrong.'),
    ('conf', 'Confidence (conf)', 'How sure OCR is about the words it read, 0 to 100. Words under 25 are dropped.'),
    ('contrast', 'Contrast', 'How much the text stands out from what is right around it (WCAG ratio). Below 3:1 the subtitle is hard to read.'),
    ('band', 'Subtitle band', 'The lower part of the frame where subtitles are drawn; only this part is read by OCR. The issue list shows it enlarged.'),
    ('edge', 'Cue edge', 'The moment a cue starts or ends. Within a short window around it (1 s on a device) both "shown" and "not shown" are accepted, because the capture is not exact to the frame.'),
    ('expect', 'Expect: present / absent / boundary', 'What should be on screen at that sample: a subtitle (present), nothing (absent), or either (boundary = near a cue edge).'),
    ('first-seen', 'First seen', 'The first sample in which the cue text was read correctly.'),
    ('lag-srt', 'Lag vs SRT', 'First seen minus the start time written in the SRT. Positive = shown late.'),
    ('lag-speech', 'Lag vs speech', 'First seen minus the moment the words are spoken, from the audio transcript. Positive = shown after the actor speaks.'),
    ('transcript', 'Audio transcript', 'The film soundtrack turned into timed words by speech recognition (faster-whisper). Used to check that a cue appears when its words are spoken.'),
    ('noise', 'OCR noise', 'A bad read in one frame of a cue that other frames of the same cue read correctly. Not counted as an issue.'),
    ('source-check', 'Source check', 'Each flagged sample is read again from the original video file at the same moment, where the subtitle is clean. If the file fails the same way, the problem is our OCR (OCR limit), not the device.'),
    ('ocr-limit', 'OCR limit', 'The original file fails the same way as the device: OCR cannot read this subtitle well. Not counted as a device issue.'),
    ('picture-text', 'Picture text', 'Text that is part of the film image (titles, credits, signs), not a subtitle.'),
    ('mosaic', 'Error mosaic', 'One picture per cue that has an issue, side by side, to see all problems at a glance.'),
    ('issue-types', 'Issue types', 'missing_subtitle, wrong_text, late_cue and the others: each one is explained in the "Issues per type" table above.'),
    ('tesseract', 'tesseract, psm 6', 'tesseract is the open-source OCR engine used here; "psm 6" tells it to read the band as one block of text lines.'),
    ('libass', 'libass', 'The library that draws subtitles onto the video picture (used by ffmpeg and most players). The device and the source check both use it.'),
    ('alignment', 'Alignment', 'Whether the report knows which second of the film each frame shows. If it does not, every check is off and the report says so at the top.'),
]
GLOSSARY_LINKS = {'CER': 'cer', 'OCR': 'ocr', 'cue': 'cue', 'cues': 'cue', 'SRT': 'srt', 'samples': 'sample', 'contrast': 'contrast',
                  'conf': 'conf', 'speech': 'lag-speech', 'mosaic': 'mosaic'}


def glossary_html() -> str:
    items = ''.join(f'<dt id="g-{k}">{html.escape(term)}</dt><dd>{html.escape(text)}</dd>' for k, term, text in GLOSSARY)
    return f'<details open id="glossary"><summary><h2>Glossary</h2></summary><dl class="gloss">{items}</dl></details>'


def gl(word: str, key: str = '') -> str:
    """A technical word linked to its glossary entry."""
    return f'<a class="gl" href="#g-{key or GLOSSARY_LINKS.get(word, word.lower())}">{html.escape(word)}</a>'


COLORS = {'ok': 'var(--vpt-success)', 'issue': 'var(--vpt-error)', 'boundary': 'var(--vpt-text-2)'}


def thumb_b64(img, width: int = 420, quality: int = 55) -> str:
    h, w = img.shape[:2]
    small = cv2.resize(img, (width, int(h * width / w)), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode('.jpg', small, [cv2.IMWRITE_JPEG_QUALITY, quality])
    return base64.b64encode(buf).decode() if ok else ''


def band_b64(img, width: int = 520, quality: int = 70) -> str:
    """The subtitle band (same ROI as the OCR), larger, so a reader can check what was on screen."""
    from .ocr import roi_crop
    crop, _ = roi_crop(img)
    h, w = crop.shape[:2]
    small = cv2.resize(crop, (width, int(h * width / w)), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode('.jpg', small, [cv2.IMWRITE_JPEG_QUALITY, quality])
    return base64.b64encode(buf).decode() if ok else ''


def _n(v, spec: str = '.2f') -> str:
    return '' if v is None else format(v, spec)


def _t(sec: float) -> str:
    return f'{int(sec // 60):d}:{sec % 60:05.2f}'


def row_issues(r: Dict) -> List[str]:
    v = r['verdict']
    return ([v['issue']] if v['issue'] else []) + [f for f in v['flags'] if f != v['issue']]


def issue_groups(rows: List[Dict], timings: List[Dict], cues: Sequence) -> 'OrderedDict':
    """Problems grouped by cue, in film order. Key = cue index, or ('t', time) for text outside any cue.
    Each group: {'cue', 'start', 'issues': Counter, 'rows': [sample rows with an issue], 'timing': timing or None}."""
    by_index = {c.index: c for c in cues}
    groups: Dict = {}

    def group(key, start, cue=None):
        return groups.setdefault(key, {'cue': cue, 'start': start, 'issues': Counter(), 'rows': [], 'timing': None})

    for r in rows:
        its = row_issues(r)
        if not its:
            continue
        idx = r['verdict']['matched_cue']
        if idx is None:  # pick the cue active at that time, if any
            active = [c for c in cues if c.start <= r['t'] <= c.end]
            idx = active[0].index if active else None
        g = group(idx, by_index[idx].start, by_index[idx]) if idx in by_index else group(('t', r['t']), r['t'])
        g['issues'].update(its)
        g['rows'].append(r)
    for t in timings:
        if t['issue'] and t['cue'] in by_index:
            g = group(t['cue'], by_index[t['cue']].start, by_index[t['cue']])
            g['issues'][t['issue']] += 1
            g['timing'] = t
    return OrderedDict(sorted(groups.items(), key=lambda kv: kv[1]['start']))


def _sample_row(i: int, r: Dict, e) -> str:
    v = r['verdict']
    issues = row_issues(r)
    cls = 'bad' if issues else ('edge' if v['state'] == 'boundary' else 'ok')
    cer_s = '' if v['cer'] is None else f'{v["cer"] * 100:.0f}%'
    detail = ''.join([
        f'CER {cer_s}' if cer_s else '',
        f' · missing: {e(" ".join(v["missing_words"]))}' if v['missing_words'] else '',
        f' · extra: {e(" ".join(v["extra_words"]))}' if v['extra_words'] else '',
    ])
    return (
        f'<tr id="s{i}" class="{cls}" data-i="{" ".join(issues) or "ok"}"><td>{i}<br>{_t(r["t"])}<br><small>{e(r["reason"])}</small></td>'
        f'<td><img loading="lazy" src="data:image/jpeg;base64,{r["thumb"]}"></td>'
        f'<td>{e(r["ocr"] or "—")}<br><small>{gl("conf")} {r["conf"]:.0f} · {gl("contrast")} {_n(r["contrast"], ".1f")} · lang {r["lang"] or "?"}</small></td>'
        f'<td>{e(r["expected"] or ("(none)" if v["state"] == "absent" else "—"))}<br><small>{gl("expect", "expect")}: {v["state"]}</small></td>'
        f'<td>{e(r["audio"] or "—")}</td>'
        f'<td><b>{"OK" if not issues else "ISSUE"}</b><br>{e(", ".join(issues))}<br><small>{detail}<br>{e(v["note"])}</small></td></tr>')


def render(meta: Dict, rows: List[Dict], timings: List[Dict], cues: Sequence, duration: float,
           mosaic_b64: Optional[str] = None) -> str:
    e = html.escape
    m = meta
    counts = Counter()
    for r in rows:
        counts.update(row_issues(r))
    for tm in timings:
        if tm['issue']:
            counts[tm['issue']] += 1
    groups = issue_groups(rows, timings, cues)
    pos = {id(r): i for i, r in enumerate(rows)}
    n_issue_samples = sum(1 for r in rows if row_issues(r))
    n_timing = sum(1 for t in timings if t['issue'])
    cue_groups = [g for g in groups.values() if g['cue'] is not None]

    # ---- verdict ----
    if not m.get('alignment_ok', True):
        verdict = ('bad', 'Alignment suspect: most in-cue samples do not match their cue, so the film-time offset is '
                          'probably wrong. The issues below are not reliable; re-run.')
    elif not counts:
        verdict = ('good', f'No subtitle issue found in {len(rows)} samples over {_t(duration)}.')
    else:
        top = ', '.join(f'{k} {v}' for k, v in counts.most_common(4))
        verdict = ('bad', f'{len(cue_groups)} of {m["n_cues"]} cues have an issue'
                          f'{f", plus {len(groups) - len(cue_groups)} outside any cue" if len(groups) > len(cue_groups) else ""}'
                          f' ({top}).')

    # ---- issues by cue ----
    gparts = []
    for key, g in groups.items():
        c = g['cue']
        tag = ', '.join(f'{k}{" ×" + str(v) if v > 1 else ""}' for k, v in g['issues'].most_common())
        if c is not None:
            head = (f'<b>Cue {c.index}</b> · {_t(c.start)}–{_t(c.end)} · <span class="tag">{e(tag)}</span>'
                    f'<div class="cue-text">“{e(c.text.replace(chr(10), " / "))}”</div>')
        else:
            head = f'<b>Outside any cue</b> · {_t(g["start"])} · <span class="tag">{e(tag)}</span>'
        tm = g['timing']
        timing_line = (f'<p class="note">Timing: {e(tm["note"])} (SRT {_t(tm["srt_start"])}, first seen '
                       f'{_t(tm["seen_first"]) if tm["seen_first"] is not None else "—"}, speech '
                       f'{_t(tm["audio_start"]) if tm["audio_start"] is not None else "—"})</p>') if tm else ''
        items = ''.join(
            f'<div class="item"><img loading="lazy" src="data:image/jpeg;base64,{r["thumb"]}">'
            f'{chr(60) + "img class=band loading=lazy src=data:image/jpeg;base64," + r["band"] + chr(62) if r.get("band") else ""}'
            f'<div><b>{_t(r["t"])}</b> · {e(", ".join(row_issues(r)))}<br>'
            f'<span class="lbl">OCR</span> {e(r["ocr"] or "— (nothing read)")}<br>'
            f'<span class="lbl">Expected</span> {e(r["expected"] or "(no cue)")}<br>'
            f'<span class="lbl">Audio</span> {e(r["audio"] or "—")}<br>'
            f'{"<span class=lbl>Source file</span> " + e(r.get("ref_ocr") or "— (nothing read)") + " <small>(same moment, read from the .mkv)</small><br>" if "ref_ocr" in r else ""}'
            f'<small>{e(" · ".join(x for x in (r["verdict"]["note"], ("CER " + format(r["verdict"]["cer"] * 100, ".0f") + "%") if r["verdict"]["cer"] is not None else "") if x))}'
            f' · <a href="#s{pos[id(r)]}" onclick="openAll()">sample #{pos[id(r)]}</a></small></div></div>'
            for r in g['rows'])
        gparts.append(f'<details class="grp" data-i="{" ".join(g["issues"])}"><summary>{head}</summary>{timing_line}{items}</details>')
    issues_html = ''.join(gparts) or '<p>No issue.</p>'

    # ---- timeline ----
    W = 1000
    sx = lambda t: t / duration * W
    tl = [f'<svg viewBox="0 0 {W} 70" width="100%" class="tl">']
    for c in cues:
        tl.append(f'<rect x="{sx(c.start):.1f}" y="4" width="{max(sx(c.end) - sx(c.start), 1):.1f}" height="12" fill="var(--vpt-steel)"/>')
    for i, r in enumerate(rows):
        v = r['verdict']
        col = COLORS['issue'] if row_issues(r) else COLORS['boundary'] if v['state'] == 'boundary' else COLORS['ok']
        tl.append(f'<a href="#s{i}" onclick="openAll()"><rect x="{sx(r["t"]):.1f}" y="22" width="2" height="30" fill="{col}">'
                  f'<title>{_t(r["t"])} {e(", ".join(row_issues(r)) or "ok")}</title></rect></a>')
    for t in timings:
        if t['issue']:
            tl.append(f'<rect x="{sx(t["srt_start"]):.1f}" y="16" width="4" height="4" fill="var(--vpt-warning)"><title>cue {t["cue"]} {t["issue"]}</title></rect>')
    for mm in range(0, int(duration) + 1, 60):
        tl.append(f'<text x="{sx(mm):.1f}" y="66" font-size="10" fill="var(--vpt-muted)">{mm // 60}m</text>')
    tl.append('</svg>')

    summary = ''.join(
        f'<tr class="{"bad" if counts.get(it) else ""}"><td><a href="#all" data-f="{it}">{it}</a></td><td>{counts.get(it, 0)}</td><td>{e(ISSUE_HELP[it])}</td></tr>'
        for it in ISSUE_TYPES)
    tim_rows = ''.join(
        f'<tr class="{"bad" if t["issue"] else "okrow"}"><td>{t["cue"]}</td><td>{_t(t["srt_start"])}</td>'
        f'<td>{_t(t["seen_first"]) if t["seen_first"] is not None else ""}</td>'
        f'<td>{_t(t["audio_start"]) if t["audio_start"] is not None else ""}</td>'
        f'<td>{_n(t["lag_srt"], "+.2f")}</td><td>{_n(t["lag_audio"], "+.2f")}</td><td>{e(t["issue"] or "")}</td></tr>'
        for t in timings)
    body = ''.join(_sample_row(i, r, e) for i, r in enumerate(rows))
    cleared = [r for r in rows if r['verdict'].get('cleared')]
    cleared_html = ''.join(
        f'<div class="item"><img loading="lazy" src="data:image/jpeg;base64,{r["band"] or r["thumb"]}">'
        f'{"<img class=band loading=lazy src=data:image/jpeg;base64," + r["ref_band"] + ">" if r.get("ref_band") else ""}'
        f'<div><b>{_t(r["t"])}</b> · was {e(r["verdict"]["cleared"])}<br><span class="lbl">Device</span> {e(r["ocr"] or "— (nothing read)")}<br>'
        f'<span class="lbl">Source file</span> {e(r.get("ref_ocr") or "— (nothing read)")}<br>'
        f'<span class="lbl">Expected</span> {e(r["expected"] or "(no cue)")}<br><small>{e(r["verdict"]["note"])}</small></div></div>'
        for r in cleared)
    sc = m.get('source_check')
    cleared_section = (f'<details><summary><h2>Not counted: {gl("OCR limit", "ocr-limit")} or {gl("picture text", "picture-text")} <small>{len(cleared)} samples · '
                       f'left = device capture, right = the same moment read from the source file</small></h2></summary>'
                       f'<p class="mut" style="margin-top:0">Each flagged sample was read again from the source .mkv at the same moment '
                       f'(subtitle drawn by libass, no capture path). When the source frame fails the same way, the problem is our OCR '
                       f'(or text that is part of the film picture), not the device, and the sample is not counted.</p>{cleared_html}</details>'
                       if cleared else '')
    oi, res = m.get('ocr') or {}, m.get('resolution') or {}
    info_rows = ''.join(f'<tr><td>{e(k)}</td><td>{e(str(v))}</td></tr>' for k, v in [
        ('OCR engine', f'{oi.get("engine", "tesseract")} {oi.get("version", "")} · language data {oi.get("lang_data", "")} · {oi.get("page_mode", "")}'),
        ('OCR input', f'{oi.get("roi", "")} · {oi.get("preprocess", "")} · words kept at confidence ≥ {oi.get("min_word_conf", "")}'),
        ('Source video', res.get('source', '')), ('Analysed frames', res.get('capture', '')), ('Subtitle band', res.get('band', '')),
        ('Source check', (f'{sc["checked"]} flagged samples re-read from the source file: {sc["source_ok"]} still an issue, '
                          f'{sc["ocr_limit"]} OCR limit, {sc["in_source"]} picture text'
                          f'{", " + str(sc["no_frame"]) + " without a source frame" if sc.get("no_frame") else ""}') if sc else
                         'not run (local mode reads the source itself: what is flagged is OCR or the file)'),
    ] if v)
    info_html = f'<details open><summary><h2>How the subtitles were read</h2></summary><table>{info_rows}</table></details>'
    back = (f'<p><a href="{e(m["run_report_url"], quote=True)}">← Back to the run report</a></p>' if m.get('run_report_url') else '')
    filters = ''.join(f'<button data-f="{it}">{it} ({counts[it]})</button>' for it in ISSUE_TYPES if counts.get(it) and it not in ('late_cue', 'early_cue'))
    mosaic_html = (f'<details open><summary><h2>Error mosaic <small>{gl("?", "mosaic")} one tile per problem cue</small></h2></summary>'
                   f'<a href="data:image/jpeg;base64,{mosaic_b64}" target="_blank"><img class="mosaic" src="data:image/jpeg;base64,{mosaic_b64}"></a></details>'
                   if mosaic_b64 else '')

    return f'''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Subtitle QA — {e(m["title"])}</title>{report_theme_head()}<style>
:root{{--bg:var(--vpt-page);--fg:var(--vpt-text);--mut:var(--vpt-muted);--line:var(--vpt-border);--bad:var(--vpt-error-tint);--edge:var(--vpt-subtle);--card:var(--vpt-surface);--good:var(--vpt-success-tint)}}
body{{font:14px/1.45 system-ui,sans-serif;background:var(--bg);color:var(--fg);margin:0 auto;padding:16px;max-width:1400px}}
h1{{margin:0 0 4px}}h2{{display:inline;font-size:18px;margin:0}}
table{{border-collapse:collapse;width:100%}}td,th{{border-bottom:1px solid var(--line);padding:6px;vertical-align:top;text-align:left}}
tr.bad{{background:var(--bad)}}tr.edge{{background:var(--edge)}}small,.mut{{color:var(--mut)}}a{{color:var(--vpt-accent-text)}}
#all img{{width:300px;max-width:100%;display:block}}
.verdict{{padding:12px 14px;border-radius:6px;font-size:15px;margin:12px 0;border:1px solid var(--line)}}.verdict.bad{{background:var(--bad);border-color:var(--vpt-error)}}.verdict.good{{background:var(--good);border-color:var(--vpt-success)}}
.kpi{{display:flex;gap:24px;flex-wrap:wrap;margin:8px 0 4px}}.kpi div{{min-width:110px}}.kpi b{{font-size:22px;display:block}}
details{{border:1px solid var(--line);border-radius:6px;margin:12px 0;padding:0 12px}}details>summary{{cursor:pointer;padding:10px 0;list-style:none}}
details>summary::before{{content:"▶ ";color:var(--mut)}}details[open]>summary::before{{content:"▼ "}}
details.grp{{background:var(--card);margin:6px 0}}.tag{{color:var(--vpt-error)}}.cue-text{{color:var(--mut);margin-top:2px}}
.item{{display:flex;gap:12px;padding:8px 0;border-top:1px solid var(--line)}}.item img{{width:220px;flex:none;border-radius:3px;align-self:flex-start}}.item img.band{{width:420px}}
.lbl{{display:inline-block;min-width:68px;color:var(--mut)}}.note{{margin:4px 0 8px}}
.mosaic{{max-width:100%;border-radius:4px;cursor:zoom-in}}.tl{{background:var(--edge);border-radius:4px}}
.bar button{{margin:0 6px 6px 0;padding:4px 10px;border:1px solid var(--line);border-radius:14px;background:var(--card);color:var(--fg);cursor:pointer}}
.bar button.on{{background:var(--vpt-accent);color:var(--vpt-on-accent);border-color:var(--vpt-accent)}}
a.gl{{color:inherit;text-decoration:underline dotted}}.gloss dt{{font-weight:600;margin-top:8px}}.gloss dd{{margin:2px 0 0 0;color:var(--mut)}}
@media(max-width:700px){{.item{{flex-direction:column}}.item img{{width:100%}}}}
</style></head><body>
{back}<h1>Subtitle QA — {e(m["title"])}</h1>
<small>{e(m["source"])} · track <b>{e(m["lang"])}</b> · audio language <b>{e(str(m["audio_lang"]))}</b> · {m["n_cues"]} cues · {len(rows)} samples over {_t(duration)} · run {e(m["when"])} · {e(m["mode"])} · OCR tesseract · audio {e(m["audio_engine"])} · analysis {m["wall"]:.0f}s</small>
<div class="verdict {verdict[0]}"><b>{"Issues found" if verdict[0] == "bad" else "OK"}:</b> {e(verdict[1])}</div>
<div class="kpi"><div><b>{len(cue_groups)}</b>{gl("cues")} with an issue</div><div><b style="color:var(--vpt-error)">{n_issue_samples}</b>samples with an issue</div>
<div><b>{len(rows) - n_issue_samples}</b>samples OK</div><div><b>{n_timing}</b>cues late / early</div>
<div><b>{m["mean_cer"] * 100:.1f}%</b>mean {gl("CER")} (in-cue samples)</div><div><b>{m["median_lag"]:+.2f}s</b>median {gl("lag vs SRT", "lag-srt")}</div></div>

{info_html}
<details open><summary><h2>Issues by cue <small>{len(groups)} groups · click a cue to see its frames</small></h2></summary>
<p class="mut" style="margin-top:0">One line per cue with a problem, in film order. A bad read in a single frame of a cue that other frames
read correctly is {gl("OCR noise", "noise")} and is not listed. Technical words link to the <a href="#glossary">glossary</a>.</p>
<div class="bar"><button type="button" id="grp-open">Expand all</button><button type="button" id="grp-close">Collapse all</button></div>{issues_html}</details>
{mosaic_html}{cleared_section}
<details open><summary><h2>Issues per type</h2></summary><table><tr><th>Issue</th><th>Count</th><th>Meaning</th></tr>{summary}</table></details>
<details open><summary><h2>Timeline</h2></summary>{"".join(tl)}<small>grey band = SRT cue · green = OK · red = issue · grey = cue edge (either state accepted) · orange dot = late/early cue. Click a mark to open its sample.</small></details>
<details><summary><h2>Cue timing <small>{gl("first seen", "first-seen")} vs {gl("SRT")} vs {gl("speech")}, {n_timing} with an issue</small></h2></summary>
<label><input type="checkbox" id="tim-all"> show every cue</label>
<table id="tim"><tr><th>Cue</th><th>SRT start</th><th>First seen</th><th>Speech start</th><th>Lag vs SRT (s)</th><th>Lag vs speech (s)</th><th>Issue</th></tr>{tim_rows}</table></details>
<details id="all"><summary><h2>All samples <small>{len(rows)}</small></h2></summary>
<div class="bar"><button data-f="" >all</button><button data-f="issue" class="on">issues only ({n_issue_samples})</button><button data-f="ok">OK</button>{filters}</div>
<table><tr><th>#</th><th>Frame</th><th>OCR subtitle</th><th>Expected cue</th><th>Audio transcript</th><th>Verdict</th></tr>{body}</table></details>
{glossary_html()}
<script>
function openAll(){{document.getElementById('all').open=true;}}
function filt(f){{document.querySelectorAll('#all tr[data-i]').forEach(r=>{{const i=r.dataset.i.split(' ');
 r.style.display=(!f||(f==='issue'&&i[0]!=='ok')||i.includes(f))?'':'none';}});
 document.querySelectorAll('.bar button').forEach(b=>b.classList.toggle('on',b.dataset.f===f));}}
document.querySelectorAll('.bar button').forEach(b=>b.onclick=()=>filt(b.dataset.f));
document.querySelectorAll('a[data-f]').forEach(a=>a.onclick=()=>{{openAll();filt(a.dataset.f);}});
const ta=document.getElementById('tim-all');function tim(){{document.querySelectorAll('#tim tr.okrow').forEach(r=>r.style.display=ta.checked?'':'none');}}
ta.onchange=tim;tim();filt('issue');
function grps(o){{document.querySelectorAll('details.grp').forEach(d=>d.open=o);}}
document.getElementById('grp-open').onclick=()=>grps(true);document.getElementById('grp-close').onclick=()=>grps(false);
</script>
</body></html>'''
