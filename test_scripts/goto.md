# goto

Generic navigation to any node in the navigation tree.

## Usage

```bash
python test_scripts/goto.py                          # Default: home
python test_scripts/goto.py --node live              # Go to live
python test_scripts/goto.py --node settings --userinterface example_androidtv
```

## Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `--userinterface` | string | `example_mobile` | UI interface name |
| `--node` | string | `home` | Target node to navigate to |

## Output

- Loads navigation tree
- Executes optimal path to target node
- Reports navigation steps and execution time
- Detects if already at destination (skips navigation)

