#!/usr/bin/env python3
"""
Campaign Execution Framework for VirtualPyTest - Host Level

This module provides functionality to execute test campaigns that consist of
multiple script executions with proper tracking and reporting at the host level.

Usage:
    from  backend_host.src.lib.utils.campaign_executor import CampaignExecutor
    
    executor = CampaignExecutor()
    result = executor.execute_campaign(campaign_config)
"""

import os
import sys
import time
import platform
import subprocess
import threading
from datetime import datetime
from typing import Dict, List, Any, Optional
from uuid import uuid4

# Add project root to path for imports
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(os.path.dirname(current_dir)))

if project_root not in sys.path:
    sys.path.insert(0, project_root)

from shared.src.lib.database.campaign_executions_db import (
    record_campaign_execution_start,
    update_campaign_execution_result,
    add_script_result_to_campaign,
)
from shared.src.lib.utils.app_utils import load_environment_variables
from shared.src.lib.utils.campaign_identity_utils import resolve_campaign_identity
from shared.src.lib.utils.cloudflare_utils import upload_script_logs, upload_script_report
from shared.src.lib.utils.report_generation_utils import generate_campaign_orchestrator_report
# REMOVED top-level import: from backend_host.src.lib.utils.host_utils import get_host_instance
# Now lazy-loaded where needed
from .script_executor import DEFAULT_TEAM_ID


class CampaignExecutionContext:
    """Context object that holds campaign execution state"""
    
    def __init__(self, campaign_id: str, campaign_name: str):
        self.campaign_id = campaign_id
        self.campaign_name = campaign_name
        self.campaign_execution_id = f"campaign_exec_{int(time.time())}_{str(uuid4())[:8]}"
        self.start_time = time.time()
        
        # Infrastructure
        self.team_id = None
        self.host = None
        self.current_os = "unknown"
        
        # Execution tracking
        self.campaign_result_id = None
        self.script_executions = []
        self.overall_success = False
        self.error_message = ""
        self.metadata = {}
        self.campaign_identity = {}
        self.orchestrator_report_url = None
        self.orchestrator_report_path = None
        self.orchestrator_logs_url = None
        self.orchestrator_logs_path = None
        
        # Statistics
        self.total_scripts = 0
        self.completed_scripts = 0
        self.successful_scripts = 0
        self.failed_scripts = 0
        self.skipped_scripts = 0
    
    def get_execution_time_ms(self) -> int:
        """Get current execution time in milliseconds"""
        return int((time.time() - self.start_time) * 1000)


class CampaignExecutor:
    """Campaign execution orchestrator for host-level execution"""
    
    def __init__(self):
        self.project_root = project_root
        self._abort_requested = False
        self._abort_reason = ""
        self._abort_lock = threading.Lock()
        self._active_device_id: Optional[str] = None

    def request_abort(self, device_id: Optional[str] = None, reason: str = 'Aborted by user') -> Dict[str, Any]:
        """Request campaign abort and stop currently running script on device when possible."""
        with self._abort_lock:
            self._abort_requested = True
            self._abort_reason = reason

        target_device = device_id or self._active_device_id
        aborted_current_script = False
        if target_device:
            try:
                from .script_executor import abort_running_script
                abort_result = abort_running_script(target_device)
                aborted_current_script = bool(abort_result.get('aborted'))
            except Exception as e:
                print(f"[@Campaign] Failed to abort current script on {target_device}: {e}")

        return {
            'success': True,
            'abort_requested': True,
            'aborted_current_script': aborted_current_script,
            'device_id': target_device,
            'reason': reason,
        }
    
    def execute_campaign(self, campaign_config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute a test campaign with multiple scripts at host level.
        
        Args:
            campaign_config: Campaign configuration dictionary
            
        Example campaign_config:
        {
            "campaign_id": "fullzap-double-test",
            "name": "Fullzap Double Execution Test",
            "description": "Execute tv/fullzap.py twice in a row",
            "userinterface_name": "example_mobile",
            "host": "auto",  # or specific host name
            "device": "auto",  # or specific device name
            "execution_config": {
                "continue_on_failure": True,
                "timeout_minutes": 60,
                "parallel": False
            },
            "script_configurations": [
                {
                    "script_name": "tv/fullzap.py",
                    "script_type": "fullzap",
                    "parameters": {
                        "action": "live_chup",
                        "max_iteration": 5,
                        "goto_live": True
                    }
                },
                {
                    "script_name": "tv/fullzap.py", 
                    "script_type": "fullzap",
                    "parameters": {
                        "action": "live_chdown", 
                        "max_iteration": 3,
                        "goto_live": False
                    }
                }
            ]
        }
        """
        context = CampaignExecutionContext(
            campaign_config["campaign_id"],
            campaign_config["name"]
        )
        
        try:
            print(f"🚀 [Campaign] Starting campaign: {context.campaign_name}")
            print(f"📋 [Campaign] Execution ID: {context.campaign_execution_id}")
            
            # Setup environment at host level
            if not self._setup_campaign_environment(context, campaign_config):
                return self._build_failure_result(context, "Failed to setup campaign environment")

            # Resolve stable campaign identity plus optional prefix/display overrides
            context.campaign_identity = resolve_campaign_identity(
                campaign_id=campaign_config.get("campaign_id"),
                campaign_name=campaign_config.get("name"),
            )
            identity_meta = self._build_campaign_identity_metadata(context)
            if identity_meta:
                print(f"🆔 [Campaign] Identity metadata: {identity_meta}")
            
            # Record campaign execution start in database (simplified single table)
            context.campaign_result_id = record_campaign_execution_start(
                team_id=context.team_id,
                campaign_name=context.campaign_name,
                campaign_execution_id=context.campaign_execution_id,
                userinterface_name=campaign_config.get("userinterface_name"),
                host_name=context.host.host_name,
                device_name=campaign_config.get("device", "auto"),
                description=campaign_config.get("description", ""),
                script_configurations=campaign_config.get("script_configurations", []),
                execution_config=campaign_config.get("execution_config", {}),
                executed_by=None,  # Could be passed from API context
                metadata=self._build_start_metadata(context, campaign_config),
            )
            
            if not context.campaign_result_id:
                return self._build_failure_result(context, "Failed to record campaign start in database")
            
            # Execute scripts
            script_configs = campaign_config.get("script_configurations", [])
            context.total_scripts = len(script_configs)
            
            if context.total_scripts == 0:
                return self._build_failure_result(context, "No scripts configured for execution")
            
            print(f"📊 [Campaign] Executing {context.total_scripts} script configurations")
            
            execution_config = campaign_config.get("execution_config", {})
            continue_on_failure = execution_config.get("continue_on_failure", True)
            consecutive_host_timeouts = 0
            
            for i, script_config in enumerate(script_configs, 1):
                if self._abort_requested:
                    context.error_message = self._abort_reason or "Campaign aborted by user"
                    print(f"🛑 [Campaign] {context.error_message}")
                    break

                print(f"\n{'='*60}")
                print(f"🎯 [Campaign] Executing script {i}/{context.total_scripts}")
                print(f"📜 Script: {script_config.get('script_name')}")
                print(f"🔧 Type: {script_config.get('script_type')}")
                print(f"{'='*60}")
                
                script_result = self._execute_single_script(
                    context, campaign_config, script_config, i
                )
                
                context.script_executions.append(script_result)
                context.completed_scripts += 1

                # Link the script result to this campaign execution
                sid = script_result.get("script_result_id")
                if sid and context.campaign_result_id:
                    try:
                        add_script_result_to_campaign(context.campaign_result_id, sid)
                        print(f"🔗 [Campaign] Linked script result {sid} to campaign {context.campaign_result_id}")
                    except Exception as link_err:
                        print(f"⚠️ [Campaign] Could not link script result: {link_err}")

                if script_result.get("skipped"):
                    context.skipped_scripts += 1
                    print(f"⏭️ [Campaign] Script {i} skipped: {script_result.get('skip_reason', 'os mismatch')}")
                    continue

                if script_result["success"]:
                    context.successful_scripts += 1
                    print(f"✅ [Campaign] Script {i} completed successfully")
                    consecutive_host_timeouts = 0
                else:
                    context.failed_scripts += 1
                    print(f"❌ [Campaign] Script {i} failed: {script_result.get('error')}")
                    
                    # Auto-abort on consecutive host timeouts (504) to prevent deadlock
                    error_str = script_result.get('error', '')
                    if '504' in error_str and 'timed out' in error_str:
                        consecutive_host_timeouts += 1
                        if consecutive_host_timeouts >= 3:
                            context.error_message = f"Campaign auto-aborted: {consecutive_host_timeouts} consecutive host timeouts (504) - host worker likely deadlocked"
                            print(f"🛑 [Campaign] {context.error_message}")
                            break
                    else:
                        consecutive_host_timeouts = 0
                    
                    if not continue_on_failure:
                        context.error_message = f"Campaign stopped after script {i} failure"
                        print(f"🛑 [Campaign] {context.error_message}")
                        break
            
            # Determine overall success
            context.overall_success = (
                context.completed_scripts == context.total_scripts and 
                context.failed_scripts == 0
            )

            if self._abort_requested:
                context.overall_success = False
                if not context.error_message:
                    context.error_message = self._abort_reason or "Campaign aborted by user"

            print(f"📦 [Campaign] Generating orchestrator artifacts...")
            orchestrator_artifacts = self._generate_orchestrator_artifacts(context, campaign_config)
            print(f"📦 [Campaign] Orchestrator artifacts result: {orchestrator_artifacts}")
            if orchestrator_artifacts:
                context.orchestrator_report_url = orchestrator_artifacts.get("report_url")
                context.orchestrator_report_path = orchestrator_artifacts.get("report_path")
                context.orchestrator_logs_url = orchestrator_artifacts.get("logs_url")
                context.orchestrator_logs_path = orchestrator_artifacts.get("logs_path")
                context.metadata["orchestrator_artifacts"] = orchestrator_artifacts

            print(f"📦 [Campaign] Updating DB: report_url={context.orchestrator_report_url}, logs_url={context.orchestrator_logs_url}")
            # Update campaign result in database
            update_campaign_execution_result(
                campaign_execution_id_uuid=context.campaign_result_id,
                status="aborted" if self._abort_requested else "completed",
                completed_at=datetime.now(),
                execution_time_ms=context.get_execution_time_ms(),
                success=context.overall_success,
                error_message=context.error_message,
                html_report_r2_path=context.orchestrator_report_path,
                html_report_r2_url=context.orchestrator_report_url,
                logs_r2_path=context.orchestrator_logs_path,
                logs_r2_url=context.orchestrator_logs_url,
                metadata=self._merge_final_metadata(context),
            )

            return self._build_success_result(context)
            
        except Exception as e:
            context.error_message = f"Campaign execution error: {str(e)}"
            print(f"💥 [Campaign] {context.error_message}")
            
            if context.campaign_result_id:
                orchestrator_artifacts = self._generate_orchestrator_artifacts(context, campaign_config)
                if orchestrator_artifacts:
                    context.orchestrator_report_url = orchestrator_artifacts.get("report_url")
                    context.orchestrator_report_path = orchestrator_artifacts.get("report_path")
                    context.orchestrator_logs_url = orchestrator_artifacts.get("logs_url")
                    context.orchestrator_logs_path = orchestrator_artifacts.get("logs_path")
                    context.metadata["orchestrator_artifacts"] = orchestrator_artifacts
                update_campaign_execution_result(
                    campaign_execution_id_uuid=context.campaign_result_id,
                    status="failed",
                    completed_at=datetime.now(),
                    execution_time_ms=context.get_execution_time_ms(),
                    success=False,
                    error_message=context.error_message,
                    html_report_r2_path=context.orchestrator_report_path,
                    html_report_r2_url=context.orchestrator_report_url,
                    logs_r2_path=context.orchestrator_logs_path,
                    logs_r2_url=context.orchestrator_logs_url,
                    metadata=self._merge_final_metadata(context),
                )
            
            return self._build_failure_result(context, context.error_message)
    
    def _setup_campaign_environment(self, context: CampaignExecutionContext, campaign_config: Dict[str, Any]) -> bool:
        """Setup campaign execution environment at host level"""
        try:
            # Load environment variables first
            current_dir = os.path.dirname(os.path.abspath(__file__))  # /shared/src/lib/executors
            lib_dir = os.path.dirname(current_dir)                    # /shared/src/lib
            src_dir = os.path.dirname(lib_dir)                        # /shared/src
            shared_dir = os.path.dirname(src_dir)                     # /shared
            project_root = os.path.dirname(shared_dir)                # /virtualpytest
            backend_host_src = os.path.join(project_root, 'backend_host', 'src')
            
            print(f"🔧 [Campaign] Loading environment variables...")
            load_environment_variables(calling_script_dir=backend_host_src)
            
            # Create host instance and get team_id
            print(f"🏗️ [Campaign] Creating host instance...")
            from backend_host.src.lib.utils.host_utils import get_host_instance  # Lazy import
            context.host = get_host_instance()
            device_count = context.host.get_device_count()
            print(f"✅ [Campaign] Host created with {device_count} devices")
            
            if device_count == 0:
                context.error_message = "No devices configured"
                return False
            
            # Prefer the team_id threaded in by the caller (deployment scheduler /
            # Run-Tests campaign run) so virtual-script steps resolve against the
            # run's own team; fall back to the loaded env, then the default.
            context.team_id = (
                campaign_config.get('team_id')
                or os.getenv('TEAM_ID', DEFAULT_TEAM_ID)
            )
            
            print(f"🏗️ [Campaign] Environment setup completed")
            print(f"👥 Team ID: {context.team_id}")
            print(f"🖥️ Host: {context.host.host_name}")
            context.current_os = self._normalize_os_name(getattr(context.host, "host_os", None) or platform.system())
            print(f"💻 Host OS: {context.current_os}")
            
            return True
            
        except Exception as e:
            context.error_message = f"Environment setup error: {str(e)}"
            return False
    
    def _execute_single_script(self, context: CampaignExecutionContext, campaign_config: Dict[str, Any], 
                             script_config: Dict[str, Any], execution_order: int) -> Dict[str, Any]:
        """Execute a single script or testcase within the campaign"""
        script_start_time = time.time()
        script_name = script_config.get("script_name")
        script_type = script_config.get("script_type", script_name)
        parameters = script_config.get("parameters", {})
        testcase_id = script_config.get("testcase_id")  # NEW: For testcase execution
        # Virtual-script step: source lives in the DB (virtual_scripts), not on
        # disk. When set, the executor materializes it (and its _script_libs)
        # to a temp file just before launch — same path the Run-Tests flow uses.
        # None for ordinary disk steps, so their behavior is unchanged.
        virtual_script_id = script_config.get("virtual_script_id")
        self._active_device_id = campaign_config.get("device_id") or campaign_config.get("device", "device1")

        if self._abort_requested:
            return {
                "script_name": script_name,
                "script_type": script_type,
                "execution_order": execution_order,
                "success": False,
                "execution_time_ms": 0,
                "error": self._abort_reason or "Campaign aborted by user",
                "script_outputs": {},
            }

        required_oses = self._get_required_oses(script_config)
        if required_oses and context.current_os not in required_oses:
            skip_reason = (
                f"os_mismatch: requires {', '.join(required_oses)}; current host os is {context.current_os}"
            )
            print(f"⏭️ [Campaign] Skipping {script_name}: {skip_reason}")
            return {
                "success": True,
                "skipped": True,
                "skip_reason": skip_reason,
                "required_oses": required_oses,
                "current_os": context.current_os,
                "script_name": script_name,
                "script_result_id": None,
                "execution_time_ms": 0,
                "execution_order": execution_order,
                "report_url": None,
                "logs_url": None,
            }
        
        # NEW: Resolve template variables in parameters (${previous.X}, ${script_N.X})
        resolved_parameters = self._resolve_template_parameters(context, parameters, execution_order)
        
        try:
            # NEW: Handle testcase execution differently
            if script_type == "testcase" and testcase_id:
                return self._execute_testcase(
                    context, 
                    campaign_config, 
                    script_config, 
                    execution_order,
                    resolved_parameters
                )
            
            # AUTO-DETECT: Check if script_name is a DB-stored testcase.
            # Skip for virtual-script steps: their name refers to a virtual_scripts
            # row, not a testcase, and virtual_script_id already pins the source.
            if not testcase_id and not virtual_script_id:
                try:
                    from shared.src.lib.database.testcase_db import get_testcase_by_name
                    tc = get_testcase_by_name(script_name, context.team_id)
                    if tc:
                        tc_id = tc.get('testcase_id') or tc.get('id')
                        print(f"🔍 [Campaign] Auto-detected DB testcase: {script_name} (ID: {tc_id})")
                        script_config_with_id = dict(script_config)
                        script_config_with_id['testcase_id'] = tc_id
                        return self._execute_testcase(
                            context,
                            campaign_config,
                            script_config_with_id,
                            execution_order,
                            resolved_parameters
                        )
                except ImportError:
                    pass  # testcase_db not available, fall through to file-based
                except Exception as e:
                    print(f"🔍 [Campaign] Testcase lookup failed for {script_name}: {e}")
            
            # EXISTING: Script execution via ScriptExecutor (file-based)
            print(f"🚀 [Campaign] Executing script via host device script executor")
            
            # Use shared script executor instead of device-specific one
            from .script_executor import ScriptExecutor
            device_id = campaign_config.get("device_id") or campaign_config.get("device", "device1")
            
            # Get actual device model
            device_model = "unknown"
            try:
                from backend_host.src.lib.utils.host_utils import get_device_by_id
                device = get_device_by_id(device_id)
                if device:
                    device_model = device.device_model
            except Exception as e:
                print(f"🔍 [Campaign] Could not get device model: {e}")
            
            # Create script executor with device context
            script_executor = ScriptExecutor(
                script_name=script_name,  # Pass script name
                host_name=context.host.host_name,
                device_id=device_id,
                device_model=device_model  # Use actual device model
            )
            script_executor.set_team_id(context.team_id)
            
            # Build parameters string for script executor
            param_parts = []

            # Add userinterface_name as optional parameter (scripts declare if they need it)
            if campaign_config.get("userinterface_name"):
                param_parts.extend(["--userinterface", campaign_config["userinterface_name"]])

            print(f"🧾 [Campaign] {script_name} script_config keys: {list(script_config.keys())}")
            print(f"🧾 [Campaign] {script_name} parameters (raw from script_config): {parameters}")
            print(f"🧾 [Campaign] {script_name} parameters (resolved): {resolved_parameters}")

            # Add script-specific parameters first (they take priority)
            for param_name, param_value in resolved_parameters.items():
                param_parts.extend([f"--{param_name}", str(param_value)])

            # Add host and device only if not already set by script-specific parameters
            script_param_names = set(resolved_parameters.keys())
            if "host" not in script_param_names and campaign_config.get("host") and campaign_config["host"] != "auto":
                param_parts.extend(["--host", campaign_config["host"]])

            if "device" not in script_param_names and campaign_config.get("device") and campaign_config["device"] != "auto":
                param_parts.extend(["--device", campaign_config["device"]])
            
            # Join parameters with proper shell quoting to handle special characters
            import shlex
            parameters_string = " ".join(shlex.quote(part) for part in param_parts)
            
            print(f"🚀 [Campaign] Executing: {script_name} {parameters_string}")
            print(f"📋 [Campaign] Starting real-time script output:")
            print("=" * 80)
            
            # Execute script using shared script executor
            # Inherit caller_ip/caller_user from the parent campaign invocation
            # (set by server_campaign_execution_routes or env vars) and force type=campaign.
            from shared.src.lib.executors.script_executor import _normalize_trigger
            parent_trigger = campaign_config.get('trigger') if isinstance(campaign_config.get('trigger'), dict) else {}
            campaign_trigger = _normalize_trigger({
                'type': 'campaign',
                'caller_ip': parent_trigger.get('caller_ip'),
                'caller_user': parent_trigger.get('caller_user'),
            })
            result = script_executor.execute_script(
                script_name, parameters_string, trigger=campaign_trigger,
                device_info=campaign_config.get('device_info'),
                virtual_script_id=virtual_script_id, team_id=context.team_id,
            )
            
            print("=" * 80)
            print(f"📋 [Campaign] Script output ended")
            
            execution_time_ms = int((time.time() - script_start_time) * 1000)
            
            # Determine success from script executor result
            # Check for script-reported success first, then fall back to exit code
            script_success = result.get('script_success')
            if script_success is not None:
                success = script_success
                print(f"📊 [Campaign] Using script-reported success status: {success}")
            else:
                success = result.get('exit_code', 1) == 0
                print(f"📊 [Campaign] Using exit code for success status: {success} (code: {result.get('exit_code')})")
            
            # Extract script result ID from stdout if available
            script_result_id = None
            stdout = result.get('stdout', '')
            if stdout and 'SCRIPT_RESULT_ID:' in stdout:
                import re
                result_id_match = re.search(r'SCRIPT_RESULT_ID:([^\s\n]+)', stdout)
                if result_id_match:
                    script_result_id = result_id_match.group(1)
                    print(f"🔗 [Campaign] Captured script result ID: {script_result_id}")
            
            # Extract URLs from script executor result
            report_url = result.get('report_url', '')
            logs_url = result.get('logs_url', '')
            
            if success:
                print(f"✅ [Campaign] Script completed successfully in {execution_time_ms}ms")
                return {
                    "success": True,
                    "script_name": script_name,
                    "script_result_id": script_result_id,
                    "execution_time_ms": execution_time_ms,
                    "stdout": stdout,
                    "execution_order": execution_order,
                    "report_url": report_url,
                    "logs_url": logs_url,
                    "script_inputs": resolved_parameters,
                }
            else:
                error_msg = f"Script failed with exit code {result.get('exit_code', 1)}"
                print(f"❌ [Campaign] {error_msg}")
                print(f"📝 [Campaign] STDERR: {result.get('stderr', '')}")

                return {
                    "success": False,
                    "script_name": script_name,
                    "script_result_id": script_result_id,
                    "execution_time_ms": execution_time_ms,
                    "error": error_msg,
                    "stderr": result.get('stderr', ''),
                    "stdout": stdout,
                    "execution_order": execution_order,
                    "report_url": report_url,
                    "logs_url": logs_url,
                    "script_inputs": resolved_parameters,
                }
                
        except Exception as e:
            error_msg = f"Script execution error: {str(e)}"
            execution_time_ms = int((time.time() - script_start_time) * 1000)
            
            return {
                "success": False,
                "script_name": script_name,
                "script_result_id": None,
                "execution_time_ms": execution_time_ms,
                "error": error_msg,
                "execution_order": execution_order,
                "report_url": None,
                "logs_url": None
            }
    
    def _resolve_template_parameters(self, context: CampaignExecutionContext, 
                                    parameters: Dict[str, Any], current_order: int) -> Dict[str, Any]:
        """
        Resolve template variables in parameters.
        Supports: ${previous.output_name} and ${script_N.output_name}
        
        Args:
            context: Campaign execution context with script_executions history
            parameters: Parameters dict with potential template strings
            current_order: Current script execution order (1-based)
            
        Returns:
            Dict with resolved parameter values
        """
        import re
        
        resolved = {}
        template_pattern = r'\$\{([^}]+)\}'  # Matches ${...}
        
        for param_name, param_value in parameters.items():
            # Only process string values
            if not isinstance(param_value, str):
                resolved[param_name] = param_value
                continue
            
            # Find all template variables in the string
            matches = re.findall(template_pattern, param_value)
            
            if not matches:
                # No templates, use as-is
                resolved[param_name] = param_value
                continue
            
            # Resolve each template
            resolved_value = param_value
            for match in matches:
                template_var = f"${{{match}}}"
                
                # Parse template: "previous.output_name" or "script_N.output_name"
                parts = match.split('.')
                if len(parts) != 2:
                    print(f"⚠️ [Campaign] Invalid template format: {template_var}")
                    continue
                
                source, output_name = parts
                
                # Resolve based on source
                if source == "previous":
                    # Get previous script's outputs
                    if current_order > 1 and len(context.script_executions) >= current_order - 1:
                        prev_script = context.script_executions[current_order - 2]  # 0-indexed
                        output_value = prev_script.get('script_outputs', {}).get(output_name)
                        if output_value is not None:
                            resolved_value = resolved_value.replace(template_var, str(output_value))
                            print(f"✓ [Campaign] Resolved {template_var} = {output_value}")
                        else:
                            print(f"⚠️ [Campaign] Output not found: {template_var}")
                    else:
                        print(f"⚠️ [Campaign] No previous script for: {template_var}")
                
                elif source.startswith("script_"):
                    # Get specific script's outputs by order
                    try:
                        script_order = int(source.split('_')[1])
                        if script_order >= 1 and len(context.script_executions) >= script_order:
                            target_script = context.script_executions[script_order - 1]  # 0-indexed
                            output_value = target_script.get('script_outputs', {}).get(output_name)
                            if output_value is not None:
                                resolved_value = resolved_value.replace(template_var, str(output_value))
                                print(f"✓ [Campaign] Resolved {template_var} = {output_value}")
                            else:
                                print(f"⚠️ [Campaign] Output not found: {template_var}")
                        else:
                            print(f"⚠️ [Campaign] Script order out of range: {template_var}")
                    except (ValueError, IndexError) as e:
                        print(f"⚠️ [Campaign] Invalid script reference: {template_var} - {e}")
                else:
                    print(f"⚠️ [Campaign] Unknown template source: {template_var}")
            
            resolved[param_name] = resolved_value
        
        return resolved

    def _normalize_os_name(self, raw_os: Any) -> str:
        """Normalize OS strings to canonical values used by campaign constraints."""
        value = str(raw_os or "").strip().lower()
        aliases = {
            "win32": "windows",
            "windows": "windows",
            "linux": "linux",
            "darwin": "macos",
            "mac": "macos",
            "macos": "macos",
            "osx": "macos",
        }
        return aliases.get(value, value or "unknown")

    def _get_required_oses(self, script_config: Dict[str, Any]) -> List[str]:
        """Read optional script OS constraints from config, normalized."""
        raw = script_config.get("os")
        if raw is None:
            raw = script_config.get("platforms")
        if raw is None:
            return []
        if isinstance(raw, str):
            normalized = self._normalize_os_name(raw)
            return [normalized] if normalized else []
        if isinstance(raw, (list, tuple)):
            values: List[str] = []
            for entry in raw:
                normalized = self._normalize_os_name(entry)
                if normalized:
                    values.append(normalized)
            # Preserve order while removing duplicates
            unique: List[str] = []
            seen = set()
            for item in values:
                if item in seen:
                    continue
                seen.add(item)
                unique.append(item)
            return unique
        return []
    
    def _execute_testcase(self, context: CampaignExecutionContext, campaign_config: Dict[str, Any],
                         script_config: Dict[str, Any], execution_order: int,
                         resolved_parameters: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute a testcase within the campaign via HTTP to the local host.

        Calls POST {HOST_API_URL}/host/testcase/{testcase_id}/execute directly
        on localhost, avoiding the server roundtrip that caused 504 deadlocks
        (server 30s timeout too short for testcase execution).

        Args:
            context: Campaign execution context
            campaign_config: Overall campaign configuration
            script_config: Testcase script configuration
            execution_order: Execution order number
            resolved_parameters: Resolved input parameters

        Returns:
            Dict with execution result including script_outputs
        """
        import requests as _requests
        import json as _json

        script_start_time = time.time()
        testcase_id = script_config.get("testcase_id")
        script_name = script_config.get("script_name", f"testcase_{testcase_id}")

        print(f"🎯 [Campaign] Executing TestCase locally: {script_name}")
        print(f"📥 [Campaign] Resolved Inputs: {resolved_parameters}")

        try:
            device_id = campaign_config.get("device_id") or campaign_config.get("device", "device1")

            # Execute locally on this host (no server roundtrip)
            host_api_url = os.environ.get("HOST_API_URL", f"http://localhost:6109")
            api_url = f"{host_api_url}/host/testcase/{testcase_id}/execute"

            print(f"🌐 [Campaign] POST {api_url} (testcase={script_name}, host={context.host.host_name}, device={device_id})")

            payload = {
                "device_id": device_id,
                "host_name": context.host.host_name,
                "userinterface_name": campaign_config.get("userinterface_name", ""),
                # Per-row input values for the testcase's scriptConfig inputs —
                # how one testcase template runs N times with different params.
                "parameters": resolved_parameters or {}
            }
            params = {"team_id": context.team_id}

            # Include API key for local host authentication
            api_key = os.environ.get("API_KEY", "")
            headers = {}
            if api_key:
                headers["X-API-Key"] = api_key

            response = _requests.post(
                api_url,
                json=payload,
                params=params,
                headers=headers,
                timeout=300
            )

            execution_time_ms = int((time.time() - script_start_time) * 1000)

            if response.status_code != 200:
                error_msg = f"API HTTP error {response.status_code}: {response.text[:300]}"
                print(f"❌ [Campaign] {error_msg}")
                return {
                    "script_name": script_name, "script_type": "testcase",
                    "testcase_id": testcase_id, "execution_order": execution_order,
                    "success": False, "execution_time_ms": execution_time_ms,
                    "error": error_msg, "script_outputs": {}
                }

            exec_result = response.json()
            success = exec_result.get("success", False)
            script_outputs = exec_result.get("script_outputs", {})

            print(f"📤 [Campaign] TestCase result: success={success}, outputs={script_outputs}")

            return {
                "script_name": script_name,
                "script_type": "testcase",
                "testcase_id": testcase_id,
                "execution_order": execution_order,
                "success": success,
                "execution_time_ms": execution_time_ms,
                "error": exec_result.get("error"),
                "report_url": exec_result.get("report_url"),
                "logs_url": exec_result.get("logs_url"),
                "script_outputs": script_outputs,
                "result_type": exec_result.get("result_type")
            }

        except _requests.exceptions.Timeout:
            execution_time_ms = int((time.time() - script_start_time) * 1000)
            error_msg = f"Testcase API timeout after 120s: {script_name}"
            print(f"💥 [Campaign] {error_msg}")
            return {
                "script_name": script_name, "script_type": "testcase",
                "testcase_id": testcase_id, "execution_order": execution_order,
                "success": False, "execution_time_ms": execution_time_ms,
                "error": error_msg, "script_outputs": {}
            }
        except Exception as e:
            execution_time_ms = int((time.time() - script_start_time) * 1000)
            error_msg = f"TestCase execution error: {str(e)}"
            print(f"💥 [Campaign] {error_msg}")
            import traceback
            traceback.print_exc()
            return {
                "script_name": script_name, "script_type": "testcase",
                "testcase_id": testcase_id, "execution_order": execution_order,
                "success": False, "execution_time_ms": execution_time_ms,
                "error": error_msg, "script_outputs": {}
            }

    def _build_success_result(self, context: CampaignExecutionContext) -> Dict[str, Any]:
        """Build successful campaign result"""
        return {
            "success": True,
            "campaign_id": context.campaign_id,
            "campaign_execution_id": context.campaign_execution_id,
            "campaign_result_id": context.campaign_result_id,
            "total_scripts": context.total_scripts,
            "completed_scripts": context.completed_scripts,
            "successful_scripts": context.successful_scripts,
            "failed_scripts": context.failed_scripts,
            "skipped_scripts": context.skipped_scripts,
            "execution_time_ms": context.get_execution_time_ms(),
            "script_executions": context.script_executions,
            "overall_success": context.overall_success,
            "orchestrator_report_url": context.orchestrator_report_url,
            "orchestrator_logs_url": context.orchestrator_logs_url,
        }

    def _build_campaign_identity_metadata(self, context: CampaignExecutionContext) -> Dict[str, Any]:
        """Extract campaign identity metadata to persist under metadata.campaign_identity."""
        identity = getattr(context, 'campaign_identity', None)
        if not isinstance(identity, dict):
            return {}

        payload = {}

        campaign_ref = identity.get('campaign_ref')
        if campaign_ref:
            payload['campaign_ref'] = campaign_ref

        prefix = identity.get('prefix')
        if prefix:
            payload['prefix'] = prefix

        display_name = identity.get('display_name')
        if display_name:
            payload['display_name'] = display_name

        return payload

    def _build_start_metadata(self, context: CampaignExecutionContext, campaign_config: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        """Build metadata payload for record_campaign_execution_start."""
        identity_payload = self._build_campaign_identity_metadata(context)
        metadata: Dict[str, Any] = {}
        if identity_payload:
            metadata['campaign_identity'] = identity_payload

        deployment_execution_id = (campaign_config or {}).get('deployment_execution_id')
        if deployment_execution_id:
            metadata['deployment_execution_id'] = deployment_execution_id
            context.metadata['deployment_execution_id'] = deployment_execution_id

        selected_version = (campaign_config or {}).get('version_number')
        if selected_version is not None:
            metadata['campaign_version'] = selected_version

        return metadata or None

    def _merge_final_metadata(self, context: CampaignExecutionContext) -> Optional[Dict[str, Any]]:
        """
        Merge runtime metadata with system metadata.

        Some flows may assign context.metadata directly; this ensures campaign_identity
        is always persisted.
        """
        merged: Dict[str, Any] = {}
        runtime_metadata = getattr(context, 'metadata', None)

        if isinstance(runtime_metadata, dict):
            merged.update(runtime_metadata)
        elif runtime_metadata not in (None, ''):
            merged['campaign_metadata_raw'] = runtime_metadata

        identity_payload = self._build_campaign_identity_metadata(context)
        if identity_payload:
            existing_identity = merged.get('campaign_identity')
            if isinstance(existing_identity, dict):
                existing_identity.update(identity_payload)
                merged['campaign_identity'] = existing_identity
            else:
                merged['campaign_identity'] = identity_payload

        merged = {k: v for k, v in merged.items() if v is not None}
        return merged or None
    
    def _build_failure_result(self, context: CampaignExecutionContext, error_message: str) -> Dict[str, Any]:
        """Build failed campaign result"""
        return {
            "success": False,
            "campaign_id": context.campaign_id,
            "campaign_execution_id": context.campaign_execution_id,
            "campaign_result_id": context.campaign_result_id,
            "error": error_message,
            "total_scripts": context.total_scripts,
            "completed_scripts": context.completed_scripts,
            "successful_scripts": context.successful_scripts,
            "failed_scripts": context.failed_scripts,
            "skipped_scripts": context.skipped_scripts,
            "execution_time_ms": context.get_execution_time_ms(),
            "script_executions": context.script_executions,
            "overall_success": False,
            "orchestrator_report_url": context.orchestrator_report_url,
            "orchestrator_logs_url": context.orchestrator_logs_url,
        }

    def _resolve_orchestrator_device_model(self, campaign_config: Dict[str, Any]) -> str:
        """Best-effort device model for artifact path grouping."""
        device_id = campaign_config.get("device_id") or campaign_config.get("device") or "host"
        try:
            from backend_host.src.lib.utils.host_utils import get_device_by_id
            device = get_device_by_id(device_id)
            if device and getattr(device, "device_model", None):
                return str(device.device_model)
        except Exception:
            pass
        return str(device_id or "host")

    def _build_orchestrator_log_content(self, context: CampaignExecutionContext) -> str:
        """Build plain-text orchestrator log listing each executed script and artifacts."""
        lines = [
            f"Campaign: {context.campaign_name}",
            f"Campaign ID: {context.campaign_id}",
            f"Execution ID: {context.campaign_execution_id}",
            f"Started: {datetime.fromtimestamp(context.start_time).isoformat()}",
            f"Duration ms: {context.get_execution_time_ms()}",
            f"Summary: total={context.total_scripts}, completed={context.completed_scripts}, success={context.successful_scripts}, failed={context.failed_scripts}, skipped={context.skipped_scripts}",
            "",
            "Scripts:",
        ]
        for idx, script in enumerate(context.script_executions, start=1):
            lines.extend([
                f"{idx}. name={script.get('script_name')}, type={script.get('script_type')}, success={script.get('success')}, skipped={script.get('skipped', False)}, execution_time_ms={script.get('execution_time_ms')}",
                f"   report_url={script.get('report_url') or ''}",
                f"   logs_url={script.get('logs_url') or ''}",
                f"   error={script.get('error') or ''}",
            ])
        return "\n".join(lines).strip() + "\n"

    def _build_orchestrator_report_html(self, context: CampaignExecutionContext) -> str:
        """Build themed HTML report for campaign orchestrator output."""
        return generate_campaign_orchestrator_report({
            "campaign_name": context.campaign_name,
            "campaign_id": context.campaign_id,
            "campaign_execution_id": context.campaign_execution_id,
            "started_at": datetime.fromtimestamp(context.start_time).strftime("%Y%m%d%H%M%S"),
            "ended_at": datetime.utcnow().strftime("%Y%m%d%H%M%S"),
            "execution_time": context.get_execution_time_ms(),
            "success": context.overall_success,
            "total_scripts": context.total_scripts,
            "completed_scripts": context.completed_scripts,
            "successful_scripts": context.successful_scripts,
            "failed_scripts": context.failed_scripts,
            "skipped_scripts": context.skipped_scripts,
            "device_name": "Campaign Device",
            "device_model": "unknown",
            "host_name": getattr(context.host, "host_name", "Unknown Host"),
            "script_executions": context.script_executions,
            "logs_url": context.orchestrator_logs_url or "",
            "error_msg": context.error_message or "",
        })

    def _generate_orchestrator_artifacts(self, context: CampaignExecutionContext, campaign_config: Dict[str, Any]) -> Dict[str, Any]:
        """Upload orchestrator logs/report to MinIO and return URLs."""
        try:
            timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
            device_model = self._resolve_orchestrator_device_model(campaign_config)
            artifact_name = f"campaign_orchestrator_{context.campaign_id}"
            artifact_id = context.campaign_result_id

            log_content = self._build_orchestrator_log_content(context)
            html_content = self._build_orchestrator_report_html(context)

            logs_upload = upload_script_logs(
                log_content=log_content,
                device_model=device_model,
                script_name=artifact_name,
                timestamp=timestamp,
                script_result_id=artifact_id,
            )
            report_upload = upload_script_report(
                html_content=html_content,
                device_model=device_model,
                script_name=artifact_name,
                timestamp=timestamp,
                script_result_id=artifact_id,
            )

            return {
                "device_model": device_model,
                "logs_url": logs_upload.get("url") if logs_upload.get("success") else None,
                "logs_path": logs_upload.get("path") if logs_upload.get("success") else None,
                "report_url": report_upload.get("report_url") if report_upload.get("success") else None,
                "report_path": report_upload.get("report_path") if report_upload.get("success") else None,
            }
        except Exception as e:
            print(f"[@Campaign] Failed to generate orchestrator artifacts: {e}")
            return {}


def handle_keyboard_interrupt(campaign_name: str):
    """Handle Ctrl+C gracefully during campaign execution"""
    print(f"\n⚠️ [Campaign:{campaign_name}] Keyboard interrupt received (Ctrl+C)")
    print(f"🛑 [Campaign:{campaign_name}] Campaign execution interrupted by user")
    sys.exit(130)  # Standard exit code for Ctrl+C


def handle_unexpected_error(campaign_name: str, error: Exception):
    """Handle unexpected errors during campaign execution"""
    print(f"\n💥 [Campaign:{campaign_name}] Unexpected error occurred:")
    print(f"❌ [Campaign:{campaign_name}] Error: {str(error)}")
    print(f"📋 [Campaign:{campaign_name}] Campaign execution failed")
    sys.exit(1)
