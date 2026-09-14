# zap_chup

Executes an action node multiple times to test navigation optimization.

## Usage

```bash
python test_scripts/tv/zap_chup.py --iterations 5
python test_scripts/tv/zap_chup.py --node live_chdown --iterations 10
python test_scripts/tv/zap_chup.py example_mobile --node live_chup --iterations 3
```

## Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `--userinterface` | string | `example_mobile` | UI interface name |
| `--node` | string | `live_chup` | Action node to execute |
| `--iterations` | int | `3` | Number of times to execute the action |

After each zap it also verifies the destination is really playing (real frame-to-frame
motion, same check `fullzap`/`zap_digit` use) and does a **best-effort read of the local
zap measurement** vpt-monitor wrote to `last_zapping.json` — channel name/number +
blackscreen/total-zap durations, matched by the navigation's action timestamp. When
detected it's attached to that iteration's navigation step (*Analysis Results → Zap
Detection*) and shown in the summary. Best-effort: a missing measurement is `null` and
never changes pass/fail.

## Output

- First iteration: Full navigation path (entry → parent → action)
- Subsequent iterations: Optimized direct action (1 step if at parent)
- Summary table showing transitions per iteration (with measured channel when available)
- Optimization statistics (how many calls were optimized)
- Zap measurements fetched count
