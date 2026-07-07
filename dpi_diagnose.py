"""
Run this on the machine where the UI looks broken and send back the printed output.

Reports: OS-reported DPI/scale, what Qt thinks the scale factor is, and
whether SetProcessDpiAwareness actually took effect -- so we stop guessing
at the cause and look at what that machine is actually doing.

Usage:
    python dpi_diagnose.py        # awareness=1 (system aware, current app behavior)
    python dpi_diagnose.py 2      # awareness=2 (per-monitor aware, to compare)
"""
import sys

requested_awareness = int(sys.argv[1]) if len(sys.argv) > 1 else 1
print(f"Requesting DPI awareness level: {requested_awareness}")

print("=== OS-level DPI (via ctypes, before Qt) ===")
if sys.platform == "win32":
    import ctypes
    try:
        awareness = ctypes.c_int()
        ctypes.windll.shcore.GetProcessDpiAwareness(0, ctypes.byref(awareness))
        print(f"Process DPI awareness before SetProcessDpiAwareness: {awareness.value} "
              f"(0=unaware, 1=system-aware, 2=per-monitor-aware)")
    except Exception as e:
        print(f"GetProcessDpiAwareness failed: {e}")

    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(requested_awareness)
        ctypes.windll.shcore.GetProcessDpiAwareness(0, ctypes.byref(awareness))
        print(f"Process DPI awareness after SetProcessDpiAwareness({requested_awareness}): {awareness.value}")
    except Exception as e:
        print(f"SetProcessDpiAwareness failed: {e}")

    try:
        hdc = ctypes.windll.user32.GetDC(0)
        LOGPIXELSX = 88
        dpi = ctypes.windll.gdi32.GetDeviceCaps(hdc, LOGPIXELSX)
        ctypes.windll.user32.ReleaseDC(0, hdc)
        print(f"System DPI (GetDeviceCaps LOGPIXELSX): {dpi}  (96 = 100%% scale)")
    except Exception as e:
        print(f"GetDeviceCaps failed: {e}")
else:
    print("Not on Windows, skipping ctypes checks.")

print()
print("=== Qt-level DPI (after QApplication is created) ===")
from PyQt5 import QtCore, QtWidgets, QtGui

QtWidgets.QApplication.setAttribute(QtCore.Qt.AA_EnableHighDpiScaling, True)
QtWidgets.QApplication.setAttribute(QtCore.Qt.AA_UseHighDpiPixmaps, True)
app = QtWidgets.QApplication(sys.argv)

screen = app.primaryScreen()
print(f"PyQt version: {QtCore.PYQT_VERSION_STR}, Qt version: {QtCore.QT_VERSION_STR}")
print(f"screen.devicePixelRatio(): {screen.devicePixelRatio()}")
print(f"screen.logicalDotsPerInch(): {screen.logicalDotsPerInch()}")
print(f"screen.physicalDotsPerInch(): {screen.physicalDotsPerInch()}")
print(f"screen.geometry(): {screen.geometry()}")
print(f"app.devicePixelRatio() [deprecated but informative]: "
      f"{getattr(app, 'devicePixelRatio', lambda: 'n/a')()}")

# Render a label with the same 32px font the real UI uses and report its
# actual on-screen box, so we can see whether Qt is scaling text/layout together.
label = QtWidgets.QLabel("Test 테스트 32px")
label.setStyleSheet("font-size: 32px;")
label.adjustSize()
print(f"QLabel with font-size:32px -> sizeHint: {label.sizeHint()}, "
      f"font().pointSize(): {label.font().pointSize()}, "
      f"font().pixelSize(): {label.font().pixelSize()}")

print()
print("Copy everything above and send it back.")
