import os,sys,cv2,io,contextlib
os.chdir("/opt/virtualpytest"); from dotenv import load_dotenv; load_dotenv(".env"); sys.path.insert(0,".")
sys.path.insert(0,"/opt/virtualpytest/backend_host/src")
from shared.src.lib.utils.supabase_utils import get_supabase_client
from shared.src.lib.utils.cloudflare_utils import get_cloudflare_utils
from backend_host.src.controllers.verification.image_helpers import ImageHelpers
from urllib.parse import urlparse
H=ImageHelpers(None,None); sb=get_supabase_client(); cf=get_cloudflare_utils()
APPLY="--apply" in sys.argv; CACHE="/tmp/vpt_localize_cache"; os.makedirs(CACHE,exist_ok=True)
for uiname in ["example_tv","example_tv_autobuild"]:
    ui=sb.table("userinterfaces").select("id").eq("name",uiname).execute().data
    if not ui: continue
    trees=sb.table("navigation_trees").select("id").eq("userinterface_id",ui[0]["id"]).execute().data
    done=skip=0
    for t in trees:
        for n in sb.table("navigation_nodes").select("node_id,label,data").eq("tree_id",t["id"]).execute().data:
            d=n.get("data") or {}; fp=d.get("fingerprint") or {}; k=d.get("screenshot")
            if not k or not fp.get("dhash"): skip+=1; continue
            kk=urlparse(k).path.lstrip("/") if k.startswith("http") else k
            lp=os.path.join(CACHE,kk.replace("/","_"))
            if not os.path.exists(lp):
                with contextlib.redirect_stdout(io.StringIO()):
                    if not cf.download_file(kk,lp).get("success"): skip+=1; continue
            img=cv2.imread(lp)
            if img is None: skip+=1; continue
            with contextlib.redirect_stdout(io.StringIO()):
                fp["regions"]=H._region_dhashes(cv2.cvtColor(img,cv2.COLOR_BGR2GRAY))
            if APPLY:
                d["fingerprint"]=fp
                sb.table("navigation_nodes").update({"data":d}).eq("tree_id",t["id"]).eq("node_id",n["node_id"]).execute()
            done+=1
    print(f"BF: {uiname}: {done} nodes {'WROTE regions' if APPLY else '(dry-run)'}, {skip} skipped")
