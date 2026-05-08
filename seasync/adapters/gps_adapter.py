"""
SeaSync V2.2 GPSAdapter — GPS/NMEA 定位适配器。
支持 GPX、NMEA RMC/GGA 语句、CSV（lat/lon/time）。
"""

# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 荣火
from __future__ import annotations
import os, re, math, datetime
from typing import List, Optional
import pandas as pd
import xml.etree.ElementTree as ET

from .base_adapter import BaseAdapter
from ..core.data_models import TargetRecord, DataSourceMeta
from ..core.geo import meters_per_deg_lat, meters_per_deg_lon


def _parse_nmea_time(tstr: str, date_str: Optional[str] = None) -> float:
    """从 HHMMSS.SS NMEA 时间字符串转为 Unix 时间戳。
    可选 date_str 为 DDMMYY 格式的日期（来自 RMC 语句）。
    """
    import time
    try:
        h, m, s = int(tstr[:2]), int(tstr[2:4]), float(tstr[4:])
        if date_str and len(date_str) >= 6:
            try:
                day = int(date_str[:2])
                month = int(date_str[2:4])
                year = int(date_str[4:6]) + 2000
                dt = datetime.datetime(year, month, day, h, m, int(s))
                return dt.timestamp()
            except Exception:
                pass
        # Fallback: 使用当前日期
        now = time.time()
        st = time.localtime(now)
        base = time.mktime((st.tm_year, st.tm_mon, st.tm_mday, h, m, int(s), 0, 0, 0))
        return base
    except Exception:
        return 0.0


class GPSAdapter(BaseAdapter):
    """GPS 数据适配器。"""

    SOURCE_TYPE = "gps"
    REQUIRED_COLS = ["timestamp", "lat", "lon"]

    def validate(self) -> bool:
        if not os.path.exists(self.file_path):
            return False
        ext = os.path.splitext(self.file_path)[-1].lower()
        return ext in (".csv", ".gpx", ".nmea", ".txt")

    def load(self) -> List[TargetRecord]:
        ext = os.path.splitext(self.file_path)[-1].lower()
        if ext == ".csv":
            return self._load_csv()
        if ext == ".gpx":
            return self._load_gpx()
        return self._load_nmea()

    def _load_csv(self) -> List[TargetRecord]:
        df = pd.read_csv(self.file_path)
        cols = {c.lower(): c for c in df.columns}
        records: List[TargetRecord] = []
        ts_col = cols.get("timestamp") or cols.get("time") or cols.get("时间")
        lat_col = cols.get("lat") or cols.get("latitude")
        lon_col = cols.get("lon") or cols.get("longitude")
        sog_col = cols.get("sog") or cols.get("speed")
        cog_col = cols.get("cog") or cols.get("heading")

        if not ts_col or not lat_col or not lon_col:
            return []

        ts_raw = pd.to_datetime(df[ts_col], errors="coerce")
        for i, row in df.iterrows():
            lat = float(row[lat_col]) if pd.notna(row.get(lat_col)) else None
            lon = float(row[lon_col]) if pd.notna(row.get(lon_col)) else None
            ts = ts_raw.iloc[i].timestamp() if pd.notna(ts_raw.iloc[i]) else 0.0
            # 计算墨卡托 X/Y（相对原点）
            x = y = None
            if lat is not None and lon is not None:
                x = lat * meters_per_deg_lat()          # 简化近似
                y = lon * meters_per_deg_lon(lat)
            records.append(TargetRecord(
                source_id=self.metadata().id,
                track_id=f"gps_{self._build_id()}_{i}",
                time=ts,
                lat=lat, lon=lon, x=x, y=y,
                speed=float(row[sog_col]) if sog_col and pd.notna(row.get(sog_col, None)) else None,
                course=float(row[cog_col]) if cog_col and pd.notna(row.get(cog_col, None)) else None,
                metadata={},
            ))
        return records

    def _load_gpx(self) -> List[TargetRecord]:
        records: List[TargetRecord] = []
        tree = ET.parse(self.file_path)
        root = tree.getroot()
        ns = {"gpx": "http://www.topografix.com/GPX/1/1"}
        track_id = self._build_id()
        for i, trkpt in enumerate(root.iter("{http://www.topografix.com/GPX/1/1}trkpt")):
            lat = float(trkpt.get("lat", 0))
            lon = float(trkpt.get("lon", 0))
            time_el = trkpt.find("{http://www.topografix.com/GPX/1/1}time")
            ts = 0.0
            if time_el is not None and time_el.text:
                import datetime
                try:
                    dt = datetime.datetime.fromisoformat(time_el.text.strip("Z") + "+00:00")
                    ts = dt.timestamp()
                except Exception:
                    pass
            x = lat * meters_per_deg_lat()
            y = lon * meters_per_deg_lon(lat)
            records.append(TargetRecord(
                source_id=self.metadata().id,
                track_id=f"{track_id}_{i}",
                time=ts, lat=lat, lon=lon, x=x, y=y,
                metadata={},
            ))
        return records

    def _load_nmea(self) -> List[TargetRecord]:
        records: List[TargetRecord] = []
        track_id = self._build_id()
        with open(self.file_path, encoding="utf-8", errors="ignore") as f:
            for i, line in enumerate(f):
                line = line.strip()
                if not line.startswith("$GPRMC") and not line.startswith("$GNRMC") \
                        and not line.startswith("$GPGGA") and not line.startswith("$GNGGA"):
                    continue
                parts = line.split(",")
                if len(parts) < 12:
                    continue
                # RMC: $GPRMC,time,status,lat,N/S,lon,E/W,spd,cog,date,Mag,chk
                try:
                    lat_dir = 1 if parts[4] == "N" else -1
                    lon_dir = 1 if parts[6] == "E" else -1
                    lat = float(parts[3][:2]) + float(parts[3][2:]) / 60.0
                    lon = float(parts[5][:3]) + float(parts[5][3:]) / 60.0
                    lat *= lat_dir
                    lon *= lon_dir
                    if parts[0] in ("$GPRMC", "$GNRMC"):
                        ts = _parse_nmea_time(parts[1], parts[9])
                    else:
                        ts = _parse_nmea_time(parts[1])
                    sog = float(parts[7]) if parts[7] else None  # 节
                    cog = float(parts[8]) if parts[8] else None  # 度
                except (ValueError, IndexError):
                    continue
                x = lat * meters_per_deg_lat()
                y = lon * meters_per_deg_lon(lat)
                records.append(TargetRecord(
                    source_id=self.metadata().id,
                    track_id=f"{track_id}_{i}",
                    time=ts, lat=lat, lon=lon, x=x, y=y,
                    speed=sog, course=cog,
                    metadata={},
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
