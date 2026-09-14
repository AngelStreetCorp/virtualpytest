# run_gw_web_campaign

Runs all Python scripts in `test_scripts/gw` and `test_scripts/web` by default, except:

- `test_scripts/gw/udp_latency.py`
- `test_scripts/web/browser_task.py`

## Behavior

- Default mode: continue on failure
- Optional mode: stop on first failure with `--stop-on-failure`
- No parallel execution (sequential only)
- Sorted filename order
- Selection can be overridden from CLI:
  - add extra scripts with `--include-script`
  - add extra folders with `--include-dir`
  - remove scripts with `--exclude-script`

## Usage

```bash
python test_campaign/run_gw_web_campaign.py [userinterface_name] [--host HOST] [--device DEVICE] [--timeout-minutes N] [--stop-on-failure]
```

Examples:

```bash
python test_campaign/run_gw_web_campaign.py
python test_campaign/run_gw_web_campaign.py --include-script test_scripts/gw/udp_latency.py
python test_campaign/run_gw_web_campaign.py --include-script test_scripts/web/browser_task.py
```

## Output

- Campaign executor logs each script execution
- Final summary line: `SUMMARY total=<n> passed=<n> skipped=<n> failed=<n>`
- Exit code `0` when all scripts pass, non-zero otherwise
