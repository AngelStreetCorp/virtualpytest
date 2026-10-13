#!/usr/bin/env python3
"""
Capture a screenshot for every screen node of a navigation tree.

For each selected node the script navigates there (same NavigationExecutor
path as goto.py), lets the screen settle, captures the device screen through
the AV controller, uploads it to R2 under navigation/<userinterface>/<label>.jpg
(same object the editor's camera button writes) and stores the URL on the
node's data.screenshot so the Navigation editor shows it as the node thumbnail.

Every argument is a flag. Nodes are visited in tree order unless --nodes is given.

Usage:
    python test_scripts/capture_node_screenshots.py --userinterface <name> [--device <device_id>]
                                                    [--nodes home,search_results] [--overwrite true|false]
                                                    [--settle_ms 1500] [--verify end|each|auto]

Examples:
    python test_scripts/capture_node_screenshots.py --userinterface youtube-web --device host
    python test_scripts/capture_node_screenshots.py --userinterface youtube-web --device host --nodes shorts,video_player
    python test_scripts/capture_node_screenshots.py --userinterface example_androidtv --overwrite false   # only nodes without one

Docs: docs/agent/navigation/NODE_SCREENSHOTS.md
"""

import asyncio
import os
import re
import sys
import time

# Add project root to path
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from shared.src.lib.executors.script_decorators import script, get_context, get_args, get_device

# Node types that represent a screen worth a thumbnail. `entry` is the virtual
# entry point and `action` nodes are transient, so neither gets a screenshot.
SCREEN_NODE_TYPES = ('screen', 'menu')


def _sanitize_filename(label: str) -> str:
    """Same rule as the editor (useNode.takeAndSaveScreenshot) and the MCP tool."""
    name = re.sub(r'\s+', '_', label)
    return re.sub(r'[^a-zA-Z0-9_-]', '', name)


def _node_type(node: dict) -> str:
    return (node.get('node_type') or (node.get('data') or {}).get('type') or '').lower()


def _node_label(node: dict) -> str:
    return node.get('label') or (node.get('data') or {}).get('label') or node.get('node_id')


def _select_nodes(nodes: list, requested: str, overwrite: bool) -> tuple:
    """Return (selected, skipped) where skipped is a list of (label, reason)."""
    selected, skipped = [], []
    wanted = [w.strip() for w in requested.split(',') if w.strip()] if requested else None

    for node in nodes:
        label = _node_label(node)
        node_type = _node_type(node)
        if wanted is not None:
            if label not in wanted and node.get('node_id') not in wanted:
                continue
        elif node_type not in SCREEN_NODE_TYPES:
            skipped.append((label, f"type '{node_type or 'unknown'}' has no screen"))
            continue
        if not overwrite and (node.get('data') or {}).get('screenshot'):
            skipped.append((label, 'already has a screenshot (overwrite=false)'))
            continue
        selected.append(node)

    if wanted is not None:
        found = {_node_label(n) for n in selected} | {n.get('node_id') for n in selected}
        for name in wanted:
            if name not in found:
                skipped.append((name, 'not found in tree'))
    return selected, skipped


def _capture_and_store(device, context, tree_id: str, node: dict, userinterface_name: str) -> str:
    """Capture the current screen, upload it and store the URL on the node. Returns the URL."""
    from shared.src.lib.utils.cloudflare_utils import upload_navigation_screenshot
    from shared.src.lib.database.navigation_trees_db import get_node_by_id, save_node

    label = _node_label(node)
    filename = _sanitize_filename(label)

    av_controller = device._get_controller('av')
    if not av_controller:
        raise RuntimeError('device has no AV controller')
    local_path = av_controller.save_screenshot(filename)
    if not local_path:
        raise RuntimeError('AV controller returned no screenshot')

    upload = upload_navigation_screenshot(local_path, userinterface_name, f"{filename}.jpg")
    if not upload.get('success') or not upload.get('url'):
        raise RuntimeError(f"upload failed: {upload.get('error', 'no url returned')}")
    url = upload['url']

    # Localize fingerprint (dHash + focus), best effort exactly like /host/av/saveScreenshot.
    fingerprint = None
    try:
        import cv2
        from backend_host.src.controllers.verification.image_helpers import ImageHelpers
        fingerprint = ImageHelpers(None, av_controller).compute_fingerprint(cv2.imread(local_path))
    except Exception as fp_err:
        print(f"⚠️ [capture_node_screenshots] fingerprint failed for {label} (non-fatal): {fp_err}")

    current = get_node_by_id(tree_id, node['node_id'], context.team_id)
    if not current.get('success'):
        raise RuntimeError(f"node read failed: {current.get('error')}")
    data = (current.get('node') or {}).get('data') or {}
    data['screenshot'] = url
    data['screenshot_timestamp'] = int(time.time() * 1000)
    if fingerprint is not None:
        data['fingerprint'] = fingerprint

    saved = save_node(tree_id, {'node_id': node['node_id'], 'data': data}, context.team_id)
    if not saved.get('success'):
        raise RuntimeError(f"node save failed: {saved.get('error')}")
    return url


def _summary(context, userinterface_name: str, results: list, skipped: list) -> str:
    lines = ["📸 [CAPTURE_NODE_SCREENSHOTS] EXECUTION SUMMARY"]
    if context.selected_device:
        lines.append(f"📱 Device: {context.selected_device.device_name} ({context.selected_device.device_model})")
    if context.host:
        lines.append(f"🖥️ Host: {context.host.host_name}")
    lines.append(f"📋 Interface: {userinterface_name}")
    ok = [r for r in results if r[1] == 'ok']
    lines.append(f"✅ Captured: {len(ok)}/{len(results)} nodes")
    for label, status, detail in results:
        icon = '✅' if status == 'ok' else '❌'
        lines.append(f"   {icon} {label}: {detail}")
    for label, reason in skipped:
        lines.append(f"   ⏭️ {label}: skipped, {reason}")
    lines.append(f"⏱️ Total Time: {context.get_execution_time_ms()/1000:.1f}s")
    lines.append(f"🎯 Result: {'SUCCESS' if context.overall_success else 'FAILED'}")
    if context.error_message:
        lines.append(f"❌ Error: {context.error_message}")
    return "\n".join(lines)


@script("capture_node_screenshots", "Capture a screenshot for every screen node", default_device="device1")
def main():
    args = get_args()
    context = get_context()
    device = get_device()
    userinterface_name = args.userinterface
    results, skipped = [], []
    print(f"📸 [capture_node_screenshots] Interface: {userinterface_name}, device: {device.device_name} ({device.device_model})")

    try:
        nav_result = device.navigation_executor.load_navigation_tree(userinterface_name, context.team_id)
        if not nav_result['success']:
            context.error_message = f"Navigation tree loading failed: {nav_result.get('error', 'Unknown error')}"
            context.overall_success = False
            return False
        context.tree_id = nav_result['tree_id']

        from shared.src.lib.database.navigation_trees_db import get_tree_nodes
        nodes_result = get_tree_nodes(context.tree_id, context.team_id)
        if not nodes_result.get('success'):
            context.error_message = f"Could not list nodes: {nodes_result.get('error')}"
            context.overall_success = False
            return False

        selected, skipped = _select_nodes(nodes_result['nodes'], args.nodes, args.overwrite)
        print(f"📸 [capture_node_screenshots] {len(selected)} node(s) to capture: {[_node_label(n) for n in selected]}")
        if not selected:
            context.error_message = 'No node selected (check --nodes / --overwrite)'
            context.overall_success = False
            return False

        verification_mode = (args.verify or 'end').strip().lower()
        if verification_mode not in ('end', 'each', 'auto'):
            verification_mode = 'end'

        for node in selected:
            label = _node_label(node)
            print(f"\n🎯 [capture_node_screenshots] → {label}")
            nav = asyncio.run(device.navigation_executor.execute_navigation(
                tree_id=context.tree_id,
                userinterface_name=context.userinterface,
                target_node_label=label,
                team_id=context.team_id,
                context=context,
                verification_mode=verification_mode,
            ))
            if not nav.get('success', False):
                results.append((label, 'failed', f"navigation failed: {nav.get('error', 'unknown')}"))
                print(f"❌ [capture_node_screenshots] {label}: navigation failed")
                continue

            time.sleep(max(args.settle_ms, 0) / 1000.0)
            try:
                url = _capture_and_store(device, context, context.tree_id, node, userinterface_name)
                results.append((label, 'ok', url.split('?')[0]))
                print(f"✅ [capture_node_screenshots] {label}: {url.split('?')[0]}")
            except Exception as capture_err:
                results.append((label, 'failed', str(capture_err)))
                print(f"❌ [capture_node_screenshots] {label}: {capture_err}")

        failed = [r for r in results if r[1] != 'ok']
        context.overall_success = not failed
        if failed:
            context.error_message = f"{len(failed)} node(s) failed: {', '.join(r[0] for r in failed)}"
        return context.overall_success
    finally:
        context.execution_summary = _summary(context, userinterface_name, results, skipped)


main._script_args = [
    '--userinterface:str:example_mobile',   # Framework param with default
    '--nodes:str:',                          # Comma-separated labels/ids; empty = every screen/menu node
    '--overwrite:bool:true',                 # false = only nodes that have no screenshot yet
    '--settle_ms:int:1500',                  # Wait after arriving before the capture
    '--verify:str:end:end|each|auto',        # Verification mode for the navigation
]
main._script_description = "Navigate to every screen node and store a screenshot on it (editor thumbnails)."
main._arg_descriptions = {
    'userinterface': 'UI interface name',
    'nodes': 'Comma-separated node labels (or ids) to capture; empty = all screen and menu nodes',
    'overwrite': 'true (default) recaptures nodes that already have a screenshot; false skips them',
    'settle_ms': 'Milliseconds to wait after navigation before capturing (default 1500)',
    'verify': "Verification mode: 'end' (default), 'each', or 'auto'",
}
main._target_rules = {
    "target_type": "device",
    "host_os": "all",
    "device_model": "all",
}

if __name__ == "__main__":
    main()
