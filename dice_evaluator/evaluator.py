"""DiceEvaluator: per-layer print quality assessment via Dice coefficient."""

import re
from pathlib import Path
from typing import List, Tuple

import cv2
import numpy as np
import pandas as pd

from .calibrate import load_calibration, mm_to_pixel
from .constants import BED_DIAMETER_MM


class DiceEvaluator:
    """Evaluates print quality by comparing captured layer images to the SVG reference mask.

    Args:
        svg_path:     Path to the SVG file used for printing.
        image_array:  Binary mask (0/1) of shape (height, width) from ImageConverter.
        captures_dir: Directory containing layer_*.png capture files.

    Raises:
        FileNotFoundError: If calibration.npz is not found next to the SVG.
    """

    def __init__(self, svg_path: str, image_array: np.ndarray, captures_dir: str) -> None:
        self.svg_path = Path(svg_path)
        self.image_array = image_array  # shape: (height, width), binary 0/1
        self.captures_dir = Path(captures_dir)

        calib = load_calibration(str(self.svg_path.parent))
        if calib is None:
            raise FileNotFoundError(
                f"calibration.npz not found in {self.svg_path.parent}. "
                "Run calibration from the printer UI first."
            )
        self.calib = calib

    def get_reference_mask(self, cam_h: int, cam_w: int) -> np.ndarray:
        """Remap the SVG binary mask from mm space to camera pixel space.

        Each pixel (row, col) in image_array is treated as occupying:
            x_mm = col * (BED_DIAMETER_MM / image_array.shape[1])
            y_mm = row * (BED_DIAMETER_MM / image_array.shape[0])

        Args:
            cam_h: Camera image height in pixels.
            cam_w: Camera image width in pixels.

        Returns:
            Binary mask of shape (cam_h, cam_w) with dtype uint8 (0 or 1).
        """
        arr_h, arr_w = self.image_array.shape
        out = np.zeros((cam_h, cam_w), dtype=np.uint8)

        for row in range(arr_h):
            for col in range(arr_w):
                if self.image_array[row, col] == 0:
                    continue
                x_mm = col * (BED_DIAMETER_MM / arr_w)
                y_mm = row * (BED_DIAMETER_MM / arr_h)
                x_px, y_px = mm_to_pixel(x_mm, y_mm, self.calib)
                if 0 <= x_px < cam_w and 0 <= y_px < cam_h:
                    out[y_px, x_px] = 1

        # Dilate by 1 px to fill gaps from rounding
        kernel = np.ones((2, 2), dtype=np.uint8)
        out = cv2.dilate(out, kernel, iterations=1)
        return out

    def evaluate_layer(self, layer_idx: int, captured_img: np.ndarray) -> dict:
        """Compute the Dice coefficient between a captured image and the reference mask.

        Args:
            layer_idx:    Layer index (1-based) for reporting.
            captured_img: RGB image of shape (h, w, ch) captured by CameraController.

        Returns:
            dict with keys:
                layer   (int)          – layer index
                dice    (float)        – Dice coefficient in [0, 1]
                overlay (np.ndarray)   – RGB image with XOR discrepancy highlighted red,
                                         shape (h, w, ch)
        """
        h, w, ch = captured_img.shape
        ref_mask = self.get_reference_mask(h, w)

        cap_gray = cv2.cvtColor(captured_img, cv2.COLOR_RGB2GRAY)
        _, cap_mask = cv2.threshold(cap_gray, 0, 1, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

        intersection = np.logical_and(ref_mask, cap_mask).sum()
        denom = ref_mask.sum() + cap_mask.sum()
        dice = float(2 * intersection / denom) if denom > 0 else 0.0

        overlay = captured_img.copy()
        overlay[np.logical_xor(ref_mask.astype(bool), cap_mask.astype(bool))] = [255, 0, 0]

        return {"layer": layer_idx, "dice": dice, "overlay": overlay}

    def evaluate_all(self) -> pd.DataFrame:
        """Evaluate every layer_*.png in captures_dir and save results.

        Overlay images are saved to captures_dir/overlays/layer_NNN_overlay.png.
        A CSV log is saved to captures_dir/{svg_stem}_dice_log.csv.

        Returns:
            DataFrame with columns [layer, dice].
        """
        overlays_dir = self.captures_dir / "overlays"
        overlays_dir.mkdir(exist_ok=True)

        pattern = re.compile(r"layer_(\d+)\.png$", re.IGNORECASE)
        png_files: List[Tuple[int, Path]] = []
        for p in self.captures_dir.iterdir():
            m = pattern.match(p.name)
            if m:
                png_files.append((int(m.group(1)), p))
        png_files.sort(key=lambda t: t[0])

        records = []
        for layer_idx, png_path in png_files:
            bgr = cv2.imread(str(png_path))
            if bgr is None:
                continue
            img_rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)

            result = self.evaluate_layer(layer_idx, img_rgb)

            overlay_bgr = cv2.cvtColor(result["overlay"], cv2.COLOR_RGB2BGR)
            overlay_path = overlays_dir / f"layer_{layer_idx:03d}_overlay.png"
            cv2.imwrite(str(overlay_path), overlay_bgr)

            records.append({"layer": result["layer"], "dice": result["dice"]})

        df = pd.DataFrame(records, columns=["layer", "dice"])
        csv_path = self.captures_dir / f"{self.svg_path.stem}_dice_log.csv"
        df.to_csv(str(csv_path), index=False)

        return df
