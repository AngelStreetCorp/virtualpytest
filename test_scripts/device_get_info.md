# device_get_info

Navigates to the info screen and extracts device information into metadata.

## Usage

```bash
python test_scripts/device_get_info.py                              # Default: info node
python test_scripts/device_get_info.py --node info_settings         # Custom node
python test_scripts/device_get_info.py --userinterface example_mobile
```

## Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `--userinterface` | string | `example_gui` | UI interface name |
| `--node` | string | `info` | Target node to navigate to |

## Output

- Navigates to specified info node
- Extracts device information using `getMenuInfo` action
- Stores parsed data in `context.metadata['info']`
- Works with ADB (mobile), Playwright (web), or OCR (video) based on device type

