# goto_live

Smart navigation to live TV - automatically selects fullscreen for mobile devices.

## Usage

```bash
python test_scripts/tv/goto_live.py
python test_scripts/tv/goto_live.py --userinterface example_mobile
```

## Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `--userinterface` | string | `example_mobile` | UI interface name |

## Behavior

- **Mobile devices**: navigates to `live_fullscreen`
- **Other devices**: navigates to `live`

Device type is determined by checking if device model contains "mobile".
