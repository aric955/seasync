"""
SeaSync V2.2 ImportManager — 数据导入管理器（Facade 模式）。
增强版：自动尝试所有已知适配器，无需用户指定类型。
"""

# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 荣火
from __future__ import annotations
import os
from typing import List, Dict, Optional, Union
import pandas as pd

from .base_adapter import BaseAdapter
from .radar_adapter import RadarAdapter
from .ais_adapter import AISAdapter
from .gps_adapter import GPSAdapter
from .csv_adapter import CSVAdapter
from .dat_adapter import DatAdapter
from .mat_adapter import MatAdapter
from .xlsx_adapter import XLSXAdapter
from .txt_track_adapter import TXTTrackAdapter
from ..core.data_models import DataSourceMeta, TargetRecord

# 类型 → 适配器类
_ADAPTER_MAP: Dict[str, type] = {
    "radar": RadarAdapter,
    "ais": AISAdapter,
    "gps": GPSAdapter,
    "csv": CSVAdapter,
    "dat": DatAdapter,
    "mat": MatAdapter,
    "matlab": MatAdapter,
    "gpx": GPSAdapter,
    "nmea": AISAdapter,
    "xlsx": XLSXAdapter,
    "xls": XLSXAdapter,
    "txt_track": TXTTrackAdapter,
}


def _auto_detect_type(file_path: str) -> str:
    """根据扩展名和文件名猜测数据类型。"""
    ext = os.path.splitext(file_path)[-1].lower().lstrip(".")
    name = os.path.basename(file_path).lower()
    
    # Excel 文件优先检测（避免被误判为 dat）
    if ext in ("xlsx", "xls"):
        return "xlsx"
    
    if "radar" in name or "cutdata" in name or "cut_data" in name or "polar" in name:
        return "radar"
    if "ais" in name or "nmea" in name or "vdm" in name:
        return "ais"
    if "gpx" in name or "gps" in name or "rmc" in name:
        return "gps"
    # "dat" 必须在 ext 为 ".dat" 时才匹配，避免 CutDataTarget 中 substring 误判
    if ext == "dat":
        return "dat"
    if ext in ("mat", "matlab"):
        return "mat"
    if ext == "csv":
        return "csv"
    if ext in _ADAPTER_MAP:
        return ext
    return "dat"


def _is_binary_file(file_path: str, sample_size: int = 256) -> bool:
    """检查文件是否为二进制（非文本）格式。"""
    try:
        with open(file_path, "rb") as f:
            chunk = f.read(sample_size)
        return b"\x00" in chunk or any(b > 127 for b in chunk)
    except Exception:
        return False


class ImportManager:
    """数据导入 Facade，统一入口。

    自动适配流程（用户无需指定类型）：
    1. 用户指定 source_type → 直接使用该适配器
    2. 未指定 → 自动检测文件类型
    3. 尝试专用适配器（CAT048二进制雷达 → AIS → GPS → DAT → CSV）
    4. 全部失败 → 降级DatAdapter（覆盖最广的通用适配器）
    """

    def __init__(self) -> None:
        self._adapters: Dict[str, BaseAdapter] = {}
        self._records: Dict[str, List[TargetRecord]] = {}
        self._source_types: Dict[str, str] = {}  # 缓存推断的源类型

    def get_source_type(self, source_id: str) -> str:
        """获取已注册源的类型（优先使用缓存的推断结果）。"""
        if source_id in self._source_types:
            return self._source_types[source_id]
        adapter = self._adapters.get(source_id)
        if adapter is not None:
            return adapter.SOURCE_TYPE
        return "unknown"

    # ── 注册与查询 ────────────────────────────────────────────

    def register(
        self,
        file_path: str,
        source_type: Optional[str] = None,
        source_id: Optional[str] = None,
        **kwargs,
    ) -> BaseAdapter:
        """注册一个数据文件，返回对应适配器实例。

        自动级联检测流程：
        - 指定类型 → 尝试该适配器 → 失败则降级CSV
        - 未指定类型 → 二进制→CAT048 → CSV
        """
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"文件不存在: {file_path}")

        sid = source_id or os.path.splitext(os.path.basename(file_path))[0]
        if sid in self._adapters:
            return self._adapters[sid]

        adapter = self._try_adapters(file_path, source_type, **kwargs)
        if source_id:
            adapter.metadata().id = source_id
        self._adapters[sid] = adapter
        # 缓存推断的源类型（优先用户指定，其次适配器类型）
        inferred_type = source_type or adapter.SOURCE_TYPE
        self._source_types[sid] = inferred_type
        return adapter

    def _try_adapters(
        self, file_path: str, source_type: Optional[str] = None, **kwargs
    ) -> BaseAdapter:
        """逐级尝试适配器，直到找到能解析的。专用适配器优先。"""
        candidates: List[BaseAdapter] = []

        # 0. 二进制文件优先尝试CAT048RadarAdapter（专用雷达二进制格式）
        ext = os.path.splitext(file_path)[-1].lower()
        if ext not in (".xlsx", ".xls", ".csv", ".json", ".txt", ".mat") and _is_binary_file(file_path):
            try:
                from .cat048_adapter import CAT048RadarAdapter
                candidates.append(CAT048RadarAdapter(file_path, **kwargs))
            except ImportError:
                pass

        # 1. 用户指定类型 → 构建对应适配器
        if source_type:
            cls = _ADAPTER_MAP.get(source_type, CSVAdapter)
            if not any(isinstance(a, cls) for a in candidates):
                candidates.append(cls(file_path, **kwargs))

        # 2. 按文件名推测类型，专用适配器优先
        dtype = _auto_detect_type(file_path)
        cls = _ADAPTER_MAP.get(dtype)
        if cls and not any(isinstance(a, cls) for a in candidates):
            candidates.append(cls(file_path, **kwargs))

        # 3. 用户指定source_type或文件名含radar时 → 尝试RadarAdapter
        if source_type == "radar" or "radar" in os.path.basename(file_path).lower():
            if not any(isinstance(a, RadarAdapter) for a in candidates):
                candidates.append(RadarAdapter(file_path, source_type="radar", **kwargs))

        # 4. 根据扩展名尝试专用适配器
        if ext in (".xlsx", ".xls"):
            # Excel文件优先尝试XLSXAdapter
            if not any(isinstance(a, XLSXAdapter) for a in candidates):
                candidates.append(XLSXAdapter(file_path, **kwargs))
        elif ext == ".csv":
            # CSV文件：先尝试专用的AISAdapter/RadarAdapter，最后才尝试通用CSVAdapter
            pass  # 已在步骤2尝试
        elif ext == ".txt":
            # TXT文件优先尝试航迹适配器（金海豚格式）
            if not any(isinstance(a, TXTTrackAdapter) for a in candidates):
                candidates.append(TXTTrackAdapter(file_path, **kwargs))
        elif ext == ".json":
            # JSON文件处理
            from .json_adapter import JSONAdapter
            if not any(isinstance(a, JSONAdapter) for a in candidates):
                candidates.append(JSONAdapter(file_path, **kwargs))
        elif ext in (".mat",):
            if not any(isinstance(a, MatAdapter) for a in candidates):
                candidates.append(MatAdapter(file_path, **kwargs))

        # 5. 对于CSV文件，补充尝试CSVAdapter（通用兜底）
        if ext == ".csv" and not any(isinstance(a, CSVAdapter) for a in candidates):
            candidates.append(CSVAdapter(file_path, **kwargs))

        # 6. 兜底：DatAdapter（覆盖最广的通用适配器）
        if not any(isinstance(a, DatAdapter) for a in candidates):
            candidates.append(DatAdapter(file_path, **kwargs))

        # 逐个尝试 validate()
        for adapter in candidates:
            try:
                if adapter.validate():
                    # 对CSVAdapter加一层校验：只读1行确认有数据，避免全量加载卡死
                    if isinstance(adapter, CSVAdapter):
                        try:
                            from .csv_adapter import _detect_encoding as _detect_csv_enc
                            import pandas as pd
                            _enc = _detect_csv_enc(file_path)
                            _check = pd.read_csv(file_path, encoding=_enc, nrows=1)
                            if len(_check) == 0:
                                continue
                        except Exception:
                            continue
                    return adapter
            except Exception:
                continue

        return candidates[-1]  # 全部失败则用最后一个（DatAdapter兜底）

    def get_adapter(self, source_id: str) -> Optional[BaseAdapter]:
        return self._adapters.get(source_id)

    def list_sources(self) -> List[Dict[str, str]]:
        return [
            {"source_id": sid, "type": a.SOURCE_TYPE, "path": a.file_path}
            for sid, a in self._adapters.items()
        ]

    # ── 加载 ──────────────────────────────────────────────────

    def load(self, source_id: str, max_records: Optional[int] = None) -> List[TargetRecord]:
        """加载数据源（支持 max_records 限制，大文件自动保护）。

        Args:
            source_id:   已注册的数据源 ID
            max_records: 最大记录数（None=全部，>50MB 文件自动设为50000）
        """
        if source_id not in self._adapters:
            raise KeyError(f"未注册的数据源: {source_id}")
        if source_id not in self._records:
            adapter = self._adapters[source_id]
            # auto-detect: large files get record limit
            if max_records is None and adapter.is_large_file():
                max_records = 50_000
            if hasattr(adapter, 'load'):
                import inspect
                sig = inspect.signature(adapter.load)
                if 'max_records' in sig.parameters:
                    self._records[source_id] = adapter.load(max_records=max_records)
                else:
                    self._records[source_id] = adapter.load()
            else:
                self._records[source_id] = adapter.load()
        return self._records[source_id]

    def load_all(self) -> Dict[str, List[TargetRecord]]:
        for sid in self._adapters:
            if sid not in self._records:
                self._records[sid] = self._adapters[sid].load()
        return self._records

    def to_dataframe(self, source_id: str) -> pd.DataFrame:
        adapter = self._adapters.get(source_id)
        if adapter is None:
            raise KeyError(f"未注册的数据源: {source_id}")
        return adapter.to_dataframe()

    def to_dataframe_all(self) -> pd.DataFrame:
        frames = []
        for sid in self._adapters:
            frames.append(self.to_dataframe(sid))
        if not frames:
            return pd.DataFrame()
        return pd.concat(frames, ignore_index=True)

    # ── 批量导入便捷方法 ─────────────────────────────────────

    def import_files(
        self, file_paths: List[str], source_types: Optional[Dict[str, str]] = None
    ) -> List[str]:
        types = source_types or {}
        sids = []
        for fp in file_paths:
            adapter = self.register(fp, source_type=types.get(fp))
            sids.append(adapter.metadata().id)
        self.load_all()
        return sids

    def import_directory(
        self,
        dir_path: str,
        recursive: bool = True,
        patterns: Optional[List[str]] = None,
        exclude_patterns: Optional[List[str]] = None,
        source_types: Optional[Dict[str, str]] = None,
    ) -> Dict[str, str]:
        """批量导入目录下的所有可识别文件。

        Args:
            dir_path: 目录路径
            recursive: 是否递归子目录
            patterns: 文件匹配模式（如 ["*.csv", "*.xlsx"]，None=全部）
            exclude_patterns: 排除模式（如 ["*.dat", "*.avi"]）
            source_types: 指定文件类型映射 {file_path: type}

        Returns:
            {file_path: source_id} 映射字典
        """
        import glob

        if not os.path.isdir(dir_path):
            raise NotADirectoryError(f"目录不存在: {dir_path}")

        # 构建搜索模式
        if patterns is None:
            patterns = ["*.csv", "*.xlsx", "*.xls", "*.dat", "*.txt", "*.json"]

        # 收集所有匹配文件
        all_files = []
        for pattern in patterns:
            if recursive:
                all_files.extend(glob.glob(os.path.join(dir_path, "**", pattern), recursive=True))
            else:
                all_files.extend(glob.glob(os.path.join(dir_path, pattern)))

        # 去重并排序
        all_files = sorted(set(all_files))

        # 排除指定模式
        if exclude_patterns:
            filtered = []
            for f in all_files:
                fname = os.path.basename(f).lower()
                should_exclude = any(
                    fname.endswith(ep.lower().lstrip("*")) for ep in exclude_patterns
                )
                if not should_exclude:
                    filtered.append(f)
            all_files = filtered

        # 注册所有文件
        results: Dict[str, str] = {}
        for fp in all_files:
            try:
                adapter = self.register(fp, source_type=(source_types or {}).get(fp))
                results[fp] = adapter.metadata().id
            except Exception as e:
                # 静默跳过无法解析的文件
                pass

        return results

    # ── 清理 ─────────────────────────────────────────────────

    def clear_cache(self) -> None:
        self._records.clear()

    def remove(self, source_id: str) -> bool:
        if source_id in self._adapters:
            del self._adapters[source_id]
        if source_id in self._records:
            del self._records[source_id]
        return True

    def __repr__(self) -> str:
        return f"<ImportManager sources={len(self._adapters)} cached={len(self._records)}>"
