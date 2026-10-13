"""The environment every tesseract subprocess runs with: one OpenMP thread.

tesseract is linked against libgomp and starts nproc threads by default. On a loaded host
(vpt-pi1, 2026-10-04: 4 cores at load 8-10 from ffmpeg, the capture monitor and whisper) those
threads spin at barriers waiting for cores, so a 380x75 crop took 0.2 s to 7.3 s and a check's
p99 was 21.7 s (max 31 s, the subprocess timeout). Single-threaded, the same crop takes 0.19 s
flat and the full frame 0.7 s, with identical output (BUG-0274).
"""
import os


def tesseract_env() -> dict:
    return {**os.environ, 'OMP_THREAD_LIMIT': '1'}
