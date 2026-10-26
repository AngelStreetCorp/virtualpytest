"""Per-node verified frame: the last frame that passed a node's verifications.

One object per (team, tree, variant, node) in the storage bucket, overwritten on
each write: `node-verified/<team_id>/<tree_id>/<variant or __base__>/<node_id>.jpg`.
`verified_at` is the object's last-modified time (no DB column). Single frame by
choice: docs/agent/navigation/NODE_SCREENSHOTS.md ("Verified frame").

Write side (host, after a passing real run): `maybe_store_verified_frame`, throttled
and never raising. Read side (server): `get_verified_frames`, one list call per tree.
"""

import threading
import time
from typing import Dict, List, Optional

BASE_VARIANT = '__base__'
THROTTLE_S = 600
URL_EXPIRY_S = 6 * 3600

_last_upload: Dict[tuple, float] = {}
_lock = threading.Lock()


def verified_frame_prefix(team_id: str, tree_id: str, variant: Optional[str]) -> str:
    return f"node-verified/{team_id}/{tree_id}/{(variant or '').lower() or BASE_VARIANT}/"


def verified_frame_key(team_id: str, tree_id: str, variant: Optional[str], node_id: str) -> str:
    return f"{verified_frame_prefix(team_id, tree_id, variant)}{node_id}.jpg"


def _claim_slot(key: str, now: float) -> bool:
    """True when this key has not been uploaded in the last THROTTLE_S (and reserves it)."""
    with _lock:
        if now - _last_upload.get(key, -THROTTLE_S) < THROTTLE_S:
            return False
        _last_upload[key] = now
        return True


def maybe_store_verified_frame(frame_path: Optional[str], team_id: str, tree_id: str,
                               variant: Optional[str], node_id: str, *,
                               is_test: bool = False, uploader=None) -> bool:
    """Upload `frame_path` as the node's verified frame. Returns True when an upload
    was started. Skips tests, missing frames and throttled keys; never raises."""
    try:
        if is_test or not frame_path or not team_id or not tree_id or not node_id:
            return False
        key = verified_frame_key(team_id, tree_id, variant, node_id)
        if not _claim_slot(key, time.monotonic()):
            return False

        # Read the bytes now: capture frames rotate, the upload may run later.
        import cv2
        img = cv2.imread(frame_path, cv2.IMREAD_COLOR)
        if img is None or img.size == 0:
            return False
        ok, buf = cv2.imencode('.jpg', img, [cv2.IMWRITE_JPEG_QUALITY, 85])
        if not ok:
            return False
        data = buf.tobytes()

        def _put():
            try:
                up = uploader
                if up is None:
                    from shared.src.lib.utils.cloudflare_utils import get_cloudflare_utils
                    up = get_cloudflare_utils()
                up.s3_client.put_object(Bucket=up.bucket_name, Key=key, Body=data,
                                        ContentType='image/jpeg')
                print(f"[@node_verified_frame] stored {key} ({len(data)} bytes)")
            except Exception as e:
                with _lock:
                    _last_upload.pop(key, None)
                print(f"[@node_verified_frame] upload failed (non-fatal): {e}")

        threading.Thread(target=_put, name='node-verified-frame', daemon=True).start()
        return True
    except Exception as e:
        print(f"[@node_verified_frame] skipped (non-fatal): {e}")
        return False


def get_verified_frames(team_id: str, tree_ids: List[str], variant: Optional[str],
                        node_ids: Optional[List[str]] = None, uploader=None) -> Dict[str, Dict]:
    """{node_id: {verified_frame_url, verified_at}} for the frames stored under the
    given trees in one variant scope. One list call per tree; {} on any failure."""
    out: Dict[str, Dict] = {}
    wanted = set(node_ids) if node_ids is not None else None
    try:
        up = uploader
        if up is None:
            from shared.src.lib.utils.cloudflare_utils import get_cloudflare_utils
            up = get_cloudflare_utils()
        for tree_id in dict.fromkeys(t for t in tree_ids if t):
            prefix = verified_frame_prefix(team_id, tree_id, variant)
            paginator = up.s3_client.get_paginator('list_objects_v2')
            for page in paginator.paginate(Bucket=up.bucket_name, Prefix=prefix):
                for obj in page.get('Contents', []):
                    node_id = obj['Key'][len(prefix):].rsplit('.', 1)[0]
                    if not node_id or (wanted is not None and node_id not in wanted):
                        continue
                    signed = up.generate_presigned_url(obj['Key'], expires_in=URL_EXPIRY_S)
                    if not signed.get('success'):
                        continue
                    modified = obj.get('LastModified')
                    out[node_id] = {
                        'verified_frame_url': signed['url'],
                        'verified_at': modified.isoformat() if modified else None,
                    }
    except Exception as e:
        print(f"[@node_verified_frame] listing failed (non-fatal): {e}")
    return out
