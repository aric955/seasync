"""
SeaSync V2.2 BaseAdapter — 所有数据适配器的抽象基类（含配置注入支持）。
"""

# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 荣火
from __future__ import annotations
import abc
import os
import re
from typing import Optional, List, Dict, Any, Tuple
import pandas as pd
import numpy as np

from ..core.data_models import DataSourceMeta, TargetRecord
from ..core.standard_columns import REQUIRED_COLUMNS

# 常用编码列表（按优先级，支持中文路径内容）
_ENCODINGS = ["utf-8", "utf-8-sig", "gbk", "gb2312", "gb18030", "latin-1"]


class BaseAdapter(abc.ABC):
    """数据适配器抽象基类。

    所有传感器/文件适配器必须实现：
    - validate()  — 检查数据是否可读
    - load()      — 返回 List[TargetRecord]
    - to_dataframe() — 返回 pd.DataFrame（标准列名）
    - metadata()  — 返回 DataSourceMeta
    """

    REQUIRED_COLS: List[str] = []   # 子类覆盖，必需的原始列名
    SOURCE_TYPE: str = "unknown"

    # 大文件阈值（超过此大小自动限制记录数）
    LARGE_FILE_BYTES: int = 100 * 1024 * 1024   # 100 MB
    MAX_RECORDS_DEFAULT: int = 50_000            # 默认最大记录数

    def __init__(self, file_path: str, config: Optional[Dict] = None,
                 **kwargs) -> None:
        """初始化适配器。

        Args:
            file_path: 数据文件路径（支持中文路径）
            config: 可选的配置字典，包含列映射、单位转换等
            **kwargs: 额外参数
        """
        self.file_path = file_path
        self._meta: Optional[DataSourceMeta] = None
        self._config = config or {}

        # ── 配置驱动的列映射 ──
        self._column_mapping: Dict[str, str] = self._config.get("column_mapping", {})
        self._unit_conversions: Dict[str, float] = self._config.get("unit_conversions", {})

        # ── 可选配置项 ──
        self._config_encoding: Optional[str] = self._config.get("encoding")
        self._config_delimiter: str = self._config.get("delimiter", ",")
        self._config_header_rows: int = self._config.get("header_rows", 1)
        self._config_skip_rows: int = self._config.get("skip_rows", 0)

    # ── 核心接口（子类必须实现）───────────────────────────────

    @abc.abstractmethod
    def validate(self) -> bool:
        """返回数据是否可读。子类实现。"""
        ...

    @abc.abstractmethod
    def load(self) -> List[TargetRecord]:
        """解析文件，返回目标记录列表。子类实现。"""
        ...

    def to_dataframe(self) -> pd.DataFrame:
        """将 load() 的结果转为标准列 DataFrame。"""
        records = self.load()
        if not records:
            return pd.DataFrame(columns=list(REQUIRED_COLUMNS.keys()))
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
        df = pd.DataFrame(rows)
        for col, dtype in REQUIRED_COLUMNS.items():
            if col not in df.columns:
                df[col] = pd.Series(dtype=dtype)
        return df

    def metadata(self) -> DataSourceMeta:
        """懒加载：首次调用时构建元信息。"""
        if self._meta is None:
            self._meta = DataSourceMeta(
                id=self._build_id(),
                type=self.SOURCE_TYPE,
                format=self._detect_format(),
                file_path=self.file_path,
            )
        return self._meta

    # ── 配置注入方法 ──────────────────────────────────────────

    def _detect_encoding(self, data_bytes: bytes = None) -> str:
        """检测文件编码，支持多编码尝试（含中文GBK/GB2312）。

        优先使用配置指定的编码，其次自动检测。
        """
        if self._config_encoding:
            return self._config_encoding
        return _detect_encoding_bytes(data_bytes) if data_bytes else _detect_encoding_file(self.file_path)

    def _apply_column_mapping(self, df: pd.DataFrame) -> pd.DataFrame:
        """应用配置驱动的列映射。

        根据 self._column_mapping（标准列名 → 源列名），
        将源文件列重命名为标准列名。
        """
        if not self._column_mapping:
            return df
        rename_map = {}
        for std_col, src_col in self._column_mapping.items():
            if src_col in df.columns:
                rename_map[src_col] = std_col
        if rename_map:
            df = df.rename(columns=rename_map)
        return df

    def _apply_unit_conversions(self, df: pd.DataFrame) -> pd.DataFrame:
        """应用配置驱动的单位转换。

        根据 self._unit_conversions（列名 → 转换因子），
        将指定列乘以转换因子。
        """
        if not self._unit_conversions:
            return df
        for col, factor in self._unit_conversions.items():
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce") * factor
        return df

    def _apply_time_conversion(self, df: pd.DataFrame,
                                time_col: str = "time") -> pd.DataFrame:
        """自动检测并转换时间列到 Unix 毫秒时间戳。

        支持格式：
        - Unix 毫秒（> 1e12）
        - Unix 秒（1e9 ~ 1e12）
        - MATLAB datenum（> 1e5，< 1e6）
        - 日期时间字符串（pandas 自动解析）
        """
        if time_col not in df.columns:
            return df

        ts = df[time_col]
        numeric_ts = pd.to_numeric(ts, errors="coerce")

        # 如果大部分可以转为数值，走数值分支
        if numeric_ts.notna().sum() > len(ts) * 0.5:
            mean_val = numeric_ts.mean()
            if mean_val > 1e12:           # 已是毫秒
                df[time_col] = numeric_ts
            elif mean_val > 1e8:           # 秒级 → 毫秒
                df[time_col] = numeric_ts * 1000
            elif 600000 < mean_val < 750000:  # MATLAB datenum → 毫秒
                df[time_col] = (numeric_ts - 719529) * 86400 * 1000
            else:                           # 其他数值，假设为秒
                df[time_col] = numeric_ts * 1000
        else:
            # 字符串时间：尝试 pandas 解析
            parsed = pd.to_datetime(ts, errors="coerce")
            if parsed.notna().sum() > len(ts) * 0.5:
                df[time_col] = parsed.astype(np.int64) // 10**6  # 转毫秒
        return df

    # ── 工具方法（子类可覆盖）────────────────────────────────

    def file_size_mb(self) -> float:
        """返回文件大小（MB）。"""
        try:
            return os.path.getsize(self.file_path) / (1024 * 1024)
        except OSError:
            return 0.0

    def is_large_file(self, threshold_mb: float = 100.0) -> bool:
        """检查是否为大文件（超过阈值）。"""
        return self.file_size_mb() > threshold_mb

    def _build_id(self) -> str:
        import hashlib
        key = f"{self.SOURCE_TYPE}:{os.path.basename(self.file_path)}"
        return hashlib.md5(key.encode()).hexdigest()[:12]

    def _detect_format(self) -> str:
        ext = os.path.splitext(self.file_path)[-1].lower()
        return ext.lstrip(".")

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} file={self.file_path!r}>"


# ── 工具函数 ──────────────────────────────────────────────────


def _detect_encoding_file(file_path: str) -> str:
    """检测文件编码。"""
    try:
        with open(file_path, "rb") as f:
            raw = f.read(4096)
        return _detect_encoding_bytes(raw)
    except Exception:
        return "utf-8"


def _detect_encoding_bytes(raw: bytes) -> str:
    """检测字节数据的编码。"""
    for enc in _ENCODINGS:
        try:
            raw.decode(enc)
            return enc
        except (UnicodeDecodeError, LookupError):
            continue
    return "utf-8"


def _read_csv_with_encoding(file_path: str, **kwargs) -> pd.DataFrame:
    """使用多编码尝试读取 CSV 文件，自动检测编码。"""
    encodings = _ENCODINGS[:]
    # 将配置编码置顶
    config_enc = kwargs.pop("encoding", None)
    if config_enc and config_enc not in encodings:
        encodings.insert(0, config_enc)

    errors = []
    for enc in encodings:
        try:
            return pd.read_csv(file_path, encoding=enc, **kwargs)
        except (UnicodeDecodeError, pd.errors.ParserError) as e:
            errors.append(f"{enc}: {e}")
            continue
    raise ValueError(
        f"无法以编码序列解析 {file_path}。尝试过的编码：\n" + "\n".join(errors)
    )
