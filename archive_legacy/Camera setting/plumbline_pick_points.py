"""
Step 1 of plumb-line calibration: click points along known-straight edges
(ruler edges) in one or more photos.

Why manual clicking instead of edge detection: ruler tick marks and numbers
create lots of short spurious edges that confuse automatic line detectors.
Clicking 4-8 points per straight edge is fast and gives clean data for the

Usage:
    python plumbline_pick_points.py --images preview1.png preview2.png preview3.png preview4.png

Controls:
    - Left click: add a point to the current line
    - 'n': finish current line, start a new one
    - 'u': undo last point
    - 'z': discard current (unfinished) line and start over
    - 's': save all lines for this image and move to the next image
    - 'q': quit (saves what's collected so far)

Output:
    plumbline_points.json -- list of {"image": path, "lines": [[[x,y], ...], ...]}
"""

import argparse
import json
import os

import cv2

WINDOW = "Click points along a straight edge (n=next line, u=undo, s=save+next image, q=quit)"


def pick_lines_for_image(img_path):
    img = cv2.imread(img_path)
    if img is None:
        raise FileNotFoundError(f"Could not read image: {img_path}")

    lines = []
    current = []

    def on_mouse(event, x, y, flags, userdata):
        if event == cv2.EVENT_LBUTTONDOWN:
            current.append([x, y])

    cv2.namedWindow(WINDOW, cv2.WINDOW_NORMAL)
    h, w = img.shape[:2]
    cv2.resizeWindow(WINDOW, min(w, 900), min(h, 1600))
    cv2.setMouseCallback(WINDOW, on_mouse)

    print(f"\n{img_path}: click points along each straight edge, 'n' for next line, 's' when done.")

    result_key = None
    while True:
        display = img.copy()
        for line in lines:
            for pt in line:
                cv2.circle(display, tuple(pt), 4, (0, 255, 0), -1)
            for a, b in zip(line, line[1:]):
                cv2.line(display, tuple(a), tuple(b), (0, 255, 0), 1)
        for pt in current:
            cv2.circle(display, tuple(pt), 4, (0, 0, 255), -1)
        for a, b in zip(current, current[1:]):
            cv2.line(display, tuple(a), tuple(b), (0, 0, 255), 1)

        cv2.imshow(WINDOW, display)
        key = cv2.waitKey(30) & 0xFF

        if key == ord('n'):
            if len(current) >= 2:
                lines.append(current)
            else:
                print("Need at least 2 points per line, ignoring.")
            current = []
        elif key == ord('u'):
            if current:
                current.pop()
            elif lines:
                current = lines.pop()
                current.pop()
        elif key == ord('z'):
            current = []
        elif key == ord('s'):
            if len(current) >= 2:
                lines.append(current)
            current = []
            result_key = "save"
            break
        elif key == ord('q'):
            if len(current) >= 2:
                lines.append(current)
            result_key = "quit"
            break

    cv2.destroyWindow(WINDOW)
    return lines, result_key


def main():
    parser = argparse.ArgumentParser(description="Pick points along straight edges for plumb-line calibration")
    parser.add_argument("--images", nargs="+", required=True, help="Ruler photo(s) to annotate")
    parser.add_argument("--out", default="plumbline_points.json", help="Output JSON path")
    args = parser.parse_args()

    all_data = []
    for img_path in args.images:
        lines, action = pick_lines_for_image(img_path)
        if lines:
            all_data.append({"image": img_path, "lines": lines})
            print(f"  saved {len(lines)} line(s) for {img_path}")
        if action == "quit":
            break

    with open(args.out, "w") as f:
        json.dump(all_data, f, indent=2)
    print(f"\nWrote {args.out} ({sum(len(d['lines']) for d in all_data)} lines total across {len(all_data)} image(s))")
    print("Next: python plumbline_solve.py --points", args.out)


if __name__ == "__main__":
    main()
