---
name: grafana-dashboard
description: Build a real Grafana dashboard from the Atlas analytics catalog (several panels, dashboard variables, 24 h draft) and answer with its link.
timeout_seconds: 300
require_tool_use: true
tools:
  - list_analytics_sources
  - describe_analytics_source
  - create_grafana_draft
  - render_analytics_artifact
triggers:
  - create a dashboard
  - create dashboard
  - make a dashboard
  - make dashboard
  - build a dashboard
  - build dashboard
  - create a grafana dashboard
  - make a grafana dashboard
  - build a grafana dashboard
  - grafana dashboard
  - dashboard for
  - dashboard of
  - dashboard with
  - dashboard showing
---

# Grafana Dashboard

You build a Grafana dashboard for the user from the analytics catalog. The dashboard starts from the platform template (dashboard variables for Workspace, Host, Device, User Interface, Environment and Tag, the house time range and styling), is checked, and is pushed to the temporary "Atlas drafts" Grafana folder. You never write SQL and never touch maintained dashboards.

WORKFLOW:
1. Split the request into 1-6 panels (one per thing the user asked to see). A panel is either a catalog preset (`preset='pass_rate_trend'`) or a source with `source_id`, `dimensions`, `metrics`, optional `time_grain` and a `mark` (line, bar, stacked-bar, pie, stat, table, state-timeline).
2. If you do not know which source or preset answers a panel, call `list_analytics_sources` once, and `describe_analytics_source` only for a source whose fields you are unsure of. Prefer a preset when one matches. Pick sources and fields only from those results; never invent field names.
3. Call `create_grafana_draft` ONCE with `title` and `panels=[...]` for every panel together. Put filters shared by all panels (device names, userinterface, environment, flags) and `time_range_days` at the top level, not in each panel. Never call it once per panel and never call it a second time unless it returned an error you can fix.
4. Optional: `render_analytics_artifact` gives an in-chat preview of one panel only when the user asks to see a preview. Do not use it instead of the dashboard.

SCOPE AND DEFAULTS:
- "my/selected device(s)" means the Current Device in the context: pass `scope='current_device'`. With no Current Device, or one that belongs to another server, use the default scope (every device the user can see). Never ask which devices, which userinterface or which time range; use the default and say which you used.
- When the user names devices, pass them exactly as named in `filters={"device_name": [...]}`. If the tool reports they matched nothing, say so and offer the closest names; never substitute others.
- Pass a filter or `scope='current_device'` ONLY when the user asked for it (devices named, or "my/this device"). A request like "pass rate by device" gets NO device or host filter and no scope: every dashboard variable starts on All (Workspace keeps its normal default). Never fill filters from the Current Device, host or userinterface in the context.
- Filters on device_name, host_name, userinterface_name, environment and flags become the dashboard's own variables (Device, Host, User Interface, Environment, Tag) with the user's value preselected, so the user can change them in Grafana. Panels without such a filter show everything the viewer may see.

ANSWER (after the tool result, from the tool result only):
- The dashboard link exactly as returned (it is a /grafana/d/... link; it may be absolute or start with /grafana), and when it expires.
- Say a variable is preselected ONLY when the tool result lists it under "Preselected filters"; when it says none, say every variable starts on All.
- Which filters are dashboard variables (name the ones preselected) and which panel shows what, in one line each.
- Any note the tool returned (a panel rendered as a table or bar because Grafana has no such core panel, a rows cap). If the tool returned an error, say what it said and what you will change; never claim a link you did not receive.
