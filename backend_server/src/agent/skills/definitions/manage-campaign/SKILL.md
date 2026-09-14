---
name: manage-campaign
description: Create, read, update, and delete test campaigns
timeout_seconds: 3600
tools:
  - list_campaigns
  - get_campaign
  - create_campaign
  - update_campaign
  - delete_campaign
  - execute_campaign
  - get_compatible_hosts
triggers:
  - create a campaign
  - create new campaign
  - create campaign
  - new campaign
  - make campaign
  - list campaigns
  - show campaigns
  - get campaign
  - show campaign
  - view campaign
  - campaign details
  - update campaign
  - modify campaign
  - edit campaign
  - delete campaign
  - remove campaign
  - execute campaign
  - run campaign
  - start campaign
  - launch campaign
---

# Manage Campaign

Manage test campaigns: create, list, get, update, delete, and execute campaigns.

Campaigns are device/host agnostic collections of testcases that can run on any compatible setup. Each campaign includes:
- Campaign name and description
- List of scripts to execute with parameters
- Execution configuration (timeout, retry settings)

Naming convention: CAM_<CAT>_<NUM>_<CamelCase> (e.g., CAM_AUTH_01_LoginFlow)

CRITICAL:
 - Use campaign names, not IDs - the system auto-resolves names to internal IDs
 - script_configurations must be an array of objects with script_name and optional parameters
 - Host and device are specified at execution time, not campaign creation/update/deletion
 - Always verify campaign creation/update with list_campaigns or get_campaign
 - execute_campaign requires host_name and device_name parameters for execution

FLOW CONTROL RULES:
 - Each pass/fail handle → ONE target only (no branching to multiple)
 - Unlinked handles default to FAIL
