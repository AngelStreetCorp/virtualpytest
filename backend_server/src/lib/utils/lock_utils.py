"""
Device lock utilities.

Server-authoritative in-memory lock manager with device-scoped keys:
- device_key = "host_name:device_id"
- explicit owner metadata
- structured conflicts
"""

import threading
import uuid
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from flask import request

from backend_server.src.lib.utils import lock_session_recorder as session_recorder


def resolve_lock_owner(data: Dict[str, Any], user_key: str = 'user_id') -> tuple:
    """(user_id, user_name) for a lock: the verified login when there is one.

    The browser sends its own user_id, and falls back to the built-in default
    user when its auth context has no id, so a logged-in person was recorded
    as that default and could not be identified (BUG-0424). A login verified
    by the auth guard (a JWT subject, always a UUID) wins; the request body is
    used only when there is no personal login (open mode, service key).
    """
    verified = getattr(request, 'user_id', None)
    try:
        uuid.UUID(str(verified))
    except ValueError:
        verified = None
    if verified:
        return verified, data.get('user_name') or getattr(request, 'user_email', None)
    return (data.get(user_key) or data.get('user_id') or request.headers.get('X-User-ID'),
            data.get('user_name'))


def get_client_ip() -> Optional[str]:
    """Extract client IP from Flask request with proxy-header support."""
    try:
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            return forwarded_for.split(",")[0].strip()

        real_ip = request.headers.get("X-Real-IP")
        if real_ip:
            return real_ip

        return request.remote_addr
    except Exception as exc:
        print(f"⚠️ [LockManager] Error extracting client IP: {exc}")
        return None


class DeviceLockManager:
    """Thread-safe device lock manager."""

    def __init__(self):
        self._locks: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.RLock()

    @staticmethod
    def _normalize_device_id(device_id: Optional[str]) -> str:
        return (device_id or "device1").strip()

    @staticmethod
    def _build_device_key(host_name: str, device_id: str) -> str:
        return f"{host_name}:{device_id}"

    @staticmethod
    def _serialize_lock(lock_data: Dict[str, Any]) -> Dict[str, Any]:
        locked_at = float(lock_data.get("locked_at", 0.0) or 0.0)
        now = time.time()
        owner_session_id = lock_data.get("owner_session_id")

        return {
            # Canonical fields
            "device_key": lock_data.get("device_key"),
            "host_name": lock_data.get("host_name"),
            "device_id": lock_data.get("device_id"),
            "owner_type": lock_data.get("owner_type"),
            "owner_session_id": owner_session_id,
            "owner_user_id": lock_data.get("owner_user_id"),
            "owner_user_name": lock_data.get("owner_user_name"),
            "owner_job_id": lock_data.get("owner_job_id"),
            "locked_at": locked_at,
            "last_heartbeat_at": lock_data.get("last_heartbeat_at"),
            "lock_reason": lock_data.get("lock_reason"),
            # Script running *under* a manual_control lock (subordinate execution).
            # The lock itself keeps owner_type/lock_reason of the human who holds
            # the device, so without these the running script name is invisible.
            "active_script_reason": lock_data.get("active_script_reason"),
            "active_script_job_id": lock_data.get("active_script_job_id"),
            "can_force_takeover": bool(lock_data.get("can_force_takeover", False)),
            "locked_ip": lock_data.get("locked_ip"),
            "lock_age_seconds": max(0.0, now - locked_at),
            # Backward-compatible fields
            "isLocked": True,
            "lockedBy": owner_session_id,
            "lockedAt": locked_at,
            "lockedDuration": max(0.0, now - locked_at),
            "lockedIp": lock_data.get("locked_ip"),
            "hostName": lock_data.get("host_name"),
        }

    def acquire_lock(
        self,
        *,
        host_name: str,
        device_id: str,
        owner_type: str,
        owner_session_id: str,
        owner_user_id: Optional[str] = None,
        owner_user_name: Optional[str] = None,
        owner_job_id: Optional[str] = None,
        lock_reason: Optional[str] = None,
        can_force_takeover: bool = True,
        client_ip: Optional[str] = None,
        allow_same_ip_takeover: bool = False,
        allow_same_user_takeover: bool = False,
    ) -> Dict[str, Any]:
        """Acquire a device lock or return structured conflict."""
        normalized_device_id = self._normalize_device_id(device_id)
        device_key = self._build_device_key(host_name, normalized_device_id)

        if not host_name or not owner_type or not owner_session_id:
            return {
                "success": False,
                "error": "host_name, owner_type, and owner_session_id are required",
            }

        with self._lock:
            existing = self._locks.get(device_key)
            now = time.time()

            if existing:
                same_session_owner = (
                    existing.get("owner_session_id") == owner_session_id
                    and existing.get("owner_type") == owner_type
                )
                existing_job_id = existing.get("owner_job_id")
                owner_job_mismatch = (
                    bool(owner_job_id)
                    and bool(existing_job_id)
                    and owner_job_id != existing_job_id
                )

                if same_session_owner and not owner_job_mismatch:
                    # Re-entrant refresh by same owner.
                    existing["last_heartbeat_at"] = now
                    existing["locked_at"] = now
                    if owner_user_id is not None:
                        existing["owner_user_id"] = owner_user_id
                    if owner_user_name is not None:
                        existing["owner_user_name"] = owner_user_name
                    if owner_job_id is not None:
                        existing["owner_job_id"] = owner_job_id
                    if lock_reason is not None:
                        existing["lock_reason"] = lock_reason
                    if client_ip is not None:
                        existing["locked_ip"] = client_ip
                    session_recorder.record_touch(existing)
                    return {
                        "success": True,
                        "reused": True,
                        "lock_info": self._serialize_lock(existing),
                    }

                if same_session_owner and owner_job_mismatch:
                    return {
                        "success": False,
                        "error": "device_locked",
                        "conflict": self._serialize_lock(existing),
                    }

                # Same user_id takeover for script execution. The built-in default id is shared by every
                # API-key, auto-sign and anonymous caller: it is not the same person, so a CI smoke must not run
                # under someone else's Take Control on it (TASK-135; same rule as live_foreign_execution).
                same_user = (
                    bool(owner_user_id)
                    and bool(existing.get("owner_user_id"))
                    and owner_user_id == existing.get("owner_user_id")
                    and str(owner_user_id) not in _shared_user_ids()
                )

                # The caller's own Take Control, matched by user or, for callers that
                # take control without a user id (MCP), by session.
                same_session = existing.get("owner_session_id") == owner_session_id

                if allow_same_user_takeover and (same_user or same_session):
                    existing_owner_type = existing.get("owner_type")

                    if existing_owner_type == "manual_control":
                        # Script runs under manual_control umbrella — don't change lock type,
                        # but record what is running so viewers see the owner AND the script
                        # name (cleared by clear_active_script on completion).
                        existing["last_heartbeat_at"] = now
                        existing["owner_job_id"] = owner_job_id
                        existing["active_script_reason"] = lock_reason
                        existing["active_script_job_id"] = owner_job_id
                        session_recorder.record_touch(existing)
                        return {
                            "success": True,
                            "reused": True,
                            "subordinate": True,
                            "lock_info": self._serialize_lock(existing),
                        }

                    # A running script's lock is never taken over implicitly, not even by
                    # the same user. It used to be: "same user, different session" superseded
                    # the running script and dispatched on top of it, while "same user, same
                    # session" was refused - so a browser tab queued and an API caller ran
                    # everything at once (BUG-0118). Taking over a stuck run is what the
                    # explicit force_unlock flag on the execute routes is for.

                if (
                    allow_same_ip_takeover
                    and client_ip
                    and existing.get("locked_ip")
                    and existing.get("locked_ip") == client_ip
                ):
                    session_recorder.record_end(existing, "superseded")
                    existing.update(
                        {
                            "owner_type": owner_type,
                            "owner_session_id": owner_session_id,
                            "owner_user_id": owner_user_id,
                            "owner_user_name": owner_user_name,
                            "owner_job_id": owner_job_id,
                            "locked_at": now,
                            "last_heartbeat_at": now,
                            "lock_reason": lock_reason,
                            "active_script_reason": None,
                            "active_script_job_id": None,
                            "can_force_takeover": bool(can_force_takeover),
                            "locked_ip": client_ip,
                        }
                    )
                    session_recorder.record_start(existing)
                    return {
                        "success": True,
                        "reused": False,
                        "lock_info": self._serialize_lock(existing),
                    }

                return {
                    "success": False,
                    "error": "device_locked",
                    "conflict": self._serialize_lock(existing),
                }

            new_lock = {
                "device_key": device_key,
                "host_name": host_name,
                "device_id": normalized_device_id,
                "owner_type": owner_type,
                "owner_session_id": owner_session_id,
                "owner_user_id": owner_user_id,
                "owner_user_name": owner_user_name,
                "owner_job_id": owner_job_id,
                "locked_at": now,
                "last_heartbeat_at": now,
                "lock_reason": lock_reason,
                "can_force_takeover": bool(can_force_takeover),
                "locked_ip": client_ip,
            }
            self._locks[device_key] = new_lock
            session_recorder.record_start(new_lock)
            return {
                "success": True,
                "reused": False,
                "lock_info": self._serialize_lock(new_lock),
            }

    def update_lock_metadata(
        self,
        *,
        host_name: str,
        device_id: str,
        owner_session_id: Optional[str],
        updates: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Update lock metadata for currently-owned lock."""
        normalized_device_id = self._normalize_device_id(device_id)
        device_key = self._build_device_key(host_name, normalized_device_id)

        with self._lock:
            existing = self._locks.get(device_key)
            if not existing:
                return {"success": False, "error": "not_locked"}

            if owner_session_id and existing.get("owner_session_id") != owner_session_id:
                return {
                    "success": False,
                    "error": "not_lock_owner",
                    "lock_info": self._serialize_lock(existing),
                }

            existing.update(updates or {})
            existing["last_heartbeat_at"] = time.time()
            session_recorder.record_touch(existing)
            return {"success": True, "lock_info": self._serialize_lock(existing)}

    def clear_active_script(
        self,
        *,
        host_name: str,
        device_id: str,
        owner_job_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Clear the subordinate-script info recorded on a manual_control lock.

        Called when a script that ran under a user's lock finishes: the lock stays
        (the human still holds the device), only the "script running" annotation goes.
        ``owner_job_id`` scopes the clear so a finished run cannot wipe the label of a
        newer run that already claimed the slot.
        """
        normalized_device_id = self._normalize_device_id(device_id)
        device_key = self._build_device_key(host_name, normalized_device_id)

        with self._lock:
            existing = self._locks.get(device_key)
            if not existing:
                return {"success": True, "cleared": False, "message": "not_locked"}

            if not existing.get("active_script_reason") and not existing.get("active_script_job_id"):
                return {
                    "success": True,
                    "cleared": False,
                    "lock_info": self._serialize_lock(existing),
                }

            active_job_id = existing.get("active_script_job_id")
            if owner_job_id and active_job_id and active_job_id != owner_job_id:
                return {
                    "success": True,
                    "cleared": False,
                    "message": "superseded_by_newer_run",
                    "lock_info": self._serialize_lock(existing),
                }

            existing["active_script_reason"] = None
            existing["active_script_job_id"] = None
            return {
                "success": True,
                "cleared": True,
                "lock_info": self._serialize_lock(existing),
            }

    def release_lock(
        self,
        *,
        host_name: str,
        device_id: str,
        owner_session_id: Optional[str] = None,
        owner_type: Optional[str] = None,
        owner_job_id: Optional[str] = None,
        force: bool = False,
    ) -> Dict[str, Any]:
        """Release lock with ownership validation by default."""
        normalized_device_id = self._normalize_device_id(device_id)
        device_key = self._build_device_key(host_name, normalized_device_id)

        with self._lock:
            existing = self._locks.get(device_key)
            if not existing:
                return {
                    "success": True,
                    "released": False,
                    "message": "not_locked",
                }

            if not force:
                if owner_session_id and existing.get("owner_session_id") != owner_session_id:
                    return {
                        "success": False,
                        "released": False,
                        "error": "not_lock_owner",
                        "lock_info": self._serialize_lock(existing),
                    }
                if owner_type and existing.get("owner_type") != owner_type:
                    return {
                        "success": False,
                        "released": False,
                        "error": "owner_type_mismatch",
                        "lock_info": self._serialize_lock(existing),
                    }
                if owner_job_id and existing.get("owner_job_id") and existing.get("owner_job_id") != owner_job_id:
                    return {
                        "success": False,
                        "released": False,
                        "error": "owner_job_mismatch",
                        "lock_info": self._serialize_lock(existing),
                    }

            released = self._locks.pop(device_key)
            session_recorder.record_end(released, "released")
            return {
                "success": True,
                "released": True,
                "lock_info": self._serialize_lock(released),
            }

    def takeover_lock(
        self,
        *,
        host_name: str,
        device_id: str,
        new_owner_session_id: str,
        new_owner_user_id: Optional[str] = None,
        reason: Optional[str] = None,
        expected_owner_types: Optional[Tuple[str, ...]] = None,
    ) -> Dict[str, Any]:
        """Atomically transfer lock to manual owner when takeover is allowed."""
        normalized_device_id = self._normalize_device_id(device_id)
        device_key = self._build_device_key(host_name, normalized_device_id)

        with self._lock:
            existing = self._locks.get(device_key)
            now = time.time()

            if not existing:
                new_lock = {
                    "device_key": device_key,
                    "host_name": host_name,
                    "device_id": normalized_device_id,
                    "owner_type": "manual_control",
                    "owner_session_id": new_owner_session_id,
                    "owner_user_id": new_owner_user_id,
                    "owner_job_id": None,
                    "locked_at": now,
                    "last_heartbeat_at": now,
                    "lock_reason": reason or "takeover_no_previous_owner",
                    "can_force_takeover": True,
                    "locked_ip": None,
                }
                self._locks[device_key] = new_lock
                session_recorder.record_start(new_lock)
                return {
                    "success": True,
                    "previous_owner": None,
                    "lock_info": self._serialize_lock(new_lock),
                }

            if existing.get("owner_session_id") == new_owner_session_id and existing.get("owner_type") == "manual_control":
                existing["last_heartbeat_at"] = now
                existing["locked_at"] = now
                session_recorder.record_touch(existing)
                return {
                    "success": True,
                    "previous_owner": self._serialize_lock(existing),
                    "lock_info": self._serialize_lock(existing),
                }

            if not bool(existing.get("can_force_takeover", False)):
                return {
                    "success": False,
                    "error": "takeover_not_allowed",
                    "conflict": self._serialize_lock(existing),
                }

            if expected_owner_types and existing.get("owner_type") not in expected_owner_types:
                return {
                    "success": False,
                    "error": "owner_type_not_takeover_eligible",
                    "conflict": self._serialize_lock(existing),
                }

            previous = self._serialize_lock(existing)
            session_recorder.record_end(existing, "takeover")
            existing.update(
                {
                    "owner_type": "manual_control",
                    "owner_session_id": new_owner_session_id,
                    "owner_user_id": new_owner_user_id,
                    "owner_job_id": None,
                    "locked_at": now,
                    "last_heartbeat_at": now,
                    "lock_reason": reason or "manual_takeover",
                    "active_script_reason": None,
                    "active_script_job_id": None,
                    "can_force_takeover": True,
                }
            )
            session_recorder.record_start(existing)
            return {
                "success": True,
                "previous_owner": previous,
                "lock_info": self._serialize_lock(existing),
            }

    def get_lock_info(self, host_name: str, device_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        if not device_id:
            return None
        with self._lock:
            key = self._build_device_key(host_name, self._normalize_device_id(device_id))
            existing = self._locks.get(key)
            if not existing:
                return None
            return self._serialize_lock(existing)

    def get_all_locked_devices(self) -> Dict[str, Dict[str, Any]]:
        with self._lock:
            return {k: self._serialize_lock(v) for k, v in self._locks.items()}

    def cleanup_expired_locks(
        self,
        timeout_seconds: int = 300,
        owner_types: Optional[Tuple[str, ...]] = ("manual_control",),
    ) -> list:
        """Cleanup by age, returning the serialized locks that were released.

        By default, only manual-control locks are expired automatically.
        Manual locks heartbeat (frontend pings refresh ``last_heartbeat_at``), so
        for them this is heartbeat age. Script/deployment locks never heartbeat
        (``last_heartbeat_at`` stays ``== locked_at``), so for them it is simply
        absolute lock age — which is exactly what we want for reaping zombie
        locks left behind when a run's completion callback never fires.
        """
        with self._lock:
            now = time.time()
            expired_keys = []
            for device_key, lock_data in self._locks.items():
                if owner_types and lock_data.get("owner_type") not in owner_types:
                    continue
                heartbeat = float(lock_data.get("last_heartbeat_at", lock_data.get("locked_at", 0)) or 0)
                if now - heartbeat > timeout_seconds:
                    expired_keys.append(device_key)

            released = []
            for device_key in expired_keys:
                lock_data = self._locks.pop(device_key, None)
                if lock_data is None:
                    continue
                session_recorder.record_end(lock_data, "expired")
                serialized = self._serialize_lock(lock_data)
                age = serialized.get("lock_age_seconds")
                print(
                    f"🧹 [LockManager] Reaping stale lock: {device_key} "
                    f"(owner_type={serialized.get('owner_type')}, "
                    f"reason={serialized.get('lock_reason')}, age={age:.0f}s)"
                )
                released.append(serialized)

            return released

    def reconcile_host_locks(
        self,
        host_name: str,
        process_start_time: float,
        owner_types: Tuple[str, ...] = ("script_execution", "deployment_execution", "testcase_execution"),
    ) -> list:
        """Reap execution locks left behind by a host's previous process.

        Called when a host (re)registers. Any execution lock for this host that
        was acquired BEFORE the host's current process start belongs to a dead
        prior process — the run it guarded cannot still be alive — so it is safe
        to release. A genuinely live run on the new process always has
        ``locked_at >= process_start_time`` and is never touched.
        """
        if not host_name or not process_start_time:
            return []
        prefix = f"{host_name}:"
        with self._lock:
            stale_keys = [
                device_key
                for device_key, lock_data in self._locks.items()
                if device_key.startswith(prefix)
                and lock_data.get("owner_type") in owner_types
                and float(lock_data.get("locked_at", 0) or 0) < process_start_time
            ]
            released = []
            for device_key in stale_keys:
                lock_data = self._locks.pop(device_key, None)
                if lock_data is None:
                    continue
                session_recorder.record_end(lock_data, "host_restart")
                serialized = self._serialize_lock(lock_data)
                print(
                    f"🔓 [LockManager] Reconciling stale lock on host restart: {device_key} "
                    f"(owner_type={serialized.get('owner_type')}, reason={serialized.get('lock_reason')})"
                )
                released.append(serialized)
            return released

    def force_unlock(self, host_name: str, device_id: Optional[str] = None) -> Dict[str, Any]:
        """Force-unlock one device or all host devices when device_id omitted."""
        with self._lock:
            if device_id:
                key = self._build_device_key(host_name, self._normalize_device_id(device_id))
                released = self._locks.pop(key, None)
                if released:
                    session_recorder.record_end(released, "force_unlock")
                return {
                    "success": True,
                    "released": bool(released),
                    "lock_info": self._serialize_lock(released) if released else None,
                }

            prefix = f"{host_name}:"
            keys = [k for k in self._locks.keys() if k.startswith(prefix)]
            released = []
            for k in keys:
                lock_data = self._locks.pop(k)
                session_recorder.record_end(lock_data, "force_unlock")
                released.append(self._serialize_lock(lock_data))
            return {
                "success": True,
                "released": bool(released),
                "released_count": len(released),
                "released_locks": released,
            }


# Global instance
_device_lock_manager = DeviceLockManager()


def get_device_lock_manager() -> DeviceLockManager:
    return _device_lock_manager


# New structured APIs

def acquire_device_lock(
    *,
    host_name: str,
    device_id: str,
    owner_type: str,
    owner_session_id: str,
    owner_user_id: Optional[str] = None,
    owner_user_name: Optional[str] = None,
    owner_job_id: Optional[str] = None,
    lock_reason: Optional[str] = None,
    can_force_takeover: bool = True,
    client_ip: Optional[str] = None,
    allow_same_ip_takeover: bool = False,
    allow_same_user_takeover: bool = False,
) -> Dict[str, Any]:
    return get_device_lock_manager().acquire_lock(
        host_name=host_name,
        device_id=device_id,
        owner_type=owner_type,
        owner_session_id=owner_session_id,
        owner_user_id=owner_user_id,
        owner_user_name=owner_user_name,
        owner_job_id=owner_job_id,
        lock_reason=lock_reason,
        can_force_takeover=can_force_takeover,
        client_ip=client_ip,
        allow_same_ip_takeover=allow_same_ip_takeover,
        allow_same_user_takeover=allow_same_user_takeover,
    )


def update_device_lock_metadata(
    *, host_name: str, device_id: str, owner_session_id: Optional[str], updates: Dict[str, Any]
) -> Dict[str, Any]:
    return get_device_lock_manager().update_lock_metadata(
        host_name=host_name,
        device_id=device_id,
        owner_session_id=owner_session_id,
        updates=updates,
    )


def clear_device_active_script(
    *, host_name: str, device_id: str, owner_job_id: Optional[str] = None
) -> Dict[str, Any]:
    return get_device_lock_manager().clear_active_script(
        host_name=host_name,
        device_id=device_id,
        owner_job_id=owner_job_id,
    )


def release_device_lock(
    *,
    host_name: str,
    device_id: str,
    owner_session_id: Optional[str] = None,
    owner_type: Optional[str] = None,
    owner_job_id: Optional[str] = None,
    force: bool = False,
) -> Dict[str, Any]:
    return get_device_lock_manager().release_lock(
        host_name=host_name,
        device_id=device_id,
        owner_session_id=owner_session_id,
        owner_type=owner_type,
        owner_job_id=owner_job_id,
        force=force,
    )


def takeover_device_lock(
    *,
    host_name: str,
    device_id: str,
    new_owner_session_id: str,
    new_owner_user_id: Optional[str] = None,
    reason: Optional[str] = None,
    expected_owner_types: Optional[Tuple[str, ...]] = None,
) -> Dict[str, Any]:
    return get_device_lock_manager().takeover_lock(
        host_name=host_name,
        device_id=device_id,
        new_owner_session_id=new_owner_session_id,
        new_owner_user_id=new_owner_user_id,
        reason=reason,
        expected_owner_types=expected_owner_types,
    )


def get_device_lock_info(host_name: str, device_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    return get_device_lock_manager().get_lock_info(host_name, device_id)


def get_all_locked_devices() -> Dict[str, Dict[str, Any]]:
    return get_device_lock_manager().get_all_locked_devices()


def cleanup_expired_locks(
    timeout_seconds: int = 300,
    owner_types: Optional[Tuple[str, ...]] = ("manual_control",),
) -> list:
    return get_device_lock_manager().cleanup_expired_locks(timeout_seconds, owner_types)


def force_unlock_device(host_name: str, device_id: Optional[str] = None) -> Dict[str, Any]:
    return get_device_lock_manager().force_unlock(host_name, device_id)


def reconcile_host_locks(host_name: str, process_start_time: float) -> list:
    return get_device_lock_manager().reconcile_host_locks(host_name, process_start_time)


# Compatibility wrappers (legacy signatures)

def lock_device(host_name: str, session_id: str, client_ip: Optional[str] = None) -> bool:
    result = acquire_device_lock(
        host_name=host_name,
        device_id="device1",
        owner_type="manual_control",
        owner_session_id=session_id,
        client_ip=client_ip,
        allow_same_ip_takeover=False,
    )
    return bool(result.get("success"))


def unlock_device(host_name: str, session_id: Optional[str] = None) -> bool:
    result = release_device_lock(
        host_name=host_name,
        device_id="device1",
        owner_session_id=session_id,
        force=not bool(session_id),
    )
    return bool(result.get("success"))


def is_device_locked(host_name: str) -> bool:
    return get_device_lock_info(host_name, "device1") is not None


def abort_running_execution(
    host_data: Dict[str, Any],
    device_id: str,
    owner_type: Optional[str],
) -> Dict[str, Any]:
    """Abort running script/campaign/deployment execution on a host device.

    Sends abort requests to the host and returns a structured result.
    404 from host is treated as reachable-but-nothing-there (not a transport failure).

    Two distinct outcomes, both reported:
    - ``success``: every abort call we made reached the host and did not error.
    - ``aborted``: the host actually killed/stopped something. ``success=True`` with
      ``aborted=False`` means "nothing was running for this device" — which is the
      normal case for a zombie lock, but is ALSO what a registry-key mismatch looks
      like. Callers that must not race a live execution should check ``aborted``.
    """
    from shared.src.lib.utils.build_url_utils import call_host

    # Testcases run as an in-process thread on the host. /server/testcase/execute locks
    # them as testcase_execution (or runs them under the caller's manual_control), but
    # other testcase routes take no lock, so this is attempted unconditionally —
    # otherwise a testcase keeps issuing actions after a human has taken the device.
    # Cooperative flag: it lands at the next block boundary, not instantly.
    targets = [("testcase", "/host/testcase/abortRunning")]

    if owner_type in ("script_execution", "deployment_execution"):
        # A campaign runs N scripts in a loop, so killing the current child is not enough —
        # the orchestrator would just advance to the next script and keep driving the device.
        # /host/campaigns/abortRunning sets the executor's cooperative abort flag. Campaigns
        # lock as 'script_execution' (interactive) or 'deployment_execution' (scheduler), so
        # this is attempted for both; it is idempotent and no-ops when nothing matches.
        targets.append(("script", "/host/script/abort"))
        targets.append(("campaign", "/host/campaigns/abortRunning"))
        if owner_type == "deployment_execution":
            targets.append(("deployment", "/host/deployment/abortRunning"))

    details: Dict[str, Any] = {}
    any_aborted = False

    for key, endpoint in targets:
        resp, status = call_host(
            host_data,
            endpoint,
            method="POST",
            data={"device_id": device_id},
            timeout=30,
        )
        details[key] = {"status_code": status, "response": resp}
        if status not in (200, 404):
            return {
                "success": False,
                "aborted": any_aborted,
                "error": resp.get("error") or f"Failed to abort running {key} execution",
                "details": details,
            }
        if status == 200 and isinstance(resp, dict) and resp.get("aborted"):
            any_aborted = True

    return {"success": True, "aborted": any_aborted, "details": details}


EXECUTION_LOCK_OWNER_TYPES = ("script_execution", "deployment_execution", "testcase_execution")

# A fresh execution lock whose run the host does not list yet is a run that is starting
# (lock grabbed, process/registry entry not there yet), not a zombie.
FRESH_EXECUTION_LOCK_GRACE_SECONDS = 60


def _shared_user_ids() -> set:
    """User ids many callers share (built-in defaults): never proof of the same caller."""
    ids = {"default-user", "default-user-id"}
    try:
        from shared.src.lib.utils.app_utils import DEFAULT_USER_ID
        ids.add(str(DEFAULT_USER_ID))
    except Exception:
        pass
    try:
        from shared.src.lib.config.constants import APP_CONFIG
        ids.add(str(APP_CONFIG.get("DEFAULT_USER_ID")))
    except Exception:
        pass
    return ids


def _lock_age_text(lock: Optional[Dict[str, Any]]) -> str:
    try:
        locked_at = float((lock or {}).get("locked_at") or 0)
    except (TypeError, ValueError):
        locked_at = 0
    if not locked_at:
        return "an unknown time"
    return datetime.fromtimestamp(locked_at, tz=timezone.utc).strftime("%H:%M:%S UTC")


def live_foreign_execution(
    host_name: str,
    device_id: str,
    caller_sessions: Optional[List[str]] = None,
    caller_user_id: Optional[str] = None,
    host_data: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """Refusal payload when force_unlock would kill ANOTHER caller's live run, else None.

    force_unlock may clear a stale lock (the host reports nothing running) or the
    caller's own lock (same session / user). It must not abort a live script, deployment
    or testcase that belongs to someone else (BUG-0679). Host unreachable counts as live:
    the abort could not be delivered anyway and the stale-lock probe cleans up later.
    """
    lock = get_device_lock_info(host_name, device_id)
    if lock:
        if lock.get("owner_type") not in EXECUTION_LOCK_OWNER_TYPES:
            return None  # manual_control etc: not a running execution; other paths decide
        owner_session = lock.get("owner_session_id")
        owner_user = lock.get("owner_user_id")
        # The default/built-in user id is shared by every API-key and fallback caller:
        # matching on it would make everyone "the same owner", so only a personal id counts.
        same_user = bool(
            caller_user_id and owner_user == caller_user_id
            and str(caller_user_id) not in _shared_user_ids()
        )
        if (owner_session and owner_session in (caller_sessions or [])) or same_user:
            return None

    if host_data is None:
        from backend_server.src.lib.utils.server_utils import get_host_manager
        host_data = get_host_manager().get_host(host_name)

    active_jobs: List[Dict[str, Any]] = []
    if host_data:
        from shared.src.lib.utils.build_url_utils import call_host
        try:
            resp, status = call_host(
                host_data, f"/host/system/device/{device_id}/is_busy", method="GET", timeout=10
            )
            if status == 200 and isinstance(resp, dict):
                if not resp.get("busy"):
                    try:
                        age = time.time() - float((lock or {}).get("locked_at") or 0)
                    except (TypeError, ValueError):
                        age = float("inf")
                    if lock and age < FRESH_EXECUTION_LOCK_GRACE_SECONDS:
                        active_jobs = [{"type": "starting", "started_at": _lock_age_text(lock)}]
                    else:
                        return None  # stale lock / nothing running
                else:
                    active_jobs = resp.get("active_jobs") or []
        except Exception as err:
            print(f"⚠️ [LOCK] is_busy probe failed for {host_name}:{device_id}: {err}")
    if not lock and not active_jobs:
        return None  # no lock and no evidence of a live run: nothing to protect

    reason = (lock or {}).get("lock_reason") or (lock or {}).get("owner_type") or (
        (active_jobs[0].get("type") if active_jobs else None) or "execution"
    )
    owner = (
        (lock or {}).get("owner_user_name")
        or (lock or {}).get("owner_user_id")
        or (lock or {}).get("owner_session_id")
        or "another caller"
    )
    since = _lock_age_text(lock) if lock else (active_jobs[0].get("started_at") or "an unknown time")
    return {
        "success": False,
        "aborted": False,
        "released": False,
        "error": (
            f"device busy: {reason} by {owner} since {since}; "
            "force_unlock does not abort another caller's live run"
        ),
        "errorType": "device_busy",
        "lock_info": lock,
        "details": {"active_jobs": active_jobs},
    }


def abort_and_force_unlock(
    host_name: str,
    device_id: str,
    *,
    strict: bool,
    protect_others: bool = False,
    caller_sessions: Optional[List[str]] = None,
    caller_user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Kill whatever is running on a device, then clear its lock.

    Single implementation of the abort-then-force sequence used by ``/forceUnlock``
    and by the force_unlock path of script/campaign execute. Clearing the server lock
    without killing the host process is split-brain: the lock says free, the script
    keeps driving the device.

    ``protect_others=True`` (API/MCP callers): refuse with ``device_busy`` instead of
    aborting a live run owned by someone other than the caller. Human UI paths
    (``/forceUnlock``, Force Takeover) leave it False.

    ``strict=True`` (a NEW execution is about to start): refuse on abort failure —
    starting a second run on a device that may still be busy is worse than failing.
    ``strict=False`` (a human is reclaiming the device): always clear the lock. The
    user's problem is the stuck lock; a host that is unreachable or has nothing
    running must not leave them wedged.

    Returns ``{'success', 'aborted', 'released', 'error', 'errorType', 'details'}``.
    On ``success=False`` the caller should surface ``error``/``errorType`` (409).
    """
    from backend_server.src.lib.utils.server_utils import get_host_manager

    if protect_others:
        # Programmatic callers (API/MCP): never kill another caller's live run.
        refusal = live_foreign_execution(host_name, device_id, caller_sessions, caller_user_id)
        if refusal:
            return refusal

    existing_lock = get_device_lock_info(host_name, device_id)
    owner_type = existing_lock.get("owner_type") if existing_lock else None

    # Called even with no lock: testcases drive the device without taking one, so
    # "no lock" does not mean "nothing running". abort_running_execution decides which
    # endpoints apply for this owner_type.
    host_data = get_host_manager().get_host(host_name)
    if host_data:
        try:
            abort_result = abort_running_execution(host_data, device_id, owner_type)
        except Exception as abort_err:
            abort_result = {
                "success": False,
                "aborted": False,
                "error": f"Abort call failed: {abort_err}",
                "details": {},
            }
    else:
        abort_result = {
            "success": False,
            "aborted": False,
            "error": f"Host {host_name} not in registry, cannot abort execution",
            "details": {},
        }

    print(
        f"🔓 [LOCK] Abort for {host_name}:{device_id} (owner={owner_type}): "
        f"success={abort_result.get('success')} aborted={abort_result.get('aborted')} "
        f"details={abort_result.get('details')}"
    )

    if strict and not abort_result.get("success"):
        return {
            "success": False,
            "aborted": abort_result.get("aborted", False),
            "released": False,
            "error": abort_result.get("error") or "Failed to abort running execution",
            "errorType": "preemption_failed",
            "details": abort_result.get("details"),
        }

    unlock_result = force_unlock_device(host_name, device_id)
    return {
        "success": bool(unlock_result.get("success")),
        "aborted": abort_result.get("aborted", False),
        "released": bool(unlock_result.get("released")),
        "lock_info": unlock_result.get("lock_info"),
        "details": abort_result.get("details"),
    }
