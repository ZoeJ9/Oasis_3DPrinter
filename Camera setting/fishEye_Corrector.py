"""
Interactive fisheye/barrel distortion correction tool.

Why this approach instead of cv2.calibrateCamera:
    Full checkerboard calibration needs ~15-20 images of a checkerboard pattern
    covering different positions/angles across the frame. With only 4 ruler photos,
    there isn't enough data for a robust calibrateCamera() solve.

    Instead, this tool uses the "straight lines should stay straight" principle.
    Since rulers are straight edges, you can manually tune the radial distortion
    coefficients (k1, k2, k3) and tangential coefficients (p1, p2) with live
    trackbars until the ruler edges in your photo look straight. This is a classic
    single-image distortion correction technique and works well for a fixed lens/
    camera setup like the ELP 48MP USB camera mounted on Oasis.

    Once you find good coefficients, they apply to ALL images from this camera at
    this fixed focal length/zoom setting -- you don't need to redo this per photo.

Usage:
    python fisheye_correction_tool.py --image path/to/ruler_photo.jpg

Controls:
    - Adjust sliders until the ruler edges (especially near the frame edges,
      where fisheye is worst) look straight.
    - Press 's' to save the undistorted image + print final coefficients.
    - Press 'q' to quit without saving.
"""

import argparse
import json
import os

import cv2
import numpy as np


def build_camera_matrix(width: int, height: int, fx_scale: float) -> np.ndarray:
    """Rough camera matrix assuming principal point at image center.

    fx_scale is expressed as a fraction of image width; without a true checkerboard
    calibration this is an approximation, but it's fine for visual undistortion --
    fx mostly just affects how aggressively the correction pulls in the edges.
    """
    fx = fy = width * fx_scale
    cx, cy = width / 2.0, height / 2.0
    return np.array([[fx, 0, cx],
                      [0, fy, cy],
                      [0, 0, 1]], dtype=np.float64)


def nothing(_):
    pass


def main():
    parser = argparse.ArgumentParser(description="Interactive fisheye correction via ruler-straightening")
    parser.add_argument("--image", required=True, help="Path to a ruler photo (e.g. one of your 4 images)")
    parser.add_argument("--out-dir", default="undistort_output", help="Where to save results")
    args = parser.parse_args()

    img = cv2.imread(args.image)
    if img is None:
        raise FileNotFoundError(f"Could not read image: {args.image}")

    h, w = img.shape[:2]
    print(f"Loaded image: {w}x{h}")

    window = "Fisheye Correction (s=save, q=quit)"
    cv2.namedWindow(window, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(window, min(w, 900), min(h, 1600))

    # Trackbars store ints; we map them to signed float ranges below.
    # k1, k2, k3: radial distortion. p1, p2: tangential distortion.
    # fx_scale: rough focal length as a fraction of image width.
    cv2.createTrackbar("k1 (x1000)", window, 500, 1000, nothing)   # maps to -0.5 .. 0.5
    cv2.createTrackbar("k2 (x1000)", window, 500, 1000, nothing)   # maps to -0.5 .. 0.5
    cv2.createTrackbar("k3 (x1000)", window, 500, 1000, nothing)   # maps to -0.5 .. 0.5
    cv2.createTrackbar("p1 (x1000)", window, 500, 1000, nothing)   # maps to -0.05 .. 0.05
    cv2.createTrackbar("p2 (x1000)", window, 500, 1000, nothing)   # maps to -0.05 .. 0.05
    cv2.createTrackbar("fx_scale (x100)", window, 100, 200, nothing)  # maps to 0.0 .. 2.0 * width

    def get_params():
        k1 = (cv2.getTrackbarPos("k1 (x1000)", window) - 500) / 1000.0
        k2 = (cv2.getTrackbarPos("k2 (x1000)", window) - 500) / 1000.0
        k3 = (cv2.getTrackbarPos("k3 (x1000)", window) - 500) / 1000.0
        p1 = (cv2.getTrackbarPos("p1 (x1000)", window) - 500) / 10000.0
        p2 = (cv2.getTrackbarPos("p2 (x1000)", window) - 500) / 10000.0
        fx_scale = cv2.getTrackbarPos("fx_scale (x100)", window) / 100.0
        return k1, k2, k3, p1, p2, fx_scale

    print("Tune sliders until ruler edges look straight. Press 's' to save, 'q' to quit.")

    while True:
        k1, k2, k3, p1, p2, fx_scale = get_params()
        if fx_scale <= 0:
            fx_scale = 0.01

        camera_matrix = build_camera_matrix(w, h, fx_scale)
        dist_coeffs = np.array([k1, k2, p1, p2, k3], dtype=np.float64)

        undistorted = cv2.undistort(img, camera_matrix, dist_coeffs)

        # Side-by-side preview: original | corrected
        preview = np.hstack([img, undistorted])
        cv2.imshow(window, preview)

        key = cv2.waitKey(30) & 0xFF
        if key == ord('q'):
            print("Quit without saving.")
            break
        elif key == ord('s'):
            os.makedirs(args.out_dir, exist_ok=True)
            base = os.path.splitext(os.path.basename(args.image))[0]
            out_path = os.path.join(args.out_dir, f"{base}_undistorted.png")
            cv2.imwrite(out_path, undistorted)

            params = {
                "camera_matrix": camera_matrix.tolist(),
                "dist_coeffs": dist_coeffs.tolist(),
                "image_size": [w, h],
                "fx_scale": fx_scale,
            }
            params_path = os.path.join(args.out_dir, "distortion_params.json")
            with open(params_path, "w") as f:
                json.dump(params, f, indent=2)

            print(f"Saved corrected image -> {out_path}")
            print(f"Saved distortion params -> {params_path}")
            print("Reuse these params on other photos from the same camera/zoom with:")
            print("    cv2.undistort(img, camera_matrix, dist_coeffs)")
            break

    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()