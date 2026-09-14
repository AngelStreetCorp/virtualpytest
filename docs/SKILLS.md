# VirtualPyTest Skills

## Format

Skills use the **SKILL.md** format (OpenClaw/Agent Skills compatible):

```
backend_server/src/agent/skills/definitions/
├── crawl-app/
│   └── SKILL.md
├── build-tree-web/
│   └── SKILL.md
├── control-device/
│   └── SKILL.md
└── ...
```

Each `SKILL.md` has YAML frontmatter (name, description, tools, triggers) + markdown body (instructions for the AI).

### Naming convention

Format: `{action}-{subject}` — reads like a command.

## Skills (12 device-coupled)

| Skill | Platform | Tools | What it does |
|-------|----------|-------|-------------|
| `crawl-app` | any | 9 | BFS crawl web/Android app to discover screens |
| `build-tree-web` | web | 28 | Build navigation tree on web device |
| `build-tree-mobile` | mobile | 38 | Build navigation tree on mobile device |
| `build-tree-stb` | stb | 23 | Build navigation tree on STB/TV device |
| `edit-tree` | — | 12 | CRUD tree nodes and edges |
| `navigate-tree` | — | 7 | Navigate using existing tree |
| `control-device` | — | 4 | Direct hardware actions (click, tap, swipe) |
| `manage-campaign` | — | 7 | CRUD test campaigns |
| `manage-script` | — | 3 | List/execute Python scripts |
| `check-system-health` | — | 2 | Device/host health status |
| `search-docs` | — | 3 | Search VPT documentation |
| `navigate-vpt-ui` | — | 6 | Navigate VPT's frontend pages |

## Migrated to QualiAi

The following intelligence skills have moved to QualiAi (the AI brain):

| Skill | Why it moved |
|-------|-------------|
| `generate-requirements` | AI reasoning — generates test strategy from app map |
| `build-testcase` | AI reasoning — builds graph_json from requirements |
| `manage-testcase` | QualiAi manages test cases in its own DB |
| `manage-requirements` | QualiAi manages requirements with VPT DB + own DB |
| `review-result` | AI reasoning — classifies test results |
| `review-incident` | AI reasoning — analyzes incidents |

QualiAi calls VPT's MCP tools for device operations. The intelligence lives in QualiAi.

## Background handlers (stay in VPT)

| Handler | What it does |
|---------|-------------|
| `sherlock_handler.py` | Automated batch result analysis (policy-driven, background) |
| `nightwatch_handler.py` | Automated alert processing (rate-limited, background) |

These are operational — they run continuously without user interaction.
