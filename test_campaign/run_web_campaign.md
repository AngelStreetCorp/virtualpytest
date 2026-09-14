# run_web_campaign

Runs all Python scripts in `test_scripts/web` by default.

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
python test_campaign/run_web_campaign.py [userinterface_name] [--host HOST] [--device DEVICE] [--timeout-minutes N] [--stop-on-failure]
```

Examples:

```bash
python test_campaign/run_web_campaign.py
python test_campaign/run_web_campaign.py --exclude-script test_scripts/web/facebook_check.py
python test_campaign/run_web_campaign.py --include-script test_scripts/tv/fullzap.py
```

## Output

- Campaign executor logs each script execution
- Final summary line: `SUMMARY total=<n> passed=<n> skipped=<n> failed=<n>`
- Exit code `0` when all scripts pass, non-zero otherwise
