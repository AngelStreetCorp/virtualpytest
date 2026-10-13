# Map Builder Tool (1 tool)

**`auto_discover_screen` builds a map of the device's current screen**: one node per screen reachable
from it, one edge each, every edge validated on the device. It is the engine behind the navigation
editor's **Build Map** button, run without the review steps.

It is **a rule-based mapping process, not an AI agent.** Read the next section before using it from an
agent.

---

## Map builder vs agent pipeline

VirtualPyTest has two different ways to build a navigation tree. Keep them apart: one is a tool, the
other is a plan that may call that tool.

| | Map builder | Agent pipeline |
|---|---|---|
| What it is | A fixed process: read the screen, propose targets, create, validate | An LLM agent that decides what to do and calls MCP tools |
| Where | Editor **Build Map** button; MCP `auto_discover_screen` | Atlas with the `build-tree-mobile` / `-web` / `-stb` skills; QualiAI (separate product, drives VPT through REST + `/server/mcp`) |
| AI model | **None on Android and web.** TV/STB only: a vision model reads the menu from the screenshot (no UI dump exists there) | Every decision |
| Decides | Nothing: rules choose the targets, a fixed order tries the ways back | Which app and start screen, which proposals to keep, how to repair a failed edge, when to go deeper |
| Scope | The current screen, one level | Whatever the agent plans |
| Repeatable | Same screen gives the same map | Depends on the model |

An agent that calls `auto_discover_screen` gets a map, not a judgement: what to keep and what to fix
stays the agent's job.

## How the map is built

| Step | Android / web (no model) | TV / STB |
|---|---|---|
| 1. Read the screen | UI dump of the **app's own window** (status bar, navigation bar, launcher dropped) | Screenshot → vision model (`vision.dom`) lists the menu items |
| 2. Choose targets | Tappable elements, the app's fixed navigation (tab bar, toolbar) before list items; list rows only when fewer than 3 | The menu items in their rows |
| 3. Create | One node per target; forward edge = tap the label, way back = BACK | Forward = D-pad moves + OK; way back = BACK + reverse move |
| 4. Validate each edge | Tap; then try the entry edge's taps (e.g. tap Home), BACK, BACK ×2, until **every** validated item shows in the app's window again; the step that worked becomes the edge's way back | D-pad, then BACK, checked on the screen |
| 5. Node checks (editor only) | Text only that screen shows, from the dumps (`dump_analyzer`, no model) | Text/image references |

Code: `backend_host/src/services/ai_exploration/` (`screen_analyzer.py`, `phases/validation_runner.py`,
`phases/verification_manager.py`). The folder name predates this split; the Android/web path does not
call a model.

## `auto_discover_screen`

```
auto_discover_screen(tree_id, host_name, userinterface_name, device_id='device1', parent_node_id='home')
```

Runs, on the host, the same calls as the editor: Start → Create (**every** proposal is accepted) →
validation of every edge. Returns the created nodes and edges and one validation result per item.

Compared with the editor's Build Map it skips:

- the review of the proposals (the editor lets the user untick one, e.g. a cast picker);
- node verifications (*Review Node Verifications*);
- *Confirm & Save*, so node labels keep their `_temp` suffix.

### Before calling it

- The interface's entry edge (`Entry → home`) must have actions. For an Android app:
  `close_app`, `launch_app`, then a tap on the app's Home tab when the app reopens on its last tab.
  Without actions the call fails with a message saying so.
- The device must be on the start node's screen, or reachable through the entry edge.

### After calling it

- Read `validation_results`: an item whose forward tap failed, or whose way back is empty, needs a fix
  (`update_edge`, see [Tree tools](mcp_tools_tree.md)).
- Add node verifications (`update_node`) and drop the `_temp` suffix from labels yourself, or finish
  from the editor.

## Related

- [Tree tools](mcp_tools_tree.md): create, update and delete nodes and edges by hand.
- `docs/technical/ai/tree-creation.md`: the editor flow (Build Map modal → validation → node
  verifications → Confirm & Save).
- `backend_server/src/agent/skills/definitions/build-tree-*/SKILL.md`: the agent pipeline's skills.
