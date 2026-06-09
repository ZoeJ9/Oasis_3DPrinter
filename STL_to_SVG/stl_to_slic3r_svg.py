"""
STL -> single multi-layer SVG, matching the Slic3r 1.3.0 "Slice to SVG" format.

Why this format: import software that expects Slic3r SVGs parses <g> layer groups
that carry slic3r:z / slic3r:slice-z / slic3r:layer-height attributes, unitless
width/height, no viewBox, and the specific namespace set Slic3r emits. A generic
SVG (units on width, viewBox, <path> with L/commas) gets rejected as "wrong type".

Requirements:
    pip install trimesh shapely numpy
"""

import trimesh
import trimesh.repair
import numpy as np

# --- Configuration ---
import os as _os
_DIR = _os.path.dirname(_os.path.abspath(__file__))
STL_FILE = _os.path.join(_DIR, "Daring_Snaget_scale.stl")
OUTPUT_SVG = _os.path.join(_DIR, "output_slic3r_format.svg")
LAYER_HEIGHT = 0.1   # mm
BED_X = 84           # mm
BED_Y = 84           # mm
FLIP_Y = False       # Slic3r writes raw mm coords (no flip). Set True only if output is mirrored.


def ring_to_points(coords, bed_y, flip_y):
    """Build a Slic3r-style polygon 'points': 'x,y x,y x,y ...' (comma-separated pairs, space between)."""
    pts = coords[:-1] if len(coords) > 1 and coords[0] == coords[-1] else coords
    fy = (lambda y: bed_y - y) if flip_y else (lambda y: y)
    return " ".join(f"{x:.4f},{fy(y):.4f}" for x, y in pts)


def main():
    # Load STL and force a single mesh (a multi-body STL would otherwise load as a Scene)
    mesh = trimesh.load(STL_FILE, force="mesh")

    # Repair the mesh
    trimesh.repair.fix_normals(mesh)
    trimesh.repair.fix_inversion(mesh)
    mesh.fill_holes()
    print(f"Watertight: {mesh.is_watertight}")

    # Center the model on the bed using the bounding-box center, drop its bottom onto z = 0
    bb_min, bb_max = mesh.bounds
    cx = (bb_min[0] + bb_max[0]) / 2
    cy = (bb_min[1] + bb_max[1]) / 2
    mesh.apply_translation([-cx + BED_X / 2, -cy + BED_Y / 2, -bb_min[2]])

    # Slice planes from just above the base up to the top
    z_min = mesh.bounds[0][2]
    z_max = mesh.bounds[1][2]
    z_levels = np.arange(z_min + LAYER_HEIGHT, z_max + LAYER_HEIGHT, LAYER_HEIGHT)

    # --- SVG header, matching Slic3r 1.3.0 exactly ---
    lines = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>']
    lines.append(
        '<!DOCTYPE svg PUBLIC "-//W3C//DTD SVG 1.0//EN" '
        '"http://www.w3.org/TR/2001/REC-SVG-20010904/DTD/svg10.dtd">'
    )
    lines.append(
        f'<svg width="{BED_X}" height="{BED_Y}" '          # unitless numbers, no "mm", no viewBox
        'xmlns="http://www.w3.org/2000/svg" '
        'xmlns:svg="http://www.w3.org/2000/svg" '
        'xmlns:xlink="http://www.w3.org/1999/xlink" '
        'xmlns:slic3r="http://slic3r.org/namespaces/slic3r">'
    )
    lines.append('  <!-- ')
    lines.append('  Generated using Slic3r 1.3.0')
    lines.append('  http://slic3r.org/')
    lines.append('   -->')

    # --- One <g> group per layer ---
    layer_count = 0
    for i, z in enumerate(z_levels):
        section = mesh.section(plane_origin=[0, 0, z], plane_normal=[0, 0, 1])
        if section is None:
            continue
        try:
            # Identity transform keeps the slice in its original XY (bed) coordinates
            path2d, _ = section.to_planar(to_2D=np.eye(4))
            polygons = path2d.polygons_full
        except Exception as e:
            print(f"Layer {i} (z={z:.3f}) skipped: {e}")
            continue

        # ImageConverter reads slic3r:z and multiplies by 1,000,000 assuming km units.
        # Store values in km (divide mm by 1,000,000) so the result comes back in mm.
        slice_z = z
        top_z = z + LAYER_HEIGHT / 2
        lines.append(
            f'  <g id="layer{i}" '
            f'slic3r:z="{top_z / 1e6:.10f}" '
            f'slic3r:slice-z="{slice_z / 1e6:.10f}" '
            f'slic3r:layer-height="{LAYER_HEIGHT / 1e6:.10f}">'
        )

        for polygon in polygons:
            # Outer contour = solid area
            lines.append(
                f'    <polygon points="{ring_to_points(list(polygon.exterior.coords), BED_Y, FLIP_Y)}" '
                f'style="fill: white" />'
            )
            # Inner holes
            for interior in polygon.interiors:
                lines.append(
                    f'    <polygon points="{ring_to_points(list(interior.coords), BED_Y, FLIP_Y)}" '
                    f'style="fill: black" />'
                )

        lines.append('  </g>')
        layer_count += 1

    lines.append('</svg>')

    with open(OUTPUT_SVG, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"Done: {layer_count} layers -> {OUTPUT_SVG}")


if __name__ == "__main__":
    main()
