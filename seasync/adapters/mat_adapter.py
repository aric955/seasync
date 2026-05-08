"""
SeaSync V2.2 MatAdapter — MATLAB .mat 文件适配器。

支持格式：
  - v5/v7（传统格式）：使用 scipy.io.loadmat
  - v7.3（HDF5 格式）：使用 h5py

功能：
  - 智能格式自动检测
  - 变量名别名映射（中英文）
  - MATLAB datenum → Unix 毫秒时间戳自动转换
  - 配置注入支持
  - 中文路径支持
"""

# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 荣火
from __future__ import annotations
import os
import math
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any, Tuple

import numpy as np

from .base_adapter import BaseAdapter
from ..core.data_models import TargetRecord, DataSourceMeta
from ..core.geo import xy_to_ll

# ── 可选依赖检查 ──────────────────────────────────────────

_HAS_SCIPY = False
try:
    import scipy.io
    _HAS_SCIPY = True
except ImportError:
    pass

_HAS_H5PY = False
try:
    import h5py
    _HAS_H5PY = True
except ImportError:
    pass

# ── 常量 ─────────────────────────────────────────────────

# MATLAB datenum 相对于 Unix epoch 的偏移量
# MATLAB datenum('1970-01-01 00:00:00') == 719529
# datenum 单位为天，因此转换公式：
#   unix_seconds = (datenum - 719529) * 86400
_MATLAB_DATENUM_EPOCH_OFFSET = 719529
_SECONDS_PER_DAY = 86400.0

# 常见变量名别名映射表
_VARIABLE_ALIASES: Dict[str, List[str]] = {
    "timestamp": [
        "timestamp", "time", "t", "时间", "gps时间", "帧时间",
        "unix_time", "datetime", "date",
    ],
    "lat": [
        "lat", "latitude", "纬度",
    ],
    "lon": [
        "lon", "lng", "longitude", "经度",
    ],
    "range": [
        "range", "distance", "dist", "距离", "目标距离",
    ],
    "azimuth": [
        "azimuth", "azi", "azimuth_deg", "bearing", "方位", "方位角",
    ],
    "x": [
        "x", "x_m", "x_north",
    ],
    "y": [
        "y", "y_m", "y_east",
    ],
    "speed": [
        "speed", "sog", "velocity", "航速", "速度",
    ],
    "course": [
        "course", "cog", "heading", "航向",
    ],
    "track_id": [
        "track_id", "trackid", "target_id", "id", "目标编号",
    ],
    "mmsi": [
        "mmsi", "ship_id", "vessel_id",
    ],
    "source_id": [
        "source_id", "src", "sensor_id",
    ],
    "snr": [
        "snr", "snr_db", "信噪比",
    ],
    "target_type": [
        "target_type", "type", "目标类型",
    ],
}


def _find_variable(var_names: List[str], target: str) -> Optional[str]:
    """在变量名列表中查找目标别名，大小写不敏感。"""
    aliases = _VARIABLE_ALIASES.get(target, [target])
    lower_names = {v.lower(): v for v in var_names}
    for alias in aliases:
        if alias.lower() in lower_names:
            return lower_names[alias.lower()]
    return None


def _is_matlab_datenum(arr: np.ndarray) -> bool:
    """启发式判断是否为 MATLAB datenum 格式。

    MATLAB datenum 特征：
      - 值域通常在 7e5 ~ 8e5 范围（对应 1900~2100 年）
      - 小数部分代表一天内的时间
    """
    if arr.ndim == 0:
        arr = arr.flatten()
    if arr.size == 0:
        return False
    try:
        flat = arr.astype(np.float64).flatten()
        # 过滤 NaN/Inf
        flat = flat[np.isfinite(flat)]
        if flat.size == 0:
            return False
        # datenum 典型范围：600000 ~ 800000
        mean_val = float(np.mean(flat))
        return 600000.0 < mean_val < 800000.0
    except (ValueError, TypeError):
        return False


def _datenum_to_unix_ms(datenum_arr: np.ndarray) -> np.ndarray:
    """将 MATLAB datenum 数组转换为 Unix 毫秒时间戳。

    MATLAB datenum 以天为单位，起点为 0000-01-00（matlab 儒略日）。
    """
    seconds = (datenum_arr.astype(np.float64) - _MATLAB_DATENUM_EPOCH_OFFSET) * _SECONDS_PER_DAY
    return (seconds * 1000).astype(np.int64)


def _squeeze_value(val) -> Any:
    """将 numpy 数组/标量提取为 Python 原生类型。"""
    if isinstance(val, np.ndarray):
        if val.ndim == 0 or val.size == 1:
            return val.item()
        return val.squeeze().tolist()
    return val


def _is_hdf5_mat(file_path: str) -> bool:
    """通过读取文件前 4 字节判断是否为 HDF5（v7.3）格式。"""
    try:
        # HDF5 签名为 \x89HDF\r\n\x1a\n
        with open(file_path, "rb") as f:
            sig = f.read(4)
        return sig == b"\x89HDF"
    except OSError:
        return False


# ═══════════════════════════════════════════════════════════
#  MatAdapter
# ═══════════════════════════════════════════════════════════

class MatAdapter(BaseAdapter):
    """MATLAB .mat 文件适配器。

    格式检测：
      - v7.3: 检测 HDF5 签名
      - v5/v7: scipy.io.loadmat

    变量映射：
      - auto_map_variables() 自动尝试将 .mat 变量名映射到标准列
      - 支持 config 中的 field_mapping 覆盖自动映射
    """

    SOURCE_TYPE = "matlab"
    REQUIRED_COLS: List[str] = []

    def __init__(self, file_path: str, config: Optional[Dict[str, Any]] = None,
                 **kwargs) -> None:
        """初始化适配器。

        Args:
            file_path: .mat 文件路径（支持中文路径）
            config: 配置字典，支持键：
                - field_mapping: Dict[str, str]，手动变量名→标准列映射
                - origin_lat: float，雷达站纬度
                - origin_lon: float，雷达站经度
                - use_datenum_conversion: bool，默认 True
            **kwargs: 传递给 BaseAdapter 的额外参数
        """
        super().__init__(file_path, **kwargs)
        self._config = config or {}
        self._field_mapping: Dict[str, str] = self._config.get("field_mapping", {})
        self._origin_lat: Optional[float] = self._config.get("origin_lat", kwargs.get("origin_lat"))
        self._origin_lon: Optional[float] = self._config.get("origin_lon", kwargs.get("origin_lon"))
        self._use_datenum_conversion: bool = self._config.get("use_datenum_conversion", True)

        # 缓存
        self._loaded: bool = False
        self._records: List[TargetRecord] = []
        self._mat_data: Optional[Dict[str, Any]] = None
        self._var_names: List[str] = []
        self._detected_format: str = ""

    # ── 格式检测 ──────────────────────────────────────────

    def _detect_format(self) -> str:
        """智能检测 .mat 文件格式。

        Returns:
            "mat_v5" | "mat_v73" | "mat_unknown"
        """
        if not os.path.exists(self.file_path):
            return "mat_unknown"
        try:
            if _is_hdf5_mat(self.file_path):
                return "mat_v73"
            if _HAS_SCIPY:
                # 尝试用 scipy.io 读取（能打开即为 v5/v7）
                import scipy.io
                scipy.io.whosmat(self.file_path)
                return "mat_v5"
            # 无 scipy 时根据扩展名推断
            return "mat_v5"
        except Exception:
            return "mat_unknown"

    # ── 验证 ──────────────────────────────────────────────

    def validate(self) -> bool:
        if not os.path.exists(self.file_path):
            return False
        fmt = self._detect_format()
        if fmt == "mat_unknown":
            return False
        if fmt == "mat_v73" and not _HAS_H5PY:
            return False
        if fmt == "mat_v5" and not _HAS_SCIPY:
            return False
        return True

    # ── 加载数据 ──────────────────────────────────────────

    def _load_mat_v5(self) -> Dict[str, Any]:
        """使用 scipy.io.loadmat 加载 v5/v7 .mat 文件。"""
        if not _HAS_SCIPY:
            raise ImportError(
                "scipy 未安装。无法读取 v5/v7 .mat 文件。\n"
                "请运行: pip install scipy"
            )
        import scipy.io
        return scipy.io.loadmat(
            self.file_path,
            chars_as_strings=True,
            squeeze_me=False,
        )

    def _load_mat_v73(self) -> Dict[str, Any]:
        """使用 h5py 加载 v7.3 (HDF5) .mat 文件。"""
        if not _HAS_H5PY:
            raise ImportError(
                "h5py 未安装。无法读取 v7.3 .mat 文件。\n"
                "请运行: pip install h5py"
            )
        import h5py
        data: Dict[str, Any] = {}
        with h5py.File(self.file_path, "r") as f:
            def _visit(name, obj):
                if isinstance(obj, h5py.Dataset):
                    # HDF5 引用转 numpy
                    arr = obj[()]
                    # h5py 默认使用行主序，MATLAB 使用列主序
                    # 对 2D 以上数组转置以恢复 MATLAB 视角
                    if isinstance(arr, bytes):
                        data[name] = arr.decode("utf-8", errors="replace")
                    elif isinstance(arr, np.ndarray) and arr.ndim >= 2:
                        data[name] = arr.T
                    elif isinstance(arr, np.ndarray):
                        data[name] = arr
                    elif isinstance(arr, (list, tuple)):
                        data[name] = np.array(arr)
                    else:
                        data[name] = np.array([arr])
            f.visititems(_visit)
        return data

    def _load_mat(self) -> Dict[str, Any]:
        """根据格式自动选择加载方法。"""
        self._detected_format = self._detect_format()
        if self._detected_format == "mat_v73":
            if not _HAS_H5PY:
                raise ImportError(
                    "检测到 v7.3 (HDF5) 格式但 h5py 未安装。\n"
                    "请运行: pip install h5py\n"
                    "或用 MATLAB 另存为 v7 格式。"
                )
            raw = self._load_mat_v73()
        elif self._detected_format in ("mat_v5", "mat_unknown"):
            raw = self._load_mat_v5()
        else:
            raise ValueError(f"不支持的文件格式: {self._detected_format}")
        # 过滤掉 MATLAB 内部元数据变量
        excluded = {"__header__", "__version__", "__globals__", "#refs#"}
        data = {k: v for k, v in raw.items()
                if not k.startswith("__") and k not in excluded}
        self._var_names = list(data.keys())
        return data

    # ── 自动变量映射 ──────────────────────────────────────

    def auto_map_variables(self) -> Dict[str, str]:
        """自动识别 .mat 变量名到标准列名的映射。

        返回格式：{标准列名: mat变量名}
        """
        if not self._var_names:
            # 懒加载：先读取变量名而不加载全量数据
            try:
                self._mat_data = self._load_mat()
                self._var_names = list(self._mat_data.keys())
            except Exception:
                return {}
        if not self._var_names:
            return {}
        mapping: Dict[str, str] = {}
        # 标准列名按优先级排序
        standard_keys = [
            "timestamp", "lat", "lon", "range", "azimuth",
            "x", "y", "speed", "course", "track_id", "mmsi",
            "source_id", "snr", "target_type",
        ]
        for key in standard_keys:
            matched = _find_variable(self._var_names, key)
            if matched:
                mapping[key] = matched
        return mapping

    # ── 核心加载接口 ──────────────────────────────────────

    def load(self) -> List[TargetRecord]:
        """解析 .mat 文件，返回目标记录列表。

        处理流程：
          1. 加载原始数据
          2. 自动识别变量映射（或使用手动配置）
          3. 处理 datenum → Unix 时间戳转换
          4. 极坐标（range+azimuth）→ 笛卡尔坐标转换
          5. 构建 TargetRecord 列表
        """
        if self._loaded:
            return self._records

        self._mat_data = self._load_mat()
        var_names = list(self._mat_data.keys())

        # 获取变量映射：手动映射 > 自动映射
        mapping = self._field_mapping.copy()
        if not mapping:
            mapping = self.auto_map_variables()
        else:
            # 手动映射的补充自动识别
            auto_map = self.auto_map_variables()
            for k, v in auto_map.items():
                if k not in mapping:
                    mapping[k] = v

        # 获取各列数据
        ts_raw = self._get_mapped_array(mapping, "timestamp")
        lat_raw = self._get_mapped_array(mapping, "lat")
        lon_raw = self._get_mapped_array(mapping, "lon")
        x_raw = self._get_mapped_array(mapping, "x")
        y_raw = self._get_mapped_array(mapping, "y")
        range_raw = self._get_mapped_array(mapping, "range")
        azi_raw = self._get_mapped_array(mapping, "azimuth")
        speed_raw = self._get_mapped_array(mapping, "speed")
        course_raw = self._get_mapped_array(mapping, "course")
        track_raw = self._get_mapped_array(mapping, "track_id")
        mmsi_raw = self._get_mapped_array(mapping, "mmsi")
        snr_raw = self._get_mapped_array(mapping, "snr")
        type_raw = self._get_mapped_array(mapping, "target_type")

        # 统一到一维数组
        ts_arr = self._to_flat_float(ts_raw)
        lat_arr = self._to_flat_float(lat_raw)
        lon_arr = self._to_flat_float(lon_raw)
        x_arr = self._to_flat_float(x_raw)
        y_arr = self._to_flat_float(y_raw)
        range_arr = self._to_flat_float(range_raw)
        azi_arr = self._to_flat_float(azi_raw)

        # 自动检测并转换 MATLAB datenum
        if self._use_datenum_conversion and ts_arr is not None and ts_arr.size > 0:
            if _is_matlab_datenum(ts_arr):
                ts_arr = _datenum_to_unix_ms(ts_arr)

        # 确定记录数量
        valid_arrs = [a for a in [ts_arr, lat_arr, lon_arr, range_arr, azi_arr]
                      if a is not None]
        n_records = max((a.size for a in valid_arrs), default=0) if valid_arrs else 0

        records: List[TargetRecord] = []
        src_id = self.metadata().id
        track_prefix = self._build_id()[:6]

        # 极坐标模式判断：有range+azimuth但无直接经纬度
        has_polar = range_arr is not None and azi_arr is not None and lat_arr is None

        for i in range(n_records):
            ts = float(ts_arr[i]) if ts_arr is not None and i < ts_arr.size else 0.0
            lat = float(lat_arr[i]) if lat_arr is not None and i < lat_arr.size else None
            lon_val = float(lon_arr[i]) if lon_arr is not None and i < lon_arr.size else None

            # 极坐标转换
            x, y = None, None
            if has_polar:
                rng_v = float(range_arr[i]) if i < range_arr.size else 0.0
                azi_v = float(azi_arr[i]) if i < azi_arr.size else 0.0
                azi_rad = math.radians(azi_v)
                x = rng_v * math.sin(azi_rad)
                y = rng_v * math.cos(azi_rad)
                if self._origin_lat is not None and self._origin_lon is not None:
                    lat, lon_val = xy_to_ll(self._origin_lat, self._origin_lon, x, y)
            else:
                x = float(x_arr[i]) if x_arr is not None and i < x_arr.size else None
                y = float(y_arr[i]) if y_arr is not None and i < y_arr.size else None

            # track_id 处理
            track_id: str = ""
            if mmsi_raw is not None:
                try:
                    mmsi_arr = np.asarray(mmsi_raw).flatten()
                    raw_val = mmsi_arr[i] if i < mmsi_arr.size else None
                    if raw_val is not None and not (isinstance(raw_val, float) and math.isnan(raw_val)):
                        track_id = str(int(raw_val)) if isinstance(raw_val, (int, float, np.integer, np.floating)) else str(raw_val)
                except (ValueError, TypeError, IndexError):
                    pass
            if not track_id and track_raw is not None:
                try:
                    tid_arr = np.asarray(track_raw).flatten()
                    raw_val = tid_arr[i] if i < tid_arr.size else None
                    if raw_val is not None and not (isinstance(raw_val, float) and math.isnan(raw_val)):
                        track_id = str(int(raw_val)) if isinstance(raw_val, (int, float, np.integer, np.floating)) else str(raw_val)
                except (ValueError, TypeError, IndexError):
                    pass
            if not track_id:
                track_id = f"{track_prefix}_{i}"

            # metadata
            meta: Dict[str, Any] = {}
            if snr_raw is not None:
                try:
                    snr_arr = np.asarray(snr_raw).flatten()
                    snr_v = snr_arr[i] if i < snr_arr.size else None
                    if snr_v is not None and not (isinstance(snr_v, float) and math.isnan(snr_v)):
                        meta["snr"] = float(snr_v)
                except (IndexError, ValueError, TypeError):
                    pass
            if type_raw is not None:
                try:
                    type_arr = np.asarray(type_raw).flatten()
                    tv = type_arr[i] if i < type_arr.size else None
                    if tv is not None:
                        meta["target_type"] = str(tv)
                except (IndexError, ValueError, TypeError):
                    pass

            records.append(TargetRecord(
                source_id=src_id,
                track_id=track_id,
                time=ts,
                lat=lat,
                lon=lon_val,
                x=x,
                y=y,
                speed=float(speed_arr[i]) if (speed_raw is not None
                        and i < (speed_arr := np.asarray(speed_raw).flatten()).size) else None,
                course=float(course_arr[i]) if (course_raw is not None
                        and i < (course_arr := np.asarray(course_raw).flatten()).size) else None,
                metadata=meta,
            ))

        self._records = records
        self._loaded = True
        return records

    def _get_mapped_array(self, mapping: Dict[str, str], key: str) -> Optional[np.ndarray]:
        """根据映射从 self._mat_data 中获取数组。"""
        var_name = mapping.get(key)
        if var_name is None or var_name not in self._mat_data:
            return None
        return np.asarray(self._mat_data[var_name])

    @staticmethod
    def _to_flat_float(arr: Optional[np.ndarray]) -> Optional[np.ndarray]:
        """将数组展平为 float64 类型，处理各种形状。"""
        if arr is None:
            return None
        try:
            flat = arr.astype(np.float64, copy=False).flatten()
            return flat
        except (ValueError, TypeError):
            return None

    # ── 元信息 ──────────────────────────────────────────

    def metadata(self) -> DataSourceMeta:
        if self._meta is None:
            fmt = self._detect_format()
            self._meta = DataSourceMeta(
                id=self._build_id(),
                type=self.SOURCE_TYPE,
                format=fmt,
                file_path=self.file_path,
            )
        return self._meta

    # ── 辅助方法 ─────────────────────────────────────────

    def get_variable_names(self) -> List[str]:
        """返回 .mat 文件中的所有变量名。"""
        if not self._var_names:
            self._load_mat()
        return self._var_names

    def get_variable_summary(self) -> Dict[str, Tuple[str, str]]:
        """返回变量摘要：{变量名: (形状字符串, 类型字符串)}。"""
        if self._mat_data is None:
            self._mat_data = self._load_mat()
        summary: Dict[str, Tuple[str, str]] = {}
        for name, val in self._mat_data.items():
            arr = np.asarray(val)
            shape_str = "x".join(str(s) for s in arr.shape)
            dtype_str = str(arr.dtype)
            summary[name] = (shape_str, dtype_str)
        return summary
