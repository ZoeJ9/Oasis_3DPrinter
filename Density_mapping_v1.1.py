# Oasis controller is the software used to control the HP45 and GRBL driver in Oasis
# Copyright (C) 2018  Yvo de Haas

# Oasis controller is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

# Oasis controller is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with Oasis controller.  If not, see <https://www.gnu.org/licenses/>.


import sys
import glob

from PyQt5 import uic
from PyQt5.QtWidgets import QApplication
from PyQt5 import QtCore, QtGui, QtWidgets
from PyQt5.QtWidgets import QFileDialog
from PyQt5.QtWidgets import QMessageBox, QComboBox, QLabel
from PyQt5.QtGui import QPixmap, QColor, QImage
from SerialGRBL import GRBL
from SerialHP45 import HP45
import os
from ImageConverter import ImageConverter
import B64
_builtin_min = min  # preserved before `from numpy import *` shadows it below
_builtin_max = max
from numpy import *
import math
import threading
import time
import serial

# a small note on threading. It is used so some of the functions update automatically (serial GRBL and inkjet)
# however, it is a bit of a lie. If python is busy in one thread, it will quietly ignore the others
# sleep commands will give enough room that python works on other threads.
# this is the reason why sending inkjet while moving is difficult. Will fix later, with another attempt

import cv2 as _cv2_global
from config_runner import ConfigRunner

# CAMERA SETTINGS — validated for 175mm bed setup
# ============================================================
CAMERA_INDEX          = 0
BACKEND               = _cv2_global.CAP_DSHOW

RESOLUTION_FULL       = (8000, 6000)   # 48MP, ~1.3 fps, requires MJPEG
RESOLUTION_PREVIEW    = (1920, 1080)   # fast preview / focusing, 30 fps

AUTO_EXPOSURE_MANUAL  = 0.25           # Windows DSHOW: 0.25=manual, 0.75=auto
EXPOSURE_VALUE        = -3             # log2(seconds). -3 = 1/8s
GAIN_VALUE            = 0
AUTO_WB               = 0             # 0 = manual lock

WARMUP_FRAMES         = 0

AVERAGING_FRAMES      = 1             # noise reduction (1 = off)
UNSHARP_SIGMA         = 2.5
UNSHARP_AMOUNT        = 1.2           # 0 = sharpening off
# ============================================================


# --- INSERTION: New Camera Controller Class ---

LED_SETTLE_MS    = 200  # ms to wait after each LED turns on before capturing
NUM_LEDS         = 5    # number of Arduino-controlled LEDs
LED_FLUSH_FRAMES = 2    # cap.grab() count before retrieve to flush stale frames


class CameraController(QtWidgets.QWidget):
    # Signal to update the UI from the printer thread safely
    update_image_signal = QtCore.pyqtSignal(object)
    # Signal to reset the preview button from a background thread safely
    _preview_done_signal = QtCore.pyqtSignal()

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Oasis Camera View")
        self.resize(600, 550)

        # Default Settings
        self.camera_port = 0
        self.pause_time = 0.0  # Total time to pause for photo (seconds)
        self.output_dir = os.path.join(os.getcwd(), "timelapse_output")
        self.camera_enabled = True
        self.exposure_value = EXPOSURE_VALUE  # log2(s), controlled by UI spinbox
        self._camera_list = []  # list of {"index": int, "name": str}
        self._last_frame_rgb = None  # most recent captured frame, for the zoom view

        # Arduino LED controller state
        self._arduino_conn   = None
        self._arduino_lock   = threading.Lock()
        self._arduino_port   = None   # str, e.g. "COM5"
        self.led_enabled     = False  # True when Arduino is connected
        self.capture_width   = 3840
        self.capture_height  = 2160

        # Ensure output directory exists
        if not os.path.exists(self.output_dir):
            os.makedirs(self.output_dir)

        # --- UI Layout: single vertical column ---
        root_layout = QtWidgets.QVBoxLayout()
        root_layout.setContentsMargins(8, 8, 8, 8)
        root_layout.setSpacing(6)

        # ── Camera feed ───────────────────────────────────────────────────────
        feed_group = QtWidgets.QGroupBox("Camera Feed")
        feed_layout = QtWidgets.QVBoxLayout(feed_group)
        self.image_label = QLabel("No Image Captured")
        self.image_label.setAlignment(QtCore.Qt.AlignCenter)
        self.image_label.setMinimumSize(480, 360)
        self.image_label.setStyleSheet("border: 2px solid #cbd5e1; border-radius: 6px; background-color: #0f172a; color: #94a3b8;")
        self.image_label.setCursor(QtCore.Qt.PointingHandCursor)
        self.image_label.setToolTip("Click to view full size")
        self.image_label.mousePressEvent = self._open_zoom_view
        feed_layout.addWidget(self.image_label)
        root_layout.addWidget(feed_group, stretch=1)

        # ── Acquisition ───────────────────────────────────────────────────────
        acq_group = QtWidgets.QGroupBox("Acquisition")
        acq_layout = QtWidgets.QGridLayout(acq_group)
        acq_layout.setSpacing(6)

        self.enable_chk = QtWidgets.QCheckBox("Enable Camera")
        self.enable_chk.setChecked(self.camera_enabled)
        self.enable_chk.toggled.connect(self.set_enabled)
        acq_layout.addWidget(self.enable_chk, 0, 0, 1, 2)

        acq_layout.addWidget(QtWidgets.QLabel("Output Dir:"), 1, 0)
        dir_row = QtWidgets.QHBoxLayout()
        self.dir_edit = QtWidgets.QLineEdit(self.output_dir)
        self.dir_edit.textChanged.connect(self.set_dir)
        self.dir_btn = QtWidgets.QPushButton("...")
        self.dir_btn.setFixedWidth(40)
        self.dir_btn.clicked.connect(self.browse_dir)
        dir_row.addWidget(self.dir_edit)
        dir_row.addWidget(self.dir_btn)
        acq_layout.addLayout(dir_row, 1, 1)

        acq_layout.addWidget(QtWidgets.QLabel("Pause Time (s):"), 2, 0)
        self.pause_spin = QtWidgets.QDoubleSpinBox()
        self.pause_spin.setValue(self.pause_time)
        self.pause_spin.setRange(0.0, 60.0)
        self.pause_spin.setSingleStep(0.5)
        self.pause_spin.valueChanged.connect(self.set_pause)
        acq_layout.addWidget(self.pause_spin, 2, 1)

        self.preview_btn = QtWidgets.QPushButton("Preview")
        self.preview_btn.setToolTip("Capture a single frame from the camera and display it")
        self.preview_btn.clicked.connect(self._preview_capture)
        acq_layout.addWidget(self.preview_btn, 3, 0, 1, 2)

        root_layout.addWidget(acq_group)

        # ── Settings ──────────────────────────────────────────────────────────
        settings_group = QtWidgets.QGroupBox("Settings")
        form_layout = QtWidgets.QFormLayout(settings_group)
        form_layout.setFieldGrowthPolicy(QtWidgets.QFormLayout.ExpandingFieldsGrow)
        form_layout.setSpacing(8)

        cam_row = QtWidgets.QHBoxLayout()
        self.port_combo = QtWidgets.QComboBox()
        self.port_combo.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        self.port_combo.setToolTip("Select camera by name")
        self.port_combo.currentIndexChanged.connect(self._on_camera_selected)
        self.refresh_btn = QtWidgets.QPushButton("↺")
        self.refresh_btn.setFixedWidth(36)
        self.refresh_btn.clicked.connect(self._populate_cameras)
        cam_row.addWidget(self.port_combo)
        cam_row.addWidget(self.refresh_btn)
        form_layout.addRow("Camera:", cam_row)
        self._populate_cameras()

        self.exposure_spin = QtWidgets.QSpinBox()
        self.exposure_spin.setRange(-7, -1)
        self.exposure_spin.setValue(self.exposure_value)
        self.exposure_spin.setSuffix("  (log₂ s)")
        self.exposure_spin.setToolTip("Camera exposure: -3 = 1/8s, -6 = 1/64s")
        self.exposure_spin.valueChanged.connect(lambda v: setattr(self, "exposure_value", v))
        form_layout.addRow("Exposure:", self.exposure_spin)

        self.resolution_combo = QtWidgets.QComboBox()
        self._resolutions = [
            ("3840 x 2160 (4K)", 3840, 2160),
            ("1920 x 1080 (FHD)", 1920, 1080),
            ("1280 x 720 (HD)", 1280, 720),
        ]
        for label, w, h in self._resolutions:
            self.resolution_combo.addItem(label, (w, h))
        self.resolution_combo.currentIndexChanged.connect(self._on_resolution_changed)
        form_layout.addRow("Capture Res:", self.resolution_combo)

        arduino_row = QtWidgets.QHBoxLayout()
        self.arduino_port_combo = QtWidgets.QComboBox()
        self.arduino_port_combo.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        self.arduino_port_combo.setToolTip("Serial port for Arduino LED controller")
        self._populate_serial_ports()
        self.arduino_connect_btn = QtWidgets.QPushButton("Connect")
        self.arduino_connect_btn.setFixedWidth(70)
        self.arduino_connect_btn.clicked.connect(self._arduino_connect_clicked)
        arduino_row.addWidget(self.arduino_port_combo)
        arduino_row.addWidget(self.arduino_connect_btn)
        form_layout.addRow("LED Controller:", arduino_row)
        self.arduino_status_lbl = QtWidgets.QLabel("Disconnected")
        self.arduino_status_lbl.setStyleSheet("color: grey;")
        form_layout.addRow("", self.arduino_status_lbl)

        self.calib_status_label = QtWidgets.QLabel("● Unknown")
        self.calib_status_label.setStyleSheet("color: grey;")
        form_layout.addRow("Calibration:", self.calib_status_label)
        self.btn_run_calibration = QtWidgets.QPushButton("Run Calibration")
        form_layout.addRow("", self.btn_run_calibration)

        root_layout.addWidget(settings_group)

        self.setLayout(root_layout)

        # Connect the signal to the UI update slot
        self.update_image_signal.connect(self.update_display_slot)
        self._preview_done_signal.connect(self._reset_preview_button)

    # --- Serial port enumeration (for Arduino combo) ---
    def _populate_serial_ports(self):
        import glob as _glob
        self.arduino_port_combo.clear()
        if sys.platform.startswith("win"):
            ports = ["COM%s" % (i + 1) for i in range(256)]
        elif sys.platform.startswith("linux") or sys.platform.startswith("cygwin"):
            ports = _glob.glob("/dev/tty[A-Za-z]*")
        else:
            ports = _glob.glob("/dev/tty.*")
        result = []
        for p in ports:
            try:
                s = serial.Serial(p)
                s.close()
                result.append(p)
            except (OSError, serial.SerialException):
                pass
        self.arduino_port_combo.addItems(result if result else ["(none)"])

    def _arduino_connect_clicked(self):
        port = self.arduino_port_combo.currentText()
        if port == "(none)" or not port:
            return
        threading.Thread(target=self._arduino_connect, args=(port,), daemon=True).start()

    def _arduino_connect(self, port: str):
        try:
            conn = serial.Serial(port, 9600, timeout=1)
            time.sleep(2.0)
            conn.reset_input_buffer()
            with self._arduino_lock:
                if self._arduino_conn and self._arduino_conn.is_open:
                    self._arduino_conn.close()
                self._arduino_conn = conn
                self._arduino_port = port
            self.led_enabled = True
            self.arduino_status_lbl.setText(f"OK: {port}")
            self.arduino_status_lbl.setStyleSheet("color: green; font-weight: bold;")
            print(f"[Arduino] Connected on {port}")
        except Exception as exc:
            self.led_enabled = False
            self.arduino_status_lbl.setText(f"Error: {exc}")
            self.arduino_status_lbl.setStyleSheet("color: red;")
            print(f"[Arduino] Connect failed: {exc}")

    def _led_send(self, cmd: str):
        with self._arduino_lock:
            if self._arduino_conn and self._arduino_conn.is_open:
                self._arduino_conn.write(cmd.encode())

    def _led_on(self, n: int):
        """Turn on LED n (1-indexed)."""
        self._led_send(str(n))

    def _led_all_off(self):
        self._led_send("0")

    # --- Camera enumeration ---
    def _populate_cameras(self):
        import cv2
        self._camera_list = []
        for i in range(8):
            cap = cv2.VideoCapture(i, cv2.CAP_DSHOW)
            if cap.isOpened():
                name = cap.getBackendName() or f"Camera {i}"
                cap.release()
                self._camera_list.append({"index": i, "name": f"{name} (index {i})"})
        self.port_combo.blockSignals(True)
        self.port_combo.clear()
        if self._camera_list:
            for cam in self._camera_list:
                self.port_combo.addItem(cam["name"], cam["index"])
            # restore previous selection if still available
            for j, cam in enumerate(self._camera_list):
                if cam["index"] == self.camera_port:
                    self.port_combo.setCurrentIndex(j)
                    break
        else:
            self.port_combo.addItem("No cameras found", -1)
        self.port_combo.blockSignals(False)

    def _on_camera_selected(self, idx):
        data = self.port_combo.itemData(idx)
        if data is not None and data >= 0:
            self.camera_port = data
        # CALIB HOOK — refresh calibration status whenever a camera is selected
        self._update_calib_status()

    def _on_resolution_changed(self, idx):
        data = self.resolution_combo.itemData(idx)
        if data:
            self.capture_width, self.capture_height = data

    # --- Setters ---
    def set_enabled(self, val):
        self.camera_enabled = val

    def set_pause(self, val):
        self.pause_time = val

    def set_dir(self, val):
        self.output_dir = val

    def browse_dir(self):
        d = QFileDialog.getExistingDirectory(
            self, "Select Output Directory", self.output_dir
        )
        if d:
            self.dir_edit.setText(d)
            self.output_dir = d

    # CALIB HOOK — status helper only; hardware routine lives in MainWindow
    def _update_calib_status(self):
        """Check for calibration.npz in output_dir and update calib_status_label."""
        import os
        npz = os.path.join(self.output_dir, "calibration.npz")
        if os.path.exists(npz):
            self.calib_status_label.setText("● Calibrated")
            self.calib_status_label.setStyleSheet("color: green; font-weight: bold;")
        else:
            self.calib_status_label.setText("● Not calibrated")
            self.calib_status_label.setStyleSheet("color: red; font-weight: bold;")

    # --- Capture Logic (Called from Print Thread) ---

    def _open_camera(self, cv2):
        """카메라를 열고 설정을 한 번만 적용 후 반환. 실패 시 None."""
        cap = cv2.VideoCapture(self.camera_port, BACKEND)
        if not cap.isOpened():
            return None

        # 설정은 카메라 오픈 직후 한 번만 — LED loop 에서 반복하면 DSHOW 지연 발생
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        cap.set(cv2.CAP_PROP_FRAME_WIDTH,  self.capture_width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.capture_height)
        cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, AUTO_EXPOSURE_MANUAL)
        cap.set(cv2.CAP_PROP_EXPOSURE,      self.exposure_value)
        cap.set(cv2.CAP_PROP_GAIN,          GAIN_VALUE)
        cap.set(cv2.CAP_PROP_AUTO_WB,       AUTO_WB)
        # FPS는 최대로 — 1로 고정하면 LED당 1초 강제 대기 발생
        cap.set(cv2.CAP_PROP_FPS, 30)

        # warm-up: 설정 적용 후 버퍼 flush
        for _ in range(WARMUP_FRAMES):
            cap.read()

        return cap

    def _grab_frame(self, cap, cv2):
        """grab×LED_FLUSH_FRAMES 로 버퍼 flush 후 retrieve."""
        for _ in range(LED_FLUSH_FRAMES):
            cap.grab()
        ret, f = cap.retrieve()
        if not ret or f is None:
            return None

        frame = f
        if UNSHARP_AMOUNT > 0:
            blurred = cv2.GaussianBlur(frame, (0, 0), UNSHARP_SIGMA)
            frame = cv2.addWeighted(frame, 1 + UNSHARP_AMOUNT,
                                    blurred, -UNSHARP_AMOUNT, 0)
        return frame

    def capture_led_sequence(self, filename_stem: str):
        """LED 1~5 를 순서대로 켜고, 각 LED 마다 카메라 캡처 후 저장.

        파일명: <filename_stem>_led1.png … <filename_stem>_led5.png
        Arduino 미연결 시 LED 없이 단일 캡처(noLED.png)로 fallback.
        카메라 설정은 오픈 시 한 번만 적용 — LED 전환 사이 딜레이 없음.
        Blocking — 프린트 스레드에서 직접 호출.
        """
        if not self.camera_enabled:
            return

        import cv2

        try:
            cap = self._open_camera(cv2)
            if cap is None:
                print(f"CAMERA: Could not open port {self.camera_port}")
                return

            led_indices = range(1, NUM_LEDS + 1) if self.led_enabled else [0]

            for led_n in led_indices:
                if led_n > 0:
                    self._led_on(led_n)
                time.sleep(LED_SETTLE_MS / 1000.0)

                frame = self._grab_frame(cap, cv2)

                if frame is None:
                    print(f"CAMERA: Failed to read frame (LED {led_n}).")
                    continue

                tag = f"led{led_n}" if led_n > 0 else "noLED"
                filepath = os.path.join(self.output_dir, f"{filename_stem}_{tag}.png")
                frame = cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE)
                cv2.imwrite(filepath, frame)
                h, w = frame.shape[:2]
                print(f"CAMERA: Saved {filepath}  ({w}x{h})")

                frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                self.update_image_signal.emit(frame_rgb)

            self._led_all_off()
            cap.release()

        except Exception as e:
            print(f"CAMERA ERROR: {e}")
            self._led_all_off()

    def capture_sync(self, filename_suffix):
        """Compatibility shim — delegates to capture_led_sequence."""
        self.capture_led_sequence(filename_suffix)

    def _preview_capture(self):
        """Grab a single low-res frame for quick preview — runs in background thread."""
        self.preview_btn.setEnabled(False)
        self.preview_btn.setText("Capturing…")
        threading.Thread(target=self._preview_worker, daemon=True).start()

    def _preview_worker(self):
        import cv2
        try:
            cap = cv2.VideoCapture(self.camera_port, BACKEND)
            if not cap.isOpened():
                return
            cap.set(cv2.CAP_PROP_FRAME_WIDTH,  1280)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
            cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, AUTO_EXPOSURE_MANUAL)
            cap.set(cv2.CAP_PROP_EXPOSURE, self.exposure_value)
            for _ in range(3):   # flush stale buffer frames
                cap.grab()
            ret, frame = cap.read()
            cap.release()
            if ret and frame is not None:
                frame = cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE)
                frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                self.update_image_signal.emit(frame_rgb)
        except Exception as e:
            print(f"PREVIEW ERROR: {e}")
        finally:
            # Qt widgets must only be touched on the main thread — emit a
            # signal instead of QMetaObject.invokeMethod, whose Q_ARG(str, ...)
            # marshalling for setText/setEnabled raises RuntimeError on some
            # PyQt5 builds and previously left the button stuck disabled.
            self._preview_done_signal.emit()

    @QtCore.pyqtSlot()
    def _reset_preview_button(self):
        self.preview_btn.setText("Preview")
        self.preview_btn.setEnabled(True)

    # --- UI Update (Runs on Main Thread) ---
    @QtCore.pyqtSlot(object)
    def update_display_slot(self, frame_rgb):
        self._last_frame_rgb = frame_rgb
        h, w, ch = frame_rgb.shape
        bytes_per_line = ch * w
        # Create QImage from data
        q_img = QImage(frame_rgb.data, w, h, bytes_per_line, QImage.Format_RGB888)
        # Scale to fit label
        pixmap = QPixmap.fromImage(q_img)
        scaled = pixmap.scaled(
            self.image_label.size(),
            QtCore.Qt.KeepAspectRatio,
            QtCore.Qt.SmoothTransformation,
        )
        self.image_label.setPixmap(scaled)

    def _open_zoom_view(self, event):
        """Show the most recent captured frame full-size in a separate dialog."""
        if self._last_frame_rgb is None:
            return
        frame_rgb = self._last_frame_rgb
        h, w, ch = frame_rgb.shape
        bytes_per_line = ch * w
        q_img = QImage(frame_rgb.data, w, h, bytes_per_line, QImage.Format_RGB888)
        pixmap = QPixmap.fromImage(q_img)

        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle("Camera Capture — Full Size")
        screen = QtWidgets.QApplication.primaryScreen().availableGeometry()
        max_w, max_h = int(screen.width() * 0.9), int(screen.height() * 0.9)
        layout = QtWidgets.QVBoxLayout(dialog)
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        zoom_label = QLabel()
        if pixmap.width() > max_w or pixmap.height() > max_h:
            pixmap = pixmap.scaled(max_w, max_h, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation)
        zoom_label.setPixmap(pixmap)
        scroll.setWidget(zoom_label)
        layout.addWidget(scroll)
        dialog.resize(_builtin_min(pixmap.width() + 40, max_w), _builtin_min(pixmap.height() + 40, max_h))
        dialog.exec_()


# -----------------------------------------------


class MainWindow(QtWidgets.QMainWindow):
    _grbl_status_signal = QtCore.pyqtSignal(str, str, str, str, str)
    _inkjet_status_signal = QtCore.pyqtSignal(str, str, str, str)
    _print_status_signal = QtCore.pyqtSignal(int, int)  # current_layer, total_layers
    _print_error_signal = QtCore.pyqtSignal(str)        # error message

    def __init__(self):
        super(MainWindow, self).__init__()

        script_dir = os.path.dirname(os.path.abspath(__file__))
        ui_path = os.path.join(script_dir, "Oasis_interface_v2.ui")
        Form, Window = uic.loadUiType(ui_path)

        self.ui = Window()
        self.form = Form()
        self.form.setupUi(self.ui)
        self.ui.show()

        qss_path = os.path.join(script_dir, "oasis_style.qss")
        with open(qss_path, "r", encoding="utf-8") as _f:
            self.ui.setStyleSheet(_f.read())

        self.camera_window = CameraController()

        # CALIB HOOK — wire calibration button to MainWindow so it can access grbl/hp45/imageconverter
        self.camera_window.btn_run_calibration.clicked.connect(self._run_calibration)

        # Add a button to the status bar (or elsewhere) to open the camera settings
        self.camera_btn = QtWidgets.QPushButton("Camera Settings")
        self.camera_btn.clicked.connect(self.camera_window.show)
        self.form.statusBar.addPermanentWidget(self.camera_btn)
        # -----------------------------------------------

        # make status variables
        self.motion_x_pos = QLabel("X=0.0")
        self.motion_y_pos = QLabel("Y=0.0")
        self.motion_f_pos = QLabel("F=0.0")
        self.motion_b_pos = QLabel("B=0.0")
        self.motion_status = QLabel("S=idle")
        self.motion_label = QLabel("Motion")

        self.inkjet_y_pos = QLabel("IY=0.0")
        self.inkjet_temperature = QLabel("T=0.0C")
        self.inkjet_bwl = QLabel("BWL=1000")
        self.inkjet_label = QLabel("Inkjet")

        self.MakeStatus()

        # self.ui = Interface()
        # self.ui.initUI()
        # self.ui.show()

        self.grbl = GRBL()
        self.inkjet = HP45()
        self.imageconverter = ImageConverter()

        self.printing_state = 0  # whether the printer is printing
        self.printing_abort_flag = 0
        self.printing_pause_flag = 0

        self.mid_print_clean_enabled = False                            # snapshot at print start; toggled by checkbox
        self.clean_interval = 5                                         # snapshot at print start; set by spinbox
        self.mid_print_clean_sequence = [("preheat", 3), ("prime", 3)] # fixed short sequence for mid-print cleans

        ## PARAMETER FOR REPEATING LAYER (NUMBER OF TIMES IT REITERATES THE PATTERN BEFORE RESETTING LAYER)
        self.layer_passes = 3  # repeat each layer this many times before Z advances

        self.RefreshPorts()  # get com ports for the buttons

        # grbl connect button
        self.grbl_connection_state = 0  # connected state of grbl
        self.form.motion_connect.clicked.connect(self.GrblConnect)
        # self.form.motion_set_port.returnPressed.connect(self.GrblConnect)
        # self.form.motion_refresh.clicked.connect(self.MakeStatus)

        # grbl send command button
        # self.form.motion_send_line.clicked.connect(self.GrblSendCommand)
        # self.ui.motion_write_line.returnPressed.connect(self.GrblSendCommand)

        # grbl home button
        self.form.motion_home.clicked.connect(self.grbl.Home)

        # Emergency unlock button — bypasses homing, coordinates unreliable
        self._emergency_btn = QtWidgets.QPushButton("⚠ Emergency Unlock")
        self._emergency_btn.setStyleSheet("background-color: #ff4444; color: white; font-weight: bold;")
        self._emergency_btn.setToolTip("Send $X to clear GRBL alarm and enable jog without homing.\nCoordinates will be unreliable.")
        self._emergency_btn.clicked.connect(self._EmergencyUnlock)
        _motion_layout = self.form.motion_home.parentWidget().layout()
        _motion_layout.addWidget(self._emergency_btn, _motion_layout.rowCount(), 0, 1, 4)

        # grbl jog buttons
        self.form.motion_xp.clicked.connect(lambda: self.grbl.Jog("X", "10", "6000"))
        self.form.motion_xn.clicked.connect(lambda: self.grbl.Jog("X", "-10", "6000"))
        self.form.motion_yp.clicked.connect(lambda: self.grbl.Jog("Y", "10", "6000"))
        self.form.motion_yn.clicked.connect(lambda: self.grbl.Jog("Y", "-10", "6000"))
        self.form.motion_goto_home.clicked.connect(
            lambda: self.grbl.SerialGotoXY(5, 245, "12000")
        )  # I am lazy, this should be automatically generated
        self.form.motion_fu.clicked.connect(lambda: self.grbl.Jog("A", "-1", "150"))
        self.form.motion_fd.clicked.connect(lambda: self.grbl.Jog("A", "1", "150"))
        self.form.motion_bu.clicked.connect(lambda: self.grbl.Jog("Z", "-1", "150"))
        self.form.motion_bd.clicked.connect(lambda: self.grbl.Jog("Z", "1", "150"))
        self.form.motion_spreader.clicked.connect(self.GRBLSpreader)
        self.form.motion_new_layer.clicked.connect(self.GRBLNewLayer)
        self.form.motion_prime_layer.clicked.connect(self.GRBLPrimeLayer)
        self.form.motion_set_overfeed.clicked.connect(self.GRBLSetOverfeed)

        self.form.motion_refresh.clicked.connect(self.RefreshPorts)
        self.form.inkjet_refresh.clicked.connect(self.RefreshPorts)

        # inkjet connect button
        self.inkjet_connection_state = 0  # connected state of inkjet
        self.form.inkjet_connect.clicked.connect(self.InkjetConnect)
        # self.form.inkjet_set_port.returnPressed.connect(self.InkjetConnect)
        # self.form.inkjet_refresh.clicked.connect(self.SetStatus)

        # inkjet send command button
        # self.form.inkjet_send_line.clicked.connect(self.InkjetSendCommand)
        # self.form.inkjet_write_line.returnPressed.connect(self.InkjetSendCommand)

        # inkjet function buttons
        self.form.inkjet_preheat.clicked.connect(self.InkjetPreheat)
        self.form.inkjet_prime.clicked.connect(self.InkjetPrime)
        self.form.inkjet_set_pos.clicked.connect(self.InkjetSetPosition)
        # self.form.inkjet_set_dpi.clicked.connect(self.InkjetSetDPI)
        self.form.dpi_combo.currentIndexChanged.connect(self.InkjetSetDPI)
        # self.form.inkjet_dpi.returnPressed.connect(self.InkjetSetDPI)
        self.form.inkjet_set_density.clicked.connect(
            self.InkjetSetDensity
        )  # 3/2 changed from self.inkjet.SetDensity to self.InkjetSetDensity
        self.form.inkjet_density.valueChanged.connect(self.InkjetSetDensityText)
        self.form.inkjet_head_clean.clicked.connect(self.InkjetHeadClean)
        self.form.inkjet_test_button.clicked.connect(self.inkjet.TestPrinthead)

        # file buttons
        self.file_loaded = 0
        self.form.file_open_button.clicked.connect(self.OpenFile)
        self.form.file_convert_button.clicked.connect(self.RenderOutput)
        self.form.file_print_button.clicked.connect(self.RunPrintArray)
        self.form.pause_button.clicked.connect(self.PausePrint)
        self.form.abort_button.clicked.connect(self.AbortPrint)

        # Config-runner: CSV-driven parameter sweep
        self.config_print_btn = QtWidgets.QPushButton("Config Print")
        self.config_print_btn.clicked.connect(self.RunConfigPrint)
        self.form.statusBar.addPermanentWidget(self.config_print_btn)
        # self.form.file_print_button.clicked.connect(self.RenderRGB)
        self.form.layer_slider.valueChanged.connect(self.UpdateLayer)
        self.form.start_layer_spinbox.setEnabled(False)  # disabled until file is loaded
        self.form.threshold_slider.valueChanged.connect(self.UpdateThresholdSliderValue)
        self.form.motion_layer_thickness.valueChanged.connect(
            self.UpdateLayerSliderValue
        )
        self.form.motion_overfeed.valueChanged.connect(self.UpdateOverfeedSliderValue)

        # Mid-print clean controls — inserted into Motion Control group below the overfeed slider.
        # motion_layer_thickness lives in an unnamed QGridLayout; grab it via parentWidget().layout().
        self.mid_print_clean_chk = QtWidgets.QCheckBox("Clean mid-print")
        self.mid_print_clean_chk.setChecked(self.mid_print_clean_enabled)
        self.mid_print_clean_chk.setToolTip(
            "Enable automatic printhead cleaning at regular layer intervals"
        )

        self.clean_interval_spin = QtWidgets.QSpinBox()
        self.clean_interval_spin.setRange(1, 50)
        self.clean_interval_spin.setValue(self.clean_interval)
        self.clean_interval_spin.setSuffix(" layers")
        self.clean_interval_spin.setToolTip("Clean every N layers (snapshot taken at print start)")
        self.clean_interval_spin.setEnabled(self.mid_print_clean_enabled)

        self.mid_print_clean_chk.toggled.connect(self.clean_interval_spin.setEnabled)

        _clean_row = QtWidgets.QHBoxLayout()
        _clean_row.addWidget(self.mid_print_clean_chk)
        _clean_row.addWidget(self.clean_interval_spin)
        _clean_row.addStretch()

        _motion_layout = self.form.motion_layer_thickness.parentWidget().layout()
        _motion_layout.addLayout(_clean_row, _motion_layout.rowCount(), 0, 1, 4)

        # self.form.save_png.clicked.connect(self.SavePng)

    def MakeStatus(self):
        """creates the status bar"""
        self.form.statusBar.addPermanentWidget(self.motion_label, 1)
        self.form.statusBar.addPermanentWidget(self.motion_x_pos, 1)
        self.form.statusBar.addPermanentWidget(self.motion_y_pos, 1)
        self.form.statusBar.addPermanentWidget(self.motion_f_pos, 1)
        self.form.statusBar.addPermanentWidget(self.motion_b_pos, 1)
        self.form.statusBar.addPermanentWidget(self.motion_status, 1)
        self._grbl_status_signal.connect(self._update_grbl_status)

        self.form.statusBar.addPermanentWidget(QLabel(" "), 5)

        self.bed_size_label = QLabel("No file loaded")
        self.form.statusBar.addPermanentWidget(self.bed_size_label, 6)

        self.form.statusBar.addPermanentWidget(self.inkjet_label, 1)
        self.form.statusBar.addPermanentWidget(self.inkjet_y_pos, 1)
        self.form.statusBar.addPermanentWidget(self.inkjet_temperature, 1)
        self.form.statusBar.addPermanentWidget(self.inkjet_bwl, 1)
        self._inkjet_status_signal.connect(self._update_inkjet_status)
        self._print_status_signal.connect(self._update_print_status)
        self._print_error_signal.connect(self._show_print_error)

    @QtCore.pyqtSlot(int, int)
    def _update_print_status(self, current, total):
        self.form.layer_slider.setValue(current)
        self.form.layer_slider_value.setText(f"Layer: {current} / {total}")

    @QtCore.pyqtSlot(str)
    def _show_print_error(self, msg):
        QtWidgets.QMessageBox.critical(self, "Print Error", msg)

    def RefreshPorts(self):
        """Lists serial port names
        :raises EnvironmentError:
            On unsupported or unknown platforms
        """
        if sys.platform.startswith("win"):
            ports = ["COM%s" % (i + 1) for i in range(256)]
        elif sys.platform.startswith("linux") or sys.platform.startswith("cygwin"):
            # this excludes your current terminal "/dev/tty"
            ports = glob.glob("/dev/tty[A-Za-z]*")
        elif sys.platform.startswith("darwin"):
            ports = glob.glob("/dev/tty.*")
        else:
            raise EnvironmentError("Unsupported platform")

        result = []
        for port in ports:
            try:
                s = serial.Serial(port)
                s.close()
                result.append(port)
            except (OSError, serial.SerialException):
                pass
        # print(result)

        # update the com ports for motion and inkjet
        self.form.motion_set_port.clear()
        self.form.motion_set_port.addItems(result)

        self.form.inkjet_set_port.clear()
        self.form.inkjet_set_port.addItems(result)

        # update Arduino LED controller port list
        if hasattr(self, "camera_window"):
            self.camera_window.arduino_port_combo.clear()
            self.camera_window.arduino_port_combo.addItems(result if result else ["(none)"])

    def _EmergencyUnlock(self):
        """Clear GRBL alarm lock without homing — jog becomes available immediately.
        WARNING: machine coordinates are unreliable until a proper Home() is run."""
        if self.grbl_connection_state != 1:
            QtWidgets.QMessageBox.warning(
                self.ui, "Not Connected", "Connect to GRBL before using Emergency Unlock."
            )
            return
        reply = QtWidgets.QMessageBox.warning(
            self.ui,
            "Emergency Unlock",
            "This bypasses homing. Machine coordinates will be unreliable.\n\nProceed?",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
        )
        if reply == QtWidgets.QMessageBox.Yes:
            self.grbl.EmergencyUnlock()

    def GrblConnect(self):
        """Gets the GRBL serial port and attempt to connect to it"""
        if (
            self.printing_state == 0
        ):  # only act on the button if the printer is not printing
            if (
                self.grbl_connection_state == 0
            ):  # get connection state, if 0 (not connected)
                # print("Attempting connection with GRBL")
                temp_port = str(self.form.motion_set_port.currentText())  # get text
                temp_succes = self.grbl.Connect(temp_port)  # attempt to connect
                if temp_succes == 1:  # on success,
                    self.form.motion_connect.setText(
                        "Disconnect"
                    )  # rewrite button text
                    self.grbl_connection_state = 1  # set  state
                    # self.form.motion_set_port.clear()
                    # start a thread that will update the serial in and output for GRBL
                    self._grbl_stop_event = threading.Event()
                    self.grbl_update_thread = threading.Thread(target=self.GrblUpdate, daemon=True)
                    self.grbl_update_thread.start()

                else:
                    print("Connection with GRBL failed")
            else:  # on state 1
                # print("disconnecting from GRBL")
                self.grbl.Disconnect()  # disconnect
                self.grbl_connection_state = 0  # set state to disconnected
                self.form.motion_connect.setText("Connect")  # rewrite button
                self._grbl_stop_event.set()  # close the grbl serial thread

    @QtCore.pyqtSlot(str, str, str, str, str)
    def _update_grbl_status(self, status, x, y, b, f):
        self.motion_status.setText(status)
        self.motion_x_pos.setText(x)
        self.motion_y_pos.setText(y)
        self.motion_b_pos.setText(b)
        self.motion_f_pos.setText(f)

    def GrblUpdate(self):
        """updates serial in and output for the GRBL window"""
        time.sleep(1)
        while not self._grbl_stop_event.is_set():
            try:
                self._grbl_status_signal.emit(
                    f"S={self.grbl.motion_state}",
                    f"X={self.grbl.motion_x_pos:.2f}",
                    f"Y={self.grbl.motion_y_pos:.2f}",
                    f"B={self.grbl.motion_z_pos:.2f}",
                    f"F={self.grbl.motion_a_pos:.2f}",
                )
            except Exception:
                import traceback
                traceback.print_exc()
            time.sleep(0.1)

    def GrblSendCommand(self):
        """Gets the command from the textedit and prints it to Grbl"""
        if self.grbl_connection_state == 1:
            temp_command = str(self.form.motion_write_line.text())  # get line
            temp_command += "\r"  # add end of line
            self.grbl.SerialWriteBufferRaw(temp_command)  # write to grbl
            self.form.motion_write_line.clear()  # clear line

    def InkjetConnect(self):
        """Gets the inkjet serial port and attempt to connect to it"""
        if (
            self.printing_state == 0
        ):  # only act on the button if the printer is not printing
            if (
                self.inkjet_connection_state == 0
            ):  # get connection state, if 0 (not connected)
                # print("Attempting connection with HP45")
                temp_port = str(self.form.inkjet_set_port.currentText())  # get text
                temp_succes = self.inkjet.Connect(temp_port)  # attempt to connect
                if temp_succes == 1:  # on success,
                    self.form.inkjet_connect.setText(
                        "Disconnect"
                    )  # rewrite button text
                    self.inkjet_connection_state = 1  # set  state
                    # self.form.inkjet_set_port.clear()
                    # start a thread that will update the serial in and output for HP45
                    self._inkjet_stop_event = threading.Event()
                    self.inkjet_update_thread = threading.Thread(
                        target=self.InkjetUpdate, daemon=True
                    )
                    self.inkjet_update_thread.start()

                else:
                    print("Connection with HP failed")
            else:  # on state 1
                # print("disconnecting from HP45")
                self.inkjet.Disconnect()  # disconnect
                self.inkjet_connection_state = 0  # set state to disconnected
                self.form.inkjet_connect.setText("Connect")  # rewrite button
                self._inkjet_stop_event.set()  # close the HP45 serial thread

    @QtCore.pyqtSlot(str, str, str, str)
    def _update_inkjet_status(self, temp, y, bwl, test_state):
        self.inkjet_temperature.setText(temp)
        self.inkjet_y_pos.setText(y)
        self.inkjet_bwl.setText(bwl)
        self.form.inkjet_test_state.setText(test_state)

    def InkjetUpdate(self):
        """updates serial in and output for the inkjet window"""
        time.sleep(1)
        while not self._inkjet_stop_event.is_set():
            try:
                self._inkjet_status_signal.emit(
                    f"T={self.inkjet.inkjet_temperature:.1f}C",
                    f"IY={self.inkjet.inkjet_x_pos:.2f}",
                    f"BWL={self.inkjet.inkjet_writeleft}",
                    f"{self.inkjet.inkjet_working_nozzles}/{self.inkjet.inkjet_total_nozzles}",
                )
            except Exception:
                import traceback
                traceback.print_exc()
            time.sleep(0.2)

    def InkjetSendCommand(self):
        """Gets the command from the textedit and prints it to Inkjet"""
        if self.inkjet_connection_state == 1:
            temp_command = str(self.form.inkjet_write_line.text())  # get line
            temp_command += "\r"  # add end of line
            self.inkjet.SerialWriteBufferRaw(temp_command)  # write to inkjet
            self.form.inkjet_write_line.clear()  # clear line

    def InkjetSetPosition(self):
        """Gets the position from GRBL, converts it and sends it to HP45"""
        if (
            self.inkjet_connection_state == 1
        ):  # and self.printing_state == 0): #only act on the button if the printer is not printing and connected
            time.sleep(0.3)  # wait for a while to get the newest pos
            temp_pos = self.grbl.motion_y_pos  # set pos to variable
            temp_pos *= 1000.0
            temp_pos = int(temp_pos)  # cast to interger
            self.inkjet.SetPosition(temp_pos)  # set position

    def InkjetPrime(self):
        """if possible, sends a priming burst to the printhead"""
        if (
            self.inkjet_connection_state == 1 and self.printing_state == 0
        ):  # only act on the button if the printer is not printing and connected
            self.inkjet.Prime(getattr(self, "prime_pulses", 100))

    def InkjetPreheat(self):
        """if possible, sends a preheating burst to the printhead"""
        if (
            self.inkjet_connection_state == 1 and self.printing_state == 0
        ):  # only act on the button if the printer is not printing and connected
            self.inkjet.Preheat(getattr(self, "preheat_pulses", 5000))

    def InkjetHeadClean(self):
        """
        Runs a printhead cleaning sequence in a background thread.
        Sequence (1000 ms interval between each burst):
          Preheat x10 -> Prime x10 -> Preheat x10 -> Prime x5 -> Preheat x5
        Blocked if printer is printing or inkjet is not connected.
        """
        if self.inkjet_connection_state != 1 or self.printing_state != 0:
            return
        threading.Thread(target=self._HeadCleanWorker, daemon=True).start()

    def _HeadCleanWorker(self, sequence=None):
        """Background worker for InkjetHeadClean — do not call directly.

        sequence: list of (action, count) tuples where action is 'preheat' or 'prime'.
        Defaults to the full manual-clean sequence when called from InkjetHeadClean.
        Pass a shorter sequence for mid-print cleaning.
        """
        preheat_pulses = getattr(self, "preheat_pulses", 5000)
        prime_pulses = getattr(self, "prime_pulses", 100)
        if sequence is None:
            sequence = [
                ("preheat", 5),
                ("prime",   5),
                ("preheat", 5),
                ("prime",   5),
            ]
        total = sum(n for _, n in sequence)
        done = 0
        print("HeadClean: starting cleaning sequence")
        for action, count in sequence:
            for _ in range(count):
                if action == "preheat":
                    self.inkjet.Preheat(preheat_pulses)
                else:
                    self.inkjet.Prime(prime_pulses)
                done += 1
                print(f"HeadClean: {done}/{total} ({action})")
                time.sleep(1.0)
        print("HeadClean: sequence complete")

    def _MaybeCleanMidPrint(self) -> None:
        """Run a short printhead clean if enabled and the clean interval is due.

        Called once per layer inside _PrintSVG_inner after current_layer increments.
        Uses the snapshot values (mid_print_clean_enabled, clean_interval) captured at
        print start — UI changes during a run have no effect until the next run.
        Runs synchronously so the print loop waits for the full clean to finish.
        """
        if not self.mid_print_clean_enabled:
            return
        if self.clean_interval == 0 or self.current_layer == 0:
            return
        if self.current_layer % self.clean_interval != 0:
            return
        if self.inkjet_connection_state != 1:
            return

        print(f"[MidPrintClean] layer {self.current_layer} — homing gantry before clean")
        self.grbl.SerialGotoHome(self.travel_speed)
        self.grbl.StatusIndexSet()
        while True:
            time.sleep(0.1)
            if (self.grbl.StatusIndexChanged() == 1
                    and self.grbl.motion_state == "idle"):
                break

        self.InkjetSetPosition()
        print(f"[MidPrintClean] running sequence: {self.mid_print_clean_sequence}")
        self._HeadCleanWorker(sequence=self.mid_print_clean_sequence)
        print("[MidPrintClean] done")

    def InkjetSetDPI(self):
        """Writes the DPI to the printhead and decode function"""
        # temp_dpi = str(self.form.inkjet_dpi.text()) #get text#get dpi
        temp_dpi = str(self.form.dpi_combo.currentText())  # get text#get dpi
        temp_dpi_val = 0
        temp_success = 0
        try:
            temp_dpi_val = int(temp_dpi)
            temp_success = 1
        except:
            # print ("Unable to convert to dpi")
            nothing = 0

        if temp_success == 1:  # if conversion was successful
            if self.printing_state == 0:  # only set DPI when not printing
                print("DPI to set: " + str(temp_dpi_val))
                if (
                    self.inkjet_connection_state == 1
                ):  # only write to printhead when connected
                    self.inkjet.SetDPI(temp_dpi_val)  # write to inkjet
                self.imageconverter.SetDPI(temp_dpi_val)  # write to image converter
                if self.file_loaded != 0:  # if any file is loaded
                    print("resising image")
                    self.OpenFile(self.input_file_name[0])

    def InkjetSetDensity(self):
        """Writes the Density to the printhead"""
        if self.inkjet_connection_state == 1:
            temp_density = str(
                self.form.inkjet_density.value()
            )  # get text #get density
            temp_density_val = 0
            temp_success = 0
            try:
                temp_density_val = int(temp_density)
                temp_success = 1
            except:
                # print ("Unable to convert to dpi")
                nothing = 0

            if temp_success == 1:  # if conversion was successful
                # Slider now operates 0–1000 directly (no x10 scaling)
                print(temp_density_val)

                self.inkjet.SetDensity(temp_density_val)  # write to inkjet

    def InkjetSetDensityText(self):
        """Rewrited density on GUI"""
        temp_density = str(self.form.inkjet_density.value())  # get text #get density
        temp_density = int(temp_density)
        # Slider now operates 0–1000 directly (no x10 scaling)
        self.form.inket_density_value.setText("Density: " + str(temp_density) + "%")

    def UpdateThresholdSliderValue(self):
        """Updates the value next to the threshold slider"""
        temp_threshold = self.form.threshold_slider.value()
        self.form.threshold_slider_value.setText("Threshold: " + str(temp_threshold))

    def UpdateLayerSliderValue(self):
        """Updates the value next to the new layer slider"""
        temp_slider = float(self.form.motion_layer_thickness.value())
        temp_slider = temp_slider * 0.05
        self.form.motion_layer_value.setText(f"New layer: {temp_slider:.2f} mm")

    def UpdateOverfeedSliderValue(self):
        """Updates the value next to the overfeed slider"""
        temp_slider = self.form.motion_overfeed.value()
        temp_slider = 80 + (temp_slider * 5)
        self.form.motion_overfeed_value.setText(f"Overfeed: {temp_slider}%")

    def GRBLSpreader(self):
        """Toggles the spreader on or off and sets the button"""
        temp_return = self.grbl.SpreaderToggle()
        if temp_return == 1:
            self.form.motion_spreader.setText("Spreader off")
            print("spreader off")
        else:
            self.form.motion_spreader.setText("Spreader on")
            print("spreader on")

    def GRBLNewLayer(self):
        """add a new layer"""
        if self.grbl_connection_state == 1:
            # print("new layer")
            temp_layer_thickness_val = float(self.form.motion_layer_thickness.value())
            temp_layer_thickness_val = temp_layer_thickness_val * 0.05

            # print("adding new layer: " + str(temp_layer_thickness_val))
            self.grbl.NewLayer(temp_layer_thickness_val)

    def GRBLPrimeLayer(self):
        """add a new layer"""
        if self.grbl_connection_state == 1:
            # print("new layer")
            temp_layer_thickness_val = float(self.form.motion_layer_thickness.value())
            temp_layer_thickness_val = temp_layer_thickness_val * 0.05

            # print("adding new layer: " + str(temp_layer_thickness_val))
            self.grbl.NewLayer(temp_layer_thickness_val, 1)

    def GRBLSetOverfeed(self):
        """set overfeed"""
        temp_overfeed = self.form.motion_overfeed.value()
        temp_overfeed = 80 + (temp_overfeed * 5)

        self.grbl.SetOverfeed(temp_overfeed)

    def OpenFile(self, temp_input_file=""):
        """Opens a file dialog, takes the filepath, and passes it to the image converter"""
        if temp_input_file:
            temp_response = self.imageconverter.OpenFile(temp_input_file)
        else:
            self.input_file_name = QFileDialog.getOpenFileName(
                self, "Open file", "", "Image files (*.jpg *.png *.svg)"
            )
            temp_response = self.imageconverter.OpenFile(self.input_file_name[0])

        if temp_response == 1:
            self.RenderInput()
            self.file_loaded = 1
        if temp_response == 2:
            self.file_loaded = 2
            self.form.layer_slider.setMaximum(self.imageconverter.svg_layers - 1)
            self.form.start_layer_spinbox.setMaximum(self.imageconverter.svg_layers)
            self.form.start_layer_spinbox.setValue(1)
            self.form.start_layer_spinbox.setEnabled(True)
            self.RenderOutput()
            self._UpdateBedSizeStatus()
            self._CheckMaxHeight()

    def _UpdateBedSizeStatus(self):
        """Show print dimensions vs 84mm circular bed in the status bar."""
        BED_DIAMETER_MM = 84.0
        w = self.imageconverter.svg_width   # mm
        h = self.imageconverter.svg_height  # mm
        layers = self.imageconverter.svg_layers

        # Diagonal of the bounding box — worst case for a circular bed
        diagonal = math.sqrt(w ** 2 + h ** 2)
        fits = diagonal <= BED_DIAMETER_MM
        fit_str = "✓ FITS" if fits else f"⚠ EXCEEDS BED (diagonal {diagonal:.1f} mm)"
        status = (
            f"Print: {w:.1f} x {h:.1f} mm  |  "
            f"Layers: {layers}  |  "
            f"Bed: {BED_DIAMETER_MM:.0f} mm dia  |  "
            f"{fit_str}"
        )
        self.bed_size_label.setText(status)

    def _CheckMaxHeight(self):
        """Warn if total structure height exceeds 21mm (210 layers × 0.1mm)."""
        MAX_HEIGHT_MM = 50.0  # 500 layers × 0.1mm
        if not self.imageconverter.svg_layer_height:
            return
        total_height = self.imageconverter.svg_layer_height[-1]  # mm
        if total_height > MAX_HEIGHT_MM:
            QMessageBox.warning(
                self,
                "Height Warning",
                f"Structure height {total_height:.2f} mm exceeds maximum {MAX_HEIGHT_MM:.1f} mm "
                f"(210 layers × 0.1 mm).\n\nPrint may fail or damage the printer.",
            )

    def UpdateLayer(self):
        if (
            self.imageconverter.file_type == 2 and self.printing_state == 0
        ):  # if file is svg
            temp_layer = self.form.layer_slider.value()
            self.form.layer_slider_value.setText("Layer: " + str(temp_layer))
            self.imageconverter.SVGLayerToArray(temp_layer)
            self.RenderOutput()

    def PausePrint(self):
        if self.file_loaded == 2:  # only update pause if print is running
            if self.printing_pause_flag == 0:
                self.printing_pause_flag = 1
                self.form.pause_button.setText("Resume")
            else:
                self.printing_pause_flag = 0
                self.form.pause_button.setText("Pause")

    def AbortPrint(self):
        if self.file_loaded == 2:  # only update pause if print is running
            # MessageBox.about(self, "Title", "Message")
            temp_response = QMessageBox.question(
                self,
                "Abort print",
                "Do you really want to abort the print?",
                QMessageBox.Yes | QMessageBox.No,
            )
            if temp_response == QMessageBox.Yes:
                self.printing_abort_flag = 1

    def RenderInput(self):
        """input_window removed in v2 UI — no-op"""
        pass

    def RenderOutput(self):
        """Gets an image from the image converter class and renders it to output"""
        if self.file_loaded == 1:
            temp_threshold = self.form.threshold_slider.value()
            self.imageconverter.Threshold(temp_threshold)
            self.imageconverter.ArrayToImage()
            self.output_image_display = self.imageconverter.output_image
            if (
                self.output_image_display.width() > 300
                and self.output_image_display.height() > 300
            ):
                self.output_image_display = self.output_image_display.scaled(
                    300, 300, QtCore.Qt.KeepAspectRatio
                )
            self.form.output_window.setPixmap(self.output_image_display)

        if self.file_loaded == 2:
            self.imageconverter.ArrayToImage()
            self.output_image_display = self.imageconverter.output_image
            overlay = self._RenderBedOverlay(self.output_image_display)
            self.form.output_window.setPixmap(overlay)

    def _RenderBedOverlay(self, svg_pixmap):
        """Composite the SVG pattern onto a circular bed preview.

        The bed (84 mm dia) is drawn as a light-grey filled circle.
        The SVG bounding box is centered on the bed (matching build_center/svg_offset logic).
        The SVG pattern image is painted inside that bounding box.
        Returns a 300x300 QPixmap.
        """
        from PyQt5.QtGui import QPainter, QColor, QPen, QBrush
        from PyQt5.QtCore import Qt, QRectF

        CANVAS = 300
        BED_DIAMETER_MM = 84.0

        svg_w_mm = self.imageconverter.svg_width   # mm
        svg_h_mm = self.imageconverter.svg_height  # mm

        # Scale factor: fit the bed circle into CANVAS px with a small margin
        MARGIN = 10
        px_per_mm = (CANVAS - MARGIN * 2) / BED_DIAMETER_MM

        bed_px = BED_DIAMETER_MM * px_per_mm                  # should equal CANVAS - 2*MARGIN
        svg_w_px = svg_w_mm * px_per_mm
        svg_h_px = svg_h_mm * px_per_mm

        # Centre of canvas
        cx = CANVAS / 2.0
        cy = CANVAS / 2.0

        # SVG is centred on bed centre (build_center - svg_offset cancels out)
        svg_left = cx - svg_w_px / 2.0
        svg_top  = cy - svg_h_px / 2.0

        canvas = QPixmap(CANVAS, CANVAS)
        canvas.fill(QColor(240, 240, 240))   # light grey background

        painter = QPainter(canvas)
        painter.setRenderHint(QPainter.Antialiasing)

        # --- Draw bed circle ---
        bed_rect = QRectF(cx - bed_px / 2, cy - bed_px / 2, bed_px, bed_px)
        painter.setBrush(QBrush(QColor(255, 255, 255)))        # white bed surface
        painter.setPen(QPen(QColor(80, 80, 80), 2))
        painter.drawEllipse(bed_rect)

        # --- Draw SVG pattern scaled to bed coordinate space ---
        if not svg_pixmap.isNull():
            scaled_svg = svg_pixmap.scaled(
                int(svg_w_px), int(svg_h_px),
                QtCore.Qt.KeepAspectRatio,
                QtCore.Qt.SmoothTransformation,
            )
            # Re-centre after KeepAspectRatio may have changed one dimension
            actual_w = scaled_svg.width()
            actual_h = scaled_svg.height()
            draw_x = int(cx - actual_w / 2)
            draw_y = int(cy - actual_h / 2)
            painter.setOpacity(0.85)
            painter.drawPixmap(draw_x, draw_y, scaled_svg)
            painter.setOpacity(1.0)

        # --- Draw SVG bounding box outline ---
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(QColor(0, 120, 220), 1, Qt.DashLine))
        painter.drawRect(QRectF(svg_left, svg_top, svg_w_px, svg_h_px))

        # --- Bed centre crosshair ---
        painter.setPen(QPen(QColor(180, 0, 0), 1))
        painter.drawLine(int(cx) - 6, int(cy), int(cx) + 6, int(cy))
        painter.drawLine(int(cx), int(cy) - 6, int(cx), int(cy) + 6)

        painter.end()
        return canvas

    def RenderAlpha(self):
        """Renders alpha mask (used for troubleshooting)"""
        self.imageconverter.AlphaMaskToImage()
        self.output_image_display = self.imageconverter.output_image
        if (
            self.output_image_display.width() > 300
            and self.output_image_display.height() > 300
        ):
            self.output_image_display = self.output_image_display.scaled(
                300, 300, QtCore.Qt.KeepAspectRatio
            )
        self.form.output_window.setPixmap(self.output_image_display)

    def RenderRGB(self):
        """Renders only RGB, ignoring alpha (used for troubleshooting)"""
        self.imageconverter.RGBToImage()
        self.output_image_display = self.imageconverter.output_image
        if (
            self.output_image_display.width() > 300
            and self.output_image_display.height() > 300
        ):
            self.output_image_display = self.output_image_display.scaled(
                300, 300, QtCore.Qt.KeepAspectRatio
            )
        self.form.output_window.setPixmap(self.output_image_display)

    def RunPrintArray(self):
        """Starts a thread for the print array function"""
        if self.file_loaded == 1:
            self._printing_stop_event = threading.Event()
            self.printing_thread = threading.Thread(target=self.PrintArray, daemon=True)
            self.printing_thread.start()
        if self.file_loaded == 2:
            self._printing_stop_event = threading.Event()
            self.printing_thread = threading.Thread(target=self.PrintSVG, daemon=True)
            self.printing_thread.start()

    # v1.1.5 HOOK
    def save_reference_png(self, layer_idx):
        """Save image_array as PNG in bed-space coordinates.

        Output image is the same pixel space as calibration_reference.png:
            size  = (BED_DIAMETER_MM + 4mm margin) sq at current DPI
            offset = 44mm  (bed centre maps to image centre)
        Bed boundary circle drawn in black. No calibration.npz required.
        """
        import cv2
        import numpy as np
        from dice_evaluator.constants import BED_DIAMETER_MM, BED_RADIUS_MM

        captures_dir = self.camera_window.output_dir
        arr = self.imageconverter.image_array
        arr_h, arr_w = arr.shape

        # bed-space output: same coordinate system as calibration_reference.png
        # Both arrays use same DPI, so pixel mapping is a simple centre-to-centre shift.
        # svg_offset (GRBL world origin) cancels out — only bed-relative position matters.
        _margin_mm = 2.0
        _bed_span_mm = BED_DIAMETER_MM + _margin_mm * 2      # 88mm
        _px_per_mm = self.printing_dpi / 25.4
        out_size = int(_bed_span_mm * _px_per_mm) + 1        # same as calib_array
        _out_cx = out_size // 2   # output image centre col (= bed centre Y)
        _out_cy = out_size // 2   # output image centre row (= bed centre X)
        _arr_cx = arr_w // 2      # image_array centre col
        _arr_cy = arr_h // 2      # image_array centre row

        out = np.zeros((out_size, out_size), dtype=np.uint8)
        for row in range(arr_h):
            for col in range(arr_w):
                if arr[row, col] == 0:
                    continue
                out_row = row - _arr_cy + _out_cy
                out_col = col - _arr_cx + _out_cx
                if 0 <= out_row < out_size and 0 <= out_col < out_size:
                    out[out_row, out_col] = 255

        kernel = np.ones((2, 2), dtype=np.uint8)
        out = cv2.dilate(out, kernel, iterations=1)
        out = 255 - out  # invert: ink=black, background=white

        # bed boundary circle at image centre
        _cx = out_size // 2
        _cy = out_size // 2
        _r = int(round(BED_RADIUS_MM * _px_per_mm))
        cv2.circle(out, (_cx, _cy), _r, color=0, thickness=1)

        # mirror + 90° CCW rotation to match camera view orientation
        out = np.rot90(out, 1)

        path = os.path.join(captures_dir, f"layer_{layer_idx:03d}_reference.png")
        cv2.imwrite(path, out)

    def save_reference_svg(self, layer_idx):
        """Extract the current layer from the loaded SVG and save as a single-layer SVG."""
        captures_dir = self.camera_window.output_dir
        svg_path = self.imageconverter.file_path
        layer_name = self.imageconverter.svg_layer_names[layer_idx - 1]

        in_layer = False
        layer_lines = []
        with open(svg_path, encoding="utf-8") as f:
            header = None
            for line in f:
                if header is None and line.startswith("<svg "):
                    header = line
                if line.startswith("  <g ") and f'id="{layer_name}"' in line:
                    in_layer = True
                if in_layer:
                    layer_lines.append(line)
                if in_layer and line.startswith("  </g>"):
                    break

        if not header or not layer_lines:
            return

        out_path = os.path.join(captures_dir, f"layer_{layer_idx:03d}_reference.svg")
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(header)
            f.writelines(layer_lines)
            f.write("</svg>\n")

    # CALIB HOOK — full calibration routine using existing hardware handles
    def _run_calibration(self):
        """Start calibration in a background thread (must not block the GUI thread)."""
        if self.grbl_connection_state != 1 or self.inkjet_connection_state != 1:
            QtWidgets.QMessageBox.warning(
                self.ui,
                "Not Ready",
                "Connect both GRBL and HP45 before running calibration.",
            )
            return
        t = threading.Thread(target=self._run_calibration_inner, daemon=True)
        t.start()

    def _run_calibration_inner(self):
        """Hardware calibration routine — runs in a background thread.

        Flow:
          1. Write asymmetric circle-grid SVG (4×11, 84mm bed) to captures_dir
          2. Parse SVG circles → build calib_array in bed-space pixel coords
          3. Print 1 layer via existing self.grbl + self.hp45 path
          4. Poll self.grbl.nl_state == 1   (same pattern as main loop)
          5. capture_sync("calibration") → frame on disk
          6. detect_circle_in_image(frame) → compute + save calibration.npz
        """
        import cv2
        from dice_evaluator.calibrate import (
            detect_circle_in_image,
            compute_calibration,
            save_calibration,
        )
        from dice_evaluator.constants import (
            BED_DIAMETER_MM, BED_RADIUS_MM, BUILD_CENTER_X_MM, BUILD_CENTER_Y_MM,
        )

        captures_dir = self.camera_window.output_dir

        # 1. Write the asymmetric circle-grid calibration SVG to disk
        # Grid: 4×11 rows (alternating offset), circle r=1.8mm, 12mm column pitch,
        #       6mm row pitch, canvas 61.6×79.6mm centred on bed
        _SVG_W_MM  = 61.6
        _SVG_H_MM  = 79.6
        _CIRCLE_R  = 1.8   # mm
        _COL_PITCH = 12.0  # mm between columns within a row
        _ROW_PITCH = 6.0   # mm between rows
        _ROW_EVEN_X0 = 9.8   # cx of first circle on even rows (0-indexed)
        _ROW_ODD_X0  = 15.8  # cx of first circle on odd rows
        _N_COLS = 4
        _N_ROWS = 11
        _ROW_Y0 = 9.8   # cy of first row

        svg_circles = []
        for row in range(_N_ROWS):
            cx0 = _ROW_EVEN_X0 if row % 2 == 0 else _ROW_ODD_X0
            cy  = _ROW_Y0 + row * _ROW_PITCH
            for col in range(_N_COLS):
                cx = cx0 + col * _COL_PITCH
                svg_circles.append((cx, cy))

        svg_lines = [
            '<?xml version="1.0" encoding="UTF-8" standalone="no"?>',
            f'<svg xmlns="http://www.w3.org/2000/svg"',
            f'    width="{_SVG_W_MM}mm" height="{_SVG_H_MM}mm"',
            f'    viewBox="0 0 {_SVG_W_MM} {_SVG_H_MM}">',
            f'  <rect x="0" y="0" width="{_SVG_W_MM}" height="{_SVG_H_MM}" fill="white" />',
            f'  <rect x="0" y="0" width="{_SVG_W_MM}" height="{_SVG_H_MM}" fill="none" stroke="black" stroke-width="0.200" />',
        ]
        for (cx, cy) in svg_circles:
            svg_lines.append(f'  <circle cx="{cx}" cy="{cy}" r="{_CIRCLE_R}" fill="black" />')
        svg_lines.append('</svg>')

        svg_path = os.path.join(captures_dir, "calibration_target.svg")
        with open(svg_path, "w", encoding="utf-8") as _f:
            _f.write("\n".join(svg_lines) + "\n")
        print(f"CALIB: SVG written to {svg_path}")

        # 2. Build calib_array in bed-space pixel coords
        #    SVG is centred on bed centre; each circle is filled as a solid disc.
        _calib_dpi   = int(self.imageconverter.dpi)
        _px_per_mm   = _calib_dpi / 25.4

        _calib_margin_mm = 2.0
        _arr_w = int((BED_DIAMETER_MM + _calib_margin_mm * 2) * _px_per_mm) + 1
        _arr_h = int((BED_DIAMETER_MM + _calib_margin_mm * 2) * _px_per_mm) + 1

        # Array centre = bed centre in pixel space
        _cx_px = _arr_w / 2.0   # col axis → machine Y
        _cy_px = _arr_h / 2.0   # row axis → machine X

        # SVG origin offset: SVG (0,0) maps to bed_centre - svg_half_size
        _svg_origin_col = _cx_px - (_SVG_W_MM / 2.0) * _px_per_mm  # col offset
        _svg_origin_row = _cy_px - (_SVG_H_MM / 2.0) * _px_per_mm  # row offset

        _r_px = int(round(_CIRCLE_R * _px_per_mm))

        import cv2 as _cv2
        import numpy as _np
        _calib_u8 = zeros((_arr_h, _arr_w), dtype=_np.uint8)

        for (svg_cx_mm, svg_cy_mm) in svg_circles:
            # SVG cx is along canvas width (→ machine Y → col axis)
            # SVG cy is along canvas height (→ machine X → row axis)
            col_c = int(round(_svg_origin_col + svg_cx_mm * _px_per_mm))
            row_c = int(round(_svg_origin_row + svg_cy_mm * _px_per_mm))
            _cv2.circle(_calib_u8, (col_c, row_c), _r_px, color=255, thickness=-1)

        # Transfer u8 mask into float calib_array (1 = ink)
        calib_array = (_calib_u8 > 0).astype(float)

        # 2b. Save reference PNG (ink=black, background=white) with bed boundary
        _out = ((1 - calib_array) * 255).astype(_np.uint8)
        _bed_r_px = int(round(BED_RADIUS_MM * _px_per_mm))
        _cv2.circle(_out, (int(_cx_px), int(_cy_px)), _bed_r_px, color=0, thickness=1)
        # mirror + 90° CCW rotation to match camera view orientation
        _out = _np.rot90(_out, 1)
        _cv2.imwrite(os.path.join(captures_dir, "calibration_reference.png"), _out)
        print("CALIB: Saved calibration_reference.png")

        # 3. Set up print variables identical to _PrintSVG_inner
        self.build_center_x = 157.0
        self.build_center_y = 116.0
        self.print_speed = 2200.0
        self.travel_speed = 3000.0
        self.acceleration_distance = 20.0
        self.printing_dpi = _calib_dpi
        self.printing_sweep_size = int(self.printing_dpi / 2)
        self.pixel_to_pos_multiplier = 25.4 / self.printing_dpi
        self.image_size_x = _arr_h
        self.image_size_y = _arr_w
        self.svg_offset_y = (BED_DIAMETER_MM + _calib_margin_mm * 2) / 2
        self.svg_offset_x = (BED_DIAMETER_MM + _calib_margin_mm * 2) / 2

        self.inkjet.SetDPI(self.printing_dpi)
        self.inkjet.ClearBuffer()

        # Home and wait
        self.grbl.Home()
        while self.grbl.motion_state != "idle":
            time.sleep(0.1)
        time.sleep(0.25)
        self.InkjetSetPosition()
        time.sleep(0.25)

        # CALIB HOOK — spread one powder layer before printing
        calib_layer_thickness = float(self.form.motion_layer_thickness.value()) * 0.05
        print(f"CALIB: Spreading powder layer (thickness={calib_layer_thickness:.2f} mm)")
        self.grbl.NewLayer(calib_layer_thickness)
        while self.grbl.nl_state == 0:  # same polling pattern as main print loop
            time.sleep(0.1)
        print("CALIB: Powder layer spread done")

        # Wait for GRBL to fully settle after spreading before starting inkjet sweeps
        while self.grbl.motion_state != "idle":
            time.sleep(0.1)
        time.sleep(0.5)
        self.InkjetSetPosition()
        time.sleep(0.25)

        # 4. Print single layer — find X sweep bounds
        sweep_x_min = 0
        sweep_x_max = 0
        temp_break_loop = 0
        for h in range(self.image_size_x):
            for w in range(self.image_size_y):
                if calib_array[h][w] != 0:
                    sweep_x_min = h
                    temp_break_loop = 1
                    break
            if temp_break_loop:
                break
        temp_break_loop = 0
        for h in reversed(range(self.image_size_x)):
            for w in range(self.image_size_y):
                if calib_array[h][w] != 0:
                    sweep_x_max = h
                    temp_break_loop = 1
                    break
            if temp_break_loop:
                break

        sweep_x_size = sweep_x_max - sweep_x_min
        sweeps = int(sweep_x_size / self.printing_sweep_size)
        if sweep_x_size % self.printing_sweep_size != 0:
            sweeps += 1

        sweep_x_pix = sweep_x_max - self.printing_sweep_size
        for _ in range(sweeps):
            sweep_x_pos = (
                sweep_x_pix * self.pixel_to_pos_multiplier
                + self.build_center_x
                - self.svg_offset_x
            )
            # Y sweep bounds
            sweep_y_min = 0
            temp_break_loop = 0
            for w in range(self.image_size_y):
                for h in range(int(sweep_x_pix), int(sweep_x_pix + self.printing_sweep_size)):
                    if h > 0 and calib_array[h][w] != 0:
                        sweep_y_min = w
                        temp_break_loop = 1
                        break
                if temp_break_loop:
                    break
            sweep_y_max = 0
            temp_break_loop = 0
            for w in reversed(range(self.image_size_y)):
                for h in range(int(sweep_x_pix), int(sweep_x_pix + self.printing_sweep_size)):
                    if h > 0 and calib_array[h][w] != 0:
                        sweep_y_max = w
                        temp_break_loop = 1
                        break
                if temp_break_loop:
                    break

            sweep_y_start_pos = (
                sweep_y_min * self.pixel_to_pos_multiplier
                + self.build_center_y
                - self.svg_offset_y
                - self.acceleration_distance
            )
            sweep_y_end_pos = (
                sweep_y_max * self.pixel_to_pos_multiplier
                + self.build_center_y
                - self.svg_offset_y
                + self.acceleration_distance
            )

            # Fill inkjet buffer
            temp_line_array = zeros(self.printing_sweep_size)
            temp_line_history = B64.B64ToArray(temp_line_array)
            temp_line_string = temp_line_history
            temp_pos = (
                (sweep_y_min - 1) * self.pixel_to_pos_multiplier
                + self.build_center_y
                - self.svg_offset_y
            ) * 1000
            self.inkjet.SerialWriteBufferRaw(
                "SBR " + B64.B64ToSingle(temp_pos) + " " + temp_line_string
            )
            for w in range(sweep_y_min, sweep_y_max):
                temp_counter = 0
                for h in range(int(sweep_x_pix), int(sweep_x_pix + self.printing_sweep_size)):
                    temp_line_array[temp_counter] = (
                        calib_array[h][w] if h >= 0 else 0
                    )
                    temp_counter += 1
                new_str = B64.B64ToArray(temp_line_array)
                if new_str != temp_line_history:
                    temp_line_history = new_str
                    temp_pos = (
                        w * self.pixel_to_pos_multiplier
                        + self.build_center_y
                        - self.svg_offset_y
                    ) * 1000
                    self.inkjet.SerialWriteBufferRaw(
                        "SBR " + B64.B64ToSingle(temp_pos) + " " + new_str
                    )
            temp_line_array = zeros(self.printing_sweep_size)
            temp_line_string = B64.B64ToArray(temp_line_array)
            temp_pos = (
                (sweep_y_max + 1) * self.pixel_to_pos_multiplier
                + self.build_center_y
                - self.svg_offset_y
            ) * 1000
            self.inkjet.SerialWriteBufferRaw(
                "SBR " + B64.B64ToSingle(temp_pos) + " " + temp_line_string
            )

            # Move to start, wait, print sweep
            self.grbl.SerialGotoXY(sweep_x_pos, sweep_y_start_pos, self.travel_speed)
            self.grbl.StatusIndexSet()
            while True:
                time.sleep(0.1)
                if self.grbl.StatusIndexChanged() == 1 and self.grbl.motion_state == "idle":
                    break
            while self.inkjet.BufferLeft() > 0:
                time.sleep(0.1)
            time.sleep(0.2)
            self.InkjetSetPosition()
            time.sleep(0.2)
            self.grbl.SerialGotoXY(sweep_x_pos, sweep_y_end_pos, self.print_speed)
            self.grbl.StatusIndexSet()
            while True:
                time.sleep(0.1)
                if self.grbl.StatusIndexChanged() == 1 and self.grbl.motion_state == "idle":
                    break

            sweep_x_pix -= self.printing_sweep_size

        # Return to home
        self.grbl.SerialGotoHome(self.travel_speed)
        self.grbl.StatusIndexSet()
        while True:
            time.sleep(0.1)
            if self.grbl.StatusIndexChanged() == 1 and self.grbl.motion_state == "idle":
                break

        # 5. Capture image via existing camera pipeline
        self.camera_window.capture_sync("calibration")

        # 6. Load frame from disk and detect circle
        img_path = os.path.join(captures_dir, "calibration.png")
        if not os.path.exists(img_path):
            print("CALIB: capture_sync did not produce calibration.png")
            QtWidgets.QMessageBox.warning(
                self.ui, "Calibration Failed", "Capture did not produce calibration.png."
            )
            return

        bgr = cv2.imread(img_path)
        if bgr is None:
            QtWidgets.QMessageBox.warning(
                self.ui, "Calibration Failed", "Could not load captured image."
            )
            return
        frame_rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)

        result = detect_circle_in_image(frame_rgb)
        if result is None:
            QtWidgets.QMessageBox.warning(
                self.ui,
                "Auto Calibration Failed",
                "Auto calibration failed.\nPlease re-run or check camera position.",
            )
            return

        cx_px, cy_px, r_px = result
        calib = compute_calibration(cx_px, cy_px, r_px)
        save_calibration(calib, captures_dir)
        print(f"CALIB: Saved calibration.npz  cx={cx_px:.1f} cy={cy_px:.1f} r={r_px:.1f}")

        self.camera_window._update_calib_status()

    # ── Config-runner helpers ──────────────────────────────────────────────────

    def _config_capture_name(self, layer_idx: int, pre_or_post: str) -> str:
        """Return capture filename stem.
        If a config run is active use the step-aware name; otherwise fall back
        to the original Layer_NNN_Spread/Printed convention.
        """
        runner = getattr(self, "_active_config_runner", None)
        if runner is None:
            suffix = "Spread" if pre_or_post == "pre" else "Printed"
            return f"Layer_{layer_idx:03d}_{suffix}"
        return runner.capture_filename(
            runner.current_step_id, layer_idx, pre_or_post, runner.current_note
        )

    def _config_log_capture(self, layer_idx: int, pre_or_post: str,
                             image_filename: str) -> None:
        """Write a config_log.csv row — only when a config run is active."""
        runner = getattr(self, "_active_config_runner", None)
        if runner is None:
            return
        step = next(
            (s for s in runner._steps if s["step_id"] == runner.current_step_id),
            None,
        )
        if step is not None:
            runner.log_capture(step, layer_idx, pre_or_post, image_filename)

    def _init_print_state(self):
        """Initialise all motion/print variables shared by both print paths.

        Called by both _PrintSVG_inner and RunConfigPrint so that
        _print_single_config_layer always finds the variables it needs.
        """
        self.build_center_x = 157.0
        self.build_center_y = 116.0
        self.print_speed    = 2200.0
        self.travel_speed   = 3000.0
        self.acceleration_distance  = 20.0
        self.printing_dpi           = int(self.imageconverter.dpi)
        self.printing_sweep_size    = int(self.printing_dpi / 2)
        self.pixel_to_pos_multiplier = 25.4 / self.printing_dpi
        self.image_size_x   = self.imageconverter.image_array_height
        self.image_size_y   = self.imageconverter.image_array_width
        self.layers         = self.imageconverter.svg_layers
        self.svg_offset_y   = self.imageconverter.svg_height / 2
        self.svg_offset_x   = self.imageconverter.svg_width  / 2
        start_layer = _builtin_max(1, _builtin_min(self.form.start_layer_spinbox.value(), self.layers))
        self.current_layer        = start_layer
        self.current_layer_height = self.imageconverter.svg_layer_height[start_layer - 1]
        self.printing_abort_flag  = 0
        self.printing_pause_flag  = 0
        return start_layer

    def RunConfigPrint(self):
        """Open a print_config.csv, build a ConfigRunner, and start the run in a thread."""
        if self.file_loaded != 2:
            QtWidgets.QMessageBox.warning(
                self.ui, "No SVG loaded",
                "Load an SVG file before starting a config print."
            )
            return
        if self.printing_state != 0:
            QtWidgets.QMessageBox.warning(
                self.ui, "Already printing", "A print is already in progress."
            )
            return
        csv_path, _ = QFileDialog.getOpenFileName(
            self.ui, "Select config CSV", "", "CSV files (*.csv)"
        )
        if not csv_path:
            return
        try:
            runner = ConfigRunner(csv_path, main_window=self)
        except Exception as e:
            QtWidgets.QMessageBox.critical(self.ui, "CSV Error", str(e))
            return
        self._active_config_runner = runner
        self._printing_stop_event  = threading.Event()
        self.printing_thread = threading.Thread(
            target=self._run_config_thread, args=(runner,), daemon=True
        )
        self.printing_thread.start()

    def _run_config_thread(self, runner: "ConfigRunner") -> None:
        try:
            if (self.file_loaded != 2
                    or self.inkjet_connection_state != 1
                    or self.grbl_connection_state != 1):
                self._print_error_signal.emit(
                    "Config print requires SVG loaded + GRBL + inkjet connected."
                )
                return

            self.printing_state = 2
            self.inkjet.ClearBuffer()
            self.grbl.Home()

            # Initialise all shared print variables (fixes AttributeError on
            # image_size_x/y, build_center, svg_offset, current_layer_height, etc.)
            start_layer = self._init_print_state()
            self.inkjet.SetDPI(self.printing_dpi)

            # Wait for homing
            while self.grbl.motion_state != "idle":
                time.sleep(0.1)
            time.sleep(0.25)
            self.InkjetSetPosition()
            time.sleep(0.25)

            # Spread first layer only when starting from layer 1
            if start_layer == 1:
                print("--- Spreading initial powder layer ---")
                self.grbl.NewLayer(self.imageconverter.svg_layer_height[0])
                while self.grbl.nl_state == 0:
                    time.sleep(0.1)
                print("--- Initial spread done ---")
            else:
                # Powder already at correct height — skip spread, unblock nl_state
                self.grbl.nl_state = 1

            runner.run()

        except Exception:
            import traceback
            msg = traceback.format_exc()
            print("CONFIG PRINT ERROR:\n" + msg)
            self._print_error_signal.emit(f"Config print error\n\n{msg}")
        finally:
            self._active_config_runner = None
            self.printing_state = 0

    def _print_single_config_layer(self, step: dict, layer_idx: int) -> None:
        """Print exactly one SVG layer using parameters already applied by ConfigRunner.

        current_layer is reset to 1 by ConfigRunner.run() at each step start,
        so every step prints the full SVG from layer 1.
        Camera captures are handled by ConfigRunner._capture, not here.
        """
        svg_layer = self.current_layer
        self.imageconverter.SVGLayerToArray(svg_layer)
        self._print_status_signal.emit(svg_layer, self.imageconverter.svg_layers)
        self.RenderOutput()
        print(f"[ConfigRunner] printing SVG layer {svg_layer} (step layer {layer_idx})")

        # Wait for previous powder spread to settle
        while self.grbl.nl_state == 0:
            time.sleep(0.1)

        self.save_reference_png(svg_layer)
        self.save_reference_svg(svg_layer)

        # Find X sweep bounds
        from numpy import zeros
        sweep_x_min, sweep_x_max = 0, 0
        flag = 0
        for h in range(self.image_size_x):
            for w in range(self.image_size_y):
                if self.imageconverter.image_array[h][w] != 0:
                    sweep_x_min = h
                    flag = 1
                    break
            if flag:
                break
        flag = 0
        for h in reversed(range(self.image_size_x)):
            for w in range(self.image_size_y):
                if self.imageconverter.image_array[h][w] != 0:
                    sweep_x_max = h
                    flag = 1
                    break
            if flag:
                break

        sweep_x_size = sweep_x_max - sweep_x_min
        sweeps = sweep_x_size // self.printing_sweep_size
        if sweep_x_size % self.printing_sweep_size != 0:
            sweeps += 1

        for _pass in range(self.layer_passes):
            sweep_x_pix = sweep_x_max - self.printing_sweep_size
            for _s in range(sweeps):
                sweep_x_pos = (
                    sweep_x_pix * self.pixel_to_pos_multiplier
                    + self.build_center_x - self.svg_offset_x
                )
                sweep_y_min, sweep_y_max = 0, 0
                flag = 0
                for w in range(self.image_size_y):
                    for h in range(int(sweep_x_pix),
                                   int(sweep_x_pix + self.printing_sweep_size)):
                        if h > 0 and self.imageconverter.image_array[h][w] != 0:
                            sweep_y_min = w
                            flag = 1
                            break
                    if flag:
                        break
                flag = 0
                for w in reversed(range(self.image_size_y)):
                    for h in range(int(sweep_x_pix),
                                   int(sweep_x_pix + self.printing_sweep_size)):
                        if h > 0 and self.imageconverter.image_array[h][w] != 0:
                            sweep_y_max = w
                            flag = 1
                            break
                    if flag:
                        break

                sweep_y_start_pos = (
                    sweep_y_min * self.pixel_to_pos_multiplier
                    + self.build_center_y - self.svg_offset_y
                    - self.acceleration_distance
                )
                sweep_y_end_pos = (
                    sweep_y_max * self.pixel_to_pos_multiplier
                    + self.build_center_y - self.svg_offset_y
                    + self.acceleration_distance
                )

                temp_arr = zeros(self.printing_sweep_size)
                temp_hist = B64.B64ToArray(temp_arr)
                temp_pos = (
                    (sweep_y_min - 1) * self.pixel_to_pos_multiplier
                    + self.build_center_y - self.svg_offset_y
                ) * 1000
                self.inkjet.SerialWriteBufferRaw(
                    "SBR " + B64.B64ToSingle(temp_pos) + " " + temp_hist
                )
                for w in range(sweep_y_min, sweep_y_max):
                    ctr = 0
                    for h in range(int(sweep_x_pix),
                                   int(sweep_x_pix + self.printing_sweep_size)):
                        temp_arr[ctr] = (
                            self.imageconverter.image_array[h][w] if h >= 0 else 0
                        )
                        ctr += 1
                    new_str = B64.B64ToArray(temp_arr)
                    if new_str != temp_hist:
                        temp_hist = new_str
                        temp_pos = (
                            w * self.pixel_to_pos_multiplier
                            + self.build_center_y - self.svg_offset_y
                        ) * 1000
                        self.inkjet.SerialWriteBufferRaw(
                            "SBR " + B64.B64ToSingle(temp_pos) + " " + new_str
                        )
                temp_arr = zeros(self.printing_sweep_size)
                temp_pos = (
                    (sweep_y_max + 1) * self.pixel_to_pos_multiplier
                    + self.build_center_y - self.svg_offset_y
                ) * 1000
                self.inkjet.SerialWriteBufferRaw(
                    "SBR " + B64.B64ToSingle(temp_pos) + " " + B64.B64ToArray(temp_arr)
                )

                self.grbl.SerialGotoXY(sweep_x_pos, sweep_y_start_pos, self.travel_speed)
                self.grbl.StatusIndexSet()
                while True:
                    time.sleep(0.1)
                    if (self.grbl.StatusIndexChanged() == 1
                            and self.grbl.motion_state == "idle"):
                        break
                while self.inkjet.BufferLeft() > 0:
                    time.sleep(0.1)
                time.sleep(0.2)
                self.InkjetSetPosition()
                time.sleep(0.2)
                self.grbl.SerialGotoXY(sweep_x_pos, sweep_y_end_pos, self.print_speed)
                self.grbl.StatusIndexSet()
                while True:
                    time.sleep(0.1)
                    if (self.grbl.StatusIndexChanged() == 1
                            and self.grbl.motion_state == "idle"):
                        break

                if self.printing_abort_flag == 1:
                    return

                sweep_x_pix -= self.printing_sweep_size

        # Return gantry home — post capture happens in ConfigRunner._capture()
        # after this function returns, so NewLayer() must come after that.
        # We store the next thickness here and let the caller trigger spreading.
        self.grbl.SerialGotoHome(self.travel_speed)
        self.grbl.StatusIndexSet()
        while True:
            time.sleep(0.1)
            if (self.grbl.StatusIndexChanged() == 1
                    and self.grbl.motion_state == "idle"):
                break

        self.current_layer += 1
        # Use svg_layers (total layers in file) as upper bound.
        # ConfigRunner resets current_layer to 1 at each step start,
        # so this correctly handles the per-step SVG replay.
        if self.current_layer <= self.imageconverter.svg_layers:
            next_h    = self.imageconverter.svg_layer_height[self.current_layer - 1]
            self._pending_layer_thickness = next_h - self.current_layer_height
            self.current_layer_height     = next_h
        else:
            self._pending_layer_thickness = None

    # ── End config-runner helpers ──────────────────────────────────────────────

    def PrintSVG(self):
        """Prints the currently loaded SVG file if present.
        This will not check powder levels, ink levels and if file is much more than theoretically possible
        """
        try:
            self._PrintSVG_inner()
        except Exception:
            import traceback
            msg = traceback.format_exc()
            print("PRINT ERROR:\n" + msg)
            layer = getattr(self, "current_layer", "?")
            total = getattr(self, "layers", "?")
            self._print_error_signal.emit(
                f"Print error (Layer {layer} / {total})\n\n{msg}"
            )
            self.printing_state = 0

    def _PrintSVG_inner(self):
        """Prints the currently loaded SVG file if present.
        This will not check powder levels, ink levels and if file is much more than theoretically possible
        """
        # Todo:
        # -Add printhead purge to the start of the print so the first sweep will work properly
        # -Re-add send code while printing. The problem with speed was traced to threading not working
        # while another thread is busy. Now there are sleep command in the While(True) blocks,
        # Giving the other threads time to do stuff.

        print("Starting print from SVG")

        # start printing if file is svg, inkjet and motion are started
        if (
            self.file_loaded == 2
            and self.inkjet_connection_state == 1
            and self.grbl_connection_state == 1
        ):
            self.printing_state = 2

            # Snapshot UI settings so mid-print UI changes don't affect this run
            self.mid_print_clean_enabled = self.mid_print_clean_chk.isChecked()
            self.clean_interval          = self.clean_interval_spin.value()

            self.inkjet.ClearBuffer()
            self.grbl.Home()

            start_layer = self._init_print_state()
            print("Starting print at height: " + str(self.current_layer_height))
            self.inkjet.SetDPI(self.printing_dpi)

            # Wait till homing is done
            while self.grbl.motion_state != "idle":
                time.sleep(0.1)

            time.sleep(0.25)  # extra delay so the system can stabilize
            self.InkjetSetPosition()  # set position
            time.sleep(0.25)  # extra delay so position can be set

            # add priming purge here, with motions to start the printhead

            # Spread the first powder layer only when starting from layer 1.
            # If resuming mid-print (start_layer > 1), powder is already at the
            # correct height — skip spreading and start printing immediately.
            if start_layer == 1:
                print("--- Spreading initial powder layer ---")
                self.grbl.NewLayer(self.imageconverter.svg_layer_height[0])
                while self.grbl.nl_state == 0:
                    time.sleep(0.1)
                print("--- Initial spread done, capturing photo ---")
                if hasattr(self, "camera_window"):
                    self.save_reference_png(self.current_layer)
                    self.save_reference_svg(self.current_layer)
                    _fname = self._config_capture_name(0, "pre")
                    self.camera_window.capture_sync(_fname)
                    self._config_log_capture(0, "pre", _fname)

            # When resuming mid-print, no NewLayer() was called above, so
            # nl_state may still be 0 — force it to 1 to skip the initial wait.
            if start_layer > 1:
                self.grbl.nl_state = 1

            # start printing
            while True:
                # load proper layer
                self.imageconverter.SVGLayerToArray(self.current_layer)
                self._print_status_signal.emit(self.current_layer, self.layers)
                self.RenderOutput()  # render image
                print(f"--- Printing layer {self.current_layer} / {self.layers} ---")

                # hold firmware while a new layer is being deposited
                while self.grbl.nl_state == 0:  # hold firmware till layer is done
                    time.sleep(0.1)
                    pass

                # v1.1.5 HOOK — save image_array for current layer as reference PNG + SVG
                if hasattr(self, "camera_window"):
                    self.save_reference_png(self.current_layer)
                    self.save_reference_svg(self.current_layer)

                # --- Photo After Recoating (Spread) ---
                if hasattr(self, "camera_window"):
                    _fname = self._config_capture_name(self.current_layer, "pre")
                    self.camera_window.capture_sync(_fname)
                    self._config_log_capture(self.current_layer, "pre", _fname)
                # ----------------------------------------

                # check abort state
                if self.printing_abort_flag == 1:
                    break

                # calculate start and end in gantry direction
                # look for X-min and X-max in image
                self.sweep_x_min = 0
                self.sweep_x_max = 0
                temp_break_loop = 0
                # loop through image
                for h in range(0, self.image_size_x):
                    for w in range(0, self.image_size_y):
                        if self.imageconverter.image_array[h][w] != 0:
                            self.sweep_x_min = h
                            temp_break_loop = 1
                            print("X-min on row: " + str(h))
                            break
                    if temp_break_loop == 1:
                        break
                temp_break_loop = 0
                for h in reversed(range(0, self.image_size_x)):
                    for w in range(0, self.image_size_y):
                        if self.imageconverter.image_array[h][w] != 0:
                            self.sweep_x_max = h
                            temp_break_loop = 1
                            print("X-max on row: " + str(h))
                            break
                    if temp_break_loop == 1:
                        break

                # calculate how many sweeps are required
                self.sweep_x_size = self.sweep_x_max - self.sweep_x_min
                print("Sweep size in pixels: " + str(self.sweep_x_size))
                if self.sweep_x_size % int(self.printing_sweep_size) == 0:
                    temp_round = 1
                else:
                    temp_round = 0
                self.sweeps = int(self.sweep_x_size / self.printing_sweep_size)
                if temp_round == 0:
                    self.sweeps += 1
                print("Sweeps in layer: " + str(self.sweeps))

                # calculate starting position and pixel
                # printer prints from x max to x min because of new layer reasons
                self.sweep_x_pix = self.sweep_x_max - self.printing_sweep_size

                # load sweep by sweep
                for _layer_pass in range(getattr(self, "layer_passes", 1)):
                    self.sweep_x_pix = self.sweep_x_max - self.printing_sweep_size
                    for L in range(self.sweeps):
                        print("printing sweep" + str(L))

                        # set X position
                        self.sweep_x_pos = (
                            (self.sweep_x_pix * self.pixel_to_pos_multiplier)
                            + self.build_center_x
                            - self.svg_offset_x
                        )

                        # calculate start and end in sweep direction
                        temp_break_loop = 0
                        for w in range(self.image_size_y):
                            for h in range(
                                int(self.sweep_x_pix),
                                int(self.sweep_x_pix + self.printing_sweep_size),
                            ):
                                if h > 0:  # if h is within bounds
                                    if self.imageconverter.image_array[h][w] != 0:
                                        self.sweep_y_min = w
                                        temp_break_loop = 1
                                        break
                            if temp_break_loop == 1:
                                break
                        # get Y max
                        temp_break_loop = 0
                        for w in reversed(range(self.image_size_y)):
                            for h in range(
                                int(self.sweep_x_pix),
                                int(self.sweep_x_pix + self.printing_sweep_size),
                            ):
                                if h > 0:  # if h is within bounds
                                    if self.imageconverter.image_array[h][w] != 0:
                                        self.sweep_y_max = w
                                        temp_break_loop = 1
                                        break
                            if temp_break_loop == 1:
                                break

                        # calculate position
                        self.sweep_y_start_pix = self.sweep_y_min
                        self.sweep_y_end_pix = self.sweep_y_max
                        self.sweep_y_start_pos = (
                            (self.sweep_y_start_pix * self.pixel_to_pos_multiplier)
                            + self.build_center_y
                            - self.svg_offset_y
                            - self.acceleration_distance
                        )
                        self.sweep_y_end_pos = (
                            (self.sweep_y_end_pix * self.pixel_to_pos_multiplier)
                            + self.build_center_y
                            - self.svg_offset_y
                            + self.acceleration_distance
                        )
                        print(
                            "Sweep from: "
                            + str(self.sweep_y_start_pos)
                            + ", to: "
                            + str(self.sweep_y_end_pos)
                        )

                        # fill inkjet buffer ------------------------------------------
                        print("Filling local buffer with inkjet")
                        temp_line_history = ""
                        temp_line_string = ""
                        temp_line_array = zeros(self.printing_sweep_size)
                        temp_line_history = B64.B64ToArray(
                            temp_line_array
                        )  # make first history 0
                        temp_line_string = temp_line_history  # make string also 0

                        # add all of starter cap at the front
                        temp_pos = (
                            (
                                (self.sweep_y_start_pix - 1)
                                * self.pixel_to_pos_multiplier
                            )
                            + self.build_center_y
                            - self.svg_offset_y
                        )
                        temp_pos *= 1000  # printhead pos is in microns
                        temp_b64_pos = B64.B64ToSingle(temp_pos)  # make position value
                        self.inkjet.SerialWriteBufferRaw(
                            "SBR " + str(temp_b64_pos) + " " + str(temp_line_string)
                        )
                        print(
                            "SBR "
                            + str(temp_b64_pos)
                            + " "
                            + str(temp_line_string)
                            + ", real pos: "
                            + str(temp_pos)
                        )
                        for w in range(
                            self.sweep_y_start_pix, self.sweep_y_end_pix
                        ):  # off by one error
                            # print("Parsing line: " + str(w))
                            temp_line_changed = 0  # reset changed
                            temp_counter = 0
                            for h in range(
                                int(self.sweep_x_pix),
                                int(self.sweep_x_pix + self.printing_sweep_size),
                            ):
                                # loop through all pixels to make a new burst
                                # while counting down h will become negative, breaking the array
                                # if h lower than 0, value defaults to 0
                                if h >= 0:
                                    temp_line_array[temp_counter] = (
                                        self.imageconverter.image_array[h][w]
                                    )  # write array value to temp
                                else:
                                    temp_line_array[temp_counter] = 0
                                temp_counter += 1
                            temp_line_string = B64.B64ToArray(
                                temp_line_array
                            )  # convert to string
                            if temp_line_string != temp_line_history:
                                # print("line changed on pos: " + str(w))
                                temp_line_history = temp_line_string
                                # add line to buffer
                                temp_pos = (
                                    (w * self.pixel_to_pos_multiplier)
                                    + self.build_center_y
                                    - self.svg_offset_y
                                )
                                temp_pos *= 1000  # printhead pos is in microns
                                temp_b64_pos = B64.B64ToSingle(
                                    temp_pos
                                )  # make position value
                                self.inkjet.SerialWriteBufferRaw(
                                    "SBR "
                                    + str(temp_b64_pos)
                                    + " "
                                    + str(temp_line_string)
                                )
                                print(
                                    "SBR "
                                    + str(temp_b64_pos)
                                    + " "
                                    + str(temp_line_string)
                                    + ", real pos: "
                                    + str(temp_pos)
                                )

                        # add all off cap at the end of the image
                        temp_line_array = zeros(self.printing_sweep_size)
                        temp_line_string = B64.B64ToArray(temp_line_array)
                        temp_pos = (
                            ((self.sweep_y_end_pix + 1) * self.pixel_to_pos_multiplier)
                            + self.build_center_y
                            - self.svg_offset_y
                        )
                        temp_pos *= 1000  # printhead pos is in microns
                        temp_b64_pos = B64.B64ToSingle(temp_pos)  # make position value
                        self.inkjet.SerialWriteBufferRaw(
                            "SBR " + str(temp_b64_pos) + " " + str(temp_line_string)
                        )
                        print(
                            "SBR "
                            + str(temp_b64_pos)
                            + " "
                            + str(temp_line_string)
                            + ", real pos: "
                            + str(temp_pos)
                        )

                        print("Making printing buffer done: ")
                        # end of fill inkjet buffer -----------------------------------
                        # move to start of sweep position
                        self.grbl.SerialGotoXY(
                            self.sweep_x_pos, self.sweep_y_start_pos, self.travel_speed
                        )
                        self.grbl.StatusIndexSet()  # set current status index
                        while True:  # wait till the printhead is at start position
                            time.sleep(0.1)
                            if (
                                self.grbl.StatusIndexChanged() == 1
                                and self.grbl.motion_state == "idle"
                            ):
                                # print("break conditions for print while loop")
                                break  # break if exit conditions met

                        # wait till inkjet is loaded and motion is done
                        while self.inkjet.BufferLeft() > 0:
                            time.sleep(0.1)
                            pass

                        # set current position to inkjet
                        print("LABABBUBU")
                        # self.InkjetPreheat()
                        time.sleep(0.2)
                        self.InkjetSetPosition()
                        time.sleep(0.2)
                        print("BRBNLENAUBAU")

                        # fill motion buffer with end of sweep
                        self.grbl.SerialGotoXY(
                            self.sweep_x_pos, self.sweep_y_end_pos, self.print_speed
                        )
                        self.grbl.StatusIndexSet()  # set current status index
                        while True:  # wait till the printhead is at home
                            time.sleep(0.1)
                            if (
                                self.grbl.StatusIndexChanged() == 1
                                and self.grbl.motion_state == "idle"
                            ):
                                # print("break conditions for print while loop")
                                break  # break if exit conditions met

                        # check pause state
                        # if pause state, go to home pos and wait till restart
                        if self.printing_pause_flag == 1:
                            # goto home and wait to reach position
                            self.grbl.SerialGotoHome(self.travel_speed)
                            self.grbl.StatusIndexSet()  # set current status index
                            while True:  # wait till the printhead is at home
                                if (
                                    self.grbl.StatusIndexChanged() == 1
                                    and self.grbl.motion_state == "idle"
                                    and self.printing_pause_flag == 0
                                ):
                                    # print("break conditions for print while loop")
                                    break  # break if exit conditions met

                        # check abort state
                        if self.printing_abort_flag == 1:
                            break

                        # set next sweep
                        self.sweep_x_pix = self.sweep_x_pix - self.printing_sweep_size

                        # return to load sweep

                # return to load layer
                self.current_layer += 1
                self._MaybeCleanMidPrint()
                if self.current_layer >= self.layers:
                    print("Last layer printed")
                    # Move to home and take final photo
                    print("Moving to home for photo...")
                    self.grbl.SerialGotoHome(self.travel_speed)
                    self.grbl.StatusIndexSet()
                    while True:
                        time.sleep(0.1)
                        if (
                            self.grbl.StatusIndexChanged() == 1
                            and self.grbl.motion_state == "idle"
                        ):
                            break
                    if hasattr(self, "camera_window"):
                        _fname = self._config_capture_name(self.current_layer - 1, "post")
                        self.camera_window.capture_sync(_fname)
                        self._config_log_capture(self.current_layer - 1, "post", _fname)
                    break

                # check exit conditions
                if self.printing_abort_flag == 1:
                    print("Print aborted")
                    break

                # --- Photo After Printing (Ink Deposition) ---
                # Capture immediately after ink sweeps, before NewLayer() starts spreading
                if hasattr(self, "camera_window"):
                    self.grbl.SerialGotoHome(self.travel_speed)
                    self.grbl.StatusIndexSet()
                    while True:
                        time.sleep(0.1)
                        if (
                            self.grbl.StatusIndexChanged() == 1
                            and self.grbl.motion_state == "idle"
                        ):
                            break
                    _fname = self._config_capture_name(self.current_layer - 1, "post")
                    self.camera_window.capture_sync(_fname)
                    self._config_log_capture(self.current_layer - 1, "post", _fname)

                # Add next layer — nl_state set to 0 inside NewLayer()
                temp_layer_thickness = (
                    self.imageconverter.svg_layer_height[self.current_layer]
                    - self.current_layer_height
                )
                print("Adding new layer, thickness: " + str(temp_layer_thickness))
                self.current_layer_height = self.imageconverter.svg_layer_height[
                    self.current_layer
                ]
                self.grbl.NewLayer(temp_layer_thickness)

            # if all layers printed or stop button pressed, exit
            if (
                self.grbl_connection_state == 1
            ):  # conditional for testing, only wait for goto home if there is motion to wait on
                self.grbl.SerialGotoHome(self.travel_speed)
                self.grbl.StatusIndexSet()  # set current status index
                while True:  # wait till the printhead is at home
                    if (
                        self.grbl.StatusIndexChanged() == 1
                        and self.grbl.motion_state == "idle"
                    ):
                        # print("break conditions for print while loop")
                        break  # break if exit conditions met

            self.printing_state = 0  # set printing to stopped

    def PrintArray(self):
        """Prints the current converted image array, only works if both inkjet and motion are connected"""
        try:
            self._PrintArray_inner()
        except Exception:
            import traceback
            msg = traceback.format_exc()
            print("PRINT ERROR:\n" + msg)
            self._print_error_signal.emit(f"Print error\n\n{msg}")
            self.printing_state = 0

    def _PrintArray_inner(self):
        """Prints the current converted image array, only works if both inkjet and motion are connected"""
        # y is sweep direction, x is gantry direction
        # Width is Y direction, height is X direction

        # check if printhead and motion are connected
        if (
            self.grbl_connection_state == 0
        ):  # do not continue if motion is not connected
            return
        # inkjet is ignored for now

        # make universal variables
        self.inkjet_line_buffer = []  # buffer storing the print lines
        self.inkjet_lines_left = 0  # the number of lines in buffer
        self.inkjet_line_history = ""  # the last burst line sent to buffer

        # print array and print svg have different speeds...
        self.travel_speed = 3000.0
        self.print_speed = 7000

        self.inkjet.ClearBuffer()  # clear inkjet buffer on HP45
        # self.inkjet.Prime(100) #prime added here
        # print("i'm pissing but its a png")

        self.grbl.Home()  # home gantry

        # look for X-min and X-max in image
        self.sweep_x_min = 0
        self.sweep_x_max = 0
        temp_break_loop = 0
        # loop through image
        for h in range(0, self.imageconverter.image_array_height):
            for w in range(0, self.imageconverter.image_array_width):
                if self.imageconverter.image_array[h][w] != 0:
                    self.sweep_x_min = 2 * h  # og just h
                    temp_break_loop = 1
                    print("X-min on row: " + str(h))
                    break
            if temp_break_loop == 1:
                break
        temp_break_loop = 0
        for h in reversed(range(0, self.imageconverter.image_array_height)):
            for w in range(0, self.imageconverter.image_array_width):
                if self.imageconverter.image_array[h][w] != 0:
                    self.sweep_x_max = 2 * h
                    temp_break_loop = 1
                    print("X-max on row: " + str(h))
                    break
            if temp_break_loop == 1:
                break

        # set X start pixel, X pixel step (using current DPI)
        self.sweep_size = int(
            self.imageconverter.GetDPI() / 2
        )  # get sweep size (is halve of DPI)
        print("Sweep size: " + str(self.sweep_size))
        # determine pixel to position multiplier (in millimeters)
        self.pixel_to_pos_multiplier = 25.4 / self.imageconverter.GetDPI()

        # determine x and y start position (in millimeters)
        self.y_start_pos = 100  # OG 100.0
        self.x_start_pos = 150  # OG 150.0
        self.y_acceleration_distance = 25.0

        self.sweep_x_min_pos = self.sweep_x_min

        ###loop through all sweeps
        temp_sweep_stop = 0
        for _layer_pass in range(getattr(self, "layer_passes", 1)):
            self.sweep_x_min_pos = self.sweep_x_min
            temp_sweep_stop = 0
            while temp_sweep_stop == 0:
                # determine if there still is a sweep left
                # determine X-start and X end of sweep
                if self.sweep_x_min_pos + self.sweep_size <= self.sweep_x_max:
                    self.sweep_x_max_pos = self.sweep_x_min_pos + self.sweep_size
                else:
                    self.sweep_x_max_pos = (
                        self.sweep_x_max
                    )  # set max of image as max pos
                    temp_sweep_stop = 1  # mark last loop
                print(
                    "Sweep from: "
                    + str(self.sweep_x_min_pos)
                    + ", to: "
                    + str(self.sweep_x_max_pos)
                )

                # Look for Y min and Y max in sweep
                self.sweep_y_min = 0
                self.sweep_y_max = 0
                # get Y min
                temp_break_loop = 0
                for w in range(self.imageconverter.image_array_width):
                    for h in range(self.sweep_x_min_pos, self.sweep_x_max_pos):
                        if self.imageconverter.image_array[h][w] != 0:
                            self.sweep_y_min = w
                            temp_break_loop = 1
                            break
                    if temp_break_loop == 1:
                        break
                # get Y max
                temp_break_loop = 0
                for w in reversed(range(self.imageconverter.image_array_width)):
                    for h in range(self.sweep_x_min_pos, self.sweep_x_max_pos):
                        if self.imageconverter.image_array[h][w] != 0:
                            self.sweep_y_max = w
                            temp_break_loop = 1
                            break
                    if temp_break_loop == 1:
                        break
                print(
                    "sweep Y min: "
                    + str(self.sweep_y_min)
                    + ", Y max: "
                    + str(self.sweep_y_max)
                )

                # determine printing direction (if necessary)
                self.printing_direction = 1  # only 1 for now

                # Set Y at starting and end position
                if self.printing_direction == 1:
                    self.y_printing_start_pos = (
                        self.sweep_y_min * self.pixel_to_pos_multiplier
                    )
                    self.y_printing_start_pos += (
                        self.y_start_pos - self.y_acceleration_distance
                    )
                    self.y_printing_end_pos = (
                        self.sweep_y_max * self.pixel_to_pos_multiplier
                    )
                    self.y_printing_end_pos += (
                        self.y_start_pos + self.y_acceleration_distance
                    )
                    print(
                        "Sweep ranges from: "
                        + str(self.y_printing_start_pos)
                        + "mm, to: "
                        + str(self.y_printing_end_pos)
                        + "mm"
                    )

                # set X position
                self.x_printing_pos = (
                    self.sweep_x_min_pos * self.pixel_to_pos_multiplier
                )
                self.x_printing_pos += self.x_start_pos

                # fill local print buffer with lines
                print("Filling local buffer with inkjet")
                temp_line_history = ""
                temp_line_string = ""
                temp_line_array = zeros(self.sweep_size)
                temp_line_history = B64.B64ToArray(
                    temp_line_array
                )  # make first history 0
                temp_line_string = temp_line_history  # make string also 0
                # add all of starter cap at the front
                if self.printing_direction == 1:
                    temp_pos = (
                        (self.sweep_y_min - 1) * self.pixel_to_pos_multiplier
                    ) + self.y_start_pos
                    temp_pos *= 1000  # printhead pos is in microns
                    temp_b64_pos = B64.B64ToSingle(temp_pos)  # make position value
                    self.inkjet_line_buffer.append(
                        "SBR " + str(temp_b64_pos) + " " + str(temp_line_string)
                    )
                    self.inkjet_lines_left += 1

                for w in range(self.sweep_y_min, self.sweep_y_max):
                    # print("Parsing line: " + str(w))
                    temp_line_changed = 0  # reset changed
                    temp_counter = 0
                    for h in range(self.sweep_x_min_pos, self.sweep_x_max_pos):
                        # loop through all pixels to make a new burst
                        temp_line_array[temp_counter] = self.imageconverter.image_array[
                            h
                        ][w]  # write array value to temp

                        temp_counter += 1
                    temp_line_string = B64.B64ToArray(
                        temp_line_array
                    )  # convert to string
                    if temp_line_string != temp_line_history:  ##nullifying this line
                        # print("line changed on pos: " + str(w))
                        temp_line_history = temp_line_string
                        # add line to buffer
                        temp_pos = (w * self.pixel_to_pos_multiplier) + self.y_start_pos
                        temp_pos *= 1000  # printhead pos is in microns
                        temp_b64_pos = B64.B64ToSingle(temp_pos)  # make position value
                        self.inkjet_line_buffer.append(
                            "SBR " + str(temp_b64_pos) + " " + str(temp_line_string)
                        )
                        self.inkjet_lines_left += 1

                # add all off cap at the end of the image
                temp_line_array = zeros(self.sweep_size)
                temp_line_string = B64.B64ToArray(temp_line_array)
                if self.printing_direction == 1:
                    temp_pos = (
                        (self.sweep_y_max + 1) * self.pixel_to_pos_multiplier
                    ) + self.y_start_pos
                    temp_pos *= 1000  # printhead pos is in microns
                    temp_b64_pos = B64.B64ToSingle(temp_pos)  # make position value
                    self.inkjet_line_buffer.append(
                        "SBR " + str(temp_b64_pos) + " " + str(temp_line_string)
                    )
                    self.inkjet_lines_left += 1

                print("Making printing buffer done: ")
                # print(self.inkjet_line_buffer)

                # wait till the head is idle
                while self.grbl.motion_state != "idle":
                    nothing = 0
                print("break from idle, moving to filling buffers")

                # match inkjet and printer pos
                self.InkjetSetPosition()

                # Fill inkjet buffer with with sweep lines
                print("Filling inkjet buffer")
                # start filling the inkjet buffer on the HP45 lines
                temp_lines_sent = 0
                while True:
                    if self.inkjet_lines_left > 0:
                        self.inkjet.SerialWriteBufferRaw(self.inkjet_line_buffer[0])
                        # time.sleep(0.001) #this is a good replacement for print, but takes forever
                        print(
                            str(self.inkjet_line_buffer[0])
                        )  # some sort of delay is required, else the function gets filled up too quickly. Will move to different buffer later
                        del self.inkjet_line_buffer[0]  # remove sent line
                        self.inkjet_lines_left -= 1
                        temp_lines_sent += 1
                    else:
                        break

                # send motion lines
                print("Filling motion buffer")
                self.grbl.SerialGotoXY(
                    self.x_printing_pos, self.y_printing_start_pos, self.travel_speed
                )
                self.grbl.SerialGotoXY(
                    self.x_printing_pos, self.y_printing_end_pos, self.print_speed
                )
                self.grbl.StatusIndexSet()  # set current status index

                while True:
                    if (
                        self.grbl.StatusIndexChanged() == 1
                        and self.grbl.motion_state == "idle"
                    ):
                        print("break conditions for print while loop")
                        break  # break if exit conditions met

                self.sweep_x_min_pos += self.sweep_size
        ###end of loop through sweep
        # repeat loop until all sweeps are finished
        print("Printing done")
        # home gantry
        # self.grbl.Home() #home gantry

    def closeEvent(self, event):
        """Clean up all threads then exit the process on window close."""
        if hasattr(self, "_grbl_stop_event"):
            self._grbl_stop_event.set()
        if hasattr(self, "_inkjet_stop_event"):
            self._inkjet_stop_event.set()
        self.printing_state = 0
        self.printing_abort_flag = 1
        event.accept()
        sys.exit(0)

    def SavePng(self):
        """Saves current SVG to array of bitmap images, enables camera"""
        if self.file_loaded == 2:  # if a file is present
            if not os.path.exists("demo"):
                os.makedirs("demo")  # make demo folder

            # run through all layers of the file
            for L in range(self.imageconverter.svg_layers):
                # save each of the files to the demo folder
                print("Layer" + str(L))
                self.imageconverter.SVGLayerToArray(L)
                self.RenderOutput()  # render image
                self.imageconverter.output_image.save(
                    "demo\\Layer" + str(L) + ".png", "PNG"
                )


if __name__ == "__main__":
    import traceback

    def excepthook(exc_type, exc_value, exc_tb):
        traceback.print_exception(exc_type, exc_value, exc_tb)
        QtWidgets.QMessageBox.critical(
            None,
            "Unhandled Error",
            "".join(traceback.format_exception(exc_type, exc_value, exc_tb)),
        )

    sys.excepthook = excepthook

    # Disable Qt's automatic OS DPI scaling so QSS px values (oasis_style.qss)
    # render the same physical size on every laptop, regardless of its
    # Windows display scale (100%/125%/150%/...).
    QtWidgets.QApplication.setAttribute(QtCore.Qt.AA_DisableHighDpiScaling, True)

    app = QtWidgets.QApplication(sys.argv)
    gui = MainWindow()
    sys.exit(app.exec_())
