"""
capture_controller.py  —  Arduino LED control + Camera capture
Extracted from photostereo_capture.py for use with external UI.
"""

import cv2 as cv
import numpy as np
import threading
import time
from pathlib import Path

try:
    import serial
    import serial.tools.list_ports
    SERIAL_OK = True
except ImportError:
    SERIAL_OK = False

# ═══════════════════════════════════════════════════════════════════════════
# USER CONFIG  ← edit to match your hardware
# ═══════════════════════════════════════════════════════════════════════════

CAMERA_INDEX    = 1
CAPTURE_WIDTH   = 1920
CAPTURE_HEIGHT  = 1080

SERIAL_PORT    = "AUTO"
BAUD_RATE      = 9600
NUM_LEDS       = 5

SETTLE_MS      = 800     # ms to wait after LED turns on before capturing

IMAGE_DIR      = Path(__file__).parent / "images"

OVEREXPOSE_THRESH  = 245
UNDEREXPOSE_THRESH = 10
FOCUS_GOOD         = 150

# ═══════════════════════════════════════════════════════════════════════════


class State:
    arduino_conn   = None
    arduino_lock   = threading.Lock()
    arduino_status = "Disconnected"
    active_led     = 0

    capture_state  = "IDLE"   # IDLE | CAPTURING | DONE
    cap_log        = []

    roi_rect       = None     # (x1, y1, x2, y2) in capture pixel coords


S = State()


# ═══════════════════════════════════════════════════════════════════════════
# Arduino
# ═══════════════════════════════════════════════════════════════════════════

def _find_port():
    if not SERIAL_OK:
        return None
    keywords = ["arduino", "ch340", "ch341", "ftdi", "usb serial",
                "usb-serial", "acm", "uno"]
    for p in serial.tools.list_ports.comports():
        desc = ((p.description or "") + (p.manufacturer or "")).lower()
        if any(k in desc for k in keywords):
            return p.device
    ports = serial.tools.list_ports.comports()
    return ports[0].device if ports else None


def arduino_connect(port="AUTO"):
    if not SERIAL_OK:
        S.arduino_status = "pyserial not installed — run: pip install pyserial"
        return
    target = _find_port() if port == "AUTO" else port
    if not target:
        S.arduino_status = "No serial port found"
        return
    try:
        conn = serial.Serial(target, BAUD_RATE, timeout=1)
        time.sleep(2.0)
        conn.reset_input_buffer()
        with S.arduino_lock:
            S.arduino_conn = conn
        S.arduino_status = f"OK: {target}"
        print(f"[Arduino] Connected on {target}")
    except Exception as exc:
        S.arduino_status = f"Error: {exc}"
        print(f"[Arduino] {S.arduino_status}")


def _send(cmd: str):
    with S.arduino_lock:
        if S.arduino_conn and S.arduino_conn.is_open:
            S.arduino_conn.write(cmd.encode())


def led_on(n: int):
    _send(str(n))
    S.active_led = n


def all_leds_off():
    _send("0")
    S.active_led = 0


def arduino_reset():
    with S.arduino_lock:
        connected = S.arduino_conn and S.arduino_conn.is_open
    if connected:
        _send("r")
        S.active_led = 0
    else:
        S.arduino_status = "Reconnecting..."
        threading.Thread(target=arduino_connect, args=(SERIAL_PORT,),
                         daemon=True).start()


# ═══════════════════════════════════════════════════════════════════════════
# Image metrics
# ═══════════════════════════════════════════════════════════════════════════

def focus_score(gray):
    return float(cv.Laplacian(gray, cv.CV_64F).var())


def exposure_stats(gray):
    n     = gray.size
    over  = np.sum(gray >= OVEREXPOSE_THRESH)  / n * 100.0
    under = np.sum(gray <= UNDEREXPOSE_THRESH) / n * 100.0
    return float(gray.mean()), float(over), float(under)


# ═══════════════════════════════════════════════════════════════════════════
# Camera open
# ═══════════════════════════════════════════════════════════════════════════

def open_camera(index=CAMERA_INDEX):
    """Open camera with 2-phase warm-up for Windows MSMF driver compatibility.
    Returns (VideoCapture, first_frame) or None on failure."""
    def _try_open(idx):
        warmup = cv.VideoCapture(idx)
        if not warmup.isOpened():
            return None
        time.sleep(5.0)
        warmed = False
        for _ in range(20):
            try:
                ok, _ = warmup.read()
                if ok:
                    warmed = True
                    break
            except cv.error:
                pass
            time.sleep(0.5)
        warmup.release()
        if not warmed:
            return None
        time.sleep(0.5)

        c = cv.VideoCapture(idx)
        if not c.isOpened():
            return None
        if CAPTURE_WIDTH and CAPTURE_HEIGHT:
            c.set(cv.CAP_PROP_FRAME_WIDTH,  CAPTURE_WIDTH)
            c.set(cv.CAP_PROP_FRAME_HEIGHT, CAPTURE_HEIGHT)
        c.set(cv.CAP_PROP_BUFFERSIZE, 1)
        time.sleep(1.5)
        for _ in range(15):
            try:
                ok, f = c.read()
                if ok and f is not None and f.size > 0:
                    return (c, f)
            except cv.error:
                pass
            time.sleep(0.3)
        c.release()
        return None

    result = _try_open(index)
    if result is None:
        print(f"[Camera] index={index} failed, scanning for working camera...")
        for idx in range(6):
            if idx == index:
                continue
            result = _try_open(idx)
            if result is not None:
                print(f"[Camera] Using index {idx} as fallback")
                break
    return result


# ═══════════════════════════════════════════════════════════════════════════
# Capture sequence  (runs in a background thread)
# ═══════════════════════════════════════════════════════════════════════════

def run_capture_sequence(cap):
    """Fire each LED in order, capture a frame, and save to IMAGE_DIR.
    Call this in a daemon thread — it updates S.capture_state and S.cap_log."""
    IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    S.capture_state = "CAPTURING"
    S.cap_log.clear()

    for i in range(1, NUM_LEDS + 1):
        led_on(i)
        time.sleep(SETTLE_MS / 1000.0)

        for _ in range(2):
            cap.grab()
        ret, frame = cap.retrieve()
        if not ret:
            S.cap_log.append(f"LED{i}: CAPTURE FAILED")
            continue

        out = frame
        if S.roi_rect:
            x1, y1, x2, y2 = S.roi_rect
            out = frame[y1:y2, x1:x2]

        fname = IMAGE_DIR / f"led{i}.jpg"
        cv.imwrite(str(fname), out)

        gray = cv.cvtColor(out, cv.COLOR_BGR2GRAY)
        fs   = focus_score(gray)
        mean, over, _ = exposure_stats(gray)
        tag  = "OK" if (fs >= FOCUS_GOOD and over < 2.0) else "WARN"
        entry = f"LED{i} f={fs:.0f} b={mean:.0f} {tag}"
        S.cap_log.append(entry)
        print(f"[Capture] {entry}  → {fname.name}")

    all_leds_off()
    S.capture_state = "DONE"
    print(f"[Capture] Complete — images in {IMAGE_DIR}")


def start_capture_sequence(cap):
    """Convenience wrapper: starts run_capture_sequence in a daemon thread."""
    if S.capture_state == "CAPTURING":
        return
    S.cap_log.clear()
    threading.Thread(target=run_capture_sequence, args=(cap,), daemon=True).start()
