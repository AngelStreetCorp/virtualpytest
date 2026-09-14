"""Autonomous UserInterface builder — OFFLINE algorithm harness.

Decoupled so the build loop is testable with no device, no DB, no LLM:
  builder logic  -> AutoUIBuilder        (auto_ui_builder.py)
  device I/O     -> DeviceAdapter        (device_adapter.py)  Replay only
  graph writes   -> GraphSink            (graph_sink.py)      Memory only
  regression     -> diff_graphs          (graph_diff.py)      vs a known fixture

Offline test = ReplayAdapter + MemorySink + fixture  (features/avq/backend_host/localize/auto_build_offline_test.py)

LIVE builds do NOT go through this package. The production live builder is
features/avq/backend_host/localize/auto_build_mcp_live.py (MCP-driven, resumable state machine) followed by
features/avq/backend_host/localize/push_autobuild_to_db.py. A LiveAdapter/DbSink pair used to be declared here
but was never exercised end-to-end (its entry script never existed) and carried
latent wiring bugs — removed 2026-07-16 rather than advertise a live mode that
doesn't work; see docs/tasks/TASK-02-consolidate-demo.md.
"""
