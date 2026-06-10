import sys
from PyQt5.QtCore import Qt, QEvent
from PyQt5.QtWidgets import (QWidget, QLabel, QLineEdit, QTextEdit,
    QGridLayout, QApplication, QPushButton, QDesktopWidget,
    QSlider, QComboBox, QFrame, QVBoxLayout, QHBoxLayout, QGroupBox)
from PyQt5.QtGui import QIcon, QPixmap, QFont, QColor

class Interface(QWidget):
    def __init__(self):
        super().__init__()
        # self.initUI()
        
    def initUI(self):	
        # --- [1] MAIN LAYOUT CONFIGURATION ---
        # 전체를 관장하는 메층 레이어 및 백그라운드 그리드 설정
        main_layout = QHBoxLayout()
        main_layout.setContentsMargins(16, 16, 16, 16)
        main_layout.setSpacing(16)
        self.setLayout(main_layout)
        
        # --- [2] CENTRALIZED INDUSTRIAL HMI QSS STYLESHEET ---
        self.setStyleSheet("""
            QWidget {
                background-color: #F3F4F6;
                color: #1F2937;
                font-family: 'Inter', system-ui, -apple-system, sans-serif;
            }
            
            /* Modern Level 1 Card Container Style */
            QFrame#card_panel, QGroupBox {
                background-color: #FFFFFF;
                border: 1px solid #E5E7EB;
                border-radius: 6px;
                padding: 12px;
            }
            
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                padding: 0 5px;
                font-weight: 600;
                color: #4B5563;
                font-family: 'JetBrains Mono', monospace;
                text-transform: uppercase;
            }
            
            /* Section Title Styling */
            QLabel#section_title {
                font-weight: 700;
                color: #111827;
                text-transform: uppercase;
                border-bottom: 2px solid #E5E7EB;
                padding-bottom: 4px;
                margin-bottom: 8px;
            }
            
            /* Industrial Inputs and Textboxes */
            QLineEdit {
                background-color: #F9FAFB;
                border: 1px solid #D1D5DB;
                border-radius: 4px;
                padding: 6px 12px;
                color: #111827;
                font-family: 'JetBrains Mono', monospace;
            }
            QLineEdit:focus {
                border: 2px solid #2563EB;
                background-color: #FFFFFF;
            }
            QLineEdit[readOnly="true"] {
                background-color: #EDEEF0;
                color: #4B5563;
                border: 1px solid #E5E7EB;
                font-weight: 600;
            }
            
            /* Log Consoles (Terminal Style) */
            QTextEdit {
                background-color: #111827;
                color: #10B981;
                font-family: 'JetBrains Mono', monospace;
                border: 1px solid #374151;
                border-radius: 4px;
                padding: 8px;
            }
            
            /* ComboBox Styles */
            QComboBox {
                background-color: #FFFFFF;
                border: 1px solid #D1D5DB;
                border-radius: 4px;
                padding: 4px 8px;
                min-width: 60px;
            }
            QComboBox::drop-down {
                border: 0px;
            }
            
            /* Custom Styled Industrial Sliders */
            QSlider::groove:horizontal {
                border: 1px solid #E5E7EB;
                height: 6px;
                background: #E5E7EB;
                border-radius: 3px;
            }
            QSlider::handle:horizontal {
                background: #2563EB;
                border: 1px solid #2563EB;
                width: 14px;
                height: 14px;
                margin: -4px 0;
                border-radius: 7px;
            }
            QSlider::handle:horizontal:hover {
                background: #1D4ED8;
            }
            
            /* --- INDUSTRIAL ACTION BUTTONS --- */
            QPushButton {
                background-color: #F3F4F6;
                color: #374151;
                border: 1px solid #D1D5DB;
                border-radius: 4px;
                padding: 8px 12px;
                font-weight: 500;
            }
            QPushButton:hover {
                background-color: #E5E7EB;
                border-color: #9CA3AF;
            }
            QPushButton:pressed {
                background-color: #D1D5DB;
            }
            
            /* Primary Operations (Active Solid Blue) */
            QPushButton#btn_primary, QPushButton[text="Connect"], QPushButton[text="Send"], QPushButton[text="Print"] {
                background-color: #2563EB;
                color: #FFFFFF;
                border: 1px solid #1D4ED8;
                font-weight: 600;
            }
            QPushButton#btn_primary:hover, QPushButton[text="Connect"]:hover, QPushButton[text="Send"]:hover, QPushButton[text="Print"]:hover {
                background-color: #1D4ED8;
            }
            
            /* Safety & Stop Triggers (High Contrast Emergency Orange/Red) */
            QPushButton[text="Abort"], QPushButton[text="Stop"] {
                background-color: #DC2626;
                color: #FFFFFF;
                border: 1px solid #B91C1C;
                font-weight: 700;
            }
            QPushButton[text="Abort"]:hover, QPushButton[text="Stop"]:hover {
                background-color: #B91C1C;
            }
            
            /* Pause Trigger Warning States */
            QPushButton[text="Pause"] {
                background-color: #D97706;
                color: #FFFFFF;
                border: 1px solid #B45309;
                font-weight: 600;
            }
            QPushButton[text="Pause"]:hover {
                background-color: #B45309;
            }
        """)

        # ==========================================
        # 1. LEFT PANEL: CAD PREVIEW & JOB CONTROL CARD
        # ==========================================
        left_card = QFrame(self)
        left_card.setObjectName("card_panel")
        left_layout = QVBoxLayout(left_card)
        left_layout.setSpacing(12)
        
        self.image_title = QLabel('Image & Print Preview', self)
        self.image_title.setObjectName("section_title")
        left_layout.addWidget(self.image_title)
        
        # Dual-Window Layout (Slice Preview & Top down rendering)
        images_container = QHBoxLayout()
        self.input_window = QLabel(self)
        self.input_window.setMinimumSize(180, 180)
        self.input_window.setStyleSheet("background-color: #111827; border-radius: 4px; border: 1px solid #374151;")
        self.input_window.setAlignment(Qt.AlignCenter)
        
        self.output_window = QLabel(self)
        self.output_window.setMinimumSize(180, 180)
        self.output_window.setStyleSheet("background-color: #111827; border-radius: 4px; border: 1px solid #374151;")
        self.output_window.setAlignment(Qt.AlignCenter)
        
        images_container.addWidget(self.input_window)
        images_container.addWidget(self.output_window)
        left_layout.addLayout(images_container)
        
        # Slider & Utilities Control Grid
        img_control_grid = QGridLayout()
        img_control_grid.setSpacing(8)
        
        # Layer Slider Row
        self.layer_slider = QSlider(Qt.Horizontal)
        self.layer_slider.setMinimum(0)
        self.layer_slider.setMaximum(0)
        self.layer_slider.setValue(0)
        self.layer_slider_value = QLabel('Layer: 0', self)
        self.layer_slider_value.setFont(QFont("JetBrains Mono", 9))
        img_control_grid.addWidget(QLabel('Layer Selection:', self), 0, 0)
        img_control_grid.addWidget(self.layer_slider, 0, 1, 1, 2)
        img_control_grid.addWidget(self.layer_slider_value, 0, 3)
        
        # Threshold Slider Row
        self.threshold_slider = QSlider(Qt.Horizontal)
        self.threshold_slider.setMinimum(0)
        self.threshold_slider.setMaximum(255)
        self.threshold_slider.setValue(128)
        self.threshold_slider_value = QLabel('Threshold: 128', self)
        self.threshold_slider_value.setFont(QFont("JetBrains Mono", 9))
        img_control_grid.addWidget(QLabel('Threshold Adjust:', self), 1, 0)
        img_control_grid.addWidget(self.threshold_slider, 1, 1, 1, 2)
        img_control_grid.addWidget(self.threshold_slider_value, 1, 3)
        
        # DPI Combo Dropdown Row
        self.dpi_title = QLabel('DPI Settings:', self)
        self.dpi_combo = QComboBox()
        self.dpi_combo.addItems(["600", "300", "200", "150"])
        img_control_grid.addWidget(self.dpi_title, 2, 0)
        img_control_grid.addWidget(self.dpi_combo, 2, 1, 1, 3)
        
        left_layout.addLayout(img_control_grid)
        
        # File Operations Buttons Layout
        bottom_file_layout = QHBoxLayout()
        self.file_open_button = QPushButton('Open File', self)
        self.file_convert_button = QPushButton('Convert', self)
        bottom_file_layout.addWidget(self.file_open_button)
        bottom_file_layout.addWidget(self.file_convert_button)
        left_layout.addLayout(bottom_file_layout)
        
        # Print Command Area Buttons
        print_action_layout = QHBoxLayout()
        self.file_print_button = QPushButton('Print', self)
        self.pause_button = QPushButton('Pause', self)
        self.abort_button = QPushButton('Abort', self)
        print_action_layout.addWidget(self.file_print_button)
        print_action_layout.addWidget(self.pause_button)
        print_action_layout.addWidget(self.abort_button)
        left_layout.addWidget(self.abort_button) # Add backup explicit sizing if needed
        left_layout.addLayout(print_action_layout)

        # ==========================================
        # 2. MIDDLE PANEL: CNC MOTION FUNCTIONS CARD
        # ==========================================
        mid_card = QFrame(self)
        mid_card.setObjectName("card_panel")
        mid_layout = QVBoxLayout(mid_card)
        mid_layout.setSpacing(10)
        
        self.motion_function_title = QLabel('CNC Motion Control', self)
        self.motion_function_title.setObjectName("section_title")
        mid_layout.addWidget(self.motion_function_title)
        
        # Jog Button Cross Controller Grid Layout
        jog_grid = QGridLayout()
        jog_grid.setSpacing(6)
        self.motion_yp = QPushButton('Y+', self)
        self.motion_yn = QPushButton('Y-', self)
        self.motion_xp = QPushButton('X+', self)
        self.motion_xn = QPushButton('X-', self)
        self.motion_goto_home = QPushButton('Home XY', self)
        self.motion_home = QPushButton('Home Config', self)
        
        jog_grid.addWidget(self.motion_yp, 0, 1)
        jog_grid.addWidget(self.motion_xn, 1, 0)
        jog_grid.addWidget(self.motion_goto_home, 1, 1)
        jog_grid.addWidget(self.motion_xp, 1, 2)
        jog_grid.addWidget(self.motion_yn, 2, 1)
        mid_layout.addLayout(jog_grid)

        # Powder Bed Pistons Control
        pistons_layout = QGridLayout()
        pistons_layout.setSpacing(6)
        self.motion_fu = QPushButton('Feed Up', self)
        self.motion_fd = QPushButton('Feed Dn', self)
        self.motion_bu = QPushButton('Build Up', self)
        self.motion_bd = QPushButton('Build Dn', self)
        
        pistons_layout.addWidget(QLabel('Feed Piston:', self), 0, 0)
        pistons_layout.addWidget(self.motion_fu, 0, 1)
        pistons_layout.addWidget(self.motion_fd, 0, 2)
        pistons_layout.addWidget(QLabel('Build Piston:', self), 1, 0)
        pistons_layout.addWidget(self.motion_bu, 1, 1)
        pistons_layout.addWidget(self.motion_bd, 1, 2)
        mid_layout.addLayout(pistons_layout)
        
        # Layer thickness inputs & Sweeper overrides
        sweeper_layout = QGridLayout()
        sweeper_layout.setSpacing(6)
        self.motion_layer_thickness = QLineEdit(self)
        self.motion_layer_thickness.setPlaceholderText("Layer Thick [mm]")
        self.motion_spreader = QPushButton('Spreader Spn', self)
        self.motion_new_layer = QPushButton('New Layer', self)
        self.motion_prime_layer = QPushButton('Prime Layer', self)
        
        sweeper_layout.addWidget(QLabel('Thickness:', self), 0, 0)
        sweeper_layout.addWidget(self.motion_layer_thickness, 0, 1, 1, 2)
        sweeper_layout.addWidget(self.motion_spreader, 1, 0)
        sweeper_layout.addWidget(self.motion_new_layer, 1, 1)
        sweeper_layout.addWidget(self.motion_prime_layer, 1, 2)
        mid_layout.addLayout(sweeper_layout)
        
        # Live Axis Telemetrys Readouts
        telemetry_box = QGroupBox("Active Coordinate Monitoring", self)
        telemetry_layout = QGridLayout(telemetry_box)
        telemetry_layout.setSpacing(4)
        
        self.motion_x_pos_title = QLabel('X Motor Realtime:', self)
        self.motion_y_pos_title = QLabel('Y Motor Realtime:', self)
        self.motion_f_pos_title = QLabel('Feed Indexer:', self)
        self.motion_b_pos_title = QLabel('Build Indexer:', self)
        self.motion_state_title = QLabel('Hardware State:', self)
        
        self.motion_x_pos = QLineEdit("0.000", self)
        self.motion_x_pos.setReadOnly(True)
        self.motion_y_pos = QLineEdit("0.000", self)
        self.motion_y_pos.setReadOnly(True)
        self.motion_f_pos = QLineEdit("0.000", self)
        self.motion_f_pos.setReadOnly(True)
        self.motion_b_pos = QLineEdit("0.000", self)
        self.motion_b_pos.setReadOnly(True)
        self.motion_state = QLineEdit("READY", self)
        self.motion_state.setReadOnly(True)
        
        telemetry_layout.addWidget(self.motion_x_pos_title, 0, 0)
        telemetry_layout.addWidget(self.motion_x_pos, 0, 1)
        telemetry_layout.addWidget(self.motion_y_pos_title, 1, 0)
        telemetry_layout.addWidget(self.motion_y_pos, 1, 1)
        telemetry_layout.addWidget(self.motion_f_pos_title, 2, 0)
        telemetry_layout.addWidget(self.motion_f_pos, 2, 1)
        telemetry_layout.addWidget(self.motion_b_pos_title, 3, 0)
        telemetry_layout.addWidget(self.motion_b_pos, 3, 1)
        telemetry_layout.addWidget(self.motion_state_title, 4, 0)
        telemetry_layout.addWidget(self.motion_state, 4, 1)
        mid_layout.addWidget(telemetry_box)

        # ==========================================
        # 3. RIGHT PANEL: INKJET CONTROLLER & CONNECTION LOGS CARD
        # ==========================================
        right_card = QFrame(self)
        right_card.setObjectName("card_panel")
        right_layout = QVBoxLayout(right_card)
        right_layout.setSpacing(8)
        
        # --- Connection Serial Console block A ---
        self.motion_title = QLabel('Motion Connection Serial Log', self)
        self.motion_title.setObjectName("section_title")
        right_layout.addWidget(self.motion_title)
        
        motion_conn_layout = QHBoxLayout()
        self.motion_set_port = QLineEdit("COM3 - Main", self)
        self.motion_connect = QPushButton('Connect', self)
        motion_conn_layout.addWidget(self.motion_set_port, 3)
        motion_conn_layout.addWidget(self.motion_connect, 1)
        right_layout.addLayout(motion_conn_layout)
        
        self.motion_serial_output = QTextEdit(self)
        self.motion_serial_output.setReadOnly(True)
        self.motion_serial_output.setMaximumHeight(80)
        right_layout.addWidget(self.motion_serial_output)
        
        motion_command_layout = QHBoxLayout()
        self.motion_write_line = QLineEdit(self)
        self.motion_write_line.setPlaceholderText("Send raw G-Code line...")
        self.motion_send_line = QPushButton('Send', self)
        motion_command_layout.addWidget(self.motion_write_line, 3)
        motion_command_layout.addWidget(self.motion_send_line, 1)
        right_layout.addLayout(motion_command_layout)
        
        self.motion_serial_input = QTextEdit(self)
        self.motion_serial_input.setReadOnly(True)
        self.motion_serial_input.setMaximumHeight(40)
        right_layout.addWidget(self.motion_serial_input)

        # --- Inkjet Hardware Functions block ---
        self.inkjet_function_title = QLabel('Inkjet Mechanical System', self)
        self.inkjet_function_title.setObjectName("section_title")
        right_layout.addWidget(self.inkjet_function_title)
        
        ink_conn_layout = QHBoxLayout()
        self.inkjet_set_port = QLineEdit("/dev/ttyUSB1", self)
        self.inkjet_connect = QPushButton('Connect', self)
        ink_conn_layout.addWidget(self.inkjet_set_port, 3)
        ink_conn_layout.addWidget(self.inkjet_connect, 1)
        right_layout.addLayout(ink_conn_layout)
        
        # Inkjet triggers
        ink_triggers = QGridLayout()
        ink_triggers.setSpacing(6)
        self.inkjet_set_pos = QPushButton('Set Position', self)
        self.inkjet_preheat = QPushButton('Preheat', self)
        self.inkjet_prime = QPushButton('Prime', self)
        self.inkjet_set_density = QPushButton('Set Density', self)
        self.inkjet_test_button = QPushButton('Test Print', self)
        self.inkjet_test_state = QLineEdit("Idle", self)
        self.inkjet_test_state.setReadOnly(True)
        
        self.inkjet_density = QSlider(Qt.Horizontal)
        self.inkjet_density.setMinimum(1)
        self.inkjet_density.setMaximum(100)
        self.inkjet_density.setValue(10)
        
        ink_triggers.addWidget(self.inkjet_set_pos, 0, 0)
        ink_triggers.addWidget(self.inkjet_preheat, 0, 1)
        ink_triggers.addWidget(self.inkjet_prime, 0, 2)
        ink_triggers.addWidget(QLabel('Jetting Density:', self), 1, 0)
        ink_triggers.addWidget(self.inkjet_density, 1, 1, 1, 2)
        ink_triggers.addWidget(self.inkjet_set_density, 2, 0)
        ink_triggers.addWidget(self.inkjet_test_button, 2, 1)
        ink_triggers.addWidget(self.inkjet_test_state, 2, 2)
        right_layout.addLayout(ink_triggers)
        
        # Inkjet Telemetry Display Section
        inkjet_telemetry = QGroupBox("Print Head Telemetry", self)
        inkjet_telemetry_layout = QGridLayout(inkjet_telemetry)
        inkjet_telemetry_layout.setSpacing(4)
        
        self.inkjet_pos_title = QLabel('Encoder Position:', self)
        self.inkjet_temp_title = QLabel('Head Temp (°C):', self)
        self.inkjet_writeleft_title = QLabel('Buffers Unwritten:', self)
        self.inkjet_pos = QLineEdit("0", self)
        self.inkjet_pos.setReadOnly(True)
        self.inkjet_temperature = QLineEdit("35.4", self)
        self.inkjet_temperature.setReadOnly(True)
        self.inkjet_writeleft = QLineEdit("0", self)
        self.inkjet_writeleft.setReadOnly(True)
        
        inkjet_telemetry_layout.addWidget(self.inkjet_pos_title, 0, 0)
        inkjet_telemetry_layout.addWidget(self.inkjet_pos, 0, 1)
        inkjet_telemetry_layout.addWidget(self.inkjet_temp_title, 1, 0)
        inkjet_telemetry_layout.addWidget(self.inkjet_temperature, 1, 1)
        inkjet_telemetry_layout.addWidget(self.inkjet_writeleft_title, 2, 0)
        inkjet_telemetry_layout.addWidget(self.inkjet_writeleft, 2, 1)
        right_layout.addWidget(inkjet_telemetry)
        
        # Core Serial communications
        self.inkjet_title = QLabel("Print Head Serial Live Log", self)
        self.inkjet_title.setStyleSheet("font-weight: 600; color: #4B5563; font-family: 'JetBrains Mono';")
        right_layout.addWidget(self.inkjet_title)
        
        self.inkjet_serial_output = QTextEdit(self)
        self.inkjet_serial_output.setReadOnly(True)
        self.inkjet_serial_output.setMaximumHeight(80)
        right_layout.addWidget(self.inkjet_serial_output)
        
        ink_cmd_send_layout = QHBoxLayout()
        self.inkjet_write_line = QLineEdit(self)
        self.inkjet_write_line.setPlaceholderText("Send manual HP45 hex line...")
        self.inkjet_send_line = QPushButton('Send', self)
        ink_cmd_send_layout.addWidget(self.inkjet_write_line, 3)
        ink_cmd_send_layout.addWidget(self.inkjet_send_line, 1)
        right_layout.addLayout(ink_cmd_send_layout)
        
        self.inkjet_serial_input = QTextEdit(self)
        self.inkjet_serial_input.setReadOnly(True)
        self.inkjet_serial_input.setMaximumHeight(40)
        right_layout.addWidget(self.inkjet_serial_input)

        # Append cards elements into central workspace layouts
        main_layout.addWidget(left_card, 4)
        main_layout.addWidget(mid_card, 3)
        main_layout.addWidget(right_card, 5)

        # --- [4] REGISTER SIGNALS AND DEFAULTS CODES (100% Retained) ---
        self.threshold_slider.valueChanged.connect(self.UpdateThresholdSliderValue) 
        
        # Tooltips & Window positioning anchors
        self.motion_connect.setToolTip("The COM port the GRBL is on. 'COM#' for Windows, '/dev/ttyUSB#' for Linux") 
        self.inkjet_connect.setToolTip("The COM port the HP45 is on. 'COM#' for Windows, '/dev/ttyUSB#' for Linux") 
        self.motion_send_line.setToolTip("Send a raw command to the GRBL") 
        self.inkjet_send_line.setToolTip("Send a raw command to the HP45")
        self.motion_new_layer.setToolTip("Add a new layer by moving feed up, build down and transering the powder using the spreader [mm]")
        self.motion_prime_layer.setToolTip("Add a new layer of powder without moving build [mm]")
        self.inkjet_preheat.setToolTip("Send a burst of short pulses to the printhead, heating up the printhead without ejecting (much) ink")
        self.inkjet_prime.setToolTip("Send a burst of long pulses to the printhead, ejecting with each nozzle")

        self.setMinimumSize(1280, 820)
        self.center()
        self.setWindowTitle('Oasis Controller - High Density HMI')
        self.setWindowIcon(QIcon('yteclogo.png')) 
        self.show()

        self.setAcceptDrops(True)

    # --- [5] DYNAMIC RESPONSIVE FONT SCALING (resizeEvent) ---
    def resizeEvent(self, event):
        super().resizeEvent(event)
        # 윈도우 너비를 기준으로 글꼴의 비례 비율 계산
        width = self.width()
        base_size = max(10, min(14, int(width / 130)))
        
        # 전역 위젯 폰트 업데이트 규칙 적용 (Inter & JetBrains Mono)
        sans_font = QFont("Inter", base_size)
        mono_font = QFont("JetBrains Mono", base_size - 1)
        
        # UI 레이블 & 제어 위젯 일괄 폰트 스케일링
        for widget in self.findChildren((QLabel, QPushButton, QComboBox)):
            widget.setFont(sans_font)
        for text_widget in self.findChildren((QLineEdit, QTextEdit)):
            text_widget.setFont(mono_font)
            
        # 개별 특별 헤더 속성 최적화
        self.image_title.setFont(QFont("Inter", base_size + 3, QFont.Bold))
        self.motion_function_title.setFont(QFont("Inter", base_size + 3, QFont.Bold))
        self.inkjet_function_title.setFont(QFont("Inter", base_size + 3, QFont.Bold))

    # --- [6] FILE INTERACTIONS & EVENTS BACKEND ---
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.accept()
        else:
            event.ignore()

    def dropEvent(self, event):
        files = [str(u.toLocalFile()) for u in event.mimeData().urls()]
        for f in files:
            print (f)
        
    def center(self):
        qr = self.frameGeometry()
        cp = QDesktopWidget().availableGeometry().center()
        qr.moveCenter(cp)
        self.move(qr.topLeft())
        
    def UpdateThresholdSliderValue(self):
        """Updates the value next to the threshold slider"""
        temp_threshold = self.threshold_slider.value()
        self.threshold_slider_value.setText("Threshold: " + str(temp_threshold))

if __name__ == '__main__':
    app = QApplication(sys.argv)
    ex = Interface()
    ex.initUI()
    sys.exit(app.exec_())