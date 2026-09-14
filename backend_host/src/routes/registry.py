"""Blueprint registry for backend_host routes."""
import os

_HOST_TYPE = os.getenv('HOST_TYPE', '')
_IS_RUNNER = _HOST_TYPE.startswith('runner_')

from . import (
    host_control_routes,
    host_remote_routes,
    host_script_routes,
    host_system_routes,
    host_verification_adb_routes,
)

if not _IS_RUNNER:
    from . import (
        host_actions_routes,
        host_ai_disambiguation_routes,
        host_ai_exploration_routes,
        host_ai_routes,
        host_av_routes,
        host_builder_routes,
        host_campaign_routes,
        host_deployment_routes,
        host_desktop_bash_routes,
        host_desktop_pyautogui_routes,
        host_monitoring_routes,
        host_navigation_routes,
        host_power_routes,
        host_restart_routes,
        host_stream_routes,
        host_testcase_routes,
        host_translation_routes,
        host_transcript_routes,
        host_verification_appium_routes,
        host_verification_audio_routes,
        host_verification_image_routes,
        host_verification_routes,
        host_verification_text_routes,
        host_verification_video_routes,
        host_verification_web_routes,
        host_web_routes,
    )

# Runner: only the essentials for ADB script execution
_runner_registry = [
    (host_system_routes.host_system_bp, 'Host system control'),
    (host_control_routes.host_control_bp, 'Device control'),
    (host_script_routes.host_script_bp, 'Script execution'),
    (host_remote_routes.host_remote_bp, 'Remote device control'),
    (host_verification_adb_routes.host_verification_adb_bp, 'ADB verification'),
]

if _IS_RUNNER:
    blueprint_registry = _runner_registry
else:
    _full_registry = [
        (host_stream_routes.host_stream_bp, 'HLS Stream file serving'),
        (host_control_routes.host_control_bp, 'Device control'),
        (host_web_routes.host_web_bp, 'Web automation'),
        (host_verification_routes.host_verification_bp, 'Verification services'),
        (host_power_routes.host_power_bp, 'Power control'),
        (host_av_routes.host_av_bp, 'Audio/Video operations'),
        (host_restart_routes.host_restart_bp, 'Restart video system'),
        (host_system_routes.host_system_bp, 'Host system control'),
        (host_translation_routes.host_translation_bp, 'Translation services'),
        (host_monitoring_routes.host_monitoring_bp, 'Monitoring system'),
        (host_remote_routes.host_remote_bp, 'Remote device control'),
        (host_desktop_bash_routes.host_desktop_bash_bp, 'Bash desktop control'),
        (host_desktop_pyautogui_routes.host_desktop_pyautogui_bp, 'PyAutoGUI desktop control'),
        (host_script_routes.host_script_bp, 'Script execution'),
        (host_verification_appium_routes.host_verification_appium_bp, 'Appium verification'),
        (host_verification_text_routes.host_verification_text_bp, 'Text verification'),
        (host_verification_audio_routes.host_verification_audio_bp, 'Audio verification'),
        (host_verification_adb_routes.host_verification_adb_bp, 'ADB verification'),
        (host_verification_image_routes.host_verification_image_bp, 'Image verification'),
        (host_verification_video_routes.host_verification_video_bp, 'Video verification'),
        (host_verification_web_routes.host_verification_web_bp, 'Web verification'),
        (host_actions_routes.host_actions_bp, 'Action execution'),
        (host_navigation_routes.host_navigation_bp, 'Navigation execution'),
        (host_ai_routes.host_ai_bp, 'AI execution'),
        (host_ai_disambiguation_routes.host_ai_disambiguation_bp, 'AI disambiguation'),
        (host_testcase_routes.host_testcase_bp, 'TestCase Builder'),
        (host_campaign_routes.host_campaign_bp, 'Campaign execution'),
        (host_transcript_routes.host_transcript_bp, 'Transcript services'),
        (host_deployment_routes.host_deployment_bp, 'Deployment scheduling'),
        (host_builder_routes.host_builder_bp, 'Standard blocks'),
        (host_ai_exploration_routes.host_ai_exploration_bp, 'AI tree exploration'),
    ]
    blueprint_registry = _full_registry
