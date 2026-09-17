"""Configuration store.

The original HGS kept these under the Windows registry / an .INI file, in the
keys `Hgs_Paths`, `HgsModeSetting`, `PcHwSetting`, `OnePortComChAssign`, etc.
Here we use a plain INI at ~/.config/hgs/hgs.ini so it is portable to Linux.
"""
from __future__ import annotations

import configparser
from pathlib import Path

CONFIG_DIR = Path.home() / ".config" / "hgs"
CONFIG_PATH = CONFIG_DIR / "hgs.ini"

DEFAULTS = {
    "Hgs_Paths": {
        # Mirrors INSTALLATION_PATH / DATA_DOWNLOAD_PATH / DATA_VIEW_PATH /
        # DESTINATION_PATH / SOURCE_PATH from the original binary.
        "installation_path": str(CONFIG_DIR),
        "data_download_path": str(Path.home() / "hgs-data" / "download"),
        "data_view_path": str(Path.home() / "hgs-data" / "view"),
    },
    "PcHwSetting": {
        # OnePortComChAssign: which serial port the DAU cable is on.
        # "" means "NO PORT PC" (view-only mode, no downloads possible).
        "com_port": "/dev/ttyUSB0",
        "baud": "9600",       # from the "9600,n,8,1" string in the binary
        "parity": "N",
        "bytesize": "8",
        "stopbits": "1",
    },
    "HgsModeSetting": {
        # HgsMode_Configuration: DownloadProcedureMode / view-only, etc.
        "mode": "download",   # download | view_only
    },
    "Settings": {
        "user_role": "USER",  # USER | ADMINISTRATOR
    },
}


class Config:
    def __init__(self, path: Path = CONFIG_PATH):
        self.path = path
        self._cp = configparser.ConfigParser()
        self.load()

    def load(self) -> None:
        # Seed defaults, then overlay whatever is on disk (immutably rebuilt).
        self._cp.read_dict(DEFAULTS)
        if self.path.exists():
            self._cp.read(self.path)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w") as fh:
            self._cp.write(fh)

    def get(self, section: str, key: str) -> str:
        return self._cp.get(section, key)

    def set(self, section: str, key: str, value: str) -> None:
        if not self._cp.has_section(section):
            self._cp.add_section(section)
        self._cp.set(section, key, value)

    @property
    def has_port(self) -> bool:
        """The original refused downloads on a 'NO PORT PC'."""
        return bool(self.get("PcHwSetting", "com_port").strip())
