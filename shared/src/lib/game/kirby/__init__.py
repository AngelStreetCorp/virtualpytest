"""
Super Kirby Clash fight bot (TASK-51). A real-time game loop on a Nintendo Switch (device model
``nintendo_switch``, HDMI capture at 1280x720, 5 JPEG/s) that fights one boss: the runner reads the
boss and Kirby positions and HP from each capture, picks a tactic with the platform's Jev decision
model in a background thread, and fires a Switch action (``press``, ``sequence``, ``stick``, ``hold``
or ``release``) on every frame. Pure vision helpers (cv2 HSV thresholds), the tactic list and bot
steps, and the loop live here. The script entry is ``test_scripts/game/game_kirby.py``.
"""