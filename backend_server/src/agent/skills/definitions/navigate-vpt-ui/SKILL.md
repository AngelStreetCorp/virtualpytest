---
name: navigate-vpt-ui
description: Navigate and interact with frontend pages
tools:
  - get_available_pages
  - get_page_schema
  - navigate_to_page
  - show_page
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
  - open the reports for
  - show me the results
  - companion
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
3b) show_page(page, params) → offer or open a filtered page in the companion
5) interact_with_element(element_id, action, params) → click/filter/interact with page elements
6) show_toast(message, severity) → show notification

COMPANION (show a real page, already filtered, beside the chat):
1) Pick the page: get_available_pages() lists `key — what it answers [params]`.
2) Resolve names to exact values: "pi4 web tv" → host=vpt-pi4, device=web_tv via list_hosts; scripts via get_execution_results.
   Enum params take only the listed values.
3) Answer in the chat with the page's data tool (get_page_schema shows it), numbers first. The page is never the answer on its own.
4) Call show_page(page, params, path_args?, open_now?). open_now only when the user asked to open the page.
Your context has a line "Page shown beside the chat: <page> — k=v, …": that page is shown. A follow-up ("only failed", "same for pi1") is
show_page with the same page and the changed params.

USAGE:
User: "test results for pi4 web_tv this week" → answer, then show_page("test_reports", {"host":"vpt-pi4","device":"web_tv","range":"7d"})
User: "open the reports for pi4" → show_page("test_reports", {"host":"vpt-pi4"}, open_now=true)
User: "show me the dashboard" → navigate_to_page("dashboard")
User: "go to reports page" → navigate_to_page("reports")
User: "open test builder" → navigate_to_page("test builder")
