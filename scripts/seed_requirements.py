#!/usr/bin/env python3
"""
Seed VirtualPyTest platform requirements and link automation scripts + testcases.

Requirements = VPT PLATFORM CAPABILITIES (what the platform can do).
Scripts/testcases in the system are linked as coverage evidence.

─────────────────────────────────────────────────────────────────────────────
REQUIREMENT CODE CONVENTION:  VPT-[WHAT-WE-TEST]-[WHAT-WE-DO]-[NNN]
─────────────────────────────────────────────────────────────────────────────

  VPT-SCRIPT-EXECUTION-001          Test the script runner / do execute scripts
  VPT-HOST-DEVICE-STACK-001         Test host+device stack / do registration & access
  VPT-CAMPAIGN-EXECUTION-001        Test campaigns / do multi-step ordered execution
  VPT-WEB-APP-AUTOMATION-001        Test web apps / do browser automation
  VPT-NETWORK-DIAGNOSTICS-001       Test network (gateway) / do performance diagnostics
  VPT-VIDEO-STREAM-VERIFICATION-001 Test video streams / do HLS stream verification
  VPT-NETWORK-DIAGNOSTICS-002       Test network (server) / do infra reachability
  VPT-API-ENDPOINT-TESTING-001      Test APIs / do endpoint validation
  VPT-UI-PAGE-ACCESS-001            Test UI pages / do accessibility check
  VPT-MONITORING-HEATMAP-001        Test monitoring / do heatmap & alert access

─────────────────────────────────────────────────────────────────────────────
TESTCASE CODE RANGES  (script_identity_map.json)
─────────────────────────────────────────────────────────────────────────────
  TC000–TC049  gw/     gateway / network scripts
  TC050–TC099  vpt/    VPT self-test scripts
  TC100–TC199  tv/     TV / set-top box scripts
  TC200–TC299  web/    web / browser scripts
  TC300–TC399  mobile/ mobile scripts
  TC400–TC499  api/    API / generic scripts

─────────────────────────────────────────────────────────────────────────────
RUN
─────────────────────────────────────────────────────────────────────────────
  SERVER_URL=http://localhost:5109 \\
  API_KEY=<key> \\
  python3 scripts/seed_requirements.py
"""

import os
import sys
import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ── Config ────────────────────────────────────────────────────────────────────

SERVER_URL = os.environ.get("SERVER_URL", "http://localhost:5109").rstrip("/")
TEAM_ID    = os.environ.get("TEAM_ID", "7fdeb4bb-3639-4ec3-959f-b54769a219ce")
API_KEY    = os.environ.get("API_KEY", "")
VERIFY_SSL = os.environ.get("VERIFY_SSL", "false").lower() in {"1", "true", "yes"}

HEADERS = {"Content-Type": "application/json"}
if API_KEY:
    HEADERS["X-API-Key"] = API_KEY
    HEADERS["Authorization"] = f"Bearer {API_KEY}"

# ── Requirements ──────────────────────────────────────────────────────────────
# "scripts"   → (script_name, coverage_type, notes)  linked via /link-script
# "testcases" → script_name values matched to testcase_definitions in DB

REQUIREMENTS = [
    {
        "requirement_code": "VPT-SCRIPT-EXECUTION-001",
        "requirement_name": "Script Execution",
        "category": "testing",
        "priority": "P1",
        "description": (
            "The platform must schedule and execute automation scripts, "
            "capture output, and persist pass/fail results."
        ),
        "acceptance_criteria": [
            "Script runs to completion without platform errors",
            "Pass/fail result is recorded and visible in reports",
            "Script logs are captured and stored",
        ],
        "app_type": "all",
        "device_model": "all",
        "status": "active",
        "scripts": [
            ("validation",        "full",    "Baseline validation — confirms execution pipeline"),
            ("kpi_measurement",   "partial", "KPI measurement — confirms result capture"),
            ("api/api_test",      "partial", "API test via execution pipeline"),
            ("api/run_api_tests", "partial", "Batch API test execution"),
        ],
        "testcases": ["validation", "kpi_measurement", "api/api_test", "api/run_api_tests"],
    },
    {
        "requirement_code": "VPT-HOST-DEVICE-STACK-001",
        "requirement_name": "Host & Device Stack",
        "category": "device",
        "priority": "P1",
        "description": (
            "At least one host must be registered and reachable, expose at least one "
            "device, and allow device-info retrieval through the host API."
        ),
        "acceptance_criteria": [
            "getAllHosts returns at least one registered host",
            "Host /health endpoint responds with HTTP 200",
            "Host device list returns at least one device",
            "Device info for the first device is retrievable",
        ],
        "app_type": "all",
        "device_model": "all",
        "status": "active",
        "scripts": [
            ("vpt/smoke_device_control", "full", "Verifies host registration, health, and device list"),
            ("device_get_info",          "partial", "Queries device state — confirms device communication"),
        ],
        "testcases": ["vpt/smoke_device_control", "device_get_info"],
    },
    {
        "requirement_code": "VPT-CAMPAIGN-EXECUTION-001",
        "requirement_name": "Campaign Execution",
        "category": "testing",
        "priority": "P1",
        "description": (
            "The platform must execute a campaign (ordered list of scripts) in sequence, "
            "aggregate results, and report overall pass/fail."
        ),
        "acceptance_criteria": [
            "Campaign runs all steps in order",
            "Individual step results are linked to the campaign run",
            "Campaign summary reports overall pass rate",
        ],
        "app_type": "all",
        "device_model": "all",
        "status": "active",
        "scripts": [],     # P1 gap — no campaign runner script yet
        "testcases": [],
    },
    {
        "requirement_code": "VPT-WEB-APP-AUTOMATION-001",
        "requirement_name": "Web Application Automation",
        "category": "device",
        "priority": "P2",
        "description": (
            "The platform must control a browser on a connected web device and execute "
            "end-to-end web application test scripts."
        ),
        "acceptance_criteria": [
            "Browser opens target URL without errors",
            "Automated interactions (click, fill, navigate) execute on web elements",
            "Test result reflects actual page state",
        ],
        "app_type": "streaming",
        "device_model": "web",
        "status": "active",
        "scripts": [
            ("web/browser_task",        "full",    "Generic browser automation"),
            ("web/facebook_check",      "partial", "Facebook web check"),
            ("web/netflix_video_check", "partial", "Netflix streaming check"),
            ("web/youtube_video_check", "partial", "YouTube streaming check"),
        ],
        "testcases": [
            "web/browser_task", "web/facebook_check",
            "web/netflix_video_check", "web/youtube_video_check",
        ],
    },
    {
        "requirement_code": "VPT-NETWORK-DIAGNOSTICS-001",
        "requirement_name": "Network Performance Diagnostics (Gateway)",
        "category": "testing",
        "priority": "P2",
        "description": (
            "The platform must run network performance tests through a gateway device: "
            "DNS response time, speed tests, ping, UDP latency, and LAN diagnostics."
        ),
        "acceptance_criteria": [
            "Speed test returns download/upload values",
            "Superping reports RTT, packet loss, and a quality score",
            "DNS lookup time is measured and recorded",
            "UDP latency test completes successfully",
        ],
        "app_type": "all",
        "device_model": "all",
        "status": "active",
        "scripts": [
            ("gw/superping",                          "full",    "RTT, packet loss, quality score"),
            ("gw/dns_lookuptime",                     "full",    "DNS resolution time"),
            ("gw/ookla_speedtest",                    "full",    "Download/upload speed"),
            ("gw/udp_latency",                        "full",    "UDP latency"),
            ("gw/gw_info",                            "partial", "Gateway system info"),
            ("gw/gw_info_gui",                        "partial", "Gateway info via GUI"),
            ("gw/gw_network_connect",                 "partial", "Network connectivity check"),
            ("gw/windows_lan_connection_information", "partial", "Windows LAN diagnostics"),
            ("gw/windows_networkassessmenttools",     "partial", "Windows network assessment"),
        ],
        "testcases": [
            "gw/superping", "gw/dns_lookuptime", "gw/ookla_speedtest", "gw/udp_latency",
            "gw/gw_info", "gw/gw_info_gui", "gw/gw_network_connect",
            "gw/windows_lan_connection_information", "gw/windows_networkassessmenttools",
        ],
    },
    {
        "requirement_code": "VPT-VIDEO-STREAM-VERIFICATION-001",
        "requirement_name": "Video Stream Verification",
        "category": "device",
        "priority": "P2",
        "description": (
            "The platform must serve a live HLS video stream for each connected device. "
            "The stream must be accessible as a valid m3u8 playlist with downloadable segments — "
            "this is what the Device Control page (RecHostPreview / RecHostStreamModal) relies on."
        ),
        "acceptance_criteria": [
            "Host returns a stream URL for the device",
            "GET stream URL returns HTTP 200 with HLS content type",
            "Playlist contains at least one video segment",
            "A video segment (.ts) is downloadable",
        ],
        "app_type": "all",
        "device_model": "all",
        "status": "active",
        "scripts": [
            ("vpt/smoke_video_stream", "full", "Verifies HLS stream URL, playlist, and segment download"),
        ],
        "testcases": ["vpt/smoke_video_stream"],
    },
    {
        "requirement_code": "VPT-NETWORK-DIAGNOSTICS-002",
        "requirement_name": "Infrastructure Reachability (Server)",
        "category": "monitoring",
        "priority": "P2",
        "description": (
            "The server/host machine must be able to reach all VPT infrastructure "
            "dependencies: Supabase (database), Cloudflare R2 (storage), "
            "OpenRouter (AI), GitHub (code deployment), and Redis (task queue)."
        ),
        "acceptance_criteria": [
            "DNS resolves supabase.co, pub.r2.dev, openrouter.ai, github.com",
            "TCP connects to GitHub:443 and OpenRouter:443",
            "Redis port is reachable on the configured host",
        ],
        "app_type": "all",
        "device_model": "all",
        "status": "active",
        "scripts": [
            ("vpt/smoke_network_server", "full", "DNS + TCP checks to all VPT infrastructure endpoints"),
        ],
        "testcases": ["vpt/smoke_network_server"],
    },
    {
        "requirement_code": "VPT-API-ENDPOINT-TESTING-001",
        "requirement_name": "API Endpoint Testing",
        "category": "testing",
        "priority": "P2",
        "description": (
            "The platform must execute HTTP API test suites against backend services "
            "and report pass/fail per endpoint."
        ),
        "acceptance_criteria": [
            "API test runs all configured endpoint checks",
            "Each endpoint result (status code, body) is captured",
            "Failures are clearly reported with endpoint and status info",
        ],
        "app_type": "all",
        "device_model": "all",
        "status": "active",
        "scripts": [
            ("api/api_test",      "full", "Single API test execution"),
            ("api/run_api_tests", "full", "Batch API test run"),
        ],
        "testcases": ["api/api_test", "api/run_api_tests"],
    },
    {
        "requirement_code": "VPT-UI-PAGE-ACCESS-001",
        "requirement_name": "UI Pages Accessible",
        "category": "dashboard",
        "priority": "P1",
        "description": (
            "Every major page in the VirtualPyTest web interface must have a "
            "working backing API endpoint so the page can load its data."
        ),
        "acceptance_criteria": [
            "Dashboard, Device Control, Run Tests, Campaigns, Test Cases, Requirements, "
            "Coverage, Incidents, Code Deployment, Interface and Models pages all return HTTP 200",
            "Average API response time under 2 000 ms",
        ],
        "app_type": "all",
        "device_model": "all",
        "status": "active",
        "scripts": [
            ("vpt/smoke_ui", "full", "Hits every VPT page's backing API and confirms HTTP 200"),
        ],
        "testcases": ["vpt/smoke_ui"],
    },
    {
        "requirement_code": "VPT-MONITORING-HEATMAP-001",
        "requirement_name": "Monitoring & Heatmap",
        "category": "monitoring",
        "priority": "P2",
        "description": (
            "The heatmap history, alert list, and recent execution endpoints must respond "
            "so the Heatmap and Incidents pages have working data sources."
        ),
        "acceptance_criteria": [
            "GET /server/heatmap/history returns HTTP 200",
            "GET /server/alerts/getAllAlerts returns HTTP 200",
            "GET /server/alerts/getActiveAlerts returns HTTP 200",
            "GET /server/deployment/executions/recent returns HTTP 200",
        ],
        "app_type": "all",
        "device_model": "all",
        "status": "active",
        "scripts": [
            ("vpt/smoke_heatmap", "full", "Checks all heatmap and monitoring endpoints"),
        ],
        "testcases": ["vpt/smoke_heatmap"],
    },
]

# ── Helpers ───────────────────────────────────────────────────────────────────

def api_post(path: str, body: dict) -> dict:
    resp = requests.post(f"{SERVER_URL}{path}", json=body, headers=HEADERS, verify=VERIFY_SSL, timeout=15)
    try:
        return resp.json()
    except Exception:
        return {"success": False, "error": resp.text}


def api_get(path: str, params: dict | None = None) -> dict:
    resp = requests.get(f"{SERVER_URL}{path}", params=params, headers=HEADERS, verify=VERIFY_SSL, timeout=15)
    try:
        return resp.json()
    except Exception:
        return {"success": False, "error": resp.text}


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    print(f"Server : {SERVER_URL}")
    print(f"Team   : {TEAM_ID}\n")

    if api_get("/server/health").get("status") not in {"ok", "healthy"}:
        print("ERROR: server not healthy"); sys.exit(1)
    print("Server is healthy\n")

    existing = {r["requirement_code"]: r
                for r in api_get("/server/requirements/list", {"team_id": TEAM_ID}).get("requirements", [])}

    # Build script_name → testcase_id map from DB
    testcases_by_script: dict[str, str] = {}
    for tc in api_get("/server/testcase/list", {"team_id": TEAM_ID}).get("testcases", []):
        name = tc.get("testcase_name", "").replace(".py", "").strip("/")
        if name and tc.get("testcase_id"):
            testcases_by_script[name] = tc["testcase_id"]
    print(f"Found {len(testcases_by_script)} testcases in DB for linking\n")

    print("=== Seeding platform requirements ===")
    created = skipped = s_linked = tc_linked = errors = 0

    for req in REQUIREMENTS:
        code      = req["requirement_code"]
        scripts   = req.pop("scripts")
        testcases = req.pop("testcases")

        if code in existing and existing[code]["status"] == "active":
            print(f"  SKIP   {code}")
            skipped += 1
            req_id = existing[code]["requirement_id"]
        else:
            r = api_post("/server/requirements/create", {**req, "team_id": TEAM_ID})
            if r.get("success"):
                req_id = r["requirement_id"]
                print(f"  CREATE {code} — {req['requirement_name']}")
                created += 1
            else:
                print(f"  ERROR  {code}: {r.get('error', r)}")
                errors += 1
                continue

        for script_name, coverage_type, notes in scripts:
            r = api_post("/server/requirements/link-script", {
                "team_id": TEAM_ID, "requirement_id": req_id,
                "script_name": script_name, "coverage_type": coverage_type, "coverage_notes": notes,
            })
            if r.get("success"):
                print(f"         ↳ script  {script_name}  [{coverage_type}]"); s_linked += 1
            elif any(w in str(r.get("error", "")).lower() for w in ("already", "duplicate", "unique")):
                print(f"         ↳ script  {script_name}  [already linked]")
            else:
                print(f"         ↳ ERR     {script_name}: {r.get('error', r)}"); errors += 1

        for tc_name in testcases:
            tc_id = testcases_by_script.get(tc_name)
            if not tc_id:
                continue
            r = api_post("/server/requirements/link-testcase", {
                "team_id": TEAM_ID, "requirement_id": req_id,
                "testcase_id": tc_id, "coverage_type": "full",
            })
            if r.get("success"):
                print(f"         ↳ testcase {tc_name}  [full]"); tc_linked += 1
            elif any(w in str(r.get("error", "")).lower() for w in ("already", "duplicate", "unique")):
                print(f"         ↳ testcase {tc_name}  [already linked]")
            else:
                print(f"         ↳ ERR tc  {tc_name}: {r.get('error', r)}"); errors += 1

    print(f"\nDone — created={created}  skipped={skipped}  "
          f"scripts_linked={s_linked}  testcases_linked={tc_linked}  errors={errors}")


if __name__ == "__main__":
    main()
