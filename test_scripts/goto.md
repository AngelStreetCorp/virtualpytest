# goto

Generic navigation to any node in the navigation tree.

## Usage

```bash
python test_scripts/goto.py                          # Default: home
python test_scripts/goto.py --node live              # Go to live
python test_scripts/goto.py --node settings --userinterface example_androidtv
python test_scripts/goto.py --userinterface youtube-android-mobile --node video_player --device device2
```

Every argument is a flag. There is no positional userinterface argument — a bare
positional is ignored and `--userinterface` keeps its default, so the run loads
the wrong tree and fails with `User interface 'example_mobile' not found`.

## Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `--userinterface` | string | `example_mobile` | UI interface name |
| `--node` | string | `home` | Target node to navigate to |
| `--variant` | string | _(empty)_ | Named variant; empty means base data |
| `--verify` | string | `end` | `end` (destination only), `each` (every step), `auto` (skip steps with edge+node confidence ≥ 0.7) |
| `--device` | string | `device1` | Device to run on. Over the API this is appended from the request's `device_id` when omitted |

## Output

- Loads navigation tree
- Executes optimal path to target node
- Reports navigation steps and execution time
- Detects if already at destination (skips navigation)

