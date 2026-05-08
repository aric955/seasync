"""
SeaSync V2.2 — 多源目标关联分析系统

N 源模式（推荐）：
    from seasync.engines import SeaSyncPipeline

    pipe = SeaSyncPipeline()
    pipe.add_source("radar.csv", source_type="radar")
    pipe.add_source("ais_ship1.csv", source_type="ais")
    pipe.add_source("ais_ship2.csv", source_type="ais")

    # 一键全流程：1 雷达 + N 个 AIS 自动两两关联
    steps = pipe.run(source_ids=["radar", "ais_ship1", "ais_ship2"])
    print(f"关联: {steps['association']['n_pairs']}对")

双源模式（向后兼容）：
    pipe = SeaSyncPipeline()
    pipe.add_source("radar.csv", source_type="radar")
    pipe.add_source("ais.csv", source_type="ais")
    result = pipe.run("radar_sid", "ais_sid")
"""

# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 荣火
from .core import (
    TargetRecord,
    DataSourceMeta,
    AssociationPair,
    AssociationResult,
    AlignmentResult,
    EventRecord,
    AssociationConfig,
    ProjectManager,
    REQUIRED_COLUMNS,
)
from .engines import (
    SeaSyncPipeline,
    AssociationEngine,
    ClusteringEngine,
    TimeAligner,
    TrackManager,
    EventDetector,
    ScanTracker,
)
from .adapters import (
    BaseAdapter,
    RadarAdapter,
    AISAdapter,
    GPSAdapter,
    CSVAdapter,
    ImportManager,
)
from .report import ReportGenerator

# 可视化模块（可选依赖：matplotlib）
try:
    from .visualization import render_tracks, SceneRenderer
    _has_visualization = True
except ImportError:
    render_tracks = None
    SceneRenderer = None
    _has_visualization = False

__version__ = "2.2.0"
__all__ = [
    # 入口
    "SeaSyncPipeline",
    "launch_gui",
    # 核心
    "TargetRecord", "DataSourceMeta", "AssociationPair",
    "AssociationResult", "AlignmentResult", "EventRecord",
    "AssociationConfig", "ProjectManager", "REQUIRED_COLUMNS",
    # 引擎
    "AssociationEngine", "ClusteringEngine", "TimeAligner",
    "TrackManager", "EventDetector",
    # 适配器
    "BaseAdapter", "RadarAdapter", "AISAdapter",
    "GPSAdapter", "CSVAdapter", "ImportManager",
    # 工具
    "ReportGenerator", "render_tracks", "SceneRenderer",
]
