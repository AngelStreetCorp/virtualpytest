"""Localize on a website: pages that share one header and sidebar must not tie with the real page (BUG-0418).

Measured on a shop site (6 pages): the live page was 1 and 3 bits from its own header and sidebar regions,
every other page 10 to 16 bits, so the best region alone ruled none of them out."""
import copy
import importlib

import cv2
import numpy as np

ih = importlib.import_module('backend_host.src.controllers.verification.image_helpers')


def _flip(hex_str, bits):
    n = int(hex_str, 16)
    for i in range(bits):
        n ^= 1 << (i * 7)
    return format(n, f'0{len(hex_str)}x')


def _page():
    img = np.full((720, 1280, 3), 255, np.uint8)
    rng = np.random.RandomState(5)
    for _ in range(150):
        x, y = int(rng.randint(0, 1100)), int(rng.randint(0, 650))
        cv2.rectangle(img, (x, y), (x + int(rng.randint(40, 200)), y + int(rng.randint(20, 90))),
                      (0, 0, 0), int(rng.choice([2, -1])))
    return img


def test_decoys_matching_only_header_and_sidebar_loosely_are_ruled_out():
    helpers = ih.ImageHelpers(None, None)
    img = _page()
    real = helpers.compute_fingerprint(img)
    real['regions']['top'] = _flip(real['regions']['top'], 1)
    real['regions']['left'] = _flip(real['regions']['left'], 3)
    node_fps = [{'node_id': 'home', 'label': 'home', 'fingerprint': real}]
    for name in ('login', 'cart'):
        d = copy.deepcopy(real)
        d['regions']['top'] = _flip(real['regions']['top'], 11)
        d['regions']['left'] = _flip(real['regions']['left'], 12)
        for r in ('full', 'center', 'bottom'):
            d['regions'][r] = _flip(real['regions'][r], 90)
        node_fps.append({'node_id': name, 'label': name, 'fingerprint': d})
    res = helpers.identify_screen(img, node_fps)
    assert [c['label'] for c in res['candidates']] == ['home']
