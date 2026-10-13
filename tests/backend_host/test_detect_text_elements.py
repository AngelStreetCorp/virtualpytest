"""
tests/backend_host/test_detect_text_elements.py — /detectText can return each text with its area.

A full-frame OCR check on a set-top box picture background reads almost nothing (stb4 show
detail, 2026-10-04: "01:40" only), while a crop of the button row reads its labels in 0.3 s.
stb_tv's checks are all cropped; a caller building a tree needs the areas to do the same.
"""
import importlib
import os
import sys
from types import SimpleNamespace

REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

text_mod = importlib.import_module('backend_host.src.controllers.verification.text')

ELEMENTS = [{'text': 'Aufnehmen', 'area': {'x': 277, 'y': 590, 'width': 128, 'height': 26}, 'confidence': 91}]


def _controller():
    ctrl = object.__new__(text_mod.TextVerificationController)
    ctrl.helpers = SimpleNamespace(
        download_image=lambda url: '/tmp/frame.jpg',
        detect_text_in_area=lambda path, area: {'extracted_text': '01:40'},
        extract_full_ocr_dump=lambda path, conf: ELEMENTS,
    )
    return ctrl


def test_include_elements_returns_each_text_with_its_area():
    r = _controller().detect_text({'image_source_url': 'http://h/frame.jpg', 'include_elements': True})
    assert r['success'] is True
    assert r['elements'] == ELEMENTS


def test_CONTROL_without_the_flag_no_dump_runs():
    r = _controller().detect_text({'image_source_url': 'http://h/frame.jpg'})
    assert r['success'] is True and r['extracted_text'] == '01:40'
    assert 'elements' not in r
