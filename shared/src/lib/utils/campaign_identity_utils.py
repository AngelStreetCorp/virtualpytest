"""
Campaign identity utilities.

Provides stable campaign reference normalization and optional metadata overrides
from test_scripts/campaign_identity_map.json.
"""

import json
import os
from typing import Any, Dict, Optional

from shared.src.lib.utils.script_identity_utils import get_project_root


def get_campaign_identity_map_path() -> str:
    """Return absolute path to campaign identity mapping file."""
    return os.path.join(get_project_root(), 'test_scripts', 'campaign_identity_map.json')


def normalize_campaign_ref(campaign_ref: Optional[str]) -> str:
    """
    Normalize campaign identifier to canonical campaign_ref format.

    Examples:
      - "Smoke Regression" -> "smoke regression"
      - "./nightly_campaign.json" -> "nightly_campaign"
      - "team/smoke.json" -> "team/smoke"
    """
    if not campaign_ref:
        return ''

    normalized = str(campaign_ref).strip().replace('\\', '/')

    if normalized.startswith('./'):
        normalized = normalized[2:]

    if normalized.endswith('.json'):
        normalized = normalized[:-5]

    return normalized.strip('/').lower()


def load_campaign_identity_map() -> Dict[str, Dict[str, Any]]:
    """
    Load campaign identity map keyed by normalized campaign_ref.

    Returns:
      Dict[campaign_ref, mapping_entry]
    """
    map_path = get_campaign_identity_map_path()

    if not os.path.exists(map_path):
        return {}

    try:
        with open(map_path, 'r', encoding='utf-8') as f:
            raw = json.load(f)

        campaigns = raw.get('campaigns', {}) if isinstance(raw, dict) else {}
        if not isinstance(campaigns, dict):
            return {}

        normalized_map: Dict[str, Dict[str, Any]] = {}
        for key, value in campaigns.items():
            norm_key = normalize_campaign_ref(key)
            if not norm_key:
                continue
            if isinstance(value, dict):
                normalized_map[norm_key] = value

        return normalized_map
    except Exception as e:
        print(f"[@campaign_identity_utils] Failed to load mapping file: {e}")
        return {}


def resolve_campaign_identity(
    campaign_id: Optional[str] = None,
    campaign_name: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Resolve canonical campaign identity plus optional metadata overrides.

    Lookup priority:
      1. campaign_id
      2. campaign_name

    Returns dict:
      {
        "campaign_ref": "nightly-smoke",
        "prefix": "CP001" | None,
        "display_name": "Nightly Smoke" | None
      }
    """
    id_ref = normalize_campaign_ref(campaign_id)
    name_ref = normalize_campaign_ref(campaign_name)
    campaign_map = load_campaign_identity_map()

    match_ref = ''
    entry: Dict[str, Any] = {}

    if id_ref and id_ref in campaign_map:
        match_ref = id_ref
        entry = campaign_map[id_ref]
    elif name_ref and name_ref in campaign_map:
        match_ref = name_ref
        entry = campaign_map[name_ref]
    else:
        # Keep canonical reference stable even when no mapping is configured.
        match_ref = id_ref or name_ref

    prefix = entry.get('prefix') if isinstance(entry, dict) else None
    display_name = entry.get('display_name') if isinstance(entry, dict) else None

    return {
        'campaign_ref': match_ref,
        'prefix': prefix,
        'display_name': display_name,
    }
