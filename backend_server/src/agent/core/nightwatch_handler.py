"""
Nightwatch Handler - Incident/Alert Background Tasks

Handles alerts from p1_alerts queue.
Supports dry-run mode for monitoring without AI processing.
In dry-run mode: logs only, NO Slack (avoids rate limits).

AI PROCESSING FILTERS:
1. DURATION FILTER (ALERT_MIN_DURATION_SECONDS = 30s):
   - Only alerts lasting >= 30 seconds are processed with AI
   - Short events are dropped and marked as checked_by='system'
   - Prevents AI processing of transient/flickering issues

2. RATE LIMIT FILTER (ALERT_RATE_LIMIT_SECONDS = 3600s):
   - Max 1 AI analysis per device per hour
   - Subsequent alerts within window are dropped and marked as checked_by='system'
   - Prevents token usage explosion from repeated alerts on same device
   - Rate limit tracked per host_name/device_id in Redis

Both filters help control AI token costs while maintaining alert visibility in DB.
Filters are configured as class constants and can be adjusted in this file.
"""

import hashlib
import json
import os
import re
import time
from datetime import datetime, timezone
from typing import Dict, Any, Optional
from urllib.parse import urlparse

from shared.src.lib.utils.supabase_utils import get_supabase_client


class NightwatchHandler:
    """Handler for Nightwatch (monitor) background tasks"""

    def __init__(self, nickname: str = "Nightwatch"):
        self.nickname = nickname
        # Duration gate
        self.alert_min_duration_seconds = max(
            0, int(os.getenv("INCIDENT_AI_MIN_DURATION_SECONDS", "30"))
        )
        # Repeated-signature policy: analyze first, then every Nth repeated occurrence
        self.repeat_every_occurrence = max(
            2, int(os.getenv("INCIDENT_AI_REPEAT_EVERY_OCCURRENCE", "10"))
        )
        # Cooldown after an analyzed incident signature (seconds)
        self.signature_cooldown_seconds = max(
            0, int(os.getenv("INCIDENT_AI_SIGNATURE_COOLDOWN_SECONDS", "2700"))
        )
        # Budget cap per device per hour
        self.per_device_hourly_cap = max(
            1, int(os.getenv("INCIDENT_AI_PER_DEVICE_HOURLY_CAP", "12"))
        )
        # Sampling by severity
        self.low_sample_percent = self._clamp_percent(
            os.getenv("INCIDENT_AI_LOW_SAMPLE_PERCENT", "15")
        )
        self.medium_sample_percent = self._clamp_percent(
            os.getenv("INCIDENT_AI_MEDIUM_SAMPLE_PERCENT", "40")
        )
        self.high_sample_percent = self._clamp_percent(
            os.getenv("INCIDENT_AI_HIGH_SAMPLE_PERCENT", "100")
        )
        self.critical_sample_percent = self._clamp_percent(
            os.getenv("INCIDENT_AI_CRITICAL_SAMPLE_PERCENT", "100")
        )

        self._supabase = None
        self._redis_local_client = None
        self._redis_upstash = None

    @staticmethod
    def _clamp_percent(value: str) -> int:
        try:
            parsed = int(value)
        except Exception:
            parsed = 0
        return min(100, max(0, parsed))

    @staticmethod
    def _normalize_text(value: str) -> str:
        if not value:
            return "empty"
        text = str(value).lower()
        text = re.sub(r"[0-9a-f]{8,}", "<hex>", text)
        text = re.sub(r"\d+", "<n>", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text[:240] or "empty"

    def _normalize_metadata_signature(self, task_data: Dict[str, Any]) -> str:
        metadata = task_data.get('metadata', {})
        if isinstance(metadata, str):
            try:
                metadata = json.loads(metadata)
            except Exception:
                metadata = {}
        if not isinstance(metadata, dict):
            metadata = {}

        incident_type = str(task_data.get('incident_type') or task_data.get('alert_type') or 'unknown')
        host_name = str(task_data.get('host_name') or 'unknown')
        device_id = str(task_data.get('device_id') or 'unknown')
        summary_bits = [
            self._normalize_text(incident_type),
            self._normalize_text(host_name),
            self._normalize_text(device_id),
            self._normalize_text(metadata.get('reason') or metadata.get('message') or ''),
            self._normalize_text(str(metadata.get('freeze', ''))),
            self._normalize_text(str(metadata.get('blackscreen', ''))),
            self._normalize_text(str(metadata.get('audio', ''))),
            self._normalize_text(str(metadata.get('mean_volume_db', ''))),
            self._normalize_text(str(task_data.get('status', 'active'))),
        ]
        base = "|".join(summary_bits)
        return hashlib.sha1(base.encode("utf-8"), usedforsecurity=False).hexdigest()[:20]

    def _infer_severity(self, task_data: Dict[str, Any]) -> str:
        metadata = task_data.get('metadata', {})
        if isinstance(metadata, str):
            try:
                metadata = json.loads(metadata)
            except Exception:
                metadata = {}
        if not isinstance(metadata, dict):
            metadata = {}

        explicit = str(metadata.get('severity') or task_data.get('severity') or '').lower()
        if explicit in {"critical", "high", "medium", "low"}:
            return explicit

        consecutive = int(task_data.get('consecutive_count') or 0)
        if consecutive >= 10:
            return "critical"
        if consecutive >= 5:
            return "high"
        if consecutive >= 3:
            return "medium"
        return "low"

    def _sample_percent_for_severity(self, severity: str) -> int:
        if severity == "critical":
            return self.critical_sample_percent
        if severity == "high":
            return self.high_sample_percent
        if severity == "medium":
            return self.medium_sample_percent
        return self.low_sample_percent

    def _get_supabase(self):
        if self._supabase is None:
            self._supabase = get_supabase_client()
        return self._supabase

    def _mark_strategy_skip(self, alert_id: str, reason: str) -> None:
        """Persist strategy skip decision for traceability."""
        try:
            supabase = self._get_supabase()
            if not supabase:
                print(f"[{self.nickname}] ⚠️ Supabase unavailable for strategy skip: {alert_id}")
                return
            supabase.table("alerts").update({
                "checked": True,
                "check_type": "ai_strategy_skip",
                "discard": False,
                "discard_comment": f"[STRATEGY_SKIP] {reason[:300]}",
                "updated_at": datetime.now(timezone.utc).isoformat()
            }).eq("id", alert_id).execute()
        except Exception as e:
            print(f"[{self.nickname}] ⚠️ Failed to mark strategy skip for alert {alert_id}: {e}")
    
    def should_process_with_ai(self, task_id: str, task_data: Dict[str, Any]) -> bool:
        """
        Check if alert should be processed with AI based on anti-flood policy.
        
        Returns:
            True if should process with AI, False if should skip
        """
        host_name = task_data.get('host_name', 'unknown')
        device_id = task_data.get('device_id', 'unknown')
        signature = self._normalize_metadata_signature(task_data)
        severity = self._infer_severity(task_data)
        sample_percent = self._sample_percent_for_severity(severity)

        # 1) Duration gate
        if task_data.get('start_time'):
            try:
                start_dt = datetime.fromisoformat(str(task_data.get('start_time')).replace('Z', '+00:00'))
                duration_seconds = (datetime.now(timezone.utc) - start_dt).total_seconds()
                if duration_seconds < self.alert_min_duration_seconds:
                    reason = (
                        f"duration {duration_seconds:.1f}s < min {self.alert_min_duration_seconds}s "
                        f"(severity={severity}, signature={signature})"
                    )
                    self._mark_strategy_skip(task_id, reason)
                    print(f"[{self.nickname}] ⏭️ Skip {task_id}: {reason}")
                    return False
            except Exception as duration_error:
                print(f"[{self.nickname}] ⚠️ Duration parsing failed for {task_id}: {duration_error}")

        # 2) Severity-aware deterministic sampling
        if sample_percent < 100:
            bucket = int(hashlib.md5(task_id.encode("utf-8"), usedforsecurity=False).hexdigest(), 16) % 100
            if bucket >= sample_percent:
                reason = (
                    f"severity={severity} sampled out ({bucket} >= {sample_percent}), "
                    f"signature={signature}"
                )
                self._mark_strategy_skip(task_id, reason)
                print(f"[{self.nickname}] ⏭️ Skip {task_id}: {reason}")
                return False

        # 3) Signature occurrence + cooldown + per-device budget
        try:
            occurrence = self._redis_incr_with_ttl(
                self._signature_occurrence_key(host_name, device_id, signature),
                ttl_seconds=max(2 * 24 * 3600, self.signature_cooldown_seconds + 3600)
            )
            if occurrence is None:
                occurrence = 1

            if occurrence != 1 and (occurrence % self.repeat_every_occurrence) != 0:
                reason = (
                    f"signature occurrence {occurrence} skipped "
                    f"(analyze first then every {self.repeat_every_occurrence}), signature={signature}"
                )
                self._mark_strategy_skip(task_id, reason)
                print(f"[{self.nickname}] ⏭️ Skip {task_id}: {reason}")
                return False

            last_analyzed = self._redis_get_float(
                self._signature_last_analyzed_key(host_name, device_id, signature)
            )
            now_ts = time.time()
            if last_analyzed and self.signature_cooldown_seconds > 0:
                since_last = now_ts - last_analyzed
                if since_last < self.signature_cooldown_seconds:
                    reason = (
                        f"signature cooldown active ({since_last:.0f}s < {self.signature_cooldown_seconds}s), "
                        f"signature={signature}"
                    )
                    self._mark_strategy_skip(task_id, reason)
                    print(f"[{self.nickname}] ⏭️ Skip {task_id}: {reason}")
                    return False

            device_budget_key = self._device_budget_key(host_name, device_id, now_ts)
            device_hour_count = self._redis_incr_with_ttl(device_budget_key, ttl_seconds=2 * 3600)
            if device_hour_count and device_hour_count > self.per_device_hourly_cap:
                reason = (
                    f"per-device hourly cap exceeded ({device_hour_count} > {self.per_device_hourly_cap}), "
                    f"host={host_name}, device={device_id}"
                )
                self._mark_strategy_skip(task_id, reason)
                print(f"[{self.nickname}] ⏭️ Skip {task_id}: {reason}")
                return False

            # Reserve signature cooldown window now to prevent burst re-analysis.
            self._redis_setex(
                self._signature_last_analyzed_key(host_name, device_id, signature),
                self.signature_cooldown_seconds or 60,
                str(now_ts)
            )
        except Exception as policy_error:
            # Fail-open for analysis to avoid dropping incidents on policy backend failure.
            print(f"[{self.nickname}] ⚠️ Policy backend failed, allowing analysis: {policy_error}")

        print(
            f"[{self.nickname}] ✅ Analyze {task_id}: severity={severity}, "
            f"sample={sample_percent}%, signature={signature}"
        )
        return True

    def update_rate_limit(self, task_data: Dict[str, Any]):
        """
        Backward-compatible hook called after successful AI processing.
        Records last-analysis timestamp per host/device for observability.
        """
        try:
            host_name = task_data.get('host_name', 'unknown')
            device_id = task_data.get('device_id', 'unknown')
            key = f"nightwatch:last_success:{host_name}:{device_id}"
            self._redis_setex(key, 24 * 3600, str(time.time()))
        except Exception as e:
            print(f"[{self.nickname}] ⚠️ Failed to update post-analysis marker: {e}")

    def _setup_redis(self):
        """Initialize Redis access (local TCP or Upstash REST)."""
        if self._redis_local_client or self._redis_upstash:
            return

        redis_url = os.getenv('REDIS_URL', '').strip()
        if not redis_url:
            return

        if redis_url.startswith('https://'):
            redis_token = os.getenv('REDIS_TOKEN', '').strip()
            if not redis_token:
                print(f"[{self.nickname}] REDIS_TOKEN required for Upstash Redis")
                return
            self._redis_upstash = {
                'url': redis_url,
                'headers': {
                    'Authorization': f'Bearer {redis_token}',
                    'Content-Type': 'application/json'
                }
            }
            return

        if redis_url.startswith('redis://') or redis_url.startswith('rediss://'):
            try:
                import redis
                parsed = urlparse(redis_url)
                self._redis_local_client = redis.Redis(
                    host=parsed.hostname or 'localhost',
                    port=parsed.port or 6379,
                    password=parsed.password or os.getenv('REDIS_PASSWORD'),
                    db=int(parsed.path.strip('/')) if parsed.path and parsed.path != '/' else 0,
                    decode_responses=True,
                    socket_timeout=5,
                    socket_connect_timeout=5,
                    ssl=(parsed.scheme == 'rediss')
                )
            except Exception as e:
                print(f"[{self.nickname}] Failed to initialize local Redis client: {e}")

    def _redis_command(self, command: list):
        self._setup_redis()
        if self._redis_upstash:
            try:
                import requests
                response = requests.post(
                    self._redis_upstash['url'],
                    headers=self._redis_upstash['headers'],
                    json=command,
                    timeout=10
                )
                if response.status_code == 200:
                    return response.json()
            except Exception as e:
                print(f"[{self.nickname}] Upstash command failed {command[0]}: {e}")
            return None

        if self._redis_local_client:
            try:
                cmd = command[0].upper()
                if cmd == 'GET':
                    return {'result': self._redis_local_client.get(command[1])}
                if cmd == 'SETEX':
                    self._redis_local_client.setex(command[1], int(command[2]), command[3])
                    return {'result': 'OK'}
                if cmd == 'INCR':
                    return {'result': self._redis_local_client.incr(command[1])}
                if cmd == 'EXPIRE':
                    return {'result': self._redis_local_client.expire(command[1], int(command[2]))}
            except Exception as e:
                print(f"[{self.nickname}] Local Redis command failed {command[0]}: {e}")
            return None

        return None

    def _redis_get_float(self, key: str) -> Optional[float]:
        result = self._redis_command(['GET', key])
        if not result:
            return None
        raw = result.get('result')
        if raw in (None, ''):
            return None
        try:
            return float(raw)
        except Exception:
            return None

    def _redis_setex(self, key: str, ttl_seconds: int, value: str) -> None:
        ttl = max(1, int(ttl_seconds))
        self._redis_command(['SETEX', key, ttl, value])

    def _redis_incr_with_ttl(self, key: str, ttl_seconds: int) -> Optional[int]:
        result = self._redis_command(['INCR', key])
        if not result or result.get('result') is None:
            return None
        count = int(result.get('result'))
        # Set expiry only on first seen key.
        if count == 1:
            self._redis_command(['EXPIRE', key, max(1, int(ttl_seconds))])
        return count

    @staticmethod
    def _device_budget_key(host_name: str, device_id: str, ts: float) -> str:
        hour_bucket = int(ts // 3600)
        return f"nightwatch:device_budget:{host_name}:{device_id}:{hour_bucket}"

    @staticmethod
    def _signature_occurrence_key(host_name: str, device_id: str, signature: str) -> str:
        return f"nightwatch:sig:occ:{host_name}:{device_id}:{signature}"

    @staticmethod
    def _signature_last_analyzed_key(host_name: str, device_id: str, signature: str) -> str:
        return f"nightwatch:sig:last:{host_name}:{device_id}:{signature}"
    
    def handle_dry_run_task(self, task_type: str, task_id: str, task_data: Dict[str, Any], queue_name: str):
        """Handle task in dry-run mode: print, emit Socket.IO, send to Slack, but no AI processing"""
        print(f"[{self.nickname}] 🏃 DRY RUN MODE - Task received:")
        print(f"[{self.nickname}]    Type: {task_type}")
        print(f"[{self.nickname}]    ID: {task_id}")
        print(f"[{self.nickname}]    Queue: {queue_name}")
        print(f"[{self.nickname}]    Data: {json.dumps(task_data, indent=2, default=str)[:500]}...")
        
        # Get Socket.IO manager
        from ..socket_manager import socket_manager
        
        # Build event for Socket.IO
        event_content = self.build_event_content(task_type, task_id, task_data)
        
        event_dict = {
            'type': 'incident_received',
            'agent': self.nickname,
            'content': event_content,
            'timestamp': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
            'task_id': task_id,
            'task_type': task_type,
            'task_data': task_data,
            'queue_name': queue_name,
            'dry_run': True,
        }
        
        # Emit to Socket.IO background_tasks room
        try:
            socket_manager.emit_to_room(
                room='background_tasks',
                event='agent_event',
                data=event_dict,
                namespace='/agent'
            )
            print(f"[{self.nickname}] 📡 Emitted dry-run event to background_tasks room")
        except Exception as emit_error:
            print(f"[{self.nickname}] ⚠️  Failed to emit event: {emit_error}")
        
        # DRY RUN: No Slack to avoid rate limits - just log + Socket.IO
        print(f"[{self.nickname}] ✅ DRY RUN complete for task {task_id} (no Slack)")
    
    def build_event_content(self, task_type: str, task_id: str, task_data: Dict[str, Any]) -> str:
        """Build human-readable event content for dry-run mode"""
        # Alert data structure: incident_type, host_name, device_name, status, consecutive_count, metadata
        incident_type = task_data.get('incident_type') or task_data.get('alert_type', 'unknown')
        host_name = task_data.get('host_name', 'Unknown')
        device_name = task_data.get('device_name', '')
        status = task_data.get('status', 'active')
        consecutive_count = task_data.get('consecutive_count', 0)
        
        # Extract severity from metadata if available
        metadata = task_data.get('metadata', {})
        if isinstance(metadata, str):
            try:
                metadata = json.loads(metadata)
            except:
                metadata = {}
        
        # Build summary from metadata
        summary_parts = []
        if metadata.get('freeze'):
            summary_parts.append('FREEZE detected')
        if metadata.get('blackscreen'):
            summary_parts.append('BLACKSCREEN detected')
        if metadata.get('audio') is False or metadata.get('mean_volume_db', 0) < -80:
            summary_parts.append('AUDIO LOSS detected')
        
        summary = ' | '.join(summary_parts) if summary_parts else f'{incident_type} detected'
        device_info = f" ({device_name})" if device_name else ""
        
        return f"""ALERT_ID: {task_id}
TYPE: {incident_type}
HOST: {host_name}{device_info}
STATUS: {status}
COUNT: {consecutive_count}
SUMMARY: {summary}"""
    
    def build_task_message(self, task_type: str, task_id: str, task_data: Dict[str, Any]) -> str:
        """Build agent message for actual processing (non dry-run mode)"""
        # Alert data structure from DB
        incident_type = task_data.get('incident_type') or task_data.get('alert_type', 'unknown')
        host_name = task_data.get('host_name', 'Unknown')
        device_name = task_data.get('device_name', '')
        status = task_data.get('status', 'active')
        consecutive_count = task_data.get('consecutive_count', 0)
        start_time = task_data.get('start_time', '')
        
        # Parse metadata for details
        metadata = task_data.get('metadata', {})
        if isinstance(metadata, str):
            try:
                metadata = json.loads(metadata)
            except:
                metadata = {}
        
        # Build context from metadata
        context_lines = []
        if metadata.get('freeze'):
            freeze_debug = metadata.get('freeze_debug', {})
            context_lines.append(f"- FREEZE: {freeze_debug.get('frames_found', '?')} frozen frames detected")
        if metadata.get('blackscreen'):
            context_lines.append(f"- BLACKSCREEN: {metadata.get('blackscreen_percentage', '?')}% black")
        if metadata.get('mean_volume_db') is not None:
            context_lines.append(f"- AUDIO: {metadata.get('mean_volume_db', '?')} dB")
        if metadata.get('r2_images', {}).get('thumbnail_urls'):
            context_lines.append(f"- IMAGES: {len(metadata['r2_images']['thumbnail_urls'])} thumbnails available")
        
        context = '\n'.join(context_lines) if context_lines else 'No additional context'
        device_info = f" ({device_name})" if device_name else ""
        
        return f"""Analyze this alert and determine appropriate action:

ALERT_ID: {task_id}
TYPE: {incident_type}
HOST: {host_name}{device_info}
STATUS: {status}
CONSECUTIVE_COUNT: {consecutive_count}
START_TIME: {start_time}

DETECTION DETAILS:
{context}

Based on the alert, determine:
1. Is this a real incident requiring action?
2. What is the root cause?
3. What action should be taken?
"""
    
    def send_to_slack(self, task_type: str, task_id: str, task_data: Dict[str, Any], result: str = None, dry_run: bool = False):
        """Send incident event to Slack #nightwatch channel (only when dry_run=False)"""
        try:
            try:
                from backend_server.src.integrations.agent_slack_hook import send_to_slack_channel
                SLACK_AVAILABLE = True
            except ImportError:
                SLACK_AVAILABLE = False
                return
            
            if not SLACK_AVAILABLE:
                return
            
            # Extract alert data
            incident_type = task_data.get('incident_type') or task_data.get('alert_type', 'unknown')
            host_name = task_data.get('host_name', 'Unknown')
            device_name = task_data.get('device_name', '')
            status = task_data.get('status', 'active')
            consecutive_count = task_data.get('consecutive_count', 0)
            
            # Parse metadata
            metadata = task_data.get('metadata', {})
            if isinstance(metadata, str):
                try:
                    metadata = json.loads(metadata)
                except:
                    metadata = {}
            
            # Build summary from metadata
            issues = []
            if metadata.get('freeze'):
                issues.append('🧊 FREEZE')
            if metadata.get('blackscreen'):
                issues.append('⬛ BLACKSCREEN')
            if metadata.get('audio') is False or metadata.get('mean_volume_db', 0) < -80:
                issues.append('🔇 AUDIO LOSS')
            
            issues_str = ' | '.join(issues) if issues else incident_type
            device_info = f" ({device_name})" if device_name else ""
            
            # Severity based on consecutive count
            if consecutive_count >= 10:
                severity_emoji = "🔴"
                severity = "critical"
            elif consecutive_count >= 5:
                severity_emoji = "🟠"
                severity = "high"
            else:
                severity_emoji = "🟡"
                severity = "normal"
            
            slack_message = f"""
{severity_emoji} *{self.nickname} Alert*

*Type*: `{incident_type}`
*Host*: `{host_name}`{device_info}
*Issues*: {issues_str}
*Status*: {status} (count: {consecutive_count})
*Severity*: {severity}

*Alert ID*: `{task_id}`
"""
            
            # Add result if provided (non dry-run)
            if result:
                slack_message += f"\n*Analysis*:\n```\n{result[:500]}...\n```"
            
            # Send to #nightwatch channel
            send_to_slack_channel(
                channel='#nightwatch',
                message=slack_message,
                agent_name=self.nickname
            )
            print(f"[{self.nickname}] 📬 Sent event to Slack #nightwatch")
            
        except Exception as e:
            print(f"[{self.nickname}] ⚠️  Failed to send to Slack: {e}")
