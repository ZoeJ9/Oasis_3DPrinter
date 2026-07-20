"""
LightControllerTest.py — standalone LED (Arduino) controller test, no camera involved.

Connects to the Arduino over serial and lets you turn each LED on/off individually,
using the same protocol as Density_mapping_v1.1.py's CameraController
(single-character commands: "1".."5" = LED n on, "0" = all off).
"""

import sys
import glob
import threading
import time

import serial
from PyQt5 import QtCore, QtWidgets


def list_serial_ports():
    if sys.platform.startswith("win"):
        ports = ["COM%s" % (i + 1) for i in range(256)]
    elif sys.platform.startswith("linux") or sys.platform.startswith("cygwin"):
        ports = glob.glob("/dev/tty[A-Za-z]*")
    else:
        ports = glob.glob("/dev/tty.*")

    result = []
    for port in ports:
        try:
            s = serial.Serial(port)
            s.close()
            result.append(port)
        except (OSError, serial.SerialException):
            pass
    return result


class LightControllerTest(QtWidgets.QWidget):
    NUM_LEDS = 5

    _status_signal = QtCore.pyqtSignal(str, bool)  # message, is_ok

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Light Controller Test")
        self.resize(360, 260)

        self._conn = None
        self._lock = threading.Lock()

        layout = QtWidgets.QVBoxLayout(self)

        # --- Connection row ---
        conn_row = QtWidgets.QHBoxLayout()
        self.port_combo = QtWidgets.QComboBox()
        self.refresh_btn = QtWidgets.QPushButton("↺")
        self.refresh_btn.setFixedWidth(32)
        self.refresh_btn.clicked.connect(self.refresh_ports)
        self.connect_btn = QtWidgets.QPushButton("Connect")
        self.connect_btn.clicked.connect(self.toggle_connect)
        conn_row.addWidget(QtWidgets.QLabel("Port:"))
        conn_row.addWidget(self.port_combo, stretch=1)
        conn_row.addWidget(self.refresh_btn)
        conn_row.addWidget(self.connect_btn)
        layout.addLayout(conn_row)

        self.status_label = QtWidgets.QLabel("Disconnected")
        self.status_label.setStyleSheet("color: grey;")
        layout.addWidget(self.status_label)

        # --- LED buttons ---
        led_group = QtWidgets.QGroupBox("LEDs")
        led_layout = QtWidgets.QGridLayout(led_group)
        self.led_buttons = []
        for n in range(1, self.NUM_LEDS + 1):
            btn = QtWidgets.QPushButton(f"LED {n}")
            btn.setCheckable(True)
            btn.clicked.connect(lambda _checked, n=n: self.led_on(n))
            led_layout.addWidget(btn, 0, n - 1)
            self.led_buttons.append(btn)
        layout.addWidget(led_group)

        self.all_off_btn = QtWidgets.QPushButton("All Off")
        self.all_off_btn.clicked.connect(self.all_off)
        layout.addWidget(self.all_off_btn)

        # --- Sequence test ---
        seq_row = QtWidgets.QHBoxLayout()
        self.settle_spin = QtWidgets.QSpinBox()
        self.settle_spin.setRange(10, 5000)
        self.settle_spin.setValue(200)
        self.settle_spin.setSuffix(" ms")
        self.run_seq_btn = QtWidgets.QPushButton("Run 1→5 Sequence")
        self.run_seq_btn.clicked.connect(self.run_sequence)
        seq_row.addWidget(QtWidgets.QLabel("Settle:"))
        seq_row.addWidget(self.settle_spin)
        seq_row.addWidget(self.run_seq_btn)
        layout.addLayout(seq_row)

        layout.addStretch()

        self._status_signal.connect(self._on_status)
        self.refresh_ports()

    # --- Ports ---
    def refresh_ports(self):
        self.port_combo.clear()
        ports = list_serial_ports()
        self.port_combo.addItems(ports if ports else ["(none)"])

    # --- Connection ---
    def toggle_connect(self):
        if self._conn and self._conn.is_open:
            with self._lock:
                self._conn.close()
                self._conn = None
            self.connect_btn.setText("Connect")
            self.status_label.setText("Disconnected")
            self.status_label.setStyleSheet("color: grey;")
            return

        port = self.port_combo.currentText()
        if port == "(none)" or not port:
            return
        threading.Thread(target=self._connect_worker, args=(port,), daemon=True).start()

    def _connect_worker(self, port):
        try:
            conn = serial.Serial(port, 9600, timeout=1)
            time.sleep(2.0)  # Arduino auto-reset settle time
            conn.reset_input_buffer()
            with self._lock:
                self._conn = conn
            self._status_signal.emit(f"OK: {port}", True)
        except Exception as exc:
            self._status_signal.emit(f"Error: {exc}", False)

    @QtCore.pyqtSlot(str, bool)
    def _on_status(self, msg, ok):
        self.status_label.setText(msg)
        self.status_label.setStyleSheet("color: green; font-weight: bold;" if ok else "color: red;")
        if ok:
            self.connect_btn.setText("Disconnect")

    # --- LED control (same protocol as Density_mapping_v1.1.py) ---
    def _send(self, cmd: str):
        with self._lock:
            if self._conn and self._conn.is_open:
                self._conn.write(cmd.encode())

    def led_on(self, n: int):
        self._send(str(n))
        for i, btn in enumerate(self.led_buttons, start=1):
            btn.setChecked(i == n)

    def all_off(self):
        self._send("0")
        for btn in self.led_buttons:
            btn.setChecked(False)

    def run_sequence(self):
        threading.Thread(target=self._sequence_worker, daemon=True).start()

    def _sequence_worker(self):
        settle_s = self.settle_spin.value() / 1000.0
        for n in range(1, self.NUM_LEDS + 1):
            self.led_on(n)
            time.sleep(settle_s)
        self.all_off()


if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    w = LightControllerTest()
    w.show()
    sys.exit(app.exec_())
