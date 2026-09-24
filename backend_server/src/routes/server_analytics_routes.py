"""
Monitoring > Analytics Routes

One route per tab section, deliberately NOT one fat /summary. The page is tabbed so
that opening it costs one cheap section instead of six, and a combined endpoint would
throw that away — in particular it would make every page load pay for the Devices
tab's availability rollup, which is the single expensive aggregate here.

Each section is served through `analytics_cache`, which serves stale values instantly
and refreshes behind the request, and which a background loop keeps warm from boot.
See backend_server/src/lib/utils/section_cache.py for why that beats a plain TTL.
"""

import os
from datetime import datetime, timezone

from flask import Blueprint, jsonify, request

from shared.src.lib.database.analytics_db import (
    get_alerts_section,
    get_devices_section,
    get_incidents_section,
    get_kpi_section,
    get_overview_section,
    get_system_section,
)
from shared.src.lib.utils.app_utils import check_supabase
from backend_server.src.lib.utils.route_handlers import handle_route_exceptions
from backend_server.src.lib.utils.section_cache import analytics_cache

server_analytics_bp = Blueprint('server_analytics', __name__, url_prefix='/server/analytics')


# How long each section's value stays fresh, and how long it may still be served
# stale while a refresh runs behind the caller.
#
# The split is by what the numbers MEAN, not by what they cost. 'overview', 'system'
# and 'devices' carry live up/down state, so they go stale in 30s. The rest are daily
# buckets — a five-minute-old answer to "how many incidents on the 3rd" is the same
# answer, so refreshing faster would be pure waste.
_SECTIONS = {
    'overview':  (lambda team_id: get_overview_section(team_id=team_id), 30,  600),
    'system':    (lambda team_id: get_system_section(),                  30,  600),
    'devices':   (lambda team_id: get_devices_section(),                 30,  600),
    'incidents': (lambda team_id: get_incidents_section(),               300, 3600),
    'alerts':    (lambda team_id: get_alerts_section(),                  300, 3600),
    'kpi':       (lambda team_id: get_kpi_section(team_id=team_id),      300, 3600),
}

for _name, (_loader, _fresh, _stale) in _SECTIONS.items():
    analytics_cache.register(_name, _loader, fresh=_fresh, stale=_stale)


def start_analytics_prewarm():
    """Keep every section warm from boot, so even the first request is a dict lookup.

    Called from app.py after the blueprints are registered. Opt out with
    ANALYTICS_PREWARM=false (useful for a local run that should not talk to the DB
    until asked).
    """
    if (os.getenv('ANALYTICS_PREWARM', 'true') or '').strip().lower() in ('false', '0', 'no'):
        print('[@route:analytics] pre-warm disabled by ANALYTICS_PREWARM')
        return
    team_id = (os.getenv('DEFAULT_TEAM_ID') or '').strip() or None
    analytics_cache.start_prewarm(team_id=team_id, interval=30.0)


@server_analytics_bp.route('/_cache', methods=['GET'])
@handle_route_exceptions('server_analytics:_cache')
def cache_stats():
    """Cache state — which sections are warm, how old, and whether one is failing.

    Registered before the <section> rule so '_cache' is never read as a section name.
    """
    return jsonify({'success': True, **analytics_cache.stats()})


@server_analytics_bp.route('/<section>', methods=['GET'])
@handle_route_exceptions('server_analytics:section')
def get_section(section):
    """Return one section's payload.

    An unknown section answers 404 rather than falling through: the auto_proxy
    blueprint catches unmatched /server/* paths and would try to proxy it to a host.
    """
    supabase_error = check_supabase()
    if supabase_error:
        return supabase_error

    team_id = request.args.get('team_id')

    try:
        data, age_state = analytics_cache.get(section, team_id=team_id)
    except KeyError:
        return jsonify({
            'success': False,
            'error': f"Unknown analytics section '{section}'",
            'sections': analytics_cache.sections(),
        }), 404

    response = jsonify({
        'success': True,
        'section': section,
        'cache': age_state,
        'generated_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'data': data,
    })
    # Let the browser and any proxy in front of us hold it too. max-age matches the
    # shortest 'fresh' window; the SWR window lets a reload repaint instantly.
    response.headers['Cache-Control'] = 'private, max-age=30, stale-while-revalidate=300'
    return response
