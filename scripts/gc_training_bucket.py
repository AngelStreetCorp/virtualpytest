#!/usr/bin/env python3
"""
gc_training_bucket.py — reconcile the AI training bucket against ``ai_training_samples``
(TASK-69 §5, step 6).

The training bucket must never carry a lifecycle (expiry) rule
(``cloudflare_utils.TrainingStorage``), because a frozen eval row's image has to
survive. So when ``retention.cleanup_training_samples()`` prunes rows, their
images are left behind in MinIO as permanent orphans. This job is the other half
of that: **the database is the authority**, and an object with no row is the only
deletable case.

Two directions are reported:

  * objects with no row  -> orphans, deletable (the only thing this script deletes)
  * rows with no object  -> reverse drift, REPORTED ONLY, never acted on. A missing
                            object is a data-loss signal for whoever owns the corpus,
                            and guessing at it here could hide a storage incident.

Dry-run by default. ``--apply`` is required to delete anything, and ``--max-delete``
caps a single run so a mis-scoped prefix cannot empty a bucket in one go.

Usage:
    python3 scripts/gc_training_bucket.py                     # dry-run, whole bucket
    python3 scripts/gc_training_bucket.py --prefix <team_id>/screen-id/stb/
    python3 scripts/gc_training_bucket.py --apply --max-delete 500

Run it after ``retention.cleanup_all()`` (a systemd timer), on a host whose
``.env`` has the ``MINIO_TRAINING_*`` vars set. Read-only against the database:
no row is ever inserted, updated or deleted here.
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Dict, List, Optional, Sequence, Set, Tuple

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from shared.src.lib.database import ai_training_samples_db as samples_db  # noqa: E402
from shared.src.lib.utils import cloudflare_utils  # noqa: E402

# delete_objects caps at 1000 keys per call.
DELETE_BATCH = 1000
# PostgREST caps a response at max-rows (1000 by default), so the key read pages
# through with an explicit range instead of trusting one response to be complete.
DB_PAGE_SIZE = 1000


def list_bucket_objects(storage, prefix: str = '') -> List[Tuple[str, int]]:
    """Every object in the training bucket as ``[(key, size_bytes)]``, fully paginated.

    ``list_objects_v2`` returns at most 1000 keys per call, so a single call would
    silently treat a large bucket as nearly empty — and a near-empty bucket means
    "delete everything". The paginator is what makes the dry-run trustworthy.
    """
    objects: List[Tuple[str, int]] = []
    paginator = storage.s3_client.get_paginator('list_objects_v2')
    for page in paginator.paginate(Bucket=storage.bucket_name, Prefix=prefix or ''):
        for entry in page.get('Contents', []) or []:
            key = entry.get('Key')
            if key:
                objects.append((key, int(entry.get('Size', 0) or 0)))
    return objects


def fetch_db_object_keys(team_id: Optional[str] = None, page_size: int = DB_PAGE_SIZE) -> Set[str]:
    """Every ``object_key`` in ``ai_training_samples`` (optionally one team), read-only.

    Pages with ``range()``: a plain ``select()`` is truncated at the PostgREST
    max-rows cap, and a truncated key set makes every object beyond the cap look
    like an orphan.
    """
    query = samples_db.get_supabase().table(samples_db.TABLE).select('object_key')
    if team_id:
        query = query.eq('team_id', team_id)
    keys: Set[str] = set()
    offset = 0
    while True:
        result = query.range(offset, offset + page_size - 1).execute()
        rows = result.data or []
        keys.update(r['object_key'] for r in rows if r.get('object_key'))
        if len(rows) < page_size:
            return keys
        offset += page_size


def reconcile(objects: Sequence[Tuple[str, int]], db_keys: Set[str],
              prefix: str = '') -> Dict[str, List]:
    """Split the bucket into the two drift directions. Pure.

    Only the prefix is looked at in both directions: a row whose object lives
    outside ``prefix`` is not reported as missing, since this run cannot see it.
    """
    listed = {k for k, _ in objects}
    orphans = [(k, s) for k, s in objects if k not in db_keys]
    # A row whose object lives outside ``prefix`` cannot be judged by this run, so
    # only keys inside the reconciled prefix are considered missing.
    missing = sorted(k for k in db_keys
                     if k not in listed and (not prefix or k.startswith(prefix)))
    return {'orphans': orphans, 'missing': missing,
            'listed': len(listed), 'db_keys': len(db_keys)}


def delete_objects(storage, keys: Sequence[str]) -> Tuple[int, List[str]]:
    """Delete ``keys`` from the training bucket in batches of 1000.

    Returns ``(deleted, errors)``. ``deleted`` counts the keys accepted by S3;
    per-key failures come back in ``errors`` rather than raising, so one bad key
    does not abandon the rest of the run.
    """
    deleted, errors = 0, []
    keys = list(keys)
    for start in range(0, len(keys), DELETE_BATCH):
        batch = keys[start:start + DELETE_BATCH]
        response = storage.s3_client.delete_objects(
            Bucket=storage.bucket_name,
            Delete={'Objects': [{'Key': k} for k in batch], 'Quiet': True},
        )
        for err in response.get('Errors', []) or []:
            errors.append(f"{err.get('Key')}: {err.get('Code')} {err.get('Message')}")
        deleted += len(batch) - len(response.get('Errors', []) or [])
    return deleted, errors


def report(result: Dict[str, List], storage, apply: bool, orphan_bytes: int) -> None:
    orphans = result['orphans']
    missing = result['missing']
    print(f"bucket           : {storage.bucket_name}")
    print(f"objects listed   : {result['listed']}")
    print(f"db object_keys   : {result['db_keys']}")
    print(f"orphans (no row) : {len(orphans)}  ({orphan_bytes / 1048576:.1f} MB)")
    print(f"missing objects  : {len(missing)}  (rows whose object is gone -- reported, never acted on)")
    for key, size in orphans[:20]:
        print(f"  orphan  {size / 1024:8.1f} KB  {key}")
    if len(orphans) > 20:
        print(f"  ... and {len(orphans) - 20} more")
    for key in missing[:20]:
        print(f"  MISSING         {key}")
    if len(missing) > 20:
        print(f"  ... and {len(missing) - 20} more")
    if not apply:
        print("\nDRY RUN -- nothing deleted. Re-run with --apply to remove the orphans.")


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[1],
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--prefix', default='',
                        help="only reconcile this key prefix (default: the whole bucket)")
    parser.add_argument('--team-id', default=None,
                        help="only load object_keys of this team (default: all teams)")
    parser.add_argument('--apply', action='store_true',
                        help="actually delete the orphaned objects (default: dry run)")
    parser.add_argument('--max-delete', type=int, default=1000,
                        help="refuse to delete more than this many orphans in one run "
                             "(0 = no cap; default: 1000)")
    args = parser.parse_args(argv)

    if not cloudflare_utils.training_storage_configured():
        print("training storage is not configured: set all MINIO_TRAINING_* vars "
              "(or CLOUDFLARE_R2_* plus R2_TRAINING_BUCKET). Nothing to do.")
        return 1

    try:
        storage = cloudflare_utils.get_training_storage()
        objects = list_bucket_objects(storage, args.prefix)
        db_keys = fetch_db_object_keys(args.team_id)
    except Exception as e:
        print(f"could not read the bucket or the rows: {e}")
        return 1

    result = reconcile(objects, db_keys, args.prefix)
    report(result, storage, args.apply, sum(s for _k, s in result['orphans']))

    orphans = result['orphans']
    if not args.apply:
        return 0
    if not orphans:
        print("\nNo orphans: bucket and rows agree.")
        return 0
    if args.max_delete and len(orphans) > args.max_delete:
        print(f"\nrefusing to delete {len(orphans)} objects: --max-delete is {args.max_delete}. "
              f"Re-run with a higher cap once you have looked at the list above.")
        return 1

    deleted, errors = delete_objects(storage, [k for k, _s in orphans])
    print(f"\ndeleted {deleted} orphan(s)" + (f", {len(errors)} failed:" if errors else ""))
    for err in errors[:20]:
        print(f"  ERROR {err}")
    return 1 if errors else 0


if __name__ == '__main__':
    sys.exit(main())
