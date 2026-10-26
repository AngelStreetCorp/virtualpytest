"""TASK-130 launcher: run on the Windows box in the user's session (see create_practice_task.ps1).

Expects the League Client to be up (run the phase-0 chain first). Writes
C:\\virtualpytest\\practice-result.json and practice-run.log.
"""
import json
import sys
import traceback
from pathlib import Path

sys.path.insert(0, r"C:\virtualpytest\virtualpytest")

from PIL import ImageGrab  # noqa: E402

from shared.src.lib.game.leagueoflegends.practice_runner import PracticeConfig, PracticeRunner  # noqa: E402

OUT = Path(r"C:\virtualpytest")


def shot(path: Path) -> None:
    ImageGrab.grab(all_screens=True).save(path)


def main() -> int:
    log = open(OUT / "practice-run.log", "w", buffering=1)
    sys.stdout = log
    try:
        cfg = PracticeConfig(screenshot_fn=shot, screenshot_dir=OUT / "practice-shots")
        result = PracticeRunner(cfg).run()
        payload = {"ok": result.ok, "final_message": result.final_message,
                   "steps": [s.__dict__ for s in result.steps]}
    except Exception:
        payload = {"ok": False, "final_message": "raised", "exception": traceback.format_exc()}
    (OUT / "practice-result.json").write_text(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
