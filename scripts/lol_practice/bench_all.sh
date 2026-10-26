#!/bin/bash
# TASK-134: run benchmark games one after the other. usage: bench_all.sh "<model>:<label>" ...   (relay must be running on :8787)
# A game that is invalid (start failed, e.g. the camera lock) is moved aside as <label>-invalidN and played again, up to 3 times.
for pair in "$@"; do
  for try in 1 2 3; do
    scripts/lol_practice/bench_cycle.sh "${pair%%:*}" "${pair#*:}" blue ${BENCH_EXTRA:-}
    [ $? -ne 5 ] && break
    mv "$HOME/vpt-deliverables/lol-model-benchmark/${pair#*:}" "$HOME/vpt-deliverables/lol-model-benchmark-misfetched/${pair#*:}-invalid$try" 2>/dev/null
  done
done
