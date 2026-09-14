"""
Host Crawl Routes

BFS app crawling endpoint that uses web or ADB controllers to explore
and map all screens of an application.
"""

from flask import Blueprint, request, jsonify
from backend_host.src.lib.utils.host_utils import get_controller, get_host
from backend_host.src.lib.utils.route_request import get_json_payload, require_field
from backend_host.src.lib.utils.route_response import controller_not_found

host_crawl_bp = Blueprint('host_crawl', __name__, url_prefix='/host/crawl')


def _run_async(coro):
    """Run async coroutine using asyncio.run() — same pattern as host_web_routes."""
    import asyncio
    return asyncio.run(coro)


def _get_device_model(device_id: str) -> str:
    """Get device model for the given device_id."""
    host = get_host()
    if not host:
        return 'unknown'
    device = host.get_device(device_id or 'device1')
    if not device:
        return 'unknown'
    return device.device_model or 'unknown'


@host_crawl_bp.route('/app', methods=['POST'])
def crawl_app():
    """BFS crawl an app and return a structured site map."""
    try:
        data = get_json_payload()
        max_depth = data.get('max_depth', 2)
        max_pages = data.get('max_pages', 10)
        skip_patterns = data.get('skip_patterns', [])
        device_id = data.get('device_id')

        # Detect platform from device model
        device_model = _get_device_model(device_id)
        is_android = 'android' in device_model.lower()

        if is_android:
            return _crawl_android(data, device_id, device_model, max_depth, max_pages, skip_patterns)
        else:
            return _crawl_web(data, max_depth, max_pages, skip_patterns)

    except Exception as e:
        print(f"[@route:host_crawl:crawl_app] Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': f'Crawl error: {str(e)}'}), 500


def _crawl_web(data, max_depth, max_pages, skip_patterns):
    """Web crawl using Playwright controller."""
    url = data.get('url')
    if not url:
        return jsonify({'success': False, 'error': 'url is required for web crawl'}), 400

    web_controller = get_controller(None, 'web')
    if not web_controller:
        return controller_not_found('web', 'host')

    # Switch browser engine if requested (chromium recommended for login)
    requested_engine = data.get('browser_engine')
    if requested_engine and hasattr(web_controller, 'browser_engine'):
        current_engine = web_controller.browser_engine
        if requested_engine != current_engine:
            print(f"[@route:host_crawl:crawl_app] Switching browser engine: {current_engine} → {requested_engine}")
            web_controller.browser_engine = requested_engine
            # Force browser restart with new engine
            if hasattr(web_controller, '_reset_state'):
                web_controller._reset_state()

    username = data.get('username')
    password = data.get('password')
    engine = getattr(web_controller, 'browser_engine', 'unknown')
    print(f"[@route:host_crawl:crawl_app] Web BFS crawl: url={url}, engine={engine}, login={'yes' if username else 'no'}")

    from .app_crawler import WebAppCrawler
    crawler = WebAppCrawler(
        web_controller=web_controller,
        max_depth=max_depth, max_pages=max_pages, skip_patterns=skip_patterns,
        username=username, password=password,
    )
    result = _run_async(crawler.crawl(url))
    return jsonify(result)


def _crawl_android(data, device_id, device_model, max_depth, max_pages, skip_patterns):
    """Android crawl using ADB remote controller."""
    device_id = device_id or 'device1'
    app_package = data.get('app_package')

    # Get the remote controller (android_tv or android_mobile)
    remote_controller = get_controller(device_id, 'remote')
    if not remote_controller:
        return controller_not_found('remote', device_id)

    # Get ADB utils from the remote controller
    adb_utils = getattr(remote_controller, 'adb_utils', None)
    android_device_id = getattr(remote_controller, 'android_device_id', None)
    if not adb_utils or not android_device_id:
        return jsonify({
            'success': False,
            'error': 'ADB not available on this device'
        }), 500

    print(f"[@route:host_crawl:crawl_app] Android BFS crawl: device={device_id}, model={device_model}, adb_id={android_device_id}")

    from .app_crawler import AndroidAppCrawler
    crawler = AndroidAppCrawler(
        remote_controller=remote_controller,
        adb_utils=adb_utils,
        device_id=android_device_id,
        device_model=device_model,
        max_depth=max_depth, max_pages=max_pages, skip_patterns=skip_patterns,
    )
    result = crawler.crawl(app_package=app_package)
    return jsonify(result)
