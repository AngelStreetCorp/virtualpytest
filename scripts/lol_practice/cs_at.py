"""Exact CS (HUD counter, read from shots/) at 5:00 and 8:00 for run folders. Usage: cs_at.py <run_dir>..."""
import sys

from shared.src.lib.game.leagueoflegends.score_run import cs_from_shots

for d in sys.argv[1:]:
    rows = cs_from_shots(d.rstrip("/"))

    def at(t):
        v = [r["cs"] for r in rows if r["t"] <= t]
        return v[-1] if v else None

    c5, c8 = at(300), at(480)
    print(d.rstrip("/").split("/")[-2], "cs@5:00", c5, f"({c5 / 5:.2f}/min)" if c5 is not None else "", "cs@8:00", c8)
