"""Standalone packing calibration: how spread quality responds to overfeed,
spread_speed (gantry traverse), and roller_voltage (bench-PSU-set, manually
recorded — no GRBL roller command exists in this codebase).

Full 2**3 factorial design. spread_speed is a gantry-traverse behavior and
roller_voltage is a roller-rotation behavior — two plausibly distinct packing
mechanisms whose independence/interaction is unconfirmed, so this does not
reduce to a 2**2 design by dropping either factor. RPM is not measured now;
it could be added later via tachometer or optical strobe.

Usage:
    python cal_packing.py --dry-run
    python cal_packing.py --verify-position
    python cal_packing.py
"""

import argparse
import itertools
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cal_common

# --- edit these for your setup ---
GRBL_PORT = "COM5"
CAMERA_PORT = 0
LED_PORT = "COM11"  # Arduino LED controller; set to None to capture unlit
# ----------------------------------

BUILD_CENTER_X_MM = 157.0
BUILD_CENTER_Y_MM = 116.0
TRAVEL_SPEED = 3000.0
LAYER_THICKNESS_MM = 0.1
SQUARE_SIZE_MM = 45.0  # used only for bed-fit / verify-position corner check

OVERFEED_LEVELS = {"lo": 2.0, "hi": 5.0}
SPREAD_SPEED_LEVELS = {"lo": 3000, "hi": 9000}
ROLLER_VOLTAGE_LEVELS = {"lo": 3.0, "hi": 7.5}

CENTER = {
    "overfeed": 3.5,
    "spread_speed": 6000,
    "roller_voltage": 5.0,
}
N_CENTER_REPS = 3
CORNER_TARGET_REPS = 3
ROLLER_OFF_TARGET_REPS = 3
OVERFEED_1_TARGET_REPS = 3

RESULTS_DIR = cal_common.RESULTS_DIR
CSV_PATH = os.path.join(RESULTS_DIR, "packing_conditions.csv")

FIELDNAMES = [
    "condition_id", "overfeed", "spread_speed", "roller_voltage_v", "rep",
    "filename_led1", "filename_led2", "filename_led3", "filename_led4", "filename_led5",
    "timestamp",
]


def _build_conditions():
    """Return {condition_id: {"overfeed":.., "spread_speed":.., "roller_voltage":.., "target_reps":..}}
    for the 8 corner conditions (2**3 factorial corners) plus the 1 center condition."""
    conditions = {}
    for of_key, ss_key, rv_key in itertools.product(("lo", "hi"), repeat=3):
        cid = f"of{of_key}_ss{ss_key}_rv{rv_key}"
        conditions[cid] = {
            "overfeed": OVERFEED_LEVELS[of_key],
            "spread_speed": SPREAD_SPEED_LEVELS[ss_key],
            "roller_voltage": ROLLER_VOLTAGE_LEVELS[rv_key],
            "target_reps": CORNER_TARGET_REPS,
        }
    conditions["center"] = {
        "overfeed": CENTER["overfeed"],
        "spread_speed": CENTER["spread_speed"],
        "roller_voltage": CENTER["roller_voltage"],
        "target_reps": N_CENTER_REPS,
    }
    # Comparison condition: same overfeed/spread_speed as center, but roller
    # off entirely (0V) — isolates whether the roller is doing anything at all.
    conditions["roller_off"] = {
        "overfeed": CENTER["overfeed"],
        "spread_speed": CENTER["spread_speed"],
        "roller_voltage": 0.0,
        "target_reps": ROLLER_OFF_TARGET_REPS,
    }
    # Comparison condition: overfeed=1.0 (no net powder surplus), everything
    # else at center — isolates how little overfeed the spread still needs.
    conditions["overfeed_1"] = {
        "overfeed": 1.0,
        "spread_speed": CENTER["spread_speed"],
        "roller_voltage": CENTER["roller_voltage"],
        "target_reps": OVERFEED_1_TARGET_REPS,
    }
    return conditions


CONDITIONS = _build_conditions()


def cmd_dry_run():
    corners = cal_common.compute_square_corners(BUILD_CENTER_X_MM, BUILD_CENTER_Y_MM, SQUARE_SIZE_MM)
    warnings = cal_common.check_bed_fit(corners)
    print("Packing calibration - 2**3 factorial + center")
    print(f"Center: ({BUILD_CENTER_X_MM}, {BUILD_CENTER_Y_MM})")
    print("Conditions:")
    for cid, params in CONDITIONS.items():
        print(f"  {cid}: overfeed={params['overfeed']}, spread_speed={params['spread_speed']}, "
              f"roller_voltage={params['roller_voltage']}V, target_reps={params['target_reps']}")
    if warnings:
        print("Bed-fit warnings (reference square, informational only):")
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


def _show_menu(progress: dict):
    print("\n=== Packing Calibration ===")
    for cid, params in CONDITIONS.items():
        done = progress.get(cid, 0)
        print(f"  [{cid}] {done}/{params['target_reps']} reps "
              f"(overfeed={params['overfeed']}, spread_speed={params['spread_speed']}, "
              f"roller_voltage={params['roller_voltage']}V)")
    print("  [q] quit")


def cmd_real_run():
    grbl = cal_common.GRBL()
    if grbl.Connect(GRBL_PORT) != 1:
        raise RuntimeError(f"Failed to connect to GRBL on {GRBL_PORT}")

    led_conn = None
    if LED_PORT:
        try:
            led_conn = cal_common.connect_led_controller(LED_PORT)
            print(f"LED controller connected on {LED_PORT}")
        except Exception as exc:
            print(f"LED controller connect failed ({exc}) — captures will be unlit")

    try:
        cal_common.home_and_wait(grbl)

        while True:
            progress = cal_common.load_progress(CSV_PATH)
            _show_menu(progress)
            cid = input("Select a condition to run (or q to quit): ").strip()
            if cid.lower() == "q":
                break
            if cid not in CONDITIONS:
                print("Unknown condition, try again.")
                continue

            params = CONDITIONS[cid]
            rep = progress.get(cid, 0) + 1

            if params["roller_voltage"] == 0.0:
                input("Turn the roller supply OFF entirely (0V). Press Enter to confirm...")
            else:
                input(
                    f"Set roller supply to {params['roller_voltage']}V "
                    "(read from bench PSU display). Press Enter to confirm voltage is set..."
                )

            cal_common.home_and_wait(grbl)
            cal_common.spread_one_layer(
                grbl, LAYER_THICKNESS_MM, params["overfeed"], params["spread_speed"],
            )

            import cv2
            led_frames = cal_common.capture_led_sequence(CAMERA_PORT, led_conn)
            filenames_by_led = {}
            for led_n, frame in led_frames:
                tag = f"led{led_n}" if led_n > 0 else "noLED"
                filename = (
                    f"spread_of{params['overfeed']}_ss{params['spread_speed']}"
                    f"_rv{params['roller_voltage']}_{rep}_{tag}.png"
                )
                cv2.imwrite(os.path.join(RESULTS_DIR, filename), frame)
                filenames_by_led[led_n] = filename
            print(f"Captured {len(led_frames)} LED frame(s)")

            cal_common.log_row(CSV_PATH, FIELDNAMES, {
                "condition_id": cid,
                "overfeed": params["overfeed"],
                "spread_speed": params["spread_speed"],
                "roller_voltage_v": params["roller_voltage"],
                "rep": rep,
                "filename_led1": filenames_by_led.get(1, ""),
                "filename_led2": filenames_by_led.get(2, ""),
                "filename_led3": filenames_by_led.get(3, ""),
                "filename_led4": filenames_by_led.get(4, ""),
                "filename_led5": filenames_by_led.get(5, ""),
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            })
            print(f"Logged {cid} rep {rep}")
    finally:
        grbl.Disconnect()
        if led_conn is not None and led_conn.is_open:
            led_conn.close()


def main():
    parser = argparse.ArgumentParser(description="Packing calibration")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--verify-position", action="store_true")
    args = parser.parse_args()

    if args.dry_run:
        cmd_dry_run()
    elif args.verify_position:
        cmd_verify_position()
    else:
        cmd_real_run()


if __name__ == "__main__":
    main()
