import os,sys,cv2,io,contextlib
os.chdir("/opt/virtualpytest"); from dotenv import load_dotenv; load_dotenv(".env"); sys.path.insert(0,".")
sys.path.insert(0,"/opt/virtualpytest/backend_host/src")
from shared.src.lib.utils.supabase_utils import get_supabase_client
from shared.src.lib.utils.cloudflare_utils import get_cloudflare_utils
from backend_host.src.controllers.verification.image_helpers import ImageHelpers
from urllib.parse import urlparse
H=ImageHelpers(None,None); sb=get_supabase_client(); cf=get_cloudflare_utils()
CACHE="/tmp/vpt_localize_cache"; os.makedirs(CACHE,exist_ok=True)
def sig(path):                          # regions + focus only — NO tesseract, fast
    img=cv2.imread(path)
    if img is None: return None
    g=cv2.cvtColor(img,cv2.COLOR_BGR2GRAY)
    with contextlib.redirect_stdout(io.StringIO()):
        return {"regions":H._region_dhashes(g),"focus":H._focus_signature(img)}
ui=sb.table("userinterfaces").select("id").eq("name","example_tv").execute().data[0]["id"]
trees=sb.table("navigation_trees").select("id").eq("userinterface_id",ui).execute().data
cands=[]; ndl=0
for t in trees:
    for n in sb.table("navigation_nodes").select("node_id,label,data").eq("tree_id",t["id"]).execute().data:
        k=(n.get("data") or {}).get("screenshot")
        if not k: continue
        if k.startswith("http"): k=urlparse(k).path.lstrip("/")
        lp=os.path.join(CACHE,k.replace("/","_"))
        if not os.path.exists(lp):       # download ONCE, then cached
            with contextlib.redirect_stdout(io.StringIO()):
                if not cf.download_file(k,lp).get("success"): continue
            ndl+=1
        s=sig(lp)
        if s: cands.append({"node_id":n["node_id"],"label":n["label"],"fingerprint":s})
for s,p in {'settings_system':'/tmp/settings_system_en.jpg','movies':'/tmp/hone_movies_en.jpg','home':'/tmp/home_en.jpg'}.items():
    cands.append({"node_id":f"{s}_EN","label":f"{s}_EN","fingerprint":sig(p)})
print(f"V5: {len(cands)} candidates ({ndl} freshly downloaded, rest cached)")
correct={'settings_system':{'settings_system','settings_system_EN'},'movies':{'home_movies','movies_EN'},'home':{'home','home_EN'}}
for s,p in {'settings_system':'/tmp/settings_system_ge.jpg','movies':'/tmp/home_movies_ge.jpg','home':'/tmp/home_ge.jpg'}.items():
    img=cv2.imread(p); g=cv2.cvtColor(img,cv2.COLOR_BGR2GRAY)
    with contextlib.redirect_stdout(io.StringIO()):
        r=H.match_fingerprint_v5(g,H._region_dhashes(g),H._focus_signature(img),cands)
    cs=r["candidates"]; top=cs[0]["label"] if cs else None
    ok="OK " if top in correct[s] else "XX "
    print(f"V5: [{ok}] {s}_GE -> [{', '.join(f'{c[chr(39)+chr(108)+chr(39)] if False else c[chr(108)]}' for c in [])}]" )
    t3=", ".join(f"{c['label']}({c.get('dist','?')})" for c in cs[:3])
    print(f"V5:      top3=[{t3}] focus={H._focus_signature(img).get('kind')} ncands={len(cs)}")
