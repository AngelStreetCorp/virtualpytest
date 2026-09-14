"""
Redis Queue Processor

Handles Redis queue operations supporting both:
- Upstash Redis REST API (cloud)
- Local Redis TCP connection (self-hosted)

Processes tasks in priority order: P1 (alerts) → P2 (scripts) → P3 (reserved)
"""

import requests
import json
import os
from typing import Optional, Dict, Any
from datetime import datetime


class RedisQueueProcessor:
    """Queue processor supporting both Upstash REST API and local Redis"""

    MAX_QUEUED_PER_DEVICE = 5  # Max alerts queued per device to prevent unbounded growth

    def __init__(self):
        self.queues = ['p1_alerts', 'p2_scripts', 'p3_reserved']
        self.redis_mode = None

        # Unified Redis configuration - auto-detect based on URL format
        redis_url = os.getenv('REDIS_URL')
        redis_token = os.getenv('REDIS_TOKEN')
        redis_password = os.getenv('REDIS_PASSWORD')

        # DEBUG: Log the Redis URL being used (mask sensitive info)
        masked_url = redis_url
        if redis_url and ':' in redis_url and '@' in redis_url:
            # Mask password in redis://:password@host:port format
            parts = redis_url.split('@')
            if len(parts) == 2 and parts[0].startswith('redis://:'):
                masked_url = f"redis://:***@{parts[1]}"
        # Debug logging removed - use proper logger if needed

        if not redis_url:
            raise ValueError(
                "Redis configuration missing. Set REDIS_URL:\n"
                "  Cloud (Upstash): REDIS_URL=https://xxx.upstash.io (requires REDIS_TOKEN)\n"
                "  Local: REDIS_URL=redis://localhost:6379 (optional REDIS_PASSWORD)"
            )

        # Detect connection type based on URL format
        if redis_url.startswith('https://'):
            # Upstash Redis REST API (cloud)
            if not redis_token:
                raise ValueError("REDIS_TOKEN required for Upstash (HTTPS) Redis URL")
            
            self.redis_mode = 'upstash'
            self.redis_url = redis_url
            self.headers = {
                'Authorization': f'Bearer {redis_token}',
                'Content-Type': 'application/json'
            }
            print(f"[@redis_queue] Upstash Redis REST API: {redis_url[:50]}...")
            return

        elif redis_url.startswith('redis://') or redis_url.startswith('rediss://'):
            # Local Redis TCP connection (parse redis:// URL)
            try:
                import redis
                from urllib.parse import urlparse
                
                parsed = urlparse(redis_url)
                self.redis_mode = 'local'
                
                # Extract connection details from URL
                host = parsed.hostname or 'localhost'
                port = parsed.port or 6379
                password = parsed.password or redis_password
                db = int(parsed.path.strip('/')) if parsed.path and parsed.path != '/' else 0
                
                self.redis_client = redis.Redis(
                    host=host,
                    port=port,
                    password=password,
                    db=db,
                    decode_responses=True,
                    socket_timeout=5,
                    socket_connect_timeout=5,
                    ssl=(parsed.scheme == 'rediss')
                )
                print(f"[@redis_queue] Local Redis: {host}:{port} (db {db})")
                return
                
            except ImportError:
                raise ValueError("redis-py library not installed. Install: pip install redis")

        else:
            raise ValueError(
                f"Invalid REDIS_URL format: {redis_url}\n"
                "  Cloud: https://xxx.upstash.io\n"
                "  Local: redis://localhost:6379 or redis://:password@host:port/db"
            )
    
    def _redis_command_upstash(self, command: list) -> Optional[dict]:
        """Execute Redis command via Upstash REST API"""
        try:
            response = requests.post(
                self.redis_url,
                headers=self.headers,
                json=command,
                timeout=10
            )

            if response.status_code == 200:
                return response.json()
            else:
                print(f"[@redis_queue] Upstash Redis API error: {response.status_code} - {response.text}")

        except Exception as e:
            print(f"[@redis_queue] Upstash Redis command failed: {e}")

        return None

    def _redis_command_local(self, command: list) -> Optional[dict]:
        """Execute Redis command via local TCP connection"""
        try:
            cmd = command[0].upper()
            if cmd == 'LPUSH':
                # LPUSH queue_name value
                result = self.redis_client.lpush(command[1], command[2])
                return {'result': result}
            elif cmd == 'LLEN':
                # LLEN queue_name
                result = self.redis_client.llen(command[1])
                return {'result': result}
            elif cmd == 'DEL':
                # DEL key
                result = self.redis_client.delete(command[1])
                return {'result': result}
            elif cmd == 'LRANGE':
                # LRANGE key start end
                result = self.redis_client.lrange(command[1], int(command[2]), int(command[3]))
                return {'result': result}
            elif cmd == 'LPOP':
                # LPOP queue_name
                result = self.redis_client.lpop(command[1])
                return {'result': result}
            elif cmd == 'PING':
                # PING
                result = self.redis_client.ping()
                return {'result': 'PONG' if result else None}
            else:
                print(f"[@redis_queue] Unsupported Redis command: {cmd}")
                return None

        except Exception as e:
            print(f"[@redis_queue] Local Redis command failed: {e}")
            return None

    def _redis_command(self, command: list) -> Optional[dict]:
        """Execute Redis command - routes to appropriate backend"""
        if self.redis_mode == 'upstash':
            return self._redis_command_upstash(command)
        elif self.redis_mode == 'local':
            return self._redis_command_local(command)
        else:
            print(f"[@redis_queue] Unknown Redis mode: {self.redis_mode}")
            return None
    
    def _evict_oldest_device_alerts(self, queue_name: str, host_name: str, device_id: str) -> int:
        """Evict oldest alerts for a device when over per-device limit.

        Reads the full queue, keeps only the most recent MAX_QUEUED_PER_DEVICE-1
        alerts for this device (leaving room for the new one), rewrites the queue.
        Returns number of evicted items.
        """
        try:
            items_raw = self._redis_command(['LRANGE', queue_name, '0', '-1'])
            if not items_raw or 'result' not in items_raw:
                return 0

            raw_items = items_raw['result']
            # Parse all items and track which belong to this device
            all_items = []  # (raw_string, parsed, is_this_device)
            for raw in raw_items:
                try:
                    parsed = json.loads(raw) if isinstance(raw, str) else raw
                except (json.JSONDecodeError, TypeError):
                    all_items.append((raw if isinstance(raw, str) else json.dumps(raw), None, False))
                    continue
                data = parsed.get('data', {})
                is_match = data.get('host_name') == host_name and data.get('device_id') == device_id
                all_items.append((raw if isinstance(raw, str) else json.dumps(raw), parsed, is_match))

            device_items = [i for i in all_items if i[2]]
            if len(device_items) < self.MAX_QUEUED_PER_DEVICE:
                return 0

            # Keep only the newest MAX_QUEUED_PER_DEVICE-1 for this device
            # Queue order: index 0 = newest (LPUSH), so device_items are already newest-first
            keep_count = self.MAX_QUEUED_PER_DEVICE - 1
            device_to_keep = set(id(item) for item in device_items[:keep_count])
            evicted = len(device_items) - keep_count

            # Rebuild queue: keep non-device items + kept device items, preserve order
            kept_raw = []
            for item in all_items:
                if not item[2] or id(item) in device_to_keep:
                    kept_raw.append(item[0])

            # Atomic rewrite: DEL + re-push (RPUSH to preserve order since index 0 = newest)
            self._redis_command(['DEL', queue_name])
            if kept_raw:
                for raw in reversed(kept_raw):
                    self._redis_command(['LPUSH', queue_name, raw])

            print(f"[@redis_queue] Evicted {evicted} oldest alerts for {host_name}/{device_id} (kept {keep_count})")
            return evicted

        except Exception as e:
            print(f"[@redis_queue] Error evicting device alerts: {e}")
            return 0

    def add_alert_to_queue(self, alert_id: str, alert_data: Dict[str, Any]) -> bool:
        """Add alert to p1 queue (highest priority), evicting oldest per-device alerts if over limit"""
        try:
            # Evict oldest alerts for this device if at limit
            host_name = alert_data.get('host_name', '')
            device_id = alert_data.get('device_id', '')
            if host_name and device_id:
                self._evict_oldest_device_alerts('p1_alerts', host_name, device_id)

            task = {
                'type': 'alert',
                'id': alert_id,
                'data': alert_data,
                'created_at': datetime.now().isoformat(),
                'priority': 1
            }

            result = self._redis_command(['LPUSH', 'p1_alerts', json.dumps(task)])

            if result and result.get('result'):
                print(f"[@redis_queue] Added alert {alert_id} to P1 queue")
                return True
            else:
                print(f"[@redis_queue] Failed to add alert {alert_id} to queue")
                return False

        except Exception as e:
            print(f"[@redis_queue] Error adding alert to queue: {e}")
            return False
    
    def add_script_to_queue(self, script_id: str, script_data: Dict[str, Any]) -> bool:
        """Add script result to p2 queue"""
        try:
            task = {
                'type': 'script',
                'id': script_id,
                'data': script_data,
                'created_at': datetime.now().isoformat(),
                'priority': 2
            }
            
            result = self._redis_command(['LPUSH', 'p2_scripts', json.dumps(task)])
            
            if result and result.get('result'):
                print(f"[@redis_queue] Added script {script_id} to P2 queue")
                return True
            else:
                print(f"[@redis_queue] Failed to add script {script_id} to queue")
                return False
                
        except Exception as e:
            print(f"[@redis_queue] Error adding script to queue: {e}")
            return False
    
    def get_queue_length(self, queue_name: str) -> int:
        """Get length of specific queue"""
        try:
            result = self._redis_command(['LLEN', queue_name])
            if result and 'result' in result:
                return int(result['result'])
        except Exception as e:
            print(f"[@redis_queue] Error getting queue length for {queue_name}: {e}")
        
        return 0
    
    def get_all_queue_lengths(self) -> Dict[str, int]:
        """Get lengths of all queues"""
        lengths = {}
        for queue in self.queues:
            lengths[queue] = self.get_queue_length(queue)
        return lengths
    
    def clear_queue(self, queue_name: str) -> bool:
        """Clear all items from a specific queue"""
        try:
            result = self._redis_command(['DEL', queue_name])
            if result and result.get('result', 0) >= 0:
                print(f"[@redis_queue] Cleared queue: {queue_name}")
                return True
            else:
                print(f"[@redis_queue] Failed to clear queue: {queue_name}")
                return False
        except Exception as e:
            print(f"[@redis_queue] Error clearing queue {queue_name}: {e}")
            return False

    def peek_queue(self, queue_name: str, limit: int = 50) -> list:
        """Peek at items in a queue without removing them (returns newest items first)"""
        try:
            result = self._redis_command(['LRANGE', queue_name, '0', str(limit - 1)])
            if result and 'result' in result:
                items = result['result']
                # Parse JSON items
                parsed_items = []
                for item in items:
                    try:
                        if isinstance(item, str):
                            parsed_item = json.loads(item)
                        else:
                            parsed_item = item  # Already parsed for local Redis
                        parsed_items.append(parsed_item)
                    except (json.JSONDecodeError, TypeError):
                        continue
                return parsed_items
            else:
                return []
        except Exception as e:
            print(f"[@redis_queue] Error peeking queue {queue_name}: {e}")
            return []

    def health_check(self) -> bool:
        """Check if Redis connection is working"""
        try:
            result = self._redis_command(['PING'])
            if self.redis_mode == 'upstash':
                return result and result.get('result') == 'PONG'
            elif self.redis_mode == 'local':
                return result and result.get('result') == 'PONG'
            else:
                return False
        except Exception as e:
            print(f"[@redis_queue] Health check failed: {e}")
            return False


# Global instance for easy import
_queue_processor = None

def get_queue_processor() -> RedisQueueProcessor:
    """Get or create global queue processor instance"""
    global _queue_processor
    if _queue_processor is None:
        _queue_processor = RedisQueueProcessor()
    return _queue_processor
