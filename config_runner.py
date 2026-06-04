"""
CSV-driven parameter sweep runner for the Oasis binder-jet printer.

Usage (inside MainWindow._PrintSVG_inner, replacing the direct layer loop):
    runner = ConfigRunner("print_config.csv", main_window=self)
    runner.run()
"""

import csv
import os
import re
import warnings
from datetime import datetime

import pandas as pd


# ── Valid value sets for range warnings ────────────────────────────────────────
_VALID = {
    "print_speed":     {1100, 2200, 3300},
    "travel_speed":    {1800, 3000, 5000},
    "spread_speed":    {1000, 3000, 6000, 10000},
    "layer_thickness": {0.05, 0.1, 0.2},
    "dpi":             {150, 300, 600},
    "density":         {100, 250, 500},
    "layer_passes":    {1, 3, 5},
    "overfeed":        {1.75, 2.5, 5.0},
}

# Defaults = medium values from the DOE table
_DEFAULTS = {
    "layers":          15,
    "print_speed":     2200,
    "travel_speed":    3000,
    "spread_speed":    6000,
    "layer_thickness": 0.1,
    "dpi":             300,
    "density":         250,
    "layer_passes":    3,
    "overfeed":        2.5,
    "note":            "default",
}

_INT_COLS   = {"step_id", "layers", "print_speed", "travel_speed", "spread_speed",
               "dpi", "density", "layer_passes"}
_FLOAT_COLS = {"layer_thickness", "overfeed"}

LOG_COLUMNS = [
    "timestamp", "step_id", "layer_idx", "pre_or_post", "note",
    "image_filename", "print_speed", "travel_speed", "spread_speed", "layer_thickness",
    "dpi", "density", "layer_passes", "overfeed",
]


def _note_slug(note: str) -> str:
    slug = re.sub(r"[^a-z0-9_]", "_", note.lower().strip())
    return slug[:20]


def _warn(msg: str) -> None:
    warnings.warn(f"[ConfigRunner] {msg}", stacklevel=3)


class ConfigRunner:
    """Load a print_config.csv and drive MainWindow layer-by-layer."""

    def __init__(self, csv_path: str, main_window=None):
        self.csv_path = csv_path
        self.mw = main_window          # MainWindow instance (None in smoke-test)
        self.current_step_id: int = 0
        self.current_note: str = ""

        self._steps = self._load_csv(csv_path)
        self._log_path = os.path.join(
            os.path.dirname(os.path.abspath(csv_path)), "config_log.csv"
        )
        self._log_exists = os.path.exists(self._log_path)

    # ── CSV loading ────────────────────────────────────────────────────────────

    def _load_csv(self, path: str) -> "list[dict]":
        df = pd.read_csv(
            path,
            comment="#",
            skip_blank_lines=True,
            dtype=str,            # read everything as str first; coerce below
        )
        df.dropna(how="all", inplace=True)

        steps = []
        prev = dict(_DEFAULTS)

        for _, row in df.iterrows():
            step: dict = {}

            # step_id is mandatory
            raw_id = str(row.get("step_id", "")).strip()
            if not raw_id or raw_id.lower() == "nan":
                continue
            step["step_id"] = int(float(raw_id))

            # carry-forward for every other column
            for col, default in _DEFAULTS.items():
                raw = str(row.get(col, "")).strip()
                if raw == "" or raw.lower() == "nan":
                    step[col] = prev[col]
                else:
                    if col in _INT_COLS:
                        step[col] = int(float(raw))
                    elif col in _FLOAT_COLS:
                        step[col] = float(raw)
                    else:
                        step[col] = raw

            # range warnings
            for param, valid_set in _VALID.items():
                val = step.get(param)
                if val is not None and val not in valid_set:
                    _warn(
                        f"step {step['step_id']}: {param}={val} not in "
                        f"known values {sorted(valid_set)} — proceeding anyway"
                    )

            prev = dict(step)
            steps.append(step)

        if not steps:
            raise ValueError(f"No valid steps found in {path}")
        return steps

    # ── Parameter application ──────────────────────────────────────────────────

    def _apply_step(self, step: dict) -> None:
        """Push step parameters onto MainWindow state."""
        mw = self.mw
        if mw is None:
            return

        mw.print_speed          = float(step["print_speed"])
        mw.travel_speed         = float(step["travel_speed"])
        mw.grbl.nl_feed_speed   = float(step["spread_speed"])
        mw.layer_passes         = int(step["layer_passes"])

        # Store thickness and overfeed as instance attrs for _print_single_config_layer
        mw.config_layer_thickness = float(step["layer_thickness"])
        mw.config_overfeed        = float(step["overfeed"])

        # inkjet.SetDPI() changes nozzle fire interval (hardware only).
        # printing_sweep_size must track inkjet DPI so each sweep covers the
        # correct physical width. pixel_to_pos_multiplier and imageconverter
        # are NOT touched — coordinates stay tied to the original pixel array.
        inkjet_dpi = int(step["dpi"])
        mw.inkjet.SetDPI(inkjet_dpi)
        mw.printing_sweep_size = inkjet_dpi // 2
        mw.inkjet.SetDensity(int(step["density"]))

        print(
            f"[ConfigRunner] step {step['step_id']} ({step['note']}): "
            f"speed={step['print_speed']}, dpi={step['dpi']}, "
            f"density={step['density']}, passes={step['layer_passes']}"
        )

    # ── Image filename + log ───────────────────────────────────────────────────

    def capture_filename(self, step_id: int, layer_idx: int,
                         pre_or_post: str, note: str) -> str:
        """Return the bare filename stem (no .png) for capture_sync."""
        slug = _note_slug(note)
        return f"s{step_id:03d}_L{layer_idx:03d}_{pre_or_post}_{slug}"

    def log_capture(self, step: dict, layer_idx: int,
                    pre_or_post: str, image_filename: str) -> None:
        row = {
            "timestamp":       datetime.now().isoformat(timespec="seconds"),
            "step_id":         step["step_id"],
            "layer_idx":       layer_idx,
            "pre_or_post":     pre_or_post,
            "note":            step["note"],
            "image_filename":  image_filename + ".png",
            "print_speed":     step["print_speed"],
            "travel_speed":    step["travel_speed"],
            "spread_speed":    step["spread_speed"],
            "layer_thickness": step["layer_thickness"],
            "dpi":             step["dpi"],
            "density":         step["density"],
            "layer_passes":    step["layer_passes"],
            "overfeed":        step["overfeed"],
        }
        write_header = not self._log_exists
        with open(self._log_path, "a", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=LOG_COLUMNS)
            if write_header:
                writer.writeheader()
                self._log_exists = True
            writer.writerow(row)

    # ── Capture helper ─────────────────────────────────────────────────────────

    def _capture(self, step: dict, layer_idx: int, pre_or_post: str) -> None:
        fname = self.capture_filename(
            step["step_id"], layer_idx, pre_or_post, step["note"]
        )
        if self.mw is not None and hasattr(self.mw, "camera_window"):
            self.mw.camera_window.capture_sync(fname)
        else:
            print(f"[ConfigRunner] (no-hw) capture: {fname}.png")
        self.log_capture(step, layer_idx, pre_or_post, fname)

    # ── Main entry point ───────────────────────────────────────────────────────

    def run(self) -> None:
        """Execute all steps in order.  Call this instead of the bare layer loop."""
        for step in self._steps:
            self.current_step_id = step["step_id"]
            self.current_note    = step["note"]

            self._apply_step(step)

            n_layers = int(step["layers"])
            print(
                f"[ConfigRunner] === Step {step['step_id']}: "
                f"{n_layers} layers, note='{step['note']}' ==="
            )

            for layer_idx in range(n_layers):
                self._capture(step, layer_idx, "pre")
                self._print_one_layer(step, layer_idx)
                self._capture(step, layer_idx, "post")   # before next spread
                self._start_next_spread()

        print("[ConfigRunner] Config run complete.")

    def _print_one_layer(self, step: dict, layer_idx: int) -> None:
        """Delegates to MainWindow or is a no-op in smoke tests."""
        if self.mw is None:
            print(
                f"[ConfigRunner] (no-hw) print layer "
                f"s{step['step_id']:03d}_L{layer_idx:03d}"
            )
            return
        self.mw._print_single_config_layer(step, layer_idx)

    def _start_next_spread(self) -> None:
        """Trigger NewLayer() after post capture — spreading starts here."""
        if self.mw is None:
            return
        thickness = getattr(self.mw, "_pending_layer_thickness", None)
        if thickness is not None:
            self.mw.grbl.NewLayer(thickness)
            self.mw._pending_layer_thickness = None
