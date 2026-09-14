#!/usr/bin/env python3
"""
Backfill: move verification-reference R2 objects from name-based paths to
stable id-based paths, and point the DB rows at the new location.

    reference-images/<userinterface_name>/<file>  ->  reference-images/<userinterface_id>/<file>
    text-references/<userinterface_name>/<file>    ->  text-references/<userinterface_id>/<file>

Why: paths/lookups keyed by the mutable userinterface *name* break on rename
(references vanish, MinIO keeps the old folder). After this backfill + the code
switch to id-based paths, a rename is purely cosmetic.

This reuses the existing, tested cloudflare_utils (download_file / upload_files /
get_public_url) rather than re-implementing object copy. Run from the backend
env (needs the same R2/MinIO + Supabase config the host uses).

    python backfill_reference_id_paths.py --dry-run   # report only, no writes
    python backfill_reference_id_paths.py             # copy objects + update DB

Idempotent: rows already on an id-based path (segment parses as a UUID) are skipped.
Old objects are left in place (copy, not move) so this is reversible; prune later.
"""
import argparse
import os
import sys
import tempfile
import uuid

# Make the repo importable when run from anywhere.
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, "..", "..", ".."))
sys.path.insert(0, _ROOT)

from shared.src.lib.utils.cloudflare_utils import get_cloudflare_utils  # noqa: E402
from shared.src.lib.utils.supabase_utils import get_supabase_client  # noqa: E402


def _is_uuid(seg: str) -> bool:
    try:
        uuid.UUID(seg)
        return True
    except (ValueError, AttributeError):
        return False


def _id_path(r2_path: str, ui_id: str) -> str | None:
    """reference-images/<whatever>/<rest>  ->  reference-images/<id>/<rest> (or None to skip).

    Uses the path's CURRENT folder segment as the copy source (it may be the old
    name after a rename — that's where the object physically is) and swaps it for
    the stable id. Skips paths already on a UUID folder.
    """
    parts = r2_path.split("/")
    if len(parts) < 3:
        return None
    prefix, seg = parts[0], parts[1]
    if prefix not in ("reference-images", "text-references"):
        return None
    if _is_uuid(seg):
        return None  # already id-based
    parts[1] = ui_id
    return "/".join(parts)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="report only, no writes")
    ap.add_argument("--team-id", help="optional: restrict to one team_id")
    ap.add_argument("--ui-name", help="optional: restrict to one userinterface_name (e.g. stb_tv)")
    args = ap.parse_args()

    sb = get_supabase_client()
    cf = get_cloudflare_utils()

    q = sb.table("verifications_references").select(
        "id,name,userinterface_name,userinterface_id,reference_type,r2_path,r2_url,team_id"
    )
    if args.team_id:
        q = q.eq("team_id", args.team_id)
    if args.ui_name:
        q = q.eq("userinterface_name", args.ui_name)
    rows = q.execute().data or []

    moved = skipped = failed = 0
    for r in rows:
        rid, ui_name, ui_id, r2_path = r["id"], r.get("userinterface_name"), r.get("userinterface_id"), r.get("r2_path")
        if not (ui_name and ui_id and r2_path):
            skipped += 1
            continue
        new_path = _id_path(r2_path, ui_id)
        if not new_path:
            skipped += 1
            continue

        is_text = r.get("reference_type") == "reference_text"
        print(f"{'[dry] ' if args.dry_run else ''}{'(text) ' if is_text else ''}{r2_path}  ->  {new_path}")
        if args.dry_run:
            moved += 1
            continue

        try:
            if is_text:
                # Text refs keep their text in `area`; r2_path is a label with no
                # backing object — just relabel it, nothing to copy.
                sb.table("verifications_references").update({"r2_path": new_path}).eq("id", rid).execute()
                moved += 1
                continue
            with tempfile.TemporaryDirectory() as td:
                local = os.path.join(td, os.path.basename(r2_path))
                dl = cf.download_file(r2_path, local)
                if not dl.get("success"):
                    print(f"  ! download failed: {dl.get('error')}")
                    failed += 1
                    continue
                up = cf.upload_files([{"local_path": local, "remote_path": new_path}])
                if not up.get("uploaded_files"):
                    print(f"  ! upload failed: {up.get('failed_uploads')}")
                    failed += 1
                    continue
            new_url = cf.get_public_url(new_path)
            sb.table("verifications_references").update(
                {"r2_path": new_path, "r2_url": new_url}
            ).eq("id", rid).execute()
            moved += 1
        except Exception as e:  # noqa: BLE001
            print(f"  ! error: {e}")
            failed += 1

    print(f"\n{'DRY-RUN ' if args.dry_run else ''}done: {moved} moved, {skipped} skipped, {failed} failed "
          f"(of {len(rows)} rows)")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
