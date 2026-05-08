"""
SeaSync V2.2 Core 模块
导出所有核心数据模型和配置类。
"""

# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 荣火
from .data_models import (
    TargetRecord,
    DataSourceMeta,
    AssociationPair,
    AssociationResult,
    AlignmentResult,
    EventRecord,
)
from .association_config import AssociationConfig
from .standard_columns import REQUIRED_COLUMNS
from .project_manager import ProjectManager
from .geo import (
    haversine_m,
    haversine_m_np,
    ll_to_xy, xy_to_ll,
    polar_to_ll, ll_to_polar,
    meters_per_deg_lat, meters_per_deg_lon,
)
from .config_manager import ConfigManager, DataConfig, ColumnMapping, UnitConversion, TimeFormat
from .format_detector import SmartFormatDetector, DetectedFormat
from .logger import log, LogManager
from .device_manager import (
    Device,
    DeviceStatus,
    DeviceType,
    MaintenanceRecord,
    DeploymentRecord,
    EquipmentListTemplate,
    ExperimentEquipmentList,
    DeviceManager,
)

__all__ = [
    # 数据模型
    "TargetRecord",
    "DataSourceMeta",
    "AssociationPair",
    "AssociationResult",
    "AlignmentResult",
    "EventRecord",
    # 配置
    "AssociationConfig",
    "REQUIRED_COLUMNS",
    # 地理工具
    "haversine_m",
    "haversine_m_np",
    "ll_to_xy", "xy_to_ll",
    "polar_to_ll", "ll_to_polar",
    "meters_per_deg_lat", "meters_per_deg_lon",
    # 持久化
    "ProjectManager",
    # 配置管理
    "ConfigManager",
    "DataConfig",
    "ColumnMapping",
    "UnitConversion",
    "TimeFormat",
    # 格式检测
    "SmartFormatDetector",
    "DetectedFormat",
    # 日志
    "log",
    "LogManager",
    # 设备管理
    "Device",
    "DeviceStatus",
    "DeviceType",
    "MaintenanceRecord",
    "DeploymentRecord",
    "EquipmentListTemplate",
    "ExperimentEquipmentList",
    "DeviceManager",
]
