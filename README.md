# Oasis_3DPrinter

This repository is a control stack for the Oasis 3D printer / powder-bed inkjet proof-of-concept printer.

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

## Dependencies

- Python 3.6+ (recommended 3.9+)
- PyQt5 == 5.15.4
- numpy == 1.19.5
- opencv-python == 4.5.5.64
- pyserial == 3.5

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
