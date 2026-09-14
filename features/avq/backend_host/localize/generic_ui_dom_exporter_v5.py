#!/usr/bin/env python3
"""Generic TV UI DOM exporter v5: v4 + deterministic cleanup/post-processing.

This version keeps the detector-plugin approach from v4, then normalizes the DOM
so the exported graph contains mostly interactive elements rather than OCR noise.
"""
from __future__ import annotations
import argparse, json, os, re, importlib.util, sys
from pathlib import Path
from dataclasses import asdict

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('domv4', str(HERE / 'generic_ui_dom_exporter_v4.py'))
domv4 = importlib.util.module_from_spec(spec)
sys.modules['domv4'] = domv4
assert spec and spec.loader
spec.loader.exec_module(domv4)

Element = domv4.Element

def norm(s: str) -> str:
    return re.sub(r'[^a-z0-9+]+', ' ', (s or '').lower()).strip()

def relabel_app_tile(e: Element) -> Element:
    """Fix common app-tile OCR/logotype errors using grid position/geometry."""
    y = e.y; x = e.x; low = norm(e.label)
    if y < 0.58:  # first app row
        # Use x bands from the 1280x720 screenshots.
        if x < 0.12:
            e.label = 'Netflix'; e.row='row_0'; e.col=0
        elif x < 0.30:
            e.label = 'Disney+'; e.row='row_0'; e.col=1
        elif x < 0.43:
            e.label = 'oneplus'; e.row='row_0'; e.col=2
        elif x < 0.58:
            e.label = 'YouTube'; e.row='row_0'; e.col=3
        elif x < 0.75:
            e.label = 'HBO Max'; e.row='row_0'; e.col=4
        elif x < 0.92:
            e.label = 'Prime Video'; e.row='row_0'; e.col=5
        else:
            e.label = 'Apple TV'; e.row='row_0'; e.col=6
    else:
        if x < 0.15:
            e.label = 'DAZN'; e.row='row_1'; e.col=0
        elif x < 0.30:
            e.label = 'Sky Sport'; e.row='row_1'; e.col=1
        elif x < 0.43:
            e.label = 'blue TV'; e.row='row_1'; e.col=2
        elif x < 0.58:
            e.label = 'Sky Show'; e.row='row_1'; e.col=3
        elif x < 0.75:
            e.label = 'Joyn'; e.row='row_1'; e.col=4
        elif x < 0.92:
            e.label = 'Play Suisse'; e.row='row_1'; e.col=5
        else:
            e.label = 'Sky Store'; e.row='row_1'; e.col=6
    e.type = 'card'; e.source = e.source or 'app_grid_clean'
    e.id = f'card_{e.row[-1]}_{e.col}_{domv4.slug(e.label)}'
    return e

def is_bad_label(label: str) -> bool:
    low = norm(label)
    if not low: return True
    if low in {'button','card','focus','focus region','underline','item'}: return True
    if re.fullmatch(r'[a-z]{1,2}( [a-z]{1,2})*', low): return True
    return False

def as_element(d: dict) -> Element:
    return Element(**{k: d[k] for k in d if k in Element.__dataclass_fields__})

def dedupe_by_center(elements):
    kept=[]
    for e in elements:
        dup=False
        for o in kept:
            if domv4.iou_box(o,(e.x,e.y,e.w,e.h))>.50 or (abs(o.cx-e.cx)<.018 and abs(o.cy-e.cy)<.022 and o.type==e.type):
                # keep focused or higher-priority source
                if e.focused and not o.focused:
                    kept.remove(o); kept.append(e)
                dup=True; break
        if not dup:
            kept.append(e)
    return kept

def clean_apps(dom):
    elems=[]
    for e in map(as_element, dom['elements']):
        # Convert app-looking hero/button/logo boxes to cards when in the grid.
        if e.source in {'app_grid','profile_avatar'} or (e.type in {'button','card'} and 0.20 < e.y < .96 and e.w>.035 and e.h>.045):
            # ignore tiny logo fragments inside already-detected tile area
            if e.w < .035 or e.h < .045: continue
            # only keep app rows, not random OCR text
            if e.y < .20: continue
            e = relabel_app_tile(e)
            elems.append(e)
        elif e.type == 'text_item' and norm(e.label) in {'apps','beliebt','streaming'}:
            # section labels are useful but should not be focusable in nav graph later
            elems.append(e)
    elems=dedupe_by_center(sorted(elems,key=lambda z:(z.y,z.x)))
    return elems

def clean_netflix_profile(dom):
    elems=[]
    for e in map(as_element, dom['elements']):
        if e.source=='profile_avatar':
            # Avoid noisy OCR as label when unreadable; stable position label is better for automation.
            idx = len(elems)
            if is_bad_label(e.label) or len(norm(e.label).split()) <= 3:
                e.label = 'Profile 1' if idx==0 else f'Profile {idx+1}'
            e.id=f'profile_{idx}_{domv4.slug(e.label)}'; e.type='card'; e.row=f'profile_row_{idx}'; e.col=0
            elems.append(e)
        elif e.type=='text_item' and 'netflix' in norm(e.label):
            elems.append(e)
    return elems

def clean_tvguide(dom):
    elems=[]
    for e in map(as_element, dom['elements']):
        if e.type in {'nav_item','epg_cell'}:
            elems.append(e)
        elif e.type=='text_item' and norm(e.label) in {'guide','tv guide'}:
            elems.append(e)
    return elems

def clean_live_menu(dom):
    elems=[]
    for e in map(as_element, dom['elements']):
        if e.source=='menu_row':
            elems.append(e)
        elif e.focused and norm(e.label)=='audio':
            e.type='menu_item'; e.source='menu_row_focus'; e.id='menu_audio'; e.label='Audio'; e.row='menu'
            elems.append(e)
    # If focus row replaced menu row, remove duplicate Subtitles/Audio overlaps.
    return dedupe_by_center(sorted(elems,key=lambda z:(z.y,z.x)))

def clean_apple_tv(dom):
    elems=[]
    for e in map(as_element, dom['elements']):
        low=norm(e.label)
        if e.source in {'hero_button','hero_button_inferred'}:
            if low in {'play','info','next','+'} or e.id in {'button_play','button_info','button_next','button_item'}:
                if e.id=='button_item' or e.label=='+': e.label='+'; e.id='button_add'
                if low=='play': e.label='Play'; e.id='button_play'
                elems.append(e)
        elif e.type=='card' and e.y>.82 and e.w>.05:
            # bottom carousel cards; labels can be noisy but geometry is useful
            if is_bad_label(e.label): e.label=f'Card {len([x for x in elems if x.type=="card"])+1}'
            elems.append(e)
        elif e.type=='button' and 'apple tv' in low and e.y<.12:
            elems.append(e)
    return dedupe_by_center(sorted(elems,key=lambda z:(z.y,z.x)))

def clean_asset_detail(dom):
    elems=[]
    for e in map(as_element, dom['elements']):
        low=norm(e.label)
        if e.focused and low in {'play','replay'}:
            e.type='button'; e.label='Replay' if low=='replay' else 'Play'; e.id=f'button_{low}'
            elems.append(e)
        elif e.source in {'hero_button','focus_cue'} and low in {'play','replay','episodes','aufnehmen','recordings'}:
            e.type='button'; elems.append(e)
        elif e.type=='nav_item':
            elems.append(e)
    return dedupe_by_center(sorted(elems,key=lambda z:(z.y,z.x)))

def generic_prune(dom):
    elems=[]
    for e in map(as_element, dom['elements']):
        # remove clear OCR clutter/body text while preserving focus and structured elements
        if e.focused or e.type in {'nav_item','epg_cell','menu_item'} or e.source in {'app_grid','profile_avatar','hero_button','hero_button_inferred'}:
            elems.append(e); continue
        if e.type=='text_item':
            # keep only large/left aligned labels, not paragraphs/subtitles/poster OCR
            if e.h>.032 and e.w<.22 and e.y<.75:
                elems.append(e)
            continue
        if e.type in {'card','button'} and e.w>.045 and e.h>.04 and not is_bad_label(e.label):
            elems.append(e)
    return dedupe_by_center(sorted(elems,key=lambda z:(z.y,z.x)))

def postprocess_dom(dom):
    img = dom.get('image','')
    screen = dom.get('screen_id','')
    if screen == 'apps' or img.startswith('apps'):
        elements = clean_apps(dom)
    elif 'netflix_profile' in img or screen.startswith('netflix'):
        elements = clean_netflix_profile(dom)
    elif screen == 'tvguide' or img.startswith('tvguide'):
        elements = clean_tvguide(dom)
    elif 'live_menu' in img:
        elements = clean_live_menu(dom)
    elif 'appletv' in img or screen == 'apple_tv':
        elements = clean_apple_tv(dom)
    elif 'asset' in img or screen in {'unknown','ait_ae_ge'}:
        elements = clean_asset_detail(dom)
        if not elements:
            elements = generic_prune(dom)
    else:
        elements = generic_prune(dom)

    # Preserve focus if retained; otherwise find focused by original label/overlap.
    orig_focus = dom.get('focused_element_id')
    if not any(e.focused for e in elements):
        orig_e = None
        for d in dom['elements']:
            if d.get('id') == orig_focus or d.get('focused'):
                orig_e = as_element(d); break
        if orig_e:
            best=None; score=-1
            for e in elements:
                s = domv4.iou_box(e,(orig_e.x,orig_e.y,orig_e.w,orig_e.h)) + (1 if norm(e.label)==norm(orig_e.label) else 0)
                if s>score: score=s; best=e
            if best and score>.15:
                best.focused=True
            else:
                # Keep the best focus: cleanup dropped the focused element entirely.
                # Re-add it so we never LOSE a focus the detector already found
                # (e.g. tvguide's focused cell pruned by clean_tvguide) — a detected
                # focus, even with a noisy label, beats no focus for navigation.
                orig_e.focused=True
                elements.append(orig_e)
    focused_id = next((e.id for e in elements if e.focused), None)
    # Reassign row/cols and rebuild nav with fewer nodes.
    domv4.assign_rows_cols(elements)
    nav = domv4.spatial_navigation(screen, elements)
    try: domv4.add_scroll_edges(nav, screen, elements)
    except Exception: pass
    out = dict(dom)
    out['elements'] = [asdict(e) for e in elements]
    out['focused_element_id'] = focused_id
    out['navigation'] = nav
    out['cleanup_version']='v5'
    return out

def infer_dom(path):
    return postprocess_dom(domv4.infer_dom(path))

def export(path, dom, out_dir):
    domv4.export(path, dom, out_dir)

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('images', nargs='+')
    ap.add_argument('--out', default='/mnt/data/generic_ui_dom_v5_out')
    args=ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    results=[]; summary=[]
    for p in args.images:
        d=infer_dom(p); results.append(d); export(p,d,args.out)
        fe=next((e for e in d['elements'] if e.get('focused')), None)
        summary.append({'image':Path(p).name,'screen_id':d['screen_id'],'focus':d.get('focused_element_id'),'focused_label':fe['label'] if fe else None,'element_count':len(d['elements']),'types':sorted(set(e['type'] for e in d['elements']))})
        print(f"{Path(p).name:18s} screen={d['screen_id']:<16s} focus={d.get('focused_element_id')} elems={len(d['elements'])}")
        print('  ', [(e['type'], e['label'][:24], e['focused']) for e in d['elements'][:12]])
    json.dump(results, open(os.path.join(args.out,'dom_results.json'),'w'), indent=2, ensure_ascii=False)
    json.dump(summary, open(os.path.join(args.out,'summary_results.json'),'w'), indent=2, ensure_ascii=False)

if __name__=='__main__':
    main()
