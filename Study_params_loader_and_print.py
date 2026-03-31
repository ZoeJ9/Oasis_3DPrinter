"""
params_loader_and_print.py
==========================
Reads the Oasis parameter CSV, builds a resolved config dict, writes a run
manifest + resolved-params CSV, and launches the Oasis GUI.

Usage
-----
Edit the USER SETTINGS section below, then run:
    python Study_params_loader_and_print.py

Python 3.6+ | stdlib + (optional) csv module only
"""

# ===========================================================================
# USER SETTINGS — edit these values before running
# ===========================================================================

# Path to the Oasis parameter CSV file
CSV_PATH = "oasis_change_parameters.csv"

# Unique identifier for this run (used for output folder naming)
RUN_ID = "run_001"

# Optional parameter overrides: set key=value pairs to override CSV values.
# Example: OVERRIDES = {"print_speed": 3500, "dpi": 600}
# Leave empty to use values from the CSV as-is.
OVERRIDES = {}

# Set to True to only log the resolved config without launching the GUI
DRY_RUN = False

# ===========================================================================

import csv
import json
import logging
import os
import subprocess
import sys
import time
from collections import OrderedDict
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Column-name mapping — edit here if the CSV schema ever changes
# ---------------------------------------------------------------------------
COLUMN_MAP: Dict[str, str] = {
    "name": "parameter_name",
    "kind": "Type of variable",   # fixed | variance  (case-insensitive)
    "value": "value",
    "unit": "unit",
    "lower": "min",
    "upper": "max",
    "category": "category",
    "description": "description",
    "code_var": "code_variable",
}

# Tokens that mean "no bound defined" in the CSV
_UNSET_TOKENS = {"-", "not sure", "auto", "", "n/a", "none"}

# Kind tokens recognised as "variance" (case-insensitive)
_VARIANCE_KINDS = {"variance"}

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger("oasis.loader")


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------
class OasisParam:
    """Represents one row of the parameter CSV."""

    __slots__ = (
        "name", "kind", "raw_value", "value",
        "unit", "lower", "upper",
        "category", "description", "code_var",
        "is_variance", "has_bounds",
    )

    def __init__(
        self,
        name: str,
        kind: str,
        raw_value: str,
        unit: str,
        lower: Optional[float],
        upper: Optional[float],
        category: str,
        description: str,
        code_var: str,
    ) -> None:
        self.name = name
        self.kind = kind.strip().lower()
        self.raw_value = raw_value.strip()
        self.unit = unit
        self.lower = lower
        self.upper = upper
        self.category = category
        self.description = description
        self.code_var = code_var
        self.is_variance = self.kind in _VARIANCE_KINDS
        self.has_bounds = lower is not None and upper is not None

        # Attempt numeric parse; keep as string for non-numeric (e.g. "auto")
        self.value: Any = _try_numeric(self.raw_value)

    def __repr__(self) -> str:
        return (
            f"OasisParam(name={self.name!r}, kind={self.kind!r}, "
            f"value={self.value!r}, lower={self.lower}, upper={self.upper})"
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _try_numeric(s: str) -> Any:
    """Return int, float, or original string — in that priority order."""
    try:
        as_int = int(s)
        return as_int
    except (ValueError, TypeError):
        pass
    try:
        return float(s)
    except (ValueError, TypeError):
        return s


def _parse_bound(raw: str, param_name: str, bound_label: str) -> Optional[float]:
    """
    Parse a bound cell.  Returns None when the cell contains an unset token.
    Raises ValueError on an invalid (non-numeric, non-unset) value.
    """
    cleaned = raw.strip().lower()
    if cleaned in _UNSET_TOKENS:
        return None
    try:
        return float(raw.strip())
    except ValueError:
        raise ValueError(
            f"Parameter '{param_name}': {bound_label} bound is '{raw}', "
            f"which is neither numeric nor a recognised unset token "
            f"({', '.join(sorted(_UNSET_TOKENS))})."
        )


def _get_col(row: Dict[str, str], logical: str) -> str:
    """Retrieve a CSV column by its logical name via COLUMN_MAP."""
    physical = COLUMN_MAP[logical]
    if physical not in row:
        raise KeyError(
            f"Expected column '{physical}' (logical: '{logical}') "
            f"not found in CSV. Available columns: {list(row.keys())}"
        )
    return row[physical]


def _git_hash() -> str:
    """Return the short HEAD git hash, or 'unknown' if git is unavailable."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=3,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return "unknown"


# ---------------------------------------------------------------------------
# CSV loading & validation
# ---------------------------------------------------------------------------
def load_csv(csv_path: str) -> List[OasisParam]:
    """
    Parse the Oasis parameter CSV into a list of OasisParam objects.

    Raises
    ------
    FileNotFoundError  — path does not exist.
    KeyError           — a required column is absent.
    ValueError         — a bound is malformed or lower > upper.
    """
    if not os.path.isfile(csv_path):
        raise FileNotFoundError(f"CSV not found: {csv_path!r}")

    params: List[OasisParam] = []

    with open(csv_path, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        for line_no, row in enumerate(reader, start=2):  # 1-indexed; row 1 = header
            try:
                name = _get_col(row, "name").strip()
                if not name:
                    log.warning("Line %d: empty parameter_name — skipping.", line_no)
                    continue

                lower = _parse_bound(_get_col(row, "lower"), name, "lower")
                upper = _parse_bound(_get_col(row, "upper"), name, "upper")

                p = OasisParam(
                    name=name,
                    kind=_get_col(row, "kind"),
                    raw_value=_get_col(row, "value"),
                    unit=_get_col(row, "unit"),
                    lower=lower,
                    upper=upper,
                    category=_get_col(row, "category"),
                    description=_get_col(row, "description"),
                    code_var=_get_col(row, "code_var"),
                )
                params.append(p)

            except (KeyError, ValueError) as exc:
                raise type(exc)(f"Line {line_no}: {exc}") from exc

    log.info("Loaded %d parameters from '%s'.", len(params), csv_path)
    return params


def validate_params(params: List[OasisParam]) -> None:
    """
    Fail fast on invalid parameter configurations.

    Checks
    ------
    * Variance parameters with defined bounds must have lower <= upper.
    * Variance parameters with bounds must have a numeric current value.
    * Current value must be within [lower, upper] when bounds exist.

    Raises
    ------
    ValueError on the first violation found.
    """
    errors: List[str] = []

    for p in params:
        if not p.has_bounds:
            if p.is_variance:
                log.warning(
                    "Variance parameter '%s' has no usable bounds — "
                    "it will be treated as fixed during sweeps.",
                    p.name,
                )
            continue

        assert p.lower is not None and p.upper is not None  # type narrowing

        if p.lower > p.upper:
            errors.append(
                f"'{p.name}': lower ({p.lower}) > upper ({p.upper})."
            )
            continue

        if p.is_variance and not isinstance(p.value, (int, float)):
            errors.append(
                f"'{p.name}': variance parameter has non-numeric value "
                f"'{p.raw_value}' — cannot sweep."
            )
            continue

        if isinstance(p.value, (int, float)):
            if p.value < p.lower or p.value > p.upper:
                log.warning(
                    "Parameter '%s' current value %s is outside bounds [%s, %s].",
                    p.name, p.value, p.lower, p.upper,
                )

    if errors:
        msg = "Parameter validation failed:\n  " + "\n  ".join(errors)
        raise ValueError(msg)

    log.info("Parameter validation passed.")


# ---------------------------------------------------------------------------
# Config builder
# ---------------------------------------------------------------------------
def build_config(
    params: List[OasisParam],
    overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Produce a flat resolved-config dict: {param_name: value}.

    Override values (from CLI --overrides) are applied last and validated
    against any defined bounds.

    Parameters
    ----------
    params:    Parsed parameter list.
    overrides: Optional dict of name→value pairs from the command line.

    Returns
    -------
    Ordered dict (param_name → resolved value).
    """
    overrides = overrides or {}
    config: Dict[str, Any] = OrderedDict()

    for p in params:
        config[p.name] = p.value

    for key, raw_val in overrides.items():
        if key not in config:
            raise KeyError(
                f"Override key '{key}' does not match any parameter name. "
                f"Known names: {sorted(config.keys())}"
            )
        val = _try_numeric(str(raw_val))

        # Validate override against bounds if available
        param_by_name = {p.name: p for p in params}
        p = param_by_name[key]
        if p.has_bounds and isinstance(val, (int, float)):
            assert p.lower is not None and p.upper is not None
            if val < p.lower or val > p.upper:
                raise ValueError(
                    f"Override '{key}={val}' is outside bounds "
                    f"[{p.lower}, {p.upper}]."
                )

        log.info("Override: %s = %r (was %r)", key, val, config[key])
        config[key] = val

    return config


# ---------------------------------------------------------------------------
# Run-folder helpers
# ---------------------------------------------------------------------------
def _ensure_run_dir(run_id: str) -> str:
    """Create ./runs/<run_id>/ and return its absolute path."""
    run_dir = os.path.abspath(os.path.join("runs", run_id))
    os.makedirs(run_dir, exist_ok=True)
    return run_dir


def write_manifest(
    run_dir: str,
    config: Dict[str, Any],
    csv_path: str,
    run_id: str,
    extra: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Write a JSON run manifest to <run_dir>/manifest.json.

    Manifest contains
    -----------------
    * run_id, timestamp (ISO-8601), git_hash
    * source CSV path
    * full resolved config
    * any extra metadata passed in

    Returns the manifest file path.
    """
    manifest = {
        "run_id": run_id,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "git_hash": _git_hash(),
        "source_csv": os.path.abspath(csv_path),
        "resolved_config": config,
    }
    if extra:
        manifest.update(extra)

    path = os.path.join(run_dir, "manifest.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2)

    log.info("Manifest written → %s", path)
    return path


def write_resolved_params(
    run_dir: str,
    params: List[OasisParam],
    config: Dict[str, Any],
) -> str:
    """
    Write the exact resolved parameter set to <run_dir>/resolved_params.csv.

    Columns match the original CSV schema plus a 'resolved_value' column.
    Returns the output file path.
    """
    path = os.path.join(run_dir, "resolved_params.csv")
    fieldnames = [
        COLUMN_MAP["name"],
        COLUMN_MAP["kind"],
        "resolved_value",
        COLUMN_MAP["value"],
        COLUMN_MAP["unit"],
        COLUMN_MAP["lower"],
        COLUMN_MAP["upper"],
        COLUMN_MAP["category"],
        COLUMN_MAP["description"],
        COLUMN_MAP["code_var"],
    ]

    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for p in params:
            writer.writerow(
                {
                    COLUMN_MAP["name"]: p.name,
                    COLUMN_MAP["kind"]: p.kind,
                    "resolved_value": config.get(p.name, p.value),
                    COLUMN_MAP["value"]: p.raw_value,
                    COLUMN_MAP["unit"]: p.unit,
                    COLUMN_MAP["lower"]: "" if p.lower is None else p.lower,
                    COLUMN_MAP["upper"]: "" if p.upper is None else p.upper,
                    COLUMN_MAP["category"]: p.category,
                    COLUMN_MAP["description"]: p.description,
                    COLUMN_MAP["code_var"]: p.code_var,
                }
            )

    log.info("Resolved params written → %s", path)
    return path


# ---------------------------------------------------------------------------
# ╔══════════════════════════════════════════════════════════════════════════╗
# ║                         ADAPTER SECTION                                  ║
# ║                                                                          ║
# ║  Everything below this banner bridges the runner to oasis_layer_repeat_and_camera.py.  ║
# ║  Changes are ISOLATED HERE — do not touch PrintSVG / PrintArray.         ║
# ╚══════════════════════════════════════════════════════════════════════════╝
#
# HOW IT WORKS
# ------------
# oasis_layer_repeat_and_camera_ruff_formatted.PrintSVG() hard-codes parameter values at the top of the
# method (e.g. self.print_speed = 2200).  To override them without touching
# the original source we use a *subclass with a locking __setattr__*.
#
# Usage pattern
# -------------
#   app = QApplication(sys.argv)
#   gui = ConfigurableMainWindow()        # drop-in replacement for MainWindow
#   gui.lock_params(config)               # ← call BEFORE RunPrintArray
#   gui.OpenFile("/path/to/file.svg")
#   gui.GrblConnect()
#   gui.InkjetConnect()
#   gui.RunPrintArray()
#
# ADAPTER_HOOKS — these are the oasis_layer_repeat_and_camera_ruff_formatted lines that can be replaced
# with getattr() calls to make injection cleaner in the future:
#
#   PrintSVG line ~185:  self.print_speed       = 2200   → getattr(self, 'print_speed', 2200)
#   PrintSVG line ~186:  self.travel_speed      = 3000.0 → getattr(self, 'travel_speed', 3000.0)
#   PrintSVG line ~187:  self.acceleration_dist = 20.0   → getattr(self, 'acceleration_distance', 20.0)
#   PrintSVG line ~188:  self.build_center_x    = 157    → getattr(self, 'build_center_x', 157)
#   PrintSVG line ~189:  self.build_center_y    = 116    → getattr(self, 'build_center_y', 116)
#
# ---------------------------------------------------------------------------

# Map from config key → (oasis_layer_repeat_and_camera_ruff_formatted attribute name, type coercion)
# Add entries here when new injectable parameters are added to the CSV.
# NOTE: layer_thickness and density are NOT listed here — they are injected
#       via widget setValue() in apply_config_to_window() because the GUI
#       reads them directly from sliders at print time.
_INJECTABLE_ATTRS: Dict[str, Tuple[str, type]] = {
    "print_speed":           ("print_speed",           float),
    "travel_speed":          ("travel_speed",           float),
    "acceleration_distance": ("acceleration_distance",  float),
    "dpi":                   ("printing_dpi",           int),
    "layer_passes":          ("layer_passes",           int),
    # Slider-based params — injected via apply_config_to_window(), not lock_params()
    # layer_thickness: form.motion_layer_thickness slider (unit: 0.05 mm per step)
    # overfeed_percent: form.motion_overfeed slider (unit: 5% per step, offset 80)
    # density: form.inkjet_density slider (0–1000 direct in v2)
    # preheat_pulses: hardcoded in InkjetPreheat() → injected as self.preheat_pulses
    # prime_pulses:   hardcoded in InkjetPrime()   → injected as self.prime_pulses
    "preheat_pulses":        ("preheat_pulses",         int),
    "prime_pulses":          ("prime_pulses",           int),
    # Camera / capture params (injected into camera_window sub-object)
    "dwell_time":            ("_cam_pause_time",        float),
    "webcam_index":          ("_cam_port",              int),
    "capture_output_dir":    ("_cam_output_dir",        str),
}

# ---------------------------------------------------------------------------
# Scaling helpers — single source of truth for unit conversions
# ---------------------------------------------------------------------------

def _density_csv_to_slider(csv_val: float) -> int:
    """
    CSV stores density in permille (0–1000).
    GUI slider (v2) operates 0–1000 directly — no x10 scaling.
    Final output = input: slider_val = csv_val
    """
    return max(0, min(1000, int(round(csv_val))))


def _layer_thickness_mm_to_slider(mm_val: float) -> int:
    """
    CSV stores layer_thickness in mm.
    GUI slider step = 0.05 mm → slider_val = mm / 0.05
    """
    return max(1, int(round(mm_val / 0.05)))


def apply_config_to_window(window: Any, config: Dict[str, Any]) -> None:
    """
    Push resolved config values onto a MainWindow instance.

    This is the *soft* adapter path — it sets attributes before PrintSVG
    runs.  Use ConfigurableMainWindow (below) to also prevent PrintSVG from
    overwriting them with its own literals.

    Parameters
    ----------
    window: A MainWindow (or ConfigurableMainWindow) instance.
    config: Resolved parameter dict from build_config().
    """
    for cfg_key, (attr_name, coerce) in _INJECTABLE_ATTRS.items():
        if cfg_key not in config:
            continue
        try:
            val = coerce(config[cfg_key])
        except (TypeError, ValueError) as exc:
            log.warning("Could not coerce '%s' to %s: %s", cfg_key, coerce, exc)
            continue

        # Camera sub-object params
        if attr_name.startswith("_cam_") and hasattr(window, "camera_window"):
            cam_attr = attr_name[5:]  # strip "_cam_"
            setattr(window.camera_window, cam_attr, val)
            log.info("  Injected: camera_window.%s = %r", cam_attr, val)
        else:
            setattr(window, attr_name, val)
            log.info("  Injected: window.%s = %r", attr_name, val)

    # density — set GUI slider so InkjetSetDensity() reads the correct value at print time.
    if "density" in config:
        try:
            slider_val = _density_csv_to_slider(float(config["density"]))
            if hasattr(window, "form") and hasattr(window.form, "inkjet_density"):
                window.form.inkjet_density.setValue(slider_val)
                log.info("  Injected: density slider = %d  [csv=%s permille]",
                         slider_val, config["density"])
        except Exception as exc:
            log.warning("Could not set density slider: %s", exc)

    # layer_thickness — set GUI slider so GRBLAddLayer() reads the correct value at print time.
    if "layer_thickness" in config:
        try:
            slider_val = _layer_thickness_mm_to_slider(float(config["layer_thickness"]))
            if hasattr(window, "form") and hasattr(window.form, "motion_layer_thickness"):
                window.form.motion_layer_thickness.setValue(slider_val)
                log.info("  Injected: layer_thickness slider = %d  [csv=%s mm]",
                         slider_val, config["layer_thickness"])
        except Exception as exc:
            log.warning("Could not set layer_thickness slider: %s", exc)

    # overfeed_percent — set GUI slider.
    if "overfeed_percent" in config:
        try:
            slider_val = max(0, int(round((float(config["overfeed_percent"]) - 80) / 5)))
            if hasattr(window, "form") and hasattr(window.form, "motion_overfeed"):
                window.form.motion_overfeed.setValue(slider_val)
                log.info("  Injected: overfeed slider = %d  [csv=%s%%]",
                         slider_val, config["overfeed_percent"])
        except Exception as exc:
            log.warning("Could not set overfeed slider: %s", exc)

    # dpi — must also be pushed into imageconverter so svg_offset and
    # pixel_to_pos_multiplier are computed from the correct DPI at print time.
    if "dpi" in config and hasattr(window, "imageconverter"):
        try:
            dpi_val = int(config["dpi"])
            window.imageconverter.SetDPI(dpi_val)
            log.info("  Injected: imageconverter.SetDPI(%d)", dpi_val)
        except Exception as exc:
            log.warning("Could not set imageconverter DPI: %s", exc)

    log.info("Config applied to MainWindow instance.")


try:
    # Only import Qt types when oasis_layer_repeat_and_camera_ruff_formatted is on the path.
    # This lets the loader module be imported (and tested) without PyQt5.
    from Oasis_printer_260327 import MainWindow  # type: ignore[import]

    class ConfigurableMainWindow(MainWindow):  # type: ignore[misc]
        """
        Drop-in MainWindow replacement that prevents PrintSVG from overwriting
        injected parameter values.

        Call gui.lock_params(config) BEFORE triggering a print.  Any attribute
        in the locked set will silently ignore subsequent reassignment attempts
        by PrintSVG (e.g. ``self.print_speed = 2200`` becomes a no-op when
        print_speed is locked).
        """

        def __setattr__(self, name: str, value: Any) -> None:
            locked: Dict[str, Any] = self.__dict__.get("_locked_attrs", {})
            if name in locked:
                log.debug(
                    "Locked attribute '%s': ignoring reassignment to %r "
                    "(keeping injected value %r).",
                    name, value, locked[name],
                )
                return
            super().__setattr__(name, value)

        def lock_params(self, config: Dict[str, Any], params: Optional[List[Any]] = None) -> None:
            """
            Lock only 'variance' parameters so PrintSVG cannot overwrite them.
            'fixed' parameters are applied to the GUI but not locked.

            Parameters
            ----------
            config: Resolved config dict (output of build_config()).
            params: OasisParam list from load_csv(). If provided, only variance
                    parameters are locked. Fixed parameters are set but remain
                    editable in the GUI.
            """
            # Build a set of variance parameter names for quick lookup
            variance_names: set = set()
            if params:
                variance_names = {p.name for p in params if p.is_variance}

            # These params are injected via slider setValue() in apply_config_to_window()
            # and must NOT be locked — the GUI reads them from the slider at print time.
            _SLIDER_ONLY = {"layer_thickness", "overfeed_percent", "density",
                            "preheat_pulses", "prime_pulses"}

            # Build the lock dict: attr_name → coerced value (variance only, non-slider)
            lock_dict: Dict[str, Any] = {}
            for cfg_key, (attr_name, coerce) in _INJECTABLE_ATTRS.items():
                if cfg_key in config and not attr_name.startswith("_cam_"):
                    if cfg_key in _SLIDER_ONLY:
                        continue  # injected via slider, not locked
                    # Only lock if variance (or no params list provided — lock all for safety)
                    if not params or cfg_key in variance_names:
                        try:
                            lock_dict[attr_name] = coerce(config[cfg_key])
                        except (TypeError, ValueError):
                            pass

            # Use super().__setattr__ to bypass our own override
            super().__setattr__("_locked_attrs", lock_dict)

            # Also pre-set the values (so they are non-None before PrintSVG)
            for attr_name, val in lock_dict.items():
                super().__setattr__(attr_name, val)
                log.info("Locked: %s = %r", attr_name, val)

            # Apply camera and inkjet params via the soft path
            apply_config_to_window(self, config)

except ImportError:
    log.debug(
        "oasis_layer_repeat_and_camera_ruff_formatted not importable — ConfigurableMainWindow not registered. "
        "Run from the oasis_layer_repeat_and_camera_ruff_formatted project directory."
    )
    ConfigurableMainWindow = None  # type: ignore[assignment,misc]


# ---------------------------------------------------------------------------
# GUI launcher
# ---------------------------------------------------------------------------
def launch_print(
    config: Dict[str, Any],
    params: Optional[List[OasisParam]] = None,
    dry_run: bool = False,
) -> int:
    """
    Injects CSV parameters and launches the oasis_layer_repeat_and_camera_ruff_formatted GUI.
    COM port connection, file open, and print start are all performed directly in the GUI.

    Parameters
    ----------
    config:  Resolved parameter dict returned by build_config().
    params:  OasisParam list from load_csv(). Used to lock only variance parameters.
    dry_run: If True, only log the config without launching the GUI.

    Returns
    -------
    0 on success, non-zero on failure.
    """
    if dry_run:
        log.info("[DRY-RUN] Would launch GUI with config:")
        for k, v in config.items():
            log.info("  %s = %r", k, v)
        return 0

    if ConfigurableMainWindow is None:
        log.error(
            "ConfigurableMainWindow is unavailable. "
            "Ensure oasis_layer_repeat_and_camera_ruff_formatted.py is on PYTHONPATH."
        )
        return 1

    try:
        from PyQt5.QtWidgets import QApplication  # type: ignore[import]
    except ImportError:
        log.error("PyQt5 is required to launch the print GUI.")
        return 1

    app = QApplication.instance() or QApplication(sys.argv)
    gui = ConfigurableMainWindow()

    # Inject CSV parameters into the GUI (must be done before COM port / file connection)
    gui.lock_params(config, params)
    log.info("Config injected. Use the GUI to open a file, connect ports, and start print.")

    # Start the Qt event loop — exits cleanly when the window is closed
    rc = app.exec_()
    log.info("GUI closed. Exiting.")
    sys.exit(rc)


if __name__ == "__main__":
    # 1. Load & validate CSV
    try:
        params = load_csv(CSV_PATH)
        validate_params(params)
    except (FileNotFoundError, KeyError, ValueError) as exc:
        log.error("%s", exc)
        sys.exit(2)

    # 2. Build resolved config (apply OVERRIDES on top of CSV values)
    try:
        config = build_config(params, OVERRIDES)
    except (KeyError, ValueError) as exc:
        log.error("Config build failed: %s", exc)
        sys.exit(2)

    # 3. Create run directory and write artefacts
    run_dir = _ensure_run_dir(RUN_ID)
    log.info("Run directory: %s", run_dir)
    write_manifest(run_dir, config, CSV_PATH, RUN_ID)
    write_resolved_params(run_dir, params, config)

    # 4. Launch GUI with injected config (only variance params are locked)
    rc = launch_print(config=config, params=params, dry_run=DRY_RUN)
    if rc != 0:
        log.error("Launch failed (exit code %d).", rc)
        sys.exit(rc)
