"""Deployment Scheduler - Manages periodic script execution with cron expressions"""
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from croniter import croniter
from shared.src.lib.utils.supabase_utils import get_supabase_client
from shared.src.lib.executors.script_executor import ScriptExecutor
from shared.src.lib.executors.campaign_executor import CampaignExecutor
from shared.src.lib.database.campaign_db import get_campaign_by_name
from shared.src.lib.utils.storage_path_utils import get_running_log_path, get_capture_folder_from_device_id
from datetime import datetime, timezone, timedelta
import logging
import threading
import os
import json
import tempfile
import time
import requests
from shared.src.lib.utils.build_url_utils import buildServerUrl, server_auth_headers
from typing import Optional, Dict, Any

# Configure deployment logger
deployment_logger = logging.getLogger('deployment_scheduler')
deployment_logger.setLevel(logging.INFO)

# Cross-platform log path:
# - Prefer installer-provided VIRTUALPYTEST_LOGS (Windows: C:\virtualpytest\logs)
# - Fallback to /tmp on Unix
# - Fallback to system temp on Windows
_log_dir = os.getenv('VIRTUALPYTEST_LOGS')
if not _log_dir:
    if os.name == 'nt':
        _log_dir = os.path.join(tempfile.gettempdir(), 'virtualpytest')
    else:
        _log_dir = '/tmp'
os.makedirs(_log_dir, exist_ok=True)
deployment_handler = logging.FileHandler(os.path.join(_log_dir, 'deployments.log'))
deployment_handler.setFormatter(logging.Formatter(
    '%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
))
deployment_logger.addHandler(deployment_handler)

class DeploymentScheduler:
    def __init__(self, host_name):
        self.host_name = host_name
        self.scheduler = BackgroundScheduler(timezone='UTC')
        self.supabase = get_supabase_client()
        self.db_lock = threading.Lock()  # Serialize concurrent DB operations
        # Device-level queue: device_id -> queued execution requests (max 10 per device)
        self.queued_executions = {}
        self.wait_lock_retry_timers: Dict[str, threading.Timer] = {}
        self.wait_lock_retry_lock = threading.Lock()

    @staticmethod
    def _parse_iso_datetime(value: Optional[str]) -> Optional[datetime]:
        if not value:
            return None
        try:
            return datetime.fromisoformat(value.replace('Z', '+00:00'))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _format_datetime(value: Optional[datetime]) -> Optional[str]:
        if not value:
            return None
        if value.tzinfo is None:
            return value.isoformat()
        return value.astimezone(timezone.utc).isoformat()

    ONE_SHOT_QUEUE_CRON = '0 0 1 1 *'

    @staticmethod
    def _is_recurring_cron(deployment: Dict[str, Any]) -> bool:
        """True for recurring scheduled deployments (not one-shot run-now)."""
        cron = deployment.get('cron_expression')
        return bool(
            cron and cron != DeploymentScheduler.ONE_SHOT_QUEUE_CRON
            and deployment.get('max_executions') != 1
        )

    @staticmethod
    def _is_future_one_shot(deployment: Dict[str, Any]) -> bool:
        start_date = DeploymentScheduler._parse_iso_datetime(deployment.get('start_date'))
        return bool(
            deployment.get('max_executions') == 1 and
            start_date and
            start_date > datetime.now(timezone.utc)
        )

    def _get_job_config(self, deployment: Dict[str, Any]):
        """Return scheduler trigger + job id for a deployment."""
        if self._is_future_one_shot(deployment):
            start_date = self._parse_iso_datetime(deployment.get('start_date'))
            return {
                'trigger': DateTrigger(run_date=start_date, timezone='UTC'),
                'job_id': deployment['id'],
            }

        cron_expr = deployment.get('cron_expression')
        if not cron_expr:
            raise ValueError(f"No cron expression for deployment {deployment.get('id')}")

        parts = cron_expr.split()
        if len(parts) != 5:
            raise ValueError(f"Invalid cron expression: {cron_expr}")

        minute, hour, day, month, day_of_week = parts
        return {
            'trigger': CronTrigger(
                minute=minute,
                hour=hour,
                day=day,
                month=month,
                day_of_week=day_of_week,
                timezone='UTC'
            ),
            'job_id': deployment['id'],
        }

    def get_scheduler_snapshot(self) -> Dict[str, Any]:
        """Return APScheduler and in-memory queue state for debugging."""
        jobs = []
        for job in self.scheduler.get_jobs():
            jobs.append({
                'id': job.id,
                'name': job.name,
                'next_run_time': self._format_datetime(job.next_run_time),
                'pending': getattr(job, 'pending', None),
                'trigger': str(job.trigger),
                'args': list(job.args or []),
                'kwargs': job.kwargs or {},
            })

        queue_snapshot = {}
        for device_id, queue in self.queued_executions.items():
            queue_snapshot[device_id] = [
                {
                    'deployment_id': item.get('deployment_id'),
                    'queued_at': item.get('queued_at'),
                    'execution_id': item.get('execution_id'),
                }
                for item in queue
            ]

        with self.db_lock:
            running_result = self.supabase.table('deployment_executions').select(
                'id, deployment_id, status, scheduled_at, started_at, completed_at, '
                'deployments!inner(host_name, device_id, name)'
            ).eq('status', 'running').eq('deployments.host_name', self.host_name).order(
                'started_at', desc=True
            ).limit(20).execute()

            queued_result = self.supabase.table('deployment_executions').select(
                'id, deployment_id, status, scheduled_at, started_at, completed_at, '
                'deployments!inner(host_name, device_id, name)'
            ).eq('status', 'queued').eq('deployments.host_name', self.host_name).order(
                'scheduled_at', desc=True
            ).limit(20).execute()

        return {
            'host_name': self.host_name,
            'scheduler_running': self.scheduler.running,
            'scheduler_state': self.scheduler.state,
            'job_count': len(jobs),
            'jobs': jobs,
            'queued_executions_by_device': queue_snapshot,
            'running_executions': running_result.data or [],
            'queued_execution_rows': queued_result.data or [],
        }

    def _notify_server_execution_status(
        self,
        *,
        dep: Dict[str, Any],
        execution_id: str,
        status: str,
        started_at: Optional[str] = None,
        completed_at: Optional[str] = None,
        success: Optional[bool] = None,
        result: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
    ) -> None:
        """Notify backend_server of a deployment execution status change."""
        try:
            callback_url = buildServerUrl('server/deployment/executionComplete')
            payload = {
                'deployment_id': dep.get('id'),
                'execution_id': execution_id,
                'host_name': dep.get('host_name') or self.host_name,
                'device_id': dep.get('device_id'),
                'script_name': dep.get('script_name'),
                'team_id': dep.get('team_id'),
                'started_at': started_at,
                'completed_at': completed_at,
                'success': success,
                'status': status,
                'result': result or {},
                'error': error,
                'callback_url': dep.get('callback_url'),
                'lock_owner_session_id': dep.get('_lock_owner_session_id'),
                'lock_owner_job_id': dep.get('_lock_owner_job_id'),
            }
            requests.post(callback_url, json=payload, timeout=10)
        except Exception as notify_error:
            print(f"[@deployment_scheduler] Failed to notify server deployment status ({status}): {notify_error}")

    def _notify_server_execution_complete(
        self,
        *,
        dep: Dict[str, Any],
        execution_id: str,
        started_at: Optional[str],
        completed_at: str,
        success: bool,
        status: str,
        result: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
    ) -> None:
        """Notify backend_server that a deployment execution finished."""
        self._notify_server_execution_status(
            dep=dep, execution_id=execution_id, status=status,
            started_at=started_at, completed_at=completed_at,
            success=success, result=result, error=error,
        )

    def _acquire_server_execution_lock(
        self,
        *,
        host_name: str,
        device_id: str,
        owner_session_id: str,
        owner_job_id: str,
        lock_reason: str,
    ) -> Dict[str, Any]:
        """Acquire device lock on backend_server for deployment execution."""
        try:
            url = buildServerUrl('server/control/acquireExecutionLock')
            payload = {
                'host_name': host_name,
                'device_id': device_id,
                'owner_type': 'deployment_execution',
                'owner_session_id': owner_session_id,
                'owner_job_id': owner_job_id,
                'lock_reason': lock_reason,
                'can_force_takeover': True,
            }
            response = requests.post(url, json=payload, headers=server_auth_headers(), timeout=10)
            response_data = response.json() if response.content else {}
            return {
                'ok': response.status_code == 200 and bool(response_data.get('success')),
                'status_code': response.status_code,
                'data': response_data,
            }
        except Exception as e:
            return {
                'ok': False,
                'status_code': 500,
                'data': {'success': False, 'error': f'lock_acquire_failed: {e}'},
            }

    def _release_server_execution_lock(
        self,
        *,
        host_name: str,
        device_id: str,
        owner_session_id: str,
        owner_job_id: str,
        force: bool = False,
    ) -> None:
        """Release deployment lock on backend_server (best effort)."""
        try:
            url = buildServerUrl('server/control/releaseExecutionLock')
            payload = {
                'host_name': host_name,
                'device_id': device_id,
                'owner_type': 'deployment_execution',
                'owner_session_id': owner_session_id,
                'owner_job_id': owner_job_id,
                'force': force,
            }
            response = requests.post(url, json=payload, headers=server_auth_headers(), timeout=10)
            response_data = response.json() if response.content else {}
            if response.status_code != 200 or not response_data.get('success'):
                print(
                    f"[@deployment_scheduler] Failed to release server execution lock "
                    f"for {host_name}:{device_id}: status={response.status_code}, "
                    f"response={response_data}"
                )
                deployment_logger.warning(
                    f"Failed to release server execution lock for {host_name}:{device_id}: "
                    f"status={response.status_code}, response={response_data}"
                )
        except Exception as e:
            print(f"[@deployment_scheduler] Failed to release server execution lock: {e}")
            deployment_logger.warning(f"Failed to release server execution lock: {e}")

    def _has_pending_wait_lock_retry(self, deployment_id: str) -> bool:
        with self.wait_lock_retry_lock:
            timer = self.wait_lock_retry_timers.get(deployment_id)
            if timer and timer.is_alive():
                return True
            if timer:
                self.wait_lock_retry_timers.pop(deployment_id, None)
            return False

    def _cancel_wait_lock_retry(self, deployment_id: str) -> None:
        with self.wait_lock_retry_lock:
            timer = self.wait_lock_retry_timers.pop(deployment_id, None)
        if timer and timer.is_alive():
            timer.cancel()

    def _start_immediate_execution(
        self,
        deployment_id: str,
        *,
        queued_execution_id: Optional[str] = None,
        reason: str = 'immediate',
    ) -> None:
        """Run an execution path in a dedicated daemon thread, bypassing APScheduler date jobs."""
        thread_name = f"deployment-{reason}-{deployment_id[:8]}"
        worker = threading.Thread(
            target=self._execute_deployment,
            args=(deployment_id, queued_execution_id),
            daemon=True,
            name=thread_name,
        )
        worker.start()
        deployment_logger.info(
            f"🧵 DIRECT EXECUTION: {deployment_id} | reason={reason} | "
            f"queued_execution_id={queued_execution_id or 'none'} | thread={thread_name}"
        )

    def _schedule_wait_lock_retry(
        self,
        deployment_id: str,
        delay_seconds: int = 20,
        queued_execution_id: Optional[str] = None,
    ) -> None:
        if self._has_pending_wait_lock_retry(deployment_id):
            return

        def _run_retry():
            with self.wait_lock_retry_lock:
                self.wait_lock_retry_timers.pop(deployment_id, None)
            self._start_immediate_execution(
                deployment_id,
                queued_execution_id=queued_execution_id,
                reason='waitlock',
            )

        timer = threading.Timer(delay_seconds, _run_retry)
        timer.daemon = True
        with self.wait_lock_retry_lock:
            self.wait_lock_retry_timers[deployment_id] = timer
        timer.start()
        deployment_logger.info(
            f"⏱️ WAIT LOCK RETRY SCHEDULED: {deployment_id} | delay={delay_seconds}s | "
            f"queued_execution_id={queued_execution_id or 'none'}"
        )
        
    def start(self):
        """Start scheduler and sync from DB"""
        print(f"[@deployment_scheduler] Starting for {self.host_name}")
        deployment_logger.info(f"=== DEPLOYMENT SCHEDULER STARTING === Host: {self.host_name}")
        self.scheduler.start()
        print(f"[@deployment_scheduler] APScheduler state: {self.scheduler.state}")
        print(f"[@deployment_scheduler] APScheduler running: {self.scheduler.running}")
        self._sync_from_db()
        # Periodic watchdog to drain orphaned queued items (handles gevent/APScheduler thread death)
        self.scheduler.add_job(
            self._queue_watchdog,
            'interval',
            seconds=60,
            id='__queue_watchdog__',
            replace_existing=True,
            max_instances=1,
        )
        print(f"[@deployment_scheduler] Active jobs count: {len(self.scheduler.get_jobs())}")
        
    def _sync_from_db(self):
        """Load active deployments from Supabase on startup"""
        try:
            # First, clean up any stale "running" executions from previous crashes/restarts
            print(f"[@deployment_scheduler] Checking for stale 'running' executions...")
            deployment_logger.info("Cleaning up stale 'running' executions from previous session...")
            
            try:
                # Get all deployments for this host to find their stale executions
                print(f"[@deployment_scheduler] Querying deployments for host: {self.host_name}")
                deployments_result = self.supabase.table('deployments').select('id').eq('host_name', self.host_name).execute()
                deployment_ids = [d['id'] for d in deployments_result.data]
                print(f"[@deployment_scheduler] Found {len(deployment_ids)} deployment(s) for this host")
                deployment_logger.info(f"Found {len(deployment_ids)} deployment(s) for host {self.host_name}")
                
                if not deployment_ids:
                    print(f"[@deployment_scheduler] No deployments for host {self.host_name}, skipping stale execution check")
                    deployment_logger.info(f"No deployments for host {self.host_name}")
                
                if deployment_ids:
                    # Find all running executions for this host's deployments
                    print(f"[@deployment_scheduler] Checking for running executions in {len(deployment_ids)} deployment(s)...")
                    stale_executions = self.supabase.table('deployment_executions')\
                        .select('id, deployment_id, started_at')\
                        .in_('deployment_id', deployment_ids)\
                        .eq('status', 'running')\
                        .execute()
                    
                    print(f"[@deployment_scheduler] Query returned {len(stale_executions.data) if stale_executions.data else 0} running execution(s)")
                    
                    if stale_executions.data:
                        stale_count = len(stale_executions.data)
                        print(f"[@deployment_scheduler] Found {stale_count} stale 'running' execution(s):")
                        for stale in stale_executions.data:
                            print(f"[@deployment_scheduler]   - Execution {stale['id']} started at {stale.get('started_at', 'unknown')}")
                        deployment_logger.warning(f"Found {stale_count} stale 'running' execution(s) - marking as failed")
                        
                        # Mark each stale execution as failed
                        for stale_exec in stale_executions.data:
                            try:
                                self.supabase.table('deployment_executions').update({
                                    'completed_at': datetime.now(timezone.utc).isoformat(),
                                    'status': 'failed',
                                    'success': False,
                                    'error_message': 'Execution aborted - scheduler restarted'
                                }).eq('id', stale_exec['id']).execute()
                                
                                print(f"[@deployment_scheduler] Marked stale execution {stale_exec['id']} as failed")
                                deployment_logger.info(f"Cleaned up stale execution: {stale_exec['id']} (started: {stale_exec.get('started_at', 'unknown')})")
                            except Exception as e:
                                print(f"[@deployment_scheduler] Failed to clean up execution {stale_exec['id']}: {e}")
                                deployment_logger.error(f"Failed to clean up stale execution {stale_exec['id']}: {e}")
                    else:
                        print(f"[@deployment_scheduler] No stale executions found")
                        deployment_logger.info("No stale executions found - clean state")
            except Exception as e:
                print(f"[@deployment_scheduler] Error cleaning up stale executions: {e}")
                deployment_logger.error(f"Error during stale execution cleanup: {e}")

            try:
                queued_result = self.supabase.table('deployment_executions').select(
                    'id, deployment_id, scheduled_at, started_at, deployments!inner(host_name, device_id)'
                ).eq('status', 'queued').eq('deployments.host_name', self.host_name).order(
                    'scheduled_at', desc=False
                ).execute()
                restored_count = 0
                aborted_count = 0
                stale_cutoff = datetime.now(timezone.utc) - timedelta(hours=4)
                for queued_exec in queued_result.data or []:
                    deployment_info = queued_exec.get('deployments') or {}
                    device_id = deployment_info.get('device_id')
                    if not device_id:
                        continue
                    # Abort stale queued items older than 4 hours
                    queued_at_str = queued_exec.get('scheduled_at') or queued_exec.get('started_at')
                    is_stale = False
                    if queued_at_str:
                        try:
                            queued_at = datetime.fromisoformat(queued_at_str.replace('Z', '+00:00'))
                            is_stale = queued_at < stale_cutoff
                        except (ValueError, TypeError):
                            is_stale = True
                    else:
                        is_stale = True
                    if is_stale:
                        try:
                            self.supabase.table('deployment_executions').update({
                                'completed_at': datetime.now(timezone.utc).isoformat(),
                                'status': 'aborted',
                                'success': False,
                                'error_message': 'Execution auto-aborted after staying queued for more than 4 hours',
                                'skip_reason': 'stale_queue_timeout',
                            }).eq('id', queued_exec['id']).execute()
                            aborted_count += 1
                        except Exception:
                            pass
                        continue
                    self.queued_executions.setdefault(device_id, []).append({
                        'deployment_id': queued_exec['deployment_id'],
                        'queued_at': queued_at_str or datetime.now(timezone.utc).isoformat(),
                        'execution_id': queued_exec['id'],
                    })
                    restored_count += 1
                if restored_count:
                    deployment_logger.info(f"Restored {restored_count} queued execution(s) from database")
                if aborted_count:
                    print(f"[@deployment_scheduler] Aborted {aborted_count} stale queued execution(s) (older than 4h)")
                    deployment_logger.info(f"Aborted {aborted_count} stale queued execution(s)")

                # Trigger processing for each device that has restored queued items
                for device_id, queue in self.queued_executions.items():
                    if queue:
                        print(f"[@deployment_scheduler] Triggering queue drain for device {device_id} ({len(queue)} item(s))")
                        self._schedule_next_queued_for_device(device_id)
            except Exception as e:
                print(f"[@deployment_scheduler] Error restoring queued executions: {e}")
                deployment_logger.error(f"Error restoring queued executions: {e}")

            # Now load active deployments
            result = self.supabase.table('deployments').select('*').eq('host_name', self.host_name).eq('status', 'active').execute()
            
            # Add jobs
            for dep in result.data:
                self._add_job(dep)
            
            # Format deployment summary for both console and log file
            separator = "=" * 80
            header = f"{'DEPLOYMENTS':^80}"
            active_count = f"Active: {len(result.data)}"
            
            # Build the summary
            summary_lines = [
                "",
                separator,
                header,
                separator,
                active_count,
                ""
            ]
            
            if len(result.data) > 0:
                for dep in result.data:
                    # Get job info for next run time
                    job = self.scheduler.get_job(dep['id'])
                    next_run = job.next_run_time.strftime('%Y-%m-%d %H:%M:%S UTC') if job and job.next_run_time else 'N/A'
                    
                    # Format last execution
                    last_exec = dep.get('last_executed_at')
                    if last_exec:
                        last_exec_dt = datetime.fromisoformat(last_exec.replace('Z', '+00:00'))
                        last_exec_str = last_exec_dt.strftime('%Y-%m-%d %H:%M:%S UTC')
                    else:
                        last_exec_str = 'Never'
                    
                    # Format frequency
                    cron_expr = dep.get('cron_expression', 'N/A')
                    
                    summary_lines.append(f"• {dep['name']}")
                    summary_lines.append(f"  Last execution:  {last_exec_str}")
                    summary_lines.append(f"  Next execution:  {next_run}")
                    summary_lines.append(f"  Frequency:       {cron_expr}")
                    
                    # Format executions count
                    exec_count = dep.get('execution_count', 0)
                    max_exec = dep.get('max_executions')
                    if max_exec:
                        summary_lines.append(f"  Executions:      {exec_count}/{max_exec}")
                    else:
                        summary_lines.append(f"  Executions:      {exec_count}")
                    summary_lines.append("")
            else:
                summary_lines.append("(No active deployments)")
                summary_lines.append("")
            
            summary_lines.append(separator)
            
            # Print to console
            for line in summary_lines:
                print(f"[@deployment_scheduler] {line}")
            
            # Write to log file
            for line in summary_lines:
                deployment_logger.info(line)
                
        except Exception as e:
            error_msg = f"Failed to sync deployments: {e}"
            print(f"[@deployment_scheduler] {error_msg}")
            deployment_logger.error(error_msg)
    
    def _get_estimated_duration(self, script_name, device_id, deployment_id=None):
        """Get estimated duration from deployment history or script_results
        
        Args:
            script_name: Name of the script
            device_id: Device identifier
            deployment_id: Optional deployment ID to check its execution history first
            
        Returns:
            float: Estimated duration in seconds
        """
        # Try deployment_executions first (more accurate per deployment)
        if deployment_id:
            try:
                with self.db_lock:
                    history = self.supabase.table('deployment_executions')\
                        .select('started_at, completed_at')\
                        .eq('deployment_id', deployment_id)\
                        .in_('status', ['completed', 'failed'])\
                        .not_.is_('started_at', 'null')\
                        .not_.is_('completed_at', 'null')\
                        .order('completed_at', desc=True)\
                        .limit(100)\
                        .execute()
                    
                    if history.data:
                        durations = []
                        for execution_row in history.data:
                            try:
                                started = datetime.fromisoformat(execution_row['started_at'].replace('Z', '+00:00'))
                                completed = datetime.fromisoformat(execution_row['completed_at'].replace('Z', '+00:00'))
                                duration_seconds = (completed - started).total_seconds()
                                if duration_seconds > 0:
                                    durations.append(duration_seconds)
                            except Exception:
                                continue
                        
                        if durations:
                            avg = sum(durations) / len(durations)
                            print(f"[@deployment_scheduler] Estimated duration from deployment history: {avg:.1f}s")
                            return avg
            except Exception as e:
                print(f"[@deployment_scheduler] Failed to get deployment history: {e}")
        
        # Fallback: script_results for this script+device
        try:
            with self.db_lock:
                results = self.supabase.table('script_results')\
                    .select('execution_time_ms')\
                    .eq('script_name', script_name)\
                    .eq('device_name', device_id)\
                    .gt('execution_time_ms', 0)\
                    .order('started_at', desc=True)\
                    .limit(100)\
                    .execute()
                
                if results.data:
                    avg_ms = sum(r['execution_time_ms'] for r in results.data) / len(results.data)
                    avg_seconds = avg_ms / 1000.0
                    print(f"[@deployment_scheduler] Estimated duration from script_results: {avg_seconds:.1f}s")
                    return avg_seconds
        except Exception as e:
            print(f"[@deployment_scheduler] Failed to get script_results: {e}")
        
        # Default: 60 seconds
        print(f"[@deployment_scheduler] No history found, using default duration: 60s")
        return 60.0
    
    def _calculate_scheduled_today(self, deployment):
        """Calculate today's scheduled execution times with estimated durations
        
        Args:
            deployment: Deployment record with cron_expression, script_name, device_id
            
        Returns:
            list: Array of dicts with 'start' and 'end' timestamps in ISO format
        """
        try:
            cron_expr = deployment.get('cron_expression')
            if not cron_expr:
                return []
            
            # Get estimated duration
            duration_seconds = self._get_estimated_duration(
                deployment['script_name'],
                deployment['device_id'],
                deployment.get('id')
            )
            
            # Generate today's scheduled times
            today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
            today_end = today_start + timedelta(days=1)
            
            schedule = []
            iter = croniter(cron_expr, today_start)
            
            # Limit to reasonable number of executions per day
            # 1440 = max possible (every minute for 24h)
            max_executions = 1500  # Safety limit slightly above 24h of every-minute executions
            count = 0
            
            while count < max_executions:
                try:
                    next_time = iter.get_next(datetime)
                    if next_time >= today_end:
                        break
                    
                    end_time = next_time + timedelta(seconds=duration_seconds)
                    schedule.append({
                        'start': next_time.isoformat(),
                        'end': end_time.isoformat()
                    })
                    count += 1
                except Exception as e:
                    print(f"[@deployment_scheduler] Error generating schedule iteration: {e}")
                    break
            
            print(f"[@deployment_scheduler] Generated {len(schedule)} scheduled times for today")
            return schedule
            
        except Exception as e:
            print(f"[@deployment_scheduler] Failed to calculate scheduled_today: {e}")
            deployment_logger.error(f"Failed to calculate scheduled_today for {deployment.get('name', 'unknown')}: {e}")
            return []
    
    def _update_scheduled_today(self, deployment_id):
        """Update scheduled_today for a specific deployment"""
        try:
            # Fetch deployment
            with self.db_lock:
                result = self.supabase.table('deployments').select('*').eq('id', deployment_id).execute()
            
            if not result.data:
                return
            
            deployment = result.data[0]
            scheduled_today = self._calculate_scheduled_today(deployment)
            
            # Update deployment (pass list directly, Supabase handles JSONB conversion)
            with self.db_lock:
                self.supabase.table('deployments').update({
                    'scheduled_today': scheduled_today if scheduled_today else None
                }).eq('id', deployment_id).execute()
            
            print(f"[@deployment_scheduler] Updated scheduled_today for {deployment.get('name')}")
            
        except Exception as e:
            print(f"[@deployment_scheduler] Failed to update scheduled_today: {e}")
            deployment_logger.error(f"Failed to update scheduled_today for {deployment_id}: {e}")
    
    def _add_job(self, deployment, log_details=False):
        """Add deployment to scheduler using cron expression"""
        try:
            job_config = self._get_job_config(deployment)
        except ValueError as e:
            print(f"[@deployment_scheduler] {e}")
            deployment_logger.error(f"{deployment.get('name')}: {e}")
            return

        self.scheduler.add_job(
            func=self._execute_deployment,
            args=[deployment['id'], None],
            trigger=job_config['trigger'],
            id=job_config['job_id'],
            replace_existing=True
        )
        
        # Update scheduled_today when adding job
        self._update_scheduled_today(deployment['id'])
        
        # Only log detailed info when adding individual deployments (not during sync)
        if log_details:
            job = self.scheduler.get_job(deployment['id'])
            next_run = job.next_run_time if job else None
            schedule_desc = deployment.get('start_date') if self._is_future_one_shot(deployment) else deployment.get('cron_expression')
            print(f"[@deployment_scheduler] Added: {deployment['name']} with schedule: {schedule_desc}")
            deployment_logger.info(f"ADDED: {deployment['name']} | Schedule: {schedule_desc} | Next run: {next_run} UTC")
    
    def _should_execute(self, deployment):
        """Check if deployment should execute based on constraints"""
        now = datetime.now(timezone.utc)
        dep_name = deployment.get('name', deployment['id'])
        
        # Check start date
        if deployment.get('start_date'):
            start_date_str = deployment['start_date']
            if start_date_str:
                start_date = datetime.fromisoformat(start_date_str.replace('Z', '+00:00'))
                if now < start_date:
                    deployment_logger.info(f"CONSTRAINT: {dep_name} | Skipped - Not started yet (starts: {start_date} UTC)")
                    return False, "Not started yet"
        
        # Check end date
        if deployment.get('end_date'):
            end_date_str = deployment['end_date']
            if end_date_str:
                end_date = datetime.fromisoformat(end_date_str.replace('Z', '+00:00'))
                if now > end_date:
                    deployment_logger.warning(f"CONSTRAINT: {dep_name} | Expired (end date: {end_date} UTC)")
                    self._mark_as_expired(deployment['id'])
                    return False, "Expired by end date"
        
        # Check max executions
        if deployment.get('max_executions'):
            execution_count = deployment.get('execution_count', 0)
            if execution_count >= deployment['max_executions']:
                deployment_logger.warning(f"CONSTRAINT: {dep_name} | Max executions reached ({execution_count}/{deployment['max_executions']})")
                self._mark_as_completed(deployment['id'])
                return False, "Max executions reached"
        
        return True, "OK"
    
    def _mark_as_expired(self, deployment_id):
        """Mark deployment as expired and remove from scheduler"""
        try:
            with self.db_lock:
                self.supabase.table('deployments')\
                    .update({'status': 'expired'})\
                    .eq('id', deployment_id)\
                    .execute()
            self.scheduler.remove_job(deployment_id)
            print(f"[@deployment_scheduler] Marked as expired: {deployment_id}")
            deployment_logger.warning(f"STATUS: {deployment_id} | EXPIRED - Removed from scheduler")
        except Exception as e:
            print(f"[@deployment_scheduler] Error marking expired: {e}")
            deployment_logger.error(f"Failed to mark deployment as expired: {e}")
    
    def _mark_as_completed(self, deployment_id):
        """Mark deployment as completed and remove from scheduler"""
        try:
            with self.db_lock:
                self.supabase.table('deployments')\
                    .update({'status': 'completed'})\
                    .eq('id', deployment_id)\
                    .execute()
            self.scheduler.remove_job(deployment_id)
            print(f"[@deployment_scheduler] Marked as completed: {deployment_id}")
            deployment_logger.info(f"STATUS: {deployment_id} | COMPLETED - Removed from scheduler")
        except Exception as e:
            print(f"[@deployment_scheduler] Error marking completed: {e}")
            deployment_logger.error(f"Failed to mark deployment as completed: {e}")

    def _schedule_next_queued_for_device(self, device_id: str, after_error: bool = False):
        """Schedule next queued deployment for a device (FIFO)."""
        queue = self.queued_executions.get(device_id, [])
        if not queue:
            return

        next_item = queue.pop(0)
        next_deployment_id = next_item['deployment_id']
        queued_at = next_item['queued_at']
        queued_execution_id = next_item.get('execution_id')

        mode = "after error" if after_error else "after completion"
        print(
            f"[@deployment_scheduler] Dequeued deployment {next_deployment_id} for device {device_id} "
            f"(queued at {queued_at}, remaining queue: {len(queue)})"
        )
        deployment_logger.info(
            f"🔄 EXECUTING DEVICE-QUEUED: {next_deployment_id} | Device: {device_id} | "
            f"Queued at: {queued_at} ({mode}) | Remaining: {len(queue)}"
        )

        self._start_immediate_execution(
            next_deployment_id,
            queued_execution_id=queued_execution_id,
            reason='queued',
        )

    def _queue_watchdog(self):
        """Periodic watchdog: drains orphaned queued executions that lost their retry timers."""
        try:
            with self.db_lock:
                queued_result = self.supabase.table('deployment_executions').select(
                    'id, deployment_id, scheduled_at, deployments!inner(host_name, device_id)'
                ).eq('status', 'queued').eq(
                    'deployments.host_name', self.host_name
                ).order('scheduled_at', desc=False).execute()

            if not queued_result.data:
                return

            # Check which devices currently have running executions
            with self.db_lock:
                running_result = self.supabase.table('deployment_executions').select(
                    'id, deployments!inner(host_name, device_id)'
                ).eq('status', 'running').eq(
                    'deployments.host_name', self.host_name
                ).execute()
            running_devices = {
                (r.get('deployments') or {}).get('device_id')
                for r in (running_result.data or [])
            }

            # Rebuild in-memory queue from DB for items that fell out of memory
            restored = 0
            for queued_exec in queued_result.data:
                dep_info = queued_exec.get('deployments') or {}
                device_id = dep_info.get('device_id')
                if not device_id:
                    continue
                dep_id = queued_exec['deployment_id']
                exec_id = queued_exec['id']

                mem_queue = self.queued_executions.get(device_id, [])
                if any(q.get('execution_id') == exec_id for q in mem_queue):
                    continue

                self.queued_executions.setdefault(device_id, []).append({
                    'deployment_id': dep_id,
                    'queued_at': queued_exec.get('scheduled_at', ''),
                    'execution_id': exec_id,
                })
                restored += 1

            if restored:
                print(f"[@deployment_scheduler] Queue watchdog: restored {restored} orphaned queued item(s) to memory")
                deployment_logger.info(f"Queue watchdog: restored {restored} orphaned queued item(s)")

            # Drain queues for idle devices
            for device_id, queue in list(self.queued_executions.items()):
                if queue and device_id not in running_devices:
                    if not self._has_pending_wait_lock_retry(queue[0]['deployment_id']):
                        print(f"[@deployment_scheduler] Queue watchdog: draining queue for idle device {device_id} ({len(queue)} item(s))")
                        deployment_logger.info(f"Queue watchdog: draining device {device_id} ({len(queue)} item(s))")
                        self._schedule_next_queued_for_device(device_id)
        except Exception as e:
            print(f"[@deployment_scheduler] Queue watchdog error: {e}")

    def _execute_deployment(self, deployment_id, queued_execution_id: Optional[str] = None):
        """Execute deployment with constraint checks"""
        exec_id = None
        completion_written = False  # Guard: ensures completed_at is always written if exec_id is set
        # Lock bookkeeping initialized before the try so the finally can always
        # reach it, even if execution blows up before these are assigned inside.
        dep = None
        lock_acquired = False
        lock_released = False  # Guard: ensures the server lock is released exactly once
        lock_owner_session_id = None
        lock_owner_job_id = None
        try:
            print(f"[@deployment_scheduler] ===== TRIGGERED: {deployment_id} =====")
            deployment_logger.info(f"===== TRIGGERED: {deployment_id} =====")

            if queued_execution_id:
                with self.db_lock:
                    queued_result = self.supabase.table('deployment_executions').select(
                        'id, status'
                    ).eq('id', queued_execution_id).limit(1).execute()
                queued_row = (queued_result.data or [None])[0]
                queued_status = (queued_row or {}).get('status')
                if queued_status != 'queued':
                    print(
                        f"[@deployment_scheduler] Skipping queued retry for {deployment_id}: "
                        f"execution {queued_execution_id} is {queued_status!r}"
                    )
                    deployment_logger.info(
                        f"⏭️  SKIPPED QUEUED RETRY: {deployment_id} | "
                        f"execution_id={queued_execution_id} | status={queued_status!r}"
                    )
                    return

            start_time = datetime.now(timezone.utc)
            lock_owner_session_id = f"deployment:{deployment_id}:{int(time.time() * 1000)}"
            lock_owner_job_id = deployment_id
            lock_acquired = False
            
            # Get deployment config
            try:
                with self.db_lock:
                    result = self.supabase.table('deployments').select('*').eq('id', deployment_id).execute()
            except Exception as db_error:
                error_type = type(db_error).__name__
                print(f"[@deployment_scheduler] Failed to fetch deployment: {error_type}: {db_error}")
                print(f"[@deployment_scheduler] Raw error: {repr(db_error)}")
                deployment_logger.error(f"Failed to fetch deployment {deployment_id}: {error_type}: {db_error}")
                deployment_logger.error(f"Raw error: {repr(db_error)}")
                if hasattr(db_error, '__dict__'):
                    deployment_logger.error(f"Error attributes: {db_error.__dict__}")
                raise
            
            if not result.data or len(result.data) == 0:
                print(f"[@deployment_scheduler] Deployment {deployment_id} no longer exists, removing from scheduler")
                deployment_logger.warning(f"DELETED: {deployment_id} | Deployment no longer exists in database")
                self.scheduler.remove_job(deployment_id)
                return
            
            dep = result.data[0]
            dep_name = dep.get('name', deployment_id)
            
            deployment_logger.info(f"⚡ TRIGGERED: {dep_name} | Time: {start_time.strftime('%Y-%m-%d %H:%M:%S')} UTC")
            
            # Check if should execute (constraints)
            should_run, reason = self._should_execute(dep)
            if not should_run:
                print(f"[@deployment_scheduler] Skipping execution: {reason}")
                deployment_logger.info(f"⏭️  SKIPPED: {dep_name} | Reason: {reason}")
                with self.db_lock:
                    if queued_execution_id:
                        self.supabase.table('deployment_executions').update({
                            'completed_at': start_time.isoformat(),
                            'status': 'skipped',
                            'success': False,
                            'skip_reason': reason,
                            'error_message': None,
                        }).eq('id', queued_execution_id).execute()
                        print(
                            f"[@deployment_scheduler] Updated queued execution {queued_execution_id} "
                            f"to skipped: {reason}"
                        )
                    else:
                        self.supabase.table('deployment_executions').insert({
                            'deployment_id': deployment_id,
                            'scheduled_at': start_time.isoformat(),
                            'completed_at': start_time.isoformat(),
                            'status': 'skipped',
                            'skip_reason': reason
                        }).execute()
                if dep.get('device_id'):
                    self._schedule_next_queued_for_device(dep['device_id'], after_error=True)
                return
            
            # Check if any execution is still running on the same device (cross-deployment)
            with self.db_lock:
                running_check = self.supabase.table('deployment_executions')\
                    .select('id, started_at, deployment_id, deployments!inner(host_name, device_id, name)')\
                    .eq('status', 'running')\
                    .eq('deployments.host_name', self.host_name)\
                    .eq('deployments.device_id', dep['device_id'])\
                    .execute()
            
            if running_check.data and len(running_check.data) > 0:
                running_exec = running_check.data[0]
                started_at_str = running_exec.get('started_at', 'unknown')
                
                # Check if execution is stale (running for more than 1 hour)
                try:
                    started_at = datetime.fromisoformat(started_at_str.replace('Z', '+00:00'))
                    age_seconds = (datetime.now(timezone.utc) - started_at).total_seconds()
                    
                    if age_seconds > 3600:  # 1 hour = 3600 seconds
                        print(f"[@deployment_scheduler] Found stale execution (age: {age_seconds/3600:.1f} hours) - marking as failed")
                        deployment_logger.warning(f"Stale execution detected: {running_exec['id']} (age: {age_seconds/3600:.1f} hours) - marking as failed")
                        
                        # Mark stale execution as failed
                        with self.db_lock:
                            self.supabase.table('deployment_executions').update({
                                'completed_at': datetime.now(timezone.utc).isoformat(),
                                'status': 'failed',
                                'success': False,
                                'error_message': f'Execution timed out - ran for {age_seconds/3600:.1f} hours'
                            }).eq('id', running_exec['id']).execute()
                        
                        # Continue with new execution (don't skip)
                        print(f"[@deployment_scheduler] Stale execution cleaned up, proceeding with new execution")
                    else:
                        # Execution is recent, check device-level queue
                        device_id = dep['device_id']
                        if device_id not in self.queued_executions:
                            self.queued_executions[device_id] = []

                        if len(self.queued_executions[device_id]) >= 10:
                            # Already have 10 queued on this device - skip this trigger
                            print(f"[@deployment_scheduler] Device queue full, skipping trigger for {device_id} (age: {age_seconds:.0f}s)")
                            deployment_logger.warning(f"⏭️  SKIPPED: {dep_name} | Device queue full ({device_id}, max 10)")
                            with self.db_lock:
                                self.supabase.table('deployment_executions').insert({
                                    'deployment_id': deployment_id,
                                    'scheduled_at': start_time.isoformat(),
                                    'status': 'skipped',
                                    'skip_reason': f'Device queue full ({device_id}, max 10)'
                                }).execute()
                            return
                        else:
                            # Recurring CRON jobs skip when device is busy — next trigger will retry
                            if self._is_recurring_cron(dep):
                                print(f"[@deployment_scheduler] Recurring CRON job {dep_name} skipped (device {device_id} busy)")
                                deployment_logger.info(f"⏭️  SKIPPED: {dep_name} | Device {device_id} busy (recurring CRON, will retry next trigger)")
                                with self.db_lock:
                                    self.supabase.table('deployment_executions').insert({
                                        'deployment_id': deployment_id,
                                        'scheduled_at': start_time.isoformat(),
                                        'status': 'skipped',
                                        'skip_reason': f'Device {device_id} busy (recurring CRON, will retry next trigger)'
                                    }).execute()
                                return

                            # Dedup: skip if this deployment_id is already queued on this device
                            already_queued = any(q['deployment_id'] == deployment_id for q in self.queued_executions[device_id])
                            if already_queued:
                                print(f"[@deployment_scheduler] Skipping duplicate queue for {deployment_id} on device {device_id}")
                                deployment_logger.info(f"⏭️  DEDUP: {dep_name} already queued on {device_id}")
                                return

                            # Queue this execution on the device (max 10 per device)
                            self.queued_executions[device_id].append({
                                'deployment_id': deployment_id,
                                'queued_at': start_time.isoformat(),
                                'execution_id': None,
                            })
                            queue_size = len(self.queued_executions[device_id])
                            print(f"[@deployment_scheduler] Queued on device {device_id} (queue size: {queue_size})")
                            deployment_logger.info(f"⏳ QUEUED: {dep_name} | Device: {device_id} | Queue position: {queue_size}")
                            with self.db_lock:
                                queued_record = self.supabase.table('deployment_executions').insert({
                                    'deployment_id': deployment_id,
                                    'scheduled_at': start_time.isoformat(),
                                    'status': 'queued',
                                    'skip_reason': None
                                }).execute().data[0]
                            self.queued_executions[device_id][-1]['execution_id'] = queued_record['id']
                            return
                except (ValueError, TypeError) as e:
                    # If we can't parse the date, skip this execution
                    print(f"[@deployment_scheduler] Could not parse started_at date: {e}, skipping execution")
                    deployment_logger.warning(
                        f"⏭️  SKIPPED: {dep_name} | Reason: Device {dep['device_id']} still running "
                        f"(started: {started_at_str})"
                    )
                    with self.db_lock:
                        self.supabase.table('deployment_executions').insert({
                            'deployment_id': deployment_id,
                            'scheduled_at': start_time.isoformat(),
                            'status': 'skipped',
                            'skip_reason': f'Device {dep["device_id"]} still running'
                        }).execute()
                    return
            
            lock_response = self._acquire_server_execution_lock(
                host_name=dep['host_name'],
                device_id=dep['device_id'],
                owner_session_id=lock_owner_session_id,
                owner_job_id=lock_owner_job_id,
                # Human-readable name: the frontend lock badge shows everything after
                # the first colon (useDeviceScriptLabel), so a bare id reads as noise.
                lock_reason=f"deployment:{dep_name}",
            )
            if not lock_response.get('ok'):
                lock_data = lock_response.get('data') or {}
                conflict = lock_data.get('lock_info') or {}
                owner_type = conflict.get('owner_type') or 'unknown'
                skip_reason = f"waiting_for_lock:{owner_type}"

                # Recurring CRON jobs skip when device is locked — next trigger will retry
                if not queued_execution_id and self._is_recurring_cron(dep):
                    print(f"[@deployment_scheduler] Recurring CRON job {dep_name} skipped (device locked by {owner_type})")
                    deployment_logger.info(f"⏭️  SKIPPED: {dep_name} | Device locked by {owner_type} (recurring CRON, will retry next trigger)")
                    with self.db_lock:
                        self.supabase.table('deployment_executions').insert({
                            'deployment_id': deployment_id,
                            'scheduled_at': start_time.isoformat(),
                            'status': 'skipped',
                            'skip_reason': f'Device locked by {owner_type} (recurring CRON, will retry next trigger)'
                        }).execute()
                    return

                print(
                    f"[@deployment_scheduler] Device lock conflict for {dep_name} on {dep['device_id']} "
                    f"(owner_type={owner_type}) - queuing retry"
                )
                deployment_logger.info(
                    f"⏳ WAITING FOR LOCK: {dep_name} | Device: {dep['device_id']} | "
                    f"Owner type: {owner_type}"
                )
                if queued_execution_id:
                    self._schedule_wait_lock_retry(
                        deployment_id,
                        delay_seconds=20,
                        queued_execution_id=queued_execution_id,
                    )
                    return

                with self.db_lock:
                    queued_record = self.supabase.table('deployment_executions').insert({
                        'deployment_id': deployment_id,
                        'scheduled_at': start_time.isoformat(),
                        'status': 'queued',
                        'skip_reason': skip_reason
                    }).execute().data[0]
                self._schedule_wait_lock_retry(
                    deployment_id,
                    delay_seconds=20,
                    queued_execution_id=queued_record['id'],
                )
                return

            lock_acquired = True
            dep['_lock_owner_session_id'] = lock_owner_session_id
            dep['_lock_owner_job_id'] = lock_owner_job_id

            # Create execution record with UTC timestamp
            # Note: Supabase auto-generates unique UUID for 'id' field to avoid conflicts
            scheduled_at = start_time.isoformat()
            try:
                with self.db_lock:
                    if queued_execution_id:
                        self.supabase.table('deployment_executions').update({
                            'started_at': scheduled_at,
                            'completed_at': None,
                            'status': 'running',
                            'skip_reason': None,
                            'error_message': None,
                        }).eq('id', queued_execution_id).execute()
                        exec_id = queued_execution_id
                        print(f"[@deployment_scheduler] Reusing queued execution record: {exec_id}")
                    else:
                        exec_record = self.supabase.table('deployment_executions').insert({
                            'deployment_id': deployment_id,
                            'scheduled_at': scheduled_at,
                            'started_at': scheduled_at,
                            'status': 'running'
                        }).execute().data[0]
                        exec_id = exec_record['id']
                        print(f"[@deployment_scheduler] Created execution record: {exec_id}")
            except Exception as db_error:
                error_type = type(db_error).__name__
                print(f"[@deployment_scheduler] Failed to create execution record: {error_type}: {db_error}")
                print(f"[@deployment_scheduler] Raw error: {repr(db_error)}")
                deployment_logger.error(f"Failed to create execution record for {dep_name}: {error_type}: {db_error}")
                deployment_logger.error(f"Raw error: {repr(db_error)}")
                if hasattr(db_error, '__dict__'):
                    deployment_logger.error(f"Error attributes: {db_error.__dict__}")
                raise
            
            # Notify server that execution is now running (emits socket event for frontend)
            try:
                self._notify_server_execution_status(
                    dep=dep, execution_id=exec_id, status='running',
                    started_at=scheduled_at,
                )
            except Exception:
                pass  # Non-critical — don't block execution

            deployment_logger.info(f"▶️  EXECUTING: {dep_name} | Script: {dep['script_name']} | Device: {dep['device_id']}")
            
            # Get capture folder from .env (centralized utility function)
            capture_folder = get_capture_folder_from_device_id(dep['device_id'])
            
            try:
                running_log_path = get_running_log_path(capture_folder)
                log_dir = os.path.dirname(running_log_path)
                
                # Ensure directory exists (should already exist from setup_ram_hot_storage.sh)
                os.makedirs(log_dir, exist_ok=True)
                
                # Clear/create file (no chmod needed - hot folders already have 777 from setup script)
                with open(running_log_path, 'w') as f:
                    f.write('')  # Clear file
                
                print(f"[@deployment_scheduler] Cleared running log: {running_log_path}")
            except Exception as log_error:
                print(f"[@deployment_scheduler] Failed to clear running log: {log_error}")
                import traceback
                traceback.print_exc()
            
            # Build complete parameters in correct order:
            # 1. userinterface_name (POSITIONAL - MUST BE FIRST)
            # 2. script parameters (--max-iteration, --edges, etc.)
            # 3. framework parameters (--host, --device)
            
            param_parts = []
            
            # FIRST: Add userinterface_name as positional argument (REQUIRED FIRST)
            if dep.get('userinterface_name'):
                param_parts.append(dep['userinterface_name'])
            
            # SECOND: Add script-specific parameters (filter out empty/null values).
            # Note: for DB campaigns, dep['parameters'] is a JSON-encoded
            # script_configurations snapshot, not a CLI string. The JSON path
            # is consumed in the CampaignExecutor branch below; here we skip
            # CLI parsing if the value doesn't look like CLI args, so a JSON
            # blob can't accidentally crash shlex or pollute the command line.
            custom_params = dep.get('parameters', '').strip()
            looks_like_cli = bool(custom_params) and not (
                custom_params.startswith('[') or custom_params.startswith('{')
            )
            if looks_like_cli:
                # Parse parameters to filter out flags with empty values
                # Example: "--max-iteration 10 --edges --host" should remove "--edges"
                import shlex
                try:
                    tokens = shlex.split(custom_params)
                except ValueError as shlex_error:
                    print(f"[@deployment_scheduler] Failed to parse CLI parameters: {shlex_error}")
                    tokens = []
                parsed_params = []
                i = 0
                while i < len(tokens):
                    token = tokens[i]
                    if token.startswith('--'):
                        # This is a flag
                        if i + 1 < len(tokens) and not tokens[i + 1].startswith('--'):
                            # Has a value
                            value = tokens[i + 1]
                            if value and value.strip():  # Only add if value is not empty
                                parsed_params.append(token)
                                parsed_params.append(value)
                                i += 2
                                continue
                            else:
                                # Skip flag with empty value
                                print(f"[@deployment_scheduler] Skipping parameter {token} with empty value")
                                i += 2
                                continue
                        else:
                            # Flag without value - skip it (invalid)
                            print(f"[@deployment_scheduler] Skipping parameter {token} (no value provided)")
                            i += 1
                            continue
                    else:
                        # Not a flag, keep as-is (shouldn't happen in custom_params)
                        parsed_params.append(token)
                        i += 1
                
                if parsed_params:
                    # Re-quote each token: shlex.split above stripped the outer
                    # quotes, so a value containing spaces (e.g. a KPI edge label
                    # "disney_asset → disney_asset_stream") would otherwise be
                    # rejoined bare and re-split downstream into multiple args,
                    # leaving argparse with only the first word ("disney_asset").
                    # Mirrors script_executor / campaign_executor quoting.
                    param_parts.append(' '.join(shlex.quote(part) for part in parsed_params))
            
            # THIRD: Add framework parameters
            param_parts.append(f"--host {dep['host_name']}")
            param_parts.append(f"--device {dep['device_id']}")
            
            all_params = ' '.join(param_parts)
            
            # Resolve script name for execution: campaign:<path>|<display_name> → <path>
            resolved_script_name = dep['script_name']
            if resolved_script_name.startswith('campaign:'):
                resolved_script_name = resolved_script_name[len('campaign:'):]
                if '|' in resolved_script_name:
                    resolved_script_name = resolved_script_name.split('|', 1)[0]
                print(f"[@deployment_scheduler] Resolved campaign script: {dep['script_name']} → {resolved_script_name}")

            # Log the exact command for debugging
            print(f"[@deployment_scheduler] Executing command: python {resolved_script_name} {all_params}")
            deployment_logger.info(f"📋 COMMAND: python {resolved_script_name} {all_params}")
            
            # Fetch average duration from last 100 executions for estimated end time
            estimated_duration_seconds = None
            try:
                with self.db_lock:
                    # Query last 100 completed executions for this deployment
                    history = self.supabase.table('deployment_executions')\
                        .select('started_at, completed_at')\
                        .eq('deployment_id', deployment_id)\
                        .in_('status', ['completed', 'failed'])\
                        .not_.is_('started_at', 'null')\
                        .not_.is_('completed_at', 'null')\
                        .order('completed_at', desc=True)\
                        .limit(100)\
                        .execute()
                    
                    if history.data and len(history.data) > 0:
                        # Calculate average duration
                        durations = []
                        for execution_row in history.data:
                            try:
                                started = datetime.fromisoformat(execution_row['started_at'].replace('Z', '+00:00'))
                                completed = datetime.fromisoformat(execution_row['completed_at'].replace('Z', '+00:00'))
                                duration_seconds = (completed - started).total_seconds()
                                if duration_seconds > 0:  # Only count valid durations
                                    durations.append(duration_seconds)
                            except Exception:
                                continue
                        
                        if durations:
                            estimated_duration_seconds = sum(durations) / len(durations)
                            print(f"[@deployment_scheduler] Estimated duration based on {len(durations)} executions: {estimated_duration_seconds:.1f}s")
            except Exception as est_error:
                print(f"[@deployment_scheduler] Failed to calculate estimated duration: {est_error}")
            
            # Virtual-script deployment: source lives in the DB, selected by
            # virtual_script_id (the run's team_id scopes resolution + _script_libs).
            # A campaign threads virtual_script_id per step (script_configurations)
            # and is handled in the campaign branch below; this handles a single
            # virtual-script deployment run directly via ScriptExecutor.
            virtual_script_id = dep.get('virtual_script_id')

            # Check if this is a DB campaign (not a .py script, not a campaign: file
            # path). A single virtual-script deployment has no .py name either, so
            # exclude it here — it runs through the ScriptExecutor branch below.
            is_db_campaign = (
                not resolved_script_name.endswith('.py')
                and not dep['script_name'].startswith('campaign:')
                and not virtual_script_id
            )
            db_campaign = None
            if is_db_campaign:
                try:
                    team_id = dep.get('team_id')
                    if team_id:
                        db_campaign = get_campaign_by_name(resolved_script_name, team_id)
                    if db_campaign:
                        print(f"[@deployment_scheduler] Found DB campaign: {resolved_script_name}, executing via CampaignExecutor")
                        deployment_logger.info(f"📦 DB CAMPAIGN: {resolved_script_name}")
                    if not db_campaign:
                        raise ValueError(
                            f"'{resolved_script_name}' is not a .py script and no DB campaign found "
                            f"with that name (team_id={team_id})"
                        )
                except ValueError:
                    raise
                except Exception as campaign_lookup_error:
                    raise ValueError(
                        f"DB campaign lookup failed for '{resolved_script_name}': {campaign_lookup_error}"
                    )

            if db_campaign:
                # Execute via CampaignExecutor (DB-based campaign).
                # For DB campaigns, deployments.parameters is interpreted as a
                # JSON-encoded list of script_configurations entries — the
                # per-deployment snapshot captured at creation time with
                # per-device parameter overrides. When present, it overrides
                # the canonical campaigns.script_configurations template so
                # scheduled runs behave identically to "Run Now". When absent
                # or unparseable, fall back to the campaign template (legacy
                # deployments).
                deployment_script_configs = None
                raw_parameters = (dep.get('parameters') or '').strip()
                deployment_logger.info(
                    f"📋 DEPLOYMENT PARAMS: {deployment_id} | dep_name={dep_name} | "
                    f"raw_length={len(raw_parameters)} | "
                    f"raw_prefix={raw_parameters[:200]!r}"
                )
                if raw_parameters:
                    try:
                        parsed_parameters = json.loads(raw_parameters)
                        if isinstance(parsed_parameters, list) and parsed_parameters:
                            deployment_script_configs = parsed_parameters
                        else:
                            deployment_logger.warning(
                                f"⚠️ SNAPSHOT SHAPE: {deployment_id} | "
                                f"parsed type={type(parsed_parameters).__name__} | "
                                f"is_empty_list={parsed_parameters == []} | "
                                f"falling back to canonical campaign template"
                            )
                    except (json.JSONDecodeError, ValueError) as parse_error:
                        deployment_logger.warning(
                            f"⚠️ SNAPSHOT PARSE FAILED: {deployment_id} | "
                            f"error={parse_error} | "
                            f"falling back to canonical campaign template"
                        )
                effective_script_configurations = (
                    deployment_script_configs
                    if deployment_script_configs
                    else db_campaign.get('script_configurations', [])
                )
                source = 'deployment_snapshot' if deployment_script_configs else 'campaign_template'
                try:
                    summary = [
                        {
                            'name': sc.get('script_name'),
                            'params': sc.get('parameters', {}),
                        }
                        for sc in effective_script_configurations
                    ]
                except Exception:
                    summary = effective_script_configurations
                deployment_logger.info(
                    f"📋 EFFECTIVE SCRIPT_CONFIGS: {deployment_id} | source={source} | "
                    f"count={len(effective_script_configurations)} | summary={summary}"
                )
                if source == 'campaign_template':
                    deployment_logger.warning(
                        f"⚠️ FALLBACK TO CAMPAIGN TEMPLATE: {deployment_id} | "
                        f"deployment.parameters is empty/invalid — scripts will use "
                        f"whatever parameters the canonical campaign template defines "
                        f"(often empty, producing argparse defaults)."
                    )
                campaign_config = {
                    'campaign_id': str(db_campaign.get('campaign_id')),
                    'name': db_campaign.get('campaign_name') or db_campaign.get('name'),
                    'description': db_campaign.get('description', ''),
                    'userinterface_name': db_campaign.get('userinterface_name'),
                    'host': dep['host_name'],
                    'device': dep['device_id'],
                    'script_configurations': effective_script_configurations,
                    'execution_config': db_campaign.get('execution_config', {}),
                    'team_id': dep.get('team_id'),
                    'device_info': dep.get('device_info'),
                    'deployment_execution_id': exec_id,
                    'trigger': {
                        'type': 'scheduler',
                        'caller_user': f"deployment:campaign:{dep.get('name') or dep.get('id') or 'unknown'}",
                        'caller_ip': None,
                    },
                }

                campaign_executor = CampaignExecutor()
                campaign_result = campaign_executor.execute_campaign(campaign_config)

                end_time = datetime.now(timezone.utc)
                duration = (end_time - start_time).total_seconds()

                script_success = campaign_result.get('success', False)
                campaign_result_id = campaign_result.get('campaign_result_id')
                script_result_id = None
                report_url = campaign_result.get('orchestrator_report_url')
                logs_url = campaign_result.get('orchestrator_logs_url')

                # Update execution record
                try:
                    with self.db_lock:
                        self.supabase.table('deployment_executions').update({
                            'completed_at': end_time.isoformat(),
                            'status': 'completed' if script_success else 'failed',
                            'success': script_success,
                            # deployment_executions.script_result_id points to script_results.id.
                            # Campaign runs produce campaign_executions rows, not script_results rows.
                            'script_result_id': None,
                        }).eq('id', exec_id).execute()
                    completion_written = True
                except Exception as db_error:
                    error_type = type(db_error).__name__
                    print(f"[@deployment_scheduler] Failed to update campaign execution record: {error_type}: {db_error}")
                    deployment_logger.error(f"Failed to update execution {exec_id}: {error_type}: {db_error}")
                    raise

                result = {
                    'duration_seconds': duration,
                    'campaign_result_id': campaign_result_id,
                    'script_result_id': script_result_id,
                    'stdout': json.dumps(campaign_result),
                    'stderr': campaign_result.get('error'),
                    'exit_code': 0 if script_success else 1,
                    'script_success': script_success,
                    'report_url': report_url,
                    'logs_url': logs_url,
                }
            else:
                # Execute script with complete parameters (file-based script)
                # Keyword args are load-bearing: ScriptExecutor's signature starts with
                # script_name/description, so passing these positionally left device_id
                # as None -> "unknown-device", and the abort registry is keyed by
                # device_id. Scheduled scripts then survived force take-control.
                executor = ScriptExecutor(
                    script_name=resolved_script_name,
                    host_name=self.host_name,
                    device_id=dep['device_id'],
                    device_model='unknown',
                )
                scheduler_trigger = {
                    'type': 'scheduler',
                    'caller_user': f"deployment:script:{dep.get('name') or dep.get('id') or 'unknown'}",
                    'caller_ip': None,
                }
                result = executor.execute_script(
                    resolved_script_name,
                    all_params,
                    estimated_duration_seconds=estimated_duration_seconds,
                    trigger=scheduler_trigger,
                    device_info=dep.get('device_info'),
                    # Virtual-script deployments: DB source materialized just before
                    # launch. None for disk-script deployments -> unchanged behavior.
                    virtual_script_id=virtual_script_id,
                    team_id=dep.get('team_id'),
                    environment=dep.get('environment'),
                )

                end_time = datetime.now(timezone.utc)
                duration = (end_time - start_time).total_seconds()

                # Extract script_result_id from stdout if available
                script_result_id = None
                if result.get('stdout'):
                    import re
                    match = re.search(r'SCRIPT_RESULT_ID:([a-f0-9-]+)', result['stdout'])
                    if match:
                        script_result_id = match.group(1)
                        print(f"[@deployment_scheduler] Extracted script_result_id: {script_result_id}")

                # Determine script success: prefer stdout marker, fall back to script_results DB record
                script_success = result.get('script_success')

                if script_success is None and script_result_id:
                    # stdout parsing missed SCRIPT_SUCCESS marker - query the script_results table
                    # (the script itself always writes correct success status to this table)
                    print(f"[@deployment_scheduler] SCRIPT_SUCCESS marker not found in stdout, falling back to script_results table")
                    try:
                        with self.db_lock:
                            sr = self.supabase.table('script_results')\
                                .select('success')\
                                .eq('id', script_result_id)\
                                .single()\
                                .execute()
                        if sr.data:
                            script_success = sr.data.get('success')
                            print(f"[@deployment_scheduler] script_results fallback: success={script_success}")
                        else:
                            print(f"[@deployment_scheduler] script_results record not found for {script_result_id}")
                    except Exception as fallback_error:
                        print(f"[@deployment_scheduler] Failed to query script_results fallback: {fallback_error}")

                # Normalize: ensure boolean (never None)
                if script_success is None:
                    script_success = False
                    print(f"[@deployment_scheduler] script_success still None after fallbacks, defaulting to False")

                # Update execution record with UTC timestamp
                try:
                    with self.db_lock:
                        self.supabase.table('deployment_executions').update({
                            'completed_at': end_time.isoformat(),
                            'status': 'completed' if script_success else 'failed',
                            'success': script_success,
                            'script_result_id': script_result_id
                        }).eq('id', exec_id).execute()
                    completion_written = True
                except Exception as db_error:
                    error_type = type(db_error).__name__
                    print(f"[@deployment_scheduler] Failed to update execution record: {error_type}: {db_error}")
                    print(f"[@deployment_scheduler] Raw error: {repr(db_error)}")
                    deployment_logger.error(f"Failed to update execution {exec_id}: {error_type}: {db_error}")
                    deployment_logger.error(f"Raw error: {repr(db_error)}")
                    if hasattr(db_error, '__dict__'):
                        deployment_logger.error(f"Error attributes: {db_error.__dict__}")
                    raise

            self._notify_server_execution_complete(
                dep=dep,
                execution_id=exec_id,
                started_at=scheduled_at,
                completed_at=end_time.isoformat(),
                success=bool(script_success),
                status='completed' if script_success else 'failed',
                result={
                    'duration_seconds': duration,
                    'script_result_id': script_result_id,
                    'stdout': result.get('stdout'),
                    'stderr': result.get('stderr'),
                    'exit_code': result.get('exit_code'),
                    'report_url': result.get('report_url'),
                    'script_success': script_success,
                },
                error=None if script_success else result.get('stderr') or 'Deployment script failed',
            )
            
            # Update deployment counters
            new_count = dep.get('execution_count', 0) + 1
            try:
                with self.db_lock:
                    self.supabase.table('deployments').update({
                        'execution_count': new_count,
                        'last_executed_at': end_time.isoformat()
                    }).eq('id', deployment_id).execute()
            except Exception as db_error:
                error_type = type(db_error).__name__
                print(f"[@deployment_scheduler] Failed to update deployment counters: {error_type}: {db_error}")
                print(f"[@deployment_scheduler] Raw error: {repr(db_error)}")
                deployment_logger.error(f"Failed to update deployment {deployment_id} counters: {error_type}: {db_error}")
                deployment_logger.error(f"Raw error: {repr(db_error)}")
                if hasattr(db_error, '__dict__'):
                    deployment_logger.error(f"Error attributes: {db_error.__dict__}")
                raise
            
            print(f"[@deployment_scheduler] Deployment {deployment_id} completed: {script_success}")
            
            # Format success status and execution count
            status_emoji = "✅" if script_success else "❌"
            success_str = "True" if script_success else "False"
            
            max_exec = dep.get('max_executions')
            if max_exec:
                exec_info = f"Executions: {new_count}/{max_exec}"
            else:
                exec_info = f"Executions: {new_count}"
            
            deployment_logger.info(f"{status_emoji} COMPLETED: {dep_name} | Duration: {duration:.1f}s | Success: {success_str} | {exec_info}")
            
            # Check if max executions reached after this run
            if dep.get('max_executions') and new_count >= dep['max_executions']:
                self._mark_as_completed(deployment_id)

            if lock_acquired:
                self._release_server_execution_lock(
                    host_name=dep['host_name'],
                    device_id=dep['device_id'],
                    owner_session_id=lock_owner_session_id,
                    owner_job_id=lock_owner_job_id,
                    force=False,
                )
                lock_released = True

            # Run next queued execution for this device, if any
            self._schedule_next_queued_for_device(dep['device_id'])
                
        except Exception as e:
            error_type = type(e).__name__
            error_msg = str(e)
            print(f"[@deployment_scheduler] Execution error: {error_msg}")
            print(f"[@deployment_scheduler] Error type: {error_type}")
            print(f"[@deployment_scheduler] Raw error: {repr(e)}")
            
            # Log detailed error info
            deployment_logger.error(f"💥 ERROR: {deployment_id} | Type: {error_type}")
            deployment_logger.error(f"💥 ERROR: {deployment_id} | Message: {error_msg}")
            deployment_logger.error(f"💥 ERROR: {deployment_id} | Raw: {repr(e)}")
            
            # Try to extract more details if it's a Supabase error
            if hasattr(e, 'args') and len(e.args) > 0:
                deployment_logger.error(f"💥 ERROR: {deployment_id} | Args: {e.args}")
            if hasattr(e, '__dict__'):
                deployment_logger.error(f"💥 ERROR: {deployment_id} | Attributes: {e.__dict__}")
            
            if exec_id:
                try:
                    completed_at = datetime.now(timezone.utc).isoformat()
                    with self.db_lock:
                        self.supabase.table('deployment_executions').update({
                            'completed_at': completed_at,
                            'status': 'failed',
                            'success': False,
                            'error_message': f"{error_type}: {error_msg}"
                        }).eq('id', exec_id).execute()
                    completion_written = True
                    if 'dep' in locals() and dep:
                        self._notify_server_execution_complete(
                            dep=dep,
                            execution_id=exec_id,
                            started_at=start_time.isoformat() if 'start_time' in locals() else None,
                            completed_at=completed_at,
                            success=False,
                            status='failed',
                            result={},
                            error=f"{error_type}: {error_msg}",
                        )
                except Exception as db_error:
                    db_error_type = type(db_error).__name__
                    print(f"[@deployment_scheduler] Failed to update execution record: {db_error_type}: {db_error}")
                    print(f"[@deployment_scheduler] Raw DB error: {repr(db_error)}")
                    deployment_logger.error(f"GHOST RECORD RISK — exec_id={exec_id} completed_at not written: {db_error_type}: {db_error}")
                    deployment_logger.error(f"Raw DB error: {repr(db_error)}")
            
            if lock_acquired and dep and not lock_released:
                self._release_server_execution_lock(
                    host_name=dep['host_name'],
                    device_id=dep['device_id'],
                    owner_session_id=lock_owner_session_id,
                    owner_job_id=lock_owner_job_id,
                    force=False,
                )
                lock_released = True

            # Continue draining queue for the same device after errors too
            if 'dep' in locals() and dep and dep.get('device_id'):
                self._schedule_next_queued_for_device(dep['device_id'], after_error=True)
        except Exception as fatal_error:
            if lock_acquired and dep and not lock_released:
                self._release_server_execution_lock(
                    host_name=dep['host_name'],
                    device_id=dep['device_id'],
                    owner_session_id=lock_owner_session_id,
                    owner_job_id=lock_owner_job_id,
                    force=True,
                )
                lock_released = True
            # Catch-all for ANY unhandled exception (syntax errors, missing imports, etc.)
            print(f"[@deployment_scheduler] 🔥 FATAL ERROR in deployment execution: {fatal_error}")
            print(f"[@deployment_scheduler] 🔥 Error type: {type(fatal_error).__name__}")
            print(f"[@deployment_scheduler] 🔥 Full error: {repr(fatal_error)}")
            deployment_logger.error(f"🔥 FATAL: {deployment_id} | {type(fatal_error).__name__}: {fatal_error}")
            deployment_logger.error(f"🔥 FATAL: {deployment_id} | Full: {repr(fatal_error)}")
            import traceback
            traceback.print_exc()
            deployment_logger.error(f"🔥 FATAL: {deployment_id} | Traceback: {traceback.format_exc()}")
        finally:
            # Last-resort guarantee: release the server lock no matter how we exit.
            # Covers the silent-greenlet-death case (gevent GreenletExit is a
            # BaseException, so it skips every `except Exception` release path above
            # but still runs this finally). force=False keeps the server-side
            # owner_session_id guard intact, so a successor run's lock is never
            # clobbered by this dead run.
            if lock_acquired and dep and not lock_released:
                try:
                    self._release_server_execution_lock(
                        host_name=dep['host_name'],
                        device_id=dep['device_id'],
                        owner_session_id=lock_owner_session_id,
                        owner_job_id=lock_owner_job_id,
                        force=False,
                    )
                    lock_released = True
                    deployment_logger.error(
                        f"🔓 LOCK RECOVERY: released server lock for {dep['host_name']}:{dep['device_id']} "
                        f"in finally (normal release path did not run)"
                    )
                except Exception as lock_err:
                    deployment_logger.error(f"Lock recovery in finally failed: {lock_err}")

            # Last-resort guarantee: if exec_id was created but completed_at was never written
            # (DB update failed in both success and exception paths), write it now.
            if exec_id and not completion_written:
                try:
                    deployment_logger.error(f"🔥 GHOST RECORD RECOVERY: writing completed_at for exec_id={exec_id} (completion_written was False)")
                    with self.db_lock:
                        self.supabase.table('deployment_executions').update({
                            'completed_at': datetime.now(timezone.utc).isoformat(),
                            'status': 'failed',
                            'success': False,
                            'error_message': 'completed_at not written by normal path — recovered in finally block'
                        }).eq('id', exec_id).execute()
                    deployment_logger.info(f"Ghost record recovery succeeded for exec_id={exec_id}")
                except Exception as final_error:
                    deployment_logger.error(f"Ghost record recovery ALSO failed for exec_id={exec_id}: {final_error}")

            # Always remove the per-device running.log once the run is done (any outcome).
            # Otherwise the file is only ever cleared at the START of the NEXT run, so a
            # device whose last run finished days ago keeps serving a stale log and the
            # frontend overlay stays stuck on "finishing..." with old steps.
            try:
                if 'dep' in locals() and dep and dep.get('device_id'):
                    finished_capture_folder = get_capture_folder_from_device_id(dep['device_id'])
                    if finished_capture_folder:
                        finished_log_path = get_running_log_path(finished_capture_folder)
                        if os.path.exists(finished_log_path):
                            os.remove(finished_log_path)
                            print(f"[@deployment_scheduler] Removed running log after completion: {finished_log_path}")
            except Exception as cleanup_error:
                print(f"[@deployment_scheduler] Failed to remove running log after completion: {cleanup_error}")

    def add_deployment(self, deployment):
        """Add new deployment (called by API)"""
        deployment_logger.info(f"API: Adding new deployment: {deployment.get('name')}")
        self._add_job(deployment, log_details=True)

        # Check if we should execute immediately (avoid conflicts with upcoming cron triggers)
        if self._is_future_one_shot(deployment):
            deployment_logger.info(f"📅 ONE-SHOT SCHEDULED: {deployment.get('name')} | Start: {deployment.get('start_date')}")
            return

        job = self.scheduler.get_job(deployment['id'])
        if job and job.next_run_time:
            time_to_next = (job.next_run_time - datetime.now(timezone.utc)).total_seconds()
            estimated_duration = self._get_estimated_duration(
                deployment['script_name'],
                deployment['device_id'],
                deployment.get('id')
            )

            # Only execute immediately if there's enough time before next cron trigger
            # Need at least estimated_duration + 5 minute buffer
            min_buffer_seconds = estimated_duration + 300  # 5 minutes buffer

            if time_to_next > min_buffer_seconds:
                deployment_logger.info(f"🚀 EXECUTING IMMEDIATELY: {deployment.get('name')} | Next cron in {time_to_next:.0f}s, duration estimate: {estimated_duration:.0f}s")
                self._start_immediate_execution(
                    deployment['id'],
                    queued_execution_id=None,
                    reason='create',
                )
            else:
                deployment_logger.info(f"⏰ SKIPPING IMMEDIATE EXEC: {deployment.get('name')} | Next cron in {time_to_next:.0f}s (too soon, estimate: {estimated_duration:.0f}s)")
        else:
            # No scheduled job found, execute immediately as fallback
            deployment_logger.info(f"🚀 EXECUTING IMMEDIATELY: {deployment.get('name')} | No cron schedule found")
            self._start_immediate_execution(
                deployment['id'],
                queued_execution_id=None,
                reason='create',
            )

    def update_deployment(self, deployment):
        """Refresh an existing deployment schedule without create-time side effects."""
        deployment_id = deployment['id']
        self._cancel_wait_lock_retry(deployment_id)

        existing_job = self.scheduler.get_job(deployment_id)
        if existing_job:
            self.scheduler.remove_job(deployment_id)

        if deployment.get('status') != 'active':
            deployment_logger.info(
                f"🔁 UPDATED: {deployment.get('name', deployment_id)} | "
                f"status={deployment.get('status')} | removed from scheduler"
            )
            return

        self._add_job(deployment, log_details=True)
        job = self.scheduler.get_job(deployment_id)
        next_run = job.next_run_time if job else None
        deployment_logger.info(
            f"🔁 UPDATED: {deployment.get('name', deployment_id)} | "
            f"Schedule: {deployment.get('start_date') if self._is_future_one_shot(deployment) else deployment.get('cron_expression')} | "
            f"Next run: {next_run} UTC"
        )

    def run_deployment_now(self, deployment_id: str):
        """Force enqueue a deployment job to execute immediately"""
        try:
            with self.db_lock:
                dep_result = self.supabase.table('deployments').select(
                    'id, name, max_executions, execution_count'
                ).eq('id', deployment_id).limit(1).execute()
            dep = (dep_result.data or [None])[0]
            if not dep:
                deployment_logger.warning(f"MANUAL TRIGGER IGNORED: {deployment_id} | deployment not found")
                return

            with self.db_lock:
                exec_result = self.supabase.table('deployment_executions').select(
                    'id, status, started_at, completed_at'
                ).eq('deployment_id', deployment_id).order('scheduled_at', desc=True).limit(10).execute()

            executions = exec_result.data or []
            if any(row.get('status') in {'queued', 'running'} for row in executions):
                deployment_logger.info(
                    f"MANUAL TRIGGER IGNORED: {deployment_id} | reason=already_active_or_queued"
                )
                return

            max_executions = dep.get('max_executions')
            execution_count = dep.get('execution_count') or 0
            has_terminal_execution = any(
                row.get('status') in {'completed', 'failed', 'skipped', 'aborted'}
                for row in executions
            )
            if max_executions == 1 and (execution_count >= 1 or has_terminal_execution):
                deployment_logger.info(
                    f"MANUAL TRIGGER IGNORED: {deployment_id} | reason=max_executions_reached"
                )
                return
        except Exception as guard_error:
            deployment_logger.warning(
                f"MANUAL TRIGGER GUARD FAILED: {deployment_id} | proceeding anyway | {guard_error}"
            )

        self._start_immediate_execution(
            deployment_id,
            queued_execution_id=None,
            reason='manual',
        )
        deployment_logger.info(f"MANUAL TRIGGER: {deployment_id} | mode=direct-thread")
    
    def pause_deployment(self, deployment_id):
        """Pause deployment by removing from scheduler"""
        try:
            self._cancel_wait_lock_retry(deployment_id)
            self.scheduler.remove_job(deployment_id)
            print(f"[@deployment_scheduler] Paused (removed from scheduler): {deployment_id}")
            deployment_logger.info(f"⏸️  PAUSED: {deployment_id} | Removed from scheduler")
        except Exception as e:
            print(f"[@deployment_scheduler] Error pausing deployment: {e}")
            deployment_logger.error(f"Failed to pause deployment {deployment_id}: {e}")
    
    def resume_deployment(self, deployment_id):
        """Resume deployment by re-adding to scheduler"""
        try:
            # Fetch deployment from database
            with self.db_lock:
                result = self.supabase.table('deployments').select('*').eq('id', deployment_id).execute()
            if not result.data or len(result.data) == 0:
                print(f"[@deployment_scheduler] Cannot resume - deployment not found: {deployment_id}")
                deployment_logger.error(f"Cannot resume - deployment not found: {deployment_id}")
                return
            
            deployment = result.data[0]
            
            # Re-add job to scheduler
            self._add_job(deployment, log_details=True)
            print(f"[@deployment_scheduler] Resumed (re-added to scheduler): {deployment_id}")
            
            job = self.scheduler.get_job(deployment_id)
            next_run = job.next_run_time if job else None
            deployment_logger.info(f"▶️  RESUMED: {deployment.get('name', deployment_id)} | Next run: {next_run} UTC")
        except Exception as e:
            print(f"[@deployment_scheduler] Error resuming deployment: {e}")
            deployment_logger.error(f"Failed to resume deployment {deployment_id}: {e}")
    
    def remove_deployment(self, deployment_id):
        """Remove deployment"""
        self._cancel_wait_lock_retry(deployment_id)
        self.scheduler.remove_job(deployment_id)
        print(f"[@deployment_scheduler] Removed: {deployment_id}")
        deployment_logger.info(f"🗑️  REMOVED: {deployment_id}")

# Global instance
_scheduler = None

def get_deployment_scheduler():
    global _scheduler
    if not _scheduler:
        from backend_host.src.lib.utils.host_utils import get_host_instance
        host = get_host_instance()
        _scheduler = DeploymentScheduler(host.host_name)
        _scheduler.start()
    return _scheduler
