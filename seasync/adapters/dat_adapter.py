"""
SeaSync V2.2 DatAdapter — 通用 DAT 数据适配器。

支持三种 DAT 解析模式（自动检测 + 可配置注入）：
1. 结构化二进制（固定记录长度） — 适用于已知字节布局的雷达/传感器DAT
2. 原始二进制流（mmap内存映射） — 适用于超大二进制文件流式处理
3. 文本DAT（扩展名为.dat的CSV/表格） — 兼容CSVAdapter同类解析

用法示例：
    adapter = DatAdapter("data.dat", config={"mode": 1, "record_length": 64})
    records = adapter.load()
"""

# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 荣火
from __future__ import annotations
import os
import struct
import mmap
import re
from typing import List, Optional, Dict, Any, Tuple

import pandas as pd
import numpy as np

from .base_adapter import BaseAdapter
from ..core.data_models import TargetRecord, DataSourceMeta
from ..core.standard_columns import REQUIRED_COLUMNS
from ..core.geo import xy_to_ll

# ── 常量 ──────────────────────────────────────────────────

_ENC_PRIORITY = ["utf-8", "utf-8-sig", "gbk", "gb2312", "gb18030", "latin-1"]
"""中文路径支持：按优先级依次尝试解码"""

_BINARY_MAGIC_SAMPLE = 256
"""二进制检测采样字节数"""

_STRUCTURED_READ_LIMIT = 1_000_000
"""结构化二进制单次加载行数上限"""

_RAW_CHUNK_SIZE = 4 * 1024 * 1024  # 4 MB
"""原始二进制流 mmap 单次分块大小"""

# 标准列别名（复用 CSVAdapter 思路，DAT 专属扩展）
_COL_ALIASES: Dict[str, List[str]] = {
    "time": ["timestamp", "time", "unix", "datetime", "时间", "帧时间"],
    "lat": ["lat", "latitude", "纬度"],
    "lon": ["lon", "lng", "longitude", "经度"],
    "x": ["x", "x_m", "x_north", "range_m"],
    "y": ["y", "y_m", "y_east", "range_km"],
    "speed": ["speed", "sog", "velocity", "航速", "速度"],
    "course": ["course", "cog", "heading", "航向", "方位角", "方位"],
    "mmsi": ["mmsi", "ship_id", "vessel_id", "目标编号"],
    "track_id": ["track_id", "target_id", "id", "编号"],
    "range": ["range", "distance", "dist", "距离", "target_range"],
    "azimuth": ["azimuth", "azi", "bearing", "azimuth_deg", "方位角"],
    "amplitude": ["amplitude", "amp", "snr", "snr_db", "强度", "幅度"],
    "target_type": ["target_type", "type", "目标类型"],
}


def _is_binary(file_path: str, sample_size: int = _BINARY_MAGIC_SAMPLE) -> bool:
    """检测文件是否为二进制格式。"""
    try:
        with open(file_path, "rb") as f:
            chunk = f.read(sample_size)
        return b"\x00" in chunk
    except Exception:
        return False


def _detect_encoding(file_path: str) -> str:
    """多编码自动检测，支持中文路径。"""
    with open(file_path, "rb") as f:
        raw = f.read(4096)
    for enc in _ENC_PRIORITY:
        try:
            raw.decode(enc)
            return enc
        except (UnicodeDecodeError, LookupError):
            continue
    return "utf-8"


def _find_col(df_cols: List[str], target: str) -> Optional[str]:
    """大小写 + 别名不敏感列名查找。"""
    aliases = _COL_ALIASES.get(target, [target])
    low = {c.strip().lower(): c for c in df_cols}
    for alias in aliases:
        if alias.lower() in low:
            return low[alias.lower()]
    return None


def _resolve_struct_format(fmt_spec: str) -> str:
    """将配置中的简短格式名转为 struct 标准格式串。

    支持的格式名：
        "f" → "f" (float, 4字节)
        "d" → "d" (double, 8字节)
        "i" → "i" (int, 4字节)
        "h" → "h" (short, 2字节)
        "H" → "H" (unsigned short)
        "I" → "I" (unsigned int)
        "b" → "b" (signed char)
        "B" → "B" (unsigned char)
    """
    # 如果是完整 struct 格式串，直接返回
    if fmt_spec in ("f", "d", "i", "h", "H", "I", "b", "B", "q", "Q"):
        return fmt_spec
    # 尝试验证是否已是合法格式（含数字前缀如 "2f"）
    try:
        test = struct.pack(fmt_spec, *(0 for _ in range(struct.calcsize(fmt_spec) // struct.calcsize(fmt_spec[-1])))) if re.match(r'^\d+[fdihHQbB]$', fmt_spec) else None
    except Exception:
        pass
    return fmt_spec


# ═══════════════════════════════════════════════════════════
# DatAdapter
# ═══════════════════════════════════════════════════════════

class DatAdapter(BaseAdapter):
    """通用 DAT 适配器，支持结构化二进制 / 原始二进制流 / 文本三种模式。

    配置注入（__init__ 的 config 参数）：
        mode (int)            : 强制指定模式 (1/2/3)，默认自动检测
        sensor_type (str)     : 传感器类型标签
        record_length (int)   : Mode1 固定记录长度（字节）
        struct_format (str)   : Mode1 struct 解析格式
        columns (Dict)        : 列映射 {标准列名: (偏移, 格式)}
        skip_bytes (int)      : Mode1 头部跳过字节
        encoding (str)        : Mode3 编码，默认自动检测
        separator (str)       : Mode3 分隔符 (csv/tsv等)，默认 ","
        origin_lat (float)    : 雷达站原点纬度
        origin_lon (float)    : 雷达站原点经度
        unit_map (Dict)       : 单位转换字典 {列名: 倍率}
    """

    SOURCE_TYPE = "dat"
    REQUIRED_COLS: List[str] = []

    # ── 构造 ─────────────────────────────────────────────

    def __init__(self, file_path: str, config: Optional[Dict[str, Any]] = None,
                 **kwargs) -> None:
        super().__init__(file_path, **kwargs)
        self._config = config or {}
        self._mode: Optional[int] = None       # 1 / 2 / 3
        self._sensor_type: Optional[str] = None
        self._records: Optional[List[TargetRecord]] = None

    # ── 核心接口 ─────────────────────────────────────────

    def validate(self) -> bool:
        """检查 DAT 文件是否可读。"""
        if not os.path.exists(self.file_path):
            return False
        if os.path.getsize(self.file_path) == 0:
            return False
        try:
            mode = self._detect_mode()
            if mode == 1:
                return self._validate_structured()
            elif mode == 2:
                return self._validate_raw()
            else:
                return self._validate_text()
        except Exception:
            return False

    def load(self) -> List[TargetRecord]:
        """解析 DAT 文件，返回 TargetRecord 列表。"""
        if self._records is not None:
            return self._records

        mode = self._detect_mode()

        if mode == 1:
            self._records = self._read_structured()
        elif mode == 2:
            self._records = self._read_raw_stream()
        else:
            self._records = self._read_text()

        # 列映射 & 单位转换
        self._apply_mapping(self._records)
        return self._records

    def get_sensor_type(self) -> str:
        """返回传感器类型字符串。"""
        if self._sensor_type:
            return self._sensor_type
        # 从配置或文件名猜测
        st = self._config.get("sensor_type", "")
        if st:
            self._sensor_type = st
            return st
        name = os.path.basename(self.file_path).lower()
        if "navy" in name or "navy_radar" in name:
            self._sensor_type = "navy_radar"
        elif "ipix" in name:
            self._sensor_type = "ipix_radar"
        elif "radar" in name:
            self._sensor_type = "radar"
        elif "sonar" in name:
            self._sensor_type = "sonar"
        else:
            self._sensor_type = "generic_dat"
        return self._sensor_type

    # ── 模式检测 ─────────────────────────────────────────

    def _detect_mode(self) -> int:
        """自动检测 DAT 解析模式。

        优先级：
        1. config 中显式指定 mode
        2. 含 null 字节且固定记录长配置 → Mode 1
        3. 含 null 字节但无结构配置    → Mode 2
        4. 文本（无 null 字节）         → Mode 3
        """
        if self._mode is not None:
            return self._mode

        # 1. config 强制模式
        forced = self._config.get("mode")
        if forced in (1, 2, 3):
            self._mode = forced
            return forced

        # 2. 二进制 vs 文本
        if _is_binary(self.file_path):
            # 有记录长度配置 → 结构化；否则原始流
            if self._config.get("record_length"):
                self._mode = 1
            else:
                self._mode = 2
        else:
            self._mode = 3

        return self._mode

    # ── Mode 1: 结构化二进制 ──────────────────────────────

    def _get_struct_layout(self) -> Tuple[int, str, Dict[str, Tuple[int, str]]]:
        """解析结构化布局配置。

        Returns:
            (record_length, struct_format, columns)
            columns: Dict[标准列名, (字节偏移, struct格式字符)]
        """
        record_length: int = self._config.get("record_length", 0)
        struct_format: str = self._config.get("struct_format", "")
        columns: Dict[str, Tuple[int, str]] = self._config.get("columns", {})

        # 从 columns 自动推导 record_length 和 struct_format
        if not record_length and columns:
            max_end = 0
            for col_name, (offset, fmt) in columns.items():
                fmt_char = _resolve_struct_format(fmt)
                size = struct.calcsize(fmt_char)
                max_end = max(max_end, offset + size)
            record_length = max_end

        if not struct_format and columns:
            # 按偏移排序拼接格式字符串
            sorted_cols = sorted(columns.items(), key=lambda x: x[1][0])
            parts = []
            prev_end = 0
            for col_name, (offset, fmt) in sorted_cols:
                fmt_char = _resolve_struct_format(fmt)
                pad = offset - prev_end
                if pad > 0:
                    parts.append(f"{pad}x")
                parts.append(fmt_char)
                prev_end = offset + struct.calcsize(fmt_char)
            # 尾部填充
            if record_length > prev_end:
                parts.append(f"{record_length - prev_end}x")
            struct_format = "<" + "".join(parts)

        return record_length, struct_format, columns

    def _validate_structured(self) -> bool:
        """验证结构化二进制DAT。"""
        record_length, struct_format, _ = self._get_struct_layout()
        if not record_length or not struct_format:
            return False
        try:
            sz = os.path.getsize(self.file_path)
            if sz < record_length:
                return False
            with open(self.file_path, "rb") as f:
                row = f.read(record_length)
            struct.unpack(struct_format, row)
            return True
        except (struct.error, OSError):
            return False

    def _read_structured(self) -> List[TargetRecord]:
        """解析结构化二进制 DAT（固定记录长度）。"""
        record_length, struct_format, columns = self._get_struct_layout()
        if not record_length or not struct_format:
            return []

        file_size = os.path.getsize(self.file_path)
        skip = self._config.get("skip_bytes", 0)
        data_start = min(skip, file_size)
        num_records = min((file_size - data_start) // record_length,
                          _STRUCTURED_READ_LIMIT)

        records: List[TargetRecord] = []
        origin_lat = self._config.get("origin_lat")
        origin_lon = self._config.get("origin_lon")
        sensor_id = self.metadata().id
        track_prefix = self._build_id()[:6]

        with open(self.file_path, "rb") as f:
            if skip > 0:
                f.seek(skip)

            for i in range(num_records):
                chunk = f.read(record_length)
                if len(chunk) < record_length:
                    break
                try:
                    vals = struct.unpack(struct_format, chunk)
                except struct.error:
                    continue

                record = self._struct_row_to_record(
                    vals, columns, i, sensor_id, track_prefix,
                    origin_lat, origin_lon,
                )
                records.append(record)

        return records

    def _struct_row_to_record(
        self,
        vals: tuple,
        columns: Dict[str, Tuple[int, str]],
        row_idx: int,
        sensor_id: str,
        track_prefix: str,
        origin_lat: Optional[float],
        origin_lon: Optional[float],
    ) -> TargetRecord:
        """将 struct 解包值转换为 TargetRecord。"""
        # 线性查询：按 columns 中的顺序取出值
        col_values: Dict[str, float] = {}
        for col_name, (offset, fmt) in columns.items():
            # 计算在 vals 中的索引
            # 复杂情况简化：按 columns 声明顺序依次取值（适配器负责顺序正确）
            pass

        # 按字节偏移排序 columns，顺序枚举即对应 struct unpack 的 tuple 索引。
        # 注意：4x / 15x 等 padding 不产生 tuple 值，所以索引直接按数据字段顺序递增。
        sorted_cols = sorted(columns.items(), key=lambda x: x[1][0])
        col_index_map: Dict[str, int] = {
            cname: ci for ci, (cname, _) in enumerate(sorted_cols)
        }

        # 提取值
        time_val = vals[col_index_map.get("time", -1)] if "time" in col_index_map else 0.0
        lat_val = vals[col_index_map.get("lat", -1)] if "lat" in col_index_map else None
        lon_val = vals[col_index_map.get("lon", -1)] if "lon" in col_index_map else None
        x_val = vals[col_index_map.get("x", -1)] if "x" in col_index_map else None
        y_val = vals[col_index_map.get("y", -1)] if "y" in col_index_map else None
        range_val = vals[col_index_map.get("range", -1)] if "range" in col_index_map else None
        azimuth_val = vals[col_index_map.get("azimuth", -1)] if "azimuth" in col_index_map else None
        speed_val = vals[col_index_map.get("speed", -1)] if "speed" in col_index_map else None
        course_val = vals[col_index_map.get("course", -1)] if "course" in col_index_map else None
        mmsi_val = vals[col_index_map.get("mmsi", -1)] if "mmsi" in col_index_map else None
        track_id_val = vals[col_index_map.get("track_id", -1)] if "track_id" in col_index_map else None

        # 极坐标 → 笛卡尔 / 经纬度
        lat = float(lat_val) if lat_val is not None else None
        lon = float(lon_val) if lon_val is not None else None
        x = float(x_val) if x_val is not None else None
        y = float(y_val) if y_val is not None else None

        if range_val is not None and azimuth_val is not None and (lat is None or lon is None):
            rng = float(range_val)
            azi = float(azimuth_val)
            azi_rad = np.deg2rad(azi)
            x = rng * np.sin(azi_rad)
            y = rng * np.cos(azi_rad)
            if origin_lat is not None and origin_lon is not None:
                lat, lon = xy_to_ll(origin_lat, origin_lon, x, y)

        # track_id
        if track_id_val is not None:
            track_id = str(int(float(track_id_val)))
        elif mmsi_val is not None:
            track_id = str(int(float(mmsi_val)))
        else:
            track_id = f"{track_prefix}_{row_idx}"

        return TargetRecord(
            source_id=sensor_id,
            track_id=track_id,
            time=float(time_val) if time_val is not None else 0.0,
            lat=lat,
            lon=lon,
            x=float(x) if x is not None else None,
            y=float(y) if y is not None else None,
            speed=float(speed_val) if speed_val is not None else None,
            course=float(course_val) if course_val is not None else None,
            metadata={
                "mmsi": str(int(float(mmsi_val))) if mmsi_val is not None else None,
                "mode": "structured_binary",
            },
        )

    # ── Mode 2: 原始二进制流（mmap）──────────────────────

    def _validate_raw(self) -> bool:
        """验证原始二进制流 DAT。"""
        try:
            sz = os.path.getsize(self.file_path)
            return sz > 0
        except OSError:
            return False

    def _read_raw_stream(self) -> List[TargetRecord]:
        """使用 mmap 读取原始二进制流。

        根据配置中的 sample_rate / bytes_per_sample 将连续字节解析为时序信号。
        返回的 TargetRecord 使用 time 作为采样时间索引，振幅作为 metadata。
        """
        file_size = os.path.getsize(self.file_path)
        if file_size == 0:
            return []

        sample_rate = self._config.get("sample_rate", 1.0)          # Hz
        bytes_per_sample = self._config.get("bytes_per_sample", 2)  # 默认 2 字节 int16
        dtype_char = self._config.get("dtype", "h")                 # h=int16, H=uint16, f=float32
        data_type = np.dtype(dtype_char).newbyteorder("<")
        expected_bytes = bytes_per_sample or np.dtype(data_type).itemsize

        sensor_id = self.metadata().id
        records: List[TargetRecord] = []

        # ── mmap 加载 ──────────────────────────────────
        try:
            with open(self.file_path, "rb") as f:
                with mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as mm:
                    total_samples = len(mm) // expected_bytes
                    if total_samples == 0:
                        return []
                    # 转换为 numpy 数组
                    arr = np.frombuffer(
                        mm[:total_samples * expected_bytes],
                        dtype=data_type,
                    ).astype(np.float64)

                    # 降采样以避免内存爆炸（最多 1M 点）
                    step = max(1, len(arr) // _STRUCTURED_READ_LIMIT)
                    sampled = arr[::step]
                    ts = np.arange(len(sampled)) / sample_rate

                    for i, (val, t) in enumerate(zip(sampled, ts)):
                        records.append(TargetRecord(
                            source_id=sensor_id,
                            track_id=f"raw_{i}",
                            time=float(t),
                            x=float(val),
                            y=None,
                            lat=None,
                            lon=None,
                            speed=None,
                            course=None,
                            metadata={
                                "amplitude": float(val),
                                "index": i,
                                "mode": "raw_binary",
                            },
                        ))
        except (OSError, ValueError, mmap.error) as e:
            raise IOError(f"mmap 读取失败: {e}") from e

        return records

    # ── Mode 3: 文本 DAT ──────────────────────────────────

    def _validate_text(self) -> bool:
        """验证文本 DAT 文件。"""
        try:
            enc = _detect_encoding(self.file_path)
            sep = self._config.get("separator", ",")
            df = pd.read_csv(self.file_path, nrows=3, encoding=enc, sep=sep)
            return len(df.columns) >= 2
        except Exception:
            return False

    def _read_text(self) -> List[TargetRecord]:
        """读取文本格式 DAT（CSV / 表格）。"""
        enc = self._config.get("encoding") or _detect_encoding(self.file_path)
        sep = self._config.get("separator", ",")

        try:
            df = pd.read_csv(self.file_path, encoding=enc, sep=sep)
        except Exception:
            # 尝试其他分隔符
            for alt_sep in (",", "\t", ";", " ", "|"):
                try:
                    df = pd.read_csv(self.file_path, encoding=enc, sep=alt_sep)
                    break
                except Exception:
                    continue
            else:
                return []

        cols = list(df.columns)
        ts_col = _find_col(cols, "time")
        lat_col = _find_col(cols, "lat")
        lon_col = _find_col(cols, "lon")
        x_col = _find_col(cols, "x")
        y_col = _find_col(cols, "y")
        speed_col = _find_col(cols, "speed")
        course_col = _find_col(cols, "course")
        mmsi_col = _find_col(cols, "mmsi")
        track_col = _find_col(cols, "track_id")
        range_col = _find_col(cols, "range")
        azi_col = _find_col(cols, "azimuth")
        amp_col = _find_col(cols, "amplitude")
        type_col = _find_col(cols, "target_type")

        origin_lat = self._config.get("origin_lat")
        origin_lon = self._config.get("origin_lon")
        sensor_id = self.metadata().id
        track_prefix = self._build_id()[:6]

        # 时间解析
        if ts_col:
            ts_raw = pd.to_datetime(df[ts_col], errors="coerce")
        else:
            ts_raw = pd.Series(dtype=float)

        has_polar = range_col and azi_col and not lat_col and not lon_col
        records: List[TargetRecord] = []

        for pos, (idx, row) in enumerate(df.iterrows()):
            lat = float(row[lat_col]) if lat_col and pd.notna(row.get(lat_col)) else None
            lon = float(row[lon_col]) if lon_col and pd.notna(row.get(lon_col)) else None

            # track_id
            mmsi_raw = str(row[mmsi_col]).strip() if mmsi_col and pd.notna(row.get(mmsi_col)) else None
            mmsi_val = mmsi_raw if mmsi_raw and mmsi_raw != "nan" else None
            if track_col:
                track_id = str(row[track_col]) if pd.notna(row.get(track_col)) else f"{track_prefix}_{pos}"
            elif mmsi_val:
                track_id = mmsi_val
            else:
                track_id = f"{track_prefix}_{pos}"

            # 极坐标处理
            x = float(row[x_col]) if x_col and pd.notna(row.get(x_col)) else None
            y = float(row[y_col]) if y_col and pd.notna(row.get(y_col)) else None
            if has_polar and (x is None or y is None):
                rng_val = float(row[range_col]) if pd.notna(row.get(range_col)) else 0.0
                azi_val = float(row[azi_col]) if pd.notna(row.get(azi_col)) else 0.0
                azi_rad = np.deg2rad(azi_val)
                x = rng_val * np.sin(azi_rad)
                y = rng_val * np.cos(azi_rad)
                if origin_lat is not None and origin_lon is not None:
                    lat, lon = xy_to_ll(origin_lat, origin_lon, x, y)

            # 时间
            try:
                ts_val = ts_raw.iloc[pos] if len(ts_raw) > pos else None
                ts = float(ts_val.timestamp()) if ts_col and pd.notna(ts_val) else float(pos)
            except (TypeError, AttributeError, ValueError, IndexError):
                ts = float(pos)

            meta: Dict[str, Any] = {"mode": "text"}
            if mmsi_val:
                meta["mmsi"] = mmsi_val
            if type_col and pd.notna(row.get(type_col)):
                meta["target_type"] = str(row[type_col]).strip()
            if amp_col and pd.notna(row.get(amp_col)):
                meta["amplitude"] = float(row[amp_col])

            records.append(TargetRecord(
                source_id=sensor_id,
                track_id=track_id,
                time=ts,
                lat=lat,
                lon=lon,
                x=float(x) if x is not None else None,
                y=float(y) if y is not None else None,
                speed=float(row[speed_col]) if speed_col and pd.notna(row.get(speed_col)) else None,
                course=float(row[course_col]) if course_col and pd.notna(row.get(course_col)) else None,
                metadata=meta,
            ))

        return records

    # ── 后处理工具 ────────────────────────────────────────

    def _apply_mapping(self, records: List[TargetRecord]) -> None:
        """应用列映射和单位转换。

        config 中的 unit_map (Dict[str, float]) 支持：
            {"range": 1852.0}    # 将 range 从海里转为米
            {"speed": 0.514444}  # 将 speed 从节转为米/秒
        """
        if not records:
            return

        unit_map: Dict[str, float] = self._config.get("unit_map", {})
        if not unit_map:
            return

        field_map: Dict[str, str] = {
            "lat": "lat", "lon": "lon",
            "speed": "speed", "course": "course",
            "x": "x", "y": "y",
            "range": "x",       # range → x (距离分量)
        }

        for rec in records:
            for col, factor in unit_map.items():
                target = field_map.get(col)
                if target is not None:
                    val = getattr(rec, target, None)
                    if val is not None:
                        setattr(rec, target, val * factor)

    # ── 元信息 ────────────────────────────────────────────

    def _get_skip_bytes(self) -> int:
        return self._config.get("skip_bytes", 0)

    def metadata(self) -> DataSourceMeta:
        if self._meta is None:
            mode = self._detect_mode()
            mode_names = {1: "structured_binary", 2: "raw_binary", 3: "text"}
            self._meta = DataSourceMeta(
                id=self._build_id(),
                type=f"dat/{self.get_sensor_type()}",
                format=f"dat_{mode_names.get(mode, 'unknown')}",
                file_path=self.file_path,
            )
        return self._meta

    # ── __repr__ ──────────────────────────────────────────

    def __repr__(self) -> str:
        mode = self._mode
        st = self.get_sensor_type()
        return (f"<DatAdapter mode={mode} sensor={st} "
                f"file={os.path.basename(self.file_path)!r}>")
