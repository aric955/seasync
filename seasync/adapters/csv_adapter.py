"""
SeaSync V2.2 CSVAdapter — 通用 CSV 适配器。
支持任意 CSV，自动检测列名并映射到标准列。
"""

# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 荣火
from __future__ import annotations
import os, math, re
from typing import List, Dict, Optional, Tuple
import pandas as pd
import numpy as np

from .base_adapter import BaseAdapter
from ..core.data_models import TargetRecord, DataSourceMeta
from ..core.geo import xy_to_ll
from ..core.logger import log_exception

# 常用编码列表（按优先级）
_ENCODINGS = ["utf-8", "utf-8-sig", "gbk", "gb2312", "gb18030", "latin-1"]


def _detect_encoding(file_path: str) -> str:
    """自动检测 CSV 文件的编码格式。"""
    with open(file_path, "rb") as f:
        raw = f.read(4096)
    for enc in _ENCODINGS:
        try:
            raw.decode(enc)
            return enc
        except (UnicodeDecodeError, LookupError):
            continue
    return "utf-8"  # 兜底


# 列名别名映射表：标准列 → 常见变体（含中英文、带单位后缀的变体）
_COL_ALIASES: Dict[str, List[str]] = {
    "time": [
        "timestamp", "time", "unix", "time_unix", "datetime",
        "时间", "帧时间", "起始时间", "gps时间", "剧情当前时间", "剧情时间",
    ],
    "lat": [
        "lat", "latitude", "lat_deg", "纬度", "latitude_deg",
    ],
    "lon": [
        "lon", "lng", "longitude", "lon_deg", "经度", "longitude_deg",
    ],
    "x": ["x", "x_m", "x_north"],
    "y": ["y", "y_m", "y_east"],
    "speed": [
        "speed", "sog", "sog_kn", "velocity", "航速", "速度",
    ],
    "course": [
        "course", "cog", "cog_deg", "heading", "heading_deg",
        "航向", "对地航向", "船艏向", "方位角", "方位",
        "目标方位",
    ],
    "mmsi": ["mmsi", "ship_id", "vessel_id", "目标编号"],
    "track_id": ["track_id", "trackid", "target_id", "id", "目标id", "目标ID", "目标真实ID", "批号"],
    "source_id": ["source_id", "src"],
    "range": ["range", "range_m", "range_nm", "dist", "距离", "目标距离"],
    "azimuth": ["azimuth", "azi", "azimuth_deg", "bearing", "方位", "方位角", "目标方位"],
    "target_type": ["target_type", "type", "目标类型"],
    "source": ["source", "src_id", "传感器", "传感器编号"],
}

# 常见单位后缀正则，用于列名模糊匹配（同时支持ASCII和全角括号）
_UNIT_SUFFIX_RE = re.compile(r'\s*[(（][^)）]*[)）]\s*$')


def _find_col(df_cols: List[str], target: str) -> Optional[str]:
    """大小写+别名不敏感查找（3级降级匹配）。"""
    aliases = _COL_ALIASES.get(target, [target])

    # 第1级：精确匹配
    low_exact = {c.strip().lower(): c for c in df_cols}
    for alias in aliases:
        if alias.lower() in low_exact:
            return low_exact[alias.lower()]

    # 第2级：去掉单位后缀再匹配（起始时间(帧)→起始时间）
    low_strip = {_UNIT_SUFFIX_RE.sub('', c).strip().lower(): c for c in df_cols}
    for alias in aliases:
        al = _UNIT_SUFFIX_RE.sub('', alias).strip().lower()
        if al in low_strip:
            return low_strip[al]

    # 第3级：别名是列名的子串，排除含干扰词的列
    # 干扰词：含量程/范围/误差/center 等的列不应被短别名匹配
    _blocked = ["量程", "范围", "误差", "修正", "[外接", "center", "centre", "像素", "坐标"]
    for c in df_cols:
        cl = _UNIT_SUFFIX_RE.sub('', c).strip().lower()
        # 跳过含干扰词的列
        if any(b in cl for b in _blocked):
            continue
        for alias in aliases:
            al = _UNIT_SUFFIX_RE.sub('', alias).strip().lower()
            if len(al) >= 3 and al in cl:  # 最少3字符避免误匹配
                return c

    return None


def _guess_origin(df: pd.DataFrame) -> Tuple[Optional[float], Optional[float]]:
    """从数据中猜测原点（取中位数 lat/lon）。无lat/lon列时返回 (None, None)。"""
    cols = list(df.columns)
    lat_col = _find_col(cols, "lat")
    lon_col = _find_col(cols, "lon")
    if lat_col and lon_col:
        try:
            lat = pd.to_numeric(df[lat_col], errors="coerce").dropna().median()
            lon = pd.to_numeric(df[lon_col], errors="coerce").dropna().median()
        except Exception:
            return None, None
        if pd.isna(lat): lat = 0.0
        if pd.isna(lon): lon = 0.0
        return float(lat), float(lon)
    return None, None


class CSVAdapter(BaseAdapter):
    """通用 CSV 适配器，支持多种列名格式。"""

    SOURCE_TYPE = "csv"
    REQUIRED_COLS = []  # 自动检测，不强制要求

    def __init__(self, file_path: str, source_id: Optional[str] = None,
                 source_type: Optional[str] = None,
                 origin_lat: Optional[float] = None,
                 origin_lon: Optional[float] = None,
                 **kwargs) -> None:
        super().__init__(file_path, **kwargs)
        self._source_id = source_id or "csv"
        self._source_type = source_type or "csv"
        self._origin_lat = origin_lat
        self._origin_lon = origin_lon
        self._track_col: Optional[str] = None
        self._ts_col: Optional[str] = None
        self._lat_col: Optional[str] = None
        self._lon_col: Optional[str] = None

    def _log_load_limit(self, size_mb: float, max_records: int) -> None:
        """记录大文件加载限制（通过 log 模块）。"""
        try:
            from ..core.logger import log
            log.warning("大文件 %s (%.0fMB)，限制加载到 %d 条记录",
                         os.path.basename(self.file_path), size_mb, max_records)
        except ImportError:
            pass

    def validate(self) -> bool:
        if not os.path.exists(self.file_path):
            return False
        try:
            enc = _detect_encoding(self.file_path)
            df = pd.read_csv(self.file_path, nrows=3, encoding=enc)
            return len(df.columns) >= 2
        except Exception:
            return False

    def load(self, max_records: Optional[int] = None) -> List[TargetRecord]:
        """加载 CSV 文件为目标记录列表。

        Args:
            max_records: 最大记录数（None=全部，用于大文件保护）
        """
        enc = _detect_encoding(self.file_path)
        file_size = self.file_size_mb()

        # 大文件处理：自动限制记录数或启用流式处理
        if max_records is None and file_size > 50:
            max_records = 50_000
            self._log_load_limit(file_size, max_records)

        # 如果有限制或文件较大，使用流式 chunk 读取避免全量加载到内存
        use_streaming = max_records is not None or file_size > 50
        if use_streaming:
            return self._load_streaming(enc, max_records)

        # 小文件全量加载
        df = pd.read_csv(self.file_path, encoding=enc)
        return self._df_to_records(df)

    def _load_streaming(self, encoding: str, max_records: Optional[int]) -> List[TargetRecord]:
        """流式加载CSV，使用chunked读取避免内存溢出。"""
        all_records: List[TargetRecord] = []
        chunk_size = 10_000  # 每次读取1万行

        for chunk in pd.read_csv(self.file_path, encoding=encoding, chunksize=chunk_size):
            records = self._df_to_records(chunk)
            all_records.extend(records)
            if max_records is not None and len(all_records) >= max_records:
                all_records = all_records[:max_records]
                break
        return all_records

    def _df_to_records(self, df: pd.DataFrame) -> List[TargetRecord]:
        """将 DataFrame 转换为 TargetRecord 列表。"""
        cols = list(df.columns)

        # 懒加载列名解析
        if self._ts_col is None:
            self._ts_col = _find_col(cols, "time")
        if self._lat_col is None:
            self._lat_col = _find_col(cols, "lat")
        if self._lon_col is None:
            self._lon_col = _find_col(cols, "lon")
        if self._track_col is None:
            self._track_col = _find_col(cols, "track_id") or _find_col(cols, "mmsi")

        if self._origin_lat is None:
            glat, glon = _guess_origin(df)
            if glat is not None:
                self._origin_lat, self._origin_lon = glat, glon

        ts_raw = pd.to_datetime(df[self._ts_col], errors="coerce") if self._ts_col else pd.Series(dtype=float)
        records: List[TargetRecord] = []
        track_col = _find_col(cols, "track_id")
        mmsi_col = _find_col(cols, "mmsi")
        speed_col = _find_col(cols, "speed")
        course_col = _find_col(cols, "course")
        range_col = _find_col(cols, "range") or _find_col(cols, "距离")
        azi_col = _find_col(cols, "azimuth") or _find_col(cols, "方位")
        type_col = _find_col(cols, "target_type")
        src_col = _find_col(cols, "source")

        # 极坐标模式：有距离+方位角但无直接经纬度
        has_polar = range_col and azi_col and (not self._lat_col or not self._lon_col)

        for pos, (idx, row) in enumerate(df.iterrows()):
            lat = float(row[self._lat_col]) if self._lat_col and pd.notna(row.get(self._lat_col)) else None
            lon = float(row[self._lon_col]) if self._lon_col and pd.notna(row.get(self._lon_col)) else None

            # track_id 优先用 mmsi（如果有），否则用track_col，最后用行号
            mmsi_raw = str(row[mmsi_col]).strip() if mmsi_col and pd.notna(row.get(mmsi_col)) else None
            mmsi_val = mmsi_raw if mmsi_raw and mmsi_raw != "nan" else None
            if track_col and mmsi_val:
                track_id = mmsi_val
            elif track_col:
                track_id = str(row[track_col]) if pd.notna(row.get(track_col)) else f"{self._source_id}_{idx}"
            elif mmsi_col and mmsi_val:
                track_id = mmsi_val
            else:
                track_id = f"{self._source_id}_{idx}"

            # 极坐标 → 本地笛卡尔坐标（米），已知原点时转经纬度
            if has_polar and (lat is None or lon is None):
                rng_val = float(row[range_col]) if pd.notna(row.get(range_col)) else 0.0
                azi_val = float(row[azi_col]) if pd.notna(row.get(azi_col)) else 0.0
                azi_rad = math.radians(azi_val)
                x = rng_val * math.sin(azi_rad)   # 东向分量
                y = rng_val * math.cos(azi_rad)   # 北向分量
                # 若已知雷达站长原点，转绝对经纬度
                if self._origin_lat is not None and self._origin_lon is not None:
                    lat, lon = xy_to_ll(self._origin_lat, self._origin_lon, x, y)
            else:
                x = float(row["x"]) if "x" in cols and pd.notna(row.get("x")) else None
                y = float(row["y"]) if "y" in cols and pd.notna(row.get("y")) else None

            # 时间解析（用位置索引pos，避免NaN行索引）
            try:
                ts_val = ts_raw.iloc[pos]
                ts = float(ts_val.timestamp()) if self._ts_col and pd.notna(ts_val) else 0.0
            except (TypeError, AttributeError, ValueError, IndexError):
                ts = 0.0

            # 构建metadata
            meta: dict = {}
            if mmsi_val:
                meta["mmsi"] = mmsi_val
            if type_col and pd.notna(row.get(type_col)):
                meta["target_type"] = str(row[type_col]).strip()
            if src_col and pd.notna(row.get(src_col)):
                meta["source_id"] = str(int(row[src_col])) if isinstance(row[src_col], (int, float)) and not pd.isna(row[src_col]) else str(row[src_col]).strip()

            records.append(TargetRecord(
                source_id=self.metadata().id,
                track_id=track_id,
                time=ts,
                lat=lat, lon=lon,
                x=x, y=y,
                speed=float(row[speed_col]) if speed_col and pd.notna(row.get(speed_col)) else None,
                course=float(row[course_col]) if course_col and pd.notna(row.get(course_col)) else None,
                metadata=meta,
            ))
        return records

    def metadata(self) -> DataSourceMeta:
        if self._meta is None:
            self._meta = DataSourceMeta(
                id=self._source_id,
                type=self._source_type,
                format="csv",
                file_path=self.file_path,
            )
        return self._meta
