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
from Interface import Interface
import os
from ImageConverter import ImageConverter
import B64
from numpy import *
import math
import threading
import time
import serial

# a small note on threading. It is used so some of the functions update automatically (serial GRBL and inkjet)
# however, it is a bit of a lie. If python is busy in one thread, it will quietly ignore the others
# sleep commands will give enough room that python works on other threads.
# this is the reason why sending inkjet while moving is difficult. Will fix later, with another attempt


# --- INSERTION: New Camera Controller Class ---
class CameraController(QtWidgets.QWidget):
    # Signal to update the UI from the printer thread safely
    update_image_signal = QtCore.pyqtSignal(object)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Oasis Camera View")
        self.resize(600, 450)

        # Default Settings
        self.camera_port = 0
        self.pause_time = 2.0  # Total time to pause for photo (seconds)
        self.output_dir = os.path.join(os.getcwd(), "timelapse_output")
        self.camera_enabled = True
        self._camera_list = []  # list of {"index": int, "name": str}

        # Ensure output directory exists
        if not os.path.exists(self.output_dir):
            os.makedirs(self.output_dir)

        # --- UI Layout ---
        layout = QtWidgets.QVBoxLayout()

        # Image Display Label
        self.image_label = QLabel("No Image Captured")
        self.image_label.setAlignment(QtCore.Qt.AlignCenter)
        self.image_label.setMinimumSize(400, 300)
        self.image_label.setStyleSheet(
            "border: 1px solid gray; background-color: #eee;"
        )
        layout.addWidget(self.image_label, stretch=1)

        # Controls Group
        controls_group = QtWidgets.QGroupBox("Settings")
        form_layout = QtWidgets.QFormLayout()
        form_layout.setFieldGrowthPolicy(QtWidgets.QFormLayout.ExpandingFieldsGrow)

        # Enable Toggle
        self.enable_chk = QtWidgets.QCheckBox("Enable Camera")
        self.enable_chk.setChecked(self.camera_enabled)
        self.enable_chk.toggled.connect(self.set_enabled)
        form_layout.addRow("Status:", self.enable_chk)

        # Camera selection (QComboBox — name + index)
        cam_row = QtWidgets.QHBoxLayout()
        self.port_combo = QtWidgets.QComboBox()
        self.port_combo.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        self.port_combo.setToolTip("Select camera by name")
        self.port_combo.currentIndexChanged.connect(self._on_camera_selected)
        self.refresh_btn = QtWidgets.QPushButton("Refresh")
        self.refresh_btn.setFixedWidth(70)
        self.refresh_btn.clicked.connect(self._populate_cameras)
        cam_row.addWidget(self.port_combo)
        cam_row.addWidget(self.refresh_btn)
        form_layout.addRow("Camera:", cam_row)
        self._populate_cameras()  # enumerate on startup

        # Pause Duration
        self.pause_spin = QtWidgets.QDoubleSpinBox()
        self.pause_spin.setValue(self.pause_time)
        self.pause_spin.setRange(0.0, 60.0)
        self.pause_spin.setSingleStep(0.5)
        self.pause_spin.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        self.pause_spin.valueChanged.connect(self.set_pause)
        form_layout.addRow("Pause Time (s):", self.pause_spin)

        # Output Directory
        self.dir_layout = QtWidgets.QHBoxLayout()
        self.dir_edit = QtWidgets.QLineEdit(self.output_dir)
        self.dir_edit.textChanged.connect(self.set_dir)
        self.dir_btn = QtWidgets.QPushButton("...")
        self.dir_btn.clicked.connect(self.browse_dir)
        self.dir_layout.addWidget(self.dir_edit)
        self.dir_layout.addWidget(self.dir_btn)
        form_layout.addRow("Output Dir:", self.dir_layout)

        # CALIB HOOK — calibration status + run button
        self.calib_status_label = QtWidgets.QLabel("● Unknown")
        self.calib_status_label.setStyleSheet("color: grey;")
        self.btn_run_calibration = QtWidgets.QPushButton("Run Calibration")
        # CALIB HOOK — connected to MainWindow._run_calibration after instantiation
        calib_row = QtWidgets.QHBoxLayout()
        calib_row.addWidget(self.calib_status_label, 1)
        calib_row.addWidget(self.btn_run_calibration)
        form_layout.addRow("Calibration Status:", calib_row)

        controls_group.setLayout(form_layout)
        controls_group.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Preferred)
        layout.addWidget(controls_group)
        self.setLayout(layout)

        # Connect the signal to the UI update slot
        self.update_image_signal.connect(self.update_display_slot)

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
    def capture_sync(self, filename_suffix):
        """
        Pauses, takes photo, saves it, and updates UI.
        Blocking call safe for use in the printing thread.
        """
        if not self.camera_enabled:
            return

        print(f"CAMERA: Initiating capture for {filename_suffix}")

        # 1. Pre-capture settle time (half of pause time)
        time.sleep(self.pause_time / 2.0)

        # 2. Capture Frame using OpenCV
        try:
            import cv2

            cap = cv2.VideoCapture(self.camera_port)
            # Try to grab a frame
            if cap.isOpened():
                ret, frame = cap.read()
                cap.release()  # Release immediately

                if ret:
                    # 3. Save to Disk
                    filename = f"{filename_suffix}.png"
                    filepath = os.path.join(self.output_dir, filename)
                    cv2.imwrite(filepath, frame)
                    print(f"CAMERA: Saved {filepath}")

                    # 4. Emit signal to update UI (Must transfer data to main thread)
                    # Convert BGR (OpenCV) to RGB (Qt)
                    frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    self.update_image_signal.emit(frame_rgb)
                else:
                    print("CAMERA: Failed to read frame.")
            else:
                print(f"CAMERA: Could not open port {self.camera_port}")

        except Exception as e:
            print(f"CAMERA ERROR: {e}")

        # 5. Post-capture wait (remainder of pause time)
        time.sleep(self.pause_time / 2.0)

    # --- UI Update (Runs on Main Thread) ---
    @QtCore.pyqtSlot(object)
    def update_display_slot(self, frame_rgb):
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


# -----------------------------------------------


class MainWindow(QtWidgets.QMainWindow):
    _grbl_status_signal = QtCore.pyqtSignal(str, str, str, str, str)
    _inkjet_status_signal = QtCore.pyqtSignal(str, str, str, str)
    _print_status_signal = QtCore.pyqtSignal(int, int)  # current_layer, total_layers
    _print_error_signal = QtCore.pyqtSignal(str)        # error message

    def __init__(self):
        super(MainWindow, self).__init__()

        script_dir = os.path.dirname(os.path.abspath(__file__))
        ui_path = os.path.join(script_dir, "Oasis_interface.ui")
        Form, Window = uic.loadUiType(ui_path)

        self.ui = Window()
        self.form = Form()
        self.form.setupUi(self.ui)
        self.ui.show()

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
        # self.form.file_print_button.clicked.connect(self.RenderRGB)
        self.form.layer_slider.valueChanged.connect(self.UpdateLayer)
        self.form.start_layer_spinbox.setEnabled(False)  # disabled until file is loaded
        self.form.threshold_slider.valueChanged.connect(self.UpdateThresholdSliderValue)
        self.form.motion_layer_thickness.valueChanged.connect(
            self.UpdateLayerSliderValue
        )
        self.form.motion_overfeed.valueChanged.connect(self.UpdateOverfeedSliderValue)

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

    def _HeadCleanWorker(self):
        """Background worker for InkjetHeadClean — do not call directly."""
        preheat_pulses = getattr(self, "preheat_pulses", 5000)
        prime_pulses = getattr(self, "prime_pulses", 100)
        sequence = [
            ("preheat", 10),
            ("prime",   10),
            ("preheat", 10),
            ("prime",    5),
            ("preheat",  5),
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
        MAX_HEIGHT_MM = 21.0  # 210 layers × 0.1mm
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
        """Gets an image from the image converter class and renders it to input"""
        self.input_image_display = self.imageconverter.input_image
        if (
            self.input_image_display.width() > 300
            and self.input_image_display.height() > 300
        ):
            self.input_image_display = self.input_image_display.scaled(
                300, 300, QtCore.Qt.KeepAspectRatio
            )
        self.form.input_window.setPixmap(self.input_image_display)
        # self.form.input_window.setPixmap(self.imageconverter.input_image)

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

        px_to_mm = 25.4 / self.printing_dpi
        svg_offset_x = self.imageconverter.svg_width / 2
        svg_offset_y = self.imageconverter.svg_height / 2

        _margin_mm = 2.0
        _bed_span_mm = BED_DIAMETER_MM + _margin_mm * 2      # 88mm
        _px_per_mm = self.printing_dpi / 25.4
        out_size = int(_bed_span_mm * _px_per_mm) + 1        # same as calib_array
        _out_offset = _bed_span_mm / 2                       # 44mm — bed centre → image centre

        out = np.zeros((out_size, out_size), dtype=np.uint8)
        for row in range(arr_h):
            for col in range(arr_w):
                if arr[row, col] == 0:
                    continue
                # GRBL mm (same as PrintSVG)
                grbl_x = row * px_to_mm + self.build_center_x - svg_offset_x
                grbl_y = col * px_to_mm + self.build_center_y - svg_offset_y
                # shift GRBL mm → bed-space px (bed centre = image centre)
                out_row = int((grbl_x - self.build_center_x + _out_offset) * _px_per_mm)
                out_col = int((grbl_y - self.build_center_y + _out_offset) * _px_per_mm)
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

        path = os.path.join(captures_dir, f"layer_{layer_idx:03d}_reference.png")
        cv2.imwrite(path, out)

    def save_reference_svg(self, layer_idx):
        """Extract the current layer from the loaded SVG and save as a single-layer SVG."""
        captures_dir = self.camera_window.output_dir
        svg_path = self.imageconverter.file_path
        layer_name = self.imageconverter.svg_layer_names[layer_idx]

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
          1. generate_calibration_svg() → svg_path          (dice_evaluator, no serial)
          2. Load svg via self.imageconverter                (same as normal print)
          3. Print 1 layer via existing self.grbl + self.hp45 path
          4. Poll self.grbl.nl_state == 1                   (same pattern as main loop)
          5. capture_sync("calibration") → frame on disk
          6. detect_circle_in_image(frame) → compute + save calibration.npz
        """
        import cv2
        from dice_evaluator import generate_calibration_svg
        from dice_evaluator.calibrate import (
            detect_circle_in_image,
            compute_calibration,
            save_calibration,
        )

        captures_dir = self.camera_window.output_dir

        # 1. Generate calibration SVG
        svg_path = os.path.join(captures_dir, "calibration_target.svg")
        generate_calibration_svg(svg_path)
        print(f"CALIB: SVG written to {svg_path}")

# 2. Build calibration image_array — 9-point cross-mark grid
        #    (largest inscribed square in bed circle: corners + edge midpoints + center)
        import math
        from dice_evaluator.constants import (
            BED_DIAMETER_MM, BED_RADIUS_MM, BUILD_CENTER_X_MM, BUILD_CENTER_Y_MM,
        )

        _calib_dpi      = int(self.imageconverter.dpi)
        _px_per_mm      = _calib_dpi / 25.4

        # FIX: add margin so corner crosses aren't clipped at array edge.
        # Inscribed-square corners sit exactly on the bed circle (r = BED_RADIUS_MM),
        # and cross arms extend 1 mm outward, so we need ≥1 mm clearance each side.
        _calib_margin_mm = 2.0
        _arr_w = int((BED_DIAMETER_MM + _calib_margin_mm * 2) * _px_per_mm) + 1
        _arr_h = int((BED_DIAMETER_MM + _calib_margin_mm * 2) * _px_per_mm) + 1
        calib_array = zeros((_arr_h, _arr_w))

        # Array centre in pixels
        _cx_px = _arr_w / 2.0   # col axis  → machine Y
        _cy_px = _arr_h / 2.0   # row axis  → machine X

        # Largest square inscribed in bed circle  →  half-side = R / √2  ≈ 29.7 mm
        _hs_px = (BED_RADIUS_MM / math.sqrt(2)) * _px_per_mm

        # 9 calibration points as (row, col) — symmetric grid
        #   row = machine-X axis,  col = machine-Y axis
        _pts = [
            # 4 corners
            (_cy_px - _hs_px, _cx_px - _hs_px),
            (_cy_px - _hs_px, _cx_px + _hs_px),
            (_cy_px + _hs_px, _cx_px - _hs_px),
            (_cy_px + _hs_px, _cx_px + _hs_px),
            # 4 edge midpoints
            (_cy_px - _hs_px, _cx_px         ),
            (_cy_px + _hs_px, _cx_px         ),
            (_cy_px,          _cx_px - _hs_px),
            (_cy_px,          _cx_px + _hs_px),
            # centre
            (_cy_px,          _cx_px         ),
        ]

        # Cross geometry: 5 mm × 5 mm bounding box → arm = 2.5 mm from centre
        #                 line thickness 2 mm
        _arm_px   = int(round(2.5 * _px_per_mm))           # 2.5 mm → 5 mm total span
        _half_thk = max(1, int(round(1.0 * _px_per_mm)))   # 1 mm   → 2 mm total

        for (pr_f, pc_f) in _pts:
            pr, pc = int(round(pr_f)), int(round(pc_f))
            # horizontal bar  (along col, thin in row)
            for dr in range(-_half_thk, _half_thk + 1):
                for dc in range(-_arm_px, _arm_px + 1):
                    r, c = pr + dr, pc + dc
                    if 0 <= r < _arr_h and 0 <= c < _arr_w:
                        calib_array[r][c] = 1
            # vertical bar  (along row, thin in col)
            for dr in range(-_arm_px, _arm_px + 1):
                for dc in range(-_half_thk, _half_thk + 1):
                    r, c = pr + dr, pc + dc
                    if 0 <= r < _arr_h and 0 <= c < _arr_w:
                        calib_array[r][c] = 1

        # 2b. Save calib_array as PNG in captures_dir (same pixel space as array)
        import cv2 as _cv2
        import numpy as _np
        _out = ((1 - calib_array) * 255).astype(_np.uint8)
        # draw bed boundary circle at array centre
        _bed_r_px = int(round(BED_RADIUS_MM * _px_per_mm))
        _cv2.circle(_out, (int(_cx_px), int(_cy_px)), _bed_r_px, color=0, thickness=1)
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
                f"인쇄 중 오류 발생 (Layer {layer} / {total})\n\n{msg}"
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
            self.printing_state = 2  # set printing state
            self.inkjet.ClearBuffer()  # clear inkjet buffer on HP45

            self.grbl.Home()  # home printer

            # make variables

            # going to fool around with these to find the offset. the originals will be maintained in the comments
            # SHIFT THESE TO CENTER PRINT ON PRINTBED
            self.build_center_x = (
                157  # 147 #OG 157.0 #where the center of the build platform is
            )

            self.build_center_y = (
                116  # 121.0 #OG 111 #where the center of the build platform is
            )

            self.print_speed = 2200  # 2200 #OG 2200.0 #how fast to print
            self.travel_speed = 3000.0  # how fast to travel

            self.acceleration_distance = 20.0  # how much to accelerate before printing
            self.printing_dpi = int(self.imageconverter.dpi)  # the set DPI
            self.printing_sweep_size = int(self.printing_dpi / 2)  # the sweep size
            self.pixel_to_pos_multiplier = (
                25.4 / self.printing_dpi
            )  # 25.4 #the value from pixel to mm
            # this setting shrinks the print by the uniform scaling factor

            self.image_size_x = (
                self.imageconverter.image_array_height
            )  # the max size of image, in X-direction
            self.image_size_y = (
                self.imageconverter.image_array_width
            )  # the max size of image, in Y-direction
            self.layers = self.imageconverter.svg_layers  # how many layers there are
            start_layer = max(1, min(self.form.start_layer_spinbox.value(), self.layers))
            self.current_layer = start_layer
            self.current_layer_height = self.imageconverter.svg_layer_height[start_layer - 1]
            print("Starting print at height: " + str(self.current_layer_height))

            # set flags
            self.printing_abort_flag = 0
            self.printing_pause_flag = 0

            # set inkjet settings
            self.inkjet.SetDPI(self.printing_dpi)

            # set motion settings

            # check file
            # offsets given above are assumed to be the center of bed
            # calculate offsets for centering file
            # width is Y, height is X
            # self.svg_offset_x = self.imageconverter.svg_height / 2
            # self.svg_offset_y = self.imageconverter.svg_width / 2
            # I flipped these because of a boo-boo somewhere.
            self.svg_offset_y = self.imageconverter.svg_height / 2
            self.svg_offset_x = self.imageconverter.svg_width / 2

            # Wait till homing is done
            if (
                self.grbl_connection_state == 1
            ):  # conditional for testing, only wait for home if there is home to wait on
                while self.grbl.motion_state != "idle":
                    time.sleep(0.1)
                    pass

            time.sleep(0.25)  # extra delay so the system can stabilize
            self.InkjetSetPosition()  # set position
            time.sleep(0.25)  # extra delay so position can be set

            # add priming purge here, with motions to start the printhead

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

                # --- INSERTION 1: Photo After Recoating (Spread) ---
                # The recoater has just finished spreading the new layer.
                if hasattr(self, "camera_window"):
                    self.camera_window.capture_sync(
                        f"Layer_{self.current_layer:03d}_Spread"
                    )
                # ---------------------------------------------------

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
                        self.camera_window.capture_sync(
                            f"Layer_{self.current_layer - 1:03d}_Printed"
                        )
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
                    self.camera_window.capture_sync(
                        f"Layer_{self.current_layer - 1:03d}_Printed"
                    )

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
            self._print_error_signal.emit(f"인쇄 중 오류 발생\n\n{msg}")
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
        """창 닫힐 때 모든 스레드 정리 후 프로세스 종료"""
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

    app = QtWidgets.QApplication(sys.argv)
    gui = MainWindow()
    sys.exit(app.exec_())
