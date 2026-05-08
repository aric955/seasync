"""
SeaSync V2.2 DrawCommand — 可视化指令系统。
业务逻辑与 UI 完全解耦：引擎生成 DrawCommand，GUI 负责渲染。
支持任意传感器类型（雷达、AIS、光学、声纳、GPS等）。
"""

# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 荣火
from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Tuple, Optional, Any, Dict
from enum import Enum

# 传感器颜色映射表（基础色：同一类型第一个源使用此颜色）
SENSOR_COLORS: Dict[str, str] = {
    "radar": "#4A90D9",      # 蓝色 — 航海雷达
    "ais": "#E74C3C",        # 红色 — AIS
    "gps": "#2ECC71",        # 绿色 — GPS
    "dat": "#E67E22",        # 橙色 — 通用DAT
    "mat": "#9B59B6",        # 紫色 — MATLAB
    "csv": "#1ABC9C",        # 青色 — 通用CSV
    "cat048": "#4A90D9",     # 蓝色 — CAT048雷达
    "optical": "#F39C12",    # 金色 — 光电
    "sonar": "#16A085",      # 深青 — 声纳
    "imu": "#8E44AD",        # 紫罗兰 — IMU
    "weather": "#D35400",    # 深橙 — 气象
    "other": "#95A5A6",      # 灰色 — 其他
}

# 可视化颜色循环（同一类型的多个源按此循环分配不同颜色）
COLOR_CYCLE = [
    "#FF6B6B", "#4ECDC4", "#45B7D1", "#96CEB4", "#FFEAA7", "#DDA0DD",
    "#FF9F43", "#10AC84", "#5F27CD", "#00D2D3", "#FF9FF3", "#54A0FF",
    "#48DBFB", "#1DD1A1", "#FECA57", "#FF6B6B", "#C8D6E5", "#8395A7",
]

# 源ID到颜色的映射缓存（确保同一源始终使用同一颜色）
_source_color_cache: Dict[str, str] = {}


def get_sensor_color(source_type: str, source_id: str = "") -> str:
    """根据传感器类型和ID返回对应颜色。

    同一类型的第一个源使用基础色，后续源使用 COLOR_CYCLE 分配不同颜色，
    确保多源数据视图中每个源都有独立可区分的颜色。
    """
    st = (source_type or "").lower()
    sid = (source_id or "").lower()

    # 用 source_id 做缓存键，确保同一源始终同色
    cache_key = f"{st}:{sid}" if sid else st
    if cache_key in _source_color_cache:
        return _source_color_cache[cache_key]

    # 尝试精确匹配类型获取基础色
    base_color = None
    if st in SENSOR_COLORS:
        base_color = SENSOR_COLORS[st]
    else:
        # 尝试 source_id 关键字匹配
        for key, color in SENSOR_COLORS.items():
            if key in sid:
                base_color = color
                break
    if base_color is None:
        base_color = SENSOR_COLORS["other"]

    # 如果没有 source_id，直接返回基础色
    if not sid:
        _source_color_cache[cache_key] = base_color
        return base_color

    # 检查该类型已有多少个源被分配了颜色
    same_type_keys = [k for k in _source_color_cache if k.startswith(f"{st}:")]
    if len(same_type_keys) == 0:
        # 第一个该类型的源，使用基础色
        color = base_color
    else:
        # 后续源使用 COLOR_CYCLE 中的颜色（跳过与基础色相同的）
        idx = len(same_type_keys) - 1
        color = COLOR_CYCLE[idx % len(COLOR_CYCLE)]

    _source_color_cache[cache_key] = color
    return color


def clear_sensor_color_cache() -> None:
    """清除源颜色缓存（例如在重新加载数据时调用）。"""
    _source_color_cache.clear()


class DrawType(Enum):
    """支持的图元类型。"""
    POINT = "point"
    LINE = "line"
    POLYGON = "polygon"
    CIRCLE = "circle"
    TEXT = "text"
    ARROW = "arrow"
    ICON = "icon"


@dataclass
class DrawCommand:
    """单个绘制指令。"""
    draw_type: DrawType
    # 坐标
    points: List[Tuple[float, float]] = field(default_factory=list)
    center: Optional[Tuple[float, float]] = None
    radius: Optional[float] = None
    # 样式
    color: str = "#FF6B6B"
    line_width: float = 2.0
    fill: Optional[str] = None
    alpha: float = 1.0
    # 标签
    label: str = ""
    label_size: float = 12.0
    label_color: str = "#FFFFFF"
    # 轨迹属性
    track_id: Optional[str] = None
    source_id: Optional[str] = None
    confidence: Optional[float] = None
    # 层级（z-order）
    z_order: int = 0
    # 元数据
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class DrawScene:
    """完整场景指令集合。"""
    viewport: Tuple[float, float, float, float]  # (min_x, min_y, max_x, max_y)
    commands: List[DrawCommand] = field(default_factory=list)
    title: str = ""
    legend_items: List[Tuple[str, str]] = field(default_factory=list)  # (label, color)

    def add(self, cmd: DrawCommand) -> None:
        self.commands.append(cmd)

    def sort(self) -> None:
        self.commands.sort(key=lambda c: c.z_order)


def records_to_draw_scene(
    records: List[Any],
    viewport: Optional[Tuple[float, float, float, float]] = None,
    source_type: Optional[str] = None,
    source_label: Optional[str] = None,
) -> DrawScene:
    """将 TargetRecord 列表转为 DrawScene（支持按传感器着色）。"""
    scene = DrawScene(viewport=viewport or (0, 0, 1000, 1000))
    if not records:
        return scene
    # 计算视口（同时考虑 xy 和经纬度坐标）
    all_xs = []
    all_ys = []
    for r in records:
        if r.x is not None and r.y is not None:
            all_xs.append(r.x)
            all_ys.append(r.y)
        elif r.lat is not None and r.lon is not None:
            all_xs.append(r.lon)
            all_ys.append(r.lat)
    if all_xs and all_ys:
        scene.viewport = (min(all_xs), min(all_ys), max(all_xs), max(all_ys))
    # 确定颜色
    color = get_sensor_color(source_type or "",
                             str(getattr(records[0], 'source_id', '')))
    label = source_label or source_type or "unknown"
    scene.legend_items.append((label, color))
    # 绘制点
    for r in records:
        if r.lat is None and r.x is None:
            continue
        if r.x is not None and r.y is not None:
            x, y = float(r.x), float(r.y)
        elif r.lon is not None and r.lat is not None:
            x, y = float(r.lon), float(r.lat)
        else:
            continue
        scene.add(DrawCommand(
            draw_type=DrawType.POINT,
            points=[(x, y)],
            color=color,
            track_id=r.track_id,
            source_id=getattr(r, "source_id", None),
            z_order=1,
        ))
    return scene


def association_to_draw_scene(
    pairs: List[Any], records_a: List[Any], records_b: List[Any]
) -> DrawScene:
    """将关联结果转为连线绘制指令（通用型，支持任意传感器对）。

    Args:
        pairs: AssociationPair 列表
        records_a: 第一组传感器记录（source1侧）
        records_b: 第二组传感器记录（source2侧）

    Returns:
        DrawScene，包含关联连线指令
    """
    from ..core.data_models import AssociationPair, TargetRecord
    scene = DrawScene(viewport=(0, 0, 1000, 1000))

    # 按 track_id 索引两组记录
    map_a = {r.track_id: r for r in records_a}
    map_b = {r.track_id: r for r in records_b}

    # 对 AIS 数据，也按 metadata.mmsi 建立索引
    for r in records_b:
        mmsi = r.metadata.get("mmsi")
        if mmsi and mmsi != "None" and mmsi not in map_b:
            map_b[mmsi] = r

    for pair in pairs:
        if not isinstance(pair, AssociationPair):
            continue

        # 使用新字段 source1_id / source2_id 查找目标
        rec_a = map_a.get(pair.source1_id)
        rec_b = map_b.get(pair.source2_id)

        if rec_a is None or rec_b is None:
            continue

        # 提取坐标（支持 xy 和 lat/lon 两种模式）
        def _get_coords(rec):
            if rec.x is not None and rec.y is not None:
                return float(rec.x), float(rec.y)
            elif rec.lon is not None and rec.lat is not None:
                return float(rec.lon), float(rec.lat)
            return None

        coords_a = _get_coords(rec_a)
        coords_b = _get_coords(rec_b)

        if coords_a is None or coords_b is None:
            continue

        alpha = float(pair.confidence) if pair.confidence else 0.5
        scene.add(DrawCommand(
            draw_type=DrawType.LINE,
            points=[coords_a, coords_b],
            color=f"rgba(255,107,107,{alpha})",
            line_width=1.5,
            track_id=pair.source1_id,
            confidence=pair.confidence,
            z_order=5,
            metadata={
                "source1_label": pair.source1_label,
                "source2_label": pair.source2_label,
                "source2_id": pair.source2_id,
            },
        ))
    return scene
