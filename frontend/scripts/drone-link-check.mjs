// Node check for the drone tile's link decision (no frontend test runner exists in this repo).
// Extracts statusIsConnected from the hook source so the check cannot drift from it.
import { readFileSync } from 'node:fs';
import assert from 'node:assert/strict';
import ts from 'typescript';

const src = readFileSync(new URL('../src/hooks/rec/useDroneWifiStatus.ts', import.meta.url), 'utf8');
const m = /export function statusIsConnected[\s\S]*?\n}\n/.exec(src);
assert(m, 'statusIsConnected not found');
const js = ts.transpileModule(m[0], { compilerOptions: { module: 'ESNext', target: 'ES2020' } }).outputText.replace('export ', '');
const statusIsConnected = new Function(`${js}; return statusIsConnected;`)();

assert.equal(statusIsConnected({ connected: true, ssid: 'TELLO-C5B142' }, null), true);
assert.equal(statusIsConnected({ connected: true, ssid: 'TELLO-C5B142' }, 'TELLO-C5B142'), true);
assert.equal(statusIsConnected({ connected: true, ssid: 'TELLO-AAAAAA' }, 'TELLO-C5B142'), false);
// switched off: socket still there (linked) and even Wi-Fi associated, but not connected
assert.equal(statusIsConnected({ linked: true, associated: true, connected: false, ssid: 'TELLO-C5B142' }, null), false);
assert.equal(statusIsConnected({ linked: true, ssid: 'TELLO-C5B142' }, null), false);
assert.equal(statusIsConnected(null, null), false);
console.log('drone-link-check: ok');
