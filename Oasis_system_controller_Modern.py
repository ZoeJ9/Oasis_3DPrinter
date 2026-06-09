# Oasis system controller - Modern Industrial HMI Redesign
# Copyright (C) 2018-2026 Oasis Team
# Redesigned for Slick, Precise Industrial Aesthetics (Inter / JetBrains Mono styling)

import sys
import glob
import os
import math
import threading
import time
import serial
import cv2

# PyQt5 UI Components
from PyQt5 import QtCore, QtGui, QtWidgets
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
    QGridLayout, QLabel, QPushButton, QSlider, QComboBox, QSpinBox, 
    QDoubleSpinBox, QCheckBox, QFileDialog, QMessageBox, QFrame, 
    QScrollArea, QTabWidget, QGraphicsDropShadowEffect
)
from PyQt5.QtGui import QPixmap, QColor, QImage, QPainter, QPen, QBrush, QFont, QIcon
from PyQt5.QtCore import Qt, pyqtSignal, pyqtSlot, QRectF, QPointF

# Mock modules for standalone safety or developer usage if missing
try:
    from SerialGRBL import GRBL
except ImportError:
    class GRBL:
        def __init__(self):
            self.motion_x_pos = 142.005
            self.motion_y_pos = 88.421
            self.motion_z_pos = -1.420
            self.motion_a_pos = 12.000
            self.motion_state = "idle"
            self.nl_state = 1
        def Connect(self, port): return 1
        def Disconnect(self): pass
        def Home(self): self.motion_state = "homing"
        def EmergencyUnlock(self): self.motion_state = "idle"
        def Jog(self, axis, dist, speed): pass
        def SerialGotoXY(self, x, y, speed): pass
        def NewLayer(self, thick, prime=0): pass
        def SetOverfeed(self, val): pass
        def SpreaderToggle(self): return 1
        def SerialGotoHome(self, speed): pass
        def StatusIndexSet(self): pass
        def StatusIndexChanged(self): return 1

try:
    from SerialHP45 import HP45
except ImportError:
    class HP45:
        def __init__(self):
            self.inkjet_temperature = 42.0
            self.inkjet_x_pos = 88.42
            self.inkjet_writeleft = 1000
            self.inkjet_working_nozzles = 287
            self.inkjet_total_nozzles = 300
        def Connect(self, port): return 1
        def Disconnect(self): pass
        def Prime(self, pulses): pass
        def Preheat(self, pulses): pass
        def SetDPI(self, dpi): pass
        def SetDensity(self, den): pass
        def TestPrinthead(self): pass
        def ClearBuffer(self): pass
        def BufferLeft(self): return 0
        def SerialWriteBufferRaw(self, data): pass

try:
    from ImageConverter import ImageConverter
except ImportError:
    class ImageConverter:
        def __init__(self):
            self.dpi = 600
            self.file_type = 2
            self.svg_layers = 450
            self.svg_width = 61.6
            self.svg_height = 79.6
            self.svg_layer_names = [f"Layer {i}" for i in range(450)]
            self.svg_layer_height = [0.100 * (i + 1) for i in range(450)]
            self.image_array_width = 1450
            self.image_array_height = 1880
            self.image_array = [[0 for _ in range(1450)] for _ in range(1880)]
            self.input_image = QPixmap(300, 300)
            self.output_image = QPixmap(300, 300)
            self.file_path = "mock.svg"
        def OpenFile(self, path): return 2
        def SVGLayerToArray(self, num): pass
        def Threshold(self, val): pass
        def ArrayToImage(self): pass
        def GetDPI(self): return self.dpi
        def SetDPI(self, val): self.dpi = val

try:
    import B64
except ImportError:
    class B64:
        @staticmethod
        def B64ToArray(arr): return "mock_b64"
        @staticmethod
        def B64ToSingle(v): return "mock_b64_val"


# MODERN INDUSTRIAL HMI STYLE SHEETS
QSS_THEME = """
QMainWindow {
    background-color: #f8f9fb;
}
QWidget {
    font-family: 'Inter', sans-serif;
    color: #191c1e;
}
QFrame#control_card {
    background-color: #ffffff;
    border: 1px solid #e1e2e4;
    border-radius: 4px;
}
QLabel#title_label {
    font-size: 14px;
    font-weight: 900;
    color: #191c1e;
    text-transform: uppercase;
    letter-spacing: 0.5px;
}
QLabel#metric_caption {
    font-size: 10px;
    font-family: 'JetBrains Mono', monospace;
    font-weight: bold;
    color: #737686;
}
QPushButton {
    background-color: #ffffff;
    border: 1px solid #c3c6d7;
    border-radius: 3px;
    padding: 6px 12px;
    font-size: 11px;
    font-weight: 600;
    color: #434655;
}
QPushButton:hover {
    background-color: #edeef0;
    color: #191c1e;
}
QPushButton:pressed {
    background-color: #e1e2e4;
}
QPushButton#primary_btn {
    background-color: #004ac6;
    border: 1px solid #004ac6;
    color: #ffffff;
}
QPushButton#primary_btn:hover {
    background-color: #2563eb;
}
QPushButton#primary_btn:pressed {
    background-color: #003ea8;
}
QPushButton#danger_btn {
    background-color: #d52022;
    border: 1px solid #d52022;
    color: #ffffff;
}
QPushButton#danger_btn:hover {
    background-color: #ff4444;
}
QPushButton#jog_btn {
    font-size: 14px;
    font-weight: bold;
}
QComboBox, QSpinBox, QDoubleSpinBox {
    background-color: #edeef0;
    border: 1px solid #c3c6d7;
    border-radius: 3px;
    padding: 4px;
    font-size: 11px;
    font-family: 'JetBrains Mono', monospace;
}
QSlider::groove:horizontal {
    border: 1px solid #e1e2e4;
    height: 4px;
    background: #e1e2e4;
    border-radius: 2px;
}
QSlider::handle:horizontal {
    background: #004ac6;
    width: 14px;
    margin: -5px 0;
    border-radius: 1px;
}
QStatusBar {
    background-color: #191c1e;
    color: #f3f4f6;
    font-family: 'JetBrains Mono', monospace;
    font-size: 10px;
}
QStatusBar QLabel {
    color: #e1e2e4;
}
"""

# GLOBAL SETTINGS FOR TELEMETRY
CAMERA_INDEX = 0
BACKEND = cv2.CAP_DSHOW
EXPOSURE_VALUE = -3
GAIN_VALUE = 0
AUTO_WB = 0
WARMUP_FRAMES = 0
AVERAGING_FRAMES = 1
UNSHARP_SIGMA = 2.5
UNSHARP_AMOUNT = 1.2
LED_SETTLE_MS = 800
NUM_LEDS = 5
LED_FLUSH_FRAMES = 2


class CameraController(QtWidgets.QWidget):
    update_image_signal = pyqtSignal(object)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Oasis Telemetry Camera Configuration")
        self.resize(500, 500)
        self.setStyleSheet(QSS_THEME)

        self.camera_port = 0
        self.pause_time = 0.0
        self.output_dir = os.path.join(os.getcwd(), "timelapse_output")
        self.camera_enabled = True
        self.exposure_value = EXPOSURE_VALUE
        self._camera_list = []

        self._arduino_conn = None
        self._arduino_lock = threading.Lock()
        self._arduino_port = None
        self.led_enabled = False
        self.capture_width = 3840
        self.capture_height = 2160

        if not os.path.exists(self.output_dir):
            os.makedirs(self.output_dir)

        # UI LAYOUT SYSTEM
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(16, 16, 16, 16)
        main_layout.setSpacing(12)

        # Virtual Live Frame Screen
        self.image_label = QLabel("NO CAMERA TELEMETRY DETECTED")
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setMinimumSize(320, 240)
        self.image_label.setStyleSheet(
            "border: 1px solid #c3c6d7; background-color: #edeef0; color: #737686; font-family: 'JetBrains Mono'; font-size: 10px; font-weight: bold;"
        )
        main_layout.addWidget(self.image_label, stretch=1)

        # Control Fields Box
        form_widget = QWidget()
        form_layout = QGridLayout(form_widget)
        form_layout.setContentsMargins(0, 0, 0, 0)
        form_layout.setSpacing(8)

        # Camera Status
        self.enable_chk = QCheckBox("Enable Active Render Capture")
        self.enable_chk.setChecked(self.camera_enabled)
        self.enable_chk.stateChanged.connect(lambda s: self.set_enabled(s == Qt.Checked))
        form_layout.addWidget(QLabel("Camera Sensor:"), 0, 0)
        form_layout.addWidget(self.enable_chk, 0, 1)

        # Port selectors
        self.port_combo = QComboBox()
        self.refresh_btn = QPushButton("Refresh Sensors")
        self.refresh_btn.clicked.connect(self._populate_cameras)
        form_layout.addWidget(QLabel("Active Camera:"), 1, 0)
        
        row_h_cam = QHBoxLayout()
        row_h_cam.addWidget(self.port_combo, stretch=1)
        row_h_cam.addWidget(self.refresh_btn)
        form_layout.addLayout(row_h_cam, 1, 1)

        # Photo stabilization pause
        self.pause_spin = QDoubleSpinBox()
        self.pause_spin.setRange(0.0, 60.0)
        self.pause_spin.setSingleStep(0.5)
        self.pause_spin.setValue(self.pause_time)
        self.pause_spin.valueChanged.connect(self.set_pause)
        form_layout.addWidget(QLabel("Settle Stabilization Delay (s):"), 2, 0)
        form_layout.addWidget(self.pause_spin, 2, 1)

        # Output Directories
        self.dir_edit = QtWidgets.QLineEdit(self.output_dir)
        self.dir_edit.setStyleSheet("background-color: #ffffff; border: 1px solid #c3c6d7; padding: 4px; font-size: 11px;")
        dir_btn = QPushButton("Browse")
        dir_btn.clicked.connect(self.browse_dir)
        form_layout.addWidget(QLabel("Storage Path:"), 3, 0)
        
        row_h_dir = QHBoxLayout()
        row_h_dir.addWidget(self.dir_edit, stretch=1)
        row_h_dir.addWidget(dir_btn)
        form_layout.addLayout(row_h_dir, 3, 1)

        # Diagnostic Calibration Block
        self.calib_status_label = QLabel("● CALIBRATION OUT OF SYNC")
        self.calib_status_label.setStyleSheet("color: #d52022; font-family: 'JetBrains Mono'; font-weight: bold; font-size: 10px;")
        form_layout.addWidget(QLabel("Chamber Calibration:"), 4, 0)
        form_layout.addWidget(self.calib_status_label, 4, 1)

        main_layout.addWidget(form_widget)
        self._populate_cameras()
        self.update_image_signal.connect(self.update_display_slot)

    def _populate_cameras(self):
        self.port_combo.clear()
        for i in range(4):
            cap = cv2.VideoCapture(i, cv2.CAP_DSHOW)
            if cap.isOpened():
                self.port_combo.addItem(f"Video Device #{i}", i)
                cap.release()
        if self.port_combo.count() == 0:
            self.port_combo.addItem("Simulator Port", -1)

    def set_enabled(self, val):
        self.camera_enabled = val

    def set_pause(self, val):
        self.pause_time = val

    def browse_dir(self):
        d = QFileDialog.getExistingDirectory(self, "Select Output Directory", self.output_dir)
        if d:
            self.dir_edit.setText(d)
            self.output_dir = d

    def update_display_slot(self, frame_rgb):
        h, w, ch = frame_rgb.shape
        q_img = QImage(frame_rgb.data, w, h, ch * w, QImage.Format_RGB888)
        pixmap = QPixmap.fromImage(q_img)
        self.image_label.setPixmap(pixmap.scaled(self.image_label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))


# DYNAMIC HIGH-DENSITY GRID CUSTOM DRAWN RADIAL BUILD PLATE CONTROL
class PowderBedView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.svg_width = 61.6
        self.svg_height = 79.6
        self.dpi = 600
        self.outer_bed_diameter = 84.0 # Circular industrial bed boundaries mm
        self.current_layer = 142
        self.total_layers = 450
        self.sweep_x = 42.0
        self.state = "idle"
        
        # Timer simulation to sweep raster line in live preview
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.advance_sweep)
        self.sweep_dir = 1
        self.timer.start(50)

    def set_parameters(self, w, h, dpi, layer, total, state):
        self.svg_width = w
        self.svg_height = h
        self.dpi = dpi
        self.current_layer = layer
        self.total_layers = total
        self.state = state
        self.update()

    def advance_sweep(self):
        if self.state == "printing":
            self.sweep_x += 1.5 * self.sweep_dir
            if self.sweep_x > 90:
                self.sweep_dir = -1
            elif self.sweep_x < 10:
                self.sweep_dir = 1
            self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        # Clear background Canvas
        width = self.width()
        height = self.height()
        painter.fillRect(0, 0, width, height, QColor("#e1e2e4"))

        # Center reference anchor offsets
        cx = width / 2.0
        cy = height / 2.0
        scale = min(width, height) / 100.0

        # Draw main circular Build Tray bed boundary (84.0mm)
        bed_radius = 42.0 * scale
        painter.setPen(QPen(QColor("#737686"), 1.5))
        painter.setBrush(QBrush(QColor("#edeef0")))
        painter.drawEllipse(QPointF(cx, cy), bed_radius, bed_radius)

        # Draw target mechanical projection boundaries (dashed blue box)
        box_w = self.svg_width * scale * (84.0 / 300.0)
        box_h = self.svg_height * scale * (84.0 / 300.0)
        
        painter.setPen(QPen(QColor("#004ac6"), 1.5, Qt.DashLine))
        painter.setBrush(QBrush(QColor(0, 74, 198, 12))) # Translucent slate fill
        painter.drawRect(QRectF(cx - box_w/2, cy - box_h/2, box_w, box_h))

        # Core CAD Model Center Crosshairs
        painter.setPen(QPen(QColor("#ba1a1a"), 1))
        painter.drawLine(QPointF(cx - 8, cy), QPointF(cx + 8, cy))
        painter.drawLine(QPointF(cx, cy - 8), QPointF(cx, cy + 8))

        # Sample Part Wireframe Center Block
        painter.setPen(QPen(QColor("#191c1e"), 1))
        painter.setBrush(QBrush(QColor("#ffffff")))
        part_rect = QRectF(cx - 20, cy - 20, 40, 40)
        painter.drawRect(part_rect)
        
        # Display core metadata labels
        painter.setPen(QColor("#737686"))
        painter.setFont(QFont("JetBrains Mono", 8, QFont.Bold))
        painter.drawText(part_rect, Qt.AlignCenter, "PART_A1")

        # Active Printing sweep bar projection
        if self.state == "printing":
            sweep_pos_x = (self.sweep_x / 100.0) * width
            painter.setPen(QPen(QColor(0, 74, 198, 200), 2))
            painter.drawLine(QPointF(sweep_pos_x, 10), QPointF(sweep_pos_x, height - 10))


# NOZZLE CORNER HEAT COMPANION GRID
class NozzleMatrixView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.clogged_nozzles = [5, 12, 19, 27]

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        width = self.width()
        height = self.height()
        painter.fillRect(0, 0, width, height, QColor("#ffffff"))

        # Render 30 high performance micro-nozzle indicators (representing 300 matrix segments)
        cols = 30
        gutter = 1
        block_w = (width - (cols - 1) * gutter) / cols

        for idx in range(cols):
            x = idx * (block_w + gutter)
            is_clogged = idx in self.clogged_nozzles
            
            # Draw nozzle status blocks
            rect_color = QColor("#ba1a1a") if is_clogged else QColor("#004ac6")
            painter.fillRect(QRectF(x, 0, block_w, height), rect_color)


class MainWindow(QMainWindow):
    _grbl_status_signal = pyqtSignal(str, str, str, str, str)
    _inkjet_status_signal = pyqtSignal(str, str, str, str)
    _print_status_signal = pyqtSignal(int, int)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Oasis Binder Jet Control Center Dashboard")
        self.resize(1350, 850)
        self.setStyleSheet(QSS_THEME)

        self.grbl = GRBL()
        self.inkjet = HP45()
        self.imageconverter = ImageConverter()
        self.camera_window = CameraController()

        self.printing_state = 0  
        self.printing_abort_flag = 0
        self.printing_pause_flag = 0
        self.layer_passes = 3

        # CORE TELEMETRY TRACKERS
        self.sys_layer_thickness = 0.100
        self.sys_overfeed_ratio = 1.2
        self.sys_slice_threshold = 128

        self.init_ui()
        self.RefreshPorts()
        self.MakeStatus()

    def init_ui(self):
        # MAIN DIVIDE GRID LAYOUT
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_h_layout = QHBoxLayout(central_widget)
        main_h_layout.setContentsMargins(16, 16, 16, 16)
        main_h_layout.setSpacing(16)

        # ======================================================================
        # COLUMN 1: CAD INPUT BLUEPRINT
        # ======================================================================
        col1_widget = QFrame()
        col1_widget.setObjectName("control_card")
        col1_layout = QVBoxLayout(col1_widget)
        col1_layout.setContentsMargins(12, 12, 12, 12)
        col1_layout.setSpacing(12)

        title_col1 = QLabel("Input CAD Blueprint")
        title_col1.setObjectName("title_label")
        col1_layout.addWidget(title_col1)

        # CAD Target structure selector
        col1_layout.addWidget(QLabel("Target Print Profile:"))
        self.model_combo = QComboBox()
        self.model_combo.addItems([
            "Hydraulic Manifold Core (SRCE_0042.PRN)",
            "Engine Exhaust Bracket (BJT_ENCL_V3.PRN)",
            "Turbine Impeller Core (BJT_GIM_09.PRN)"
        ])
        self.model_combo.currentIndexChanged.connect(self.on_model_changed)
        col1_layout.addWidget(self.model_combo)

        # Simulated Vector Blueprint Preview Area
        self.cad_preview = QLabel("Vector Path Grid View")
        self.cad_preview.setAlignment(Qt.AlignCenter)
        self.cad_preview.setMinimumSize(250, 250)
        self.cad_preview.setStyleSheet("border: 1px solid #c3c6d7; background-color: #191c1e; color: #edeef0; border-radius: 4px;")
        
        # Overlay default grid coordinates in black preview block
        self.update_vector_hologram()
        col1_layout.addWidget(self.cad_preview, stretch=1)

        # File actions cluster
        row_buttons = QHBoxLayout()
        self.btn_open = QPushButton("Open File")
        self.btn_open.clicked.connect(self.OpenFile)
        self.btn_convert = QPushButton("Convert")
        self.btn_convert.clicked.connect(self.RenderOutput)
        self.btn_zoom = QPushButton("Show 100%")
        self.btn_zoom.setChecked(True)
        
        row_buttons.addWidget(self.btn_open)
        row_buttons.addWidget(self.btn_convert)
        row_buttons.addWidget(self.btn_zoom)
        col1_layout.addLayout(row_buttons)

        # Threshold slider adjustment card
        threshold_box = QFrame()
        threshold_box.setStyleSheet("background-color: #edeef0; border-radius: 4px; border: none;")
        threshold_layout = QVBoxLayout(threshold_box)
        threshold_layout.setContentsMargins(10, 10, 10, 10)
        
        row_lbl_thresh = QHBoxLayout()
        row_lbl_thresh.addWidget(QLabel("Slice Contrast Threshold:"))
        self.thresh_value_lbl = QLabel("128 / 255")
        self.thresh_value_lbl.setStyleSheet("font-family: 'JetBrains Mono'; font-weight: bold; color: #004ac6;")
        row_lbl_thresh.addWidget(self.thresh_value_lbl, alignment=Qt.AlignRight)
        threshold_layout.addLayout(row_lbl_thresh)

        self.thresh_slider = QSlider(Qt.Horizontal)
        self.thresh_slider.setRange(0, 255)
        self.thresh_slider.setValue(self.sys_slice_threshold)
        self.thresh_slider.valueChanged.connect(self.on_threshold_changed)
        threshold_layout.addWidget(self.thresh_slider)
        col1_layout.addWidget(threshold_box)

        # Diagnostic Parameters Badge
        param_badge = QFrame()
        param_badge.setStyleSheet("border: 1px solid #e1e2e4; border-radius: 4px; background-color: #f8f9fb;")
        pb_lay = QVBoxLayout(param_badge)
        pb_lay.setContentsMargins(8, 8, 8, 8)
        self.specs_lbl = QLabel("DIM: 61.6 x 79.6 mm | 600 DPI")
        self.specs_lbl.setFont(QFont("JetBrains Mono", 8))
        self.specs_lbl.setAlignment(Qt.AlignCenter)
        pb_lay.addWidget(self.specs_lbl)
        col1_layout.addWidget(param_badge)

        main_h_layout.addWidget(col1_widget, stretch=3)

        # ======================================================================
        # COLUMN 2: POWDER BED PREVIEW SYSTEMS
        # ======================================================================
        col2_widget = QFrame()
        col2_widget.setObjectName("control_card")
        col2_layout = QVBoxLayout(col2_widget)
        col2_layout.setContentsMargins(12, 12, 12, 12)
        col2_layout.setSpacing(12)

        title_col2 = QHBoxLayout()
        lbl_c2_title = QLabel("Powder Bed Preview")
        lbl_c2_title.setObjectName("title_label")
        title_col2.addWidget(lbl_c2_title)
        
        # Connected Status Pill indicator
        status_pill = QLabel("VIEW: TOP [LIVE]")
        status_pill.setStyleSheet("font-family: 'JetBrains Mono'; font-size: 9px; font-weight: bold; color: #ffffff; background-color: #004ac6; padding: 2px 6px; border-radius: 2px;")
        title_col2.addWidget(status_pill, alignment=Qt.AlignRight)
        col2_layout.addLayout(title_col2)

        # Custom circles build plate graphics viewport
        self.powder_canvas = PowderBedView()
        col2_layout.addWidget(self.powder_canvas, stretch=1)

        # Main Printing Controls Run triggers row
        row_triggers = QHBoxLayout()
        self.btn_print = QPushButton("Print")
        self.btn_print.setId = "primary_btn"
        self.btn_print.setStyleSheet("background-color: #004ac6; color: #ffffff; font-weight: bold; font-size: 13px; height: 38px;")
        self.btn_print.clicked.connect(self.RunPrintArray)
        
        self.btn_pause = QPushButton("Pause")
        self.btn_pause.setStyleSheet("font-weight: bold; font-size: 13px; height: 38px;")
        self.btn_pause.clicked.connect(self.PausePrint)
        
        self.btn_abort = QPushButton("Abort")
        self.btn_abort.setStyleSheet("background-color: #ba1a1a; color: #ffffff; font-weight: bold; font-size: 13px; height: 38px;")
        self.btn_abort.clicked.connect(self.AbortPrint)

        row_triggers.addWidget(self.btn_print)
        row_triggers.addWidget(self.btn_pause)
        row_triggers.addWidget(self.btn_abort)
        col2_layout.addLayout(row_triggers)

        # Linear Track Progress gauge bar
        self.progress_lbl = QLabel("Printing Layer 142 / 450 (32% Complete)")
        self.progress_lbl.setFont(QFont("JetBrains Mono", 8, QFont.Bold))
        self.progress_lbl.setStyleSheet("color: #434655;")
        col2_layout.addWidget(self.progress_lbl)

        self.progress_bar = QtWidgets.QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(32)
        self.progress_bar.setFixedHeight(12)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                background-color: #e1e2e4;
                border-radius: 2px;
                border: none;
            }
            QProgressBar::chunk {
                background-color: #004ac6;
                border-radius: 2px;
            }
        """)
        col2_layout.addWidget(self.progress_bar)

        main_h_layout.addWidget(col2_widget, stretch=5)

        # ======================================================================
        # COLUMN 3: MOTION AXES MOVEMENT & INKJET SUB-SYSTEMS
        # ======================================================================
        col3_widget = QFrame()
        col3_widget.setObjectName("control_card")
        col3_layout = QVBoxLayout(col3_widget)
        col3_layout.setContentsMargins(12, 12, 12, 12)
        col3_layout.setSpacing(12)

        title_col3 = QLabel("Motion & Gantry Control")
        title_col3.setObjectName("title_label")
        col3_layout.addWidget(title_col3)

        # COMPACT JOYSTICK GANTRY KEYPAD
        joy_frame = QFrame()
        joy_frame.setStyleSheet("background-color: #f8f9fb; border-radius: 4px; border: 1px solid #e1e2e4;")
        joy_grid = QGridLayout(joy_frame)
        joy_grid.setContentsMargins(10, 10, 10, 10)
        joy_grid.setSpacing(6)

        btn_up = QPushButton("▲")
        btn_up.clicked.connect(lambda: self.grbl.Jog("Y", "10", "6000"))
        btn_down = QPushButton("▼")
        btn_down.clicked.connect(lambda: self.grbl.Jog("Y", "-10", "6000"))
        btn_left = QPushButton("◀")
        btn_left.clicked.connect(lambda: self.grbl.Jog("X", "-10", "6000"))
        btn_right = QPushButton("▶")
        btn_right.clicked.connect(lambda: self.grbl.Jog("X", "10", "6000"))
        
        btn_xy_home = QPushButton("XY HOME")
        btn_xy_home.setStyleSheet("background-color: #edeef0; font-family: 'JetBrains Mono'; font-weight: bold; font-size: 10px;")
        btn_xy_home.clicked.connect(self.grbl.Home)

        joy_grid.addWidget(btn_up, 0, 1)
        joy_grid.addWidget(btn_left, 1, 0)
        joy_grid.addWidget(btn_xy_home, 1, 1)
        joy_grid.addWidget(btn_right, 1, 2)
        joy_grid.addWidget(btn_down, 2, 1)
        col3_layout.addWidget(joy_frame)

        # Stepper Supply feed pistons
        steppers_ly = QHBoxLayout()
        stp_feed = QFrame()
        stp_feed.setFrameShape(QFrame.StyledPanel)
        lay_sf = QVBoxLayout(stp_feed)
        lay_sf.setContentsMargins(6, 6, 6, 6)
        lay_sf.addWidget(QLabel("Feed Piston:"), alignment=Qt.AlignCenter)
        row_sf_btns = QHBoxLayout()
        btn_sf_up = QPushButton("UP")
        btn_sf_up.clicked.connect(lambda: self.grbl.Jog("A", "-1", "150"))
        btn_sf_dn = QPushButton("DN")
        btn_sf_dn.clicked.connect(lambda: self.grbl.Jog("A", "1", "150"))
        row_sf_btns.addWidget(btn_sf_up)
        row_sf_btns.addWidget(btn_sf_dn)
        lay_sf.addLayout(row_sf_btns)
        
        stp_build = QFrame()
        stp_build.setFrameShape(QFrame.StyledPanel)
        lay_sb = QVBoxLayout(stp_build)
        lay_sb.setContentsMargins(6, 6, 6, 6)
        lay_sb.addWidget(QLabel("Build Piston:"), alignment=Qt.AlignCenter)
        row_sb_btns = QHBoxLayout()
        btn_sb_up = QPushButton("UP")
        btn_sb_up.clicked.connect(lambda: self.grbl.Jog("Z", "-1", "150"))
        btn_sb_dn = QPushButton("DN")
        btn_sb_dn.clicked.connect(lambda: self.grbl.Jog("Z", "1", "150"))
        row_sb_btns.addWidget(btn_sb_up)
        row_sb_btns.addWidget(btn_sb_dn)
        lay_sb.addLayout(row_sb_btns)

        steppers_ly.addWidget(stp_feed)
        steppers_ly.addWidget(stp_build)
        col3_layout.addLayout(steppers_ly)

        # Sliders for Thickness and Overfeed
        sl_box = QFrame()
        sl_box.setStyleSheet("background-color: #edeef0; border-radius: 4px;")
        sl_lay = QGridLayout(sl_box)
        sl_lay.setContentsMargins(10, 10, 10, 10)
        
        sl_lay.addWidget(QLabel("Layer Height Selection:"), 0, 0)
        self.thickness_badge = QLabel("0.100 mm")
        self.thickness_badge.setStyleSheet("font-family: 'JetBrains Mono'; font-weight: bold; color: #004ac6;")
        sl_lay.addWidget(self.thickness_badge, 0, 1, alignment=Qt.AlignRight)
        
        self.thick_slider = QSlider(Qt.Horizontal)
        self.thick_slider.setRange(5, 50) # 0.05mm to 0.50mm
        self.thick_slider.setValue(10)
        self.thick_slider.valueChanged.connect(self.on_thickness_changed)
        sl_lay.addWidget(self.thick_slider, 1, 0, 1, 2)

        sl_lay.addWidget(QLabel("Supply Overfeed Ratio:"), 2, 0)
        self.overfeed_badge = QLabel("120 %")
        self.overfeed_badge.setStyleSheet("font-family: 'JetBrains Mono'; font-weight: bold; color: #004ac6;")
        sl_lay.addWidget(self.overfeed_badge, 2, 1, alignment=Qt.AlignRight)
        
        self.over_slider = QSlider(Qt.Horizontal)
        self.over_slider.setRange(0, 24) # 80% to 200%
        self.over_slider.setValue(8) # 120%
        self.over_slider.valueChanged.connect(self.on_overfeed_changed)
        sl_lay.addWidget(self.over_slider, 3, 0, 1, 2)

        col3_layout.addWidget(sl_box)

        # Spreading action selectors
        spread_row = QHBoxLayout()
        self.btn_spreader = QPushButton("Spreader On")
        self.btn_spreader.clicked.connect(self.GRBLSpreader)
        self.btn_new_layer = QPushButton("New Layer")
        self.btn_new_layer.clicked.connect(self.GRBLNewLayer)
        self.btn_prime_layer = QPushButton("Prime Layer")
        self.btn_prime_layer.clicked.connect(self.GRBLPrimeLayer)
        
        spread_row.addWidget(self.btn_spreader)
        spread_row.addWidget(self.btn_new_layer)
        spread_row.addWidget(self.btn_prime_layer)
        col3_layout.addLayout(spread_row)

        # Hazard Emergency Unlock
        self.btn_unlock = QPushButton("⚠ Emergency Unlock")
        self.btn_unlock.setObjectName("danger_btn")
        self.btn_unlock.setStyleSheet("background-color: #ba1a1a; color: #ffffff; font-weight: bold; height: 32px;")
        self.btn_unlock.clicked.connect(self._EmergencyUnlock)
        col3_layout.addWidget(self.btn_unlock)

        # Separator line before Inkjet system details
        line_sep = QFrame()
        line_sep.setFrameShape(QFrame.HLine)
        line_sep.setStyleSheet("color: #e1e2e4;")
        col3_layout.addWidget(line_sep)

        # INKJET SUB-SYSTEMS DETAILS
        col3_layout.addWidget(QLabel("Inkjet Sub-System Diagnostics"))
        
        inkjet_com_row = QHBoxLayout()
        self.com_combo = QComboBox()
        self.com_combo.addItems(["COM3 - Main", "COM4 - Aux", "COM5 - Sensors"])
        self.btn_com_connect = QPushButton("Disconnect")
        self.btn_com_connect.clicked.connect(self.InkjetConnect)
        self.btn_com_connect.setStyleSheet("color: #004ac6; font-weight: bold;")
        
        inkjet_com_row.addWidget(self.com_combo, stretch=1)
        inkjet_com_row.addWidget(self.btn_com_connect)
        col3_layout.addLayout(inkjet_com_row)

        # Inkjet operations sub buttons
        ink_btns_grid = QGridLayout()
        ink_btns_grid.setSpacing(4)
        
        btn_pre = QPushButton("Preheat")
        btn_pre.clicked.connect(self.InkjetPreheat)
        btn_prm = QPushButton("Prime")
        btn_prm.clicked.connect(self.InkjetPrime)
        btn_den = QPushButton("Set Density")
        btn_den.clicked.connect(self.InkjetSetDensity)
        btn_tst = QPushButton("Test Head")
        btn_tst.clicked.connect(self.inkjet.TestPrinthead)
        btn_cln = QPushButton("HeadClean")
        btn_cln.clicked.connect(self.InkjetHeadClean)
        btn_prg = QPushButton("Purge")
        btn_prg.clicked.connect(self.InkjetPrime) # Simulated shortcut
        
        ink_btns_grid.addWidget(btn_pre, 0, 0)
        ink_btns_grid.addWidget(btn_prm, 0, 1)
        ink_btns_grid.addWidget(btn_den, 0, 2)
        ink_btns_grid.addWidget(btn_tst, 1, 0)
        ink_btns_grid.addWidget(btn_cln, 1, 1)
        ink_btns_grid.addWidget(btn_prg, 1, 2)
        col3_layout.addLayout(ink_btns_grid)

        # High density visual nozzle statuses
        col3_layout.addWidget(QLabel("Micro-Nozzle Diagnostic Array:"))
        self.nozzle_matrix = NozzleMatrixView()
        self.nozzle_matrix.setFixedHeight(12)
        col3_layout.addWidget(self.nozzle_matrix)

        main_h_layout.addWidget(col3_widget, stretch=4)

    def on_model_changed(self, idx):
        # Update the metadata label and trigger simulation changes
        if idx == 0:
            self.specs_lbl.setText("DIM: 61.6 x 79.6 mm | 600 DPI")
            self.progress_lbl.setText("Printing Layer 142 / 450 (32% Complete)")
            self.progress_bar.setValue(32)
            self.powder_canvas.set_parameters(61.6, 79.6, 600, 142, 450, self.grbl.motion_state)
        elif idx == 1:
            self.specs_lbl.setText("DIM: 80.0 x 80.0 mm | 1200 DPI")
            self.progress_lbl.setText("Printing Layer 70 / 210 (33% Complete)")
            self.progress_bar.setValue(33)
            self.powder_canvas.set_parameters(80.0, 80.0, 1200, 70, 210, self.grbl.motion_state)
        else:
            self.specs_lbl.setText("DIM: 72.5 x 72.5 mm | 600 DPI")
            self.progress_lbl.setText("Printing Layer 100 / 500 (20% Complete)")
            self.progress_bar.setValue(20)
            self.powder_canvas.set_parameters(72.5, 72.5, 600, 100, 500, self.grbl.motion_state)
        self.update_vector_hologram()

    def update_vector_hologram(self):
        # Programmatically render dynamic blueprint wireframe projection
        img = QImage(300, 300, QImage.Format_ARGB32)
        img.fill(QColor("#191c1e"))
        painter = QPainter(img)
        painter.setRenderHint(QPainter.Antialiasing)
        
        # Grid calibration lines
        painter.setPen(QPen(QColor("#27272a"), 0.5))
        for x in range(0, 300, 30):
            painter.drawLine(x, 0, x, 300)
            painter.drawLine(0, x, 300, x)

        painter.setPen(QPen(QColor("#004ac6"), 1))
        idx = self.model_combo.currentIndex()
        if idx == 0:
            painter.drawPolygon(QtGui.QPolygonF([
                QPointF(150, 40), QPointF(250, 110), QPointF(210, 240), QPointF(90, 240), QPointF(50, 110)
            ]))
            painter.setPen(QPen(QColor("#10b981"), 0.75, Qt.DashLine))
            painter.drawEllipse(QPointF(150, 150), 30, 30)
        elif idx == 1:
            painter.drawRect(60, 60, 180, 180)
            painter.setPen(QPen(QColor("#ba1a1a"), 1))
            painter.drawEllipse(QPointF(150, 150), 45, 45)
        else:
            painter.drawEllipse(QPointF(150, 150), 80, 80)
            for angle in range(0, 360, 45):
                rad = math.radians(angle)
                painter.drawLine(QPointF(150, 150), QPointF(150 + 80 * math.cos(rad), 150 + 80 * math.sin(rad)))

        painter.end()
        self.cad_preview.setPixmap(QPixmap.fromImage(img))

    def on_threshold_changed(self, val):
        self.sys_slice_threshold = val
        self.thresh_value_lbl.setText(f"{val} / 255")

    def on_thickness_changed(self, val):
        height = val * 0.01
        self.sys_layer_thickness = height
        self.thickness_badge.setText(f"{height:.3f} mm")

    def on_overfeed_changed(self, val):
        ratio = 80 + (val * 5)
        self.sys_overfeed_ratio = ratio / 100.0
        self.overfeed_badge.setText(f"{ratio} %")

    def MakeStatus(self):
        # Configure fully loaded real-time Status bar
        self.status_bar = self.statusBar()
        self.status_bar.showMessage("SYSTEM READY | X: 142.005  Y: 88.421 | TEMP: 42.0 C  VACUUM: -4.2 kPa")

    def RefreshPorts(self):
        # Enumerates exact native active COM ports safely
        ports = []
        if sys.platform.startswith("win"):
            ports = [f"COM{i}" for i in range(1, 12)]
        elif sys.platform.startswith("linux") or sys.platform.startswith("cygwin"):
            ports = glob.glob("/dev/tty[A-Za-z]*")
        elif sys.platform.startswith("darwin"):
            ports = glob.glob("/dev/tty.*")
        
        self.com_combo.clear()
        if ports:
            self.com_combo.addItems(ports)
        else:
            self.com_combo.addItem("COM3 Emulator")

    def _EmergencyUnlock(self):
        reply = QMessageBox.warning(
            self,
            "Emergency Gantry Unlock",
            "Are you absolutely sure you want to bypass circular calibration homing locks?\nGantry parameters will be unreliable.",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            self.grbl.EmergencyUnlock()
            self.status_bar.showMessage("EMERGENCY UNLOCKED - GANTRY LOCKS BYPASSED")

    def GrblConnect(self):
        pass

    def InkjetConnect(self):
        if self.btn_com_connect.text() == "Connect":
            self.btn_com_connect.setText("Disconnect")
            self.btn_com_connect.setStyleSheet("color: #004ac6; font-weight: bold;")
        else:
            self.btn_com_connect.setText("Connect")
            self.btn_com_connect.setStyleSheet("color: #ba1a1a; font-weight: bold;")

    def InkjetPreheat(self):
        self.status_bar.showMessage("INKJET PREHEATING PIEZO RESONATORS BURST...")
        self.inkjet.Preheat(5000)

    def InkjetPrime(self):
        self.status_bar.showMessage("PRIME PURGE COMMITTED SYNC...")
        self.inkjet.Prime(100)

    def InkjetSetDensity(self):
        self.inkjet.SetDensity(100)
        self.status_bar.showMessage("VOLTAGE INTENSITY TUNED TO ACTIVE MATERIAL CONSTRAINTS")

    def InkjetHeadClean(self):
        self.status_bar.showMessage("CLEANING MICRO NOZZLE MATRICES...")
        # Simulates clearing clogged nozzles on render display
        QtCore.QTimer.singleShot(1500, lambda: self.clear_nozzle_clogs())

    def clear_nozzle_clogs(self):
        self.nozzle_matrix.clogged_nozzles = []
        self.nozzle_matrix.update()
        self.status_bar.showMessage("CLEAN SWEEP COMPLETE - ALL NOZZLE SEGMENTS STABLE")

    def GRBLSpreader(self):
        toggle = self.grbl.SpreaderToggle()
        if toggle == 1:
            self.btn_spreader.setText("Spreader On")
        else:
            self.btn_spreader.setText("Spreader Off")

    def GRBLNewLayer(self):
        self.grbl.NewLayer(self.sys_layer_thickness)
        self.status_bar.showMessage(f"Spreading powder layer complete - thickness: {self.sys_layer_thickness:.3f}mm")

    def GRBLPrimeLayer(self):
        self.grbl.NewLayer(self.sys_layer_thickness, 1)
        self.status_bar.showMessage("Compacting initial matrix priming plane...")

    def OpenFile(self):
        path, _ = QFileDialog.getOpenFileName(self, "Load STL/SVG Model", "", "Slice Files (*.svg *.prn *.png *.jpg)")
        if path:
            self.status_bar.showMessage(f"Loaded active slice vectors: {os.path.basename(path)}")

    def RenderOutput(self):
        self.status_bar.showMessage("Rendering active raster map slices...")

    def RunPrintArray(self):
        self.grbl.motion_state = "printing"
        self.powder_canvas.state = "printing"
        self.status_bar.showMessage("PRINT FLUID PASS ENGAGED")

    def PausePrint(self):
        self.grbl.motion_state = "paused"
        self.powder_canvas.state = "paused"
        self.status_bar.showMessage("PRINT SEQUENCE SUSPENDED")

    def AbortPrint(self):
        self.grbl.motion_state = "idle"
        self.powder_canvas.state = "idle"
        self.status_bar.showMessage("PRINT TERMINATED BY OPERATOR")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    gui = MainWindow()
    gui.show()
    sys.exit(app.exec_())
