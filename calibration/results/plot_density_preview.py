"""
Quick preview plot: binder delivery vs density.

Reads calibration/results/binder_delivery_density.csv (produced by
cal_binder_delivery.py --mode density) and makes a single, presentation-
ready figure: delivered binder mass (mg) vs density, individual reps as
points, condition means as a connected line, plus a linear fit + R^2.

Usage:
    python plot_density_preview.py
    python plot_density_preview.py --csv path/to/binder_delivery_density.csv
    python plot_density_preview.py --out preview.png

No dependencies beyond pandas + matplotlib + numpy.
"""

import argparse
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


def load_data(csv_path: Path) -> pd.DataFrame:
    if not csv_path.exists():
        sys.exit(
            f"Could not find {csv_path}\n"
            f"Run cal_binder_delivery.py --mode density first, or pass "
            f"--csv <path> to point at the right file."
        )
    df = pd.read_csv(csv_path)

    required = {"level_value", "delta_g"}
    missing = required - set(df.columns)
    if missing:
        sys.exit(
            f"{csv_path} is missing expected column(s): {sorted(missing)}\n"
            f"Found columns: {list(df.columns)}"
        )

    # mg is a friendlier unit than g for single-layer drop deposits
    df["delta_mg"] = df["delta_g"] * 1000.0
    return df


def make_plot(df: pd.DataFrame, out_path: Path) -> None:
    fig, ax = plt.subplots(figsize=(7, 5), dpi=150)

    levels = sorted(df["level_value"].unique())
    means = df.groupby("level_value")["delta_mg"].mean().reindex(levels)
    stds = df.groupby("level_value")["delta_mg"].std().reindex(levels)
    n_reps = df.groupby("level_value")["delta_mg"].count().reindex(levels)

    # individual reps, jittered slightly so overlapping points are visible
    rng = np.random.default_rng(0)
    for lvl in levels:
        vals = df.loc[df["level_value"] == lvl, "delta_mg"].values
        jitter = rng.uniform(-2, 2, size=len(vals))
        ax.scatter(
            np.full(len(vals), lvl) + jitter,
            vals,
            color="#7fa8d9",
            s=35,
            alpha=0.8,
            zorder=2,
            label="individual reps" if lvl == levels[0] else None,
        )

    # condition means +/- std
    ax.errorbar(
        levels,
        means.values,
        yerr=stds.values,
        fmt="o-",
        color="#1f4e8c",
        linewidth=2,
        markersize=7,
        capsize=4,
        zorder=3,
        label="mean +/- std",
    )

    # linear fit across condition means (weights by n if reps differ)
    if len(levels) >= 2:
        coeffs = np.polyfit(levels, means.values, deg=1)
        fit_x = np.linspace(min(levels), max(levels), 100)
        fit_y = np.polyval(coeffs, fit_x)
        y_pred = np.polyval(coeffs, np.array(levels))
        ss_res = np.sum((means.values - y_pred) ** 2)
        ss_tot = np.sum((means.values - means.values.mean()) ** 2)
        r2 = 1 - ss_res / ss_tot if ss_tot > 0 else float("nan")
        ax.plot(
            fit_x, fit_y, "--", color="#c0392b", linewidth=1.5, zorder=1,
            label=f"linear fit: y={coeffs[0]:.3f}x+{coeffs[1]:.2f}  (R^2={r2:.3f})",
        )

    ax.set_xlabel("Density (printer setting)")
    ax.set_ylabel("Delivered binder mass (mg)")
    ax.set_title("Binder density vs. Binder mass — 40x45mm 3 passes layer")
    ax.legend(loc="upper left", fontsize=9, framealpha=0.9)
    ax.grid(alpha=0.3)

    # annotate n per condition along the top
    ymax = df["delta_mg"].max()
    for lvl in levels:
        ax.annotate(
            f"n={n_reps[lvl]}",
            (lvl, ymax * 1.05),
            ha="center",
            fontsize=8,
            color="gray",
        )
    ax.set_ylim(top=ymax * 1.15)

    fig.tight_layout()
    fig.savefig(out_path)
    print(f"Saved: {out_path}")

    # console summary table, handy to paste into chat/slack alongside the image
    print("\nSummary:")
    summary = pd.DataFrame({
        "density": levels,
        "n_reps": [n_reps[l] for l in levels],
        "mean_mg": [round(means[l], 3) for l in levels],
        "std_mg": [round(stds[l], 3) if not np.isnan(stds[l]) else 0.0 for l in levels],
    })
    print(summary.to_string(index=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--csv",
        type=Path,
        default=Path("calibration/results/binder_delivery_density.csv"),
        help="Path to binder_delivery_density.csv",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("calibration/results/plots/density_preview.png"),
        help="Output image path",
    )
    args = parser.parse_args()

    args.out.parent.mkdir(parents=True, exist_ok=True)
    df = load_data(args.csv)
    make_plot(df, args.out)


if __name__ == "__main__":
    main()
