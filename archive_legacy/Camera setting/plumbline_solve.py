"""
Step 2 of plumb-line calibration: solve for distortion coefficients (k1, k2,
k3, p1, p2) + focal length that make the clicked edge points (from
plumbline_pick_points.py) as straight as possible after undistortion.

Method (Devernay & Faugeras plumb-line calibration):
    For a candidate set of distortion parameters, undistort every clicked
    point, fit the best straight line through each line's undistorted points,
    and measure each point's perpendicular distance to that line. Those
    distances are the residuals. scipy.optimize.least_squares adjusts
    (k1, k2, k3, p1, p2) to minimize the sum of squared residuals across
    every line in every image at once -- more data and more lines means a
    much more stable fit than tuning against one photo by eye.

    Focal length (fx) is fixed rather than solved for. Straightness alone
    can't separate fx from k1/k2 -- many (fx, k1, k2) combinations flatten
    the same lines equally well (a gauge freedom in the optimization), so
    solving for fx jointly makes the fit wander to arbitrary, unstable
    values. Fixing fx to a reasonable estimate (image width is a decent
    default for typical webcam-like FOVs; pass --fx to override) removes
    that ambiguity and leaves a well-posed problem for the distortion terms.

Usage:
    python plumbline_solve.py --points plumbline_points.json --out-dir undistort_output [--fx 700]
"""

import argparse
import json
import os

import cv2
import numpy as np
from scipy.optimize import least_squares

# undistortPoints computes in float32 internally; scipy's default finite-difference
# step (~1e-8 * x) rounds away to zero at that precision, making the Jacobian look
# flat and stalling the optimizer at the initial guess. A larger explicit step avoids it.
DIFF_STEP = 1e-4


def build_camera_matrix(width, height, fx):
    cx, cy = width / 2.0, height / 2.0
    return np.array([[fx, 0, cx],
                      [0, fx, cy],
                      [0, 0, 1]], dtype=np.float64)


def line_residuals(points_undist):
    """Perpendicular distance of each point to the best-fit line through them."""
    pts = np.asarray(points_undist, dtype=np.float64)
    centroid = pts.mean(axis=0)
    centered = pts - centroid
    # Best-fit direction = principal axis (largest singular vector).
    _, _, vt = np.linalg.svd(centered)
    direction = vt[0]
    normal = np.array([-direction[1], direction[0]])
    return centered @ normal


def make_residual_fn(lines_per_image, image_size, fx):
    """fx is fixed (see module docstring); only k1, k2, k3, p1, p2 are solved for."""
    w, h = image_size
    camera_matrix = build_camera_matrix(w, h, fx)

    def residual_fn(params):
        k1, k2, k3, p1, p2 = params
        dist_coeffs = np.array([k1, k2, p1, p2, k3], dtype=np.float64)

        all_residuals = []
        for lines in lines_per_image:
            for line_pts in lines:
                # undistortPoints requires float32 input.
                pts = np.array(line_pts, dtype=np.float32).reshape(-1, 1, 2)
                undist = cv2.undistortPoints(pts, camera_matrix, dist_coeffs, P=camera_matrix)
                undist = undist.reshape(-1, 2)
                all_residuals.append(line_residuals(undist))
        return np.concatenate(all_residuals)

    return residual_fn


def main():
    parser = argparse.ArgumentParser(description="Solve distortion coefficients from plumb-line point data")
    parser.add_argument("--points", default="plumbline_points.json", help="Output of plumbline_pick_points.py")
    parser.add_argument("--out-dir", default="undistort_output", help="Where to save distortion_params.json")
    parser.add_argument("--fx", type=float, default=None,
                         help="Fixed focal length in pixels (default: image width, a reasonable rough estimate)")
    args = parser.parse_args()

    with open(args.points) as f:
        data = json.load(f)
    if not data:
        raise ValueError(f"{args.points} has no annotated lines -- run plumbline_pick_points.py first")

    lines_per_image = [d["lines"] for d in data]

    sample_img = cv2.imread(data[0]["image"])
    h, w = sample_img.shape[:2]
    for d in data:
        img = cv2.imread(d["image"])
        if img.shape[:2] != (h, w):
            raise ValueError(f"{d['image']} is {img.shape[1]}x{img.shape[0]}, expected {w}x{h}. "
                              "All calibration images must share the same resolution.")

    n_lines = sum(len(d["lines"]) for d in data)
    n_points = sum(len(line) for d in data for line in d["lines"])
    print(f"Loaded {n_lines} line(s), {n_points} point(s) across {len(data)} image(s) at {w}x{h}")
    if n_lines < 4:
        print("Warning: fewer than 4 lines total. Include both horizontal and vertical "
              "edges (e.g. ruler's long edge and side edge) or k1/k2/k3 won't be well separated.")

    fx = args.fx if args.fx is not None else float(w)
    print(f"Using fixed focal length fx={fx:.1f}px (pass --fx to change)")

    residual_fn = make_residual_fn(lines_per_image, (w, h), fx)

    x0 = np.zeros(5)  # k1, k2, k3, p1, p2 -- no distortion as a starting guess
    rms_before = np.sqrt(np.mean(residual_fn(x0) ** 2))

    print("Solving least-squares fit...")
    result = least_squares(residual_fn, x0, method="lm", diff_step=DIFF_STEP, max_nfev=10000)

    k1, k2, k3, p1, p2 = result.x
    rms_after = np.sqrt(np.mean(result.fun ** 2))
    print(f"RMS straight-line residual: {rms_before:.3f}px -> {rms_after:.3f}px")
    print(f"k1={k1:.5f} k2={k2:.5f} k3={k3:.5f} p1={p1:.5f} p2={p2:.5f}")

    camera_matrix = build_camera_matrix(w, h, fx)
    dist_coeffs = np.array([k1, k2, p1, p2, k3], dtype=np.float64)

    os.makedirs(args.out_dir, exist_ok=True)
    params_path = os.path.join(args.out_dir, "distortion_params.json")
    with open(params_path, "w") as f:
        json.dump({
            "camera_matrix": camera_matrix.tolist(),
            "dist_coeffs": dist_coeffs.tolist(),
            "image_size": [w, h],
            "rms_residual_px": rms_after,
            "method": "plumb_line_least_squares",
        }, f, indent=2)
    print(f"Saved -> {params_path}")
    print("Reuse everywhere with fisheye_apply.FisheyeCorrector(params_path)")

    # Save an undistorted preview of the first image so you can eyeball the result.
    preview = cv2.undistort(sample_img, camera_matrix, dist_coeffs)
    preview_path = os.path.join(args.out_dir, "plumbline_preview_undistorted.png")
    cv2.imwrite(preview_path, np.hstack([sample_img, preview]))
    print(f"Saved before/after preview -> {preview_path}")


if __name__ == "__main__":
    main()
