"""Standalone binder-delivery calibration: how much binder mass lands per
unit area as a function of HP45 density, layer_passes, and print speed.

Usage:
    python cal_binder_delivery.py --dry-run --mode density
    python cal_binder_delivery.py --verify-position --mode density
    python cal_binder_delivery.py --mode density
    python cal_binder_delivery.py --mode passes
    python cal_binder_delivery.py --mode speed

Real runs require a printed weighing-paper procedure: mass is measured before
and after each square print to compute delta_g. No image analysis is done here.
"""

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cal_common

# --- edit these for your setup ---
GRBL_PORT = "COM5"
HP45_PORT = "COM6"
CAMERA_PORT = 0
# ----------------------------------

BUILD_CENTER_X_MM = 157.0
BUILD_CENTER_Y_MM = 116.0
SQUARE_SIZE_MM = 45.0
DPI = 600
LAYER_THICKNESS_MM = 0.1
TRAVEL_SPEED = 3000.0
DEFAULT_PRINT_SPEED = 2200.0
DEFAULT_DENSITY = 250
DEFAULT_PASSES = 3  # print the same square 3x per measurement to accumulate more binder mass

TARGET_REPS = 3

CONDITIONS = {
    "density": [100, 200, 300, 400, 500],
    "passes": [3,6,9],
    "speed": [800, 2200, 3000],
}

RESULTS_DIR = cal_common.RESULTS_DIR


def _csv_path(mode: str) -> str:
    return os.path.join(RESULTS_DIR, f"binder_delivery_{mode}.csv")


FIELDNAMES = [
    "mode", "condition_id", "level_name", "level_value", "rep",
    "mass_before_g", "mass_after_g", "delta_g", "area_mm2", "timestamp",
]


def _params_for_level(mode: str, level_value):
    """Return (density, passes, print_speed) for a given mode/level, holding
    the other two parameters at their defaults."""
    density = DEFAULT_DENSITY
    passes = DEFAULT_PASSES
    print_speed = DEFAULT_PRINT_SPEED
    if mode == "density":
        density = level_value
    elif mode == "passes":
        passes = level_value
    elif mode == "speed":
        print_speed = level_value
    return density, passes, print_speed


def cmd_dry_run(mode: str):
    corners = cal_common.compute_square_corners(BUILD_CENTER_X_MM, BUILD_CENTER_Y_MM, SQUARE_SIZE_MM)
    warnings = cal_common.check_bed_fit(corners)
    print(f"Mode: {mode}")
    print(f"Center: ({BUILD_CENTER_X_MM}, {BUILD_CENTER_Y_MM})")
    print(f"Square size: {SQUARE_SIZE_MM} mm")
    print("Corners:")
    for c in corners:
        print(f"  {c}")
    if warnings:
        print("Bed-fit warnings:")
        for w in warnings:
            print(f"  - {w}")
    else:
        print("Bed-fit: OK")


def cmd_verify_position():
    grbl = cal_common.GRBL()
    if grbl.Connect(GRBL_PORT) != 1:
        raise RuntimeError(f"Failed to connect to GRBL on {GRBL_PORT}")
    try:
        cal_common.home_and_wait(grbl)
        corners = cal_common.compute_square_corners(BUILD_CENTER_X_MM, BUILD_CENTER_Y_MM, SQUARE_SIZE_MM)
        for i, (x, y) in enumerate(corners, start=1):
            grbl.SerialGotoXY(x, y, TRAVEL_SPEED)
            cal_common.wait_motion_idle(grbl)
            input(f"At corner {i}/4: ({x:.2f}, {y:.2f}). Press Enter to continue...")
        print("Position verification complete.")
    finally:
        grbl.Disconnect()


def _show_menu(mode: str, progress: dict):
    print(f"\n=== Binder Delivery Calibration - mode: {mode} ===")
    for level in CONDITIONS[mode]:
        cid = f"{mode}_{level}"
        done = progress.get(cid, 0)
        print(f"  [{level}] {cid}: {done}/{TARGET_REPS} reps")
    print("  [q] quit")


def cmd_real_run(mode: str):
    print("=" * 70)
    print("BINDER DELIVERY CALIBRATION - WEIGHING PAPER PROCEDURE")
    print("Place a fresh weighing paper on the build platform before each print.")
    print("Use an analytical balance for mass_before_g / mass_after_g.")
    print("=" * 70)

    grbl, inkjet = cal_common.connect_hardware(GRBL_PORT, HP45_PORT)
    try:
        cal_common.home_and_wait(grbl)

        csv_path = _csv_path(mode)
        levels = CONDITIONS[mode]

        while True:
            progress = cal_common.load_progress(csv_path)
            _show_menu(mode, progress)
            choice = input("Select a level to run (or q to quit): ").strip()
            if choice.lower() == "q":
                break
            try:
                level_value = type(levels[0])(choice)
                if level_value not in levels:
                    raise ValueError
            except ValueError:
                print("Invalid level, try again.")
                continue

            cid = f"{mode}_{level_value}"
            rep = progress.get(cid, 0) + 1

            input("Place a fresh weighing paper on the build platform. Press Enter when ready...")
            cal_common.home_and_wait(grbl)

            mass_before = float(input("Mass before print (g): ").strip())

            density, passes, print_speed = _params_for_level(mode, level_value)
            cal_common.print_solid_square(
                grbl, inkjet,
                BUILD_CENTER_X_MM, BUILD_CENTER_Y_MM, SQUARE_SIZE_MM,
                DPI, density, passes, print_speed, TRAVEL_SPEED,
            )

            mass_after = float(input("Mass after print (g): ").strip())
            delta_g = mass_after - mass_before

            cal_common.log_row(csv_path, FIELDNAMES, {
                "mode": mode,
                "condition_id": cid,
                "level_name": mode,
                "level_value": level_value,
                "rep": rep,
                "mass_before_g": mass_before,
                "mass_after_g": mass_after,
                "delta_g": delta_g,
                "area_mm2": SQUARE_SIZE_MM * SQUARE_SIZE_MM,
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            })
            print(f"Logged {cid} rep {rep}: delta_g={delta_g:.4f}")
    finally:
        grbl.Disconnect()
        inkjet.Disconnect()


def main():
    parser = argparse.ArgumentParser(description="Binder delivery calibration")
    parser.add_argument("--mode", required=True, choices=list(CONDITIONS.keys()))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--verify-position", action="store_true")
    args = parser.parse_args()

    if args.dry_run:
        cmd_dry_run(args.mode)
    elif args.verify_position:
        cmd_verify_position()
    else:
        cmd_real_run(args.mode)


if __name__ == "__main__":
    main()
