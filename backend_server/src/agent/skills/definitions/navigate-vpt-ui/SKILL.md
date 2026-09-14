---
name: navigate-vpt-ui
description: Navigate and interact with frontend pages
tools:
  - get_available_pages
  - get_page_schema
  - navigate_to_page
  - highlight_element
  - interact_with_element
  - show_toast
triggers:
  - show me the page
  - open the page
  - take me to page
  - navigate frontend
  - show frontend
  - open frontend
  - go to page
  - goto page
  - page navigation
  - frontend navigation
  - ui page
  - web page
  - highlight element
  - click element
  - interact with ui element
  - show toast
  - dashboard
  - reports page
  - builder page
  - monitoring page
---

# Navigate Vpt Ui

FRONTEND PAGE NAVIGATION WORKFLOW
Navigate the USER'S BROWSER to different frontend pages in the VirtualPyTest web application.

⚠️ SCOPE: This skill is ONLY for frontend web pages (Dashboard, Reports, Builder pages).
⚠️ NOT FOR: Device navigation (that's device-control skill), app exploration (that's explore-* skills)

CONTEXT DETECTION:
- If query mentions: "dashboard", "reports", "builder", "monitoring", "page", "frontend" → Use this skill
- If query mentions: "device", "node", "app screen", "userinterface", "tree" → NOT this skill

TOOLS:
1) get_available_pages() → list all navigable frontend pages
2) get_page_schema(page_path) → get interactive elements on a page
3) navigate_to_page(page_name, context) → navigate user's browser
   - Works with: "dashboard", "reports", "heatmap", "test builder", etc.
   - Automatically handles: "show me reports", "go to dashboard page"
4) highlight_element(element_id) → highlight UI element
5) interact_with_element(element_id, action, params) → click/filter/interact with page elements
6) show_toast(message, severity) → show notification

AVAILABLE FRONTEND PAGES:
- Dashboard, Device Control, AI Agent, Agent Dashboard
- Test Builder, Campaign Builder, Navigation Editor, MCP Playground
- Test Cases, Campaigns, Requirements, Coverage
- Run Tests, Run Campaigns, Deployments
- Incidents, Heatmap, AI Queue, System Monitoring
- Test Reports, Campaign Reports, Model Reports, Dependency Report

USAGE:
User: "show me the dashboard" → navigate_to_page("dashboard")
User: "go to reports page" → navigate_to_page("reports")
User: "open test builder" → navigate_to_page("test builder")
