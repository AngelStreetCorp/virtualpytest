"""Virtual-scripts feature - python shared by its server part (features/virtual-scripts/lib).

Nothing outside this feature imports it today (ai-test does not). If another feature ever
needs `virtual_script_utils`, the direction is <other feature> -> virtual-scripts, never the
reverse, via `importlib.import_module('features.virtual-scripts.lib.virtual_script_utils')`
(the hyphen rules out `from features.virtual-scripts...`); see docs/technical/FEATURES.md.
A helper both features need belongs in core `shared/` instead.
"""
