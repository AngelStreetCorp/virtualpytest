import argparse
import os
from time import perf_counter
from dataclasses import dataclass
from typing import Optional, Tuple

import cv2
import numpy as np


@dataclass
class BoundingBox:
    x: int
    y: int
    w: int
    h: int

    def as_tuple(self) -> Tuple[int, int, int, int]:
        return self.x, self.y, self.w, self.h


def _compute_dark_mask(gray_roi: np.ndarray) -> np.ndarray:
    """
    Produce a boolean mask where True corresponds to dark pixels.

    Uses Otsu threshold on a lightly blurred ROI to separate dark subtitle
    boxes from the background. The ROI is expected to be grayscale [0, 255].
    """
    blurred = cv2.GaussianBlur(gray_roi, (5, 5), 0)
    # Otsu threshold returns threshold value; below it is considered dark
    # We want a boolean mask of dark pixels.
    thr, _ = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    dark_mask = blurred <= thr
    return dark_mask


def _find_vertical_span(mask: np.ndarray, min_density: float, join_gap: int) -> Optional[Tuple[int, int]]:
    """
    Given a boolean mask (rows x cols) of dark pixels, find a vertical span
    [row_start, row_end) that corresponds to the subtitle region by looking at
    rows with high dark-pixel density. Returns None if not found.
    """
    # Compute per-row dark pixel fraction using OpenCV reductions (faster than NumPy on large arrays)
    row_avg = cv2.reduce(mask.astype(np.uint8) * 255, 1, cv2.REDUCE_AVG)  # shape (rows,1), values 0..255
    row_density = (row_avg.astype(np.float32).ravel()) / 255.0
    # Smooth vertically with a box filter (1D moving average)
    kernel_size = max(7, (mask.shape[0] // 100) * 2 + 1)
    smoothed = cv2.blur(row_density.reshape(-1, 1), (kernel_size, 1)).ravel()
    active = smoothed > float(min_density)

    # Find contiguous active segments; merge small gaps up to join_gap
    indices = np.where(active)[0]
    if indices.size == 0:
        return None

    segments = []
    start = indices[0]
    prev = indices[0]
    for idx in indices[1:]:
        if idx - prev <= join_gap:
            prev = idx
            continue
        segments.append((start, prev))
        start = idx
        prev = idx
    segments.append((start, prev))

    # Choose the longest segment (by height)
    best = max(segments, key=lambda s: s[1] - s[0])
    return int(best[0]), int(best[1] + 1)


def _find_horizontal_span(mask: np.ndarray, min_density: float) -> Optional[Tuple[int, int]]:
    """
    Given a boolean mask (rows x cols) restricted to the previously found
    vertical subtitle span, find the horizontal span [col_start, col_end).
    Returns None if not found.
    """
    if mask.size == 0:
        return None
    col_avg = cv2.reduce(mask.astype(np.uint8) * 255, 0, cv2.REDUCE_AVG)  # shape (1, cols)
    col_density = (col_avg.astype(np.float32).ravel()) / 255.0
    kernel_size = max(7, (mask.shape[1] // 100) * 2 + 1)
    smoothed = cv2.blur(col_density.reshape(1, -1), (1, kernel_size)).ravel()
    active = smoothed > float(min_density)

    cols = np.where(active)[0]
    if cols.size == 0:
        return None
    return int(cols[0]), int(cols[-1] + 1)


def find_subtitle_bbox(gray_image: np.ndarray) -> BoundingBox:
    """
    Detect the subtitle bounding box in a grayscale frame.

    Strategy:
      - Restrict search to the bottom half of the image.
      - Identify rows with high density of dark pixels (subtitle boxes are black).
      - Project within those rows to find wide, dark columns.

    Returns a BoundingBox. Raises ValueError if not found.
    """
    if len(gray_image.shape) != 2:
        raise ValueError("Input image must be grayscale (H x W).")

    height, width = gray_image.shape
    bottom_start = int(height * 0.5)
    roi = gray_image[bottom_start:height, :]

    dark_mask = _compute_dark_mask(roi)

    # Find vertical span in ROI with dense dark pixels
    vert_span = _find_vertical_span(dark_mask, min_density=0.35, join_gap=max(6, height // 120))
    if vert_span is None:
        raise ValueError("Subtitle vertical span not found.")

    v0, v1 = vert_span
    # Slight padding to include margins
    pad_v = max(2, (v1 - v0) // 20)
    v0 = max(0, v0 - pad_v)
    v1 = min(dark_mask.shape[0], v1 + pad_v)

    dark_mask_band = dark_mask[v0:v1, :]

    # Find horizontal span in the selected band
    horiz_span = _find_horizontal_span(dark_mask_band, min_density=0.20)
    if horiz_span is None:
        raise ValueError("Subtitle horizontal span not found.")

    h0, h1 = horiz_span
    pad_h = max(2, (h1 - h0) // 30)
    h0 = max(0, h0 - pad_h)
    h1 = min(width, h1 + pad_h)

    x = h0
    y = bottom_start + v0
    w = max(1, h1 - h0)
    h = max(1, v1 - v0)

    # Basic sanity: expect a wide, short region near the bottom
    if w < int(width * 0.25) or h > int(height * 0.35):
        raise ValueError("Detected region does not meet subtitle geometry heuristics.")

    return BoundingBox(x=x, y=y, w=w, h=h)


def crop_subtitle_region(image_path: str, output_path: Optional[str] = None) -> BoundingBox:
    """
    Load an image (grayscale or color), detect the subtitle area, and optionally
    write the cropped region.
    """
    image = cv2.imread(image_path, cv2.IMREAD_UNCHANGED)
    if image is None:
        raise ValueError(f"Failed to read image: {image_path}")

    if image.ndim == 3:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    else:
        gray = image

    bbox = find_subtitle_bbox(gray)
    x, y, w, h = bbox.as_tuple()

    if output_path:
        crop = image[y : y + h, x : x + w]
        ok = cv2.imwrite(output_path, crop)
        if not ok:
            raise ValueError(f"Failed to write cropped image to: {output_path}")

    return bbox


def _draw_bbox(image: np.ndarray, bbox: BoundingBox) -> np.ndarray:
    x, y, w, h = bbox.as_tuple()
    vis = image.copy()
    cv2.rectangle(vis, (x, y), (x + w, y + h), (0, 255, 0), 2)
    return vis


def main() -> None:
    parser = argparse.ArgumentParser(description="Crop subtitle area from an image.")
    parser.add_argument(
        "input",
        nargs="?",
        default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "img", "subtitles_original.jpg"),
        help="Path to input image (grayscale or color). Defaults to subtitles_original.jpg",
    )
    parser.add_argument("--out", dest="output", help="Optional path to save cropped subtitle region")
    parser.add_argument("--viz", dest="viz", help="Optional path to save visualization with bbox")
    args = parser.parse_args()

    # Auto-generate output filename alongside input when not provided
    output = args.output
    if output is None and args.input:
        import os

        base, ext = os.path.splitext(args.input)
        output = f"{base}_crop{ext or '.jpg'}"

    start = perf_counter()
    bbox = crop_subtitle_region(args.input, output)
    elapsed_ms = (perf_counter() - start) * 1000.0

    # Optional visualization
    if args.viz:
        image = cv2.imread(args.input)
        vis = _draw_bbox(image, bbox)
        ok = cv2.imwrite(args.viz, vis)
        if not ok:
            raise ValueError(f"Failed to write visualization to: {args.viz}")

    print(f"bbox={bbox} time_ms={elapsed_ms:.2f}")  # simple stdout for quick inspection


if __name__ == "__main__":
    main()


