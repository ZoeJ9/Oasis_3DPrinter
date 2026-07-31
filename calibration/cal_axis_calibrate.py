"""Standalone GRBL axis steps/mm calibration by ruler measurement.

Jogs a chosen axis a commanded distance, asks the operator to measure the
actual physical movement with a ruler/caliper, and computes the steps/mm
value that would make commanded and measured distance agree — so a
NewLayer() thickness/overfeed calculation that looks correct in code can be
checked against what the hardware actually does.

Does not read or write GRBL's $$ settings automatically (SerialGRBL.py has
no $$ response parser — see src/SerialGRBL.py's Update() loop, which only
handles ok/error/alarm/[...]/</status responses, not raw $-prefixed replies).
Reports the corrected steps/mm value for the operator to set manually via
a terminal (e.g. $102=<value> for the A axis) or GRBL config.

Usage:
    python cal_axis_calibrate.py --axis A --distance 10
    python cal_axis_calibrate.py --axis Z --distance 10
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cal_common

# --- edit for your setup ---
GRBL_PORT = "COM5"
JOG_FEED = 150.0
# ----------------------------

# GRBL setting number for each axis's steps/mm ($100=X, $101=Y, $102=Z, $103=A)
STEPS_PER_MM_SETTING = {"X": "$100", "Y": "$101", "Z": "$102", "A": "$103"}


def main():
    parser = argparse.ArgumentParser(description="Axis steps/mm calibration by ruler measurement")
    parser.add_argument("--axis", required=True, choices=["X", "Y", "Z", "A"])
    parser.add_argument("--distance", type=float, required=True,
                         help="Commanded relative jog distance in mm (e.g. 10)")
    parser.add_argument("--current-steps-per-mm", type=float, default=None,
                         help="Current GRBL steps/mm for this axis, if known "
                              "(needed to compute the corrected value). "
                              "If omitted, only the measured/commanded ratio is reported.")
    args = parser.parse_args()

    grbl = cal_common.GRBL()
    if grbl.Connect(GRBL_PORT) != 1:
        raise RuntimeError(f"Failed to connect to GRBL on {GRBL_PORT}")

    try:
        cal_common.home_and_wait(grbl)

        print(f"Homed. About to jog axis {args.axis} by {args.distance}mm "
              f"(commanded, relative move) at F{JOG_FEED}.")
        input("Position a ruler/caliper against the moving part now. Press Enter to jog...")

        grbl.Jog(args.axis, args.distance, JOG_FEED)
        cal_common.wait_motion_idle(grbl)

        print("Jog complete.")
        measured = float(input(
            f"Measured actual movement of axis {args.axis} in mm "
            f"(commanded was {args.distance}mm): "
        ).strip())

        ratio = measured / args.distance
        print(f"\nCommanded: {args.distance}mm")
        print(f"Measured:  {measured}mm")
        print(f"Ratio (measured/commanded): {ratio:.4f}")

        setting = STEPS_PER_MM_SETTING[args.axis]
        if args.current_steps_per_mm is not None:
            corrected = args.current_steps_per_mm * ratio
            print(f"\nCurrent {setting} (steps/mm): {args.current_steps_per_mm}")
            print(f"Corrected {setting} (steps/mm): {corrected:.4f}")
            print(f"\nTo apply: connect a terminal (e.g. main.py's motion console or any "
                  f"serial terminal) and send:  {setting}={corrected:.4f}")
        else:
            print(f"\nNo --current-steps-per-mm given — can't compute the corrected {setting} value.")
            print(f"Query it first: connect a serial terminal to {GRBL_PORT} and send $$ "
                  f"to see the current {setting}, then re-run this script with "
                  f"--current-steps-per-mm <that value>.")
            print(f"(This can't be automated here — SerialGRBL.py's Update() loop doesn't "
                  f"parse raw $-prefixed responses, only ok/error/alarm/status lines.)")
    finally:
        grbl.Disconnect()


if __name__ == "__main__":
    main()
