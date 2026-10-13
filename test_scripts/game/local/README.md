# Local game runs (TASK-33 phase 3)

Play the phase-3 web games in a local Chromium before using a host. Nothing here is listed as a
runnable script (discovery only looks one folder deep under `test_scripts/`).

```bash
python3 -m venv /tmp/gvenv && /tmp/gvenv/bin/pip install playwright opencv-python-headless numpy pytest
/tmp/gvenv/bin/python -m playwright install chromium
Xvfb :97 -screen 0 1280x720x24 &          # 1280x720 = the web host's VNC screen
```

| File | What it runs |
|---|---|
| `tetris_vpt_local.py` | **The real VirtualPyTest Tetris runner** (`shared/src/lib/game/tetris/runner.py`) with the `tetris-web` tree's own actions, played by Playwright instead of the executors. `--action-ms 25` mimics the host's per-action overhead. Run this before deploying a Tetris change. |
| `flappy_vpt_local.py` | **The real VirtualPyTest Flappy Bird runner** (`shared/src/lib/game/flappy/runner.py`) with the `flappy-web` tree. `--url http://127.0.0.1:8765/` points at a local copy of github.com/nebez/floppybird (`python3 -m http.server 8765` in the clone): nebezb.com throttles repeated loads. |
| `flappy_predict.py` | Flappy Bird trial comparing two calls / one call / planned jump with simulated latency |
| `_local_io.py` | `LocalIO`: plays a tree's action dicts with Playwright, shared by the `*_vpt_local.py` runs |
| `probe.py` | Phase 3a probe: page state reads, real vs synthetic keys, read-then-press loop latency |
| `tetris_local.py` | First Tetris prototype (Playwright only) |
| `flappy_local.py` | Flappy Bird prototype (Playwright only); prints the last frames on death |

```bash
DISPLAY=:97 /tmp/gvenv/bin/python test_scripts/game/local/tetris_vpt_local.py --max-pieces 200 --action-ms 25
DISPLAY=:97 /tmp/gvenv/bin/python test_scripts/game/local/probe.py
DISPLAY=:97 /tmp/gvenv/bin/python test_scripts/game/local/flappy_local.py 300 6 1
```

Run one game per X display: several browsers on one machine slow the Flappy control loop.
Results and conclusions are in `docs/tasks/TASK-33-2048-game-showcase.md` §000.
