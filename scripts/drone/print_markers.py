#!/usr/bin/env python3
"""
Print the hide-and-seek ArUco markers (TASK-32 §C.1) on one A4 page at 300 dpi.

Each drone carries the DICT_4X4_50 marker whose id is its index (drone 1 -> id 1). The seeker flies at
about the same height as the hider, so a tag lying flat on top would be seen edge-on: each id is printed
4 times (--copies), to be glued on the 4 sides of a light paper box (about 3 g) taped on top of the
shell, so one face looks at the seeker from any direction. Print at 100 % scale (no "fit to page") and
check that the black square measures --size_cm.

    python3 scripts/drone/print_markers.py --out /tmp/tello_markers.png      # ids 1 and 2, 4 x 4 cm each
    python3 scripts/drone/print_markers.py --ids 1 --copies 1 --size_cm 6 --out m.pdf
"""
import argparse

import cv2
import numpy as np

DPI = 300
A4_CM = (21.0, 29.7)


def px(cm: float) -> int:
    return int(round(cm / 2.54 * DPI))


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--ids", type=int, nargs="+", default=[1, 2])
    p.add_argument("--size_cm", type=float, default=4.0)
    p.add_argument("--copies", type=int, default=4, help="copies of each id (4 = one per box side)")
    p.add_argument("--out", default="tello_markers.png", help=".png, or .pdf (needs Pillow)")
    a = p.parse_args()

    page = np.full((px(A4_CM[1]), px(A4_CM[0])), 255, np.uint8)
    dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
    side, gap = px(a.size_cm), px(2.0)
    x, y = px(2.0), px(2.5)
    for marker_id in [m for m in a.ids for _ in range(a.copies)]:
        if x + side > page.shape[1] - px(1.0):
            x, y = px(2.0), y + side + gap + px(1.0)
        if y + side + px(1.0) > page.shape[0]:
            raise SystemExit("too many markers for one A4 page: lower --copies or --size_cm")
        page[y:y + side, x:x + side] = cv2.aruco.generateImageMarker(dictionary, marker_id, side)
        cv2.putText(page, f"drone {marker_id} ({a.size_cm:g} cm)", (x, y + side + px(0.6)),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.0, 0, 2)
        x += side + gap
    cv2.putText(page, "Print at 100% scale. Check the black square with a ruler.", (px(2.0), px(1.5)),
                cv2.FONT_HERSHEY_SIMPLEX, 1.4, 0, 3)

    if a.out.lower().endswith(".pdf"):
        from PIL import Image
        Image.fromarray(page).save(a.out, resolution=DPI)
    else:
        cv2.imwrite(a.out, page)
    print(f"{a.out}: ids {a.ids} x{a.copies}, {a.size_cm:g} cm at {DPI} dpi")


if __name__ == "__main__":
    main()
