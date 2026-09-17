"""Qt main window mirroring the original HGS menu layout."""
from __future__ import annotations

from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QMainWindow, QTableWidget, QTableWidgetItem, QTabWidget, QWidget,
    QVBoxLayout, QLabel, QMessageBox, QFileDialog, QStatusBar,
)

from . import APP_TITLE
from .config import Config
from .logtypes import LOG_TYPES, BY_KEY, LogType
from . import logformat, hg6
from .protocol import Downloader, SerialParams, State


class LogView(QWidget):
    def __init__(self, log_type: LogType):
        super().__init__()
        self.log_type = log_type
        layout = QVBoxLayout(self)
        self.info = QLabel(log_type.empty_message)
        self.table = QTableWidget(0, len(log_type.columns))
        self.table.setHorizontalHeaderLabels(list(log_type.columns))
        layout.addWidget(self.info)
        layout.addWidget(self.table)

    def set_rows(self, rows: list[list[str]]) -> None:
        if not rows:
            self.info.setText(self.log_type.empty_message)
            self.table.setRowCount(0)
            return
        self.info.setText(f"{len(rows)} record(s)")
        self.table.setRowCount(len(rows))
        ncols = len(self.log_type.columns)
        for r, row in enumerate(rows):
            for c in range(ncols):
                val = row[c] if c < len(row) else ""
                self.table.setItem(r, c, QTableWidgetItem(str(val)))
        self.table.resizeColumnsToContents()


class MainWindow(QMainWindow):
    def __init__(self, config: Config):
        super().__init__()
        self.config = config
        self.setWindowTitle(APP_TITLE)
        self.resize(900, 600)

        self.tabs = QTabWidget()
        self.views: dict[str, LogView] = {}
        for lt in LOG_TYPES:
            view = LogView(lt)
            self.views[lt.key] = view
            self.tabs.addTab(view, lt.title)
        self.setCentralWidget(self.tabs)

        self.setStatusBar(QStatusBar())
        self._status(State.IDLE.value)
        self._build_menus()

    # --- menus mirror the .cnt help structure -----------------------------
    def _build_menus(self) -> None:
        mb = self.menuBar()

        m_file = mb.addMenu("&File")
        self._add(m_file, "Open Log File...", self.open_file)
        m_file.addSeparator()
        self._add(m_file, "E&xit", self.close)

        m_ids = mb.addMenu("&IDS")
        self._add(m_ids, "Download Logs", lambda: self.download(self._current_key()))
        self._add(m_ids, "Download Cumulative", lambda: self.download("cumulative"))
        self._add(m_ids, "IDS Status Download", lambda: self.download("ids_status"))
        self._add(m_ids, "IDS Setup...", self.not_impl)

        m_view = mb.addMenu("&Data View")
        for lt in LOG_TYPES:
            self._add(m_view, lt.title,
                      lambda _=False, k=lt.key: self.tabs.setCurrentWidget(self.views[k]))

        m_tools = mb.addMenu("&Tools")
        self._add(m_tools, "Passwords...", self.not_impl)
        self._add(m_tools, "Com Settings...", self.not_impl)
        self._add(m_tools, "Directories...", self.not_impl)
        self._add(m_tools, "HGS Mode Settings...", self.not_impl)

        m_help = mb.addMenu("&Help")
        self._add(m_help, "About HGS", self.about)

    def _add(self, menu, text, slot) -> None:
        act = QAction(text, self)
        act.triggered.connect(slot)
        menu.addAction(act)

    # --- actions -----------------------------------------------------------
    def _current_key(self) -> str:
        return LOG_TYPES[self.tabs.currentIndex()].key

    def _status(self, text: str) -> None:
        self.statusBar().showMessage(text)

    def open_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Open HGS download",
            self.config.get("Hgs_Paths", "data_view_path"),
            "HGS downloads (*.HG1 *.HG2 *.HG3 *.HG4 *.HG5 *.HG6 *.HG7);;All files (*)")
        if not path:
            return
        if path.upper().endswith(tuple(f".HG{n}" for n in range(1, 8))):
            self._load_hg6(path)
            return
        key = self._current_key()
        lt = BY_KEY[key]
        try:
            rows = logformat.parse_file(path, lt)
        except NotImplementedError as exc:
            QMessageBox.warning(self, "Not yet supported", str(exc))
            return
        except Exception as exc:
            QMessageBox.critical(self, "Load error", f"Cannot read {path}\n{exc}")
            return
        self.views[key].set_rows(rows)
        self._status(f"Loaded {len(rows)} record(s) from {path}")

    def _load_hg6(self, path: str) -> None:
        try:
            parsed = hg6.parse_file(path)
        except Exception as exc:
            QMessageBox.critical(self, "Load error", f"Cannot parse {path}\n{exc}")
            return
        self.views["exceedance"].set_rows([[l, str(v)] for l, v in parsed.counters])
        self.views["fault"].set_rows(parsed.faults)
        self.views["afcs_fault"].set_rows(parsed.afcs_faults)
        self.views["cumulative"].set_rows(parsed.cumulative)
        self.views["power_assurance"].set_rows(parsed.power_assurance)
        self.views["time_history"].set_rows(parsed.time_history)
        if parsed.time_history:
            self.tabs.setCurrentWidget(self.views["time_history"])
        self._status(
            f"{path}: {len(parsed.counters)} parameters, "
            f"{len(parsed.faults)} faults, {len(parsed.afcs_faults)} AFCS faults, "
            f"{parsed.frame_count} frames, {len(parsed.time_history)} samples")

    def download(self, key: str) -> None:
        if not self.config.has_port:
            QMessageBox.warning(
                self, "No Port",
                "This function cannot be performed with a NO PORT PC !!!")
            return
        lt = BY_KEY[key]
        params = SerialParams(
            port=self.config.get("PcHwSetting", "com_port"),
            baud=int(self.config.get("PcHwSetting", "baud")),
            parity=self.config.get("PcHwSetting", "parity"),
            bytesize=int(self.config.get("PcHwSetting", "bytesize")),
            stopbits=int(self.config.get("PcHwSetting", "stopbits")),
        )
        dl = Downloader(params, lambda st, d: self._status(f"{st.value} {d}".strip()))
        raw = dl.run(key)
        if raw is None:
            return
        try:
            rows = logformat.parse(raw, lt)
        except NotImplementedError as exc:
            QMessageBox.warning(self, "Not yet supported", str(exc))
            return
        self.views[key].set_rows(rows)

    def not_impl(self) -> None:
        QMessageBox.information(self, "HGS", "Not implemented in this scaffold yet.")

    def about(self) -> None:
        QMessageBox.about(
            self, "About",
            f"{APP_TITLE}\nLinux re-implementation scaffold\n"
            "Port of the MFC ground-station application.")
