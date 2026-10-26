"""Build the navigation-node payload for an accepted unknown screen.

The accept route (``server_userinterface_routes.accept_unknown_screen``) creates a
node from the stored unknown-screen row. Keeping the payload construction here
makes the fingerprint-preservation contract testable: the row's ``fingerprint``
is the complete v6 blob (G2/G3) or a legacy ``{dhash}`` — either is stored as-is
on the node, and ``identify_screen`` reads a dhash-only one through its v4 path.
"""
import re
from typing import Any, Dict, Optional


def build_unknown_node_data(row: Dict[str, Any], ui_name: str, row_id: str,
                            label: Optional[str] = None) -> Dict[str, Any]:
    """The node payload for ``accept_unknown_screen`` (no DB access)."""
    node_label = label or row.get('proposed_name') or f'{ui_name}_unknown_{str(row_id)[:8]}'
    node_id = re.sub(r'[^A-Za-z0-9_]+', '_', node_label).strip('_').lower() or f'unknown_{str(row_id)[:8]}'
    return {
        'node_id': node_id,
        'label': node_label,
        'node_type': 'screen',
        'verifications': [],
        'data': {
            'type': 'screen',
            'is_root': False,
            'ai_generated': True,
            'discovery_order': 0,
            'depth': 1,
            'screenshot': row.get('image_url'),
            # The complete v6 fingerprint when the live matcher stored one;
            # legacy rows keep their dhash-only dict.
            'fingerprint': row.get('fingerprint'),
            'dom': row.get('dom'),
            'from_unknown_screen': row_id,
        },
        'position_x': 250,
        'position_y': 100,
    }
