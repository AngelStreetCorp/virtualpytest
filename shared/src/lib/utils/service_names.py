"""Unit-name mapping for the renamed monitor services (TASK-90).

vpt-monitor -> vpt-monitor-img, vpt-transcript -> vpt-monitor-audio,
vpt-subtitle -> vpt-monitor-subtitle. systemd keeps the old names as aliases, but
``journalctl -u <old>`` does not follow an alias, so code that receives a unit name from
outside (old links, agent prompts, saved dashboards) translates it here first.
"""

LEGACY_UNIT_NAMES = {
    'vpt-monitor': 'vpt-monitor-img',
    'vpt-transcript': 'vpt-monitor-audio',
    'vpt-subtitle': 'vpt-monitor-subtitle',
}


def canonical_unit_name(name):
    """Return the current unit name for ``name`` (old names are mapped, others pass through)."""
    return LEGACY_UNIT_NAMES.get(name, name)
