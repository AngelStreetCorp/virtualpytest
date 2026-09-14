---
name: manage-script
description: List and execute Python scripts on devices
requires_device: true
timeout_seconds: 3600
tools:
  - list_scripts
  - get_compatible_hosts
  - execute_script
triggers:
  - list scripts
  - show scripts
  - available scripts
  - run script
  - execute script
---

# Manage Script

Manage scripts: list, create and execute

Naming convention: SC_<CAT>_<NUM>_<CamelCase> (e.g., SC_AUTH_01_LoginFlow)

CRITICAL:
 - Call get_compatible_hosts only if host_name, device_id not available in current message or conversation history
 - Do NOT call list_scripts if script_name is clearly specified in the current user message
