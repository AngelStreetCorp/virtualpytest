#!/usr/bin/env node
/**
 * Theme colour checker (TASK-102 G10). Run: `cd frontend && node scripts/theme_colour_check.mjs`.
 *
 * The files in CHECKED_FILES were moved onto the active colour theme (`useAgentChatPalette()` /
 * the MUI theme). This fails on any raw colour literal in them (#hex, rgb()/rgba(), 'white',
 * 'black') that is not listed for that file in scripts/theme-colour-allow.json.
 * Allowed literals are intentional: fixed status colours, scrims and text drawn over video,
 * black letterboxes, drop shadows. Add to the allow-list only with a reason in "reasons".
 *
 * Flags: --list (print every literal found per file, to refresh the allow-list).
 */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const FRONTEND = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const ALLOW = JSON.parse(fs.readFileSync(path.join(FRONTEND, 'scripts', 'theme-colour-allow.json'), 'utf8'));

const CHECKED_FILES = [
  'src/components/common/ExecutionProgressOverlay.tsx',
  'src/contexts/ThemeContext.tsx',
  'src/components/rec/RecStreamModalHeader.tsx',
  'src/components/rec/DeviceStatusChip.tsx',
  'src/components/rec/RestartSettingsPanel.tsx',
  'src/components/rec/RecHostStreamModal.tsx',
  'src/components/rec/group/GroupControlModal.tsx',
  'src/components/rec/group/GroupStreamCell.tsx',
  'src/components/rec/group/GroupModelBadgeRow.tsx',
  'src/components/common/QuickfilterBadgeArea.tsx',
  'src/components/common/PageChrome.tsx',
  'src/components/heatmap/HeatMapFreezeModal.tsx',
  'src/components/heatmap/HeatMapHistory.tsx',
  'src/components/MosaicPlayer.tsx',
  'src/components/common/Navigation_GroupedDropdown.tsx',
  'src/components/common/Navigation_ItemStyle.tsx',
  'src/components/common/ServiceLogsModal.tsx',
  'src/config/validationColors.ts',
  'src/components/reports/status.tsx',
  'src/utils/navigation/navigationMappers.ts',
];

const LITERAL = /#[0-9a-fA-F]{3,8}\b|rgba?\([^)]*\)|(['"])(?:white|black)\1/g;

const findings = {};
for (const rel of CHECKED_FILES) {
  const file = path.join(FRONTEND, rel);
  if (!fs.existsSync(file)) {
    console.error(`missing checked file: ${rel}`);
    process.exit(1);
  }
  const lines = fs.readFileSync(file, 'utf8').split('\n');
  lines.forEach((line, i) => {
    const code = line.replace(/\/\/.*$/, '');
    for (const m of code.matchAll(LITERAL)) {
      (findings[rel] ||= []).push({ line: i + 1, literal: m[0].replace(/\s+/g, ' ') });
    }
  });
}

if (process.argv.includes('--list')) {
  for (const [rel, list] of Object.entries(findings)) {
    console.log(rel);
    list.forEach((f) => console.log(`  ${f.line}: ${f.literal}`));
  }
  process.exit(0);
}

let bad = 0;
for (const [rel, list] of Object.entries(findings)) {
  const allowed = new Set(((ALLOW.files || {})[rel] || []).map((s) => s.replace(/\s+/g, ' ')));
  for (const f of list) {
    if (allowed.has(f.literal)) continue;
    bad += 1;
    console.error(`${rel}:${f.line}: raw colour ${f.literal} (use useAgentChatPalette() P.* or the MUI theme, or allow-list it with a reason)`);
  }
}
if (bad) {
  console.error(`\ntheme_colour_check: ${bad} raw colour literal(s). See docs/agent/platform/UI_STYLE.md section 12.`);
  process.exit(1);
}
console.log(`theme_colour_check: ok (${CHECKED_FILES.length} files)`);
