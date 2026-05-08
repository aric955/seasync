"""
SeaSync V2.2 XLSXAdapter — Excel 文件适配器。

支持：
  - .xlsx / .xls Excel 工作簿
  - 多 Sheet 自动检测
  - 中文列名兼容
  - 自动识别航迹数据 / 配置表 / 匹配关系表
"""

# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 荣火
from __future__ import annotations
import os
from typing import List, Optional, Dict
import pandas as pd
import numpy as np

from .base_adapter import BaseAdapter
from ..core.data_models import TargetRecord, DataSourceMeta


class XLSXAdapter(BaseAdapter):
    """处理 Excel (.xlsx/.xls) 格式数据。"""

    SOURCE_TYPE = "xlsx"
    REQUIRED_COLS = []

    @staticmethod
    def detect(file_path: str) -> bool:
        """检测是否为 Excel 文件。"""
        ext = os.path.splitext(file_path)[-1].lower()
        if ext not in (".xlsx", ".xls"):
            return False
        try:
            df = pd.read_excel(file_path, nrows=5)
            return True
        except Exception:
            return False

    def validate(self) -> bool:
        """验证 Excel 文件是否可读。"""
        return self.detect(self.file_path)

    def load(self, max_records: Optional[int] = None) -> List[TargetRecord]:
        """加载 Excel 文件并转为 TargetRecord 列表。"""
        try:
            all_sheets: Dict[str, pd.DataFrame] = pd.read_excel(self.file_path, sheet_name=None)
        except Exception:
            self._records = []
            return self._records
        
        records: List[TargetRecord] = []
        for sheet_name, df in all_sheets.items():
            if df.empty:
                continue
            
            cols = list(df.columns)
            col_lower = {c.lower() if isinstance(c, str) else c: c for c in cols}
            
            lat_col = self._find_col(col_lower, ["lat", "纬度", "latitude"])
            lon_col = self._find_col(col_lower, ["lon", "经度", "longitude", "lng"])
            time_col = self._find_col(col_lower, ["time", "时间", "timestamp", "日期"])
            mmsi_col = self._find_col(col_lower, ["mmsi", "船舶编号", "船号"])
            speed_col = self._find_col(col_lower, ["speed", "速度", "vel", "vel_kn"])
            course_col = self._find_col(col_lower, ["course", "航向", "cou", "heading"])
            
            if lat_col and lon_col:
                for _, row in df.iterrows():
                    if max_records is not None and len(records) >= max_records:
                        break
                    
                    lat = row[lat_col] if pd.notna(row.get(lat_col)) else None
                    lon = row[lon_col] if pd.notna(row.get(lon_col)) else None
                    
                    if lat is None or lon is None:
                        continue
                    
                    ts = 0.0
                    if time_col and pd.notna(row.get(time_col)):
                        try:
                            if isinstance(row[time_col], (int, float)):
                                ts = float(row[time_col]) / 1000.0 if row[time_col] > 1e12 else float(row[time_col])
                            else:
                                ts = pd.to_datetime(row[time_col]).timestamp()
                        except Exception:
                            ts = 0.0
                    
                    track_id = str(int(row[mmsi_col])) if mmsi_col and pd.notna(row.get(mmsi_col)) else ""
                    speed = float(row[speed_col]) if speed_col and pd.notna(row.get(speed_col)) else None
                    course = float(row[course_col]) if course_col and pd.notna(row.get(course_col)) else None
                    
                    records.append(TargetRecord(
                        source_id=self.metadata().id,
                        track_id=track_id,
                        time=ts,
                        lat=float(lat),
                        lon=float(lon),
                        speed=speed,
                        course=course,
                        metadata={"mmsi": track_id, "sheet": sheet_name},
                    ))
            else:
                for idx, row in df.iterrows():
                    if max_records is not None and len(records) >= max_records:
                        break
                    records.append(TargetRecord(
                        source_id=self.metadata().id,
                        track_id=f"{sheet_name}_row_{idx}",
                        time=0.0,
                        lat=None,
                        lon=None,
                        speed=None,
                        course=None,
                        metadata={
                            "sheet": sheet_name,
                            "row_index": idx,
                            "data": {c: str(row[c]) if pd.notna(row.get(c)) else None for c in cols},
                        },
                    ))
        
        self._records = records
        return records

    def to_dataframe(self) -> pd.DataFrame:
        """转为标准 DataFrame。"""
        records = self.load()
        if not records:
            return pd.DataFrame()
        
        rows = []
        for r in records:
            rows.append({
                "time": r.time,
                "lat": r.lat,
                "lon": r.lon,
                "x": r.x,
                "y": r.y,
                "speed": r.speed,
                "course": r.course,
                "mmsi": r.metadata.get("mmsi"),
                "track_id": r.track_id,
                "source_id": r.source_id,
            })
        return pd.DataFrame(rows)

    def metadata(self) -> DataSourceMeta:
        if self._meta is None:
            self._meta = DataSourceMeta(
                id=self._build_id(),
                type=self.SOURCE_TYPE,
                format="xlsx",
                file_path=self.file_path,
            )
        return self._meta

    @staticmethod
    def _find_col(col_map: Dict[str, str], candidates: List[str]) -> Optional[str]:
        """在列名映射中查找目标列。"""
        for candidate in candidates:
            for key, orig in col_map.items():
                if candidate in key.lower():
                    return orig
        return None
