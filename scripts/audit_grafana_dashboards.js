#!/usr/bin/env node

const fs = require('fs');
const path = require('path');

const dashboardsDir = path.join(__dirname, '..', 'infra', 'monitoring', 'grafana', 'dashboards');

function walk(node, visitor) {
  if (!node || typeof node !== 'object') {
    return;
  }
  if (Array.isArray(node)) {
    node.forEach((item) => walk(item, visitor));
    return;
  }
  visitor(node);
  Object.values(node).forEach((value) => walk(value, visitor));
}

function analyzeDashboard(filename) {
  const fullPath = path.join(dashboardsDir, filename);
  const dashboard = JSON.parse(fs.readFileSync(fullPath, 'utf8'));
  const templatingList = Array.isArray(dashboard.templating?.list) ? dashboard.templating.list : [];
  const hasSuccessVariable = templatingList.some((item) => item?.name === 'success');
  const findings = [];

  walk(dashboard.panels, (node) => {
    if (typeof node.rawSql !== 'string') {
      return;
    }

    const sql = node.rawSql;
    const referencesScriptResults = /\bscript_results\b/i.test(sql);
    if (!referencesScriptResults) {
      return;
    }

    const hasSuccessFilter = /\$success|success::text\s+IN\s*\(\$success\)|success\s+IN\s*\(\$success\)/i.test(sql);
    const usesHostLatestGatewayMapping = /\bWITH\s+gw_latest\s+AS\s*\(/i.test(sql);

    if (!hasSuccessFilter) {
      findings.push({
        type: 'missing_success_filter',
        panelId: node.id ?? 'unknown',
        title: node.title || '(untitled)',
      });
    }

    if (usesHostLatestGatewayMapping) {
      findings.push({
        type: 'host_latest_gateway_mapping',
        panelId: node.id ?? 'unknown',
        title: node.title || '(untitled)',
      });
    }
  });

  if (!hasSuccessVariable && findings.some((item) => item.type === 'missing_success_filter')) {
    findings.unshift({
      type: 'missing_success_variable',
      panelId: '-',
      title: 'dashboard',
    });
  }

  return {
    filename,
    hasSuccessVariable,
    findings,
  };
}

function main() {
  const files = fs.readdirSync(dashboardsDir).filter((name) => name.endsWith('.json')).sort();
  const results = files.map(analyzeDashboard).filter((result) => result.findings.length > 0);

  if (results.length === 0) {
    console.log('No Grafana dashboard findings.');
    return;
  }

  results.forEach((result) => {
    console.log(result.filename);
    result.findings.forEach((finding) => {
      console.log(`  - ${finding.type} | panel=${finding.panelId} | ${finding.title}`);
    });
  });
}

main();
