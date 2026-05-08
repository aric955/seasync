"""
SeaSync V2.2 AISAdapter — AIS 消息适配器。
支持：
  - AIS NMEA 原始语句（!AIVDM/!AIVDO）
  - AIS CSV（mmsi, lat, lon, sog, cog, timestamp）
"""

# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 荣火
from __future__ import annotations
import os, re
from typing import List, Optional, Tuple
import pandas as pd
import numpy as np

from .base_adapter import BaseAdapter
from ..core.data_models import TargetRecord, DataSourceMeta


# AIS 6bit 解码（ITU-R M.1371 Table 48，覆盖全部 64 个字符）
def _ais6bit(ch: str) -> int:
    """AIS 6-bit 字符转整数（@.._ + space..? 共 64 字符）。"""
    c = ord(ch)
    if 0x40 <= c <= 0x5F:          # @ (0) .. _ (31)
        return c - 0x40
    if 0x20 <= c <= 0x3F:          # space (32) .. ? (63)
        return c - 0x20 + 32
    return 0


def _decode_ais_payload(bits: str) -> dict:
    """解码 AIS 填充 bit 串，返回解析字典（精简版）。"""
    def get_bits(start: int, length: int) -> int:
        s = bits[start:start + length]
        s = s.ljust(length, "0")
        val = 0
        for b in s:
            val = (val << 1) | (1 if b == "1" else 0)
        return val

    msg_type = get_bits(0, 6)
    if msg_type not in (1, 2, 3, 5, 18):
        return {}

    result = {"mmsi": get_bits(8, 30)}
    if msg_type in (1, 2, 3):
        lat_i = get_bits(89, 28)
        lon_i = get_bits(61, 27)
        result["lat"] = lat_i / 600000.0 if lat_i < 0x4000000 else 0.0
        result["lon"] = lon_i / 600000.0 if lon_i < 0x4000000 else 0.0
        sog_i = get_bits(50, 10)
        result["sog"] = sog_i / 10.0 if sog_i < 1022 else None
        cog_i = get_bits(116, 12)
        result["cog"] = cog_i / 10.0 if cog_i < 3600 else None
        result["nav_status"] = get_bits(38, 4)
    return result


class AISAdapter(BaseAdapter):
    """AIS 数据适配器。"""

    SOURCE_TYPE = "ais"
    REQUIRED_COLS = ["mmsi", "timestamp"]

    def __init__(self, file_path: str, **kwargs) -> None:
        super().__init__(file_path, **kwargs)
        # NMEA 分片缓存（实例级，避免多实例共享）
        self._fragments: dict = {}

    def validate(self) -> bool:
        if not os.path.exists(self.file_path):
            return False
        try:
            from .csv_adapter import _detect_encoding
            enc = _detect_encoding(self.file_path)
            with open(self.file_path, encoding=enc, errors="ignore") as f:
                first = f.read(200)
            ext = os.path.splitext(self.file_path)[-1].lower()
            if ext == ".nmea" or "!AIVDM" in first or "!AIVDO" in first:
                return True
            if ext == ".csv":
                df = pd.read_csv(self.file_path, nrows=3, encoding=enc)
                cols = list(df.columns)
                return "mmsi" in [c.lower() for c in cols]
            return False
        except Exception:
            return False

    def load(self) -> List[TargetRecord]:
        ext = os.path.splitext(self.file_path)[-1].lower()
        if ext == ".csv":
            return self._load_csv()
        else:
            return self._load_nmea()

    def _load_csv(self) -> List[TargetRecord]:
        from .csv_adapter import _find_col, _detect_encoding
        enc = _detect_encoding(self.file_path)
        df = pd.read_csv(self.file_path, encoding=enc)
        cols_list = list(df.columns)
        records: List[TargetRecord] = []
        ts_col = _find_col(cols_list, "time")
        mmsi_col = _find_col(cols_list, "mmsi")
        lat_col = _find_col(cols_list, "lat")
        lon_col = _find_col(cols_list, "lon")
        sog_col = _find_col(cols_list, "speed")
        cog_col = _find_col(cols_list, "course")

        ts_raw = pd.to_datetime(df[ts_col], errors="coerce") if ts_col else pd.Series(dtype=float)

        for i, row in df.iterrows():
            mmsi = str(int(row[mmsi_col])) if mmsi_col and pd.notna(row[mmsi_col]) else ""
            lat = float(row[lat_col]) if lat_col and pd.notna(row.get(lat_col, None)) else None
            lon = float(row[lon_col]) if lon_col and pd.notna(row.get(lon_col, None)) else None
            ts = ts_raw.iloc[i].timestamp() if pd.notna(ts_raw.iloc[i]) else 0.0
            records.append(TargetRecord(
                source_id=self.metadata().id,
                track_id=mmsi,
                time=ts,
                lat=lat, lon=lon,
                speed=float(row[sog_col]) if sog_col and pd.notna(row.get(sog_col, None)) else None,
                course=float(row[cog_col]) if cog_col and pd.notna(row.get(cog_col, None)) else None,
                metadata={"mmsi": mmsi},
            ))
        return records

    def _load_nmea(self) -> List[TargetRecord]:
        records: List[TargetRecord] = []
        with open(self.file_path, encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if not line.startswith("!AIVDM") and not line.startswith("!AIVDO"):
                    continue
                parts = line.split(",")
                if len(parts) < 6:
                    continue
                try:
                    total_fragments = int(parts[1])
                    fragment_num = int(parts[2])
                    seq_id = parts[3]
                    channel = parts[4]
                    payload = parts[5]
                    # 解析时间戳（字段 6）
                    ts_str = parts[6] if len(parts) > 6 else ""
                    ts = 0.0
                    if ts_str:
                        try:
                            ts = float(ts_str)
                        except ValueError:
                            pass
                except (ValueError, IndexError):
                    continue

                # 组合分片
                key = f"{channel}:{seq_id}"
                if total_fragments == 1:
                    frag_payload = payload
                else:
                    if fragment_num == 1:
                        self._fragments[key] = payload
                    elif fragment_num > 1:
                        self._fragments[key] = (self._fragments.get(key, "") + payload)
                    if fragment_num < total_fragments:
                        continue
                    frag_payload = self._fragments.pop(key, "")

                # 6bit → bit 串
                bits = "".join(
                    bin(_ais6bit(ch))[2:].rjust(6, "0")
                    for ch in frag_payload if ch not in ("@", " ", "\r", "\n")
                )
                decoded = _decode_ais_payload(bits)
                if not decoded:
                    continue
                mmsi = str(decoded.get("mmsi", ""))
                records.append(TargetRecord(
                    source_id=self.metadata().id,
                    track_id=mmsi,
                    time=ts,
                    lat=decoded.get("lat"),
                    lon=decoded.get("lon"),
                    speed=decoded.get("sog"),
                    course=decoded.get("cog"),
                    metadata={"mmsi": mmsi, "nav_status": decoded.get("nav_status")},
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
