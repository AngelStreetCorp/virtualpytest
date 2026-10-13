"""
Transcript Tools - Audio transcript retrieval

Reads the Whisper transcript a host's vpt-transcript service wrote for a device, and says
why it is empty when it is (service off, transcription disabled, no audio, silence, no
speech, or a real failure). Server -> host goes through the auto proxy
(/server/transcript/status -> /host/transcript/status, call_host()).
"""

import json
from typing import Dict, Any
from ..utils.api_client import MCPAPIClient
from ..utils.mcp_formatter import MCPFormatter
from shared.src.lib.config.constants import get_team_id


class TranscriptTools:
    """Audio transcript retrieval tools"""

    def __init__(self, api_client: MCPAPIClient):
        self.api = api_client
        self.formatter = MCPFormatter()

    def get_transcript(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Get the audio transcript of a device (what was said on screen) for a time window, and WHY it is empty when it is.

        Window: the last `minutes` (default 10, max 120), or `hour` (0-23, local host time) with optional `chunk_index` (0-5 = 10-minute block) for its most recent occurrence. The transcript lags ~1-2 min behind live.

        Returns a summary line plus a JSON block with: status (ok | unavailable | empty | error), reason (transcribed | service_inactive | transcription_disabled | no_audio_stream | silent_audio | no_speech | no_audio_recorded | processing_pending | audio_status_missing | audio_check_stale | transcription_mode_unknown | mp3_missing | transcript_missing | host_not_found | host_unreachable | request_failed), message, transcription_enabled, service_active, audio {present, mean_volume_db, age_s}, window, language, segments [{time, text}], text.
        Only status=error is a fault worth reporting; 'unavailable' means the host is not set up to transcribe, 'empty' means there was nothing to transcribe.

        Example: get_transcript(device_id='device4', host_name='vpt-pi3', minutes=5)

        Args:
            params: {
                'device_id': str (REQUIRED - device identifier, e.g. device1),
                'host_name': str (REQUIRED - host the device is connected to),
                'minutes': int (OPTIONAL - window back from now, 1-120, default 10),
                'hour': int (OPTIONAL - hour of day 0-23 instead of minutes; most recent occurrence),
                'chunk_index': int (OPTIONAL - 10-minute block 0-5 within hour; needs hour)
            }

        Returns:
            Summary text + JSON payload with status, reason, message, segments and text
        """
        device_id = params.get('device_id')
        host_name = params.get('host_name')
        if not device_id or not host_name:
            return {"content": [{"type": "text", "text": "Error: device_id and host_name are required"}], "isError": True}
        if params.get('chunk_index') is not None and params.get('hour') is None:
            return {"content": [{"type": "text", "text": "Error: chunk_index needs hour"}], "isError": True}

        query = {'host_name': host_name, 'device_id': device_id, 'team_id': params.get('team_id', get_team_id())}
        for key in ('minutes', 'hour', 'chunk_index'):
            if params.get(key) is not None:
                query[key] = params[key]

        result = self.api.get('/server/transcript/status', params=query)

        if not isinstance(result, dict) or 'status' not in result:
            error = (result or {}).get('error') if isinstance(result, dict) else str(result)
            text = str(error).lower()
            if 'host' in text and 'not found' in text:
                reason = 'host_not_found'
            elif isinstance(result, dict) and (result.get('network_error') or result.get('timeout')
                                               or result.get('status_code') in (502, 503, 504)
                                               or 'connect' in text or 'timeout' in text):
                reason = 'host_unreachable'
            else:
                reason = 'request_failed'
            payload = {
                'status': 'error',
                'reason': reason,
                'message': f"Could not read the transcript from {host_name}/{device_id}: {error}",
                'device_id': device_id,
                'host_name': host_name,
            }
            return {"content": [{"type": "text", "text": f"{payload['message']}\n{json.dumps(payload)}"}],
                    "isError": True}

        result.pop('success', None)
        result['host_name'] = host_name
        summary = f"[{result['status']}/{result['reason']}] {result.get('message', '')}"
        if result.get('text'):
            summary += f"\n\nTranscript:\n{result['text']}"
        payload = json.dumps(result, default=str)
        if result['status'] == 'error':
            # The MCP server keeps only the first text block of an error result.
            return {"content": [{"type": "text", "text": f"{summary}\n{payload}"}], "isError": True}
        return {"content": [{"type": "text", "text": summary}, {"type": "text", "text": payload}], "isError": False}
