"""
AI Queue Status Routes

Provides queue monitoring endpoints that directly query Redis
without requiring the backend_discard service to be running.
"""

import os
import json
import requests
from datetime import datetime, timezone, timedelta
from flask import Blueprint, jsonify, request
from backend_server.src.lib.utils.route_handlers import handle_route_exceptions

from shared.src.lib.utils.redis_queue import get_queue_processor
from shared.src.lib.utils.supabase_utils import get_supabase_client

# Create blueprint
server_ai_queue_bp = Blueprint('server_ai_queue', __name__, url_prefix='/server/ai-queue')

def get_redis_queue_lengths():
    """Get queue lengths using RedisQueueProcessor (supports both Upstash and local Redis)"""
    queue_processor = get_queue_processor()
    return queue_processor.get_all_queue_lengths()

def clear_redis_queue(queue_name):
    """Clear a specific queue in Redis using RedisQueueProcessor"""
    queue_processor = get_queue_processor()
    return queue_processor.clear_queue(queue_name)

def peek_redis_queue(queue_name, limit=50):
    """Peek at items in a Redis queue without removing them using RedisQueueProcessor"""
    queue_processor = get_queue_processor()
    return queue_processor.peek_queue(queue_name, limit)


def _get_24h_analysis_summary(team_id=None):
    """Get last 24h AI analysis summary for scripts and incidents."""
    since = datetime.now(timezone.utc) - timedelta(hours=24)
    since_iso = since.isoformat()
    now_iso = datetime.now(timezone.utc).isoformat()
    summary = {
        'window_hours': 24,
        'since': since_iso,
        'until': now_iso,
        'scripts': {
            'analyzed': 0,
            'discarded': 0,
            'kept': 0,
            'last_analyzed': None
        },
        'incidents': {
            'analyzed': 0,
            'discarded': 0,
            'kept': 0,
            'last_analyzed': None
        }
    }

    try:
        supabase = get_supabase_client()
        if not supabase:
            return summary

        scripts_base = supabase.table('script_results').select('id', count='exact').eq('checked', True).gte('updated_at', since_iso)
        if team_id:
            scripts_base = scripts_base.eq('team_id', team_id)

        scripts_analyzed = scripts_base.limit(1).execute()
        summary['scripts']['analyzed'] = scripts_analyzed.count or 0

        scripts_discarded_query = supabase.table('script_results').select('id', count='exact').eq('checked', True).eq('discard', True).gte('updated_at', since_iso)
        if team_id:
            scripts_discarded_query = scripts_discarded_query.eq('team_id', team_id)
        scripts_discarded = scripts_discarded_query.limit(1).execute()
        summary['scripts']['discarded'] = scripts_discarded.count or 0
        summary['scripts']['kept'] = max(0, summary['scripts']['analyzed'] - summary['scripts']['discarded'])

        scripts_all_query = supabase.table('script_results').select(
            'id,script_name,success,discard,check_type,discard_comment,updated_at'
        ).eq('checked', True).gte('updated_at', since_iso)
        if team_id:
            scripts_all_query = scripts_all_query.eq('team_id', team_id)
        scripts_all = scripts_all_query.order('updated_at', desc=True).limit(200).execute()
        if scripts_all.data:
            summary['scripts']['last_analyzed'] = scripts_all.data[0]
            summary['scripts']['items'] = scripts_all.data

        incidents_analyzed = supabase.table('alerts').select('id', count='exact').eq('checked', True).gte('updated_at', since_iso).limit(1).execute()
        summary['incidents']['analyzed'] = incidents_analyzed.count or 0

        incidents_discarded = supabase.table('alerts').select('id', count='exact').eq('checked', True).eq('discard', True).gte('updated_at', since_iso).limit(1).execute()
        summary['incidents']['discarded'] = incidents_discarded.count or 0
        summary['incidents']['kept'] = max(0, summary['incidents']['analyzed'] - summary['incidents']['discarded'])

        incidents_all = supabase.table('alerts').select(
            'id,incident_type,status,discard,check_type,discard_comment,updated_at,host_name,device_id'
        ).eq('checked', True).gte('updated_at', since_iso).order('updated_at', desc=True).limit(200).execute()
        if incidents_all.data:
            summary['incidents']['last_analyzed'] = incidents_all.data[0]
            summary['incidents']['items'] = incidents_all.data

    except Exception as e:
        summary['error'] = str(e)

    return summary


@server_ai_queue_bp.route('/status', methods=['GET'])
@handle_route_exceptions('ai_queue:get_ai_queue_status')
def get_ai_queue_status():
    """Get AI queue status with lengths and basic stats"""
    queue_lengths = get_redis_queue_lengths()
    include_items = request.args.get('include_items', 'false').lower() == 'true'
    team_id = request.args.get('team_id')
    
    if queue_lengths is None:
        return jsonify({
            'status': 'error',
            'error': 'Could not connect to Redis',
            'queues': {
                'incidents': {'name': 'Incidents', 'length': 0, 'processed': 0, 'discarded': 0, 'validated': 0, 'items': []},
                'scripts': {'name': 'Scripts', 'length': 0, 'processed': 0, 'discarded': 0, 'validated': 0, 'items': []}
            }
        }), 500
    
    # Get queue items if requested
    incidents_items = peek_redis_queue('p1_alerts', 50) if include_items else []
    scripts_items = peek_redis_queue('p2_scripts', 50) if include_items else []
    analysis_24h = _get_24h_analysis_summary(team_id=team_id)
    
    return jsonify({
        'status': 'healthy',
        'service': 'ai_queue_monitor',
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'stats': {
            'service_running': False,  # backend_discard not required for queue monitoring
            'redis_connected': True
        },
        'analysis_24h': analysis_24h,
        'queues': {
            'incidents': {
                'name': 'Incidents',
                'length': queue_lengths.get('p1_alerts', 0),
                'processed': 0,  # Would need backend_discard stats for this
                'discarded': 0,
                'validated': 0,
                'items': incidents_items
            },
            'scripts': {
                'name': 'Scripts', 
                'length': queue_lengths.get('p2_scripts', 0),
                'processed': 0,
                'discarded': 0,
                'validated': 0,
                'items': scripts_items
            }
        }
    })
    
@server_ai_queue_bp.route('/clear', methods=['POST'])
@handle_route_exceptions('ai_queue:clear_queues')
def clear_queues():
    """Clear AI processing queues"""
    data = request.json if request.json else {}
    queue_type = data.get('queue_type', 'all')  # 'incidents', 'scripts', or 'all'
    
    results = {}
    
    if queue_type in ['incidents', 'all']:
        results['incidents'] = clear_redis_queue('p1_alerts')
        
    if queue_type in ['scripts', 'all']:
        results['scripts'] = clear_redis_queue('p2_scripts')
        
    if queue_type == 'all':
        results['reserved'] = clear_redis_queue('p3_reserved')
    
    success = all(results.values())
    
    return jsonify({
        'status': 'success' if success else 'partial_failure',
        'cleared': results,
        'message': f'Queue clearing {"completed" if success else "completed with some failures"}'
    })
    
