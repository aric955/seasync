"""
关联参数配置
支持序列化为 JSON 格式。
"""

# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 荣火
from __future__ import annotations
from typing import Dict, Any


class AssociationConfig:
    """关联算法配置

    属性可通过 .to_dict() 序列化为字典，
    或从字典通过 .from_dict() 恢复。
    """

    def __init__(
        self,
        distance_threshold: float = 500.0,
        time_window_base: float = 5.0,
        time_window_tolerance: float = 2.0,
        min_confidence: float = 0.6,
        use_mahalanobis: bool = True,
        use_track_interpolation: bool = True,
        use_spatial_hash: bool = True,
        sensor_uncertainty: Dict[str, float] = None,
    ) -> None:
        self.distance_threshold = distance_threshold
        self.time_window_base = time_window_base
        self.time_window_tolerance = time_window_tolerance
        self.min_confidence = min_confidence
        self.use_mahalanobis = use_mahalanobis
        self.use_track_interpolation = use_track_interpolation
        self.use_spatial_hash = use_spatial_hash
        self.sensor_uncertainty = sensor_uncertainty or {"radar": 20.0, "ais": 10.0}

    # ── 序列化 ──────────────────────────────────────────────

    def to_dict(self) -> Dict[str, Any]:
        return {
            "distance_threshold": self.distance_threshold,
            "time_window_base": self.time_window_base,
            "time_window_tolerance": self.time_window_tolerance,
            "min_confidence": self.min_confidence,
            "use_mahalanobis": self.use_mahalanobis,
            "use_track_interpolation": self.use_track_interpolation,
            "use_spatial_hash": self.use_spatial_hash,
            "sensor_uncertainty": dict(self.sensor_uncertainty),
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> AssociationConfig:
        return cls(
            distance_threshold=d.get("distance_threshold", 500.0),
            time_window_base=d.get("time_window_base", 5.0),
            time_window_tolerance=d.get("time_window_tolerance", 2.0),
            min_confidence=d.get("min_confidence", 0.6),
            use_mahalanobis=d.get("use_mahalanobis", True),
            use_track_interpolation=d.get("use_track_interpolation", True),
            use_spatial_hash=d.get("use_spatial_hash", True),
            sensor_uncertainty=d.get("sensor_uncertainty", {"radar": 20.0, "ais": 10.0}),
        )

    def to_json(self) -> str:
        import json
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)

    @classmethod
    def from_json(cls, s: str) -> AssociationConfig:
        import json
        return cls.from_dict(json.loads(s))

    # ── 便利方法 ────────────────────────────────────────────

    def __repr__(self) -> str:
        return (
            f"AssociationConfig("
            f"distance={self.distance_threshold}, "
            f"time_window={self.time_window_base}, "
            f"min_conf={self.min_confidence})"
        )
