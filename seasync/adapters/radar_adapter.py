"""
SeaSync V2.2 RadarAdapter — 雷达数据适配器。
支持格式：
  - CSV（原始点迹）：timestamp, range_nm, azimuth_deg, snr_db
  - AIS 消息（某些雷达附带 AIS 解码）
"""

# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 荣火
from __future__ import annotations
import os
from typing import List, Optional
import pandas as pd
import numpy as np

from .base_adapter import BaseAdapter
from ..core.data_models import TargetRecord, DataSourceMeta
from ..core.geo import meters_per_deg_lat, meters_per_deg_lon


# 中文 + 英文列名映射
_ALIASES = {
    "timestamp": ["timestamp", "time", "时间", "帧时间", "起始时间(帧)", "起始时间"],
    "range_nm": ["range_nm", "range", "dist", "距离_nm", "距离",
                 "目标距离(米)", "目标距离"],
    "azimuth_deg": ["azimuth_deg", "azimuth", "azi", "方位_deg", "方位角",
                    "目标方位(°)", "目标方位", "方位(°)"],
    "snr_db": ["snr_db", "snr", "信噪比"],
    "target_id": ["目标编号", "target_id", "id", "编号"],
    "target_type": ["目标类型", "target_type", "type"],
}


def _resolve_col(df_cols: list, target: str) -> Optional[str]:
    """大小写不敏感匹配，支持别名。"""
    low = {c.lower(): c for c in df_cols}
    for alias in _ALIASES.get(target, [target]):
        if alias.lower() in low:
            return low[alias.lower()]
    return None


class RadarAdapter(BaseAdapter):
    """雷达数据适配器。"""

    SOURCE_TYPE = "radar"
    REQUIRED_COLS = ["timestamp", "range_nm", "azimuth_deg"]

    # 极坐标转换参数（默认，可从 kwargs 或 pipeline 覆盖）
    ORIGIN_LAT: float = 0.0
    ORIGIN_LON: float = 0.0

    def __init__(self, file_path: str, **kwargs) -> None:
        super().__init__(file_path, **kwargs)
        # Pipeline 通过 _origin_lat/_origin_lon 设置
        if "origin_lat" in kwargs:
            self.ORIGIN_LAT = float(kwargs["origin_lat"])
        if "origin_lon" in kwargs:
            self.ORIGIN_LON = float(kwargs["origin_lon"])
        self._origin_lat = self.ORIGIN_LAT
        self._origin_lon = self.ORIGIN_LON

    def validate(self) -> bool:
        if not os.path.exists(self.file_path):
            return False
        try:
            # 尝试读取，检查必需列
            ext = os.path.splitext(self.file_path)[-1].lower()
            if ext == ".csv":
                df = pd.read_csv(self.file_path, nrows=5)
            elif ext in (".xlsx", ".xls"):
                df = pd.read_excel(self.file_path, nrows=5)
            else:
                return False
            cols = list(df.columns)
            return (
                _resolve_col(cols, "timestamp") is not None
                and (_resolve_col(cols, "range_nm") is not None
                     or _resolve_col(cols, "range") is not None)
                and _resolve_col(cols, "azimuth_deg") is not None
            )
        except Exception:
            return False

    def load(self) -> List[TargetRecord]:
        ext = os.path.splitext(self.file_path)[-1].lower()
        if ext == ".csv":
            df = pd.read_csv(self.file_path)
        elif ext in (".xlsx", ".xls"):
            df = pd.read_excel(self.file_path)
        else:
            return []

        cols = list(df.columns)
        ts_col = _resolve_col(cols, "timestamp")
        rng_col = _resolve_col(cols, "range_nm") or _resolve_col(cols, "range")
        azi_col = _resolve_col(cols, "azimuth_deg")
        tid_col = _resolve_col(cols, "target_id")
        ttype_col = _resolve_col(cols, "target_type")

        if not all([ts_col, rng_col, azi_col]):
            return []

        records: List[TargetRecord] = []
        # 解析时间
        ts_raw = pd.to_datetime(df[ts_col], errors="coerce")
        ts_unix = ts_raw.map(
            lambda x: x.timestamp() if pd.notna(x) else np.nan
        )
        # 极坐标 → 地心地
        rng = df[rng_col].astype(float).values
        azi = np.deg2rad(df[azi_col].astype(float).values)
        x_arr = rng * np.sin(azi)       # 东向分量
        y_arr = rng * np.cos(azi)       # 北向分量
        # 简易墨卡托 → 经纬度
        olat = getattr(self, '_origin_lat', self.ORIGIN_LAT) or 0.0
        olon = getattr(self, '_origin_lon', self.ORIGIN_LON) or 0.0
        lat_arr = olat + y_arr / meters_per_deg_lat()
        lon_arr = olon + x_arr / meters_per_deg_lon(olat)

        track_id_prefix = self._build_id()[:6]

        for i, row in df.iterrows():
            # 提取目标编号（MMSI或内部ID）
            mmsi_val = None
            if tid_col is not None and pd.notna(row.get(tid_col)):
                mmsi_val = str(int(row[tid_col]))
            ttype_val = None
            if ttype_col is not None and pd.notna(row.get(ttype_col)):
                ttype_val = str(row[ttype_col])

            records.append(TargetRecord(
                source_id=self.metadata().id,
                track_id=mmsi_val or f"{track_id_prefix}_{i}",
                time=float(ts_unix.iloc[i]) if pd.notna(ts_unix.iloc[i]) else 0.0,
                x=float(x_arr[i]),
                y=float(y_arr[i]),
                lat=float(lat_arr[i]),
                lon=float(lon_arr[i]),
                speed=None,
                course=None,
                metadata={
                    "mmsi": mmsi_val,
                    "target_type": ttype_val,
                    "snr": float(row[_resolve_col(cols, "snr_db")]) if _resolve_col(cols, "snr_db") else None,
                },
            ))
        return records

    def metadata(self) -> DataSourceMeta:
        if self._meta is None:
            self._meta = DataSourceMeta(
                id=self._build_id(),
                type=self.SOURCE_TYPE,
                format=os.path.splitext(self.file_path)[-1].lstrip("."),
                file_path=self.file_path,
            )
        return self._meta
