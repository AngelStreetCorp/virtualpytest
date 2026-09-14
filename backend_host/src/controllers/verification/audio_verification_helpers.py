"""
Audio Verification Logic Helpers

High-level verification workflow helpers for the AudioVerificationController:
1. Verification execution and orchestration
2. Configuration management and validation
3. Verification result formatting
4. Logging and tracking utilities
5. Status and capability reporting

This helper handles the business logic and workflow orchestration
for audio verification operations.
"""

import time
from datetime import datetime
from typing import Dict, Any, Optional, List, Tuple


class AudioVerificationHelpers:
    """High-level verification logic and workflow orchestration for audio."""

    def __init__(self, controller_instance, device_name: str = "AudioVerification"):
        """
        Initialize audio verification helpers.

        Args:
            controller_instance: Reference to the main AudioVerificationController
            device_name: Name for logging purposes
        """
        self.controller = controller_instance
        self.device_name = device_name
        self.verification_logs = []

    def log_verification(self, command: str, target: str, success: bool, details: Dict[str, Any] = None, duration: float = None):
        """
        Log a verification operation for tracking and analysis.

        Args:
            command: Verification command executed
            target: Target of the verification (e.g., threshold, frequency)
            success: Whether the verification succeeded
            details: Additional details about the verification
            duration: Duration of the verification in seconds
        """
        try:
            log_entry = {
                'timestamp': datetime.now().isoformat(),
                'command': command,
                'target': target,
                'success': success,
                'details': details or {},
                'duration': duration
            }

            self.verification_logs.append(log_entry)

            # Keep only the last 100 logs to prevent memory issues
            if len(self.verification_logs) > 100:
                self.verification_logs = self.verification_logs[-100:]

        except Exception as e:
            print(f"AudioVerification[{self.device_name}]: Logging error: {e}")

    def get_verification_history(self, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Get recent verification history.

        Args:
            limit: Maximum number of entries to return

        Returns:
            List of recent verification log entries
        """
        return self.verification_logs[-limit:] if self.verification_logs else []

    def get_controller_status(self) -> Dict[str, Any]:
        """
        Get comprehensive controller status information.

        Returns:
            Status dictionary with verification counts and capabilities
        """
        return {
            'controller_type': self.controller.controller_type,
            'device_name': self.controller.device_name,
            'connected': True,
            'session_id': self.controller.verification_session_id,
            'acquisition_source': self.controller.av_controller.device_name if self.controller.av_controller else None,
            'sample_rate': getattr(self.controller, 'sample_rate', '44100'),
            'channels': getattr(self.controller, 'channels', '2'),
            'capabilities': [
                'audio_level_detection', 'silence_detection', 'frequency_analysis',
                'audio_playback_verification', 'performance_metrics'
            ],
            'verification_logs_count': len(self.verification_logs)
        }

    def get_available_verifications(self) -> List[Dict[str, Any]]:
        """Get available verifications for audio controller with typed parameters."""
        from shared.src.lib.schemas.param_types import create_param, ParamType

        return [
            {
                'command': 'waitForAudioToAppear',
                'params': {
                    'min_level': create_param(
                        ParamType.NUMBER,
                        required=False,
                        default=10.0,
                        description="Minimum audio level to consider as playing",
                        min=0.0,
                        max=100.0
                    ),
                    'duration': create_param(
                        ParamType.NUMBER,
                        required=False,
                        default=2.0,
                        description="Duration to check for audio (seconds)",
                        min=0.1,
                        max=30.0
                    )
                },
                'verification_type': 'audio',
                'description': 'Wait for audio to start playing'
            },
            {
                'command': 'waitForAudioToDisappear',
                'params': {
                    'max_level': create_param(
                        ParamType.NUMBER,
                        required=False,
                        default=5.0,
                        description="Maximum audio level to consider as silent",
                        min=0.0,
                        max=100.0
                    ),
                    'duration': create_param(
                        ParamType.NUMBER,
                        required=False,
                        default=2.0,
                        description="Duration to check for silence (seconds)",
                        min=0.1,
                        max=30.0
                    )
                },
                'verification_type': 'audio',
                'description': 'Wait for audio to stop playing (inverse of appear)'
            }
        ]
