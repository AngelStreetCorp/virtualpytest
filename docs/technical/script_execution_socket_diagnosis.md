# Script Execution Socket Diagnosis

Date: 2026-03-05

## Symptom

In Run Tests, script execution could remain stuck or fail to complete in UI even though backend task was running/completing.

## Root Causes Found

1. Wrong socket base URL source in frontend execution waiter.
- `frontend/src/utils/executionSocketWait.ts` connected to:
  - `window.location.origin + /system`
- But API calls use selected backend from `getServerBaseUrl()`.
- In multi-server/proxy setups, this can connect to the wrong server namespace and miss events.

2. Reconnection logic was effectively disabled.
- `connect_error` immediately rejected the wait promise.
- This bypassed Socket.IO reconnection behavior and caused early failure on transient network/proxy issues.

## Fix Applied

1. Use backend-selected URL for `/system` socket namespace.
- `executionSocketWait.ts` now uses `getServerBaseUrl()` (fallback to `window.location.origin`).

2. Preserve reconnection attempts.
- `connect_error` now records warning telemetry and keeps waiting.
- Final failure is decided by timeout/abort, not first handshake error.

3. Keep socket issues visible when polling fallback is used in script hook.
- `frontend/src/hooks/script/useScript.ts` now logs explicit warning when completion came from polling fallback.
- This avoids silent masking of socket transport issues.

## Operational Outcome

- If socket works: completion arrives through `/system` `execution_update` quickly.
- If socket is degraded: status polling still completes UX, and console warns that fallback was used.

## Next Validation

1. Open browser devtools console and run one script.
2. Verify either:
- socket completion path, or
- polling fallback warning with socket error reason.
3. Confirm `/server/script/status/{task_id}` reaches terminal status in fallback path.
