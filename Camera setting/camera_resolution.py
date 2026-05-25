"""
camera_resolution.py — Live camera viewer with full UVC control.
Run: python camera_resolution.py
"""

import sys
import cv2
import numpy as np
from PyQt5 import QtCore, QtGui, QtWidgets


PROBE_RESOLUTIONS = [
    (640,   360),
    (640,   480),
    (800,   600),
    (1024,  576),
    (1280,  720),
    (1280,  960),
    (1920, 1080),
    (2560, 1440),
    (3840, 2160),
    (8000, 6000),
]


def _spin(label, lo, hi, default, step=1, decimals=0):
    """Helper: returns (QLabel, QSpinBox-or-QDoubleSpinBox)."""
    lbl = QtWidgets.QLabel(label)
    if decimals:
        sb = QtWidgets.QDoubleSpinBox()
        sb.setDecimals(decimals)
        sb.setSingleStep(step)
    else:
        sb = QtWidgets.QSpinBox()
        sb.setSingleStep(step)
    sb.setRange(lo, hi)
    sb.setValue(default)
    sb.setFixedWidth(80)
    return lbl, sb


class CameraViewer(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Camera Viewer")
        self.cap = None
        self._frame_buffer = []   # for frame averaging
        self._build_ui()
        self._populate_cameras()

        self.timer = QtCore.QTimer()
        self.timer.timeout.connect(self._update_frame)

    # ------------------------------------------------------------------
    def _build_ui(self):
        root = QtWidgets.QVBoxLayout(self)

        # ── row 1: camera + resolution ─────────────────────────────────
        row1 = QtWidgets.QHBoxLayout()

        self.camera_combo = QtWidgets.QComboBox()
        self.camera_combo.setMinimumWidth(180)
        self.refresh_btn = QtWidgets.QPushButton("Refresh")
        self.refresh_btn.clicked.connect(self._populate_cameras)

        self.res_combo = QtWidgets.QComboBox()
        self.res_combo.setMinimumWidth(140)

        self.apply_res_btn = QtWidgets.QPushButton("Apply Res")
        self.apply_res_btn.clicked.connect(self._apply_resolution)

        self.open_btn = QtWidgets.QPushButton("Open Camera")
        self.open_btn.setCheckable(True)
        self.open_btn.clicked.connect(self._toggle_camera)

        self.capture_btn = QtWidgets.QPushButton("Capture")
        self.capture_btn.clicked.connect(self._capture)
        self.capture_btn.setEnabled(False)

        for w in (QtWidgets.QLabel("Camera:"), self.camera_combo, self.refresh_btn,
                  QtWidgets.QLabel("  Res:"), self.res_combo, self.apply_res_btn,
                  self.open_btn, self.capture_btn):
            row1.addWidget(w)
        row1.addStretch()
        root.addLayout(row1)

        # ── row 2: UVC controls ────────────────────────────────────────
        grp = QtWidgets.QGroupBox("Camera Controls")
        form = QtWidgets.QFormLayout(grp)
        form.setFieldGrowthPolicy(QtWidgets.QFormLayout.ExpandingFieldsGrow)

        # Format
        self.fmt_combo = QtWidgets.QComboBox()
        self.fmt_combo.addItem("MJPEG", cv2.VideoWriter_fourcc(*"MJPG"))
        self.fmt_combo.addItem("YUY2",  cv2.VideoWriter_fourcc(*"YUY2"))
        form.addRow("Format:", self.fmt_combo)

        # FPS
        _, self.fps_spin = _spin("", 1, 120, 1)
        fps_apply = QtWidgets.QPushButton("Apply")
        fps_apply.setFixedWidth(55)
        fps_apply.clicked.connect(self._apply_fps)
        fps_row = QtWidgets.QHBoxLayout()
        fps_row.addWidget(self.fps_spin)
        fps_row.addWidget(fps_apply)
        fps_row.addStretch()
        form.addRow("FPS:", fps_row)

        # Autofocus toggle + manual focus
        self.af_chk = QtWidgets.QCheckBox("Autofocus")
        self.af_chk.setChecked(True)
        self.af_chk.toggled.connect(self._apply_focus_mode)
        _, self.focus_spin = _spin("", 0, 1023, 0)
        focus_apply = QtWidgets.QPushButton("Apply")
        focus_apply.setFixedWidth(55)
        focus_apply.clicked.connect(self._apply_focus)
        focus_row = QtWidgets.QHBoxLayout()
        focus_row.addWidget(self.af_chk)
        focus_row.addWidget(QtWidgets.QLabel("  Manual:"))
        focus_row.addWidget(self.focus_spin)
        focus_row.addWidget(focus_apply)
        focus_row.addStretch()
        form.addRow("Focus:", focus_row)

        # Auto-exposure toggle + manual exposure
        self.ae_chk = QtWidgets.QCheckBox("Auto Exposure")
        self.ae_chk.setChecked(True)
        self.ae_chk.toggled.connect(self._apply_exposure_mode)
        _, self.exp_spin = _spin("", 1, 10000, 500)
        exp_apply = QtWidgets.QPushButton("Apply")
        exp_apply.setFixedWidth(55)
        exp_apply.clicked.connect(self._apply_exposure)
        exp_row = QtWidgets.QHBoxLayout()
        exp_row.addWidget(self.ae_chk)
        exp_row.addWidget(QtWidgets.QLabel("  Manual:"))
        exp_row.addWidget(self.exp_spin)
        exp_row.addWidget(exp_apply)
        exp_row.addStretch()
        form.addRow("Exposure:", exp_row)

        # Gain
        _, self.gain_spin = _spin("", 0, 1023, 0)
        gain_apply = QtWidgets.QPushButton("Apply")
        gain_apply.setFixedWidth(55)
        gain_apply.clicked.connect(self._apply_gain)
        gain_row = QtWidgets.QHBoxLayout()
        gain_row.addWidget(self.gain_spin)
        gain_row.addWidget(gain_apply)
        gain_row.addStretch()
        form.addRow("Gain:", gain_row)

        # Frame averaging
        _, self.avg_spin = _spin("", 1, 32, 1)
        form.addRow("Frame avg (N):", self.avg_spin)

        root.addWidget(grp)

        # ── live view ─────────────────────────────────────────────────
        self.view = QtWidgets.QLabel("No camera open")
        self.view.setAlignment(QtCore.Qt.AlignCenter)
        self.view.setMinimumSize(800, 500)
        self.view.setStyleSheet("background:#111; color:#aaa; font-size:16px;")
        root.addWidget(self.view, stretch=1)

        # ── status ────────────────────────────────────────────────────
        self.status = QtWidgets.QLabel("Ready")
        root.addWidget(self.status)

    # ------------------------------------------------------------------
    def _populate_cameras(self):
        self.camera_combo.blockSignals(True)
        self.camera_combo.clear()
        for i in range(8):
            cap = cv2.VideoCapture(i, cv2.CAP_DSHOW)
            if cap.isOpened():
                name = cap.getBackendName() or f"Camera {i}"
                cap.release()
                self.camera_combo.addItem(f"[{i}] {name}", i)
        self.camera_combo.blockSignals(False)
        if self.camera_combo.count() == 0:
            self.camera_combo.addItem("No cameras found", -1)

    def _probe_resolutions(self, index):
        seen = []
        for (w, h) in PROBE_RESOLUTIONS:
            cap = cv2.VideoCapture(index, cv2.CAP_DSHOW)
            if not cap.isOpened():
                break
            cap.set(cv2.CAP_PROP_FOURCC,        cv2.VideoWriter_fourcc(*"MJPG"))
            cap.set(cv2.CAP_PROP_FRAME_WIDTH,   w)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT,  h)
            aw = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            ah = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            cap.release()
            if (aw, ah) not in seen:
                seen.append((aw, ah))
        return seen

    # ------------------------------------------------------------------
    def _toggle_camera(self, checked):
        if checked:
            self._open_camera()
        else:
            self._close_camera()

    def _open_camera(self):
        idx = self.camera_combo.currentData()
        if idx is None or idx < 0:
            self.open_btn.setChecked(False)
            return

        self.status.setText("Probing resolutions…")
        QtWidgets.QApplication.processEvents()
        resolutions = self._probe_resolutions(idx)
        self.res_combo.clear()
        for (w, h) in resolutions:
            self.res_combo.addItem(f"{w} x {h}", (w, h))

        self.cap = cv2.VideoCapture(idx, cv2.CAP_DSHOW)
        if not self.cap.isOpened():
            self.status.setText(f"Failed to open camera {idx}")
            self.open_btn.setChecked(False)
            self.cap = None
            return

        self._apply_format_and_resolution()

        fps = int(self.fps_spin.value())
        interval = max(33, int(1000 / fps))
        self.timer.start(interval)

        self.open_btn.setText("Close Camera")
        self.capture_btn.setEnabled(True)
        self.status.setText(f"Camera {idx} opened")

    def _close_camera(self):
        self.timer.stop()
        if self.cap:
            self.cap.release()
            self.cap = None
        self._frame_buffer.clear()
        self.view.setText("No camera open")
        self.open_btn.setText("Open Camera")
        self.capture_btn.setEnabled(False)
        self.status.setText("Camera closed")

    # ------------------------------------------------------------------
    def _apply_format_and_resolution(self, silent=False):
        if not self.cap:
            return
        fourcc = self.fmt_combo.currentData()
        self.cap.set(cv2.CAP_PROP_FOURCC, fourcc)
        data = self.res_combo.currentData()
        if data:
            w, h = data
            # explicit 8000×6000 or any res
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH,  w)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, h)
        aw = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        ah = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        if not silent:
            self.status.setText(f"Format/res applied → {aw} x {ah}")

    def _apply_resolution(self):
        self._apply_format_and_resolution(silent=False)

    def _apply_fps(self, silent=False):
        if not self.cap:
            return
        fps = int(self.fps_spin.value())
        self.cap.set(cv2.CAP_PROP_FPS, fps)
        actual = self.cap.get(cv2.CAP_PROP_FPS)
        interval = max(33, int(1000 / max(fps, 1)))
        self.timer.setInterval(interval)
        if not silent:
            self.status.setText(f"FPS set → requested {fps}, actual {actual:.1f}")

    def _apply_focus_mode(self, auto, silent=False):
        if not self.cap:
            return
        # 0 = manual, 1 = auto  (CAP_PROP_AUTOFOCUS)
        self.cap.set(cv2.CAP_PROP_AUTOFOCUS, 1 if auto else 0)
        self.focus_spin.setEnabled(not auto)
        if not auto:
            self._apply_focus(silent=True)
        if not silent:
            self.status.setText(f"Autofocus {'ON' if auto else 'OFF (manual)'}")

    def _apply_focus(self, silent=False):
        if not self.cap:
            return
        val = self.focus_spin.value()
        self.cap.set(cv2.CAP_PROP_FOCUS, val)
        if not silent:
            self.status.setText(f"Focus set → {val}")

    def _apply_exposure_mode(self, auto, silent=False):
        if not self.cap:
            return
        # DirectShow: 1 = manual, 3 = auto
        self.cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 3 if auto else 1)
        self.exp_spin.setEnabled(not auto)
        if not auto:
            self._apply_exposure(silent=True)
        if not silent:
            self.status.setText(f"Auto-exposure {'ON' if auto else 'OFF (manual)'}")

    def _apply_exposure(self, silent=False):
        if not self.cap:
            return
        val = self.exp_spin.value()
        self.cap.set(cv2.CAP_PROP_EXPOSURE, val)
        if not silent:
            self.status.setText(f"Exposure set → {val}")

    def _apply_gain(self, silent=False):
        if not self.cap:
            return
        val = self.gain_spin.value()
        self.cap.set(cv2.CAP_PROP_GAIN, val)
        if not silent:
            self.status.setText(f"Gain set → {val}")

    # ------------------------------------------------------------------
    def _update_frame(self):
        if not self.cap:
            return
        ret, frame = self.cap.read()
        if not ret:
            return

        n = max(1, int(self.avg_spin.value()))
        if n > 1:
            self._frame_buffer.append(frame.astype(np.float32))
            if len(self._frame_buffer) > n:
                self._frame_buffer.pop(0)
            frame = np.mean(self._frame_buffer, axis=0).astype(np.uint8)
        else:
            self._frame_buffer.clear()

        h, w, ch = frame.shape
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        img = QtGui.QImage(rgb.data, w, h, ch * w, QtGui.QImage.Format_RGB888)
        pix = QtGui.QPixmap.fromImage(img).scaled(
            self.view.size(), QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation
        )
        self.view.setPixmap(pix)
        self.status.setText(f"Live  {w} x {h}  |  avg={len(self._frame_buffer)}/{n}")

    # ------------------------------------------------------------------
    def _capture(self):
        """Capture: accumulate N frames and save the average."""
        if not self.cap:
            return
        n = max(1, int(self.avg_spin.value()))
        self.status.setText(f"Capturing {n} frame(s)…")
        QtWidgets.QApplication.processEvents()

        frames = []
        for _ in range(n):
            ret, frame = self.cap.read()
            if ret:
                frames.append(frame.astype(np.float32))

        if not frames:
            self.status.setText("Capture failed.")
            return

        result = np.mean(frames, axis=0).astype(np.uint8)

        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Save capture", "capture.png", "PNG (*.png);;JPEG (*.jpg)"
        )
        if path:
            cv2.imwrite(path, result)
            self.status.setText(f"Saved {result.shape[1]}x{result.shape[0]} → {path}")

    def closeEvent(self, event):
        self._close_camera()
        event.accept()


if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    win = CameraViewer()
    win.resize(960, 800)
    win.show()
    sys.exit(app.exec_())
