"""Entry point: `python -m hgs`."""
from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from .config import Config
from .ui import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    config = Config()
    win = MainWindow(config)
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
