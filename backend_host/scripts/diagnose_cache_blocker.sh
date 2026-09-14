#!/usr/bin/env bash
# On-box diagnostic for the dispatch "live goto serves an 18-node root-only graph" blocker.
# RUN ON THE HOST that owns the device (device4 = host1). It probes, in order:
#   A. clear-coverage: does clear_unified_cache(variant=None) actually drop the 'base' variant key?
#      (Prime suspect: the navigate keys on variant='base', but our whole-tree clear only dropped None.)
#   B. in-process load: force the LIVE vpt-host to rebuild its cache via its own /cache/populate route
#      (same process that serves the navigate), then check node count — 18 (load bug) or 42 (cache bug)?
#   C. device variant: what variant does device4's navigation_context carry (the navigate used 'base')?
#   D. re-navigate: after a forced populate, does goto settings_system resolve?
#
#   sudo bash diagnose_cache_blocker.sh
set -u
REPO=/opt/virtualpytest
UI=example_tv_autobuild
TEAM=7fdeb4bb-3639-4ec3-959f-b54769a219ce
PY=$REPO/venv/bin/python
HOST_IP=$(sudo ss -ltnp 2>/dev/null | grep 6109 | grep -oE '[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+' | head -1)
KEY=$(sudo -n grep -hE '^API_KEY=' $REPO/.env $REPO/backend_host/src/.env 2>/dev/null | head -1 | cut -d= -f2)

echo "host=$HOST_IP  ui=$UI"

ROOT=$(sudo -u vpt_user $PY - <<PY 2>/dev/null
import os,sys; sys.path.insert(0,"$REPO"); os.chdir("$REPO")
from dotenv import load_dotenv; load_dotenv(".env")
from shared.src.lib.utils.supabase_utils import get_supabase_client
sb=get_supabase_client()
ui=sb.table("userinterfaces").select("id").eq("name","$UI").execute().data[0]["id"]
print([t for t in sb.table("navigation_trees").select("id,name").eq("userinterface_id",ui).execute().data if t["name"].endswith("_navigation")][0]["id"])
PY
)
echo "root tree=$ROOT"

echo; echo "===== A. clear-coverage (standalone cache module) ====="
sudo -u vpt_user $PY - <<PY 2>&1 | grep -E "^A:"
import os,sys,io,contextlib; sys.path.insert(0,"$REPO"); os.chdir("$REPO/backend_host/src")
from dotenv import load_dotenv; load_dotenv("$REPO/.env")
from backend_host.src.services.navigation.navigation_executor_tree_manager import discover_complete_hierarchy, build_unified_tree_data
from shared.src.lib.utils.navigation_cache import populate_unified_cache, get_cached_unified_graph, clear_unified_cache
root,team="$ROOT","$TEAM"
with contextlib.redirect_stdout(io.StringIO()):
    data=build_unified_tree_data(discover_complete_hierarchy(root,team),team)
    for v in (None,"base"): populate_unified_cache(root,team,data,variant=v)
def cnt(v):
    g=get_cached_unified_graph(root,team,variant=v); return g.number_of_nodes() if g else "MISS"
print("A: built all_trees_data trees=",len(data))
print("A: before clear -> None=",cnt(None)," base=",cnt("base"))
with contextlib.redirect_stdout(io.StringIO()): clear_unified_cache(root,team,variant=None)
print("A: after clear(variant=None) -> None=",cnt(None)," base=",cnt("base"),
      "  <-- if base is still a number, the None-clear does NOT cover 'base' = THE BUG")
PY

echo; echo "===== B. force the LIVE host to rebuild its cache (its own process) ====="
echo "B: /cache/check before:"; curl -s "http://$HOST_IP:6109/host/navigation/cache/check/$ROOT?team_id=$TEAM" -H "X-API-Key: $KEY"; echo
for V in "" "base"; do
  echo "B: POST /cache/populate variant='$V':"
  curl -s -X POST "http://$HOST_IP:6109/host/navigation/cache/populate/$ROOT?team_id=$TEAM&variant=$V" -H "X-API-Key: $KEY" | head -c 240; echo
done

echo; echo "===== C. device4 navigation_context variant ====="
sudo journalctl -u vpt-host --since "-10min" --no-pager 2>/dev/null | grep -oE "variant=[a-zA-Z0-9_]+" | sort | uniq -c | tail -5
echo "C: (the navigate earlier synced variant=base; if device4 should be base, B must populate 'base')"

echo; echo "===== D. interpretation ====="
echo "  - A shows base STILL cached after clear(None)  => fix clear_unified_cache to drop all variants,"
echo "    OR always clear with the device's actual variant. Then the live navigate reloads 42."
echo "  - B /cache/populate returning 42 nodes for variant=base => the host CAN build it in-process;"
echo "    the blocker was purely the stale 'base' cache entry. Re-run a goto to confirm."
echo "  - B returning 18 for variant=base => the in-process LOAD itself yields 18 (deeper: compare"
echo "    discover_complete_hierarchy / build_unified_tree_data output in-process vs the A standalone)."
