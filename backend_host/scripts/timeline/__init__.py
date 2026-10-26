"""Timeline (TASK-94): per-chunk thumbnail sprites and reduced tracks for the Timeline page.

Reads only finished 10-min archive chunks and their metadata JSON; never touches the capture
device and never runs inside hot_cold_archiver.py. Files go to cold `thumbnails/<hour>/`, a
folder the host nginx already serves (and that the archiver's own cleanup patterns do not match).
"""
