"""
Visualize all calibration experiment results.

Reads whichever of these CSVs exist under calibration/results/ and plots
what it can — missing files are skipped with a warning, not an error, so
this works fine mid-experiment (e.g. density done, passes/speed not yet).

    calibration/results/binder_delivery_density.csv
    calibration/results/binder_delivery_passes.csv
    calibration/results/binder_delivery_speed.csv
    calibration/results/packing_conditions.csv

Produces (into calibration/results/plots/):
    dose_response_density.png   -- delivered mass vs density, + linear fit
    dose_response_passes.png    -- delivered mass vs layer_passes
    speed_check.png             -- delivered mass vs print_speed (should be flat)
    packing_main_effects.png    -- main-effects plot for the 2^3 factorial
    packing_interactions.png    -- pairwise interaction plots
    packing_cube.png            -- cube plot of the 2^3 design

Usage:
    python plot_calibration_results.py
    python plot_calibration_results.py --results-dir calibration/results
    python plot_calibration_results.py --response defect_count   \\
        # for packing plots, choose which numeric column in
        # packing_conditions.csv to use as the response (default:
        # auto-detects the first numeric column that isn't a known
        # condition/id column)

No dependencies beyond pandas + matplotlib + numpy.
"""

import argparse
import itertools
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.optimize import curve_fit

CONDITION_COLS = {
    "overfeed", "spread_speed", "roller_voltage_v", "rep", "timestamp",
    "filename",
}


def _r2(y, y_pred):
    ss_res = np.sum((y - y_pred) ** 2)
    ss_tot = np.sum((y - y.mean()) ** 2)
    return 1 - ss_res / ss_tot if ss_tot > 0 else float("nan")


# candidate dose-response shapes, tried in order; best R^2 wins.
# ponytail: fixed candidate set (linear/saturation/power) covers the shapes
# seen in binder-delivery data so far. Add another lambda here if a future
# dataset needs a different curve family.
def _fit_candidates(x, y):
    results = []

    lin = np.polyfit(x, y, deg=1)
    results.append((
        "linear", lin,
        lambda xx, c=lin: np.polyval(c, xx),
        _r2(y, np.polyval(lin, x)),
    ))

    # saturation growth: y = a - b*exp(-c*x), needs x>0 and a rising-then-flattening trend
    if np.all(x > 0):
        try:
            a0 = y.max()
            b0 = y.max() - y.min() if y.max() > y.min() else 1.0
            c0 = 1.0 / (x.max() - x.min() + 1e-9)
            popt, _ = curve_fit(
                lambda xx, a, b, c: a - b * np.exp(-c * xx),
                x, y, p0=[a0, b0, c0], maxfev=5000,
            )
            pred = popt[0] - popt[1] * np.exp(-popt[2] * x)
            results.append((
                "saturation", popt,
                lambda xx, p=popt: p[0] - p[1] * np.exp(-p[2] * xx),
                _r2(y, pred),
            ))
        except RuntimeError:
            pass

    # power law through the origin: y = a * x^b (binder scales with e.g. passes)
    if np.all(x > 0) and np.all(y > 0):
        try:
            popt, _ = curve_fit(
                lambda xx, a, b: a * np.power(xx, b),
                x, y, p0=[y.mean() / x.mean(), 1.0], maxfev=5000,
            )
            pred = popt[0] * np.power(x, popt[1])
            results.append((
                "power", popt,
                lambda xx, p=popt: p[0] * np.power(xx, p[1]),
                _r2(y, pred),
            ))
        except RuntimeError:
            pass

    return max(results, key=lambda r: r[3])


# --------------------------------------------------------------------------
# Shared helpers
# --------------------------------------------------------------------------

def try_load(csv_path: Path) -> "pd.DataFrame | None":
    if not csv_path.exists():
        print(f"[skip] {csv_path} not found yet")
        return None
    df = pd.read_csv(csv_path)
    if df.empty:
        print(f"[skip] {csv_path} exists but has no rows yet")
        return None
    print(f"[ok]   {csv_path}  ({len(df)} rows)")
    return df


def dose_response_plot(df: pd.DataFrame, level_col: str, out_path: Path,
                        title: str, xlabel: str, fit: bool = True) -> None:
    fig, ax = plt.subplots(figsize=(7, 5), dpi=150)

    df = df.copy()
    df["delta_mg"] = df["delta_g"] * 1000.0
    levels = sorted(df[level_col].unique())
    means = df.groupby(level_col)["delta_mg"].mean().reindex(levels)
    stds = df.groupby(level_col)["delta_mg"].std().reindex(levels).fillna(0.0)
    n_reps = df.groupby(level_col)["delta_mg"].count().reindex(levels)

    rng = np.random.default_rng(0)
    span = (max(levels) - min(levels)) if len(levels) > 1 else 1
    jitter_scale = span * 0.01
    for lvl in levels:
        vals = df.loc[df[level_col] == lvl, "delta_mg"].values
        jitter = rng.uniform(-jitter_scale, jitter_scale, size=len(vals))
        ax.scatter(np.full(len(vals), lvl) + jitter, vals,
                   color="#7fa8d9", s=35, alpha=0.8, zorder=2)

    ax.errorbar(levels, means.values, yerr=stds.values, fmt="o-",
               color="#1f4e8c", linewidth=2, markersize=7, capsize=4,
               zorder=3, label="mean +/- std")

    if fit and len(levels) >= 2:
        name, _, fit_fn, r2 = _fit_candidates(np.array(levels, dtype=float), means.values)
        fit_x = np.linspace(min(levels), max(levels), 100)
        ax.plot(fit_x, fit_fn(fit_x), "--", color="#c0392b", linewidth=1.5,
               label=f"{name} fit  (R^2={r2:.3f})")
    elif not fit and len(levels) >= 1:
        overall_mean = df["delta_mg"].mean()
        ax.axhline(overall_mean, color="#c0392b", linestyle="--",
                  linewidth=1.5, label=f"overall mean = {overall_mean:.2f} mg")

    ax.set_xlabel(xlabel)
    ax.set_ylabel("Delivered binder mass (mg)")
    ax.set_title(title)
    ax.legend(loc="best", fontsize=9, framealpha=0.9)
    ax.grid(alpha=0.3)

    ymax = df["delta_mg"].max()
    for lvl in levels:
        ax.annotate(f"n={n_reps[lvl]}", (lvl, ymax * 1.05), ha="center",
                   fontsize=8, color="gray")
    ax.set_ylim(top=ymax * 1.15)

    fig.tight_layout()
    fig.savefig(out_path)
    plt.close(fig)
    print(f"  -> {out_path}")


def detect_response_col(df: pd.DataFrame, override: "str | None") -> "str | None":
    if override:
        if override not in df.columns:
            print(f"  [warn] requested response column '{override}' not in "
                 f"packing_conditions.csv (columns: {list(df.columns)})")
            return None
        return override
    for col in df.columns:
        if col in CONDITION_COLS:
            continue
        if pd.api.types.is_numeric_dtype(df[col]):
            return col
    return None


def main_effects_plot(df: pd.DataFrame, response_col: str, out_path: Path) -> None:
    factors = [c for c in ("overfeed", "spread_speed", "roller_voltage_v")
              if c in df.columns]
    center_mask = pd.Series(True, index=df.index)
    # crude "is this the center point" detector: value is between the
    # min and max seen for that factor, not equal to either
    corner_rows = df.copy()
    for f in factors:
        lo, hi = corner_rows[f].min(), corner_rows[f].max()
        corner_rows = corner_rows[corner_rows[f].isin([lo, hi])]

    fig, axes = plt.subplots(1, len(factors), figsize=(5 * len(factors), 4.5), dpi=150)
    if len(factors) == 1:
        axes = [axes]

    for ax, factor in zip(axes, factors):
        lo, hi = df[factor].min(), df[factor].max()
        # average the response over all OTHER factors, at each level of this one
        lo_mean = corner_rows.loc[corner_rows[factor] == lo, response_col].mean()
        hi_mean = corner_rows.loc[corner_rows[factor] == hi, response_col].mean()
        ax.plot([0, 1], [lo_mean, hi_mean], "o-", color="#1f4e8c",
               linewidth=2, markersize=8)
        ax.set_xticks([0, 1])
        ax.set_xticklabels([f"lo\n({lo})", f"hi\n({hi})"])
        ax.set_title(factor)
        ax.set_ylabel(response_col)
        ax.grid(alpha=0.3)

    fig.suptitle(f"Main effects — {response_col}")
    fig.tight_layout()
    fig.savefig(out_path)
    plt.close(fig)
    print(f"  -> {out_path}")


def interaction_plots(df: pd.DataFrame, response_col: str, out_path: Path) -> None:
    factors = [c for c in ("overfeed", "spread_speed", "roller_voltage_v")
              if c in df.columns]
    corner_rows = df.copy()
    for f in factors:
        lo, hi = corner_rows[f].min(), corner_rows[f].max()
        corner_rows = corner_rows[corner_rows[f].isin([lo, hi])]

    pairs = list(itertools.combinations(factors, 2))
    if not pairs:
        print("  [skip] need >= 2 factors for interaction plots")
        return

    fig, axes = plt.subplots(1, len(pairs), figsize=(5.5 * len(pairs), 4.5), dpi=150)
    if len(pairs) == 1:
        axes = [axes]

    for ax, (fa, fb) in zip(axes, pairs):
        lo_a, hi_a = corner_rows[fa].min(), corner_rows[fa].max()
        lo_b, hi_b = corner_rows[fb].min(), corner_rows[fb].max()
        for b_val, label, color in ((lo_b, f"{fb}=lo", "#7fa8d9"),
                                    (hi_b, f"{fb}=hi", "#c0392b")):
            y = []
            for a_val in (lo_a, hi_a):
                sub = corner_rows[(corner_rows[fa] == a_val) &
                                  (corner_rows[fb] == b_val)]
                y.append(sub[response_col].mean())
            ax.plot([0, 1], y, "o-", color=color, linewidth=2,
                   markersize=8, label=label)
        ax.set_xticks([0, 1])
        ax.set_xticklabels([f"{fa}=lo", f"{fa}=hi"])
        ax.set_title(f"{fa} x {fb}")
        ax.set_ylabel(response_col)
        ax.legend(fontsize=8)
        ax.grid(alpha=0.3)
        note = "parallel = independent, crossing = interaction"
        ax.text(0.5, -0.18, note, transform=ax.transAxes, ha="center",
               fontsize=7.5, color="gray")

    fig.tight_layout()
    fig.savefig(out_path)
    plt.close(fig)
    print(f"  -> {out_path}")


def cube_plot(df: pd.DataFrame, response_col: str, out_path: Path) -> None:
    factors = [c for c in ("overfeed", "spread_speed", "roller_voltage_v")
              if c in df.columns]
    if len(factors) != 3:
        print(f"  [skip] cube plot needs exactly 3 factors, found {factors}")
        return

    fa, fb, fc = factors
    lo_a, hi_a = df[fa].min(), df[fa].max()
    lo_b, hi_b = df[fb].min(), df[fb].max()
    lo_c, hi_c = df[fc].min(), df[fc].max()

    corners = {
        (0, 0, 0): (lo_a, lo_b, lo_c), (1, 0, 0): (hi_a, lo_b, lo_c),
        (0, 1, 0): (lo_a, hi_b, lo_c), (1, 1, 0): (hi_a, hi_b, lo_c),
        (0, 0, 1): (lo_a, lo_b, hi_c), (1, 0, 1): (hi_a, lo_b, hi_c),
        (0, 1, 1): (lo_a, hi_b, hi_c), (1, 1, 1): (hi_a, hi_b, hi_c),
    }

    fig = plt.figure(figsize=(7, 6), dpi=150)
    ax = fig.add_subplot(111, projection="3d")

    xs, ys, zs = [0, 1], [0, 1], [0, 1]
    edges = [
        ((0, 0, 0), (1, 0, 0)), ((0, 1, 0), (1, 1, 0)),
        ((0, 0, 1), (1, 0, 1)), ((0, 1, 1), (1, 1, 1)),
        ((0, 0, 0), (0, 1, 0)), ((1, 0, 0), (1, 1, 0)),
        ((0, 0, 1), (0, 1, 1)), ((1, 0, 1), (1, 1, 1)),
        ((0, 0, 0), (0, 0, 1)), ((1, 0, 0), (1, 0, 1)),
        ((0, 1, 0), (0, 1, 1)), ((1, 1, 0), (1, 1, 1)),
    ]
    for p1, p2 in edges:
        ax.plot(*zip(p1, p2), color="gray", linewidth=1)

    for corner_xyz, (a_val, b_val, c_val) in corners.items():
        sub = df[(df[fa] == a_val) & (df[fb] == b_val) & (df[fc] == c_val)]
        val = sub[response_col].mean() if len(sub) else float("nan")
        n = len(sub)
        ax.scatter(*corner_xyz, s=120, color="#1f4e8c")
        ax.text(corner_xyz[0], corner_xyz[1], corner_xyz[2] + 0.06,
               f"{val:.2f}\n(n={n})", fontsize=8, ha="center")

    ax.set_xticks([0, 1]); ax.set_xticklabels([f"{fa}\nlo({lo_a})", f"hi({hi_a})"])
    ax.set_yticks([0, 1]); ax.set_yticklabels([f"{fb}\nlo({lo_b})", f"hi({hi_b})"])
    ax.set_zticks([0, 1]); ax.set_zticklabels([f"{fc}\nlo({lo_c})", f"hi({hi_c})"])
    ax.set_title(f"2^3 factorial cube — {response_col}")

    fig.tight_layout()
    fig.savefig(out_path)
    plt.close(fig)
    print(f"  -> {out_path}")


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--results-dir", type=Path,
                       default=Path("calibration/results"))
    parser.add_argument("--response", type=str, default=None,
                       help="Column in packing_conditions.csv to use as the "
                            "response for packing plots (auto-detected if "
                            "omitted)")
    args = parser.parse_args()

    results_dir = args.results_dir
    plots_dir = results_dir / "plots"
    plots_dir.mkdir(parents=True, exist_ok=True)

    print("Loading calibration results...")
    density_df = try_load(results_dir / "binder_delivery_density.csv")
    passes_df = try_load(results_dir / "binder_delivery_passes.csv")
    speed_df = try_load(results_dir / "binder_delivery_speed.csv")
    packing_df = try_load(results_dir / "packing_conditions.csv")

    print("\nGenerating plots...")

    if density_df is not None:
        dose_response_plot(
            density_df, "level_value", plots_dir / "dose_response_density.png",
            title="Binder delivery vs. density", xlabel="Density (printer setting)",
            fit=True,
        )
    if passes_df is not None:
        dose_response_plot(
            passes_df, "level_value", plots_dir / "dose_response_passes.png",
            title="Binder delivery vs. layer_passes", xlabel="layer_passes",
            fit=True,
        )
    if speed_df is not None:
        dose_response_plot(
            speed_df, "level_value", plots_dir / "speed_check.png",
            title="Binder delivery vs. print_speed (expect ~flat)",
            xlabel="print_speed", fit=False,
        )

    if packing_df is not None:
        response_col = detect_response_col(packing_df, args.response)
        if response_col is None:
            print("  [skip] packing plots — no usable numeric response column "
                 "found. Pass --response <column_name> once image-analysis "
                 "metrics (e.g. gray_level_variance, defect_count) are added "
                 "to packing_conditions.csv.")
        else:
            print(f"  using response column: {response_col}")
            main_effects_plot(packing_df, response_col,
                             plots_dir / "packing_main_effects.png")
            interaction_plots(packing_df, response_col,
                             plots_dir / "packing_interactions.png")
            cube_plot(packing_df, response_col, plots_dir / "packing_cube.png")

    print(f"\nAll available plots saved to {plots_dir}/")


if __name__ == "__main__":
    main()
