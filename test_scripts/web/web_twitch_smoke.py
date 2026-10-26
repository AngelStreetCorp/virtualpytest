#!/usr/bin/env python3
"""Smoke test the `web-twitch` web navigation tree (TASK-161).

Walks every screen of the tree on a live browser and back again, two passes in a row:
entry -> each node (navigation + its own verifications) -> home. A pass that cannot reach a
node, cannot verify it, or cannot get back fails the run.

Usage:
    python test_scripts/web/web_twitch_smoke.py --local-debug
    python test_scripts/web/web_twitch_smoke.py --local-debug --passes 2
"""

import sys
import os

current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.abspath(os.path.join(current_dir, '..', '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from shared.src.lib.executors.script_decorators import script, get_context, get_args
from shared.src.lib.utils.local_debug_browser_helpers import normalize_local_debug_flag
from shared.src.lib.utils.web_tree_smoke import smoke_walk_web_tree

sys.argv = normalize_local_debug_flag(sys.argv)

UI_NAME = 'web-twitch'
SITE_LABEL = 'Twitch browse'

_script_args = [
    '--userinterface:str:web-twitch',   # Framework param with default
    '--passes:int:2',                           # Consecutive passes over the whole tree
]
_script_description = 'Walk the Twitch browse web tree: every screen forward and back, twice.'
_arg_descriptions = {
    'userinterface': 'Web user interface (navigation tree) to smoke',
    'passes': 'Consecutive passes over the tree',
}


@script('web_twitch_smoke', 'Smoke test the Twitch browse web navigation tree', default_device='host')
def main():
    context = get_context()
    args = get_args()
    ui = (getattr(args, 'userinterface', '') or UI_NAME).strip() or UI_NAME
    passes = int(getattr(args, 'passes', 2) or 2)

    try:
        result = smoke_walk_web_tree(context, ui, passes=passes)
    except Exception:
        # A walker bug must say where it broke: the report log is the only place left to look.
        import traceback
        traceback.print_exc()
        raise
    context.execution_summary = result['summary']
    print(result['summary'])
    return result['success']


main._script_args = _script_args
main._script_description = _script_description
main._arg_descriptions = _arg_descriptions
# NOT browser_isolated: this script drives the tree through the device's own navigation
# executor (the host's service browser), exactly like validation.py, so it needs the host to
# itself and two of them must not run on one device at the same time.
main._target_rules = {
    "target_type": "host",
    "host_os": "all",
    "device_model": "all",
}


if __name__ == "__main__":
    main()
