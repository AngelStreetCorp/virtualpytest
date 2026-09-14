# Batch Campaign Selection

Batch campaign wrappers in `test_campaign/` use [`_campaign_batch_common.py`](~/virtualpytest/test_campaign/_campaign_batch_common.py) to build a script list.

## Default Model

- `run_gw_campaign.py` includes `test_scripts/gw`
- `run_web_campaign.py` includes `test_scripts/web`
- scripts are executed sequentially in sorted filename order
- script-level `_target_rules` are parsed dynamically for host OS constraints

## Selection Flags

Use these flags on top of the wrapper defaults:

- `--include-script <path>`: add one script anywhere in the repo
- `--include-dir <path>`: add one script folder
- `--exclude-script <path>`: remove one script from the final selection

Paths are relative to the project root, for example:

- `test_scripts/gw/udp_latency.py`
- `test_scripts/tv/fullzap.py`
- `test_scripts/web`

## Examples

Run the default GW batch:

```bash
python test_campaign/run_gw_campaign.py
```

Run all GW scripts except one:

```bash
python test_campaign/run_gw_campaign.py --exclude-script test_scripts/gw/udp_latency.py
```

Run the default web batch plus one TV script:

```bash
python test_campaign/run_web_campaign.py --include-script test_scripts/tv/fullzap.py
```

Run only one script with the batch helper pattern:

```bash
python test_campaign/run_web_campaign.py \
  --exclude-script test_scripts/web/facebook_check.py \
  --exclude-script test_scripts/web/youtube_video_check.py \
  --include-script test_scripts/tv/fullzap.py
```

If you need a fully custom campaign composition, create a dedicated wrapper in `test_campaign/` and pass `include_dirs`, `include_scripts`, and `exclude_scripts` to `execute_batch_campaign()`.
