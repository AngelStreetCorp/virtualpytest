"""
Analysis Tools

Tools for querying and analyzing execution results.
Reports are pre-fetched using backend_server.src.lib.report_fetcher (saves tokens).
"""

from datetime import datetime, timezone
from typing import Dict, Any, Optional

from shared.src.lib.utils.supabase_utils import get_supabase_client


class AnalysisTools:
    """Tools for analyzing execution results"""

    CLASSIFICATIONS = {
        'VALID_PASS', 'VALID_FAIL', 'BUG', 'SCRIPT_ISSUE',
        'SYSTEM_ISSUE', 'EXTERNAL_BLOCK',
    }
    DISCARD_CLASSIFICATIONS = {'SCRIPT_ISSUE', 'SYSTEM_ISSUE'}
    
    def __init__(self):
        self.supabase = None
        self.session_started = datetime.now(timezone.utc)
        
        # Session stats - tracked in memory as we process
        self.stats = {
            'processed': 0,
            'discarded': 0,
            'kept': 0,
            'by_classification': {},
            'last_processed': None,  # {id, script_name, classification, timestamp}
            'history': []  # Last N processed items
        }
    
    def _get_supabase(self):
        """Lazy load supabase client"""
        if self.supabase is None:
            self.supabase = get_supabase_client()
        return self.supabase
    
    def get_execution_results(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Get execution results from database with filters. Automatically fetches and includes report content.
        
        Example: get_execution_results(userinterface_name='google_tv', limit=5)
        
        Args:
            params: {
                'script_name': str (OPTIONAL - filter by script name, e.g., 'dns_test.py'),
                'userinterface_name': str (OPTIONAL - filter by interface),
                'device_name': str (OPTIONAL - filter by device),
                'host_name': str (OPTIONAL - filter by host),
                'success': bool (OPTIONAL - filter by success status),
                'limit': int (OPTIONAL - max results default 1)
            }
        
        Returns:
            List of execution results with pre-fetched report content
        """
        try:
            supabase = self._get_supabase()
            
            script_name = params.get('script_name')
            userinterface_name = params.get('userinterface_name')
            device_name = params.get('device_name')
            host_name = params.get('host_name')
            success = params.get('success')
            checked = params.get('checked')
            limit = params.get('limit', 1)
            include_report = params.get('include_report', True)  # Default True

            print(f"[@analysis] get_execution_results: script={script_name}, ui={userinterface_name}, device={device_name}, host={host_name}, success={success}, limit={limit}, include_report={include_report}")

            # Build query
            query = supabase.table('script_results').select('*')

            # Apply filters
            if script_name:
                query = query.eq('script_name', script_name)
            if userinterface_name:
                query = query.eq('userinterface_name', userinterface_name)
            if device_name:
                query = query.eq('device_name', device_name)
            if host_name:
                query = query.eq('host_name', host_name)
            if success is not None:
                query = query.eq('success', success)
            if checked is not None:
                query = query.eq('checked', checked)
            
            # Order by most recent and limit
            result = query.order('created_at', desc=True).limit(limit).execute()
            
            if not result.data:
                return {
                    "content": [{"type": "text", "text": "No execution results found matching criteria"}],
                    "isError": False,
                    "results": []
                }
            
            # Format results for agent
            formatted_results = []
            for r in result.data:
                formatted = {
                    'id': r.get('id'),
                    'script_name': r.get('script_name'),
                    'script_type': r.get('script_type'),
                    'userinterface_name': r.get('userinterface_name'),
                    'device_name': r.get('device_name'),
                    'host_name': r.get('host_name'),
                    'success': r.get('success'),
                    'error_msg': r.get('error_msg'),
                    'execution_time_ms': r.get('execution_time_ms'),
                    'html_report_r2_url': r.get('html_report_r2_url'),
                    'logs_url': r.get('logs_url'),
                    'created_at': r.get('created_at'),
                    # Analysis fields
                    'checked': r.get('checked', False),
                    'check_type': r.get('check_type'),
                    'discard': r.get('discard', False),
                    'discard_comment': r.get('discard_comment'),
                    'metadata': r.get('metadata') if isinstance(r.get('metadata'), dict) else {}
                }
                metadata = formatted['metadata']
                if metadata:
                    formatted['verification_review_url'] = metadata.get('verification_review_r2_url')
                    formatted['verification_review_path'] = metadata.get('verification_review_r2_path')
                formatted_results.append(formatted)
            
            # Pre-fetch report content if requested (default True)
            if include_report and formatted_results:
                from backend_server.src.lib.report_fetcher import fetch_execution_report
                
                for r in formatted_results:
                    report_url = r.get('html_report_r2_url')
                    logs_url = r.get('logs_url')
                    
                    if report_url:
                        try:
                            report_data = fetch_execution_report(report_url, logs_url)
                            r['report_content'] = report_data.get('summary', '')
                        except Exception as e:
                            print(f"[@analysis] Warning: Failed to fetch report for {r['id']}: {e}")
                            r['report_content'] = None
            
            # Build summary text
            summary_lines = [f"Found {len(formatted_results)} execution result(s):\n"]
            for i, r in enumerate(formatted_results, 1):
                status = "✅ PASS" if r['success'] else "❌ FAIL"
                checked_status = f" [Analyzed: {r['check_type']}]" if r['checked'] else " [Not analyzed]"
                summary_lines.append(f"{i}. {r['script_name']} ({r['script_type']})")
                summary_lines.append(f"   SCRIPT_RESULT_ID: {r['id']}")
                summary_lines.append(f"   Status: {status}{checked_status}")
                summary_lines.append(f"   Interface: {r['userinterface_name']} | Device: {r['device_name']}")
                summary_lines.append(f"   Duration: {r['execution_time_ms']}ms")
                if r['error_msg']:
                    summary_lines.append(f"   Error: {r['error_msg'][:100]}")
                if r['discard_comment']:
                    summary_lines.append(f"   Analysis: {r['discard_comment'][:100]}")
                review_url = r.get('verification_review_url')
                if review_url:
                    summary_lines.append(f"   Review Markdown URL: {review_url}")
                
                # Include pre-fetched report content
                if r.get('report_content'):
                    summary_lines.append(f"\n{r['report_content']}")
                
                summary_lines.append("")
            
            return {
                "content": [{"type": "text", "text": "\n".join(summary_lines)}],
                "isError": False,
                "results": formatted_results
            }
            
        except Exception as e:
            print(f"[@analysis] Error in get_execution_results: {e}")
            return {
                "content": [{"type": "text", "text": f"Error querying execution results: {e}"}],
                "isError": True
            }
    
    def update_execution_analysis(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Save analysis results to database.
        
        Example: update_execution_analysis(script_result_id='123', classification='BUG', explanation='Button not found')
        
        Args:
            params: {
                'script_result_id': str (REQUIRED - ID of script result to update),
                'discard': bool (OPTIONAL - true if false positive),
                'classification': str (REQUIRED - BUG SCRIPT_ISSUE SYSTEM_ISSUE EXTERNAL_BLOCK VALID_PASS VALID_FAIL),
                'explanation': str (REQUIRED - brief analysis explanation)
            }
        
        Returns:
            Success/failure status
        """
        try:
            supabase = self._get_supabase()
            
            script_result_id = params.get('script_result_id')
            discard = params.get('discard')
            classification = params.get('classification')
            explanation = params.get('explanation')
            
            if not script_result_id:
                return {
                    "content": [{"type": "text", "text": "Error: script_result_id is required"}],
                    "isError": True
                }
            
            if discard is None:
                return {
                    "content": [{"type": "text", "text": "Error: discard (true/false) is required"}],
                    "isError": True
                }
            
            if not classification:
                return {
                    "content": [{"type": "text", "text": "Error: classification is required"}],
                    "isError": True
                }

            classification = str(classification).strip().upper()
            if classification not in self.CLASSIFICATIONS:
                return {
                    "content": [{"type": "text", "text": (
                        "Error: classification must be one of "
                        f"{', '.join(sorted(self.CLASSIFICATIONS))}"
                    )}],
                    "isError": True
                }
            
            if not explanation:
                return {
                    "content": [{"type": "text", "text": "Error: explanation is required"}],
                    "isError": True
                }

            expected_discard = classification in self.DISCARD_CLASSIFICATIONS
            if bool(discard) != expected_discard:
                return {
                    "content": [{"type": "text", "text": (
                        f"Error: {classification} requires discard={str(expected_discard).lower()}"
                    )}],
                    "isError": True
                }
            
            # Build comment with classification
            discard_comment = f"[{classification}] {explanation[:200]}"
            
            print(f"[@analysis] update_execution_analysis: id={script_result_id}, discard={discard}, class={classification}")
            
            # Update database
            update_data = {
                'checked': True,
                'check_type': 'ai_agent',
                'discard': discard,
                'discard_comment': discard_comment,
                'updated_at': datetime.now(timezone.utc).isoformat()
            }
            
            result = supabase.table('script_results').update(update_data).eq('id', script_result_id).execute()
            
            if result.data:
                # Track session stats
                self.stats['processed'] += 1
                if discard:
                    self.stats['discarded'] += 1
                else:
                    self.stats['kept'] += 1
                
                # Track by classification
                if classification not in self.stats['by_classification']:
                    self.stats['by_classification'][classification] = 0
                self.stats['by_classification'][classification] += 1
                
                # Track last processed
                script_name = result.data[0].get('script_name', 'unknown') if result.data else 'unknown'
                script_type = result.data[0].get('script_type', '') if result.data else ''
                userinterface = result.data[0].get('userinterface_name', '') if result.data else ''
                
                self.stats['last_processed'] = {
                    'id': script_result_id,
                    'script_name': script_name,
                    'classification': classification,
                    'discard': discard,
                    'timestamp': datetime.now(timezone.utc).isoformat()
                }
                
                # Keep history (last 20)
                self.stats['history'].append(self.stats['last_processed'])
                if len(self.stats['history']) > 20:
                    self.stats['history'] = self.stats['history'][-20:]
                
                # Build rich markdown response
                action_text = "DISCARDED" if discard else "KEPT"
                action_icon = "❌" if discard else "✅"
                
                # Classification indicator
                class_icon = "✅" if classification == 'VALID_PASS' else "❌" if classification in ('BUG', 'VALID_FAIL') else ""
                class_display = f"{class_icon} **{classification}**" if class_icon else f"**{classification}**"
                
                markdown_response = f"""## {action_icon} Analysis Saved

| Field | Value |
|-------|-------|
| **Script** | `{script_name}` |
| **Type** | {script_type or 'N/A'} |
| **Interface** | {userinterface or 'N/A'} |
| **Classification** | {class_display} |
| **Action** | {action_text} |

### Reasoning
> {explanation}

---
*Result ID: `{script_result_id[:8]}...`*"""

                return {
                    "content": [{"type": "text", "text": markdown_response}],
                    "isError": False
                }
            else:
                return {
                    "content": [{"type": "text", "text": f"Error: Script result {script_result_id} not found"}],
                    "isError": True
                }
            
        except Exception as e:
            print(f"[@analysis] Error in update_execution_analysis: {e}")
            return {
                "content": [{"type": "text", "text": f"Error updating analysis: {e}"}],
                "isError": True
            }
    
    def get_analysis_queue_status(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Get analysis queue status with pending items and session processing stats.
        
        Example: get_analysis_queue_status()
        
        Args:
            params: {}
        
        Returns:
            Queue lengths and session statistics
        """
        try:
            # Get Redis queue lengths
            queue_status = self._get_redis_queue_status()
            
            # Calculate session uptime
            uptime = datetime.now(timezone.utc) - self.session_started
            uptime_str = f"{int(uptime.total_seconds())}s"
            if uptime.total_seconds() > 60:
                uptime_str = f"{int(uptime.total_seconds() / 60)}m {int(uptime.total_seconds() % 60)}s"
            if uptime.total_seconds() > 3600:
                uptime_str = f"{int(uptime.total_seconds() / 3600)}h {int((uptime.total_seconds() % 3600) / 60)}m"
            
            # Build summary from session stats (no DB queries!)
            lines = [
                "═══ ANALYSIS QUEUE STATUS ═══\n",
                f"⏱️  Session Uptime: {uptime_str}",
                "",
                "📊 Redis Queues (Pending):",
                f"   • P1 Alerts:  {queue_status.get('p1_alerts', 0)}",
                f"   • P2 Scripts: {queue_status.get('p2_scripts', 0)}",
                f"   • P3 Reserved: {queue_status.get('p3_reserved', 0)}",
                "",
                "📈 Session Stats (This Session):",
                f"   • Processed:  {self.stats['processed']}",
                f"   • Kept:       {self.stats['kept']}",
                f"   • Discarded:  {self.stats['discarded']}",
            ]
            
            if self.stats['processed'] > 0:
                discard_rate = (self.stats['discarded'] / self.stats['processed']) * 100
                lines.append(f"   • Discard Rate: {discard_rate:.1f}%")
            
            # Classification breakdown
            if self.stats['by_classification']:
                lines.append("")
                lines.append("🏷️  Classification Breakdown:")
                for cls, count in self.stats['by_classification'].items():
                    lines.append(f"   • {cls}: {count}")
            
            # Last processed
            if self.stats['last_processed']:
                last = self.stats['last_processed']
                lines.append("")
                lines.append("📝 Last Processed:")
                lines.append(f"   • Script: {last['script_name']}")
                lines.append(f"   • Classification: {last['classification']}")
                lines.append(f"   • Action: {'Discarded' if last['discard'] else 'Kept'}")
            
            return {
                "content": [{"type": "text", "text": "\n".join(lines)}],
                "isError": False,
                "queue_status": queue_status,
                "session_stats": self.stats
            }
            
        except Exception as e:
            print(f"[@analysis] Error in get_analysis_queue_status: {e}")
            return {
                "content": [{"type": "text", "text": f"Error getting queue status: {e}"}],
                "isError": True
            }
    
    def get_alerts(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Query alerts/incidents from the database. Use this to look up past or active incidents.

        Example: get_alerts()
        Example: get_alerts(status='active')
        Example: get_alerts(host_name='host1', device_name='tv1', limit=10)
        Example: get_alerts(incident_type='blackscreen', status='resolved', limit=5)

        Args:
            params: {
                'alert_id': str (OPTIONAL - fetch a single alert by ID),
                'host_name': str (OPTIONAL - filter by host),
                'device_name': str (OPTIONAL - filter by device name),
                'device_id': str (OPTIONAL - filter by device id),
                'incident_type': str (OPTIONAL - e.g. blackscreen, app_crash, anr),
                'status': str (OPTIONAL - 'active', 'resolved', or omit for both),
                'limit': int (OPTIONAL - max results per status bucket, default 20)
            }

        Returns:
            List of alerts with incident details
        """
        try:
            from shared.src.lib.database.alerts_db import (
                get_alert_by_id, get_active_alerts, get_closed_alerts, get_all_alerts
            )

            alert_id = params.get('alert_id')
            host_name = params.get('host_name')
            device_name = params.get('device_name')
            device_id = params.get('device_id')
            incident_type = params.get('incident_type')
            status = params.get('status')
            limit = int(params.get('limit', 20))

            print(f"[@analysis] get_alerts: id={alert_id}, host={host_name}, device={device_name or device_id}, type={incident_type}, status={status}, limit={limit}")

            # Single alert lookup
            if alert_id:
                alert = get_alert_by_id(alert_id)
                if not alert:
                    return {"content": [{"type": "text", "text": f"Alert {alert_id} not found"}], "isError": False}
                alerts = [alert]
            elif status == 'active':
                result = get_active_alerts(host_name=host_name, device_id=device_id or device_name, incident_type=incident_type, limit=limit)
                alerts = result.get('alerts', [])
            elif status == 'resolved':
                result = get_closed_alerts(host_name=host_name, device_id=device_id or device_name, incident_type=incident_type, limit=limit)
                alerts = result.get('alerts', [])
            else:
                result = get_all_alerts(host_name=host_name, device_id=device_id or device_name, incident_type=incident_type, active_limit=limit, resolved_limit=limit)
                alerts = result.get('alerts', [])

            if not alerts:
                return {"content": [{"type": "text", "text": "No alerts found matching criteria"}], "isError": False, "alerts": []}

            # Format summary
            lines = [f"Found {len(alerts)} alert(s):\n"]
            for i, a in enumerate(alerts, 1):
                status_icon = "🔴" if a.get('status') == 'active' else "✅"
                lines.append(f"{i}. {status_icon} [{a.get('incident_type', 'unknown')}] on {a.get('device_name') or a.get('device_id')} @ {a.get('host_name')}")
                lines.append(f"   ID: {a.get('id')}")
                lines.append(f"   Status: {a.get('status')} | Started: {a.get('start_time', '')[:19]}")
                if a.get('end_time'):
                    lines.append(f"   Ended: {a.get('end_time', '')[:19]}")
                if a.get('discard_comment'):
                    lines.append(f"   Analysis: {a.get('discard_comment')[:120]}")
                elif not a.get('checked'):
                    lines.append(f"   Analysis: not yet checked")
                lines.append("")

            return {
                "content": [{"type": "text", "text": "\n".join(lines)}],
                "isError": False,
                "alerts": alerts,
            }

        except Exception as e:
            print(f"[@analysis] Error in get_alerts: {e}")
            return {"content": [{"type": "text", "text": f"Error querying alerts: {e}"}], "isError": True}

    def _get_redis_queue_status(self) -> Dict[str, int]:
        """Get Redis queue lengths using unified Redis configuration"""
        try:
            from ....shared.src.lib.utils.redis_queue import get_queue_processor
            
            # Use shared queue processor (handles both Upstash and local Redis)
            queue_processor = get_queue_processor()
            return queue_processor.get_all_queue_lengths()
            
        except Exception as e:
            print(f"[@analysis] Error getting Redis queue status: {e}")
            return {'p1_alerts': 0, 'p2_scripts': 0, 'p3_reserved': 0, 'error': str(e)}
