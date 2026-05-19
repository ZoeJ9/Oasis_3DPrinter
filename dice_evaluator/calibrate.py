"""Calibration utilities: SVG generation, circle detection, and px<->mm mapping."""

from pathlib import Path
from typing import Optional, Tuple

import cv2
import numpy as np

from .constants import (
    BED_DIAMETER_MM,
    BED_RADIUS_MM,
    BUILD_CENTER_X_MM,
    BUILD_CENTER_Y_MM,
    CALIB_LINE_WIDTH_MM,
    CALIB_NPZ_FILENAME,
    GRBL_HOME_X_MM,
    GRBL_HOME_Y_MM,
)

# GRBL working area dimensions in mm
_WORK_W = 480.0
_WORK_H = 250.0


def generate_calibration_svg(save_path: str) -> str:
    """Generate a calibration SVG with a single circle centred on the build platform.

    The circle has:
        cx=BUILD_CENTER_X_MM, cy=BUILD_CENTER_Y_MM, r=BED_RADIUS_MM
    The viewBox covers the full GRBL working area so pixel mapping is consistent.

    Args:
        save_path: Destination file path for the SVG.

    Returns:
        Absolute path string of the saved SVG.
    """
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="0 0 {_WORK_W} {_WORK_H}" '
        f'width="{_WORK_W}" height="{_WORK_H}">\n'
        f'  <circle '
        f'cx="{BUILD_CENTER_X_MM}" cy="{BUILD_CENTER_Y_MM}" '
        f'r="{BED_RADIUS_MM}" '
        f'stroke="black" stroke-width="{CALIB_LINE_WIDTH_MM}" fill="none"/>\n'
        f'</svg>\n'
    )
    path = Path(save_path)
    path.write_text(svg, encoding="utf-8")
    return str(path.resolve())


def detect_circle_in_image(
    img: np.ndarray,
) -> Optional[Tuple[float, float, float]]:
    """Detect the largest circle in an RGB image using Hough transform.

    Args:
        img: RGB image array of shape (h, w, ch).

    Returns:
        (cx_px, cy_px, r_px) of the best detected circle, or None if not found.
    """
    h, w, ch = img.shape
    gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
    _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    circles = cv2.HoughCircles(
        thresh,
        method=cv2.HOUGH_GRADIENT,
        dp=1,
        minDist=w // 2,
        param1=50,
        param2=30,
        minRadius=int(min(h, w) * 0.2),
        maxRadius=int(min(h, w) * 0.8),
    )

    if circles is None:
        return None

    cx, cy, r = circles[0][0]
    return float(cx), float(cy), float(r)


def compute_calibration(
    cx_px: float,
    cy_px: float,
    r_px: float,
    cx_mm: float = BUILD_CENTER_X_MM,
    cy_mm: float = BUILD_CENTER_Y_MM,
    r_mm: float = BED_RADIUS_MM,
) -> dict:
    """Compute scale and offset from detected circle geometry.

    Assumes uniform scale (same px/mm ratio for X and Y).

    Args:
        cx_px: Circle centre X in pixels.
        cy_px: Circle centre Y in pixels.
        r_px:  Circle radius in pixels.
        cx_mm: Known centre X in mm (default BUILD_CENTER_X_MM).
        cy_mm: Known centre Y in mm (default BUILD_CENTER_Y_MM).
        r_mm:  Known radius in mm  (default BED_RADIUS_MM).

    Returns:
        dict with keys: scale_x, scale_y, offset_x, offset_y, circle_px.
    """
    scale_x = r_px / r_mm
    scale_y = r_px / r_mm
    offset_x = cx_px - cx_mm * scale_x
    offset_y = cy_px - cy_mm * scale_y
    return {
        "scale_x": scale_x,
        "scale_y": scale_y,
        "offset_x": offset_x,
        "offset_y": offset_y,
        "circle_px": (cx_px, cy_px, r_px),
    }


def save_calibration(calib: dict, svg_dir: str) -> None:
    """Save calibration dict to a .npz file alongside the SVG.

    Args:
        calib:   Dict returned by compute_calibration().
        svg_dir: Directory where calibration.npz will be written.
    """
    out = Path(svg_dir) / CALIB_NPZ_FILENAME
    np.savez(
        str(out),
        scale_x=calib["scale_x"],
        scale_y=calib["scale_y"],
        offset_x=calib["offset_x"],
        offset_y=calib["offset_y"],
        circle_px=np.array(calib["circle_px"]),
    )


def load_calibration(svg_dir: str) -> Optional[dict]:
    """Load calibration from calibration.npz in svg_dir.

    Args:
        svg_dir: Directory that should contain calibration.npz.

    Returns:
        Calibration dict with keys scale_x, scale_y, offset_x, offset_y,
        circle_px, or None if the file is not found.
    """
    path = Path(svg_dir) / CALIB_NPZ_FILENAME
    if not path.exists():
        return None
    data = np.load(str(path))
    return {
        "scale_x": float(data["scale_x"]),
        "scale_y": float(data["scale_y"]),
        "offset_x": float(data["offset_x"]),
        "offset_y": float(data["offset_y"]),
        "circle_px": tuple(data["circle_px"].tolist()),
    }


def mm_to_pixel(x_mm: float, y_mm: float, calib: dict) -> Tuple[int, int]:
    """Convert GRBL mm coordinates to image pixel coordinates.

    Args:
        x_mm:  X position in mm (GRBL space).
        y_mm:  Y position in mm (GRBL space).
        calib: Calibration dict from load_calibration() or compute_calibration().

    Returns:
        (x_px, y_px) as integers.
    """
    x_px = x_mm * calib["scale_x"] + calib["offset_x"]
    y_px = y_mm * calib["scale_y"] + calib["offset_y"]
    return int(x_px), int(y_px)
