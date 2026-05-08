"""
SeaSync V2.2 CAT048RadarAdapter — 通用CAT-048二进制雷达适配器。
支持格式：
- CAT=048 (0x30) 雷达点迹数据（金海豚竞赛格式）
- 大端字节序
- 单报文支持多点迹打包

兼容的数据集：
- 海军第二届"金海豚"杯算法挑战赛 — 科目一海上目标点迹数据
- 其他 CAT=048 格式雷达点迹数据
"""

# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 荣火
from __future__ import annotations
from typing import List, Optional, Tuple
import struct
import math
import os

import numpy as np

from .base_adapter import BaseAdapter
from ..core.data_models import TargetRecord, DataSourceMeta

# CAT048 常量
CAT048_MAGIC = 0x30           # CAT=048 标识字节
HEADER_SIZE = 15               # CAT048公共头部长度
PLOT_RECORD_SIZE = 11          # 金海豚点迹记录长度（与标准23B不同）


class CAT048RadarAdapter(BaseAdapter):
    """CAT-048 二进制雷达数据适配器（金海豚兼容版）。

    格式说明：
    - 每帧 = CAT048头部(15B) + N×点迹记录(11B/条)
    - 15B短报文(info_type=0x00)为时间同步帧，不含点迹
    - 点迹记录(11B): range(2) + azimuth(2) + flags(3) + seq(2) + reserved(2)

    关键参数（可通过 config/kwargs 传入）：
    - data_mode: "plot" | "track" | "auto" (默认auto)
    - use_xy: True (默认) 用笛卡尔坐标；False 用极坐标
    - coord_unit: 坐标单位转换（默认1852, 海里→米）
    """

    SOURCE_TYPE = "radar"
    REQUIRED_COLS = ["CAT=048"]

    def __init__(self, file_path: str, config: Optional[dict] = None,
                 **kwargs) -> None:
        super().__init__(file_path, config=config, **kwargs)
        self._data_mode = (config or {}).get("data_mode",
                           kwargs.get("data_mode", "auto"))
        self._use_xy = (config or {}).get("use_xy",
                        kwargs.get("use_xy", True))
        self._coord_unit = (config or {}).get("coord_unit",
                            kwargs.get("coord_unit", 1852.0))

    def validate(self) -> bool:
        """检查是否为有效的CAT-048格式。"""
        if not os.path.exists(self.file_path):
            return False
        try:
            size = os.path.getsize(self.file_path)
            if size < 15:
                return False
            with open(self.file_path, "rb") as f:
                header = f.read(3)
            if len(header) < 3:
                return False
            # CAT=048 标识 + 长度至少15
            if header[0] != CAT048_MAGIC:
                return False
            length = struct.unpack('>H', header[1:3])[0]
            return length >= 15
        except Exception:
            return False

    def load(self) -> List[TargetRecord]:
        """解析CAT-048文件，返回目标记录列表。"""
        with open(self.file_path, "rb") as f:
            data = f.read()

        records: List[TargetRecord] = []
        pos = 0
        seq_counter = 0

        while pos + HEADER_SIZE <= len(data):
            # 查找CAT048帧同步
            if data[pos] != CAT048_MAGIC:
                pos += 1
                continue

            length = struct.unpack('>H', data[pos+1:pos+3])[0]
            if length < HEADER_SIZE or pos + length > len(data):
                pos += 1
                continue

            # 解析公共头部
            time_raw = (data[pos+9] << 16) | (data[pos+10] << 8) | data[pos+11]
            time_sec = time_raw / 128.0  # 1/128秒精度
            info_type = data[pos+12]

            # info_type=0x00 是时间同步帧，不含点迹
            if info_type == 0x00:
                pos += length
                continue

            # info_type=0x20 是雷达点迹帧
            if info_type == 0x20:
                plot_data_len = length - HEADER_SIZE
                n_plots = plot_data_len // PLOT_RECORD_SIZE
                off = pos + HEADER_SIZE

                for i in range(n_plots):
                    plot_start = off + i * PLOT_RECORD_SIZE
                    if plot_start + PLOT_RECORD_SIZE > pos + length:
                        break

                    plot = data[plot_start:plot_start + PLOT_RECORD_SIZE]

                    # 点迹字段解析
                    rng_raw = struct.unpack('>H', plot[0:2])[0]
                    azi_raw = struct.unpack('>H', plot[2:4])[0]
                    amp = plot[6]  # 振幅
                    seq = struct.unpack('>H', plot[7:9])[0]

                    # 极坐标→笛卡尔
                    rng_nm = rng_raw / 256.0
                    azi_deg = azi_raw / 65536.0 * 360.0
                    az_rad = math.radians(azi_deg)
                    x_nm = rng_nm * math.sin(az_rad)
                    y_nm = rng_nm * math.cos(az_rad)

                    seq_counter += 1
                    records.append(TargetRecord(
                        source_id=self.metadata().id,
                        track_id=f"plot_{seq}",
                        time=time_sec,
                        x=x_nm * self._coord_unit,
                        y=y_nm * self._coord_unit,
                        metadata={
                            'seq': int(seq),
                            'range_nm': round(rng_nm, 2),
                            'azimuth_deg': round(azi_deg, 4),
                            'amplitude': int(amp),
                            'info_type': info_type,
                            'frame_seq': seq_counter,
                        }
                    ))

            # 其他 info_type 预留（金海豚格式暂未使用航迹帧）
            pos += length

        return records

    def _detect_mode(self, data: bytes) -> str:
        """自动检测数据是点迹(plot)还是航迹(track)。"""
        if self._data_mode != "auto":
            return self._data_mode
        # 金海豚格式全部为点迹(0x20)
        plot_count = 0
        pos = 0
        samples = min(500, len(data))
        while pos + HEADER_SIZE <= samples:
            if data[pos] != CAT048_MAGIC:
                pos += 1
                continue
            length = struct.unpack('>H', data[pos+1:pos+3])[0]
            if length < HEADER_SIZE or pos + length > len(data):
                break
            if data[pos+12] == 0x20:
                plot_count += 1
            pos += length
        return "plot" if plot_count > 0 else "track"

    def to_dataframe(self) -> 'pd.DataFrame':
        import pandas as pd
        recs = self.load()
        rows = []
        for r in recs:
            rows.append({
                'time': r.time, 'x': r.x, 'y': r.y,
                'track_id': r.track_id, 'source_id': r.source_id,
                'lat': r.lat, 'lon': r.lon,
                'speed': r.speed, 'course': r.course,
                'range_nm': r.metadata.get('range_nm'),
                'azimuth_deg': r.metadata.get('azimuth_deg'),
            })
        return pd.DataFrame(rows)

    def __repr__(self) -> str:
        return (f"<CAT048RadarAdapter file={os.path.basename(self.file_path)!r}"
                f" mode={self._data_mode}>")


def _is_cat048(file_path: str) -> bool:
    """快速判断文件是否为CAT-048格式（给SmartFormatDetector用）。"""
    try:
        with open(file_path, 'rb') as f:
            header = f.read(3)
        if len(header) < 3:
            return False
        if header[0] != CAT048_MAGIC:
            return False
        length = struct.unpack('>H', header[1:3])[0]
        return 15 <= length <= 500
    except Exception:
        return False
