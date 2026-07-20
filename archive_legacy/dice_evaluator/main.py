"""Standalone Oasis Dice Evaluator GUI.

Run with:
    python -m dice_evaluator.main
"""

import sys
from pathlib import Path

import numpy as np
from PyQt5 import QtCore, QtGui, QtWidgets

from .calibrate import load_calibration
from .constants import CALIB_NPZ_FILENAME
from .evaluator import DiceEvaluator


# ──────────────────────────────────────────────────────────────────────────────
# Background worker
# ──────────────────────────────────────────────────────────────────────────────

class _EvalWorker(QtCore.QThread):
    """Runs DiceEvaluator.evaluate_all() off the main thread."""

    progress = QtCore.pyqtSignal(int, int, float)   # layer_idx, total, dice
    finished = QtCore.pyqtSignal(object)             # pd.DataFrame
    error = QtCore.pyqtSignal(str)

    def __init__(self, evaluator: DiceEvaluator, total_layers: int) -> None:
        super().__init__()
        self._evaluator = evaluator
        self._total = total_layers

    def run(self) -> None:
        try:
            import re
            from typing import List, Tuple

            pattern = re.compile(r"layer_(\d+)\.png$", re.IGNORECASE)
            captures_dir = self._evaluator.captures_dir
            overlays_dir = captures_dir / "overlays"
            overlays_dir.mkdir(exist_ok=True)

            import cv2, pandas as pd

            png_files: List[Tuple[int, Path]] = []
            for p in captures_dir.iterdir():
                m = pattern.match(p.name)
                if m:
                    png_files.append((int(m.group(1)), p))
            png_files.sort(key=lambda t: t[0])

            records = []
            total = len(png_files)
            for i, (layer_idx, png_path) in enumerate(png_files, 1):
                bgr = cv2.imread(str(png_path))
                if bgr is None:
                    continue
                img_rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
                result = self._evaluator.evaluate_layer(layer_idx, img_rgb)

                overlay_bgr = cv2.cvtColor(result["overlay"], cv2.COLOR_RGB2BGR)
                overlay_path = overlays_dir / f"layer_{layer_idx:03d}_overlay.png"
                cv2.imwrite(str(overlay_path), overlay_bgr)

                records.append({"layer": result["layer"], "dice": result["dice"]})
                self.progress.emit(layer_idx, total, result["dice"])

            df = pd.DataFrame(records, columns=["layer", "dice"])
            svg_stem = self._evaluator.svg_path.stem
            csv_path = captures_dir / f"{svg_stem}_dice_log.csv"
            df.to_csv(str(csv_path), index=False)

            self.finished.emit(df)
        except Exception as exc:
            self.error.emit(str(exc))


# ──────────────────────────────────────────────────────────────────────────────
# Main window
# ──────────────────────────────────────────────────────────────────────────────

class MainWindow(QtWidgets.QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Oasis Dice Evaluator")
        self.resize(640, 500)
        self._worker = None
        self._csv_path: Path | None = None

        self._build_ui()

    def _build_ui(self) -> None:
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        layout = QtWidgets.QVBoxLayout(central)
        layout.setSpacing(8)
        layout.setContentsMargins(12, 12, 12, 12)

        # ── SVG file row ──────────────────────────────────────────────────────
        svg_row = QtWidgets.QHBoxLayout()
        svg_row.addWidget(QtWidgets.QLabel("SVG File:"))
        self._svg_edit = QtWidgets.QLineEdit()
        self._svg_edit.setPlaceholderText("Path to .svg used for printing…")
        self._svg_edit.textChanged.connect(self._on_svg_changed)
        svg_row.addWidget(self._svg_edit, 1)
        svg_browse = QtWidgets.QPushButton("Browse")
        svg_browse.clicked.connect(self._browse_svg)
        svg_row.addWidget(svg_browse)
        layout.addLayout(svg_row)

        # ── Captures dir row ─────────────────────────────────────────────────
        cap_row = QtWidgets.QHBoxLayout()
        cap_row.addWidget(QtWidgets.QLabel("Captures Dir:"))
        self._cap_edit = QtWidgets.QLineEdit()
        self._cap_edit.setPlaceholderText("Directory containing layer_*.png…")
        cap_row.addWidget(self._cap_edit, 1)
        cap_browse = QtWidgets.QPushButton("Browse")
        cap_browse.clicked.connect(self._browse_captures)
        cap_row.addWidget(cap_browse)
        layout.addLayout(cap_row)

        # ── Calibration status row ────────────────────────────────────────────
        calib_row = QtWidgets.QHBoxLayout()
        calib_row.addWidget(QtWidgets.QLabel("Calibration:"))
        self._calib_label = QtWidgets.QLabel("● No SVG selected")
        self._calib_label.setStyleSheet("color: grey;")
        calib_row.addWidget(self._calib_label, 1)
        reset_btn = QtWidgets.QPushButton("Reset")
        reset_btn.setToolTip("Delete calibration.npz and re-run from the printer UI")
        reset_btn.clicked.connect(self._reset_calibration)
        calib_row.addWidget(reset_btn)
        layout.addLayout(calib_row)

        layout.addWidget(_HLine())

        # ── Run button ────────────────────────────────────────────────────────
        self._run_btn = QtWidgets.QPushButton("Run Evaluation")
        self._run_btn.setFixedHeight(36)
        font = self._run_btn.font()
        font.setBold(True)
        self._run_btn.setFont(font)
        self._run_btn.clicked.connect(self._run_evaluation)
        layout.addWidget(self._run_btn)

        # ── Progress bar ──────────────────────────────────────────────────────
        self._progress = QtWidgets.QProgressBar()
        self._progress.setValue(0)
        self._progress.setTextVisible(True)
        layout.addWidget(self._progress)

        # ── Results table ─────────────────────────────────────────────────────
        self._table = QtWidgets.QTableWidget(0, 2)
        self._table.setHorizontalHeaderLabels(["Layer", "Dice Score"])
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self._table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        layout.addWidget(self._table, 1)

        # ── Bottom buttons ────────────────────────────────────────────────────
        btn_row = QtWidgets.QHBoxLayout()
        export_btn = QtWidgets.QPushButton("Export CSV")
        export_btn.clicked.connect(self._export_csv)
        btn_row.addWidget(export_btn)
        overlays_btn = QtWidgets.QPushButton("View Overlays")
        overlays_btn.clicked.connect(self._view_overlays)
        btn_row.addWidget(overlays_btn)
        layout.addLayout(btn_row)

    # ── Slots ─────────────────────────────────────────────────────────────────

    def _browse_svg(self) -> None:
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Select SVG File", "", "SVG files (*.svg)"
        )
        if path:
            self._svg_edit.setText(path)

    def _browse_captures(self) -> None:
        path = QtWidgets.QFileDialog.getExistingDirectory(
            self, "Select Captures Directory"
        )
        if path:
            self._cap_edit.setText(path)

    def _on_svg_changed(self, text: str) -> None:
        svg_dir = Path(text).parent if text else None
        if svg_dir and (svg_dir / CALIB_NPZ_FILENAME).exists():
            self._calib_label.setText("● Calibrated")
            self._calib_label.setStyleSheet("color: green; font-weight: bold;")
        elif text:
            self._calib_label.setText("● Not calibrated")
            self._calib_label.setStyleSheet("color: red; font-weight: bold;")
        else:
            self._calib_label.setText("● No SVG selected")
            self._calib_label.setStyleSheet("color: grey;")

    def _reset_calibration(self) -> None:
        svg_path = Path(self._svg_edit.text())
        npz = svg_path.parent / CALIB_NPZ_FILENAME
        if npz.exists():
            npz.unlink()
            self._on_svg_changed(self._svg_edit.text())
            QtWidgets.QMessageBox.information(
                self, "Reset", "calibration.npz deleted. Re-run calibration from the printer UI."
            )
        else:
            QtWidgets.QMessageBox.information(self, "Reset", "No calibration file found.")

    def _run_evaluation(self) -> None:
        svg_text = self._svg_edit.text().strip()
        cap_text = self._cap_edit.text().strip()

        if not svg_text or not cap_text:
            QtWidgets.QMessageBox.warning(self, "Missing Input", "Please set both SVG file and Captures Dir.")
            return

        svg_path = Path(svg_text)
        cap_dir = Path(cap_text)

        if not (svg_path.parent / CALIB_NPZ_FILENAME).exists():
            QtWidgets.QMessageBox.critical(
                self,
                "Calibration Required",
                "Calibration required. Please run calibration from the printer UI.",
            )
            return

        # Count PNGs for progress bar
        import re
        pattern = re.compile(r"layer_(\d+)\.png$", re.IGNORECASE)
        png_count = sum(1 for p in cap_dir.iterdir() if pattern.match(p.name))
        if png_count == 0:
            QtWidgets.QMessageBox.warning(self, "No Images", "No layer_*.png files found in captures directory.")
            return

        # Build a dummy image_array — caller must supply the real one in integrated use.
        # Here we load a placeholder that evaluate_layer will use; the GUI is standalone.
        image_array = np.ones((100, 100), dtype=np.uint8)

        try:
            evaluator = DiceEvaluator(str(svg_path), image_array, str(cap_dir))
        except FileNotFoundError as exc:
            QtWidgets.QMessageBox.critical(self, "Error", str(exc))
            return

        self._table.setRowCount(0)
        self._progress.setMaximum(png_count)
        self._progress.setValue(0)
        self._run_btn.setEnabled(False)

        self._worker = _EvalWorker(evaluator, png_count)
        self._worker.progress.connect(self._on_layer_done)
        self._worker.finished.connect(self._on_finished)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def _on_layer_done(self, layer_idx: int, total: int, dice: float) -> None:
        self._progress.setValue(self._progress.value() + 1)
        row = self._table.rowCount()
        self._table.insertRow(row)
        self._table.setItem(row, 0, QtWidgets.QTableWidgetItem(str(layer_idx)))
        dice_item = QtWidgets.QTableWidgetItem(f"{dice:.4f}")
        dice_item.setTextAlignment(QtCore.Qt.AlignCenter)
        self._table.setItem(row, 1, dice_item)

    def _on_finished(self, df) -> None:
        self._run_btn.setEnabled(True)
        cap_dir = Path(self._cap_edit.text())
        svg_stem = Path(self._svg_edit.text()).stem
        self._csv_path = cap_dir / f"{svg_stem}_dice_log.csv"
        QtWidgets.QMessageBox.information(
            self,
            "Done",
            f"Evaluation complete. {len(df)} layers processed.\nCSV saved to:\n{self._csv_path}",
        )

    def _on_error(self, msg: str) -> None:
        self._run_btn.setEnabled(True)
        QtWidgets.QMessageBox.critical(self, "Evaluation Error", msg)

    def _export_csv(self) -> None:
        if self._csv_path is None or not self._csv_path.exists():
            QtWidgets.QMessageBox.warning(self, "No CSV", "Run evaluation first.")
            return
        dest, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Export CSV", str(self._csv_path.name), "CSV files (*.csv)"
        )
        if dest:
            import shutil
            shutil.copy2(str(self._csv_path), dest)

    def _view_overlays(self) -> None:
        cap_text = self._cap_edit.text().strip()
        if not cap_text:
            QtWidgets.QMessageBox.warning(self, "No Directory", "Set captures directory first.")
            return
        overlays_dir = Path(cap_text) / "overlays"
        overlays_dir.mkdir(exist_ok=True)
        QtGui.QDesktopServices.openUrl(
            QtCore.QUrl.fromLocalFile(str(overlays_dir))
        )


class _HLine(QtWidgets.QFrame):
    def __init__(self) -> None:
        super().__init__()
        self.setFrameShape(QtWidgets.QFrame.HLine)
        self.setFrameShadow(QtWidgets.QFrame.Sunken)


# ──────────────────────────────────────────────────────────────────────────────

def main() -> None:
    app = QtWidgets.QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
