"""
SeaSync V2.2 核心数据模型
所有模块间的数据交换均基于以下结构化类。
"""

# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 荣火
from dataclasses import dataclass, field
from typing import List, Tuple, Optional, Dict, Any
import logging

_logger = logging.getLogger(__name__)


@dataclass
class TargetRecord:
    """单条目标记录（通用型，支持雷达/AIS/光学/声纳等任意传感器）"""
    source_id: str
    track_id: str
    time: float
    x: Optional[float] = None
    y: Optional[float] = None
    lat: Optional[float] = None
    lon: Optional[float] = None
    speed: Optional[float] = None
    course: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class DataSourceMeta:
    """数据源元信息"""
    id: str
    type: str
    format: str
    file_path: str
    time_offset: float = 0.0
    time_range: Optional[Tuple[float, float]] = None
    data_shape: Optional[Tuple[int, int]] = None


@dataclass
class AssociationPair:
    """单条关联结果对（通用型，支持任意两个数据源间的关联）。

    字段设计原则：
    - source1_id / source2_id: 两端的 track_id（如雷达批号、AIS的MMSI、光学的目标ID）
    - source1_label / source2_label: 两端的传感器类型标签（如 "radar", "ais", "optical", "sonar", "gps"）
    - 不区分"雷达端"和"AIS端"，任何传感器都可以作为 source1 或 source2

    向后兼容说明：
    - radar_track_id 属性映射到 source1_id（当 source1_label == "radar" 时）
    - ais_mmsi 属性映射到 source2_id（当 source2_label == "ais" 时）
    - 这些属性为只读，用于兼容旧代码读取，新代码应直接使用 source1_id / source2_id
    """
    source1_id: str = ""
    source2_id: str = ""
    source1_label: str = ""   # "radar", "ais", "optical", "sonar", "gps" 等
    source2_label: str = ""
    confidence: float = 0.0
    method: str = "auto"
    verified: bool = False
    top_candidates: List[Tuple[str, float]] = field(default_factory=list)

    @property
    def radar_track_id(self) -> str:
        """向后兼容：当 source1 或 source2 为雷达时返回其 ID。"""
        if self.source1_label == "radar":
            return self.source1_id
        if self.source2_label == "radar":
            return self.source2_id
        return ""

    @property
    def ais_mmsi(self) -> str:
        """向后兼容：当 source1 或 source2 为 AIS 时返回其 ID。"""
        if self.source1_label == "ais":
            return self.source1_id
        if self.source2_label == "ais":
            return self.source2_id
        return ""

    @property
    def source_ids(self) -> Tuple[str, str]:
        """返回两端的 source_id。"""
        return (self.source1_id, self.source2_id)

    @property
    def source_labels(self) -> Tuple[str, str]:
        """返回两端的类型标签。"""
        return (self.source1_label, self.source2_label)

    def get_id(self, label: str) -> Optional[str]:
        """按标签获取对应的 source_id。

        Args:
            label: 传感器类型标签，如 "radar", "ais", "optical"

        Returns:
            匹配的 source_id，未找到返回 None
        """
        if self.source1_label == label:
            return self.source1_id
        if self.source2_label == label:
            return self.source2_id
        return None

    def get_other_id(self, known_id: str) -> Optional[str]:
        """已知一端 ID，获取另一端 ID。

        Args:
            known_id: 已知的一端 source_id

        Returns:
            另一端的 source_id，未找到返回 None
        """
        if self.source1_id == known_id:
            return self.source2_id
        if self.source2_id == known_id:
            return self.source1_id
        return None

    def __repr__(self) -> str:
        return (
            f"AssociationPair({self.source1_label}:{self.source1_id} "
            f"<-> {self.source2_label}:{self.source2_id}, "
            f"confidence={self.confidence:.3f})"
        )


@dataclass
class AssociationResult:
    """完整的关联结果（通用型）。

    unmatched 字典使用传感器标签作为键，支持任意传感器类型。
    """
    pairs: List[AssociationPair] = field(default_factory=list)
    total_quality: float = 0.0
    unmatched: Dict[str, List[str]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """向后兼容：将旧字段 unmatched_radar / unmatched_ais 迁移到 unmatched 字典。"""
        if not hasattr(self, '_compat_processed'):
            self._compat_processed = True
            # 处理可能存在的旧字段（从旧版 pickle/JSON 加载时）
            old_radar = getattr(self, 'unmatched_radar', None)
            old_ais = getattr(self, 'unmatched_ais', None)
            if old_radar and "radar" not in self.unmatched:
                self.unmatched["radar"] = list(old_radar)
            if old_ais and "ais" not in self.unmatched:
                self.unmatched["ais"] = list(old_ais)

    def get_unmatched(self, label: str) -> List[str]:
        """按标签获取未匹配的 track_id 列表。"""
        return list(self.unmatched.get(label, []))

    def add_unmatched(self, label: str, track_ids: List[str]) -> None:
        """添加未匹配的 track_id 列表。"""
        if label not in self.unmatched:
            self.unmatched[label] = []
        self.unmatched[label].extend(track_ids)

    @property
    def n_pairs(self) -> int:
        return len(self.pairs)

    @property
    def unmatched_radar(self) -> List[str]:
        """向后兼容属性。"""
        return self.get_unmatched("radar")

    @property
    def unmatched_ais(self) -> List[str]:
        """向后兼容属性。"""
        return self.get_unmatched("ais")


@dataclass
class AlignmentResult:
    """时域对齐结果"""
    offset: float
    quality_score: float
    suggestion: str
    needs_manual: bool = False


@dataclass
class EventRecord:
    """事件记录"""
    id: str
    time: float
    name: str
    severity: str
    description: str
    evidence_path: str = ""
    auto_detected: bool = False


@dataclass
class SourceRef:
    """多源关联中的单个数据源引用（V3.0规划）。

    用于表示多元关联关系，如 (radar, AIS, optical) 三元组。
    """
    source_id: str
    track_id: str
    label: str = ""  # "radar", "ais", "optical", "sonar", "gps" 等


@dataclass
class MultiSourceAssociation:
    """多元关联结果（V3.0规划）。

    支持 N 源同时关联，例如 radar ↔ AIS ↔ optical 三元组。
    当前版本仅支持两两关联，此数据结构为未来扩展预留。
    """
    sources: List[SourceRef] = field(default_factory=list)
    confidence: float = 0.0
    method: str = "auto"
    verified: bool = False

    @property
    def n_sources(self) -> int:
        """关联的源数量。"""
        return len(self.sources)

    @property
    def source_ids(self) -> List[str]:
        """返回所有 source_id。"""
        return [s.source_id for s in self.sources]
