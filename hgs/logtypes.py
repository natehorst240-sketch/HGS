"""The seven HGS log types, taken verbatim from the original binary's strings.

Each LogType names the display columns the original viewer showed. Column sets
are best-effort inferred from the binary's string table; refine once real data
files are available.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class LogType:
    key: str
    title: str          # menu / window title as in the original
    header: str         # the "HGS ... LOG DATA" clipboard/print header
    empty_message: str  # shown when no records match the selection
    columns: tuple[str, ...] = field(default_factory=tuple)


# Strings below are lifted directly from Hgs_cpp.exe.
LOG_TYPES: tuple[LogType, ...] = (
    LogType(
        key="exceedance",
        title="Exceedance Log",
        header="HGS EXCEEDANCE LOG DATA",
        empty_message="NO EXCEEDINGS ARE AVAILABLE FOR THE CURRENT SELECTIONS",
        # .HG6 front block is the parameter catalog; the trailing uint16 per
        # entry is a sequence/record ID, NOT an event count (confirmed against
        # the original app showing "NO EXCEEDINGS" for a file where these are
        # populated). Actual exceedance event records only appear when events
        # occurred.
        columns=("Parameter", "Seq ID"),
    ),
    LogType(
        key="fault",
        title="Fault Log",
        header="HGS FAULT LOG DATA",
        empty_message="NO FAULTS ARE AVAILABLE FOR THE CURRENT SELECTIONS",
        # Decoded from .HG6 catalog records with populated occurrence fields;
        # event list verified against the original app's Fault Log display.
        columns=("Event", "First Occurrence", "Last Occurrence", "Count"),
    ),
    LogType(
        key="cumulative",
        title="Cumulative Log",
        header="HGS CUMULATIVE LOG DATA",
        empty_message="NO CUMULATIVES LOG DATA ARE AVAILABLE FOR THE CURRENT SELECTIONS",
        # Key/value form mirroring the app's Cumulative Log Display.
        columns=("Item", "Value"),
    ),
    LogType(
        key="time_history",
        title="Time History Log",
        header="HGS TIME_HISTORY LOG DATA",
        empty_message="NO TIME HISTORY LOG DATA ARE AVAILABLE FOR THE CURRENT SELECTIONS",
        # Decoded from real .HG6 downloads and verified value-for-value
        # against the original app's Time History Log Display.
        columns=("Time", "N1 1 (%)", "N2 1 (%)", "TRQ 1 (%)", "TOT 1 (degC)",
                 "CLP 1 (%)", "N1 2 (%)", "N2 2 (%)", "TRQ 2 (%)",
                 "TOT 2 (degC)", "CLP 2 (%)", "NR (%)"),
    ),
    LogType(
        key="power_assurance",
        title="Power Assurance Log",
        header="HGS POWER_ASSURANCE LOG DATA",
        empty_message="NO POWER ASSURANCE LOG DATA ARE AVAILABLE FOR THE CURRENT SELECTIONS",
        # Stored fields only; the app's TOT/N1 "Calc" columns are computed
        # at display time from its PA model, not stored in the download.
        columns=("Time", "OAT (degC)", "Pa (feet)", "IAS (Kts)",
                 "N2 1 (%)", "TRQ 1 (%)", "TOT 1 Act (degC)", "N1 1 Act (%)",
                 "IDLE 1", "MAN 1",
                 "N2 2 (%)", "TRQ 2 (%)", "TOT 2 Act (degC)", "N1 2 Act (%)",
                 "IDLE 2", "MAN 2"),
    ),
    LogType(
        key="ids_status",
        title="IDS Status Log",
        header="HGS IDSSTATUS LOG DATA",
        empty_message="NO IDS STATUS LOG DATA ARE AVAILABLE FOR THE CURRENT SELECTIONS",
        columns=("Record No", "Date and Time", "Status", "Detail"),
    ),
    LogType(
        key="afcs_fault",
        title="AFCS Fault Log",
        header="HGS AFCSFAULT LOG DATA",
        empty_message="NO AFCSFAULTS ARE AVAILABLE FOR THE CURRENT SELECTIONS",
        # Same record layout as faults; labels carry "FAIL CODE nnn".
        columns=("Event", "First Occurrence", "Last Occurrence", "Count"),
    ),
)

BY_KEY = {lt.key: lt for lt in LOG_TYPES}
