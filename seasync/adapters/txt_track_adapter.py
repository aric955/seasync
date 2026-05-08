"""
SeaSync V2.2 TXT航迹适配器 - 支持金海豚挑战赛TXT格式

格式: T{unix_timestamp} {lon} {lat} {speed} {course}
示例: T1653714907 -15.473600 24.767384 10.2 206.5
"""

# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 荣火
from __future__ import annotations
import os
import re
from typing import List, Optional
import pandas as pd
import numpy as np

from .base_adapter import BaseAdapter
from ..core.data_models import TargetRecord, DataSourceMeta


class TXTTrackAdapter(BaseAdapter):
    """处理TXT航迹格式（金海豚挑战赛格式）。"""

    SOURCE_TYPE = "txt_track"
    REQUIRED_COLS = ["time", "lat", "lon"]

    @staticmethod
    def detect(file_path: str) -> bool:
        """检测是否为TXT航迹文件。"""
        ext = os.path.splitext(file_path)[-1].lower()
        if ext != ".txt":
            return False
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    # 检查是否符合 T{timestamp} {lon} {lat} {speed} {course} 格式
                    if re.match(r'^T\d+\s+[-\d.]+\s+[-\d.]+\s+[\d.]+\s+[\d.]+$', line):
                        return True
                    # 如果不是匹配格式就停止（只检查第一行有效数据）
                    break
            return False
        except Exception:
            return False

    def validate(self) -> bool:
        """验证TXT航迹文件是否可读。"""
        return self.detect(self.file_path)

    def load(self, max_records: Optional[int] = None) -> List[TargetRecord]:
        """加载TXT航迹文件并转为TargetRecord列表。"""
        # 从文件名提取track_id（去掉.txt）
        track_id = os.path.splitext(os.path.basename(self.file_path))[0]
        
        records: List[TargetRecord] = []
        
        with open(self.file_path, 'r', encoding='utf-8') as f:
            for line_num, line in enumerate(f):
                if max_records is not None and len(records) >= max_records:
                    break
                
                line = line.strip()
                if not line:
                    continue
                
                # 解析: T{timestamp} {lon} {lat} {speed} {course}
                parts = line.split()
                if len(parts) < 5:
                    continue
                
                try:
                    # 时间戳: T1653714907 -> 1653714907
                    time_str = parts[0]
                    if time_str.startswith('T'):
                        time_str = time_str[1:]
                    timestamp = float(time_str)
                    
                    lon = float(parts[1])
                    lat = float(parts[2])
                    speed = float(parts[3])
                    course = float(parts[4])
                    
                    # 验证坐标范围
                    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                        continue
                    
                    records.append(TargetRecord(
                        source_id=self.metadata().id,
                        track_id=track_id,
                        time=timestamp,
                        lat=lat,
                        lon=lon,
                        speed=speed,
                        course=course,
                        metadata={
                            "mmsi": track_id,
                            "format": "jht_txt",
                            "line": line_num + 1,
                        },
                    ))
                except (ValueError, IndexError):
                    continue
        
        self._records = records
        return records

    def to_dataframe(self) -> pd.DataFrame:
        """转为标准DataFrame。"""
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
                format="txt_track",
                file_path=self.file_path,
            )
        return self._meta
