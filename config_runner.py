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
    "layer_passes":      {1, 3, 5},
    "overfeed":          {2.0, 3.5, 5.0},
    "separation_layers": {0, 5, 10, 15, 20},
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
    "overfeed":          3.5,
    "separation_layers": 15,
    "note":              "default",
}

_INT_COLS   = {"step_id", "layers", "print_speed", "travel_speed", "spread_speed",
               "dpi", "density", "layer_passes", "separation_layers"}
_FLOAT_COLS = {"layer_thickness", "overfeed"}

# ── Phase 2: hardcoded single-condition DOE runs ────────────────────────────────
# Fill in values after Phase 1 (ConfigRunner CSV sweep) narrows the ranges.
# Units match nl_piston_overfeed directly (e.g. overfeed=3.5 means 350% feed) —
# NOT the GUI slider's SetOverfeed() percent convention, which is dead code
# (SerialGRBL.SetOverfeed writes to a local variable, never self.nl_piston_overfeed).
DOE_CONDITIONS = {
    # --- density ladder (all else baseline) ---
    1: dict(density=100, overfeed=3.5, spread_speed=6000, print_speed=2200, layer_passes=3),
    2: dict(density=175, overfeed=3.5, spread_speed=6000, print_speed=2200, layer_passes=3),
    3: dict(density=250, overfeed=3.5, spread_speed=6000, print_speed=2200, layer_passes=3),  # baseline
    4: dict(density=325, overfeed=3.5, spread_speed=6000, print_speed=2200, layer_passes=3),
    5: dict(density=400, overfeed=3.5, spread_speed=6000, print_speed=2200, layer_passes=3),
    # --- packing ladder (density = safe mid from runs 1-5) ---
    6: dict(density=250, overfeed=2.0, spread_speed=9000, print_speed=2200, layer_passes=3),
    7: dict(density=250, overfeed=5.0, spread_speed=3000, print_speed=2200, layer_passes=3),
    # --- dwell ladder ---
    8: dict(density=250, overfeed=3.5, spread_speed=6000, print_speed=800,  layer_passes=3),
    9: dict(density=250, overfeed=3.5, spread_speed=6000, print_speed=3000, layer_passes=3),
}
SELECTED_RUN = 1
DOE_LAYER_THICK_MM = 0.1


def apply_print_condition(mw, params: dict) -> dict:
    """Inject only the keys present in params onto the live hardware objects.

    Shared by both entry points (ConfigRunner CSV steps and DOE Print) so
    there is exactly one place that knows how to push a parameter onto
    hardware. Must be called AFTER _init_print_state(), which hardcodes
    print_speed=2200.0 / travel_speed=3000.0 — calling before would let
    those defaults clobber the injected values.

    Returns the post-injection readback dict (applied_*), read from the
    hardware objects themselves, not echoed from params.
    """
    if "print_speed" in params:
        mw.print_speed = float(params["print_speed"])

    if "spread_speed" in params:
        mw.grbl.nl_feed_speed = float(params["spread_speed"])

    if "overfeed" in params:
        # SetOverfeed() is dead code (self-less local var) — write the field
        # NewLayer() actually reads for the feed-piston move directly.
        mw.grbl.nl_piston_overfeed = float(params["overfeed"])

    if "layer_passes" in params:
        mw.layer_passes = int(params["layer_passes"])

    if "layer_thickness" in params:
        mw.config_mode_active     = True
        mw.config_layer_thickness = float(params["layer_thickness"])

    if "dpi" in params:
        inkjet_dpi = int(params["dpi"])
        if inkjet_dpi != int(mw.imageconverter.dpi):
            # SetDPI() alone only changes self.dpi — image_array_height/width
            # stay at whatever they were computed at on load. Re-opening the
            # already-loaded file re-runs SVGGetData(), which recomputes the
            # pixel grid from the new dpi. Same pattern as InkjetSetDPI().
            mw.imageconverter.SetDPI(inkjet_dpi)
            if not getattr(mw, "input_file_name", None):
                raise RuntimeError(
                    "apply_print_condition: dpi change requires a re-openable "
                    "file (mw.input_file_name not set) to re-rasterize."
                )
            mw.OpenFile(mw.input_file_name[0])
            mw.printing_dpi            = inkjet_dpi
            mw.printing_sweep_size     = inkjet_dpi // 2
            mw.pixel_to_pos_multiplier = 25.4 / inkjet_dpi
            mw.image_size_x            = mw.imageconverter.image_array_height
            mw.image_size_y            = mw.imageconverter.image_array_width
        mw.inkjet.SetDPI(inkjet_dpi)
        mw.printing_sweep_size = inkjet_dpi // 2

    if "density" in params:
        # Must be re-sent every time — HP45 otherwise keeps the last
        # manually-set value from the GUI density slider.
        mw.inkjet.SetDensity(int(params["density"]))

    applied = {
        "applied_print_speed":     mw.print_speed,
        "applied_travel_speed":    mw.travel_speed,
        "applied_spread_speed":    mw.grbl.nl_feed_speed,
        "applied_layer_thickness": getattr(mw, "config_layer_thickness", None),
        "applied_dpi":             mw.inkjet.inkjet_dpi,
        "applied_density":         mw.inkjet.inkjet_density,
        "applied_layer_passes":    mw.layer_passes,
        "applied_overfeed":        mw.grbl.nl_piston_overfeed,
    }
    print(f"[apply_print_condition] {applied}")
    return applied

LOG_COLUMNS = [
    "timestamp", "step_id", "layer_idx", "svg_layer", "pre_or_post", "note",
    "image_filename",
    # applied_* = read back from the hardware objects after injection, not the
    # raw CSV value — this is what the printer actually used for this layer.
    "applied_print_speed", "applied_travel_speed", "applied_spread_speed",
    "applied_layer_thickness", "applied_dpi", "applied_density",
    "applied_layer_passes", "applied_overfeed", "separation_layers",
]


def _note_slug(note: str) -> str:
    slug = re.sub(r"[^a-z0-9_]", "_", note.lower().strip())
    return slug[:20]


def _warn(msg: str) -> None:
    warnings.warn(f"[ConfigRunner] {msg}", stacklevel=3)


class ConfigRunner:
    """Load a print_config.csv and drive MainWindow layer-by-layer."""

    def __init__(self, csv_path: str, main_window=None, capture_policy: str = "all"):
        """capture_policy: "all" (pre+post every layer, existing behavior),
        "last" (pre+post only on each step's final layer), or "none"."""
        if capture_policy not in ("all", "last", "none"):
            raise ValueError(f"capture_policy must be all/last/none, got {capture_policy!r}")
        self.csv_path = csv_path
        self.mw = main_window          # MainWindow instance (None in smoke-test)
        self.capture_policy = capture_policy
        self.current_step_id: int = 0
        self.current_note: str = ""

        self._steps = self._load_csv(csv_path)
        self._log_path = os.path.join(
            os.path.dirname(os.path.abspath(csv_path)), "config_log.csv"
        )
        self._log_exists = os.path.exists(self._log_path)
        self._applied: dict = {}  # no-hw (dry-run) shadow of what _apply_step set

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

        # dpi must be uniform across the whole build — it's applied once
        # before rasterization starts, not re-applied per step.
        dpis = {s["dpi"] for s in steps}
        if len(dpis) > 1:
            raise ValueError(
                f"print_config.csv has non-uniform dpi across steps: {sorted(dpis)}. "
                f"dpi is applied once for the whole build — use one CSV per dpi."
            )
        return steps

    def _validate_against_svg(self, svg_layers: int) -> None:
        """Continuous build: each step consumes step['layers'] SVG layers in
        sequence, so the sum must fit inside the loaded SVG. Called from
        run() once the real (or simulated, in dry-run) layer count is known.
        """
        total = sum(s["layers"] for s in self._steps)
        if total > svg_layers:
            raise ValueError(
                f"print_config.csv steps consume {total} SVG layers "
                f"(sum of each step's 'layers' column) but the loaded SVG "
                f"only has {svg_layers}. Reduce step layer counts or load a "
                f"taller SVG."
            )
        if total < svg_layers:
            print(
                f"[ConfigRunner] NOTICE: steps consume {total} of "
                f"{svg_layers} SVG layers — trailing {svg_layers - total} "
                f"layer(s) will be unprinted."
            )

    # ── Parameter application ──────────────────────────────────────────────────

    def _apply_step(self, step: dict) -> None:
        """Push step parameters onto MainWindow state via apply_print_condition.

        dpi is intentionally excluded from the per-step params dict — it's
        validated uniform across the whole CSV at load time and applied once
        in run() before the build starts, not re-applied every step.
        """
        mw = self.mw
        if mw is None:
            # Dry-run: nothing to inject into, but record what *would* be
            # applied so applied_* logging still reflects per-step changes.
            self._applied = {
                "applied_print_speed":     float(step["print_speed"]),
                "applied_travel_speed":    float(step["travel_speed"]),
                "applied_spread_speed":    float(step["spread_speed"]),
                "applied_layer_thickness": float(step["layer_thickness"]),
                "applied_dpi":             int(step["dpi"]),
                "applied_density":         int(step["density"]),
                "applied_layer_passes":    int(step["layer_passes"]),
                "applied_overfeed":        float(step["overfeed"]),
            }
            return

        mw.travel_speed = float(step["travel_speed"])  # not a DOE factor, but still per-CSV
        params = {
            "print_speed":     step["print_speed"],
            "spread_speed":    step["spread_speed"],
            "overfeed":        step["overfeed"],
            "layer_passes":    step["layer_passes"],
            "layer_thickness": step["layer_thickness"],
            "density":         step["density"],
        }
        self._applied = apply_print_condition(mw, params)
        self._applied["applied_travel_speed"] = mw.travel_speed

        print(
            f"[ConfigRunner] step {step['step_id']} ({step['note']}): "
            f"speed={step['print_speed']}, density={step['density']}, "
            f"passes={step['layer_passes']}"
        )

    # ── Image filename + log ───────────────────────────────────────────────────

    def capture_filename(self, step_id: int, layer_idx: int,
                         pre_or_post: str, note: str) -> str:
        """Return the bare filename stem (no .png) for capture_sync."""
        slug = _note_slug(note)
        return f"s{step_id:03d}_L{layer_idx:03d}_{pre_or_post}_{slug}"

    def log_capture(self, step: dict, layer_idx: int, svg_layer: int,
                    pre_or_post: str, image_filename: str) -> None:
        row = {
            "timestamp":       datetime.now().isoformat(timespec="seconds"),
            "step_id":         step["step_id"],
            "layer_idx":       layer_idx,
            "svg_layer":       svg_layer,
            "pre_or_post":     pre_or_post,
            "note":            step["note"],
            "image_filename":  image_filename + ".png",
            "separation_layers": step["separation_layers"],
            **self._applied,
        }
        write_header = not self._log_exists
        with open(self._log_path, "a", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=LOG_COLUMNS)
            if write_header:
                writer.writeheader()
                self._log_exists = True
            writer.writerow(row)

    # ── Capture helper ─────────────────────────────────────────────────────────

    def _capture(self, step: dict, layer_idx: int, svg_layer: int, pre_or_post: str) -> None:
        fname = self.capture_filename(
            step["step_id"], layer_idx, pre_or_post, step["note"]
        )
        if self.mw is not None and hasattr(self.mw, "camera_window"):
            self.mw.camera_window.capture_sync(fname)
        else:
            print(f"[ConfigRunner] (no-hw) capture: {fname}.png")
        self.log_capture(step, layer_idx, svg_layer, pre_or_post, fname)

    # ── Main entry point ───────────────────────────────────────────────────────

    def run(self, simulated_svg_layers: int = None) -> None:
        """Execute all steps as ONE continuous build over a single loaded SVG.

        Step 1 prints SVG layers 1..step1['layers'], step 2 continues from
        where step 1 left off, etc. — current_layer is never reset mid-build.
        Each step's separation_layers blank recoats (at least 1, unless it's
        the last step) run after its own SVG layers and before the next
        step's parameters are applied.

        simulated_svg_layers: dry-run only (mw is None) — stands in for
        imageconverter.svg_layers so the sum-of-steps validation and the
        continuous svg_layer counter can be exercised with no SVG loaded.
        """
        svg_layers = (
            self.mw.imageconverter.svg_layers if self.mw is not None
            else simulated_svg_layers
        )
        if svg_layers is not None:
            self._validate_against_svg(svg_layers)

        # dpi is uniform across the CSV (validated in _load_csv) — apply once,
        # before the first rasterization, instead of re-applying every step.
        if self.mw is not None:
            apply_print_condition(self.mw, {"dpi": self._steps[0]["dpi"]})
            self.mw.current_layer        = 1
            self.mw.current_layer_height = self.mw.imageconverter.svg_layer_height[0]
        svg_layer = 1  # dry-run mirror of mw.current_layer, 1-based

        for step_num, step in enumerate(self._steps):
            is_last_step = step_num == len(self._steps) - 1
            self.current_step_id = step["step_id"]
            self.current_note    = step["note"]

            self._apply_step(step)

            n_step_layers = int(step["layers"])
            svg_start = self.mw.current_layer if self.mw is not None else svg_layer
            print(
                f"[ConfigRunner] === Step {step['step_id']}: "
                f"SVG layers {svg_start}-{svg_start + n_step_layers - 1}, "
                f"sep={step['separation_layers']}, note='{step['note']}' ==="
            )

            for layer_idx in range(n_step_layers):
                is_last = layer_idx == n_step_layers - 1
                do_capture = (
                    self.capture_policy == "all"
                    or (self.capture_policy == "last" and is_last)
                )
                cur_svg_layer = self.mw.current_layer if self.mw is not None else svg_layer
                if do_capture:
                    self._capture(step, layer_idx, cur_svg_layer, "pre")
                self._print_one_layer(step, layer_idx)
                if do_capture:
                    self._capture(step, layer_idx, cur_svg_layer, "post")
                if not is_last:
                    # Mid-step: spread for the next SVG layer immediately.
                    # On the step's last layer, skip this — separation_spread
                    # (below) owns the next spread so thickness/overfeed for
                    # the *next* step's params apply cleanly, with no stray
                    # extra spread using the outgoing step's thickness.
                    self._start_next_spread()
                if self.mw is None:
                    svg_layer += 1

            # Consume the pending post-layer spread (queued by
            # _print_single_config_layer after the step's last layer) so it
            # doesn't leak into the next step — separation recoats replace it.
            if self.mw is not None:
                self.mw._pending_layer_thickness = None

            # Blank recoats between steps (no SBR — powder only). Skipped
            # entirely after the last step — the build is done, nothing
            # left to spread for. Otherwise at least one always runs, even
            # if separation_layers=0: the step-boundary spread cancelled
            # above still has to happen so the next step's first layer isn't
            # printed onto bare, unspread powder.
            if not is_last_step:
                n_sep = max(1, int(step["separation_layers"]))
                print(f"[ConfigRunner] {n_sep} separation layer(s) after step {step['step_id']}")
                self._separation_spread(step, n_sep)

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

    def _separation_spread(self, step: dict, n: int) -> None:
        """Spread powder N times without printing (no SBR).

        Uses the last SVG layer_thickness as the recoat increment.
        Waits for each spread to complete before triggering the next.
        """
        if self.mw is None:
            print(f"[ConfigRunner] (no-hw) separation: {n} blank recoats")
            return
        thickness = float(step["layer_thickness"])
        import time
        for i in range(n):
            print(f"[ConfigRunner] separation spread {i + 1}/{n} (thickness={thickness}mm)")
            self.mw.grbl.NewLayer(thickness)
            # Wait for spread to complete
            while self.mw.grbl.nl_state == 0:
                time.sleep(0.1)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Run a print_config.csv with no hardware attached and "
                     "print the applied_* values per step (dry run)."
    )
    parser.add_argument("csv_path", help="Path to print_config.csv")
    parser.add_argument(
        "--dry-run", action="store_true", required=True,
        help="Required flag — this CLI only supports no-hardware dry runs.",
    )
    parser.add_argument(
        "--svg-layers", type=int, default=None,
        help="Simulated total SVG layer count, so the continuous-build "
             "sum(step['layers']) <= svg_layers validation can run with no "
             "SVG loaded. Omit to skip validation.",
    )
    args = parser.parse_args()

    runner = ConfigRunner(args.csv_path, main_window=None)
    runner.run(simulated_svg_layers=args.svg_layers)
    print(f"[ConfigRunner] dry-run log written to {runner._log_path}")
