"""
Reusable fisheye/barrel distortion corrector.

Loads the distortion_params.json produced by fishEye_Corrector.py's interactive
tuner and applies cv2.undistort() to any frame. Import this into printer code
to correct every camera frame with the coefficients tuned once for this
camera/zoom setup.

Usage:
    from fisheye_apply import FisheyeCorrector

    corrector = FisheyeCorrector("undistort_output/distortion_params.json")
    fixed = corrector.undistort(frame)
"""

import json

import cv2
import numpy as np


class FisheyeCorrector:
    def __init__(self, params_path: str):
        with open(params_path) as f:
            params = json.load(f)

        self.camera_matrix = np.array(params["camera_matrix"], dtype=np.float64)
        self.dist_coeffs = np.array(params["dist_coeffs"], dtype=np.float64)
        self.calib_size = tuple(params["image_size"])  # (w, h) the params were tuned on

        self._map1 = None
        self._map2 = None
        self._map_size = None

    def _scaled_camera_matrix(self, w: int, h: int) -> np.ndarray:
        """Rescale fx/fy/cx/cy for frames captured at a different resolution
        than calibration was done at (e.g. calibrated at 720x1280 preview res,
        applied to a 2160x3840 full-res capture). dist_coeffs are on normalized
        coordinates and don't need rescaling."""
        calib_w, calib_h = self.calib_size
        if (w, h) == (calib_w, calib_h):
            return self.camera_matrix
        sx, sy = w / calib_w, h / calib_h
        scaled = self.camera_matrix.copy()
        scaled[0, 0] *= sx  # fx
        scaled[1, 1] *= sy  # fy
        scaled[0, 2] *= sx  # cx
        scaled[1, 2] *= sy  # cy
        return scaled

    def undistort(self, frame: np.ndarray) -> np.ndarray:
        h, w = frame.shape[:2]
        if self._map_size != (w, h):
            camera_matrix = self._scaled_camera_matrix(w, h)
            self._map1, self._map2 = cv2.initUndistortRectifyMap(
                camera_matrix, self.dist_coeffs, None, camera_matrix,
                (w, h), cv2.CV_16SC2,
            )
            self._map_size = (w, h)
        return cv2.remap(frame, self._map1, self._map2, cv2.INTER_LINEAR)


def _demo():
    """ponytail check: verify undistort runs and preserves frame shape."""
    params = {
        "camera_matrix": [[800.0, 0, 320.0], [0, 800.0, 240.0], [0, 0, 1]],
        "dist_coeffs": [-0.1, 0.05, 0.0, 0.0, 0.0],
        "image_size": [640, 480],
    }
    import os
    import tempfile

    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    with open(path, "w") as f:
        json.dump(params, f)

    try:
        corrector = FisheyeCorrector(path)
        frame = np.random.randint(0, 255, (480, 640, 3), dtype=np.uint8)
        fixed = corrector.undistort(frame)
        assert fixed.shape == frame.shape
        # calling again with same size should reuse cached maps
        map1_ref = corrector._map1
        corrector.undistort(frame)
        assert corrector._map1 is map1_ref

        # a frame at a different resolution (e.g. full-res capture vs preview
        # calibration size) must rescale camera_matrix, not reuse it as-is
        big_frame = np.random.randint(0, 255, (960, 1280, 3), dtype=np.uint8)
        fixed_big = corrector.undistort(big_frame)
        assert fixed_big.shape == big_frame.shape
        assert corrector._map1 is not map1_ref
        print("fisheye_apply self-check passed")
    finally:
        os.remove(path)


if __name__ == "__main__":
    _demo()
