"""Shared hardware/geometry/CSV helpers for standalone calibration scripts.

Reuses the same GRBL/HP45 protocol and SBR sweep-printing algorithm as
main.py's _run_calibration_inner / _print_single_config_layer, without
importing main.py or src/config_runner.py (no GUI, no SVG/ImageConverter).
"""

import csv
import math
import os
import sys
import time

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from src.SerialGRBL import GRBL
from src.SerialHP45 import HP45
from src import B64

RESULTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")

BED_DIAMETER_MM = 84.0

# Camera settings — matches main.py module constants (MJPEG, manual exposure)
CAMERA_BACKEND_IS_DSHOW = True  # main.py uses cv2.CAP_DSHOW on Windows
AUTO_EXPOSURE_MANUAL = 0.25
EXPOSURE_VALUE = -3
GAIN_VALUE = 0
CAPTURE_WIDTH = 3840
CAPTURE_HEIGHT = 2160
LED_FLUSH_FRAMES = 8  # matches main.py's _grab_frame flush count

# Arduino LED controller protocol — matches archive_legacy/Density_mapping_v1.1.py's
# CameraController: single-char commands "1".."5" turn on that LED, "0" turns all off.
LED_BAUD_RATE = 9600
LED_CONNECT_SETTLE_S = 2.0
LED_SETTLE_MS = 200  # ms to wait after a LED turns on before capturing
NUM_LEDS = 5


def connect_led_controller(port: str):
    """Connect to the Arduino LED controller. Returns an open serial.Serial, or
    raises if the port can't be opened. No hardware to disconnect if omitted —
    capture_frame() falls back to an unlit capture when conn is None."""
    import serial
    conn = serial.Serial(port, LED_BAUD_RATE, timeout=1)
    time.sleep(LED_CONNECT_SETTLE_S)
    conn.reset_input_buffer()
    return conn


def _led_send(led_conn, cmd: str) -> None:
    if led_conn is not None and led_conn.is_open:
        led_conn.write(cmd.encode())


def led_on(led_conn, n: int) -> None:
    """Turn on LED n (1-indexed)."""
    _led_send(led_conn, str(n))


def led_all_off(led_conn) -> None:
    _led_send(led_conn, "0")


def connect_hardware(grbl_port: str, hp45_port: str):
    """Connect to GRBL and HP45. Hard-fails with a clear message if either fails."""
    grbl = GRBL()
    if grbl.Connect(grbl_port) != 1:
        raise RuntimeError(f"Failed to connect to GRBL on {grbl_port}")

    inkjet = HP45()
    if inkjet.Connect(hp45_port) != 1:
        raise RuntimeError(f"Failed to connect to HP45 on {hp45_port}")

    return grbl, inkjet


class HomingFailed(RuntimeError):
    """Raised when GRBL never reaches homed_state == 1 — e.g. it's in an alarm/lock
    state and silently ignored the $h homing command. NewLayer()/Jog() both gate on
    homed_state == 1 and no-op (no error, no motion) if it's not set, so catching
    this here up front avoids a confusing "nothing moved" result downstream."""


def home_and_wait(grbl: GRBL, poll_interval: float = 0.1, timeout_s: float = 30.0) -> None:
    """Home the printer and block until motion is idle and homing has completed.

    Raises HomingFailed if GRBL doesn't report homed_state == 1 within timeout_s
    (e.g. because it started in an alarm/lock state that $h can't clear)."""
    grbl.Home()
    start = time.time()
    while grbl.motion_state != "idle":
        if time.time() - start > timeout_s:
            raise HomingFailed(
                f"GRBL motion_state stuck at {grbl.motion_state!r} after {timeout_s}s. "
                f"If GRBL is alarm-locked, send $X to unlock it, then retry."
            )
        time.sleep(poll_interval)
    time.sleep(0.25)  # settle, matches main.py's post-home delay

    if grbl.homed_state != 1:
        raise HomingFailed(
            f"Homing did not complete (homed_state={grbl.homed_state}, expected 1). "
            f"GRBL may be alarm-locked — send $X to unlock, then retry. "
            f"NewLayer()/Jog() will silently no-op (no motion, no error) otherwise."
        )


def spread_one_layer(grbl: GRBL, thickness_mm: float, overfeed: float, feed_speed: float,
                      poll_interval: float = 0.005) -> None:
    """Spread one powder layer with the given overfeed and feed speed.

    Sets grbl.nl_piston_overfeed / grbl.nl_feed_speed directly — SetOverfeed()
    is dead code (assigns a bare local, never self.nl_piston_overfeed), so it
    is never called here.
    """
    grbl.nl_piston_overfeed = overfeed
    grbl.nl_feed_speed = feed_speed
    print(f"[spread_one_layer] before NewLayer: homed_state={grbl.homed_state}, "
          f"motion_state={grbl.motion_state!r}, gcode_buffer_left={grbl.gcode_buffer_left}, "
          f"nl_state={grbl.nl_state}")
    if grbl.homed_state != 1:
        raise HomingFailed(
            f"NewLayer() would silently no-op: homed_state={grbl.homed_state} (expected 1). "
            f"GRBL likely dropped out of homed state (e.g. an alarm) between home_and_wait() "
            f"and this call — re-home before retrying."
        )
    grbl.NewLayer(thickness_mm)
    print(f"[spread_one_layer] after NewLayer call: gcode_buffer_left={grbl.gcode_buffer_left}, "
          f"nl_state={grbl.nl_state} (0 = queued/in-progress, 1 = never started or already done)")
    start = time.time()
    last_log = start
    while grbl.nl_state == 0:
        now = time.time()
        if now - last_log > 3.0:
            print(f"[spread_one_layer] waiting on nl_state: gcode_buffer_left={grbl.gcode_buffer_left}, "
                  f"motion_state={grbl.motion_state!r}, {now - start:.0f}s elapsed")
            last_log = now
        time.sleep(poll_interval)
    print(f"[spread_one_layer] nl_state reached 1, gcode_buffer_left={grbl.gcode_buffer_left}")


def compute_square_corners(cx: float, cy: float, size_mm: float):
    """Return the four (x, y) corners of a size_mm x size_mm square centered on (cx, cy).

    Single source of truth for corner math — dry-run, --verify-position, and
    real printing all call this same function.
    """
    half = size_mm / 2.0
    return [
        (cx - half, cy - half),
        (cx - half, cy + half),
        (cx + half, cy - half),
        (cx + half, cy + half),
    ]


def check_bed_fit(corners, bed_diameter_mm: float = BED_DIAMETER_MM):
    """Return a list of warning strings (never raises) if the square may not fit the bed."""
    warnings = []
    bed_radius = bed_diameter_mm / 2.0

    xs = [c[0] for c in corners]
    ys = [c[1] for c in corners]
    cx = (min(xs) + max(xs)) / 2.0
    cy = (min(ys) + max(ys)) / 2.0
    diagonal = math.hypot(max(xs) - min(xs), max(ys) - min(ys))

    if diagonal > bed_diameter_mm:
        warnings.append(
            f"Square diagonal {diagonal:.2f}mm exceeds bed diameter {bed_diameter_mm:.2f}mm"
        )

    for (x, y) in corners:
        dist = math.hypot(x - cx, y - cy)
        if dist > bed_radius:
            warnings.append(
                f"Corner ({x:.2f}, {y:.2f}) is {dist:.2f}mm from center, "
                f"exceeds bed radius {bed_radius:.2f}mm"
            )

    return warnings


def _sbr(pos_mm: float, bit_array) -> str:
    """Build one SBR command: 'SBR <b64 position in microns> <b64 bit pattern>'."""
    pos_microns = pos_mm * 1000.0
    return "SBR " + B64.B64ToSingle(pos_microns) + " " + B64.B64ToArray(bit_array)


def wait_motion_idle(grbl: GRBL, poll_interval: float = 0.1) -> None:
    grbl.StatusIndexSet()
    while True:
        time.sleep(poll_interval)
        if grbl.StatusIndexChanged() == 1 and grbl.motion_state == "idle":
            break


class HP45BufferTimeout(RuntimeError):
    """Raised when the HP45 print buffer never drains — the head has stopped
    acknowledging (OK) or has stalled, instead of silently hanging forever."""


_WRITELEFT_STALL_RESET_S = 3.0  # if inkjet_writeleft doesn't change for this long, force-unstick it
_WRITELEFT_RESET_VALUE = 900    # matches the head's observed idle buffer size


def _wait_buffer_drain(inkjet: HP45, poll_interval: float = 0.1, timeout_s: float = 30.0,
                        log_every_s: float = 5.0) -> None:
    """Wait for inkjet.BufferLeft() to reach 0, with a timeout instead of an
    unbounded wait. main.py's equivalent loops (e.g. main.py:2140) have no
    timeout at all — this is the diagnostic upgrade for calibration scripts,
    since a stalled/unresponsive head there just hangs with zero output.

    Also works around a boundary bug in SerialHP45.Update(): the send gate is
    `if inkjet_writeleft > 50`, so if the head's reported write-left ever
    lands on exactly 50 (observed in practice) the gate is permanently false
    and BufferNext() never fires again, even though nothing is actually
    wrong. If inkjet_writeleft hasn't moved for _WRITELEFT_STALL_RESET_S,
    force it back up to _WRITELEFT_RESET_VALUE to unstick the gate — this
    only touches the local Python-side estimate, not real hardware state, so
    it's a safe no-op if the head genuinely is still busy (the next status
    poll will just report the real value again).
    """
    start = time.time()
    last_log = start
    last_writeleft = inkjet.inkjet_writeleft
    last_change = start
    while inkjet.BufferLeft() > 0:
        now = time.time()
        if now - start > timeout_s:
            raise HP45BufferTimeout(
                f"HP45 buffer did not drain within {timeout_s}s "
                f"(buffer_left={inkjet.BufferLeft()}, ok_state={inkjet.ok_state}, "
                f"inkjet_writeleft={inkjet.inkjet_writeleft}). "
                f"The printhead may have stopped responding — check the connection "
                f"and try a manual Prime/Preheat from main.py before retrying."
            )

        if inkjet.inkjet_writeleft != last_writeleft:
            last_writeleft = inkjet.inkjet_writeleft
            last_change = now
        elif now - last_change > _WRITELEFT_STALL_RESET_S:
            print(f"[print_solid_square]   inkjet_writeleft stuck at {inkjet.inkjet_writeleft} "
                  f"for {now - last_change:.1f}s, forcing to {_WRITELEFT_RESET_VALUE} to unstick send gate")
            inkjet.inkjet_writeleft = _WRITELEFT_RESET_VALUE
            last_writeleft = inkjet.inkjet_writeleft
            last_change = now

        if now - last_log > log_every_s:
            print(f"[print_solid_square]   still waiting on HP45 buffer "
                  f"(buffer_left={inkjet.BufferLeft()}, ok_state={inkjet.ok_state}, "
                  f"inkjet_writeleft={inkjet.inkjet_writeleft}, {now - start:.0f}s elapsed)")
            last_log = now
        time.sleep(poll_interval)


def print_solid_square(grbl: GRBL, inkjet: HP45, cx: float, cy: float, size_mm: float,
                        dpi: int, density: int, passes: int,
                        print_speed: float, travel_speed: float) -> None:
    """Print a solid square centered on (cx, cy), matching the sweep algorithm in
    main.py's _run_calibration_inner / _print_single_config_layer.

    Direct pixel/sweep math — no SVG, no ImageConverter, no image array.
    Sweeps from max-X toward min-X (same convention as the production path).
    Repeats the full sweep set `passes` times, matching _print_single_config_layer's
    `for _pass in range(self.layer_passes)` wrapper (unlike the single-pass
    _run_calibration_inner).
    """
    inkjet.SetDPI(dpi)
    inkjet.SetDensity(density)

    printing_sweep_size = dpi // 2
    pixel_to_pos_multiplier = 25.4 / dpi

    half_mm = size_mm / 2.0
    square_width_px = int(round(size_mm * dpi / 25.4))

    sweeps = square_width_px // printing_sweep_size
    if square_width_px % printing_sweep_size != 0:
        sweeps += 1

    # square is uniform, so a single burst covers the whole Y span of every strip
    y_min_mm = cy - half_mm
    y_max_mm = cy + half_mm

    for _pass in range(passes):
        sweep_x_pix = square_width_px - printing_sweep_size  # start at max-X
        for sweep_i in range(sweeps):
            # last (min-X) strip is partial when sweep_x_pix goes negative — h < 0 slots
            # are off, matching how _print_single_config_layer/_run_calibration_inner
            # treat h < 0 as off. temp_counter (array index) increases alongside h, so
            # the off slots are the leading ones (low index), not the trailing ones.
            leading_off = max(-sweep_x_pix, 0)  # nozzle slots at h < 0, forced off
            sweep_x_pos = cx - half_mm + (sweep_x_pix * pixel_to_pos_multiplier)

            y_start_pos = y_min_mm
            y_end_pos = y_max_mm

            print(f"[print_solid_square] pass {_pass + 1}/{passes} sweep {sweep_i + 1}/{sweeps} "
                  f"(sweep_x_pix={sweep_x_pix})")

            # fill inkjet buffer: off-cap, one burst covering the strip's real width, off-cap
            full_bit_array = [0] * leading_off + [1] * (printing_sweep_size - leading_off)
            zero_bit_array = [0] * printing_sweep_size

            inkjet.SerialWriteBufferRaw(_sbr(y_start_pos - pixel_to_pos_multiplier, zero_bit_array))
            inkjet.SerialWriteBufferRaw(_sbr(y_start_pos, full_bit_array))
            inkjet.SerialWriteBufferRaw(_sbr(y_end_pos + pixel_to_pos_multiplier, zero_bit_array))

            print(f"[print_solid_square]   moving to sweep start ({sweep_x_pos:.2f}, {y_start_pos:.2f})")
            grbl.SerialGotoXY(sweep_x_pos, y_start_pos, travel_speed)
            wait_motion_idle(grbl)

            print(f"[print_solid_square]   waiting for HP45 buffer drain (buffer_left={inkjet.BufferLeft()})")
            _wait_buffer_drain(inkjet)

            time.sleep(0.3)
            inkjet.SetPosition(int(grbl.motion_y_pos * 1000.0))  # one-shot sync, matches InkjetSetPosition
            time.sleep(0.2)

            print(f"[print_solid_square]   printing sweep to end ({sweep_x_pos:.2f}, {y_end_pos:.2f})")
            grbl.SerialGotoXY(sweep_x_pos, y_end_pos, print_speed)
            wait_motion_idle(grbl)

            sweep_x_pix -= printing_sweep_size

    grbl.SerialGotoHome(travel_speed)
    wait_motion_idle(grbl)


def _open_camera(cv2, camera_port: int):
    """Open and configure the camera with the confirmed settings (MJPEG, manual exposure).
    Caller is responsible for cap.release()."""
    backend = cv2.CAP_DSHOW if CAMERA_BACKEND_IS_DSHOW else 0
    cap = cv2.VideoCapture(camera_port, backend)
    if not cap.isOpened():
        raise RuntimeError(f"Could not open camera at index {camera_port}")
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, CAPTURE_WIDTH)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAPTURE_HEIGHT)
    cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, AUTO_EXPOSURE_MANUAL)
    cap.set(cv2.CAP_PROP_EXPOSURE, EXPOSURE_VALUE)
    cap.set(cv2.CAP_PROP_GAIN, GAIN_VALUE)
    return cap


def _grab_frame(cap, camera_port: int):
    frame = None
    for _ in range(LED_FLUSH_FRAMES):
        ret, f = cap.read()
        if ret:
            frame = f
    if frame is None:
        raise RuntimeError(f"Failed to read any frame from camera at index {camera_port}")
    return frame


def capture_frame(camera_port: int, led_conn=None, led_n: int = 1):
    """Open the camera with the confirmed settings, flush buffered frames, return one frame.

    If led_conn is given (from connect_led_controller()), turns on LED led_n,
    waits LED_SETTLE_MS for it to reach full brightness, captures, then turns
    all LEDs back off — otherwise captures whatever ambient light is present
    (a fully unlit build chamber will read back as a black frame).
    """
    import cv2

    cap = _open_camera(cv2, camera_port)
    try:
        if led_conn is not None:
            led_on(led_conn, led_n)
            time.sleep(LED_SETTLE_MS / 1000.0)
        try:
            return _grab_frame(cap, camera_port)
        finally:
            if led_conn is not None:
                led_all_off(led_conn)
    finally:
        cap.release()


def capture_led_sequence(camera_port: int, led_conn):
    """Open the camera once, cycle through LEDs 1..NUM_LEDS, and capture one frame per
    LED — matches archive_legacy/Density_mapping_v1.1.py's capture_led_sequence.
    Returns a list of (led_index, frame) tuples. If led_conn is None, captures a
    single unlit frame instead (led_index 0), matching that script's no-Arduino fallback.
    """
    import cv2

    cap = _open_camera(cv2, camera_port)
    try:
        led_indices = range(1, NUM_LEDS + 1) if led_conn is not None else [0]
        frames = []
        try:
            for led_n in led_indices:
                if led_n > 0:
                    led_on(led_conn, led_n)
                time.sleep(LED_SETTLE_MS / 1000.0)
                frames.append((led_n, _grab_frame(cap, camera_port)))
        finally:
            if led_conn is not None:
                led_all_off(led_conn)
        return frames
    finally:
        cap.release()


def log_row(csv_path: str, fieldnames, row: dict) -> None:
    """Append-only CSV write. Writes header only if the file doesn't exist yet."""
    os.makedirs(os.path.dirname(csv_path), exist_ok=True)
    write_header = not os.path.exists(csv_path)
    with open(csv_path, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if write_header:
            writer.writeheader()
        writer.writerow(row)


def load_progress(csv_path: str, condition_key: str = "condition_id"):
    """Return {condition_id: completed_count} from an existing CSV, or {} if none exists."""
    if not os.path.exists(csv_path):
        return {}
    counts = {}
    with open(csv_path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            cid = row.get(condition_key)
            if cid is not None:
                counts[cid] = counts.get(cid, 0) + 1
    return counts
