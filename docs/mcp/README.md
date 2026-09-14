# VirtualPyTest MCP Server Documentation

**Version**: 4.7.0  
**Last Updated**: 2025-11-22  
**Total Tools**: 75

This documentation has been modularized for easier navigation and maintenance.

---

## 📚 Quick Navigation

### Core Documentation
- **[MCP Core](mcp_core.md)** - Overview, architecture, prerequisites, setup, security, and quick start
- **[MCP Security](mcp_security.md)** - Sensitive file protection: 3-layer defense (tool filtering, global gate, system prompt)

### Tool Documentation by Category

#### 🔐 Control & Discovery
- **[Control Tools](mcp_tools_control.md)** (1 tool) - `take_control` ⚠️ **MUST BE FIRST**
- **[Action Tools](mcp_tools_action.md)** (2 tools) - `execute_device_action`, `list_actions` ⏱️ **[Wait Time Guidelines](mcp_tools_action.md#⏱️-action-wait-time-guidelines)**
- **[Navigation Tools](mcp_tools_navigation.md)** (3 tools) - `navigate_to_node`, `list_navigation_nodes`, `preview_userinterface` 🆕
- **[Verification Tools](mcp_tools_verification.md)** (4 tools) - `verify_device_state`, `verify_node`, `list_verifications`, `dump_ui_elements`
- **[Screen Analysis Tools](mcp_tools_screen_analysis.md)** (2 tools) - `analyze_screen_for_action`, `analyze_screen_for_verification` 🆕 **Unified Selector Scoring**

#### 🔧 Tree Building
- **[🤖 AI Exploration Tools](mcp_tools_exploration.md)** (7 tools) - **RECOMMENDED** ⭐ Automated tree building (start_ai_exploration, approve_exploration_plan, validate_exploration_edges)
- **[Tree Tools](mcp_tools_tree.md)** (11 tools) - Manual primitives (create/update/delete nodes/edges, subtrees, execute_edge)

#### 🧪 Test Management
- **[TestCase Tools](mcp_tools_testcase.md)** (6 tools) - Save, load, list, execute, rename testcases
- **[Script Tools](mcp_tools_script.md)** (2 tools) - `execute_script`, `list_scripts`
- **[AI Tools](mcp_tools_ai.md)** (2 tools) - `generate_test_graph`, `generate_and_save_testcase`

#### 🎨 App & Requirements
- **[UserInterface Tools](mcp_tools_userinterface.md)** (6 tools) - Create/list/delete userinterfaces, nodes, edges
- **[Requirements Tools](mcp_tools_requirements.md)** (10 tools) - Requirements & coverage tracking

#### 📸 Media & Monitoring
- **[Screenshot Tools](mcp_tools_screenshot.md)** (1 tool) - `capture_screenshot`
- **Device Tools** (3 tools) - `get_device_info`, `get_compatible_hosts`, `get_execution_status` *(in mcp_core.md)*
- **Transcript Tools** (1 tool) - `get_transcript` *(in mcp_core.md)*
- **Logs Tools** (2 tools) - `view_logs`, `list_services` *(in mcp_core.md)*

### Additional Resources
- **[MCP Playground](mcp_playground.md)** - Web interface with voice input (mobile-first)

---

## 🚀 Quick Start Guide

### 1. Prerequisites & Setup
→ [Installation & Security Configuration](mcp_core.md#prerequisites)

### 2. First Steps
1. **[Take Control](mcp_tools_control.md)** - Lock device (CRITICAL FIRST STEP)
2. **[Discover Actions](mcp_tools_action.md#list_actions)** - See what commands are available
3. **[Execute Action](mcp_tools_action.md#execute_device_action)** - Swipe, tap, type
4. **[Navigate](mcp_tools_navigation.md)** - Move through UI tree
5. **[Verify State](mcp_tools_verification.md)** - Check elements exist

### 3. Advanced Usage
- **[Build Navigation Trees](mcp_tools_tree.md)** - Create nodes & edges
- **[Generate Tests with AI](mcp_tools_ai.md)** - Natural language → test case
- **[Manage Requirements](mcp_tools_requirements.md)** - Track coverage

---

## 📖 Common Workflows

### Quick Device Test
```
1. take_control (REQUIRED FIRST)
2. list_navigation_nodes (discover targets)
3. navigate_to_node (go to screen)
4. capture_screenshot (verify visually)
```
→ See: [Control](mcp_tools_control.md) | [Navigation](mcp_tools_navigation.md) | [Screenshot](mcp_tools_screenshot.md)

### Build Navigation Tree (Automated - RECOMMENDED)
```
1. create_userinterface (create app model)
2. start_ai_exploration (AI analyzes screen)
3. approve_exploration_plan (creates all nodes/edges)
4. validate_exploration_edges (tests all edges)
5. finalize_exploration (makes permanent)
```
→ See: [AI Exploration](mcp_tools_exploration.md) | [UserInterface](mcp_tools_userinterface.md)

### Build Navigation Tree (Manual - Advanced)
```
1. create_userinterface (create app model)
2. dump_ui_elements (see what's on screen)
3. create_node (for each screen)
4. create_edge (navigation between screens)
5. save_node_screenshot (visual documentation)
```
→ See: [Tree Tools](mcp_tools_tree.md) | [Screen Analysis](mcp_tools_screen_analysis.md)

### Automated Testing (AI Agent Recommended Workflow)
```
1. crawl_app(url, host_name)              → discover app structure
2. create_requirement(code, name)         → define what to test
3. Build graph_json yourself              → see save_testcase for format
4. save_testcase(name, graph_json)        → store in VPT
5. execute_testcase(name, host_name, device_id) → run tests
6. capture_screenshot(host_name, device_id)     → grab results
```

> **For AI agents:** Do NOT use `generate_and_save_testcase` — that uses VPT's built-in AI
> (OpenRouter). Build the graph yourself and use `save_testcase()` instead.

→ See: [AI Tools](mcp_tools_ai.md) | [TestCase](mcp_tools_testcase.md) | [Requirements](mcp_tools_requirements.md)

### Automated Testing (Legacy — VPT Web UI)
```
1. generate_test_graph (from natural language)
2. save_testcase (to database)
3. execute_testcase (run test)
4. link_testcase_to_requirement (track coverage)
```

---

## 🧭 Navigation Autonomy Concept

**CRITICAL UNDERSTANDING FOR AI TEST GENERATION:**

### The Two-Layer Architecture

**Layer 1: Navigation Tree (App-Specific)**
- Defines HOW to move between screens
- Contains explicit actions (click_element, press_key, etc.)
- Built once per app (Netflix, YouTube, etc.)
- Example: `home -(click "Play")→ player`

**Layer 2: Test Cases (Reusable)**
- Defines WHAT to test
- References navigation tree nodes by label
- Reusable across apps by changing `userinterface_name`
- Example: Navigate to "player" → Verify video plays

### Why This Matters

❌ **Wrong Approach (Manual Navigation in Test Cases):**
```json
{
  "type": "action",
  "data": {"command": "click_element", "text": "Play"}
}
```
*Problem: Hardcodes Netflix-specific actions, not reusable*

✅ **Correct Approach (Reference Navigation Tree):**
```json
{
  "type": "navigation",
  "data": {"target_node_label": "player"}
}
```
*Solution: Uses navigation tree, works for any streaming app*

### When to Use What

- **`navigate_to_node`**: Go to screens defined in navigation tree (DECLARATIVE)
- **`execute_device_action`**: One-off actions NOT part of navigation (pause video, adjust volume)
- **`verify_device_state`**: Check screen state after navigation

### Benefits

1. **Reusability**: Same test case works on Netflix, YouTube, Hulu
2. **Maintainability**: UI changes only affect navigation tree, not test cases
3. **Separation of Concerns**: Navigation logic vs. test logic
4. **Declarative Testing**: Say "go to player" not "click this, then that"

→ See: [Navigation Tools](mcp_tools_navigation.md) | [TestCase Tools](mcp_tools_testcase.md)

---

## 🎯 Tool Categories Overview

### By Functionality

**Discovery & Inspection** (7 tools)
- `list_actions`, `list_verifications`, `list_navigation_nodes`, `dump_ui_elements`, `preview_userinterface` 🆕, `analyze_screen_for_action` 🆕, `analyze_screen_for_verification` 🆕

**Execution** (5 tools)
- `execute_device_action`, `navigate_to_node`, `verify_device_state`, `execute_edge`, `verify_node`

**Tree Management** (11 tools)
- `create_node`, `update_node`, `delete_node`, `create_edge`, `update_edge`, `delete_edge`, `create_subtree`, `get_node`, `get_edge`, `save_node_screenshot`, `dump_ui_elements`

**Test Management** (9 tools)
- `save_testcase`, `load_testcase`, `list_testcases`, `rename_testcase`, `execute_testcase`, `execute_testcase_by_id`, `execute_script`, `list_scripts`, `generate_test_graph`, `generate_and_save_testcase`

**App & Requirements** (16 tools)
- `create_userinterface`, `list_userinterfaces`, `delete_userinterface`, `list_nodes`, `list_edges`, `get_userinterface_complete`
- `create_requirement`, `update_requirement`, `get_requirement`, `list_requirements`, `link_testcase_to_requirement`, `unlink_testcase_from_requirement`, `get_testcase_requirements`, `get_requirement_coverage`, `get_coverage_summary`, `get_uncovered_requirements`

**Media & Monitoring** (7 tools)
- `capture_screenshot`, `save_node_screenshot`, `get_transcript`, `get_device_info`, `get_compatible_hosts`, `get_execution_status`, `view_logs`, `list_services`

---

## 🔗 Integration Options

### 1. Cursor IDE ⭐ PRIMARY
Native MCP integration via `~/.cursor/mcp.json`  
→ [Setup Guide](mcp_core.md#integration-with-llms)

### 2. Claude Desktop
HTTP MCP client configuration  
→ [Setup Guide](mcp_core.md#integration-with-llms)

### 3. MCP Playground
Web interface with voice input (mobile-first)  
→ [Full Documentation](mcp_playground.md)

---

## ⚠️ Important Notes

### Critical Prerequisites
- **`take_control` MUST be called first** before any device operations
- Bearer token authentication required for all endpoints
- Tree cache required for navigation operations

→ [Control Tools](mcp_tools_control.md)

### Smart Defaults
Most tools support optional parameters with sensible defaults:
- `team_id` → `team_1`
- `host_name` → `host1`
- `device_id` → `device_1`

→ [Core Documentation - Smart Defaults](mcp_core.md#smart-defaults--configuration)

---

## 📊 Statistics

- **Total Tools**: 75
- **Tool Categories**: 15
- **Documentation Pages**: 15+
- **Supported Integrations**: 3 (Cursor, Claude Desktop, MCP Playground)
- **Lines of Documentation**: 5,000+
- **MCP Server Code**: 351 lines (refactored from 2,028 lines)
- **Platform-Specific Prompts**: 4 (Generic, Web, Mobile, TV/STB)

---

## 🆘 Troubleshooting

### Common Issues

**Authentication errors**  
→ [Core Documentation - Troubleshooting](mcp_core.md#troubleshooting)

**Device not found**  
→ [Control Tools - Prerequisites](mcp_tools_control.md)

**Navigation failures**  
→ [Navigation Tools](mcp_tools_navigation.md)

**Verification issues**  
→ [Verification Tools](mcp_tools_verification.md)

### Debug Tools

**See what's on screen**  
→ `dump_ui_elements` in [Tree Tools](mcp_tools_tree.md#dump_ui_elements)

**Check device capabilities**  
→ `get_device_info` in [Core Documentation](mcp_core.md)

**View system logs**  
→ `view_logs` in [Core Documentation](mcp_core.md)

---

## 📞 Support

For issues or questions:
1. Check the relevant tool documentation
2. Review [Core Documentation - Troubleshooting](mcp_core.md#troubleshooting)
3. Check system logs via `view_logs`
4. Open an issue on GitHub

---

## 📝 Quick Start Templates

Platform-specific automation prompts with AI Exploration:

- **Generic Automation Prompt** - Universal template
- **Web Automation Prompt** - CSS selectors, click patterns, form handling
- **Mobile Automation Prompt** - Touch, swipe, resource-id, deep navigation
- **TV/STB Automation Prompt** - D-pad, dual-layer, subtrees, IR devices

**Example use cases:**
- Sauce Demo (E-commerce) - Complete web automation example

---

## 📈 Version History

- **v4.7.0** (2025-11-22): 75 tools (+ AI Exploration: start_ai_exploration, approve_exploration_plan, validate_exploration_edges, get_node_verification_suggestions, approve_node_verifications, finalize_exploration, get_exploration_status)
- **v4.6.0** (2025-11-21): 56 tools (+ analyze_screen_for_action, analyze_screen_for_verification - unified selector scoring + shared/src/lib/utils/selector_scoring.py)
- **v4.5.0** (2025-11-18): 54 tools (+ generate_and_save_testcase, rename_testcase, get_compatible_hosts + MCP server refactor: 327 lines)
- **v4.4.0** (2025-11): 51 tools (+ preview_userinterface - "What do we test?")
- **v4.3.0** (2025-11): 49 tools (+ requirements management)
- **v4.2.1** (2025-11): 39 tools (documentation alignment)
- **v4.2.0** (2025-11): 39 tools (+ execute_edge & verify_node)
- **v4.1.0** (2025-01): 35 tools (+ userinterface management)
- **v4.0.0** (2025-01): 29 tools (+ primitive tree tools)
- **v3.0.0** (2025-01): 21 tools (+ discovery & web UI)
- **v2.0.0** (2025-01): 11 tools (production-ready)
- **v1.0.0** (2024): 11 tools (basic automation)

→ [Full Version History](mcp_core.md#version-history)

---

**Made with ❤️ by the VirtualPyTest team**

---

## 📁 File Structure

```
docs/
├── mcp.md (this file)                # Main index & navigation
├── mcp/
│   ├── mcp_core.md                   # Core: Overview, architecture, setup
│   ├── mcp_security.md               # Security: sensitive file protection (3-layer)
│   ├── mcp_tools_control.md          # take_control (CRITICAL FIRST)
│   ├── mcp_tools_action.md           # execute_device_action, list_actions
│   ├── mcp_tools_navigation.md       # navigate_to_node, list_navigation_nodes
│   ├── mcp_tools_verification.md     # verify_device_state, verify_node, list_verifications
│   ├── mcp_tools_exploration.md      # 7 AI exploration tools (RECOMMENDED) ⭐
│   ├── mcp_tools_screen_analysis.md  # analyze_screen_for_action, analyze_screen_for_verification
│   ├── mcp_tools_tree.md             # 11 primitive tools (create/update/delete node/edge)
│   ├── mcp_tools_testcase.md         # save/load/list/execute testcases
│   ├── mcp_tools_script.md           # execute_script, list_scripts
│   ├── mcp_tools_ai.md               # generate_test_graph, generate_and_save_testcase
│   ├── mcp_tools_screenshot.md       # capture_screenshot, save_node_screenshot
│   ├── mcp_tools_userinterface.md    # create/list/delete userinterfaces
│   ├── mcp_tools_requirements.md     # 10 requirements management tools
│   └── mcp_playground.md             # Web interface documentation
└── docs_new/
    ├── automate-prompt.md            # Generic automation template
    ├── automate-prompt-web.md        # Web-specific template
    ├── automate-prompt-mobile.md     # Mobile-specific template
    ├── automate-prompt-tv.md         # TV/STB-specific template
    └── demo/
        ├── sauce-demo-optimal-prompt.md   # Complete e-commerce example
        └── sauce-demo-clean-prompt.md     # Manual approach (legacy)
```
