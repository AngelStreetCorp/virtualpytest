import threading
import time
from typing import Any, Optional

_response_cache: dict[str, dict[str, Any]] = {}
_response_cache_lock = threading.Lock()


def get_cached_response(cache_key: str, ttl_seconds: int) -> Optional[Any]:
    with _response_cache_lock:
        cached = _response_cache.get(cache_key)
        if not cached:
            return None

        age = time.time() - cached['timestamp']
        if age >= ttl_seconds:
            _response_cache.pop(cache_key, None)
            return None

        return cached['data']


def set_cached_response(cache_key: str, data: Any) -> None:
    with _response_cache_lock:
        _response_cache[cache_key] = {
            'data': data,
            'timestamp': time.time(),
        }


def invalidate_cached_responses(prefix: str) -> None:
    with _response_cache_lock:
        keys_to_remove = [cache_key for cache_key in _response_cache if cache_key.startswith(prefix)]
        for cache_key in keys_to_remove:
            _response_cache.pop(cache_key, None)
