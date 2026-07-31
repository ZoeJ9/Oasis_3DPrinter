# Calibration scripts

Standalone hardware calibration tools for the binder-jet printer. These do
**not** import `main.py` or `src/config_runner.py` and have no GUI — they
connect directly to GRBL/HP45 over serial using the same protocol as the
main printer software (`src/SerialGRBL.py`, `src/SerialHP45.py`, `src/B64.py`).

## Scripts

- **`cal_binder_delivery.py`** — measures how much binder mass lands per
  unit area as a function of HP45 `density`, `layer_passes`, and print
  `speed`. Prints a solid 50mm square onto weighing paper and weighs it
  before/after. Output: `results/binder_delivery_{mode}.csv`.
- **`cal_packing.py`** — measures spread quality across a full 2³ factorial
  of `overfeed`, `spread_speed` (gantry traverse), and `roller_voltage`
  (bench-PSU setting, recorded manually — there is no GRBL command for
  roller speed in this codebase). Spreads powder (no binder) and captures a
  photo per condition. Output: `results/packing_conditions.csv` +
  `results/spread_of..._ss..._rv..._{rep}.png`.

## Setup

Edit the top of each script before first use:

- `GRBL_PORT`, `HP45_PORT` (binder script only) — COM port strings.
- `CAMERA_PORT` — OpenCV camera index (packing script only).

## Recommended sequence before a real binder run

1. `python cal_binder_delivery.py --dry-run --mode <density|passes|speed>` —
   prints center, square corners, and bed-fit warnings, no hardware touched.
2. `python cal_binder_delivery.py --verify-position --mode <mode>` — connects
   GRBL only, homes, and jogs to each of the four square corners for a
   visual check. No binder/SBR commands are sent.
3. `python cal_binder_delivery.py --mode <mode>` — the real run.

Binder delivery uses **weighing paper** on the build platform (place a fresh
sheet before each print, weigh before and after). Packing uses **fresh
powder with no binder** — nothing is weighed, a photo is taken per
condition instead.

## Resuming after interruption

Both scripts read their CSV at startup and show completed/target rep counts
per condition in a menu. Ctrl+C between measurements loses nothing already
logged — re-running does not repeat completed target reps (extra reps can
always be added manually by selecting the same condition again). Bad
measurements are never auto-deleted or overwritten; log a corrected
measurement as a new rep instead.

## Homing

Both scripts home once at the start of a real session (before the first
menu draw), and again immediately before every print/spread. `--dry-run`
never connects to hardware or homes. `--verify-position` homes once at
start, before visiting the corners.

> Build center (157.0, 116.0) is a working estimate, not a verified physical
> center — coordinates are repeatable session-to-session via homing, but not
> confirmed to be bed-centered. This is acceptable for relative comparisons
> across calibration conditions; it would need separate verification if
> absolute bed-centering becomes important later.

## Out of scope here

- Verifying the physical build-center against the bed (camera-based
  correction, bed-edge detection, `calibration.npz` integration) — a
  separate, later task.
- Automated analysis of `cal_packing.py`'s output images — downstream work.
- Any GRBL roller command, RPM recording, estimation, or measurement.
