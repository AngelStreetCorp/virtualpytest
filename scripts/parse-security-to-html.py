#!/usr/bin/env python3

"""
Parse security reports into interactive HTML with filters and collapsible sections
"""

import fnmatch
import json
from datetime import datetime
from pathlib import Path

try:
    import yaml
except ImportError:  # pyyaml is in backend_server/requirements.txt
    yaml = None

DOCS_SECURITY = Path("docs/security")
TEMP_DIR = DOCS_SECURITY / "temp"

HOST_BANDIT_JSON = TEMP_DIR / "host_bandit.json"
SERVER_BANDIT_JSON = TEMP_DIR / "server_bandit.json"
SHARED_BANDIT_JSON = TEMP_DIR / "shared_bandit.json"
FRONTEND_AUDIT_JSON = TEMP_DIR / "frontend_audit.json"
SNYK_HOST_JSON = TEMP_DIR / "snyk_host_code.json"
SNYK_SERVER_JSON = TEMP_DIR / "snyk_server_code.json"
SNYK_SHARED_JSON = TEMP_DIR / "snyk_shared_code.json"

OUTPUT_HTML = DOCS_SECURITY / "index.html"
OUTPUT_HOST_JSON = DOCS_SECURITY / "host-report.json"
OUTPUT_SERVER_JSON = DOCS_SECURITY / "server-report.json"
OUTPUT_SHARED_JSON = DOCS_SECURITY / "shared-report.json"
OUTPUT_FRONTEND_JSON = DOCS_SECURITY / "frontend-report.json"
OUTPUT_SNYK_HOST_JSON = DOCS_SECURITY / "snyk-host-report.json"
OUTPUT_SNYK_SERVER_JSON = DOCS_SECURITY / "snyk-server-report.json"
OUTPUT_SNYK_SHARED_JSON = DOCS_SECURITY / "snyk-shared-report.json"

# Repo-root Snyk policy. The Snyk CLI honours it on its own scans; we also apply it
# here so the committed dashboard reflects the same triage decisions.
SNYK_POLICY = Path(".snyk")


def load_snyk_ignores():
    """Return [(rule_id, path_glob)] from the `ignore:` block of .snyk (repo-root relative)."""
    if yaml is None or not SNYK_POLICY.exists():
        return []
    data = yaml.safe_load(SNYK_POLICY.read_text()) or {}
    ignores = []
    for rule_id, entries in (data.get('ignore') or {}).items():
        for entry in entries or []:
            for path_glob in (entry or {}).keys():
                ignores.append((rule_id, path_glob))
    return ignores


def is_ignored(rule_id, repo_path, ignores):
    for ign_rule, path_glob in ignores:
        if ign_rule == rule_id and (path_glob == '*' or fnmatch.fnmatch(repo_path, path_glob)):
            return True
    return False


def parse_bandit_report(json_path, fallback_path=None):
    path_to_use = json_path if json_path.exists() else fallback_path
    if not path_to_use or not path_to_use.exists():
        return None
    
    with open(path_to_use, 'r') as f:
        data = json.load(f)
    
    metrics = data.get('metrics', {}).get('_totals', {})
    results = data.get('results', [])
    
    return {
        'metrics': metrics,
        'results': results,
        'raw_data': data
    }


def parse_npm_audit(json_path, fallback_path=None):
    path_to_use = json_path if json_path.exists() else fallback_path
    if not path_to_use or not path_to_use.exists():
        return None
    
    try:
        with open(path_to_use, 'r') as f:
            data = json.load(f)
        
        if 'error' in data:
            return {'status': 'error', 'vulnerabilities': {}, 'issues': []}
        
        metadata = data.get('metadata', {})
        vuln_counts = metadata.get('vulnerabilities', {})
        
        # Extract issues from vulnerabilities object
        issues = []
        vulns = data.get('vulnerabilities', {})
        for name, info in vulns.items():
            severity = info.get('severity', 'info')
            via = info.get('via', [])
            title = via[0].get('title', name) if via and isinstance(via[0], dict) else name
            issues.append({
                'name': name,
                'severity': severity,
                'title': title,
                'fixAvailable': info.get('fixAvailable', False)
            })
        
        return {
            'status': 'found' if issues else 'clean',
            'counts': vuln_counts,
            'issues': issues,
            'raw_data': data
        }
    except:
        return {'status': 'error', 'vulnerabilities': {}, 'issues': []}


def parse_snyk_sarif(json_path, fallback_path=None, scan_root='', ignores=()):
    """Parse Snyk Code SARIF format output.

    scan_root is the directory that was passed to `snyk code test` (e.g. backend_server/src);
    SARIF URIs are relative to it. Findings matching a .snyk ignore are dropped from
    `results` and counted in `ignored`.
    """
    path_to_use = json_path if json_path.exists() else fallback_path
    if not path_to_use or not path_to_use.exists():
        return None
    
    try:
        with open(path_to_use, 'r') as f:
            data = json.load(f)
        
        if 'error' in data:
            return {'status': 'error', 'results': [], 'raw_data': data}
        
        # SARIF format: runs[0].results contains the findings
        runs = data.get('runs', [])
        if not runs:
            return {'status': 'clean', 'results': [], 'raw_data': data}
        
        sarif_results = runs[0].get('results', [])
        
        # Map SARIF level to severity
        level_to_severity = {
            'error': 'HIGH',
            'warning': 'MEDIUM',
            'note': 'LOW',
            'none': 'LOW'
        }
        
        issues = []
        ignored = 0
        for r in sarif_results:
            rule_id = r.get('ruleId', 'unknown')
            level = r.get('level', 'warning')
            message = r.get('message', {}).get('text', '')[:80]
            
            # Extract location
            locations = r.get('locations', [])
            if locations:
                phys_loc = locations[0].get('physicalLocation', {})
                artifact = phys_loc.get('artifactLocation', {})
                uri = artifact.get('uri', '')
                # Clean up file path
                filename = uri.replace('file://', '').split('backend_host/')[-1].split('backend_server/')[-1]
                region = phys_loc.get('region', {})
                line = region.get('startLine', 0)
            else:
                filename = 'unknown'
                line = 0

            repo_path = uri.replace('file://', '')
            if scan_root and not repo_path.startswith(scan_root):
                repo_path = f"{scan_root}/{repo_path}"
            if is_ignored(rule_id, repo_path, ignores):
                ignored += 1
                continue
            
            issues.append({
                'rule_id': rule_id,
                'severity': level_to_severity.get(level, 'MEDIUM'),
                'message': message,
                'filename': filename,
                'line': line
            })
        
        return {
            'status': 'found' if issues else 'clean',
            'results': issues,
            'ignored': ignored,
            'raw_data': data
        }
    except Exception as e:
        return {'status': 'error', 'results': [], 'raw_data': {'error': str(e)}}


def generate_html_report():
    host_bandit = parse_bandit_report(HOST_BANDIT_JSON, OUTPUT_HOST_JSON)
    server_bandit = parse_bandit_report(SERVER_BANDIT_JSON, OUTPUT_SERVER_JSON)
    shared_bandit = parse_bandit_report(SHARED_BANDIT_JSON, OUTPUT_SHARED_JSON)
    frontend_audit = parse_npm_audit(FRONTEND_AUDIT_JSON, OUTPUT_FRONTEND_JSON)
    ignores = load_snyk_ignores()
    snyk_host = parse_snyk_sarif(SNYK_HOST_JSON, OUTPUT_SNYK_HOST_JSON, 'backend_host/src', ignores)
    snyk_server = parse_snyk_sarif(SNYK_SERVER_JSON, OUTPUT_SNYK_SERVER_JSON, 'backend_server/src', ignores)
    snyk_shared = parse_snyk_sarif(SNYK_SHARED_JSON, OUTPUT_SNYK_SHARED_JSON, 'shared/src', ignores)

    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M')

    # Calculate metrics
    host_results = host_bandit.get('results', []) if host_bandit else []
    server_results = server_bandit.get('results', []) if server_bandit else []
    shared_results = shared_bandit.get('results', []) if shared_bandit else []
    frontend_issues = frontend_audit.get('issues', []) if frontend_audit else []
    snyk_host_results = snyk_host.get('results', []) if snyk_host else []
    snyk_server_results = snyk_server.get('results', []) if snyk_server else []
    snyk_shared_results = snyk_shared.get('results', []) if snyk_shared else []
    snyk_host_ignored = snyk_host.get('ignored', 0) if snyk_host else 0
    snyk_server_ignored = snyk_server.get('ignored', 0) if snyk_server else 0
    snyk_shared_ignored = snyk_shared.get('ignored', 0) if snyk_shared else 0

    def ignored_badge(n):
        return f'<span class="ignored" title="suppressed by .snyk">· {n} ignored</span>' if n else ''

    host_loc = host_bandit['metrics'].get('loc', 0) if host_bandit else 0
    server_loc = server_bandit['metrics'].get('loc', 0) if server_bandit else 0
    shared_loc = shared_bandit['metrics'].get('loc', 0) if shared_bandit else 0
    total_loc = host_loc + server_loc + shared_loc
    
    # Count by severity for Bandit
    def count_severity(results):
        return {
            'high': len([r for r in results if r.get('issue_severity') == 'HIGH']),
            'medium': len([r for r in results if r.get('issue_severity') == 'MEDIUM']),
            'low': len([r for r in results if r.get('issue_severity') == 'LOW'])
        }
    
    # Count by severity for Snyk (uses 'severity' key)
    def count_snyk_severity(results):
        return {
            'high': len([r for r in results if r.get('severity') == 'HIGH']),
            'medium': len([r for r in results if r.get('severity') == 'MEDIUM']),
            'low': len([r for r in results if r.get('severity') == 'LOW'])
        }
    
    host_counts = count_severity(host_results)
    server_counts = count_severity(server_results)
    shared_counts = count_severity(shared_results)
    snyk_host_counts = count_snyk_severity(snyk_host_results)
    snyk_server_counts = count_snyk_severity(snyk_server_results)
    snyk_shared_counts = count_snyk_severity(snyk_shared_results)

    frontend_counts = frontend_audit.get('counts', {}) if frontend_audit else {}

    # Frontend (npm audit) uses info/low/moderate/high/critical; fold into the 3 buckets
    frontend_high = frontend_counts.get('high', 0) + frontend_counts.get('critical', 0)
    frontend_medium = frontend_counts.get('moderate', 0)
    frontend_low = frontend_counts.get('low', 0)

    # Total includes Bandit + Snyk + npm audit (the header must match the sum of the sections)
    total_high = (host_counts['high'] + server_counts['high'] + shared_counts['high']
                  + snyk_host_counts['high'] + snyk_server_counts['high'] + snyk_shared_counts['high']
                  + frontend_high)
    total_medium = (host_counts['medium'] + server_counts['medium'] + shared_counts['medium']
                    + snyk_host_counts['medium'] + snyk_server_counts['medium'] + snyk_shared_counts['medium']
                    + frontend_medium)
    total_low = (host_counts['low'] + server_counts['low'] + shared_counts['low']
                 + snyk_host_counts['low'] + snyk_server_counts['low'] + snyk_shared_counts['low']
                 + frontend_low)
    
    # Save JSON reports
    if host_bandit and HOST_BANDIT_JSON.exists():
        with open(OUTPUT_HOST_JSON, 'w') as f:
            json.dump(host_bandit['raw_data'], f, indent=2)
    
    if server_bandit and SERVER_BANDIT_JSON.exists():
        with open(OUTPUT_SERVER_JSON, 'w') as f:
            json.dump(server_bandit['raw_data'], f, indent=2)

    if shared_bandit and SHARED_BANDIT_JSON.exists():
        with open(OUTPUT_SHARED_JSON, 'w') as f:
            json.dump(shared_bandit['raw_data'], f, indent=2)

    if frontend_audit and frontend_audit.get('raw_data') and FRONTEND_AUDIT_JSON.exists():
        with open(OUTPUT_FRONTEND_JSON, 'w') as f:
            json.dump(frontend_audit['raw_data'], f, indent=2)
    
    if snyk_host and snyk_host.get('raw_data') and SNYK_HOST_JSON.exists():
        with open(OUTPUT_SNYK_HOST_JSON, 'w') as f:
            json.dump(snyk_host['raw_data'], f, indent=2)
    
    if snyk_server and snyk_server.get('raw_data') and SNYK_SERVER_JSON.exists():
        with open(OUTPUT_SNYK_SERVER_JSON, 'w') as f:
            json.dump(snyk_server['raw_data'], f, indent=2)

    if snyk_shared and snyk_shared.get('raw_data') and SNYK_SHARED_JSON.exists():
        with open(OUTPUT_SNYK_SHARED_JSON, 'w') as f:
            json.dump(snyk_shared['raw_data'], f, indent=2)

    # Generate issue rows for bandit results
    def generate_issue_rows(results, prefix):
        rows = ""
        for r in results:
            severity = r.get('issue_severity', 'LOW').lower()
            test_id = r.get('test_id', '')
            filename = r.get('filename', '').replace('backend_host/', '').replace('backend_server/', '').replace('shared/', '')
            line = r.get('line_number', '')
            text = r.get('issue_text', '')[:80]
            rows += f'''<div class="issue {severity}" data-severity="{severity}">
                <span class="issue-id">{test_id}</span>
                <span class="issue-loc">{filename}:{line}</span>
                <span class="issue-text">{text}</span>
            </div>'''
        return rows
    
    # Generate frontend issue rows
    def generate_npm_rows(issues):
        rows = ""
        for i in issues:
            severity = i.get('severity', 'info').lower()
            if severity == 'moderate':
                severity = 'medium'
            elif severity == 'critical':
                severity = 'high'
            name = i.get('name', '')
            title = i.get('title', '')[:60]
            fix = '✓ fix available' if i.get('fixAvailable') else ''
            rows += f'''<div class="issue {severity}" data-severity="{severity}">
                <span class="issue-id">{name}</span>
                <span class="issue-text">{title}</span>
                <span class="issue-fix">{fix}</span>
            </div>'''
        return rows
    
    # Generate Snyk issue rows (SARIF format)
    def generate_snyk_rows(results):
        rows = ""
        for r in results:
            severity = r.get('severity', 'MEDIUM').lower()
            rule_id = r.get('rule_id', '')
            # Shorten rule_id for display (e.g., python/PT -> PT)
            short_id = rule_id.split('/')[-1] if '/' in rule_id else rule_id
            filename = r.get('filename', '')
            line = r.get('line', 0)
            message = r.get('message', '')[:80]
            rows += f'''<div class="issue {severity}" data-severity="{severity}">
                <span class="issue-id">{short_id}</span>
                <span class="issue-loc">{filename}:{line}</span>
                <span class="issue-text">{message}</span>
            </div>'''
        return rows
    
    host_issue_rows = generate_issue_rows(host_results, 'host')
    server_issue_rows = generate_issue_rows(server_results, 'server')
    shared_issue_rows = generate_issue_rows(shared_results, 'shared')
    frontend_issue_rows = generate_npm_rows(frontend_issues)
    snyk_host_issue_rows = generate_snyk_rows(snyk_host_results)
    snyk_server_issue_rows = generate_snyk_rows(snyk_server_results)
    snyk_shared_issue_rows = generate_snyk_rows(snyk_shared_results)
    
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Security Report</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #1a1a2e;
            color: #e0e0e0;
            padding: 12px;
            font-size: 12px;
        }}
        .header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 10px;
        }}
        .header h1 {{ font-size: 14px; color: #fff; }}
        .timestamp {{ font-size: 10px; color: #666; }}
        
        /* Summary Card */
        .summary {{
            background: #252540;
            border-radius: 6px;
            padding: 12px 16px;
            margin-bottom: 10px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            border: 1px solid #333;
        }}
        .summary-metrics {{
            display: flex;
            gap: 24px;
        }}
        .metric {{ text-align: center; }}
        .metric-value {{ font-size: 28px; font-weight: 700; line-height: 1; }}
        .metric-label {{ font-size: 9px; color: #666; text-transform: uppercase; margin-top: 2px; }}
        .summary-info {{ font-size: 10px; color: #555; }}
        
        .high {{ color: #ff6b6b; }}
        .medium {{ color: #ffd93d; }}
        .low {{ color: #6bcb77; }}
        
        /* Filters */
        .filters {{
            display: flex;
            gap: 6px;
            margin-bottom: 10px;
        }}
        .filter-btn {{
            padding: 4px 10px;
            border: 1px solid #444;
            border-radius: 4px;
            background: transparent;
            color: #888;
            font-size: 10px;
            cursor: pointer;
            transition: all 0.2s;
        }}
        .filter-btn:hover {{ border-color: #666; color: #fff; }}
        .filter-btn.active {{ background: #333; color: #fff; border-color: #555; }}
        .filter-btn.active.high {{ border-color: #ff6b6b; color: #ff6b6b; }}
        .filter-btn.active.medium {{ border-color: #ffd93d; color: #ffd93d; }}
        .filter-btn.active.low {{ border-color: #6bcb77; color: #6bcb77; }}
        
        /* Sections */
        .section {{
            background: #252540;
            border-radius: 6px;
            margin-bottom: 8px;
            border: 1px solid #333;
            overflow: hidden;
        }}
        .section-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 10px 12px;
            cursor: pointer;
            user-select: none;
        }}
        .section-header:hover {{ background: #2a2a4a; }}
        .section-left {{
            display: flex;
            align-items: center;
            gap: 8px;
        }}
        .section-arrow {{
            font-size: 10px;
            color: #666;
            transition: transform 0.2s;
        }}
        .section.expanded .section-arrow {{ transform: rotate(90deg); }}
        .section-title {{
            font-size: 11px;
            font-weight: 600;
            color: #aaa;
            text-transform: uppercase;
        }}
        .section-counts {{
            display: flex;
            gap: 8px;
            font-size: 11px;
        }}
        .section-counts span {{ opacity: 0.8; }}
        .section-counts .ignored {{ color: #888; font-weight: 400; margin-left: 4px; }}
        .json-link {{
            font-size: 10px;
            color: #4dabf7;
            text-decoration: none;
            padding: 2px 6px;
            border-radius: 3px;
        }}
        .json-link:hover {{ background: #333; }}
        
        /* Issue list */
        .issues {{
            display: none;
            max-height: 300px;
            overflow-y: auto;
            border-top: 1px solid #333;
        }}
        .section.expanded .issues {{ display: block; }}
        .issue {{
            display: flex;
            align-items: center;
            gap: 10px;
            padding: 6px 12px;
            border-left: 3px solid #444;
            font-size: 11px;
        }}
        .issue:nth-child(odd) {{ background: rgba(0,0,0,0.1); }}
        .issue.high {{ border-left-color: #ff6b6b; }}
        .issue.medium {{ border-left-color: #ffd93d; }}
        .issue.low {{ border-left-color: #6bcb77; }}
        .issue.hidden {{ display: none; }}
        .issue-id {{
            font-weight: 600;
            color: #aaa;
            min-width: 50px;
        }}
        .issue-loc {{
            color: #666;
            font-family: monospace;
            font-size: 10px;
            min-width: 200px;
        }}
        .issue-text {{
            color: #888;
            flex: 1;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
        }}
        .issue-fix {{
            color: #6bcb77;
            font-size: 10px;
        }}
        .no-issues {{
            padding: 12px;
            color: #555;
            text-align: center;
            font-style: italic;
        }}
        
        /* Scrollbar */
        .issues::-webkit-scrollbar {{ width: 6px; }}
        .issues::-webkit-scrollbar-track {{ background: #1a1a2e; }}
        .issues::-webkit-scrollbar-thumb {{ background: #444; border-radius: 3px; }}
    </style>
</head>
<body>
    <div class="header">
        <h1>🔒 Security Report</h1>
        <span class="timestamp">{timestamp}</span>
    </div>

    <!-- Summary -->
    <div class="summary">
        <div class="summary-metrics">
            <div class="metric">
                <div class="metric-value high">{total_high}</div>
                <div class="metric-label">High</div>
            </div>
            <div class="metric">
                <div class="metric-value medium">{total_medium}</div>
                <div class="metric-label">Medium</div>
            </div>
            <div class="metric">
                <div class="metric-value low">{total_low}</div>
                <div class="metric-label">Low</div>
            </div>
        </div>
        <div class="summary-info">{total_loc:,} lines scanned</div>
    </div>

    <!-- Filters -->
    <div class="filters">
        <button class="filter-btn active high" data-filter="high" onclick="toggleFilter('high')">High</button>
        <button class="filter-btn active medium" data-filter="medium" onclick="toggleFilter('medium')">Medium</button>
        <button class="filter-btn active low" data-filter="low" onclick="toggleFilter('low')">Low</button>
    </div>

    <!-- Backend Host -->
    <div class="section" id="section-host">
        <div class="section-header" onclick="toggleSection('host')">
            <div class="section-left">
                <span class="section-arrow">▶</span>
                <span class="section-title">Backend Host</span>
                <div class="section-counts">
                    <span class="high">{host_counts['high']}</span> /
                    <span class="medium">{host_counts['medium']}</span> /
                    <span class="low">{host_counts['low']}</span>
                </div>
            </div>
            <a class="json-link" href="host-report.json" target="_blank" onclick="event.stopPropagation()">JSON ↗</a>
        </div>
        <div class="issues">
            {host_issue_rows if host_issue_rows else '<div class="no-issues">No issues</div>'}
        </div>
    </div>

    <!-- Backend Server -->
    <div class="section" id="section-server">
        <div class="section-header" onclick="toggleSection('server')">
            <div class="section-left">
                <span class="section-arrow">▶</span>
                <span class="section-title">Backend Server</span>
                <div class="section-counts">
                    <span class="high">{server_counts['high']}</span> /
                    <span class="medium">{server_counts['medium']}</span> /
                    <span class="low">{server_counts['low']}</span>
                </div>
            </div>
            <a class="json-link" href="server-report.json" target="_blank" onclick="event.stopPropagation()">JSON ↗</a>
        </div>
        <div class="issues">
            {server_issue_rows if server_issue_rows else '<div class="no-issues">No issues</div>'}
        </div>
    </div>

    <!-- Shared Library -->
    <div class="section" id="section-shared">
        <div class="section-header" onclick="toggleSection('shared')">
            <div class="section-left">
                <span class="section-arrow">▶</span>
                <span class="section-title">Shared Library</span>
                <div class="section-counts">
                    <span class="high">{shared_counts['high']}</span> /
                    <span class="medium">{shared_counts['medium']}</span> /
                    <span class="low">{shared_counts['low']}</span>
                </div>
            </div>
            <a class="json-link" href="shared-report.json" target="_blank" onclick="event.stopPropagation()">JSON ↗</a>
        </div>
        <div class="issues">
            {shared_issue_rows if shared_issue_rows else '<div class="no-issues">No issues</div>'}
        </div>
    </div>

    <!-- Frontend -->
    <div class="section" id="section-frontend">
        <div class="section-header" onclick="toggleSection('frontend')">
            <div class="section-left">
                <span class="section-arrow">▶</span>
                <span class="section-title">Frontend (npm)</span>
                <div class="section-counts">
                    <span class="high">{frontend_high}</span> /
                    <span class="medium">{frontend_medium}</span> /
                    <span class="low">{frontend_low}</span>
                </div>
            </div>
            <a class="json-link" href="frontend-report.json" target="_blank" onclick="event.stopPropagation()">JSON ↗</a>
        </div>
        <div class="issues">
            {frontend_issue_rows if frontend_issue_rows else '<div class="no-issues">No issues</div>'}
        </div>
    </div>

    <!-- Snyk Code - Host -->
    <div class="section" id="section-snyk-host">
        <div class="section-header" onclick="toggleSection('snyk-host')">
            <div class="section-left">
                <span class="section-arrow">▶</span>
                <span class="section-title">🔍 Snyk Code - Host</span>
                <div class="section-counts">
                    <span class="high">{snyk_host_counts['high']}</span> /
                    <span class="medium">{snyk_host_counts['medium']}</span> /
                    <span class="low">{snyk_host_counts['low']}</span>
                    {ignored_badge(snyk_host_ignored)}
                </div>
            </div>
            <a class="json-link" href="snyk-host-report.json" target="_blank" onclick="event.stopPropagation()">JSON ↗</a>
        </div>
        <div class="issues">
            {snyk_host_issue_rows if snyk_host_issue_rows else '<div class="no-issues">No issues (or Snyk not installed)</div>'}
        </div>
    </div>

    <!-- Snyk Code - Server -->
    <div class="section" id="section-snyk-server">
        <div class="section-header" onclick="toggleSection('snyk-server')">
            <div class="section-left">
                <span class="section-arrow">▶</span>
                <span class="section-title">🔍 Snyk Code - Server</span>
                <div class="section-counts">
                    <span class="high">{snyk_server_counts['high']}</span> /
                    <span class="medium">{snyk_server_counts['medium']}</span> /
                    <span class="low">{snyk_server_counts['low']}</span>
                    {ignored_badge(snyk_server_ignored)}
                </div>
            </div>
            <a class="json-link" href="snyk-server-report.json" target="_blank" onclick="event.stopPropagation()">JSON ↗</a>
        </div>
        <div class="issues">
            {snyk_server_issue_rows if snyk_server_issue_rows else '<div class="no-issues">No issues (or Snyk not installed)</div>'}
        </div>
    </div>

    <!-- Snyk Code - Shared -->
    <div class="section" id="section-snyk-shared">
        <div class="section-header" onclick="toggleSection('snyk-shared')">
            <div class="section-left">
                <span class="section-arrow">▶</span>
                <span class="section-title">🔍 Snyk Code - Shared</span>
                <div class="section-counts">
                    <span class="high">{snyk_shared_counts['high']}</span> /
                    <span class="medium">{snyk_shared_counts['medium']}</span> /
                    <span class="low">{snyk_shared_counts['low']}</span>
                    {ignored_badge(snyk_shared_ignored)}
                </div>
            </div>
            <a class="json-link" href="snyk-shared-report.json" target="_blank" onclick="event.stopPropagation()">JSON ↗</a>
        </div>
        <div class="issues">
            {snyk_shared_issue_rows if snyk_shared_issue_rows else '<div class="no-issues">No issues (or Snyk not installed)</div>'}
        </div>
    </div>

    <script>
        // Toggle section expand/collapse
        function toggleSection(id) {{
            const section = document.getElementById('section-' + id);
            section.classList.toggle('expanded');
        }}
        
        // Active filters
        const activeFilters = {{ high: true, medium: true, low: true }};
        
        // Toggle filter
        function toggleFilter(severity) {{
            activeFilters[severity] = !activeFilters[severity];
            
            // Update button state
            const btn = document.querySelector(`[data-filter="${{severity}}"]`);
            btn.classList.toggle('active', activeFilters[severity]);
            
            // Filter issues
            document.querySelectorAll('.issue').forEach(issue => {{
                const issueSeverity = issue.dataset.severity;
                const show = activeFilters[issueSeverity];
                issue.classList.toggle('hidden', !show);
            }});
        }}
    </script>
</body>
</html>
"""
    
    with open(OUTPUT_HTML, 'w') as f:
        f.write(html)
    
    print(f"✅ Generated: {OUTPUT_HTML}")


if __name__ == '__main__':
    generate_html_report()
