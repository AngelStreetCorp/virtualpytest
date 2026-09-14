# campaign_fullzap.py Verification

## Target

- Requested path: `test_campaign/campaign_fullzap.py`
- Resolved file found at: `/home/jndoye/shared/projects/virtualpytest/test_campaign/campaign_fullzap.py`
- Verification date: 2026-03-05

## What The Script Does

- Builds a configurable campaign for `tv/fullzap.py`
- Runs one first execution with `goto-live=True`
- Runs `--max-execution` additional executions with `goto-live=False`
- Uses `CampaignExecutor.execute_campaign(...)`
- Forces sequential execution with `"parallel": False`
- Uses `"continue_on_failure": True` in `execution_config`

## CLI Defaults Verified

- `userinterface_name`: `example_mobile`
- `--host`: `auto`
- `--device`: `auto`
- `--max-iteration`: `2`
- `--max-execution`: `1`
- `--timeout-minutes`: `60`

## Exit Behavior Verified

- Returns exit `0` when campaign succeeds, including partial script failures when `result["success"]` is true and `result["overall_success"]` is false
- Returns exit `1` when campaign itself fails (`result["success"]` is false)
- KeyboardInterrupt and unexpected exceptions are delegated to shared handlers

## Findings

- `timestamp` is computed in `create_campaign_config()` but never used
- `campaign_id` is constant (`fullzap-configurable`), so multiple runs are not uniquely identified by this field
- No validation on numeric args (`--max-iteration`, `--max-execution`, `--timeout-minutes`), so invalid values like `0` or negatives are currently possible
- Output uses emoji-rich logs; fine for humans, but noisy for machine parsing

## Compatibility Note

- This script is a `test_campaign` orchestrator and does not replace:
  - `run_web_campaign` (runs files in `test_scripts/web`)
  - `run_gw_campaign` (runs files in `test_scripts/gw`)
