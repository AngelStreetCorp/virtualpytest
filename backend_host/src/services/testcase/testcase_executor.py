"""
TestCase Executor

Executes visual test cases created in TestCase Builder.
Integrates with existing executors and ScriptExecutionContext.
Supports async execution with real-time progress tracking.
"""

import re
import time
import threading
import uuid
import sys
import io
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional
from shared.src.lib.executors.script_executor import ScriptExecutionContext
from shared.src.lib.utils.script_identity_utils import resolve_script_identity
from shared.src.lib.database.testcase_db import get_testcase_by_name, get_testcase
from shared.src.lib.database.script_results_db import record_script_execution_start
from backend_host.src.lib.utils.execution_event_utils import emit_execution_event
from .testcase_validator import TestCaseValidator


class TestCaseExecutor:
    """
    Executes test case graphs by traversing nodes and delegating to existing executors.
    Supports async execution with real-time progress tracking.
    """
    
    def __init__(self):
        self.validator = TestCaseValidator()
        self.context = None
        self.device = None
        self.current_block_id = None
        
        # Async execution tracking
        self._executions: Dict[str, Dict[str, Any]] = {}  # execution_id -> execution state
        self._lock = threading.Lock()

    def _create_start_metadata(
        self,
        *,
        device_id: str,
        device_model: str,
        testcase_id: Optional[str] = None,
        execution_id: Optional[str] = None,
        unsaved: bool = False,
        execution_metadata: Optional[Dict[str, Any]] = None,
        testcase_name: Optional[str] = None,
        team_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Build the persisted start metadata for testcase executions."""
        metadata: Dict[str, Any] = {
            'device_id': device_id,
            'device_model': device_model,
            'unsaved': unsaved,
        }

        # Testcases never go through /server/script/execute, so no identity is
        # forwarded to them — resolve it here or the TCnnn prefix and display name
        # are missing from every testcase report. Same metadata.script_identity
        # shape the script path writes (_build_script_identity_metadata).
        if testcase_name:
            identity = resolve_script_identity(testcase_name, team_id=team_id) or {}
            identity_payload = {k: v for k, v in identity.items() if v}
            if identity_payload:
                metadata['script_identity'] = identity_payload
        if testcase_id:
            metadata['testcase_id'] = str(testcase_id)
        if execution_id:
            metadata['execution_id'] = execution_id
        if isinstance(execution_metadata, dict):
            metadata.update(execution_metadata)

        try:
            from shared.src.lib.executors.script_executor import _normalize_trigger
            raw_trigger = metadata.get('trigger') if isinstance(metadata.get('trigger'), dict) else None
            metadata['trigger'] = _normalize_trigger(raw_trigger)
        except Exception:
            pass

        return metadata

    def _print_execution_banner(self, context: 'ScriptExecutionContext', testcase_name: str) -> None:
        """Print VERSION + TRIGGER banner at the top of the captured testcase logs.

        Must be called AFTER `context.start_stdout_capture()` so the banner lands in the
        uploaded execution.txt alongside the rest of the testcase stdout.
        """
        try:
            import os as _os
            from shared.src.lib.executors.script_executor import _normalize_trigger
            utils_dir = _os.path.dirname(_os.path.abspath(__file__))
            project_root = _os.path.abspath(_os.path.join(utils_dir, '..', '..', '..', '..', '..'))
            version_path = _os.path.join(project_root, 'VERSION.txt')
            if _os.path.exists(version_path):
                with open(version_path, 'r', encoding='utf-8') as vf:
                    version_line = next((ln.strip() for ln in vf if ln.strip()), '')
                if version_line:
                    print(f"[@testcase_executor] VERSION: {version_line}")

            raw_trigger = None
            if isinstance(getattr(context, 'initial_metadata', None), dict):
                raw_trigger = context.initial_metadata.get('trigger')
            trigger = _normalize_trigger(raw_trigger if isinstance(raw_trigger, dict) else None)
            try:
                context.trigger = trigger
            except Exception:
                pass
            parts = [f"type={trigger.get('type') or 'host'}"]
            if trigger.get('caller_user'):
                parts.append(f"user={trigger['caller_user']}")
            if trigger.get('caller_ip'):
                parts.append(f"ip={trigger['caller_ip']}")
            print(f"[@testcase_executor] TRIGGER: {' | '.join(parts)}")
            print(f"[@testcase_executor] TESTCASE: {testcase_name}")
        except Exception as banner_error:
            print(f"[@testcase_executor] Banner unavailable ({banner_error})")

    def _set_running_log_path(self, context: ScriptExecutionContext, device_id: str):
        """Enable running log output for testcase executions when capture storage is configured."""
        from shared.src.lib.utils.storage_path_utils import get_capture_folder_from_device_id
        try:
            capture_folder = get_capture_folder_from_device_id(device_id)
            context.set_running_log_path(capture_folder)
            print(f"📝 [@testcase_executor] Running log enabled: {context.running_log_path}")
        except ValueError as e:
            print(f"⚠️ [@testcase_executor] Could not set running log: {e}")

    def _capture_step_screenshot(
        self,
        context: ScriptExecutionContext,
        step_number: int,
        phase: str,
        node_type: str,
    ) -> str:
        """Capture a step screenshot and return the stored path for report rendering."""
        if not context.selected_device:
            return ''

        try:
            from shared.src.lib.utils.device_utils import capture_screenshot_for_script
            screenshot_id = f"testcase_step_{step_number}_{node_type}_{phase}"
            captured = capture_screenshot_for_script(context.selected_device, context, screenshot_id)
            if captured and context.screenshot_paths:
                return context.screenshot_paths[-1]
        except Exception as e:
            print(f"⚠️ [@testcase_executor] Step screenshot capture failed ({phase}): {e}")
        return ''

    def _build_step_actions(self, node_type: str, data: Dict[str, Any], block_result: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Build report-friendly action definitions for a testcase block."""
        if node_type == 'action':
            # Container: a sequence of actions (data['actions'] only — no legacy
            # single-command shape).
            return [
                {'command': a.get('command', 'unknown'), 'params': a.get('params', {}) or {}}
                for a in (data.get('actions') or [])
            ]

        if node_type == 'verification':
            return []

        if node_type == 'navigation':
            target = data.get('target_node_label') or data.get('target_node') or data.get('target_node_id') or 'unknown'
            return [{'command': 'navigate_to_node', 'params': {'target': target}}]

        command = data.get('command')
        if command:
            return [{'command': command, 'params': data.get('params', {}) or {}}]

        if node_type == 'loop':
            return [{'command': 'loop', 'params': {'iterations': data.get('iterations', 1)}}]

        result_message = block_result.get('message')
        return [{'command': node_type, 'params': {'message': result_message}}] if result_message else []

    def _build_step_verifications(self, node_type: str, data: Dict[str, Any], block_result: Dict[str, Any]) -> (List[Dict[str, Any]], List[Dict[str, Any]]):
        """Build report-friendly verification definitions/results for a testcase block."""
        if node_type != 'verification':
            return [], []

        result_success = block_result.get('success', False)
        result_message = block_result.get('message') or 'Verification'

        # Container: a set of verifications (data['verifications'] only). The
        # verification executor returns per-leg rows 1:1 with the input
        # (attached by _execute_verification_block as 'verification_results') —
        # use each leg's own success/message; fall back to aggregate stamping
        # when per-leg rows are unavailable (e.g. executor-level error).
        items = data.get('verifications') or []
        per_leg = block_result.get('verification_results')
        has_per_leg = isinstance(per_leg, list) and len(per_leg) == len(items)

        defs: List[Dict[str, Any]] = []
        results: List[Dict[str, Any]] = []
        for i, it in enumerate(items):
            command = it.get('command', 'unknown')
            defs.append({
                'command': command,
                'params': it.get('params', {}) or {},
                'label': it.get('label') or it.get('name') or command,
            })
            if has_per_leg:
                leg = per_leg[i] or {}
                vr = {
                    'success': leg.get('success', False),
                    'verification_type': leg.get('verification_type') or it.get('verification_type') or command,
                    'message': leg.get('message') or result_message,
                }
                if leg.get('error'):
                    vr['error'] = leg.get('error')
            else:
                vr = {
                    'success': result_success,
                    'verification_type': it.get('verification_type') or command,
                    'message': result_message,
                }
                if block_result.get('error'):
                    vr['error'] = block_result.get('error')
            results.append(vr)
        return defs, results

    def _resolve_step_nodes(self, node_type: str, data: Dict[str, Any]) -> (str, str):
        """Resolve from/to node labels for report rendering."""
        nav_context = getattr(self.device, 'navigation_context', {}) if self.device else {}
        current_label = nav_context.get('current_node_label') or nav_context.get('previous_node_label') or 'current'

        if node_type == 'navigation':
            target = data.get('target_node_label') or data.get('target_node') or data.get('target_node_id') or 'target'
            return current_label, target

        block_label = data.get('label') or data.get('name') or data.get('command') or node_type
        return current_label, block_label

    def _record_block_step(
        self,
        *,
        context: ScriptExecutionContext,
        node: Dict[str, Any],
        block_result: Dict[str, Any],
        block_start_iso: str,
        block_end_iso: str,
        block_duration_ms: int,
        step_start_screenshot_path: str,
        step_end_screenshot_path: str,
    ) -> int:
        """Normalize one testcase block into the shared report step schema."""
        node_type = node['type']
        data = node.get('data', {})
        from_node, to_node = self._resolve_step_nodes(node_type, data)
        actions = self._build_step_actions(node_type, data, block_result)
        verifications, verification_results = self._build_step_verifications(node_type, data, block_result)

        # Steps executed inside a loop iteration are tagged "[k/N]" so the
        # repeated runs are distinguishable in the report (set by _execute_loop_block).
        message = block_result.get('message', '')
        iteration_label = getattr(context, 'loop_iteration_label', None)
        if iteration_label:
            message = f"[{iteration_label}] {message}" if message else f"[{iteration_label}]"

        step_payload = {
            'block_id': node.get('id'),
            'block_type': node_type,
            'success': block_result['success'],
            'execution_time_ms': block_result.get('execution_time_ms', block_duration_ms),
            'message': message,
            'error': block_result.get('error'),
            'logs': block_result.get('logs', ''),
            'step_category': 'testcase_block',
            'start_time': block_start_iso,
            'end_time': block_end_iso,
            'from_node': from_node,
            'to_node': to_node,
            'actions': actions,
            'retry_actions': data.get('retry_actions', []),
            'failure_actions': data.get('failure_actions', []),
            'verifications': verifications,
            'verification_results': verification_results,
            'screenshot_path': step_end_screenshot_path or step_start_screenshot_path,
            'step_start_screenshot_path': step_start_screenshot_path,
            'step_end_screenshot_path': step_end_screenshot_path,
        }
        return context.record_step_immediately(step_payload)

    def _build_execution_summary(
        self,
        context: ScriptExecutionContext,
        testcase_name: str,
        execution_result: Dict[str, Any],
    ) -> str:
        """Build a console-style summary for the shared report overview section."""
        result_type = execution_result.get('result_type', 'error').upper()
        lines = [
            f"TESTCASE SUMMARY: {testcase_name}",
            f"Result: {result_type}",
            f"Success: {context.overall_success}",
            f"Steps Executed: {len(context.step_results)}",
            f"Screenshots Captured: {len(context.screenshot_paths)}",
            f"Script Result ID: {context.script_result_id or 'n/a'}",
        ]
        if context.host:
            lines.append(f"Host: {context.host.host_name}")
        if context.selected_device:
            lines.append(f"Device: {context.selected_device.device_name} ({context.selected_device.device_model})")
        if context.error_message:
            lines.append(f"Error: {context.error_message}")
        return "\n".join(lines)
    
    def execute_testcase_from_graph(
        self,
        graph: Dict[str, Any],
        team_id: str,
        host_name: str,
        device_id: str,
        device_name: str,
        device_model: str,
        userinterface_name: str = '',
        testcase_name: str = 'unsaved_testcase',  # 🆕 NEW: Accept testcase_name parameter
        execution_metadata: Optional[Dict[str, Any]] = None,
        generate_report: bool = True,
    ) -> Dict[str, Any]:
        """
        Execute a test case directly from graph JSON (no save required).
        
        Args:
            graph: Graph JSON definition
            team_id: Team ID
            host_name: Host name
            device_id: Device ID
            device_name: Device name
            device_model: Device model
            userinterface_name: Userinterface name (optional)
            testcase_name: Test case name for tracking (optional, defaults to 'unsaved_testcase')
        
        Returns:
            Execution result with success, report_url, etc.
        """
        start_time = time.time()
        context = None
        
        try:
            # Validate graph structure
            print(f"[@testcase_executor] Validating graph...")
            is_valid, errors, warnings = self.validator.validate_graph(
                graph,
                userinterface_name=userinterface_name,
                team_id=team_id
            )
            
            if not is_valid:
                error_msg = '; '.join(errors)
                print(f"[@testcase_executor] Validation failed: {error_msg}")
                return {
                    'success': False,
                    'error': f'Invalid graph: {error_msg}',
                    'validation_errors': errors,
                    'validation_warnings': warnings,
                    'execution_time_ms': 0
                }
            
            if warnings:
                print(f"[@testcase_executor] Validation warnings: {'; '.join(warnings)}")
            
            # Record execution start in script_results
            start_metadata = self._create_start_metadata(
                device_id=device_id,
                device_model=device_model,
                unsaved=testcase_name == 'unsaved_testcase',
                execution_metadata=execution_metadata,
                testcase_name=testcase_name,
                team_id=team_id,
            )
            if generate_report:
                script_result_id = record_script_execution_start(
                    team_id=team_id,
                    script_name=testcase_name,  # 🆕 FIXED: Use provided testcase_name
                    script_type='testcase',
                    userinterface_name=userinterface_name,
                    host_name=host_name,
                    device_name=device_name,
                    metadata=start_metadata
                )
            else:
                script_result_id = None

            print(f"[@testcase_executor] Script result ID: {script_result_id}")
            
            # Create execution context
            context = ScriptExecutionContext(testcase_name)  # 🆕 FIXED: Use provided testcase_name
            context.script_result_id = script_result_id
            context.team_id = team_id
            context.userinterface_name = userinterface_name
            context.initial_metadata = start_metadata.copy()
            # Testcases never go through /server/script/execute, so they receive no
            # forwarded identity — resolve it here or the TCnnn prefix is missing
            # from every testcase report.
            context.script_identity = resolve_script_identity(testcase_name, team_id=team_id)
            
            # Start stdout capture for logs
            context.start_stdout_capture()
            self._print_execution_banner(context, testcase_name)
            
            # Get device from controller manager
            from backend_host.src.controllers.controller_manager import get_host
            host = get_host(device_ids=[device_id])
            
            device = next((d for d in host.get_devices() if d.device_id == device_id), None)
            if not device:
                raise ValueError(f"Device not found: {device_id}")
            
            context.selected_device = device
            context.host = host
            self._set_running_log_path(context, device_id)
            
            # Populate device navigation_context for executor tracking
            nav_context = device.navigation_context
            nav_context['script_id'] = script_result_id
            nav_context['script_name'] = testcase_name  # 🆕 FIXED: Use provided testcase_name
            nav_context['script_context'] = 'testcase'
            nav_context['current_node_id'] = None
            nav_context['current_node_label'] = None

            from shared.src.lib.utils.device_utils import capture_screenshot
            print(f"📸 [@testcase_executor] Capturing initial state screenshot...")
            capture_screenshot(context.selected_device, context, "[@testcase_executor]")
            
            # Initialize scriptConfig inputs and variables in context
            self._initialize_script_inputs_and_variables(graph, context)
            
            # Execute the graph
            print(f"[@testcase_executor] Executing test case from graph...")
            self.context = context
            self.device = device
            
            import asyncio
            execution_result = asyncio.run(self._execute_graph(graph, context))
            
            # Calculate execution time
            execution_time_ms = int((time.time() - start_time) * 1000)
            
            # Determine result type for logging
            result_type = execution_result.get('result_type', 'error')
            if result_type == 'success':
                print(f"[@testcase_executor] Execution completed: SUCCESS (reached SUCCESS block)")
            elif result_type == 'failure':
                print(f"[@testcase_executor] Execution completed: FAILURE (reached FAILURE block)")
            else:
                print(f"[@testcase_executor] Execution completed: ERROR - {execution_result.get('error')}")
            
            # Use ScriptExecutor's cleanup to generate report (same as @script decorator does)
            print(f"[@testcase_executor] Generating execution report using ScriptExecutor cleanup...")
            report_url = ""
            logs_url = ""
            try:
                from shared.src.lib.executors.script_executor import ScriptExecutor
                executor = ScriptExecutor(testcase_name)
                executor.current_trigger = getattr(context, 'trigger', None) or {}
                
                # Set overall_success in context before cleanup
                context.overall_success = execution_result['success']
                context.error_message = execution_result.get('error', '') or ''
                context.execution_summary = self._build_execution_summary(context, testcase_name, execution_result)

                finalization = executor.finalize_execution_context(
                    context,
                    userinterface_name,
                    success=execution_result['success'],
                    error_message=execution_result.get('error'),
                    generate_report=generate_report,
                )
                report_url = finalization.get('report_url', '')
                logs_url = finalization.get('logs_url', '')
            except Exception as e:
                print(f"[@testcase_executor] Error generating report: {e}")
                import traceback
                traceback.print_exc()
            
            return {
                'success': execution_result['success'],
                'result_type': result_type,
                'execution_time_ms': execution_time_ms,
                'step_count': len(context.step_results),
                'error': execution_result.get('error'),
                'script_result_id': script_result_id,
                'step_results': context.step_results,
                'report_url': report_url,
                'logs_url': logs_url,
                'script_outputs': getattr(context, 'script_outputs', {})  # NEW: For campaign chaining
            }
            
        except Exception as e:
            execution_time_ms = int((time.time() - start_time) * 1000)
            error_msg = f"Execution error: {str(e)}"
            print(f"[@testcase_executor] ERROR: {error_msg}")
            
            import traceback
            traceback.print_exc()

            if context is not None:
                try:
                    from shared.src.lib.executors.script_executor import ScriptExecutor
                    executor = ScriptExecutor(testcase_name)
                    executor.current_trigger = getattr(context, 'trigger', None) or {}
                    context.error_message = error_msg
                    context.execution_summary = self._build_execution_summary(
                        context,
                        testcase_name,
                        {'success': False, 'result_type': 'error', 'error': error_msg},
                    )
                    executor.finalize_execution_context(
                        context,
                        userinterface_name,
                        success=False,
                        error_message=error_msg,
                        generate_report=generate_report,
                    )
                except Exception as finalize_error:
                    print(f"[@testcase_executor] Failed to finalize errored execution: {finalize_error}")

            return {
                'success': False,
                'error': error_msg,
                'execution_time_ms': execution_time_ms
            }

    def execute_testcase(
        self,
        testcase_name: str,
        team_id: str,
        host_name: str,
        device_id: str,
        device_name: str,
        device_model: str,
        parameters: Optional[Dict[str, Any]] = None,
        userinterface_name: str = '',
    ) -> Dict[str, Any]:
        """
        Execute a test case by name.

        Args:
            testcase_name: Name of the test case to execute
            team_id: Team ID
            host_name: Host name
            device_id: Device ID
            device_name: Device name
            device_model: Device model
            parameters: Run-time values for the testcase's scriptConfig inputs
                        (e.g. per-row campaign parameters). Stamped as
                        inputs[].value on the loaded graph so {name} placeholders
                        resolve per run.
            userinterface_name: Override UI name (e.g. from campaign). Falls back to testcase's stored UI.

        Returns:
            Execution result with success, report_url, etc.
        """
        start_time = time.time()
        context = None

        try:
            # Load test case definition from database
            print(f"[@testcase_executor] Loading test case: {testcase_name}")
            testcase = get_testcase_by_name(testcase_name, team_id)

            if not testcase:
                return {
                    'success': False,
                    'error': f'Test case not found: {testcase_name}',
                    'execution_time_ms': 0
                }

            graph = testcase['graph_json']
            # Campaign/caller-provided UI overrides the testcase's stored UI
            if not userinterface_name:
                userinterface_name = testcase.get('userinterface_name', '')

            # Stamp run-time parameter values onto the declared inputs (the saved
            # graph is a template; values are per run). Names that don't match a
            # declared input are skipped — campaign params can carry script-level
            # extras (host, device, …) that aren't testcase inputs.
            if parameters:
                declared_inputs = (graph.get('scriptConfig') or {}).get('inputs', []) or []
                declared_names = {i.get('name') for i in declared_inputs}
                for input_def in declared_inputs:
                    name = input_def.get('name')
                    # Empty string means "use the testcase's own default" — don't
                    # let it shadow the default with ''.
                    if name in parameters and parameters[name] not in (None, ''):
                        input_def['value'] = parameters[name]
                        print(f"[@testcase_executor] Stamped input '{name}' = {parameters[name]}")
                for name in parameters:
                    if name not in declared_names:
                        print(f"[@testcase_executor] Skipping parameter '{name}' — not a declared input")
            
            # Validate graph structure
            print(f"[@testcase_executor] Validating graph...")
            is_valid, errors, warnings = self.validator.validate_graph(
                graph,
                userinterface_name=userinterface_name,
                team_id=team_id
            )
            
            if not is_valid:
                error_msg = '; '.join(errors)
                print(f"[@testcase_executor] Validation failed: {error_msg}")
                return {
                    'success': False,
                    'error': f'Invalid graph: {error_msg}',
                    'validation_errors': errors,
                    'validation_warnings': warnings,
                    'execution_time_ms': 0
                }
            
            if warnings:
                print(f"[@testcase_executor] Validation warnings: {'; '.join(warnings)}")
            
            # Record execution start in script_results
            start_metadata = self._create_start_metadata(
                device_id=device_id,
                device_model=device_model,
                testcase_id=str(testcase['testcase_id']),
                unsaved=False,
                testcase_name=testcase_name,
                team_id=team_id,
            )
            script_result_id = record_script_execution_start(
                team_id=team_id,
                script_name=testcase_name,
                script_type='testcase',  # Mark as test case execution
                userinterface_name=userinterface_name,
                host_name=host_name,
                device_name=device_name,
                metadata=start_metadata
            )
            
            print(f"[@testcase_executor] Script result ID: {script_result_id}")
            
            # Create execution context
            context = ScriptExecutionContext(testcase_name)
            context.script_result_id = script_result_id
            context.team_id = team_id
            context.userinterface_name = userinterface_name
            context.initial_metadata = start_metadata.copy()
            # Testcases never go through /server/script/execute, so they receive no
            # forwarded identity — resolve it here or the TCnnn prefix is missing
            # from every testcase report.
            context.script_identity = resolve_script_identity(testcase_name, team_id=team_id)
            
            # Start stdout capture for logs (parity with scripts/async testcase path)
            context.start_stdout_capture()
            self._print_execution_banner(context, testcase_name)
            
            # Get device from controller manager
            from backend_host.src.controllers.controller_manager import get_host
            host = get_host(device_ids=[device_id])
            
            device = next((d for d in host.get_devices() if d.device_id == device_id), None)
            if not device:
                raise ValueError(f"Device not found: {device_id}")
            
            context.selected_device = device
            context.host = host
            self._set_running_log_path(context, device_id)
            
            # Populate device navigation_context for executor tracking
            nav_context = device.navigation_context
            nav_context['script_id'] = script_result_id
            nav_context['script_name'] = testcase_name
            nav_context['script_context'] = 'testcase'

            from shared.src.lib.utils.device_utils import capture_screenshot
            print(f"📸 [@testcase_executor] Capturing initial state screenshot...")
            capture_screenshot(context.selected_device, context, "[@testcase_executor]")
            
            # Execute the graph
            print(f"[@testcase_executor] Executing test case...")
            self.context = context
            self.device = device
            
            import asyncio
            execution_result = asyncio.run(self._execute_graph(graph, context))
            
            # Calculate execution time
            execution_time_ms = int((time.time() - start_time) * 1000)
            
            # Determine result type for logging
            result_type = execution_result.get('result_type', 'error')
            if result_type == 'success':
                print(f"[@testcase_executor] Execution completed: SUCCESS (reached SUCCESS block)")
            elif result_type == 'failure':
                print(f"[@testcase_executor] Execution completed: FAILURE (reached FAILURE block)")
            else:
                print(f"[@testcase_executor] Execution completed: ERROR - {execution_result.get('error')}")
            
            # Use ScriptExecutor's cleanup to generate report (same as @script decorator does)
            print(f"[@testcase_executor] Generating execution report using ScriptExecutor cleanup...")
            report_url = ""
            logs_url = ""
            try:
                from shared.src.lib.executors.script_executor import ScriptExecutor
                executor = ScriptExecutor(testcase_name)
                executor.current_trigger = getattr(context, 'trigger', None) or {}
                
                # Set overall_success in context before cleanup
                context.overall_success = execution_result['success']
                context.error_message = execution_result.get('error', '') or ''
                context.execution_summary = self._build_execution_summary(context, testcase_name, execution_result)

                finalization = executor.finalize_execution_context(
                    context,
                    userinterface_name,
                    success=execution_result['success'],
                    error_message=execution_result.get('error'),
                )
                report_url = finalization.get('report_url', '')
                logs_url = finalization.get('logs_url', '')
            except Exception as e:
                print(f"[@testcase_executor] Error generating report: {e}")
                import traceback
                traceback.print_exc()
            
            return {
                'success': execution_result['success'],
                'result_type': result_type,
                'execution_time_ms': execution_time_ms,
                'step_count': len(context.step_results),
                'error': execution_result.get('error'),
                'script_result_id': script_result_id,
                'step_results': context.step_results,
                'report_url': report_url,
                'logs_url': logs_url,
                'script_outputs': getattr(context, 'script_outputs', {})  # NEW: For campaign chaining
            }
            
        except Exception as e:
            execution_time_ms = int((time.time() - start_time) * 1000)
            error_msg = f"Execution error: {str(e)}"
            print(f"[@testcase_executor] ERROR: {error_msg}")
            
            import traceback
            traceback.print_exc()

            if context is not None:
                try:
                    from shared.src.lib.executors.script_executor import ScriptExecutor
                    executor = ScriptExecutor(testcase_name)
                    executor.current_trigger = getattr(context, 'trigger', None) or {}
                    context.error_message = error_msg
                    context.execution_summary = self._build_execution_summary(
                        context,
                        testcase_name,
                        {'success': False, 'result_type': 'error', 'error': error_msg},
                    )
                    executor.finalize_execution_context(
                        context,
                        userinterface_name,
                        success=False,
                        error_message=error_msg,
                    )
                except Exception as finalize_error:
                    print(f"[@testcase_executor] Failed to finalize errored execution: {finalize_error}")
            
            return {
                'success': False,
                'error': error_msg,
                'execution_time_ms': execution_time_ms
            }
    
    def execute_testcase_from_graph_async(
        self,
        graph: Dict[str, Any],
        team_id: str,
        host_name: str,
        device_id: str,
        device_name: str,
        device_model: str,
        userinterface_name: str = '',
        testcase_name: str = 'unsaved_testcase',  # 🆕 NEW: Accept testcase_name parameter
        execution_metadata: Optional[Dict[str, Any]] = None,
        generate_report: bool = True,
    ) -> Dict[str, Any]:
        """
        Start async execution of test case from graph.
        Returns immediately with execution_id for polling.
        
        Args:
            graph: Graph JSON definition
            team_id: Team ID
            host_name: Host name
            device_id: Device ID
            device_name: Device name
            device_model: Device model
            userinterface_name: Userinterface name (optional)
            testcase_name: Test case name for tracking (optional, defaults to 'unsaved_testcase')
        
        Returns:
            {
                'success': True,
                'execution_id': str,
                'message': 'Execution started'
            }
        """
        execution_id = str(uuid.uuid4())
        
        # Initialize execution state
        with self._lock:
            self._executions[execution_id] = {
                'execution_id': execution_id,
                'status': 'running',
                'start_time': time.time(),
                'host_name': host_name,
                'device_id': device_id,
                'team_id': team_id,
                'current_block_id': None,
                'block_states': {},  # block_id -> {status, duration, error, message}
                'result': None,
                'error': None,
                'context': None  # 🆕 NEW: Store context reference for live variable/metadata tracking
            }
        
        # Start execution in background thread
        thread = threading.Thread(
            target=self._execute_testcase_async_worker,
            args=(execution_id, graph, team_id, host_name, device_id, device_name, device_model, userinterface_name, testcase_name, execution_metadata, generate_report)
        )
        thread.daemon = True
        thread.start()
        
        print(f"[@testcase_executor] Started async execution: {execution_id}")
        emit_execution_event(
            'testcase',
            execution_id,
            'running',
            host_name=host_name,
            device_id=device_id,
            team_id=team_id,
            progress=0,
            message='Test case execution started',
        )
        
        return {
            'success': True,
            'execution_id': execution_id,
            'message': 'Execution started asynchronously'
        }
    
    def _execute_testcase_async_worker(
        self,
        execution_id: str,
        graph: Dict[str, Any],
        team_id: str,
        host_name: str,
        device_id: str,
        device_name: str,
        device_model: str,
        userinterface_name: str,
        testcase_name: str = 'unsaved_testcase',  # 🆕 NEW: Accept testcase_name parameter
        execution_metadata: Optional[Dict[str, Any]] = None,
        generate_report: bool = True,
    ):
        """Background worker for async execution"""
        start_time = time.time()
        context = None
        
        try:
            # Validate graph
            print(f"[@testcase_executor:{execution_id}] Validating graph...")
            is_valid, errors, warnings = self.validator.validate_graph(
                graph,
                userinterface_name=userinterface_name,
                team_id=team_id
            )
            
            if not is_valid:
                error_msg = '; '.join(errors)
                print(f"[@testcase_executor:{execution_id}] Validation failed: {error_msg}")
                with self._lock:
                    self._executions[execution_id]['status'] = 'failed'
                    self._executions[execution_id]['error'] = f'Invalid graph: {error_msg}'
                    self._executions[execution_id]['result'] = {
                        'success': False,
                        'error': f'Invalid graph: {error_msg}',
                        'validation_errors': errors,
                        'execution_time_ms': 0
                    }
                emit_execution_event(
                    'testcase',
                    execution_id,
                    'failed',
                    host_name=host_name,
                    device_id=device_id,
                    team_id=team_id,
                    error=f'Invalid graph: {error_msg}',
                    progress=100,
                    message='Test case validation failed',
                )
                return
            
            # Record execution start
            start_metadata = self._create_start_metadata(
                device_id=device_id,
                device_model=device_model,
                execution_id=execution_id,
                unsaved=testcase_name == 'unsaved_testcase',
                execution_metadata=execution_metadata,
                testcase_name=testcase_name,
                team_id=team_id,
            )
            # Ad-hoc single-step runs (generate_report=False) skip the DB lifecycle
            # entirely — no start row to record, so finalize has nothing to update.
            if generate_report:
                script_result_id = record_script_execution_start(
                    team_id=team_id,
                    script_name=testcase_name,  # 🆕 FIXED: Use provided testcase_name
                    script_type='testcase',
                    userinterface_name=userinterface_name,
                    host_name=host_name,
                    device_name=device_name,
                    metadata=start_metadata
                )
            else:
                script_result_id = None

            print(f"[@testcase_executor:{execution_id}] Script result ID: {script_result_id}")
            
            # Create execution context
            context = ScriptExecutionContext(testcase_name)  # 🆕 FIXED: Use provided testcase_name
            context.script_result_id = script_result_id
            context.team_id = team_id
            context.userinterface_name = userinterface_name
            context.initial_metadata = start_metadata.copy()
            # Testcases never go through /server/script/execute, so they receive no
            # forwarded identity — resolve it here or the TCnnn prefix is missing
            # from every testcase report.
            context.script_identity = resolve_script_identity(testcase_name, team_id=team_id)
            
            # Start stdout capture for logs (CRITICAL for log upload)
            context.start_stdout_capture()
            print(f"[@testcase_executor:{execution_id}] Started stdout capture for logs")
            self._print_execution_banner(context, testcase_name)
            
            # Get device
            from backend_host.src.controllers.controller_manager import get_host
            host = get_host(device_ids=[device_id])
            device = next((d for d in host.get_devices() if d.device_id == device_id), None)
            
            if not device:
                raise ValueError(f"Device not found: {device_id}")
            
            context.selected_device = device
            context.host = host
            self._set_running_log_path(context, device_id)
            
            # 🆕 Store context reference in execution dict for live tracking
            with self._lock:
                if execution_id in self._executions:
                    self._executions[execution_id]['context'] = context
            
            # Populate device navigation_context
            nav_context = device.navigation_context
            nav_context['script_id'] = script_result_id
            nav_context['script_name'] = testcase_name  # 🆕 FIXED: Use provided testcase_name
            nav_context['script_context'] = 'testcase'
            nav_context['current_node_id'] = None
            nav_context['current_node_label'] = None

            from shared.src.lib.utils.device_utils import capture_screenshot
            print(f"📸 [@testcase_executor:{execution_id}] Capturing initial state screenshot...")
            capture_screenshot(context.selected_device, context, f"[@testcase_executor:{execution_id}]")
            
            # Initialize scriptConfig inputs and variables in context
            self._initialize_script_inputs_and_variables(graph, context)
            
            # Store context for block execution callbacks
            self.context = context
            self.device = device
            
            # Execute graph with progress tracking
            print(f"[@testcase_executor:{execution_id}] Executing test case...")
            import asyncio
            execution_result = asyncio.run(self._execute_graph_with_tracking(graph, context, execution_id))
            
            # Calculate execution time
            execution_time_ms = int((time.time() - start_time) * 1000)
            
            # Generate report (same as synchronous path). Single-step runs pass
            # generate_report=False, which makes finalize skip the artifact tail
            # (video/R2/HTML/DB) and just clean up the device — fast, no report.
            print(f"[@testcase_executor:{execution_id}] Finalizing execution (generate_report={generate_report})...")
            report_url = ""
            logs_url = ""
            try:
                from shared.src.lib.executors.script_executor import ScriptExecutor
                executor = ScriptExecutor(testcase_name)
                executor.current_trigger = getattr(context, 'trigger', None) or {}

                # Set overall_success in context
                context.overall_success = execution_result['success']
                context.error_message = execution_result.get('error', '') or ''
                context.execution_summary = self._build_execution_summary(context, testcase_name, execution_result)

                finalization = executor.finalize_execution_context(
                    context,
                    userinterface_name,
                    success=execution_result['success'],
                    error_message=execution_result.get('error'),
                    generate_report=generate_report,
                )
                report_url = finalization.get('report_url', '')
                logs_url = finalization.get('logs_url', '')
                print(f"[@testcase_executor:{execution_id}] Report URL: {report_url}")
                print(f"[@testcase_executor:{execution_id}] Logs URL: {logs_url}")
            except Exception as e:
                print(f"[@testcase_executor:{execution_id}] Error generating report: {e}")
                import traceback
                traceback.print_exc()
            
            # Update execution state
            with self._lock:
                if self._executions[execution_id].get('status') != 'aborted':
                    self._executions[execution_id]['status'] = 'completed'
                    self._executions[execution_id]['result'] = {
                        'success': execution_result['success'],
                        'result_type': execution_result.get('result_type', 'error'),
                        'execution_time_ms': execution_time_ms,
                        'step_count': len(context.step_results),
                        'error': execution_result.get('error'),
                        'script_result_id': script_result_id,
                        'step_results': context.step_results,
                        'report_url': report_url,
                        'logs_url': logs_url
                    }
                else:
                    # Abort already emitted; don't overwrite state.
                    return
            emit_execution_event(
                'testcase',
                execution_id,
                'completed',
                host_name=host_name,
                device_id=device_id,
                team_id=team_id,
                result=self._executions[execution_id]['result'],
                progress=100,
                message='Test case execution completed',
            )
            
            print(f"[@testcase_executor:{execution_id}] Execution completed: {execution_result.get('result_type')}")
            
        except Exception as e:
            execution_time_ms = int((time.time() - start_time) * 1000)
            error_msg = f"Execution error: {str(e)}"
            print(f"[@testcase_executor:{execution_id}] ERROR: {error_msg}")
            
            import traceback
            traceback.print_exc()

            if context is not None:
                try:
                    from shared.src.lib.executors.script_executor import ScriptExecutor
                    executor = ScriptExecutor(testcase_name)
                    executor.current_trigger = getattr(context, 'trigger', None) or {}
                    context.error_message = error_msg
                    context.execution_summary = self._build_execution_summary(
                        context,
                        testcase_name,
                        {'success': False, 'result_type': 'error', 'error': error_msg},
                    )
                    finalization = executor.finalize_execution_context(
                        context,
                        userinterface_name,
                        success=False,
                        error_message=error_msg,
                        generate_report=generate_report,
                    )
                    report_url = finalization.get('report_url', '')
                    logs_url = finalization.get('logs_url', '')
                except Exception as finalize_error:
                    print(f"[@testcase_executor:{execution_id}] Failed to finalize errored execution: {finalize_error}")
                    report_url = ''
                    logs_url = ''
            else:
                report_url = ''
                logs_url = ''
            
            with self._lock:
                if self._executions[execution_id].get('status') != 'aborted':
                    self._executions[execution_id]['status'] = 'failed'
                    self._executions[execution_id]['error'] = error_msg
                    self._executions[execution_id]['result'] = {
                        'success': False,
                        'error': error_msg,
                        'execution_time_ms': execution_time_ms,
                        'report_url': report_url,
                        'logs_url': logs_url,
                    }
                else:
                    return
            emit_execution_event(
                'testcase',
                execution_id,
                'failed',
                host_name=host_name,
                device_id=device_id,
                team_id=team_id,
                error=error_msg,
                result=self._executions[execution_id]['result'],
                progress=100,
                message='Test case execution failed',
            )
    
    def get_execution_status(self, execution_id: str) -> Optional[Dict[str, Any]]:
        """
        Get current status of async execution.
        
        Returns:
            {
                'execution_id': str,
                'status': 'running' | 'completed' | 'failed' | 'aborted',
                'current_block_id': str | None,
                'block_states': {},
                'result': {} | None,
                'error': str | None,
                'elapsed_time_ms': int,
                'variables': {},  # 🆕 NEW: Runtime variable values
                'metadata': {}    # 🆕 NEW: Runtime metadata values
            }
        """
        with self._lock:
            if execution_id not in self._executions:
                return None
            
            execution = self._executions[execution_id].copy()
            
            # Calculate elapsed time
            start_time = execution.get('start_time', time.time())
            execution['elapsed_time_ms'] = int((time.time() - start_time) * 1000)
            
            # 🆕 NEW: Extract live variable and metadata values from context
            context = execution.get('context')
            if context:
                execution['variables'] = getattr(context, 'variables', {}).copy() if hasattr(context, 'variables') else {}
                execution['metadata'] = getattr(context, 'metadata', {}).copy() if hasattr(context, 'metadata') else {}
            else:
                execution['variables'] = {}
                execution['metadata'] = {}
            
            # Don't include start_time and context in response
            execution.pop('start_time', None)
            execution.pop('context', None)  # Don't send context object to frontend
            
            return execution

    def abort_running_execution(self, device_id: str, execution_id: Optional[str] = None) -> Dict[str, Any]:
        """Mark running async testcase execution(s) as aborted."""
        aborted_ids: List[str] = []
        with self._lock:
            for exec_id, execution in self._executions.items():
                if execution.get('status') != 'running':
                    continue
                if execution_id and exec_id != execution_id:
                    continue
                if device_id and execution.get('device_id') != device_id:
                    continue

                execution['status'] = 'aborted'
                execution['error'] = 'Execution aborted by user'
                execution['result'] = {
                    'success': False,
                    'result_type': 'error',
                    'execution_time_ms': int((time.time() - execution.get('start_time', time.time())) * 1000),
                    'error': 'Execution aborted by user',
                }
                aborted_ids.append(exec_id)

        if not aborted_ids:
            return {
                'success': True,
                'aborted': False,
                'message': f'No running testcase execution found for device {device_id}',
            }

        for exec_id in aborted_ids:
            execution = self._executions.get(exec_id, {})
            emit_execution_event(
                'testcase',
                exec_id,
                'aborted',
                host_name=execution.get('host_name'),
                device_id=execution.get('device_id'),
                team_id=execution.get('team_id'),
                error='Execution aborted by user',
                result=execution.get('result'),
                progress=100,
                message='Test case execution aborted by user',
            )

        return {
            'success': True,
            'aborted': True,
            'aborted_execution_ids': aborted_ids,
            'message': f'Aborted {len(aborted_ids)} testcase execution(s) on device {device_id}',
        }
    
    def _is_aborted(self, context: ScriptExecutionContext) -> bool:
        """True once this execution has been marked aborted (force take-control, user abort).

        Abort is cooperative — there is no subprocess to signal, so it is only honoured
        where this is polled. Reads the execution_id off the context so nested graphs and
        loop bodies (which do not receive execution_id) can check it too.
        """
        execution_id = getattr(context, 'testcase_execution_id', None)
        if not execution_id:
            return False
        with self._lock:
            execution_state = self._executions.get(execution_id)
            return bool(execution_state and execution_state.get('status') == 'aborted')

    async def _execute_graph_with_tracking(self, graph: Dict[str, Any], context: ScriptExecutionContext, execution_id: str) -> Dict[str, Any]:
        """
        Execute graph with real-time progress tracking for async execution.
        Updates execution state as blocks are processed.
        """
        # Carried on the context so _execute_graph / _execute_loop_block, which are shared
        # with the untracked sync path, can poll the abort flag without a signature change.
        context.testcase_execution_id = execution_id
        nodes = {node['id']: node for node in graph['nodes']}
        edges = graph['edges']
        
        # Find START block
        start_node = next((node for node in graph['nodes'] if node['type'] == 'start'), None)
        if not start_node:
            return {'success': False, 'error': 'No START block found'}
        
        start_node_id = start_node['id']
        current_node_id = self._find_next_node(start_node_id, 'success', edges)
        
        if not current_node_id:
            executable_blocks = [n for n in graph['nodes'] if n['type'] not in ['start', 'success', 'failure', 'break_success']]
            if executable_blocks:
                return {'success': False, 'error': 'START block is not connected to any executable block'}
            else:
                context.overall_success = True
                return {'success': True, 'result_type': 'success'}
        
        max_iterations = 1000
        iteration_count = 0
        
        while current_node_id and iteration_count < max_iterations:
            iteration_count += 1

            with self._lock:
                execution_state = self._executions.get(execution_id)
                if execution_state and execution_state.get('status') == 'aborted':
                    context.overall_success = False
                    return {'success': False, 'result_type': 'error', 'error': 'Execution aborted by user'}
            
            # Update current block ID in execution state
            with self._lock:
                if execution_id in self._executions:
                    self._executions[execution_id]['current_block_id'] = current_node_id
            
            current_node = nodes.get(current_node_id)
            if not current_node:
                return {'success': False, 'error': f'Node not found: {current_node_id}'}
            
            node_type = current_node['type']
            
            # Terminal blocks
            if node_type == 'success':
                context.overall_success = True
                print(f"[@testcase_executor:{execution_id}] ✅ REACHED SUCCESS BLOCK - about to resolve metadata")
                
                # 🔍 DEBUG: Log block_outputs before resolution
                print(f"[@testcase_executor:{execution_id}] 🔍 DEBUG: block_outputs before resolution:")
                block_outputs = getattr(context, 'block_outputs', {})
                print(f"  - type: {type(block_outputs)}")
                print(f"  - keys: {list(block_outputs.keys())}")
                for block_id, outputs in block_outputs.items():
                    print(f"  - {block_id}: {list(outputs.keys()) if isinstance(outputs, dict) else outputs}")
                
                # Resolve scriptConfig outputs and metadata before returning
                print(f"[@testcase_executor:{execution_id}] 🔄 Calling _resolve_script_outputs_and_metadata...")
                self._resolve_script_outputs_and_metadata(graph, context)
                print(f"[@testcase_executor:{execution_id}] ✅ Metadata resolution completed")
                
                return {'success': True, 'result_type': 'success'}
            
            if node_type == 'failure':
                context.overall_success = False
                return {'success': False, 'result_type': 'failure', 'error': 'Test case reached FAILURE block'}
            
            # Execute block
            block_start_time = time.time()
            block_start_iso = datetime.now(timezone.utc).isoformat()
            next_step_number = context.step_counter + 1
            step_start_screenshot_path = self._capture_step_screenshot(context, next_step_number, 'start', node_type)
            self.current_block_id = current_node_id
            try:
                block_result = await self._execute_block(current_node, context)
            except Exception as e:
                error_msg = f"Block {current_node_id} execution error: {str(e)}"
                return {'success': False, 'result_type': 'error', 'error': error_msg}
            
            block_duration_ms = int((time.time() - block_start_time) * 1000)
            block_end_iso = datetime.now(timezone.utc).isoformat()
            step_end_screenshot_path = self._capture_step_screenshot(context, next_step_number, 'end', node_type)
            
            # ✅ Store block output_data for scriptConfig resolution (CRITICAL!)
            if block_result.get('output_data'):
                if not hasattr(context, 'block_outputs'):
                    context.block_outputs = {}
                context.block_outputs[current_node_id] = block_result['output_data']
                print(f"[@testcase_executor:{execution_id}] ✅ Stored block outputs for {current_node_id}: {list(block_result['output_data'].keys())}")
                
                # 🆕 Immediately update any variables linked to this block's outputs
                self._update_linked_variables(current_node_id, block_result['output_data'], graph, context, execution_id)
                
                # 🆕 Immediately update any metadata fields linked to this block's outputs or variables
                self._update_linked_metadata(current_node_id, block_result['output_data'], graph, context, execution_id)
            
            # Update block state in execution tracking
            with self._lock:
                if execution_id in self._executions:
                    self._executions[execution_id]['block_states'][current_node_id] = {
                        'status': 'success' if block_result['success'] else 'failure',
                        'duration': block_duration_ms,
                        'error': block_result.get('error'),
                        'message': block_result.get('message')
                    }
            
            # Record step
            self._record_block_step(
                context=context,
                node=current_node,
                block_result=block_result,
                block_start_iso=block_start_iso,
                block_end_iso=block_end_iso,
                block_duration_ms=block_duration_ms,
                step_start_screenshot_path=step_start_screenshot_path,
                step_end_screenshot_path=step_end_screenshot_path,
            )
            
            # Find next node
            edge_type = 'success' if block_result['success'] else 'failure'
            next_node_id = self._find_next_node(current_node_id, edge_type, edges)
            
            if not next_node_id:
                if edge_type == 'failure':
                    context.overall_success = False
                    return {'success': False, 'result_type': 'failure', 'error': f'Block {current_node_id} failed with no failure handler'}
                else:
                    context.overall_success = False
                    return {'success': False, 'result_type': 'error', 'error': f'No {edge_type} connection from block {current_node_id}'}
            
            current_node_id = next_node_id
        
        if iteration_count >= max_iterations:
            return {'success': False, 'result_type': 'error', 'error': 'Max iterations reached (possible infinite loop)'}
        
        return {'success': False, 'result_type': 'error', 'error': 'Graph execution ended unexpectedly'}
    
    async def _execute_graph(self, graph: Dict[str, Any], context: ScriptExecutionContext) -> Dict[str, Any]:
        """
        Execute a test case graph by traversing nodes.
        
        START block is never executed - it's only an entry point marker.
        SUCCESS/FAILURE blocks are terminal - they end execution immediately.
        Execution begins at the first executable block connected to START.
        
        Args:
            graph: {nodes: [...], edges: [...]}
            context: Execution context
        
        Returns:
            {
                success: bool (True only if reached SUCCESS terminal block),
                result_type: 'success' | 'failure' | 'error',
                error: str (if error occurred)
            }
        """
        nodes = {node['id']: node for node in graph['nodes']}
        edges = graph['edges']
        
        # Debug: Print raw graph structure
        print(f"[@testcase_executor] === RAW GRAPH DEBUG ===")
        print(f"[@testcase_executor] Total nodes: {len(graph['nodes'])}")
        for node in graph['nodes']:
            print(f"[@testcase_executor]   Node: {node['id']} (type: {node['type']})")
        
        print(f"[@testcase_executor] Total edges: {len(edges)}")
        for edge in edges:
            edge_type = edge.get('sourceHandle') or edge.get('type', 'unknown')
            print(f"[@testcase_executor]   Edge: {edge['source']} --[{edge_type}]--> {edge['target']}")
        print(f"[@testcase_executor] === END RAW GRAPH DEBUG ===")
        
        # Find START block - it's the entry point but never executed
        start_node = next((node for node in graph['nodes'] if node['type'] == 'start'), None)
        if not start_node:
            return {'success': False, 'error': 'No START block found'}
        
        # Skip START and find the first executable block
        # START is only a marker - execution begins at the first connected block
        start_node_id = start_node['id']
        print(f"[@testcase_executor] START node ID: {start_node_id}")
        print(f"[@testcase_executor] Looking for 'success' edge from START...")
        current_node_id = self._find_next_node(start_node_id, 'success', edges)
        
        if current_node_id:
            print(f"[@testcase_executor] Found first executable block: {current_node_id}")
        else:
            print(f"[@testcase_executor] No block connected to START via 'success' edge")
        
        # If START has no connection, check if graph has other blocks
        if not current_node_id:
            # Count executable blocks (exclude START, SUCCESS, FAILURE)
            executable_blocks = [n for n in graph['nodes'] if n['type'] not in ['start', 'success', 'failure', 'break_success']]
            
            if executable_blocks:
                # Graph has blocks but START is not connected - this is an error
                return {
                    'success': False,
                    'error': f'START block is not connected to any executable block. Found {len(executable_blocks)} disconnected block(s).'
                }
            else:
                # No executable blocks - minimal test case (just validates setup)
                print(f"[@testcase_executor] No executable blocks - minimal test case, treating as success")
                context.overall_success = True
                return {'success': True, 'result_type': 'success'}
        
        visited_blocks = set()
        max_iterations = 1000  # Prevent infinite loops
        iteration_count = 0
        
        print(f"[@testcase_executor] Skipping START block, beginning execution at first connected block: {current_node_id}")
        
        while current_node_id and iteration_count < max_iterations:
            iteration_count += 1

            # Reached via nested graphs from the tracked async path, so honour abort here
            # too — otherwise a testcase inside a loop keeps driving a device that has
            # already been taken over. No-ops for the untracked sync path.
            if self._is_aborted(context):
                context.overall_success = False
                return {'success': False, 'result_type': 'error', 'error': 'Execution aborted by user'}

            # Get current node
            current_node = nodes.get(current_node_id)
            if not current_node:
                return {'success': False, 'error': f'Node not found: {current_node_id}'}

            node_type = current_node['type']
            
            print(f"[@testcase_executor] Processing block: {current_node_id} (type: {node_type})")
            
            # SUCCESS and FAILURE are terminal blocks - they end execution immediately
            # They are not executed, just signal the final test result
            if node_type == 'success':
                context.overall_success = True
                print(f"[@testcase_executor] Reached SUCCESS terminal block - test passed")
                
                # 🔍 DEBUG: Log block_outputs before resolution
                print(f"[@testcase_executor] 🔍 DEBUG: block_outputs before resolution:")
                block_outputs = getattr(context, 'block_outputs', {})
                print(f"  - type: {type(block_outputs)}")
                print(f"  - keys: {list(block_outputs.keys())}")
                for block_id, outputs in block_outputs.items():
                    print(f"  - {block_id}: {list(outputs.keys()) if isinstance(outputs, dict) else outputs}")
                
                # Resolve scriptConfig outputs and metadata before returning
                self._resolve_script_outputs_and_metadata(graph, context)
                
                return {'success': True, 'result_type': 'success'}
            
            if node_type == 'failure':
                context.overall_success = False
                print(f"[@testcase_executor] Reached FAILURE terminal block - test failed")
                return {'success': False, 'result_type': 'failure', 'error': 'Test case reached FAILURE block'}

            # break_success is a loop-only terminal (QuickTest "break on success"):
            # like SUCCESS, but the result_type signals the enclosing loop to stop
            # early with a PASS instead of running its remaining iterations. Only
            # appears inside a loop's nested_blocks — harmless at the top level.
            if node_type == 'break_success':
                context.overall_success = True
                print(f"[@testcase_executor] Reached BREAK_SUCCESS terminal block - loop stops early (pass)")
                return {'success': True, 'result_type': 'break_success'}
            
            # Execute block
            self.current_block_id = current_node_id  # Set for output storage
            block_start_time = time.time()
            block_start_iso = datetime.now(timezone.utc).isoformat()
            next_step_number = context.step_counter + 1
            step_start_screenshot_path = self._capture_step_screenshot(context, next_step_number, 'start', node_type)
            try:
                block_result = await self._execute_block(current_node, context)
            except Exception as e:
                error_msg = f"Block {current_node_id} execution error: {str(e)}"
                print(f"[@testcase_executor] ERROR: {error_msg}")
                return {'success': False, 'result_type': 'error', 'error': error_msg}
            block_duration_ms = int((time.time() - block_start_time) * 1000)
            block_end_iso = datetime.now(timezone.utc).isoformat()
            step_end_screenshot_path = self._capture_step_screenshot(context, next_step_number, 'end', node_type)
            
            # Show execution result
            result_status = "SUCCESS" if block_result['success'] else "FAILURE"
            print(f"[@testcase_executor] Block {current_node_id} executed: {result_status}")
            if block_result.get('message'):
                print(f"[@testcase_executor]   Message: {block_result['message']}")
            if block_result.get('error'):
                print(f"[@testcase_executor]   Error: {block_result['error']}")
            
            # Record step with block ID for frontend tracking
            self._record_block_step(
                context=context,
                node=current_node,
                block_result=block_result,
                block_start_iso=block_start_iso,
                block_end_iso=block_end_iso,
                block_duration_ms=block_duration_ms,
                step_start_screenshot_path=step_start_screenshot_path,
                step_end_screenshot_path=step_end_screenshot_path,
            )
            
            # Find next node based on success/failure result
            edge_type = 'success' if block_result['success'] else 'failure'
            print(f"[@testcase_executor] Looking for {edge_type} edge from block {current_node_id}...")
            next_node_id = self._find_next_node(current_node_id, edge_type, edges)
            
            if not next_node_id:
                # Block executed but has no outgoing connection for this result
                if edge_type == 'failure':
                    # IMPLICIT FAILURE ROUTING: Unconnected failure edges automatically route to FAILURE terminal
                    print(f"[@testcase_executor] No failure edge found from block {current_node_id} - implicitly routing to FAILURE terminal")
                    context.overall_success = False
                    return {'success': False, 'result_type': 'failure', 'error': f'Block {current_node_id} failed with no failure handler (implicit FAILURE terminal)'}
                else:
                    # Success edge must be connected - this is an error in graph structure
                    error_msg = f"No {edge_type} connection found from block {current_node_id}"
                    print(f"[@testcase_executor] ERROR: {error_msg}")
                    context.overall_success = False
                    return {'success': False, 'result_type': 'error', 'error': error_msg}
            
            print(f"[@testcase_executor] Following {edge_type} edge to block: {next_node_id}")
            
            current_node_id = next_node_id
        
        # Max iterations reached - treat as error
        if iteration_count >= max_iterations:
            return {'success': False, 'result_type': 'error', 'error': 'Max iterations reached (possible infinite loop)'}
        
        return {'success': False, 'result_type': 'error', 'error': 'Graph execution ended unexpectedly'}
    
    async def _execute_block(self, node: Dict, context: ScriptExecutionContext) -> Dict[str, Any]:
        """
        Execute a single block by delegating to appropriate executor.
        Captures all stdout/stderr logs during execution.
        
        Returns:
            {success: bool, execution_time_ms: int, message: str, error: str, logs: str}
        """
        # Capture logs during block execution
        log_buffer = io.StringIO()
        old_stdout = sys.stdout
        old_stderr = sys.stderr
        
        try:
            # Redirect stdout/stderr to buffer
            sys.stdout = log_buffer
            sys.stderr = log_buffer
            
            node_type = node['type']
            data = node.get('data', {})

            # START block should never reach here - it's skipped in _execute_graph
            if node_type == 'start':
                raise Exception('START block should not be executed - it is only an entry point marker')

            # Resolve {variable} placeholders from context.variables (populated from
            # scriptConfig inputs/variables) BEFORE dispatch — single resolution locus
            # covering target_node_label, actions[].params, verifications[].params and
            # standard-block params. Resolving here (not at graph load) means values
            # set later by set_variable / linked outputs bind correctly downstream.
            try:
                data = self._resolve_block_data(data, context)
            except ValueError as resolve_error:
                return {
                    'success': False,
                    'execution_time_ms': 0,
                    'error': str(resolve_error),
                    'logs': log_buffer.getvalue(),
                }

            # Execute based on type
            if node_type == 'action':
                result = await self._execute_action_block(data, context)
            elif node_type == 'verification':
                # Verification blocks run through the VERIFICATION executor (not
                # the action executor): it evaluates ALL legs and honors the
                # 'all'/'any' pass condition natively. The action executor breaks
                # on first failure, which would make 'any' unsatisfiable.
                result = await self._execute_verification_block(data, context)
            elif node_type == 'navigation':
                result = await self._execute_navigation_block(data, context)
            elif node_type == 'loop':
                # Pass the node with resolved top-level data (e.g. iterations); the
                # nested graph was skipped by the resolver and resolves per nested block.
                #
                # A loop is a CONTAINER, not a leaf: restore the real stdout for the
                # duration of the nested run so its per-iteration progress and inner
                # traversal stream to the execution log (otherwise every iteration of
                # every inner block gets swallowed into this one block's buffer and
                # the loop reads as an opaque black box). Leaf blocks inside still
                # redirect their own stdout per step, so their detailed logs remain
                # attached to each recorded step for the report.
                sys.stdout = old_stdout
                sys.stderr = old_stderr
                try:
                    result = await self._execute_loop_block({**node, 'data': data}, context)
                finally:
                    sys.stdout = log_buffer
                    sys.stderr = log_buffer
            else:
                # Try to execute as standard block (evaluate_condition, sleep, etc.)
                # Block registry auto-discovers all blocks from builder/blocks/ folder
                result = await self._execute_standard_block(data, context)
            
            # Add captured logs to result
            result['logs'] = log_buffer.getvalue()
            return result
            
        finally:
            # Always restore stdout/stderr
            sys.stdout = old_stdout
            sys.stderr = old_stderr
    
    async def _execute_action_block(self, data: Dict, context: ScriptExecutionContext) -> Dict[str, Any]:
        """
        Execute an ACTION container block: data['actions'] is an ordered sequence
        run via the action executor (which correctly aborts the sequence on the
        first failed action). No legacy single-command shape — blocks authored
        before the container refactor must be re-created.
        """
        start_time = time.time()

        try:
            items = data.get('actions')
            if not isinstance(items, list) or not items:
                return {
                    'success': False,
                    'execution_time_ms': int((time.time() - start_time) * 1000),
                    'error': 'Action block has no actions — re-create the block',
                }

            retry_actions = data.get('retry_actions', [])
            failure_actions = data.get('failure_actions', [])

            def _to_action(it: Dict) -> Dict:
                # Only include fields that have values — None breaks action_type routing.
                a = {'command': it.get('command'), 'params': it.get('params', {})}
                if it.get('action_type'):
                    a['action_type'] = it['action_type']
                if it.get('verification_type'):
                    a['verification_type'] = it['verification_type']
                if it.get('threshold') is not None:
                    a['threshold'] = it['threshold']
                if it.get('reference'):
                    a['reference'] = it['reference']
                return a

            actions = [_to_action(it) for it in items]

            # Use orchestrator for unified logging
            from backend_host.src.orchestrator import ExecutionOrchestrator
            result = await ExecutionOrchestrator.execute_actions(
                device=self.device,
                actions=actions,
                retry_actions=retry_actions,
                failure_actions=failure_actions,
                team_id=context.team_id,
                context=context,
                userinterface_name=getattr(context, 'userinterface_name', None) or data.get('userinterface_name'),
            )

            execution_time_ms = int((time.time() - start_time) * 1000)

            # ✅ Include output_data from result for block_outputs storage
            return {
                'success': result['success'],
                'execution_time_ms': execution_time_ms,
                'message': f"Block: {len(actions)} action(s)",
                'error': result.get('error'),
                'output_data': result.get('output_data', {})  # ✅ Pass through output_data
            }

        except Exception as e:
            execution_time_ms = int((time.time() - start_time) * 1000)
            return {
                'success': False,
                'execution_time_ms': execution_time_ms,
                'error': f'Action execution error: {str(e)}'
            }

    async def _execute_verification_block(self, data: Dict, context: ScriptExecutionContext) -> Dict[str, Any]:
        """
        Execute a VERIFICATION container block: data['verifications'] is a set
        evaluated through the verification executor, which runs ALL legs and
        honors data['verification_pass_condition'] ('all'|'any') natively —
        auto-detected from verifications[0]['verification_pass_condition']
        (same mechanism as the node-verification flow). Per-leg results are
        attached as 'verification_results' for the step report.
        """
        start_time = time.time()

        try:
            items = data.get('verifications')
            if not isinstance(items, list) or not items:
                return {
                    'success': False,
                    'execution_time_ms': int((time.time() - start_time) * 1000),
                    'error': 'Verification block has no verifications — re-create the block',
                }

            pass_condition = data.get('verification_pass_condition', 'all')

            verifications = []
            for it in items:
                v = {
                    'command': it.get('command'),
                    'params': it.get('params', {}),
                    # The executor auto-detects the pass condition from the items.
                    'verification_pass_condition': pass_condition,
                }
                if it.get('verification_type'):
                    v['verification_type'] = it['verification_type']
                if it.get('threshold') is not None:
                    v['threshold'] = it['threshold']
                if it.get('reference'):
                    v['reference'] = it['reference']
                verifications.append(v)

            from backend_host.src.orchestrator import ExecutionOrchestrator
            result = await ExecutionOrchestrator.execute_verifications(
                device=self.device,
                verifications=verifications,
                userinterface_name=getattr(context, 'userinterface_name', None) or data.get('userinterface_name') or '',
                team_id=context.team_id,
                context=context,
            )

            execution_time_ms = int((time.time() - start_time) * 1000)

            return {
                'success': result.get('success', False),
                'execution_time_ms': execution_time_ms,
                'message': f"Block: {len(verifications)} verification(s) [{pass_condition}]",
                'error': result.get('error'),
                'output_data': result.get('output_data', {}) or {},
                # Per-leg rows (1:1 with input) for _build_step_verifications.
                'verification_results': result.get('results', []),
            }

        except Exception as e:
            execution_time_ms = int((time.time() - start_time) * 1000)
            return {
                'success': False,
                'execution_time_ms': execution_time_ms,
                'error': f'Verification execution error: {str(e)}'
            }
    
    async def _execute_standard_block(self, data: Dict, context: ScriptExecutionContext) -> Dict[str, Any]:
        """Execute standard block (like evaluate_condition) using Orchestrator"""
        start_time = time.time()
        
        try:
            command = data.get('command')
            params = data.get('params', {})

            # Build blocks array from single block
            blocks = [{
                'command': command,
                'params': params
            }]
            
            # Use orchestrator for unified logging (same pattern as actions/verifications)
            from backend_host.src.orchestrator import ExecutionOrchestrator
            result = await ExecutionOrchestrator.execute_blocks(
                device=self.device,
                blocks=blocks,
                context=context
            )
            
            execution_time_ms = int((time.time() - start_time) * 1000)
            
            # Store block output_data for scriptConfig resolution
            if result.get('output_data'):
                if not hasattr(context, 'block_outputs'):
                    context.block_outputs = {}
                # Store with current block ID
                if self.current_block_id:
                    context.block_outputs[self.current_block_id] = result['output_data']
                    print(f"[@testcase_executor] Stored block outputs for {self.current_block_id}: {list(result['output_data'].keys())}")
            
            return {
                'success': result['success'],
                'execution_time_ms': execution_time_ms,
                'message': f"Standard block: {command}",
                'error': result.get('error')
            }
            
        except Exception as e:
            execution_time_ms = int((time.time() - start_time) * 1000)
            return {
                'success': False,
                'execution_time_ms': execution_time_ms,
                'error': f'Standard block execution error: {str(e)}'
            }
    
    async def _execute_navigation_block(self, data: Dict, context: ScriptExecutionContext) -> Dict[str, Any]:
        """Execute navigation block using ExecutionOrchestrator"""
        start_time = time.time()
        
        try:
            navigation_executor = self.device.navigation_executor
            
            # Load navigation tree if not already loaded
            if not context.tree_id:
                nav_result = navigation_executor.load_navigation_tree(
                    context.userinterface_name,
                    context.team_id
                )
                if not nav_result['success']:
                    return {
                        'success': False,
                        'execution_time_ms': int((time.time() - start_time) * 1000),
                        'error': f"Failed to load navigation tree: {nav_result.get('error')}"
                    }
                context.tree_id = nav_result['tree_id']
            
            # DEBUG: Check navigation context before execution
            nav_context = self.device.navigation_context
            print(f"[@testcase_executor:_execute_navigation_block] 🔍 NAVIGATION CONTEXT CHECK:")
            print(f"[@testcase_executor:_execute_navigation_block]   → current_node_id: {nav_context.get('current_node_id')}")
            print(f"[@testcase_executor:_execute_navigation_block]   → current_node_label: {nav_context.get('current_node_label')}")
            print(f"[@testcase_executor:_execute_navigation_block]   → target_node_label: {data.get('target_node_label')}")
            print(f"[@testcase_executor:_execute_navigation_block]   → target_node_id: {data.get('target_node_id')}")
            
            # Call navigation through ExecutionOrchestrator for consistency
            # PRIORITY: Use label if available (more human-readable), fallback to ID
            # Backend validation requires EXACTLY ONE parameter, not both
            target_label = data.get('target_node_label') or data.get('target_node')
            target_id = data.get('target_node_id')
            
            # ✅ Use ExecutionOrchestrator for unified logging and consistent execution
            from backend_host.src.orchestrator import ExecutionOrchestrator
            
            # Prefer label over ID - only pass ID if no label exists
            if target_label:
                print(f"[@testcase_executor:_execute_navigation_block] Using target_node_label: {target_label}")
                result = await ExecutionOrchestrator.execute_navigation(
                    device=self.device,
                    tree_id=context.tree_id,
                    userinterface_name=context.userinterface_name,
                    target_node_id=None,  # Explicitly set to None when using label
                    target_node_label=target_label,
                    team_id=context.team_id,
                    context=context
                )
            elif target_id:
                print(f"[@testcase_executor:_execute_navigation_block] Using target_node_id: {target_id}")
                result = await ExecutionOrchestrator.execute_navigation(
                    device=self.device,
                    tree_id=context.tree_id,
                    userinterface_name=context.userinterface_name,
                    target_node_id=target_id,
                    target_node_label=None,  # Explicitly set to None when using ID
                    team_id=context.team_id,
                    context=context
                )
            else:
                return {
                    'success': False,
                    'execution_time_ms': int((time.time() - start_time) * 1000),
                    'error': 'Navigation block missing both target_node_label and target_node_id'
                }
            
            execution_time_ms = int((time.time() - start_time) * 1000)
            
            # Get the target for the message
            target = data.get('target_node_label') or data.get('target_node') or data.get('target_node_id') or 'unknown'
            
            return {
                'success': result['success'],
                'execution_time_ms': execution_time_ms,
                'message': f"Navigate to: {target}",
                'error': result.get('error')
            }
            
        except Exception as e:
            execution_time_ms = int((time.time() - start_time) * 1000)
            return {
                'success': False,
                'execution_time_ms': execution_time_ms,
                'error': f'Navigation execution error: {str(e)}'
            }
    
    async def _execute_loop_block(self, node: Dict, context: ScriptExecutionContext) -> Dict[str, Any]:
        """Execute loop block with nested graph"""
        start_time = time.time()
        
        try:
            data = node.get('data', {})
            # iterations may arrive as a resolved {variable} (e.g. the string "3");
            # coerce so range() never sees a str. An unresolved placeholder fails loud.
            raw_iterations = data.get('iterations', 1)
            try:
                iterations = int(raw_iterations)
            except (TypeError, ValueError):
                return {
                    'success': False,
                    'execution_time_ms': 0,
                    'error': f'Loop iterations is not a number: {raw_iterations!r}'
                }
            nested_blocks = data.get('nested_blocks')

            if not nested_blocks:
                return {
                    'success': False,
                    'execution_time_ms': 0,
                    'error': 'Loop block has no nested blocks'
                }
            
            # A nested graph that can reach a break_success terminal is a
            # "break on success" loop (QuickTest retry/poll): it stops early with a
            # PASS when an iteration hits that terminal, and — crucially — counts as
            # FAILED if it exhausts every iteration without ever hitting it (the
            # retry never succeeded). Loops without such a terminal keep the legacy
            # behavior: exhausting all iterations is a PASS.
            has_break_success = any(
                n.get('type') == 'break_success' for n in nested_blocks.get('nodes', [])
            )

            # Tag every step recorded inside an iteration with "[k/N]" so the
            # report distinguishes the repeated runs (cleared/restored around the
            # loop so the loop's own summary step is untagged; save+restore makes
            # this nesting-safe). See _record_block_step.
            prev_iteration_label = getattr(context, 'loop_iteration_label', None)
            try:
                # Execute nested graph for specified iterations
                for i in range(iterations):
                    if self._is_aborted(context):
                        return {
                            'success': False,
                            'execution_time_ms': int((time.time() - start_time) * 1000),
                            'error': 'Execution aborted by user',
                            'message': f'Loop aborted at iteration {i+1}/{iterations}',
                        }

                    print(f"[@testcase_executor] Loop iteration {i+1}/{iterations}")
                    context.loop_iteration_label = f"{i+1}/{iterations}"

                    result = await self._execute_graph(nested_blocks, context)

                    # Iteration reached a break_success terminal -> stop early, pass.
                    if result.get('result_type') == 'break_success':
                        execution_time_ms = int((time.time() - start_time) * 1000)
                        return {
                            'success': True,
                            'execution_time_ms': execution_time_ms,
                            'message': f'Loop stopped early (pass) at iteration {i+1}'
                        }

                    # Check loop behavior (continue/break)
                    if not result['success']:
                        # Nested graph failed - should we break or continue?
                        loop_behavior = data.get('on_failure', 'break')  # 'break' or 'continue'

                        if loop_behavior == 'break':
                            execution_time_ms = int((time.time() - start_time) * 1000)
                            return {
                                'success': False,
                                'execution_time_ms': execution_time_ms,
                                'message': f'Loop failed at iteration {i+1}',
                                'error': result.get('error')
                            }
                        # else: continue to next iteration

                execution_time_ms = int((time.time() - start_time) * 1000)

                # Exhausted all iterations. A break-on-success loop that never broke
                # means the awaited success never happened -> fail.
                if has_break_success:
                    return {
                        'success': False,
                        'execution_time_ms': execution_time_ms,
                        'message': f'Loop exhausted {iterations} iterations without success',
                        'error': f'Loop did not reach a success condition in {iterations} iterations'
                    }

                return {
                    'success': True,
                    'execution_time_ms': execution_time_ms,
                    'message': f'Loop completed {iterations} iterations'
                }
            finally:
                context.loop_iteration_label = prev_iteration_label
            
        except Exception as e:
            execution_time_ms = int((time.time() - start_time) * 1000)
            return {
                'success': False,
                'execution_time_ms': execution_time_ms,
                'error': f'Loop execution error: {str(e)}'
            }
    
    # Keys whose subtrees hold nested graphs — their blocks re-enter _execute_block
    # and resolve there (late binding), so the parent block must not touch them.
    _RESOLVE_SKIP_KEYS = ('nested_blocks', 'nested_graph')

    def _resolve_block_data(self, data: Any, context: ScriptExecutionContext) -> Any:
        """
        Deep-resolve {variable} placeholders in block data from context.variables.

        A string whose WHOLE value matches {name} (same convention as the frontend's
        variableResolutionUtils regex) is replaced by context.variables[name].
        Partial interpolation ("channel_{n}") is intentionally NOT supported.

        Raises:
            ValueError: a placeholder references a name absent from context.variables
                        (no value, no default, not produced by any block).
        """
        if isinstance(data, str):
            match = re.fullmatch(r'\{(.+)\}', data)
            if not match:
                return data
            name = match.group(1).strip()
            variables = getattr(context, 'variables', {}) or {}
            if name not in variables:
                raise ValueError(
                    f"Unresolved variable '{{{name}}}' — no value, default, or variable provides it"
                )
            value = variables[name]
            print(f"[@testcase_executor] Resolved {{{name}}} = {value}")
            return value
        if isinstance(data, dict):
            return {
                key: value if key in self._RESOLVE_SKIP_KEYS else self._resolve_block_data(value, context)
                for key, value in data.items()
            }
        if isinstance(data, list):
            return [self._resolve_block_data(item, context) for item in data]
        return data

    def _initialize_script_inputs_and_variables(self, graph: Dict[str, Any], context: ScriptExecutionContext):
        """
        Initialize scriptConfig inputs and variables at start of execution.
        Populates context.variables with default values and links to inputs.
        
        Args:
            graph: Graph JSON with scriptConfig
            context: Execution context
        """
        script_config = graph.get('scriptConfig')
        if not script_config:
            print(f"[@testcase_executor] No scriptConfig found - skipping input/variable initialization")
            return
        
        print(f"[@testcase_executor] ========== INITIALIZING SCRIPT INPUTS & VARIABLES ==========")
        
        # Initialize Script Inputs in context.variables
        script_inputs_config = script_config.get('inputs', [])
        if script_inputs_config:
            print(f"[@testcase_executor] Initializing {len(script_inputs_config)} script inputs...")
            
            for input_config in script_inputs_config:
                input_name = input_config.get('name')
                # ✅ Check 'value' first (set by frontend at runtime), then fall back to 'default'
                input_value = input_config.get('value')
                if input_value is None:
                    input_value = input_config.get('default')
                input_type = input_config.get('type', 'string')
                
                if not input_name:
                    print(f"[@testcase_executor] Warning: Input config missing 'name', skipping")
                    continue
                
                # An input with neither runtime value nor default stays OUT of
                # context.variables — any block referencing it then fails loudly
                # ("Unresolved variable") instead of silently using ''/0/False.
                if input_value is not None:
                    context.variables[input_name] = input_value
                    print(f"[@testcase_executor]   ✓ {input_name} = {input_value} ({input_type})")
                else:
                    print(f"[@testcase_executor]   ⚠ {input_name} has no value or default — not initialized")
        
        # Initialize Script Variables (with or without source links)
        script_variables_config = script_config.get('variables', [])
        if script_variables_config:
            print(f"[@testcase_executor] Initializing {len(script_variables_config)} script variables...")
            
            for variable_config in script_variables_config:
                variable_name = variable_config.get('name')
                variable_value = variable_config.get('value')
                variable_type = variable_config.get('type', 'string')
                
                if not variable_name:
                    print(f"[@testcase_executor] Warning: Variable config missing 'name', skipping")
                    continue
                
                # Initialize context.variables with value if set
                if variable_value is not None:
                    context.variables[variable_name] = variable_value
                    print(f"[@testcase_executor]   ✓ {variable_name} = {variable_value}")
                else:
                    # Initialize with type default (will be overwritten if linked to block output)
                    if variable_type == 'string':
                        context.variables[variable_name] = ''
                    elif variable_type == 'number':
                        context.variables[variable_name] = 0
                    elif variable_type == 'boolean':
                        context.variables[variable_name] = False
                    else:
                        context.variables[variable_name] = None
                    print(f"[@testcase_executor]   ✓ {variable_name} = {context.variables[variable_name]} (default for {variable_type})")
        
        print(f"[@testcase_executor] ========================================================")
    
    def _update_linked_variables(self, block_id: str, output_data: Dict[str, Any], 
                                  graph: Dict[str, Any], context: ScriptExecutionContext, 
                                  execution_id: str):
        """
        Immediately update any variables that link to this block's outputs.
        Called right after a block executes with outputs.
        
        Args:
            block_id: The block that just executed
            output_data: The output_data from the block
            graph: Graph JSON with scriptConfig
            context: Execution context
            execution_id: Execution ID for logging
        """
        script_config = graph.get('scriptConfig')
        if not script_config:
            return
        
        variables = script_config.get('variables', [])
        if not variables:
            return
        
        # Initialize context.variables if not present
        if not hasattr(context, 'variables'):
            context.variables = {}
        
        # Check each variable to see if it links to this block
        for variable in variables:
            variable_name = variable.get('name')
            if not variable_name:
                continue
            
            # Support both old single-link and new multi-link format
            source_links = variable.get('sourceLinks', [])
            
            # Backward compatibility: convert old format to new
            if not source_links and variable.get('sourceBlockId'):
                source_links = [{
                    'sourceBlockId': variable.get('sourceBlockId'),
                    'sourceOutputName': variable.get('sourceOutputName'),
                    'sourceOutputType': variable.get('sourceOutputType')
                }]
            
            # Check if any source link matches this block
            for link in source_links:
                if link.get('sourceBlockId') == block_id:
                    output_name = link.get('sourceOutputName')
                    if output_name and output_name in output_data:
                        value = output_data[output_name]
                        context.variables[variable_name] = value
                        print(f"[@testcase_executor:{execution_id}] 🔗 Updated variable '{variable_name}' = {value if not isinstance(value, dict) else '{...}'} (from block {block_id[:8]}... output '{output_name}')")
    
    def _update_linked_metadata(self, block_id: str, output_data: Dict[str, Any], 
                                 graph: Dict[str, Any], context: ScriptExecutionContext, 
                                 execution_id: str):
        """
        Immediately update any metadata fields that link to this block's outputs OR variables.
        Called right after a block executes and variables are updated.
        
        Args:
            block_id: The block that just executed
            output_data: The output_data from the block
            graph: Graph JSON with scriptConfig
            context: Execution context
            execution_id: Execution ID for logging
        """
        script_config = graph.get('scriptConfig')
        if not script_config:
            print(f"[@testcase_executor:{execution_id}] 🔍 _update_linked_metadata: No scriptConfig found")
            return
        
        metadata_config = script_config.get('metadata', {})
        metadata_fields = metadata_config.get('fields', [])
        if not metadata_fields:
            print(f"[@testcase_executor:{execution_id}] 🔍 _update_linked_metadata: No metadata fields configured")
            return
        
        print(f"[@testcase_executor:{execution_id}] 🔍 _update_linked_metadata: Checking {len(metadata_fields)} metadata fields for block {block_id[:8]}...")
        
        # Initialize context.metadata if not present
        if not hasattr(context, 'metadata'):
            context.metadata = {}
        
        # Check each metadata field
        for field in metadata_fields:
            field_name = field.get('name')
            source_block_id = field.get('sourceBlockId')
            source_output_name = field.get('sourceOutputName')
            
            print(f"[@testcase_executor:{execution_id}]   🔍 Metadata '{field_name}': sourceBlockId={source_block_id[:8] if source_block_id else 'None'}..., sourceOutputName={source_output_name}")
            
            if not field_name or not source_block_id or not source_output_name:
                print(f"[@testcase_executor:{execution_id}]   ⚠️ Skipping '{field_name}': missing config")
                continue
            
            # Check if this metadata field links to the block that just executed
            if source_block_id == block_id:
                print(f"[@testcase_executor:{execution_id}]   ✅ Block ID matches! Checking output '{source_output_name}'...")
                
                # First check if source_output_name is a variable name
                if hasattr(context, 'variables') and source_output_name in context.variables:
                    value = context.variables[source_output_name]
                    context.metadata[field_name] = value
                    print(f"[@testcase_executor:{execution_id}]   📋 Updated metadata '{field_name}' = {value if not isinstance(value, dict) else '{...}'} (from variable '{source_output_name}')")
                # Otherwise check if it's a direct block output
                elif source_output_name in output_data:
                    value = output_data[source_output_name]
                    context.metadata[field_name] = value
                    print(f"[@testcase_executor:{execution_id}]   📋 Updated metadata '{field_name}' = {value if not isinstance(value, dict) else '{...}'} (from block {block_id[:8]}... output '{source_output_name}')")
                else:
                    print(f"[@testcase_executor:{execution_id}]   ❌ Output '{source_output_name}' not found in variables or block outputs")
            else:
                # 🆕 FALLBACK: If sourceOutputName matches a variable name, use it regardless of block mismatch
                # This handles cases where metadata links to an old/wrong block ID but correct variable name
                if hasattr(context, 'variables') and source_output_name in context.variables:
                    value = context.variables[source_output_name]
                    context.metadata[field_name] = value
                    print(f"[@testcase_executor:{execution_id}]   📋 Updated metadata '{field_name}' = {value if not isinstance(value, dict) else '{...}'} (from variable '{source_output_name}' - block mismatch ignored)")
                else:
                    print(f"[@testcase_executor:{execution_id}]   ⏭️ Block ID doesn't match (expected {source_block_id[:8]}..., got {block_id[:8]}...)")
    
    def _resolve_script_outputs_and_metadata(self, graph: Dict[str, Any], context: ScriptExecutionContext):
        """
        Resolve scriptConfig outputs and metadata from block outputs.
        Populates context.script_outputs and context.metadata based on links.
        
        Args:
            graph: Graph JSON with scriptConfig
            context: Execution context with block_outputs
        """
        script_config = graph.get('scriptConfig')
        if not script_config:
            print(f"[@testcase_executor] No scriptConfig found - skipping output/metadata resolution")
            return
        
        print(f"[@testcase_executor] ========== RESOLVING SCRIPT OUTPUTS & METADATA ==========")
        
        # 🔍 DEBUG: Log scriptConfig content
        print(f"[@testcase_executor] 🔍 DEBUG: scriptConfig content:")
        print(f"  - outputs: {script_config.get('outputs', [])}")
        print(f"  - metadata: {script_config.get('metadata', {})}")
        
        # Resolve Script Outputs
        script_outputs_config = script_config.get('outputs', [])
        if script_outputs_config:
            print(f"[@testcase_executor] Resolving {len(script_outputs_config)} script outputs...")
            
            for output_config in script_outputs_config:
                output_name = output_config.get('name')
                source_block_id = output_config.get('sourceBlockId')
                source_output_name = output_config.get('sourceOutputName')
                source_output_path = output_config.get('sourceOutputPath')  # JSONPath for nested access
                
                if not output_name:
                    print(f"[@testcase_executor] Warning: Output config missing 'name', skipping")
                    continue
                
                if not source_block_id or not source_output_name:
                    print(f"[@testcase_executor] Warning: Output '{output_name}' has no source link, skipping")
                    continue
                
                # Get block output from context
                block_outputs = getattr(context, 'block_outputs', {})
                block_data = block_outputs.get(source_block_id, {})
                output_value = block_data.get(source_output_name)
                
                if output_value is None:
                    print(f"[@testcase_executor] Warning: Block '{source_block_id}' has no output '{source_output_name}'")
                    continue
                
                # Apply JSONPath if specified (for nested access like parsed_data.serial)
                if source_output_path and isinstance(output_value, dict):
                    try:
                        # Simple dot-notation path (e.g., "serial" or "device.serial")
                        for key in source_output_path.split('.'):
                            output_value = output_value.get(key)
                            if output_value is None:
                                break
                    except Exception as e:
                        print(f"[@testcase_executor] Error accessing path '{source_output_path}': {e}")
                        output_value = None
                
                if output_value is not None:
                    # Store in context.script_outputs (for campaign chaining)
                    if not hasattr(context, 'script_outputs'):
                        context.script_outputs = {}
                    context.script_outputs[output_name] = output_value
                    print(f"[@testcase_executor]   ✓ {output_name} = {output_value}")
                else:
                    print(f"[@testcase_executor]   ✗ {output_name} = None (path not found)")
        
        # Resolve Metadata
        metadata_config = script_config.get('metadata', {})
        metadata_mode = metadata_config.get('mode', 'append')
        metadata_fields = metadata_config.get('fields', [])
        
        if metadata_fields:
            print(f"[@testcase_executor] Resolving {len(metadata_fields)} metadata fields (mode: {metadata_mode})...")
            
            resolved_metadata = {}
            
            for field_config in metadata_fields:
                field_name = field_config.get('name')
                source_block_id = field_config.get('sourceBlockId')
                source_output_name = field_config.get('sourceOutputName')
                
                if not field_name:
                    print(f"[@testcase_executor] Warning: Metadata field missing 'name', skipping")
                    continue
                
                if not source_block_id or not source_output_name:
                    print(f"[@testcase_executor] Warning: Metadata field '{field_name}' has no source link, skipping")
                    continue
                
                # Get block output from context
                block_outputs = getattr(context, 'block_outputs', {})
                block_data = block_outputs.get(source_block_id, {})
                field_value = block_data.get(source_output_name)
                
                if field_value is not None:
                    resolved_metadata[field_name] = field_value
                    print(f"[@testcase_executor]   ✓ {field_name} = {field_value if not isinstance(field_value, dict) else '{...}'}")
                else:
                    print(f"[@testcase_executor]   ✗ {field_name} = None (not found)")
            
            # Apply to context.metadata based on mode
            if metadata_mode == 'set':
                # Replace entire metadata
                context.metadata = resolved_metadata
                print(f"[@testcase_executor] Metadata mode 'set': replaced with {len(resolved_metadata)} fields")
            else:  # append (default)
                # Merge into existing metadata
                if not hasattr(context, 'metadata'):
                    context.metadata = {}
                context.metadata.update(resolved_metadata)
                print(f"[@testcase_executor] Metadata mode 'append': added {len(resolved_metadata)} fields")
        
        print(f"[@testcase_executor] ========== RESOLUTION COMPLETE ==========")
        print(f"[@testcase_executor] Script Outputs: {getattr(context, 'script_outputs', {})}")
        print(f"[@testcase_executor] Metadata: {context.metadata}")
    
    def _find_next_node(self, current_node_id: str, edge_type: str, edges: List[Dict]) -> Optional[str]:
        """
        Find the next node ID by following edges.
        
        Args:
            current_node_id: Current node ID
            edge_type: 'success' or 'failure'
            edges: List of edges
        
        Returns:
            Next node ID or None
        """
        for edge in edges:
            if edge['source'] == current_node_id:
                # Check edge type (can be in 'type' or 'sourceHandle')
                edge_handle = edge.get('sourceHandle') or edge.get('type')
                
                # React Flow adds suffixes like '-hitarea' to handle names
                # Match if edge_handle starts with the edge_type we're looking for
                if edge_handle and edge_handle.startswith(edge_type):
                    print(f"[@testcase_executor] Found edge: {current_node_id} --[{edge_handle}]--> {edge['target']}")
                    return edge['target']
        
        return None
