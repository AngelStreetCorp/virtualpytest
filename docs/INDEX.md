# Documentation Index

Master lookup: scan the section matching the question's topic, open the file whose "read when" fits. Paths are relative to `docs/`. API request/response contracts live in `api/specs/*.yaml` (endpoint paths listed per spec below).

## FAQ
- `faq/README.md` — quick conceptual Q&A: how one script runs on all devices, navigation-tree model, verifications, supported devices, prerequisites, differences vs Appium/Selenium, adding a device, CI/CD usage, and licensing/pricing ("is it really free" — MIT, self-hosted costs).

## Get Started (installation & deployment)
- `get-started/README.md` — THE entry point: chooser Docker / one VM / Proxmox fleet / developer, sizing, architecture picture.
- `get-started/docker.md` — whole platform as containers on one machine (`setup/docker/launch.sh`), ports, first test, devices, host-only mode, exposure checklist.
- `get-started/proxmox.md` — native install: one VM (`install_all.sh`) or one VM per role; day-two commands.
- `get-started/local-dev.md` — developer setup on Linux (foreground services); macOS and Windows as host role only.
- `get-started/supabase.md` — where Supabase runs (in-stack / CLI / cloud), auth posture table (open mode default), enforce-login recipes, RLS note; `get-started/supabase-auth-setup.md` — long version: OAuth providers, roles, permissions, token flow.
- `get-started/configuration.md` — every env variable per component, ports, pinned versions.
- `get-started/hardware.md` — what to buy, with pictures and links: Raspberry Pi 5 16 GB kit (standalone) vs Minisforum MS-A2 + Proxmox (lab), the MS2109 HDMI→USB capture dongle, Proxmox node sizing for the full fleet, IR / BLE / smart-plug control hardware, optional local-LLM VM layout, shopping lists.
- `get-started/emulators.md` — emulator VMs per device type (web/mobile/tablet/TV): vCPU/RAM/disk sizing, which AVD or browser, creating the VM on Proxmox or any hypervisor, and configuring it for VirtualPyTest.
- `get-started/network.md` — UFW rules for a standalone box and for a production LAN, compute<->device segmentation, TLS/certbot, nginx HTTP->HTTPS, and remote-access options (Cloudflare Tunnel, VPN).
- `get-started/content-filtering.md` — keep lab browsers, emulators and devices off adult/malware sites: block list via Cloudflare for Families DNS (one dnsmasq change on the Proxmox node covers every VM and emulator), standalone-box and per-device recipes, allow-list variant for a showcase device, what DNS filtering does not cover.
- `get-started/production-checklist.md` — going-live hardening: every default credential the installers ship (MinIO/Redis/VNC/Postgres/JWT), the auth switches (`SERVER_OPEN_MODE`, public key, auto-sign), what must not be exposed, least privilege, backups, CI runners.
- `get-started/security.md` — transport security (nginx ssl-params, certbot renewal), API key generation, CORS posture, UFW/firewall hardening, and the per-service exposure rules.
- `get-started/cloud-setup.md` — Vercel frontend + Render server + local host variant; `get-started/branding.md` — white-labeling; `get-started/ci_cd.md` — the regression workflow's jobs.

## User Guide (using the product)
- `user-guide/README.md` — user-guide navigation hub.
- `user-guide/getting-started.md` — the first test once the UI is up (install is in get-started/).
- `user-guide/running-tests.md` — Run Tests web page: pick targets, execute scripts, testcases, campaigns, read results.
- `user-guide/writing-scripts.md` — authoring scripts with the `@script` decorator: parameters, target rules, step reporting, metadata.
- `user-guide/troubleshooting.md` — end-user problem/solution list (system won't start, device issues, etc.).

## Features (capability overviews / marketing-style)
- `features/README.md` — visual overview of all features.
- `features/test-automation.md` — low-code automation: navigation trees + visual builder; `features/unified-controller.md` — one script across Android TV/iOS/mobile/STB/smart-TV.
- `features/ai-validation.md` — OCR/image/screen-state verification with evidence capture; `features/visual-capture.md` — video capture, live streaming, screenshots.
- `features/analytics.md` — real-time Grafana dashboards (execution, device health, system perf).
- `features/integrations.md` — feature-level tour of JIRA/Grafana/CI-CD integrations; `features/navigation-tree-history.md` — tree version control and restore.
- `features/mobile-app.md` — Android app: the platform in a phone layout, and a paired phone as a device under test (`phone_agent`); technical detail in `technical/MOBILE_APP.md`.
- `features/nav-visibility.md` — 3-layer navbar item visibility keyed by full route path.
- `features/requirements-management.md` — requirements-management feature spec (link requirements to testcases/scripts, coverage tracking, REST + hooks).
- `features/workspace-scoping.md` — how `device_filter`/`script_filter` narrow devices, scripts and run history; which APIs to call.

## API (request/response contracts — specs/*.yaml)
- `api/specs/server-access-workspace.yaml` — auth/users/teams/workspaces: `/server/auth/{check,profile}`, `/server/permissions/matrix`, `/server/users[/{user_id}][/assign-team|/remove-team|/permissions]`, `/server/teams[/{team_id}][/members[/{user_id}]]`, `/server/workspaces[/user/{user_id}|/{workspace_id}[/members[/user|/team|/{member_id}]]]`.
- `api/specs/server-ai-analysis.yaml` — AI agent: `/server/ai/{analyzeCompatibility,generatePlan,getStatus,stopExecution,analyzePrompt,resetCache}`.
- `api/specs/server-campaign-management.yaml` — campaign CRUD: `/server/campaigns/{getAllCampaigns,createCampaign,getCampaign,updateCampaign,deleteCampaign}[/{campaign_id}]`.
- `api/specs/server-core-system.yaml` — health check: `/server/system/health`.
- `api/specs/server-deployment-scheduling.yaml` — scheduled deployments: `/server/deployment/{create,list,pause,resume,delete}[/{deployment_id}]`.
- `api/specs/server-device-management.yaml` — device CRUD: `/server/devices/{getAllDevices,createDevice,getDevice,updateDevice,deleteDevice}[/{device_id}]`.
- `api/specs/server-metrics-analytics.yaml` — navigation metrics: `/server/metrics/{tree,node/node-id,edge/edge-id,history/actions/edge-id,history/verifications/node-id}/{navigation_id}`.
- `api/specs/server-navigation-management.yaml` — navigation & trees: `/server/navigation/goto`, `/server/navigation/config/createEmpty/{ui_name}`, `/server/navigation-trees/{getTree/{navigation_id},getAllTrees,deleteTree/{navigation_id}}`.
- `api/specs/server-requirements-management.yaml` — requirements: `/server/requirements/{create,list,{requirement_id},link-testcase,coverage/summary}`.
- `api/specs/server-results-reporting.yaml` — results/alerts/heatmap: `/server/script-results/{getAllScriptResults,getVerificationReviewMarkdown,updateCheckedStatus,updateDiscardStatus}`, `/server/campaign-results/getAllCampaignResults`, `/server/execution-results/getAllExecutionResults`, `/server/alerts/{getAllAlerts,getActiveAlerts,getClosedAlerts,updateCheckedStatus,updateDiscardStatus,deleteAllAlerts}`, `/server/heatmap/{history,generateReport}`.
- `api/specs/server-script-management.yaml` — script list/analyze/execute/status/abort: `/server/script/{list,analyze,get_edge_options,execute,abortRunning,status/{task_id}}`.
- `api/specs/server-testcase-management.yaml` — testcase CRUD: `/server/testcase/{list,save,{testcase_id}}`.
- `api/specs/server-user-interface-management.yaml` — userinterface CRUD: `/server/userinterface/{getAllUserInterfaces,createUserInterface,getUserInterface,updateUserInterface,deleteUserInterface}[/{interface_id}]`.
- `api/COVERAGE.md` — how the spec set is organized: source of truth (backend routes vs specs vs rendered HTML), what the grouped specs cover.
- `api/source-endpoints.md` — source code management/deployment endpoints with examples: `/server/system/source/{detect,git/branches,git/prepare,zip/upload,zip/validate,zip/apply}`.

## Technical (architecture & internals)
- `technical/README.md` — technical docs hub.
- `technical/architecture/architecture.md` — high-level system design (all services, data flow).
- `technical/architecture/components/backend-core.md` (controllers/business-logic lib), `backend-host.md` (hardware interface service), `backend-server.md` (API orchestration + Grafana), `frontend.md` (React TS UI), `shared.md` (common Python utils) — per-component deep dives.
- `technical/architecture/navigation.md` — the 3 navigation layers and when scripts should use each.
- `technical/architecture/navigation_metrics.md`, `node_edges_metrics.md`, `technical/dev/navigation_metrics_implementation.md` — metrics aggregation via PG triggers, confidence coloring, hierarchical implementation.
- `technical/architecture/ORCHESTRATOR_WORKFLOW.md` — unified async-first execution flow for navigation/verifications/actions/testcases/campaigns.
- `technical/architecture/deployment.md` — cron-expression scheduled script execution system.
- `technical/architecture/incidents.md` — incident detection system design (dedup, clean rewrite).
- `technical/architecture/CONTROLLER_CREATION_GUIDE.md` — step-by-step: add a new controller; `DIRECT_PYTHON_CONTROLLER_USAGE.md` — use controllers in Python without HTTP ("controller not found" fixes); `APPIUM_REMOTE_IMPLEMENTATION.md` — Appium controller for iOS/Android/Windows/macOS.
- `technical/architecture/MINIO_PRIVATE_BUCKET_GUIDE.md` / `R2_PRIVATE_BUCKET_GUIDE.md` — presigned-URL private storage buckets (self-hosted MinIO / Cloudflare R2).
- `technical/architecture/storage-hot-ram.md` — RAM-based hot storage for capture files; `storage-audio.md` — audio chunks in the hot/cold storage model.
- `technical/ai/builder.md` — AI graph builder internals; `technical/ai/tree-creation.md` — automated 2-level navigation tree generation algorithm; `technical/ai/exploration.md` — auto-exploration without user approval.
- `technical/ai/detector.md` — real-time frame analysis engine (quality issues, zapping, subtitles).
- `technical/dev/GLOBAL_NAMING_CONVENTION.md` — naming rules for the verification & action system across FE/BE/routes.
- `technical/dev/navigation_history.md` — Navigation Editor undo/redo system.
- `technical/dev/deployment_lock_flow.md` — deployment lock indicator data flow.
- `technical/dev/url-builders.md` — the 3 canonical URL builder functions; `timezone.md` — timezone handling and known issues.
- `technical/dev/COLOR_CONSISTENCY_GUIDE.md` — centralized theme colors; `Z_INDEX_MANAGEMENT.md` — central z-index registry.
- `technical/testcase/testcase-graph.md` — `graph_json` structure (Blockly-style nodes/edges); `testcase-naming.md` — testcase naming convention; `testcase-template.md` — standard description format.
- `technical/permissions/PERMISSION_PLAN.md` — fine-grained permission system design (not yet implemented).
- `technical/webhook.md` — webhook + WebSocket completion contract for script/deployment execution.
- `technical/script_execution_socket_diagnosis.md` — field diagnosis of a script-execution socket failure.
- `technical/AI_ANALYZER_DIRECT_TEST_STRATEGY.md` — test strategy for the direct queue-analyzer loop (failure/success sampling policy); `AI_FALSE_POSITIVE_MARKDOWN_PLAN.md` — plan: per-execution AI-only markdown artifact for false-positive classification.

## MCP (Model Context Protocol server)
- `mcp/README.md` — MCP docs hub (version, tool count, links to all tool pages).
- `mcp/mcp_core.md` — server overview: endpoint URL, Bearer auth, protocol, how external LLMs connect.
- `mcp/mcp_security.md` — security layers preventing tools from leaking .env/credentials/keys.
- `mcp/mcp_playground.md` — MCP Playground web interface for trying tools.
- `mcp/mcp_tools_generated.md` — auto-generated catalog of all 75 tools by category (source of truth for tool names).
- `mcp/mcp_tools_control.md` — `take_control` (mandatory first step); `mcp/mcp_tools_action.md` — device action tools reference.
- `mcp/mcp_tools_navigation.md` — navigation tools; `mcp/mcp_tools_tree.md` — 11 primitive tree CRUD tools; `mcp/mcp_tools_exploration.md` — 7 AI exploration tools that auto-build navigation trees.
- `mcp/mcp_tools_verification.md` — verification tools; `mcp/mcp_tools_screen_analysis.md` — `analyze_screen_for_action`/`_verification`; `mcp/mcp_tools_screenshot.md` — `capture_screenshot`.
- `mcp/mcp_tools_script.md` — script execution tools; `mcp/mcp_tools_testcase.md` — testcase management tools; `mcp/mcp_tools_requirements.md` — 10 requirements/coverage tools.
- `mcp/mcp_tools_ai.md` — AI generation tools; `mcp/mcp_tools_userinterface.md` — userinterface management tools.

## Integrations (external tools)
- `integrations/README.md` — integrations hub.
- `integrations/jira-setup.md` — JIRA ticket dashboard setup (multi-instance, API token proxy).
- `integrations/slack-setup.md` — Slack app setup walkthrough; `integrations/slack-integration.md` — architecture of AI-conversation→Slack-thread sync.

## Security
- `security/README.md` — automated Bandit/Snyk scan reports index (dashboard + raw JSON per component).

## Agent docs (operational references for AI agents working on/with VPT)
- `agent/INDEX.md` — generated full index with keywords; route here for the subdirectories not listed below (`agent/devices/`, `agent/execution/`, `agent/infra/`, `agent/navigation/`, `agent/platform/`, `agent/validation/`).
- `agent/README.md` — agent onboarding, read first; `agent/MAP.md` — codebase map, find the right files without grepping.
- `agent/CONTRACTS.md` — hidden implicit rules that cause bugs when violated; `agent/PATTERNS.md` — canonical files to copy when adding features; `agent/BEST_PRACTICES.md` — practices mined from past incidents/bugs.
- `agent/TROUBLESHOOT.md` — known issues and fixes across the platform.
- `agent/TESTING.md` — auto-sign token to bypass auth for agent/E2E testing; `agent/AGENT_API_TESTING.md` — drive Atlas/Sherlock/Nightwatch from a terminal via API/MCP, no browser.
- `agent/DEPLOY.md` — push, deploy to debug env, verify end-to-end; `agent/CODE_DEPLOYMENT.md` — admin Code Deployment page and backend deploy APIs; `agent/CICD.md` — regression pipeline details.
- `agent/DATABASE.md` — DB architecture, access, backup/recovery; `agent/INFRA.md` — VM topology, IPs, services (single source of truth).
- `agent/HOST_SERVICE.md` — how host-side Linux services fit together; `agent/host_runner.md` — lightweight runner hosts (script-exec only, no capture).
- `agent/STREAM.md` — `run_ffmpeg.sh` AV capture pipeline (HLS, frames, audio); `agent/devices/FFMPEG_TROUBLESHOOT.md` — ffmpeg stall runbook; `agent/FFMPEG_HD_PLUS.md` — HD+ buffered watch-stream tier.
- `agent/CPU_PARTITIONING.md` — shielding the latency-critical control path from ffmpeg CPU load.
- `agent/DEVICE_CONTROL.md` — drive any device type via one route/many controllers; `agent/DEVICE_SCREENSHOTS.md` — fetch frames from devices under test (NOT frontend screenshots).
- `agent/DEVICE_LOCK.md` — device locking/arbitration and leaked-lock recovery; `agent/PERSISTENT_DEVICES.md` — stable per-STB peripheral naming on multi-device hosts.
- `agent/DEVICE_INFO_CORRECTION.md` — OCR-extracted device info fields and manual overrides.
- `agent/INFRARED.md` — IR key-press pipeline + debugging; `agent/IRTRANS_PROXY.md` — reaching a networked IRTrans box through the nginx proxy.
- `agent/BLUETOOTH.md` — BLE remote emulation for the Arris STB (HID descriptor, pairing, reboot persistence).
- `agent/EMULATOR.md` — Android emulator VM topology and operations; `agent/devices/ANDROID_EMULATOR_TROUBLESHOOT.md` — step-by-step debugging of the 3 emulator hosts.
- `agent/USERINTERFACE.md` — index across all UserInterface concerns; `agent/navigation_trees.md` — navigation tree data model; `agent/NAVIGATION.md` — runtime action execution and node verification; `agent/VARIANT.md` — named-variant overlay on trees.
- `agent/KNOWN_ISSUES_USERINTERFACE.md` — catalogue of UI-validation bugs (symptom → root cause → fix).
- `agent/VALIDATION_ANALYSIS.md` — diagnosis playbook for failed validation runs (cause-of-failure ladder); `agent/VALIDATION_FIX_LOOP.md` — validate→fix→re-validate loop workflow.
- `agent/REFERENCE.md` — how verification references (image + text) are stored, scoped, replaced; `agent/image.md` — image/icon matching algorithms and extensions.
- `agent/KPI.md` — action→on-screen-confirmation timing: measurement, storage, aggregation, display.
- `agent/navigation/AUTOBUILD.md` — auto-build pipeline runbook (machine-created, oracle-certified UIs); `agent/navigation/AUTOBUILD_STRIP_MODEL.md` — its hard case: commit-strip/pane-row settings screens.
- `agent/testgen/AI_TEST_GENERATION.md` — concept: AI creates deterministic zero-token `graph_json` testcases; `agent/testgen/AI_TEST_GENERATION_GUIDE.md` — full E2E guide per platform (web, tablet, TV).
- `agent/testgen/AI_TEST_GENERATION_PHASES.md` — implementation status by phase; `agent/testgen/AI_TEST_GENERATION_ROADMAP.md` — platform coverage matrix; `agent/testgen/AI_TEST_GENERATION_V2.md` — v2 design (requirements drive tests).
- `agent/AI_USERINTERFACE.md` — AI-learned UI knowledge base (DB tables, CRUD, history); `agent/navigation/AI_USERINTERFACE_MARKDOWN_PACKS.md` — current 5-layer pack model + runtime contract (read first for AI-UI work).
- `agent/navigation/AI_USERINTERFACE_CRAWLING.md` — how to crawl a UI into a pack and verify it; `agent/navigation/AI_USERINTERFACE_TROUBLESHOOT.md` — field log of AI-UI failures; `agent/navigation/AI_USERINTERFACE_BENCHMARKS.md` — LLM/VLM benchmark results on STB tasks.
- `agent/TEST_PROMPT.md` — free-text prompt + acceptance-criteria AI test feature.
- `agent/SCRIPTS_AND_CAMPAIGNS.md` — adding/moving/wiring `test_scripts/` and `test_campaign/` files; `agent/execution/VIRTUAL_SCRIPTS.md` — DB-stored, browser-edited scripts run without deploy.
- `agent/PERIODIC_TEST_RUN.md` — the TWO separate scheduling mechanisms and when each applies.
- `agent/mcp.md` — VPT MCP tools reference for agents (75+ tools, workflows).
- `agent/GRAFANA.md` — Grafana access/operations; `agent/GRAFANA_DASHBOARD_PERF.md` — SRI dashboard slowness diagnosis and applied fix.
- `agent/SCREENSHOTS.md` — screenshotting the VPT frontend itself (Puppeteer, responsive review); `agent/UIUX.md` — UI/UX review findings.
- `agent/ORG_MANAGEMENT.md` — admin management of users/teams/workspaces (UI + API); `agent/WORKSPACES.md` — workspace DB schema, permission semantics, API, frontend.
- `agent/USER_PERMISSION.md` — authentication, roles, fine-grained permission checks; `agent/SERVER_AUTH.md` — `/server/*` auth baseline design (API key / JWT / auto-sign).
- `agent/REQUIREMENTS.md` — requirements & coverage technical reference; `agent/COVERAGE.md` — Coverage dashboard internals.
- `agent/CHANGE_DOMAIN.md` — exact updates needed when the production domain changes.
- `agent/AVQ_IMPLEMENTATION.md` — per-minute audio/video quality KPI implementation plan.
- `agent/PROFILING.md` — py-spy sampling of remote host services; `agent/DOCS_BENCHMARK.md` — benchmark for whether agents can retrieve facts from these docs; `agent/OBSIDIAN.md` — viewing docs/ as an Obsidian graph.
- `agent/ai/UNIFIED_CHAT_REFACTOR.md` — plan to unify the 3 overlapping agent-chat systems.
- `agent/ai/README.md` — AI agent system docs hub; `agent/ai/agent.md` — skill-based 3-agent architecture with prompt caching.
- `agent/ai/analyser_agent.md` — Sherlock/Nightwatch monitoring & analysis agents; `agent/ai/agent_memory_strategy.md` — conversation context/memory between messages.
- `agent/ai/socket.md` — Socket.IO real-time config for the AI agent.
- `agent/ai/tool-caching.md` — dual tool-caching strategy; `agent/ai/tool_definition_autogeneration.md` — tool definitions auto-generated from implementation code.
- `agent/ai/agent_benchmarks.md` — 3-tier agent benchmarking pyramid; `agent/ai/langfuse_integration.md` — Langfuse LLM observability; `agent/ai/mcp_improvement.md` — MCP tool improvement plan (partially superseded).

## Release Notes
- `release_note/README.md` — what shipped, newest first (user-facing features and fixes only).

## Bugs
- `bugs/README.md` — in-repo bug tracker index and how to log a bug (one file per BUG-NNNN).
