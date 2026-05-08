"""
SeaSync V2.2 Visualization — Matplotlib 渲染器。
支持 DrawCommand 批量渲染 + 关联结果可视化。
通用型设计：支持任意传感器对（雷达/AIS/光学/声纳/GPS等）。
"""

# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 荣火
from __future__ import annotations
from typing import Optional, List, Tuple, Dict, Any
import numpy as np
import matplotlib
matplotlib.use("Agg")  # 无头模式
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import matplotlib.patches as mpatches

# 设置中文字体
for _fname in ['SimHei', 'Microsoft YaHei', 'Noto Sans SC']:
    try:
        matplotlib.rcParams['font.family'] = _fname
        matplotlib.rcParams['axes.unicode_minus'] = False
        break
    except Exception:
        continue

from matplotlib.collections import LineCollection, PathCollection
from matplotlib.path import Path

from .draw_command import DrawScene, DrawCommand, DrawType
from ..core.data_models import TargetRecord, AssociationResult


class SceneRenderer:
    """Matplotlib 场景渲染器。"""

    def __init__(self, figsize: Tuple[int, int] = (12, 8), dpi: int = 100) -> None:
        self.figsize = figsize
        self.dpi = dpi
        self._fig: Optional[plt.Figure] = None
        self._ax: Optional[plt.Axes] = None

    def render(self, scene: DrawScene, title: str = "") -> plt.Figure:
        """渲染 DrawScene，返回 Figure。"""
        # figsize 减半 + 保持 DPI = 在维持物理输出大小的同时提高像素密度（retina 适配）
        fig, ax = plt.subplots(figsize=(self.figsize[0] / 2, self.figsize[1] / 2), dpi=self.dpi)
        fig.patch.set_facecolor("#1a1a2e")
        ax.set_facecolor("#16213e")

        for cmd in scene.commands:
            self._render_command(ax, cmd)

        # 坐标轴
        ax.set_xlim(scene.viewport[0] - 50, scene.viewport[2] + 50)
        ax.set_ylim(scene.viewport[1] - 50, scene.viewport[3] + 50)
        ax.set_xlabel("X (m)", color="white", fontsize=10)
        ax.set_ylabel("Y (m)", color="white", fontsize=10)
        ax.tick_params(colors="white")
        for spine in ax.spines.values():
            spine.set_edgecolor("#4a4a6a")
        ax.set_aspect("equal")
        ax.set_title(title or scene.title, color="white", fontsize=14, pad=12)

        # 图例
        if scene.legend_items:
            patches = [mpatches.Patch(color=c, label=l) for l, c in scene.legend_items]
            ax.legend(handles=patches, loc="upper right", labelcolor="white",
                      facecolor="#1a1a2e", edgecolor="#4a4a6a")

        plt.tight_layout()
        self._fig, self._ax = fig, ax
        return fig

    def _render_command(self, ax: plt.Axes, cmd: DrawCommand) -> None:
        """渲染单个 DrawCommand。"""
        if cmd.draw_type == DrawType.POINT:
            if not cmd.points:
                return
            x, y = cmd.points[0]
            ax.scatter(x, y, color=cmd.color, s=20, alpha=cmd.alpha, zorder=cmd.z_order)
            if cmd.label:
                ax.annotate(cmd.label, (x, y), color=cmd.label_color,
                            fontsize=cmd.label_size, ha="center", va="bottom",
                            zorder=cmd.z_order + 1)

        elif cmd.draw_type == DrawType.LINE:
            if len(cmd.points) < 2:
                return
            xs = [p[0] for p in cmd.points]
            ys = [p[1] for p in cmd.points]
            ax.plot(xs, ys, color=cmd.color, linewidth=cmd.line_width,
                    alpha=cmd.alpha, zorder=cmd.z_order)

        elif cmd.draw_type == DrawType.CIRCLE:
            if cmd.center is None or cmd.radius is None:
                return
            circle = plt.Circle(cmd.center, cmd.radius,
                                color=cmd.color, fill=bool(cmd.fill),
                                facecolor=cmd.fill, alpha=cmd.alpha,
                                zorder=cmd.z_order)
            ax.add_patch(circle)

        elif cmd.draw_type == DrawType.TEXT:
            if not cmd.points:
                return
            x, y = cmd.points[0]
            ax.text(x, y, cmd.label, color=cmd.color, fontsize=cmd.label_size,
                    ha="center", va="center", zorder=cmd.z_order)

        elif cmd.draw_type == DrawType.ARROW:
            if len(cmd.points) < 2:
                return
            ax.annotate("",
                         xy=cmd.points[1], xytext=cmd.points[0],
                         arrowprops=dict(arrowstyle="->", color=cmd.color,
                                         lw=cmd.line_width),
                         zorder=cmd.z_order)

    def save(self, path: str, **kwargs) -> None:
        if self._fig:
            self._fig.savefig(path, **kwargs)

    def close(self) -> None:
        if self._fig:
            plt.close(self._fig)
            self._fig = None
            self._ax = None


def render_tracks(
    tracks: Dict[str, List],
    output_path: Optional[str] = None,
    figsize: Tuple[int, int] = (14, 8),
) -> Optional[str]:
    """渲染多条轨迹，返回图像路径或 Figure。"""
    renderer = SceneRenderer(figsize=figsize)
    scene = DrawScene(viewport=(0, 0, 1000, 1000), title="轨迹视图")

    COLORS = [
        "#FF6B6B", "#4ECDC4", "#45B7D1", "#96CEB4",
        "#FFEAA7", "#DDA0DD", "#98D8C8", "#F7DC6F",
    ]

    all_x, all_y = [], []
    for i, (tid, recs) in enumerate(tracks.items()):
        color = COLORS[i % len(COLORS)]
        xs, ys = [], []
        for r in sorted(recs, key=lambda x: x.time if hasattr(x, "time") else 0):
            if hasattr(r, "x") and r.x is not None and hasattr(r, "y") and r.y is not None:
                x, y = r.x, r.y
            elif hasattr(r, "lon") and r.lon is not None and hasattr(r, "lat") and r.lat is not None:
                x, y = r.lon, r.lat
            else:
                x, y = 0, 0
            xs.append(x)
            ys.append(y)
            scene.add(DrawCommand(
                draw_type=DrawType.POINT,
                points=[(float(x), float(y))],
                color=color,
                track_id=tid,
                z_order=2,
            ))
        if len(xs) >= 2:
            scene.add(DrawCommand(
                draw_type=DrawType.LINE,
                points=list(zip(xs, ys)),
                color=color,
                line_width=1.5,
                track_id=tid,
                z_order=1,
            ))
        all_x.extend(xs)
        all_y.extend(ys)

    if all_x and all_y:
        scene.viewport = (min(all_x), min(all_y), max(all_x), max(all_y))
    scene.legend_items = [(f"轨迹 {k}", COLORS[i % len(COLORS)])
                          for i, k in enumerate(tracks.keys())]

    fig = renderer.render(scene, title="多目标轨迹视图")
    if output_path:
        renderer.save(output_path, facecolor="#1a1a2e")
        renderer.close()
        return output_path
    return None


# ── P2：关联结果可视化（通用型，支持任意传感器对）───────────────────────────

def render_association(
    records_a: List[TargetRecord],
    records_b: List[TargetRecord],
    assoc_result: Optional[AssociationResult] = None,
    output_path: Optional[str] = None,
    title: str = "关联可视化",
    label_a: str = "源A",
    label_b: str = "源B",
) -> Optional[str]:
    """渲染两源关联图（通用型，支持任意传感器对）。

    Args:
        records_a: 第一组传感器记录
        records_b: 第二组传感器记录
        assoc_result: 关联结果
        output_path: 输出图像路径
        title: 图表标题
        label_a: 第一组标签（如 "雷达", "光学"）
        label_b: 第二组标签（如 "AIS", "声纳"）
    """
    fig, ax = plt.subplots(figsize=(14, 10), dpi=100)
    fig.patch.set_facecolor("#1a1a2e")
    ax.set_facecolor("#16213e")

    # ── 提取有效经纬度记录 ──
    valid_a = [r for r in records_a if r.lat is not None and r.lon is not None]
    valid_b = [r for r in records_b if r.lat is not None and r.lon is not None]

    if not valid_a and not valid_b:
        ax.text(0.5, 0.5, "无有效经纬度数据", color="white", ha="center", va="center",
                transform=ax.transAxes, fontsize=16)
        if output_path:
            fig.savefig(output_path)
        plt.close(fig)
        return output_path

    # ── 按 track_id 分组绘制轨迹 ──
    # 源A轨迹
    tracks_a: Dict[str, List[TargetRecord]] = {}
    for r in valid_a:
        tracks_a.setdefault(r.track_id, []).append(r)

    # 源B轨迹（按 metadata.mmsi 或 track_id 分组）
    tracks_b: Dict[str, List[TargetRecord]] = {}
    for r in valid_b:
        key = r.metadata.get("mmsi") or r.track_id
        tracks_b.setdefault(key, []).append(r)

    # 绘制源A轨迹
    color_a = "#FF6B6B"  # 红色
    for tid, recs in tracks_a.items():
        recs_sorted = sorted(recs, key=lambda r: r.time)
        lons = [r.lon for r in recs_sorted]
        lats = [r.lat for r in recs_sorted]
        if len(lons) >= 2:
            ax.plot(lons, lats, color=color_a, linewidth=1.0, alpha=0.4, zorder=2)
        ax.scatter(lons, lats, color=color_a, s=15, alpha=0.6, zorder=3)

    # 绘制源B轨迹
    color_b = "#4ECDC4"  # 青色
    for tid, recs in tracks_b.items():
        recs_sorted = sorted(recs, key=lambda r: r.time)
        lons = [r.lon for r in recs_sorted]
        lats = [r.lat for r in recs_sorted]
        if len(lons) >= 2:
            ax.plot(lons, lats, color=color_b, linewidth=1.2, alpha=0.5, zorder=2)
        ax.scatter(lons, lats, color=color_b, s=20, alpha=0.7, zorder=3)

    # ── 关联连线（黄色虚线）──
    if assoc_result and assoc_result.pairs:
        drawn_labels = set()
        for pair in assoc_result.pairs:
            # 使用新字段 source1_id / source2_id 查找目标
            recs_a = tracks_a.get(pair.source1_id)
            recs_b = tracks_b.get(pair.source2_id)

            if not recs_a or not recs_b:
                continue

            # 取时间最新的点绘制连线
            latest_a = max(recs_a, key=lambda r: r.time)
            latest_b = max(recs_b, key=lambda r: r.time)

            label = "关联匹配" if "关联匹配" not in drawn_labels else None
            ax.plot([latest_a.lon, latest_b.lon],
                    [latest_a.lat, latest_b.lat],
                    color="#FFD93D", linewidth=2.5, linestyle="--", alpha=0.9,
                    label=label, zorder=5)
            drawn_labels.add("关联匹配")

            # 中点标注置信度
            mid_lon = (latest_a.lon + latest_b.lon) / 2
            mid_lat = (latest_a.lat + latest_b.lat) / 2
            ax.annotate(f"{pair.confidence:.3f}",
                        xy=(mid_lon, mid_lat), color="#FFD93D", fontsize=10,
                        ha="center", va="bottom", fontweight="bold",
                        bbox=dict(boxstyle="round,pad=0.2", facecolor="#1a1a2e",
                                  edgecolor="#FFD93D", alpha=0.8))

        # 如果没有绘制任何连线，添加一个图例占位符
        if not drawn_labels:
            ax.plot([], [], color="#FFD93D", linewidth=2.5, linestyle="--", alpha=0.9,
                    label="关联匹配", zorder=5)

    # ── 坐标轴 ──
    all_lons = [r.lon for r in valid_a] + [r.lon for r in valid_b]
    all_lats = [r.lat for r in valid_a] + [r.lat for r in valid_b]
    if all_lons and all_lats:
        margin = max((max(all_lons) - min(all_lons)) * 0.1, 0.001)
        ax.set_xlim(min(all_lons) - margin, max(all_lons) + margin)
        ax.set_ylim(min(all_lats) - margin, max(all_lats) + margin)

    ax.set_xlabel("经度 (Longitude)", color="white", fontsize=11)
    ax.set_ylabel("纬度 (Latitude)", color="white", fontsize=11)
    ax.tick_params(colors="white", labelsize=9)
    ax.grid(True, alpha=0.15, color="white", linestyle=":")
    for spine in ax.spines.values():
        spine.set_edgecolor("#4a4a6a")

    # ── 标题 ──
    ax.set_title(title, color="white", fontsize=15, pad=15, fontweight="bold")

    # ── 图例 ──
    legend_items = [
        (color_a, f"{label_a}轨迹"),
        (color_b, f"{label_b}轨迹"),
    ]
    if assoc_result and assoc_result.pairs:
        legend_items.append(("#FFD93D", "关联匹配"))

    patches = [mpatches.Patch(color=c, label=l) for c, l in legend_items]
    ax.legend(handles=patches, loc="upper right", labelcolor="white", fontsize=10,
              facecolor="#1a1a2e", edgecolor="#4a4a6a", framealpha=0.9)

    # ── 信息标注 ──
    info_parts = []
    if valid_a:
        info_parts.append(f"{label_a}: {len(tracks_a)}条轨迹/{len(valid_a)}点")
    if valid_b:
        info_parts.append(f"{label_b}: {len(tracks_b)}条轨迹/{len(valid_b)}点")
    if assoc_result:
        info_parts.append(f"匹配: {len(assoc_result.pairs)}对")

    info_text = "\n".join(info_parts)
    ax.text(0.02, 0.98, info_text, color="#aaaaaa", fontsize=9,
            transform=ax.transAxes, va="top", ha="left",
            bbox=dict(boxstyle="round,pad=0.3", facecolor="#0d0d1a", alpha=0.6))

    plt.tight_layout()

    if output_path:
        fig.savefig(output_path, facecolor="#1a1a2e", dpi=150, bbox_inches="tight")
        plt.close(fig)
        return output_path

    return None
