"""Jev review shadow for screen-id training samples (TASK-38 goal 6 = TASK-39 section 4 goal 4).

Three machines, four phases (``run.py``): ``export`` on the server (DB + storage, no OCR),
``evidence`` on codebox (tesseract, cv2, no network), ``decide`` on the server (OpenRouter),
``report`` anywhere. The bundle directory is the only thing passed between them.
"""
import importlib.util
import os
import sys

REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
if os.path.isdir(os.path.join(REPO_ROOT, 'shared')) and REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

LAB_TEAM = '7fdeb4bb-3639-4ec3-959f-b54769a219ce'


def load_lib(name: str):
    """A features/ai-dataset/lib module by path (same pattern as scripts/triage_batch.py)."""
    path = os.path.join(REPO_ROOT, 'features', 'ai-dataset', 'lib', f'{name}.py')
    spec = importlib.util.spec_from_file_location(f'ai_dataset_{name}', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
