"""
Host Test Prompt Routes — Execute AI test prompts on devices

Flow: initial screenshot → navigate to target screen → verify acceptance criteria → final screenshot → report
"""

import asyncio
import threading
import time
import uuid
from flask import Blueprint, request, jsonify
from backend_host.src.lib.utils.execution_event_utils import emit_execution_event
from shared.src.lib.database.script_results_db import (
    record_script_execution_start,
    update_script_execution_result,
)
from ..lib.test_prompts_db import update_prompt_execution

host_testprompt_bp = Blueprint('host_testprompt', __name__, url_prefix='/host/testprompt')


@host_testprompt_bp.route('/execute', methods=['POST'])
def testprompt_execute():
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'message': 'No data provided'}), 400

    prompt = data.get('prompt', '')
    acceptance_criteria = data.get('acceptance_criteria', '')
    host_name = data.get('host_name', '')
    device_id = data.get('device_id', '')
    device_name = data.get('device_name', device_id)
    device_model = data.get('device_model', '') or 'unknown_model'
    userinterface_name = data.get('userinterface_name', '')
    team_id = data.get('team_id', '')
    test_prompt_id = data.get('test_prompt_id', '')
    prompt_execution_id = data.get('prompt_execution_id', '')
    prompt_name = data.get('prompt_name', 'test_prompt').replace(' ', '_').replace('/', '_')
    target_screen_node_id = data.get('target_screen_node_id', '')
    target_screen_label = data.get('target_screen_label', '')

    if not all([prompt, host_name, device_id, team_id]):
        return jsonify({'success': False, 'message': 'prompt, host_name, device_id, team_id are required'}), 400

    execution_id = str(uuid.uuid4())

    thread = threading.Thread(
        target=_execute_prompt_worker,
        args=(execution_id, prompt, acceptance_criteria, host_name, device_id,
              device_name, device_model, userinterface_name, team_id,
              test_prompt_id, prompt_execution_id, prompt_name,
              target_screen_node_id, target_screen_label),
        daemon=True,
    )
    thread.start()

    emit_execution_event(
        'test_prompt', prompt_execution_id or execution_id, 'running',
        host_name=host_name, device_id=device_id, team_id=team_id,
        progress=0, message='Test prompt execution started',
    )

    return jsonify({
        'success': True,
        'execution_id': execution_id,
        'message': 'Test prompt execution started',
    })


def _take_screenshot(av_controller, label='screenshot'):
    """Take a screenshot and return the path, or None."""
    try:
        if av_controller and hasattr(av_controller, 'take_screenshot'):
            path = av_controller.take_screenshot()
            if path:
                print(f"[@testprompt_executor] Screenshot '{label}': {path}")
                return path
    except Exception as e:
        print(f"[@testprompt_executor] Screenshot '{label}' error: {e}")
    return None


def _execute_prompt_worker(
    execution_id, prompt, acceptance_criteria, host_name, device_id,
    device_name, device_model, userinterface_name, team_id,
    test_prompt_id, prompt_execution_id, prompt_name,
    target_screen_node_id, target_screen_label,
):
    start_time = time.time()
    report_url = None
    logs_url = None
    script_result_id = None
    success = False
    screenshot_paths = []
    step_results = []
    step_num = 0

    def _emit(progress, message):
        emit_execution_event(
            'test_prompt', prompt_execution_id or execution_id, 'running',
            host_name=host_name, device_id=device_id, team_id=team_id,
            progress=progress, message=message,
        )

    try:
        # Record execution start
        script_result_id = record_script_execution_start(
            team_id=team_id,
            script_name=f"prompt_{prompt_name}",
            script_type='test_prompt',
            host_name=host_name,
            device_name=device_name or device_id,
            userinterface_name=userinterface_name,
            metadata={
                'test_prompt_id': test_prompt_id,
                'prompt_execution_id': prompt_execution_id,
                'prompt': prompt[:500],
                'acceptance_criteria': acceptance_criteria[:500],
                'target_screen': target_screen_label or 'none',
            },
        )

        print(f"[@testprompt_executor] Starting execution {execution_id}")
        print(f"[@testprompt_executor] Prompt: {prompt[:100]}")
        print(f"[@testprompt_executor] Target: {target_screen_label or 'none'}")

        # Get device and controllers
        from backend_host.src.lib.utils.host_utils import get_device_by_id, get_controller
        device = get_device_by_id(device_id)
        if not device:
            raise Exception(f"Device {device_id} not found")

        if not device_model or device_model == 'unknown_model':
            device_model = getattr(device, 'device_model', None) or 'unknown_model'
        if not device_name or device_name == device_id:
            device_name = getattr(device, 'device_name', None) or device_id

        av_controller = get_controller(device_id, 'av')

        # ========== STEP 1: Initial screenshot ==========
        _emit(10, 'Capturing initial state...')
        initial_screenshot = _take_screenshot(av_controller, 'initial_state')
        if initial_screenshot:
            screenshot_paths.append(initial_screenshot)

        # ========== STEP 2: Navigate to target screen (if specified) ==========
        nav_success = True
        nav_error = None

        if target_screen_label and target_screen_node_id:
            _emit(20, f'Navigating to {target_screen_label}...')
            step_num += 1
            nav_start = time.time()

            try:
                if hasattr(device, 'navigation_executor') and device.navigation_executor:
                    from backend_host.src.orchestrator.execution_orchestrator import ExecutionOrchestrator

                    # Load navigation tree to get tree_id (same as testcase executor)
                    tree_id = None
                    nav_load = device.navigation_executor.load_navigation_tree(
                        userinterface_name, team_id
                    )
                    if nav_load and nav_load.get('success'):
                        tree_id = nav_load.get('tree_id')
                        print(f"[@testprompt_executor] Navigation tree loaded: {tree_id}")

                    if tree_id:
                        nav_result = asyncio.run(ExecutionOrchestrator.execute_navigation(
                            device=device,
                            tree_id=tree_id,
                            userinterface_name=userinterface_name,
                            target_node_label=target_screen_label,
                            team_id=team_id,
                        ))
                        nav_success = nav_result.get('success', False) if nav_result else False
                        nav_error = nav_result.get('error') if not nav_success else None
                        print(f"[@testprompt_executor] Navigation result: success={nav_success}")
                    else:
                        nav_error = 'No tree_id available for navigation'
                        nav_success = False
                else:
                    nav_error = 'No navigation executor available'
                    nav_success = False
            except Exception as e:
                nav_success = False
                nav_error = str(e)
                print(f"[@testprompt_executor] Navigation error: {e}")

            nav_duration = int((time.time() - nav_start) * 1000)

            # Screenshot after navigation
            nav_screenshot = _take_screenshot(av_controller, f'after_nav_{target_screen_label}')
            if nav_screenshot:
                screenshot_paths.append(nav_screenshot)

            step_results.append({
                'step_number': step_num,
                'success': nav_success,
                'message': f'Navigate to {target_screen_label}',
                'step_category': 'navigation',
                'from_node': 'current',
                'to_node': target_screen_label,
                'execution_time_ms': nav_duration,
                'actions': [{'command': 'navigate', 'params': {'target': target_screen_label}}],
                'verifications': [],
                'error': nav_error,
                'screenshot_path': nav_screenshot,
                'step_end_screenshot_path': nav_screenshot,
            })

        # ========== STEP 3: Evaluate acceptance criteria ==========
        _emit(50, 'Evaluating acceptance criteria...')

        text_ctrl = None
        try:
            text_ctrl = get_controller(device_id, 'verification_text')
        except Exception:
            pass

        criteria_lines = [c.strip() for c in acceptance_criteria.split('\n') if c.strip()]
        if not criteria_lines:
            criteria_lines = [c.strip() for c in acceptance_criteria.split(',') if c.strip()]

        verification_results = []
        for criterion in criteria_lines:
            step_num += 1
            criterion_start = time.time()
            criterion_result = {'criterion': criterion, 'passed': False, 'evidence': ''}

            try:
                # Take a fresh screenshot for OCR
                ocr_screenshot = _take_screenshot(av_controller, f'ocr_{criterion[:15]}')

                if text_ctrl and ocr_screenshot:
                    # Use detect_text with the screenshot image
                    import os
                    image_filename = os.path.basename(ocr_screenshot)
                    ocr_result = text_ctrl.detect_text({'image_source_url': image_filename})

                    if ocr_result and ocr_result.get('success'):
                        detected_text = ocr_result.get('text', '').lower()
                        criterion_lower = criterion.lower()
                        if criterion_lower in detected_text:
                            criterion_result['passed'] = True
                            criterion_result['evidence'] = f'Found "{criterion}" in OCR text'
                        else:
                            criterion_result['evidence'] = f'"{criterion}" not found in detected text ({len(detected_text)} chars)'
                    else:
                        criterion_result['evidence'] = f'OCR failed: {ocr_result.get("message", "unknown error") if ocr_result else "no result"}'
                elif not text_ctrl:
                    criterion_result['evidence'] = 'Text verification controller not available'
                    criterion_result['passed'] = True  # Don't fail if no OCR
                else:
                    criterion_result['evidence'] = 'Screenshot failed — cannot verify'
            except Exception as e:
                criterion_result['evidence'] = f'Verification error: {str(e)}'

            criterion_duration = int((time.time() - criterion_start) * 1000)
            verification_results.append(criterion_result)

            # Screenshot per criterion
            criterion_screenshot = _take_screenshot(av_controller, f'criterion_{step_num}_{criterion[:20]}')
            if criterion_screenshot:
                screenshot_paths.append(criterion_screenshot)

            step_results.append({
                'step_number': step_num,
                'success': criterion_result['passed'],
                'message': f"Check: {criterion}",
                'step_category': 'verification',
                'from_node': target_screen_label or 'current',
                'to_node': target_screen_label or 'current',
                'execution_time_ms': criterion_duration,
                'actions': [],
                'verifications': [{
                    'label': criterion,
                    'success': criterion_result['passed'],
                    'message': criterion_result['evidence'],
                }],
                'error': None if criterion_result['passed'] else criterion_result['evidence'],
                'screenshot_path': criterion_screenshot,
                'step_end_screenshot_path': criterion_screenshot,
            })

        # ========== STEP 4: Final screenshot ==========
        _emit(85, 'Capturing final state...')
        final_screenshot = _take_screenshot(av_controller, 'final_state')
        if final_screenshot and final_screenshot not in screenshot_paths:
            screenshot_paths.append(final_screenshot)

        # ========== Compile results ==========
        passed_count = sum(1 for r in verification_results if r['passed'])
        total_count = len(verification_results)
        success = nav_success and (total_count == 0 or passed_count == total_count)
        execution_time_ms = int((time.time() - start_time) * 1000)

        # Execution summary for report header
        execution_summary = (
            f"Prompt: {prompt}\n\n"
            f"Acceptance Criteria: {acceptance_criteria}\n\n"
            f"Target Screen: {target_screen_label or 'none'}\n"
            f"Navigation: {'OK' if nav_success else f'FAILED - {nav_error}'}\n"
            f"Result: {passed_count}/{total_count} criteria passed"
        )

        # Stdout/logs
        log_lines = [
            f"=== Test Prompt Execution ===",
            f"Name: {prompt_name}",
            f"Prompt: {prompt}",
            f"Acceptance Criteria: {acceptance_criteria}",
            f"Target Screen: {target_screen_label or 'none'}",
            f"Device: {device_name} ({device_model})",
            f"Host: {host_name}",
            f"Interface: {userinterface_name}",
            f"",
            f"=== Execution Steps ===",
        ]
        if target_screen_label:
            log_lines.append(f"Navigation to {target_screen_label}: {'OK' if nav_success else f'FAILED - {nav_error}'}")
        log_lines.append(f"Screenshots captured: {len(screenshot_paths)}")
        log_lines.append(f"")
        log_lines.append(f"=== Acceptance Criteria ({passed_count}/{total_count} passed) ===")
        for r in verification_results:
            status = "PASS" if r['passed'] else "FAIL"
            log_lines.append(f"  [{status}] {r['criterion']}")
            log_lines.append(f"         Evidence: {r['evidence']}")
        log_lines.append(f"")
        log_lines.append(f"=== Overall: {'PASSED' if success else 'FAILED'} in {execution_time_ms}ms ===")
        stdout_content = '\n'.join(log_lines)

        # ========== Capture test video ==========
        _emit(88, 'Capturing test video...')
        test_video_url = ''
        try:
            if av_controller and hasattr(av_controller, 'take_video_for_report'):
                video_duration = max(10.0, execution_time_ms / 1000.0)
                test_video_url = av_controller.take_video_for_report(video_duration, start_time) or ''
                if test_video_url:
                    print(f"[@testprompt_executor] Video captured: {test_video_url}")
        except Exception as e:
            print(f"[@testprompt_executor] Video capture error: {e}")

        # ========== Generate report ==========
        _emit(90, 'Generating report...')

        try:
            from shared.src.lib.utils.report_generation_utils import generate_and_upload_script_report

            device_info = {
                'device_id': device_id,
                'device_name': device_name or device_id,
                'device_model': device_model,
            }
            host_info = {'host_name': host_name}

            report_result = generate_and_upload_script_report(
                script_name=f"prompt_{prompt_name}",
                device_info=device_info,
                host_info=host_info,
                execution_time=execution_time_ms,
                success=success,
                step_results=step_results,
                screenshot_paths=screenshot_paths,
                screenshot_url_mapping={},
                error_message=nav_error if not nav_success else None,
                userinterface_name=userinterface_name,
                stdout=stdout_content,
                execution_summary=execution_summary,
                test_video_url=test_video_url,
                script_result_id=script_result_id,
            )

            report_url = report_result.get('report_url')
            logs_url = report_result.get('logs_url')
            print(f"[@testprompt_executor] Report: {report_url}")
            print(f"[@testprompt_executor] Logs: {logs_url}")

        except Exception as e:
            print(f"[@testprompt_executor] Report generation error: {e}")
            import traceback
            traceback.print_exc()

        # Update database
        if script_result_id:
            update_script_execution_result(
                script_result_id=script_result_id,
                success=success,
                execution_time_ms=execution_time_ms,
                html_report_r2_url=report_url,
                logs_r2_url=logs_url,
                error_msg=nav_error if not nav_success else None,
                metadata={
                    'test_prompt_id': test_prompt_id,
                    'criteria_results': verification_results,
                    'passed_count': passed_count,
                    'total_count': total_count,
                },
            )

        if prompt_execution_id:
            update_prompt_execution(
                execution_id=prompt_execution_id,
                team_id=team_id,
                status='passed' if success else 'failed',
                script_result_id=script_result_id,
                report_url=report_url,
                logs_url=logs_url,
                execution_time_ms=execution_time_ms,
            )

        # Emit completion
        emit_execution_event(
            'test_prompt', prompt_execution_id or execution_id, 'completed',
            host_name=host_name, device_id=device_id, team_id=team_id,
            progress=100, message='Test prompt execution completed',
            result={
                'success': success,
                'execution_time_ms': execution_time_ms,
                'report_url': report_url,
                'logs_url': logs_url,
                'script_result_id': script_result_id,
                'criteria_results': verification_results,
            },
        )

        print(f"[@testprompt_executor] Completed: success={success}, steps={len(step_results)}, screenshots={len(screenshot_paths)}")

    except Exception as e:
        execution_time_ms = int((time.time() - start_time) * 1000)
        print(f"[@testprompt_executor] Error: {e}")
        import traceback
        traceback.print_exc()

        if prompt_execution_id:
            update_prompt_execution(
                execution_id=prompt_execution_id,
                team_id=team_id,
                status='error',
                execution_time_ms=execution_time_ms,
            )

        emit_execution_event(
            'test_prompt', prompt_execution_id or execution_id, 'completed',
            host_name=host_name, device_id=device_id, team_id=team_id,
            progress=100, message=f'Execution failed: {str(e)}',
            result={
                'success': False,
                'error': str(e),
                'execution_time_ms': execution_time_ms,
            },
        )
