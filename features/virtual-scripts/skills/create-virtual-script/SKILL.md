---
name: create-virtual-script
description: Write, edit and save a virtual script (DB-stored Python test script), then optionally run it on a device
timeout_seconds: 3600
tools:
  - list_scripts
  - get_virtual_script
  - save_virtual_script
  - list_userinterfaces
  - get_userinterface_complete
  - get_compatible_hosts
  - execute_script
  - get_script_execution_status
triggers:
  - create a script
  - create script
  - new script
  - write a script
  - write script
  - python script
  - virtual script
  - create virtual script
  - edit script
  - update script
  - modify script
  - fix script
---

# Create Virtual Script

You write Python test scripts that live in the database (virtual scripts). Saving one makes it
runnable at once: no deploy. It appears in Run Tests (green "VS" badge) and in list_scripts.

## Flow

1. **Understand the ask.** If the script navigates an app, call list_userinterfaces() and
   get_userinterface_complete(userinterface_name) to get the real node names. Never invent a node.
2. **Editing an existing script?** Call get_virtual_script(name) first and change that source.
   Never rewrite a script from memory.
3. **Write the full source** from the template below and call
   save_virtual_script(name, source, folder?). A syntax error comes back with its line: fix and save again.
   Warnings (no @script, no _script_args) mean the script will not run properly: fix them too.
4. **Run it only if the user asked** (or says "and run it"): get_compatible_hosts(userinterface_name),
   then execute_script(script_name=<name>, virtual_script_id=<id from save>, host_name, device_id,
   parameters='--node live'), then get_script_execution_status(execution_id) until done is true.
   Report passed/failed and the report link.
5. Answer with: name, folder, parameters, and what the script does in one or two sentences.
   Do not paste the whole source back unless asked.

## Naming

- `SC_<CAT>_<NUM>_<CamelCase>`, e.g. `SC_NAV_01_GotoLive`, `SC_PLAY_02_ZapFiveChannels`.
- Letters, digits and underscores only. No folder in the name: pass `folder` instead.
- Names starting with `utils_`, `lib_`, `common_` or `_` are **libraries**: shared code that other
  scripts import, never run. A script imports them by declaring `_script_libs = ["utils_x"]` at the
  top, then `import utils_x`.

## Template (keep every marked part)

```python
#!/usr/bin/env python3
"""SC_NAV_01_GotoLive - navigate to a node and report the result."""

import sys
import os
import asyncio

current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from shared.src.lib.executors.script_decorators import script, get_context, get_args, get_device


@script("SC_NAV_01_GotoLive", "Navigate to a node", default_device="device1")
def main():
    args = get_args()
    context = get_context()
    device = get_device()

    nav = device.navigation_executor.load_navigation_tree(args.userinterface, context.team_id)
    if not nav['success']:
        context.error_message = f"Tree load failed: {nav.get('error')}"
        context.overall_success = False
        return False
    context.tree_id = nav['tree_id']

    result = asyncio.run(device.navigation_executor.execute_navigation(
        tree_id=context.tree_id,
        userinterface_name=context.userinterface,
        target_node_label=args.node,
        team_id=context.team_id,
        context=context,
    ))
    success = result.get('success', False)
    if not success:
        context.error_message = result.get('error', 'Navigation failed')

    context.overall_success = success
    context.execution_summary = f"Target: {args.node}\nResult: {'SUCCESS' if success else 'FAILED'}"
    return success


# --name:type:default[:choice1|choice2]  (--host/--device are added by the platform)
main._script_args = [
    '--userinterface:str:stb_tv',
    '--variant:str:',
    '--node:str:home',
]
main._script_description = "Navigate to a node and report the result."
main._arg_descriptions = {
    'userinterface': 'UI interface name',
    'variant': 'Optional variant; empty = base',
    'node': 'Target node',
}
main._target_rules = {
    "target_type": "device",   # 'host' for a script that runs on the host machine itself
    "host_os": "all",
    "device_model": "all",
}

if __name__ == "__main__":
    main()
```

## Rules

- The `@script(...)` name matches the script name. `main()` sets `context.overall_success` and returns it.
- `_script_args` sits right after `main()`, not at the bottom of a long file.
- Set `context.error_message` on every failure path, and `context.execution_summary` for the report.
- Report text in French/German: add `main._i18n = {"English text {name}": {"fr": "...", "de": "..."}}`
  next to `_script_args` (English text is the key).
- No secrets in the source. No `time.sleep` loops longer than the user asked for.
