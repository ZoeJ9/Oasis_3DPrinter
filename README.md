# Oasis_3DPrinter

This repository is a control stack for the Oasis 3D printer / powder-bed inkjet printer.

The main GUI and print engine is in `Oasis_printer_260327.py` and supports:

- GRBL motion control (X/Y gantry + build/powder axes) through `SerialGRBL.py`
- HP45 inkjet printhead management through `SerialHP45.py`
- Image file conversion and rasterisation through `ImageConverter.py`
- Densities and DPI conversion for print output
- Layer-by-layer print with sweep-based line injection
- Optional `OpenCV` camera capture before/after each layer via `CameraController` in `Oasis_printer_260327.py`
- Pause/abort and status visualization

Other useful components:

- `Study_params_loader_and_print.py`: Parameter injection workflow from CSV (`oasis_change_parameters.csv`)
  - Reads `name`, `kind`, `value`, `lower`, `upper`, `code_var`, etc.
  - Builds resolved config and writes manifest + resolved params
  - Optionally launches GUI with locked or overridden parameters
- `B64.py`: Burst encoding/decoding support for sending print buffer lines to HP45

---

## Changelog

### v2.4 (2026-05-26)

**Mid-print cleaning: checkbox enable + UI snapshot**

- Added "Clean mid-print" checkbox (default unchecked) and interval spinbox (1–50 layers)
  to the Motion Control group in the main form — spinbox disabled when checkbox is off
- `_PrintSVG_inner` snapshots both UI values into instance variables at print start,
  so toggling the checkbox mid-print does not affect the current run
- `_MaybeCleanMidPrint` now checks `mid_print_clean_enabled` flag first
- `mid_print_clean_enabled = False` default — cleaning is opt-in

---

### v2.3 (2026-05-26)

**Mid-print printhead cleaning**

- Every N layers (default 5, configurable via status bar spinbox; 0 = disabled), the print
  loop homes the gantry then runs a short clean: preheat ×3 + prime ×3, 1s between bursts
- Gantry is moved to home before cleaning to prevent priming over the powder bed
- `_HeadCleanWorker` now accepts an optional `sequence` parameter (default = full
  5+5+5+5 manual sequence = 20 bursts; backward-compatible with existing `InkjetHeadClean`)
- New `_MaybeCleanMidPrint()` method encapsulates the modulo check, homing, and clean call
- SVG print path only (`_PrintSVG_inner`); `PrintArray` unchanged

---

### v2.2 (2026-05-26)

**Fix: `printing_sweep_size` tracks inkjet DPI during config run**

`ConfigRunner._apply_step()` now updates `mw.printing_sweep_size = inkjet_dpi // 2`
whenever `inkjet.SetDPI()` is called. Previously, changing inkjet DPI mid-print left
`printing_sweep_size` at the original value, causing output size and sweep positions to
shift. `pixel_to_pos_multiplier` and `imageconverter` remain untouched.

---

### v2.1 (2026-05-24)

**CSV-driven parameter sweep (DOE) integration** — `Oasis_printer_v2.1.py`:

- `config_runner.py`: `ConfigRunner` class loads `print_config.csv` and drives
  layer-by-layer printing with per-step parameter overrides
- Per-step parameters: `print_speed`, `travel_speed`, `layer_thickness`, `dpi`,
  `density`, `preheat`, `prime`, `layer_passes`, `overfeed`
- Step-aware image filenames: `s001_L003_pre_baseline.png` / `_post_`
- Per-capture CSV log: `config_log.csv` alongside the config file
- Post-capture timing: photo taken before `NewLayer()` so powder doesn't cover print
- `_init_print_state()` shared by both normal and config print paths
- `QFileDialog` parent fixed to `self.ui` (prevents window resize on CSV upload)
- All Korean strings replaced with English
- Smoke test: `test_config_runner_smoke.py`

---

### v1.3.1 (2026-05-22)

**Camera capture quality overhaul** — validated settings for 175 mm bed setup:

| Constant | Value | Note |
|---|---|---|
| `RESOLUTION_FULL` | 8000×6000 | 48 MP, MJPEG, ~1.3 fps |
| `RESOLUTION_PREVIEW` | 1920×1080 | focusing / preview |
| `AUTO_EXPOSURE_MANUAL` | 0.25 | DSHOW manual lock |
| `EXPOSURE_VALUE` | −3 | 1/8 s (log₂) |
| `GAIN_VALUE` | 0 | minimum |
| `AUTO_WB` | 0 | white-balance locked |
| `WARMUP_FRAMES` | 5 | discarded before capture |
| `AVERAGING_FRAMES` | 10 | temporal noise reduction |
| `UNSHARP_SIGMA` | 2.5 | unsharp mask radius |
| `UNSHARP_AMOUNT` | 1.2 | sharpening strength (0 = off) |

`capture_sync()` flow: MJPEG + full-res → exposure/gain lock → FPS=1 → discard warmup → average N frames → unsharp mask → save PNG.

---

### v1.2.2 (2026-05-22)

Spread one powder layer + capture photo before the main print loop starts (`Layer_000_Spread`).

---

### v1.1.4 (2026-05-18)

**Camera calibration** added to `CameraController` settings panel:
- `calib_status_label` — green/red dot showing whether `calibration.npz` exists in the output dir
- `btn_run_calibration` — triggers the full calibration flow: generate SVG target → capture image → detect circle via Hough → save `calibration.npz`
- Calibration status auto-refreshes when a camera is selected from the combo box
- No changes to the existing print logic

**New package: `dice_evaluator/`** — standalone layer quality evaluation tool (not yet tested):

| File | Purpose |
|------|---------|
| `constants.py` | Shared constants (bed size, build centre, GRBL home, calibration filename) |
| `calibrate.py` | SVG generation, Hough circle detection, px↔mm mapping, save/load calibration |
| `evaluator.py` | `DiceEvaluator` — remaps `image_array` to camera space, computes Dice coefficient per layer, saves overlay PNGs and CSV |
| `main.py` | Standalone PyQt5 GUI (`python -m dice_evaluator.main`) |

**Dependencies added:**
- `pandas==0.25.3` (Python 3.6 compatible) — added to `requirements.txt` and installed in venv

---

## Dependencies

- Python 3.6+ (recommended 3.9+)
- PyQt5 == 5.15.4
- numpy == 1.19.5
- opencv-python == 4.5.5.64
- pyserial == 3.5
- pandas == 0.25.3

Install dependencies:

```bash
pip install -r requirements.txt
```

---

## Quick Start

1. Connect hardware:
   - GRBL controller (e.g., `/dev/ttyUSB0` or `COM3`)
   - HP45 inkjet (serial)
   - USB camera (optional)

2. Configure printing parameters via `oasis_change_parameters.csv`.

3. Launch from parameter loader (recommended):

```bash
python Study_params_loader_and_print.py
```

4. The GUI will open. Steps in GUI:
   - `Connect` GRBL (`motion_connect`)
   - `Connect` HP45 inkjet (`inkjet_connect`)
   - `Open File` (PNG/JPG/SVG)
   - Optionally adjust `threshold`, `layer`, `density`, `dpi`, `overfeed`, `layer thickness`
   - Click `Print`

5. During print:
   - The system writes coordinated G-code sweep moves via GRBL
   - It writes `SBR` commands to HP45 for each line in a sweep
   - It can take camera snapshots at key states (`Spread`, `Printed`)
   - Use `Pause` / `Abort` as needed

---

## Camera integration

`CameraController` in `Oasis_printer_260327.py` uses OpenCV:

- detects up to 8 cameras on startup
- `capture_sync()` waits for settle time and grabs one frame
- saves PNG to `timelapse_output` (default) or configured folder
- updates live QLabel preview in GUI

---

## Parameter injection workflow

`Study_params_loader_and_print.py`:

- reads `oasis_change_parameters.csv` and validates bounds
- resolves fixed & variance parameters
- writes `runs/<RUN_ID>/manifest.json` and `runs/<RUN_ID>/resolved_params.csv`
- starts GUI with `ConfigurableMainWindow` (locks variance parameters to prevent overwrite in `PrintSVG`)

Attributes mapped from CSV:

- `print_speed`, `travel_speed`, `acceleration_distance`, `dpi`, `layer_passes`
- `preheat_pulses`, `prime_pulses`
- camera configuration: `dwell_time`,`webcam_index`,`capture_output_dir`
- slider proxies: `layer_thickness`, `overfeed_percent`, `density`

---

## Notes

- `Oasis_printer_260327.py` implements two print kernels:
  - `PrintArray`: raster from currently converted bitmap
  - `PrintSVG`: SVG layer loop with full layer-recoater integration
- `PrintSVG` uses hard-coded defaults but can be overridden by `Study_params_loader_and_print.py` adapter
- Expect non-blocking serial performance limits; heavy sleeps inserted to work around Python GIL and serial throughput delays

---

## Troubleshooting

- If no camera detected, verify OpenCV installation and device permissions
- If serial ports are missing, restart the process after connecting hardware and run `Refresh` in GUI
- If print hangs, ensure `grbl.motion_state` reads `idle` before `SBR` bursts

---

## License

GPL v3 (as in original `Oasis` controller code).  
