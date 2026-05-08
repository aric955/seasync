"""
SeaSync V2.2 Adapters 模块
导出所有数据适配器。
"""

# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 荣火
from .base_adapter import BaseAdapter
from .radar_adapter import RadarAdapter
from .ais_adapter import AISAdapter
from .gps_adapter import GPSAdapter
from .csv_adapter import CSVAdapter
from .dat_adapter import DatAdapter
from .mat_adapter import MatAdapter
from .xlsx_adapter import XLSXAdapter
from .txt_track_adapter import TXTTrackAdapter
from .import_manager import ImportManager, _auto_detect_type

__all__ = [
    "BaseAdapter",
    "RadarAdapter",
    "AISAdapter",
    "GPSAdapter",
    "CSVAdapter",
    "DatAdapter",
    "MatAdapter",
    "XLSXAdapter",
    "TXTTrackAdapter",
    "ImportManager",
    "_auto_detect_type",
]
