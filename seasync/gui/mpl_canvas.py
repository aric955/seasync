"""
SeaSync MplCanvas — Matplotlib 嵌入式画布组件。
提供场景渲染、关联图、PPI 极坐标显示。
通用型设计：支持任意传感器对（雷达/AIS/光学/声纳/GPS等）。
"""

# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 荣火
from __future__ import annotations
from typing import Optional, List, Tuple, Dict
from collections import defaultdict

_HAVE_MPL = False
FigureCanvasQTAgg = None
NavigationToolbar2QT = None
Figure = None
mpatches = None
_import_errors = []

# 尝试导入 matplotlib Qt 后端（支持多种后端名称）
for _backend_name in ['matplotlib.backends.backend_qt5agg', 'matplotlib.backends.backend_qtagg']:
    try:
        _mod = __import__(_backend_name, fromlist=['FigureCanvasQTAgg', 'NavigationToolbar2QT'])
        FigureCanvasQTAgg = _mod.FigureCanvasQTAgg
        NavigationToolbar2QT = _mod.NavigationToolbar2QT
        from matplotlib.figure import Figure
        import matplotlib.patches as mpatches
        _HAVE_MPL = True
        break
    except Exception as _e:
        _import_errors.append(f"{_backend_name}: {_e}")
        continue

if _HAVE_MPL:
    import matplotlib.pyplot as plt
    import numpy as np

    class MplCanvas(FigureCanvasQTAgg):
        def __init__(self, figsize=(8, 6), dpi=100) -> None:
            self.fig = Figure(figsize=figsize, dpi=dpi)
            self.fig.patch.set_facecolor("#1a1a2e")
            self.ax = self.fig.add_subplot(111)
            self._style_axes()
            self._hover_annot = None
            self._hover_conn = None
            self.toolbar = None
            # 保存用户手动设置的视图范围，避免刷新时重置缩放
            self._user_xlim: Optional[Tuple[float, float]] = None
            self._user_ylim: Optional[Tuple[float, float]] = None
            self._auto_scale = True
            # 框选放大状态
            self._zoom_rect = None
            self._zoom_start = None
            self._zoom_active = False
            super().__init__(self.fig)
            self._setup_mouse_events()

        def _setup_mouse_events(self) -> None:
            """设置鼠标事件：滚轮缩放 + 框选放大。"""
            self.mpl_connect("scroll_event", self._on_scroll)
            self.mpl_connect("button_press_event", self._on_mouse_press)
            self.mpl_connect("button_release_event", self._on_mouse_release)
            self.mpl_connect("motion_notify_event", self._on_mouse_move)
            # 滚轮事件节流计时器
            self._scroll_timer = None

        def _on_scroll(self, event) -> None:
            """鼠标滚轮缩放：以鼠标位置为中心。"""
            if event.inaxes != self.ax:
                return
            # 滚轮向上=放大(factor<1)，向下=缩小(factor>1)
            factor = 0.9 if event.step > 0 else 1.1
            self._auto_scale = False
            xlim = self.ax.get_xlim()
            ylim = self.ax.get_ylim()
            # 以鼠标位置为中心缩放
            x_data = event.xdata
            y_data = event.ydata
            x_range = (xlim[1] - xlim[0]) * factor / 2
            y_range = (ylim[1] - ylim[0]) * factor / 2
            # 新范围：保持鼠标位置在相对位置不变
            x_ratio = (x_data - xlim[0]) / (xlim[1] - xlim[0])
            y_ratio = (y_data - ylim[0]) / (ylim[1] - ylim[0])
            new_xlim = (x_data - x_range * 2 * x_ratio, x_data + x_range * 2 * (1 - x_ratio))
            new_ylim = (y_data - y_range * 2 * y_ratio, y_data + y_range * 2 * (1 - y_ratio))
            # 限制最小范围
            if abs(new_xlim[1] - new_xlim[0]) < 1e-6:
                return
            if abs(new_ylim[1] - new_ylim[0]) < 1e-6:
                return
            self.ax.set_xlim(new_xlim)
            self.ax.set_ylim(new_ylim)
            self._user_xlim = new_xlim
            self._user_ylim = new_ylim
            # 使用 flush_events 强制立即刷新，避免事件堆积
            self.fig.canvas.draw_idle()
            self.fig.canvas.flush_events()

        def _on_mouse_press(self, event) -> None:
            """鼠标按下：开始框选（右键）或 PPI 点击（左键）。"""
            if event.inaxes != self.ax:
                return
            # 右键（button 3）开始框选
            if event.button == 3:
                self._zoom_active = True
                self._zoom_start = (event.xdata, event.ydata)
                # 移除旧的矩形
                if self._zoom_rect is not None:
                    try:
                        self._zoom_rect.remove()
                    except Exception:
                        pass
                    self._zoom_rect = None
                # 保存背景用于 blit
                self._bg_cache = self.fig.canvas.copy_from_bbox(self.ax.bbox)

        def _on_mouse_move(self, event) -> None:
            """鼠标移动：更新框选矩形（使用 blit 避免全量重绘）。"""
            if not self._zoom_active or event.inaxes != self.ax:
                return
            if self._zoom_start is None:
                return
            x0, y0 = self._zoom_start
            x1, y1 = event.xdata, event.ydata
            if x1 is None or y1 is None:
                return
            # 恢复背景
            if hasattr(self, '_bg_cache') and self._bg_cache is not None:
                self.fig.canvas.restore_region(self._bg_cache)
            # 移除旧矩形
            if self._zoom_rect is not None:
                try:
                    self._zoom_rect.remove()
                except Exception:
                    pass
            # 绘制新矩形
            self._zoom_rect = plt.Rectangle(
                (min(x0, x1), min(y0, y1)),
                abs(x1 - x0), abs(y1 - y0),
                fill=False, edgecolor="#0EA5E9", linewidth=1.5, linestyle="--"
            )
            self.ax.add_patch(self._zoom_rect)
            self.ax.draw_artist(self._zoom_rect)
            self.fig.canvas.blit(self.ax.bbox)

        def _on_mouse_release(self, event) -> None:
            """鼠标释放：执行框选放大（右键）。"""
            if not self._zoom_active or event.button != 3:
                return
            self._zoom_active = False
            if self._zoom_start is None or event.inaxes != self.ax:
                return
            x0, y0 = self._zoom_start
            x1, y1 = event.xdata, event.ydata
            # 移除框选矩形
            if self._zoom_rect is not None:
                try:
                    self._zoom_rect.remove()
                except Exception:
                    pass
                self._zoom_rect = None
            self._zoom_start = None
            if hasattr(self, '_bg_cache'):
                self._bg_cache = None
            if x1 is None or y1 is None:
                return
            # 如果框选区域太小，忽略
            if abs(x1 - x0) < 1e-6 or abs(y1 - y0) < 1e-6:
                return
            # 放大到框选区域
            self._auto_scale = False
            self.ax.set_xlim(min(x0, x1), max(x0, x1))
            self.ax.set_ylim(min(y0, y1), max(y0, y1))
            self._user_xlim = self.ax.get_xlim()
            self._user_ylim = self.ax.get_ylim()
            self.fig.canvas.draw_idle()
            self.fig.canvas.flush_events()

        def get_toolbar(self, parent=None) -> NavigationToolbar2QT:
            """返回 NavigationToolbar2QT 实例，支持缩放/平移/保存。"""
            if self.toolbar is None:
                self.toolbar = NavigationToolbar2QT(self, parent)
                # 拦截缩放/平移按钮，标记为用户手动操作
                self.toolbar.zoom = self._wrap_toolbar_action(self.toolbar.zoom, "zoom")
                self.toolbar.pan = self._wrap_toolbar_action(self.toolbar.pan, "pan")
                self.toolbar.home = self._wrap_home_action(self.toolbar.home)
            return self.toolbar

        def _wrap_toolbar_action(self, original_method, action_name):
            """包装工具栏方法，检测用户手动缩放/平移。"""
            def wrapped(*args, **kwargs):
                self._auto_scale = False
                return original_method(*args, **kwargs)
            return wrapped

        def _wrap_home_action(self, original_method):
            """包装 Home 按钮，恢复自动缩放。"""
            def wrapped(*args, **kwargs):
                self._auto_scale = True
                self._user_xlim = None
                self._user_ylim = None
                return original_method(*args, **kwargs)
            return wrapped

        def _save_user_limits(self) -> None:
            """保存当前视图范围（如果用户手动调整过）。"""
            if not self._auto_scale:
                self._user_xlim = self.ax.get_xlim()
                self._user_ylim = self.ax.get_ylim()

        def zoom_in(self, factor: float = 0.9) -> None:
            """放大视图（factor < 1 表示放大，0.9=每次放大10%）。"""
            self._auto_scale = False
            xlim = self.ax.get_xlim()
            ylim = self.ax.get_ylim()
            x_center = (xlim[0] + xlim[1]) / 2
            y_center = (ylim[0] + ylim[1]) / 2
            x_range = (xlim[1] - xlim[0]) * factor / 2
            y_range = (ylim[1] - ylim[0]) * factor / 2
            # 限制最小范围，避免缩放到比数据点还小
            x_range = max(x_range, 1e-6)
            y_range = max(y_range, 1e-6)
            self.ax.set_xlim(x_center - x_range, x_center + x_range)
            self.ax.set_ylim(y_center - y_range, y_center + y_range)
            self._user_xlim = self.ax.get_xlim()
            self._user_ylim = self.ax.get_ylim()
            self.draw_idle()

        def zoom_out(self, factor: float = 1.1) -> None:
            """缩小视图（factor > 1 表示缩小，1.1=每次缩小10%）。"""
            self._auto_scale = False
            xlim = self.ax.get_xlim()
            ylim = self.ax.get_ylim()
            x_center = (xlim[0] + xlim[1]) / 2
            y_center = (ylim[0] + ylim[1]) / 2
            x_range = (xlim[1] - xlim[0]) * factor / 2
            y_range = (ylim[1] - ylim[0]) * factor / 2
            self.ax.set_xlim(x_center - x_range, x_center + x_range)
            self.ax.set_ylim(y_center - y_range, y_center + y_range)
            self._user_xlim = self.ax.get_xlim()
            self._user_ylim = self.ax.get_ylim()
            self.draw_idle()

        def zoom_reset(self) -> None:
            """恢复自动缩放（Home功能）。"""
            self._auto_scale = True
            self._user_xlim = None
            self._user_ylim = None
            # 触发一次重绘以应用自动缩放
            from ..visualization.draw_command import DrawScene, DrawCommand, DrawType
            scene = DrawScene(viewport=self.ax.get_xlim() + self.ax.get_ylim())
            self.render_scene(scene, "")

        def _style_axes(self) -> None:
            from .themes import SeaSyncTheme as T
            self.ax.tick_params(colors=T.TEXT_SECONDARY, labelsize=9)
            self.ax.set_facecolor(T.BG_DARK)
            for spine in self.ax.spines.values():
                spine.set_edgecolor(T.BORDER)
            self.ax.set_xlabel("X", color=T.TEXT_PRIMARY, fontsize=10)
            self.ax.set_ylabel("Y", color=T.TEXT_PRIMARY, fontsize=10)

        def render_scene(self, scene, title=None, coord_mode="xy"):
            from ..visualization.draw_command import DrawType
            from .themes import SeaSyncTheme as T
            # 保存用户手动调整的视图范围
            self._save_user_limits()
            self.ax.clear(); self._style_axes(); self.ax.set_facecolor(T.BG_DARK)
            scene.sort()
            for cmd in scene.commands:
                self._render_command(cmd)
            if scene.viewport:
                if self._auto_scale or self._user_xlim is None:
                    self.ax.set_xlim(scene.viewport[0], scene.viewport[2])
                    self.ax.set_ylim(scene.viewport[1], scene.viewport[3])
                else:
                    self.ax.set_xlim(self._user_xlim)
                    self.ax.set_ylim(self._user_ylim)
            if scene.legend_items:
                patches = [mpatches.Patch(color=c, label=l) for l, c in scene.legend_items]
                self.ax.legend(handles=patches, loc="upper right", labelcolor=T.TEXT_PRIMARY,
                               facecolor=T.BG_DARKEST, edgecolor=T.BORDER, fontsize=9)
            self.ax.set_title(title or scene.title, color=T.TEXT_PRIMARY, fontsize=14, pad=12)
            lbl = "经度 (Longitude)" if coord_mode == "latlon" else "X"
            self.ax.set_xlabel(lbl, color=T.TEXT_PRIMARY, fontsize=10)
            self.ax.set_ylabel("纬度" if coord_mode == "latlon" else "Y", color=T.TEXT_PRIMARY, fontsize=10)
            self.fig.tight_layout(); self.draw()

        def _render_command(self, cmd):
            from ..visualization.draw_command import DrawType
            t = cmd.draw_type
            if t == DrawType.POINT and cmd.points:
                x, y = cmd.points[0]
                self.ax.scatter(x, y, color=cmd.color, s=20, alpha=cmd.alpha, zorder=cmd.z_order)
                if cmd.label:
                    self.ax.annotate(cmd.label, (x, y), color=cmd.label_color or cmd.color,
                                     fontsize=cmd.label_size or 9, zorder=cmd.z_order + 1)
            elif t == DrawType.LINE and len(cmd.points) >= 2:
                self.ax.plot([p[0] for p in cmd.points], [p[1] for p in cmd.points],
                             color=cmd.color, lw=cmd.line_width, alpha=cmd.alpha, zorder=cmd.z_order)
            elif t == DrawType.CIRCLE and cmd.center and cmd.radius:
                self.ax.add_patch(plt.Circle(cmd.center, cmd.radius,
                    ec=cmd.color, fc=cmd.fill or "none", alpha=cmd.alpha,
                    lw=cmd.line_width, zorder=cmd.z_order))
            elif t == DrawType.TEXT and cmd.points:
                self.ax.text(cmd.points[0][0], cmd.points[0][1], cmd.label or "",
                             color=cmd.color, fontsize=cmd.label_size or 10, zorder=cmd.z_order)
            elif t == DrawType.ARROW and len(cmd.points) >= 2:
                self.ax.annotate("", xy=cmd.points[0], xytext=cmd.points[-1],
                                 arrowprops=dict(arrowstyle="->", color=cmd.color,
                                                 lw=cmd.line_width), zorder=cmd.z_order)

        def render_association(self, records_a, records_b,
                               assoc_result=None, title="关联可视化",
                               label_a="源A", label_b="源B"):
            """渲染两源关联图（通用型）。

            Args:
                records_a: 第一组传感器记录
                records_b: 第二组传感器记录
                assoc_result: 关联结果
                title: 图表标题
                label_a: 第一组标签
                label_b: 第二组标签
            """
            from .themes import SeaSyncTheme as T
            self._save_user_limits()
            self.ax.clear(); self.ax.set_facecolor(T.BG_DARK); self.fig.patch.set_facecolor(T.BG_DARKEST)
            from ..visualization.draw_command import COLOR_CYCLE as _color_cycle
            valid_a = [r for r in records_a if r.lat is not None]
            valid_b = [r for r in records_b if r.lat is not None]
            if not valid_a and not valid_b:
                self.ax.text(0.5, 0.5, "no data", color="white",
                             ha="center", va="center", transform=self.ax.transAxes, fontsize=16)
                self.draw(); return

            # 按 track_id 分组
            tracks_a = defaultdict(list)
            for r in valid_a:
                tracks_a[r.track_id].append(r)
            tracks_b = defaultdict(list)
            for r in valid_b:
                key = r.metadata.get("mmsi") or r.track_id
                tracks_b[key].append(r)

            # 构建匹配映射（使用新字段 source1_id / source2_id）
            ms: Dict[str, str] = {}
            if assoc_result and assoc_result.pairs:
                for p in assoc_result.pairs:
                    ms[p.source1_id] = p.source2_id

            # 匹配/未匹配分类
            matched_a = set(ms.keys())
            matched_b = set(ms.values())
            rm, ru = [], []
            for r in valid_a:
                (rm if r.track_id in matched_a else ru).append(r)
            am, au = [], []
            for r in valid_b:
                key = r.metadata.get("mmsi") or r.track_id
                (am if key in matched_b else au).append(r)

            # 未匹配源A：灰点
            if ru:
                self.ax.scatter([r.lon for r in ru], [r.lat for r in ru], c="#555555", s=8, alpha=0.3)
            # 未匹配源B：按源着色
            if au:
                src_colors = {}
                for r in au:
                    src = r.source_id or ""
                    if src not in src_colors:
                        idx = len(src_colors) % len(_color_cycle)
                        src_colors[src] = _color_cycle[idx]
                for src, color in src_colors.items():
                    src_recs = [r for r in au if (r.source_id or "") == src]
                    if src_recs:
                        self.ax.scatter(
                            [r.lon for r in src_recs], [r.lat for r in src_recs],
                            c=color, s=15, alpha=0.5, marker="D")

            # 匹配对：逐对使用独立颜色 + 连线
            TC = _color_cycle
            legend_items = []
            for i, (id_a, id_b) in enumerate(ms.items()):
                c = TC[i % len(TC)]
                rp = sorted([r for r in rm if r.track_id == id_a], key=lambda x: x.time)
                ap = sorted([r for r in am if (r.metadata.get("mmsi") or r.track_id) == id_b], key=lambda x: x.time)
                label = f"{id_a}↔{id_b}"
                if len(rp) > 1:
                    self.ax.plot([r.lon for r in rp], [r.lat for r in rp], c=c, lw=2, alpha=0.7, label=label)
                if len(ap) > 1:
                    self.ax.plot([r.lon for r in ap], [r.lat for r in ap], c=c, lw=2, alpha=0.7, ls=":")
                if rp and ap:
                    self.ax.plot([rp[-1].lon, ap[-1].lon], [rp[-1].lat, ap[-1].lat],
                                 c=c, lw=1.5, ls="--", alpha=0.6)
                    self.ax.scatter([rp[-1].lon], [rp[-1].lat], c=c, s=120, alpha=0.9,
                                    ec="white", lw=1.5, zorder=3)
                    self.ax.scatter([ap[-1].lon], [ap[-1].lat], c=c, s=120, alpha=0.9,
                                    ec="white", lw=1.5, marker="D", zorder=3)
                legend_items.append((c, label))

            if assoc_result:
                self.ax.text(0.5, 0.98,
                             f"pairs: {len(assoc_result.pairs)} quality: {assoc_result.total_quality:.3f}",
                             c="#aaa", fontsize=10, ha="center", va="top", transform=self.ax.transAxes)

            # 图例
            patches = [mpatches.Patch(color=c, label=l) for c, l in legend_items]
            if ru:
                patches.insert(0, mpatches.Patch(color="#555555", label=f"{label_a}({len(ru)})"))
            from .themes import SeaSyncTheme as T
            self.ax.legend(handles=patches, loc="upper right", labelcolor=T.TEXT_PRIMARY,
                           facecolor=T.BG_DARKEST, edgecolor=T.BORDER, fontsize=9)
            self.ax.set_xlabel("lon", color=T.TEXT_PRIMARY); self.ax.set_ylabel("lat", color=T.TEXT_PRIMARY)
            self.ax.set_title(title, c=T.TEXT_PRIMARY, fontsize=15)
            self.fig.tight_layout(); self.draw()

        def clear(self) -> None:
            from .themes import SeaSyncTheme as T
            self.ax.clear(); self._style_axes(); self.ax.set_facecolor(T.BG_DARK); self.draw()

        def render_ppi(self, radar_records, ais_records,
                       origin_lat=37.53, origin_lon=121.42,
                       max_range_km=30.0, assoc_result=None,
                       title="radar ppi"):
            """PPI极坐标显示。点击目标弹出距离方位信息。"""
            from ..core.geo import ll_to_xy
            self._save_user_limits()
            self.ax.clear(); self.ax.set_facecolor("#001a00"); self.fig.patch.set_facecolor("#0a1a0a")

            r_pts = [(r.x or 0, r.y or 0) for r in radar_records if r.x is not None]
            a_pts = []
            for r in ais_records:
                if r.lat is not None:
                    a_pts.append(ll_to_xy(origin_lat, origin_lon, r.lat, r.lon))
                elif r.x is not None:
                    a_pts.append((r.x, r.y))
            all_pts = r_pts + a_pts
            if not all_pts:
                self.ax.text(0, 0, "no data", c="white", ha="center", va="center", fontsize=16)
                self.ax.set_xlim(-5000, 5000); self.ax.set_ylim(-5000, 5000); self.draw(); return
            mdist = max(np.sqrt(x*x + y*y) for x, y in all_pts)
            if max_range_km * 1000 > mdist * 2:
                max_range_km = max(np.ceil(mdist / 5000) * 5, 5)
            mr = max_range_km * 1000

            # grid
            for rk in range(5, int(max_range_km) + 1, 5):
                rm = rk * 1000
                self.ax.add_patch(plt.Circle((0, 0), rm, fill=False, ec="#1a7a1a",
                    lw=1 if rk % 10 == 0 else 0.5, ls="-" if rk % 10 == 0 else "--", alpha=0.7))
                self.ax.text(0, rm, f"{rk}km", c="#3a7a3a", fontsize=9, ha="center", va="bottom")
            for az in range(0, 360, 45):
                r = np.deg2rad(az); dx, dy = mr * np.sin(r), mr * np.cos(r)
                self.ax.plot([0, dx], [0, dy], c="#1a7a1a", lw=0.5, alpha=0.5)
                self.ax.text(dx * 1.08, dy * 1.08, f"{az}", c="#3a7a3a", fontsize=10, ha="center", va="center")
            self.ax.scatter(0, 0, c="#FFD700", s=160, marker="X", ec="white", lw=2, zorder=10, label="radar site")

            # 匹配映射（使用新字段 source1_id / source2_id）
            ms: Dict[str, str] = {}
            if assoc_result and assoc_result.pairs:
                for p in assoc_result.pairs:
                    ms[p.source1_id] = p.source2_id

            self._ppi_targets: List[dict] = []
            # radar
            rbt = defaultdict(list)
            for r, (x, y) in [(r, (r.x or 0, r.y or 0)) for r in radar_records if r.x is not None]:
                rbt[r.track_id].append((x, y, r.lat, r.lon, r.time))
            for tid, pts in rbt.items():
                xs, ys = [p[0] for p in pts], [p[1] for p in pts]
                m = tid in ms
                sc = self.ax.scatter(xs, ys, c="#FF4444" if m else "#66EE66",
                    s=50 if m else 20, alpha=0.95 if m else 0.6,
                    ec="white" if m else "#AAFFAA", lw=1, picker=True, zorder=5 if m else 3)
                cx, cy = np.mean(xs), np.mean(ys)
                self._ppi_targets.append({
                    "scatter": sc, "type": "radar", "track": tid,
                    "dist_m": f"{np.sqrt(cx*cx+cy*cy):.0f}m",
                    "az_deg": f"{np.rad2deg(np.arctan2(cx,cy))%360:.1f}",
                    "latlon": f"lat={pts[0][2]:.4f}, lon={pts[0][3]:.4f}" if pts[0][2] else "",
                    "matched": m, "count": len(pts),
                })

            # ais — 按源分组不同颜色
            from ..visualization.draw_command import COLOR_CYCLE as _color_cycle
            akey = defaultdict(list)
            a_sources: Dict[str, str] = {}  # key -> color
            for r in ais_records:
                if r.lat is not None:
                    key = r.metadata.get("mmsi") or r.track_id
                    akey[key].append(ll_to_xy(origin_lat, origin_lon, r.lat, r.lon))
                    src = r.source_id or ""
                    if src not in a_sources:
                        idx = len(a_sources) % len(_color_cycle)
                        a_sources[src] = _color_cycle[idx]
            for key, pts in akey.items():
                xs, ys = [p[0] for p in pts], [p[1] for p in pts]
                m = any(key == ms.get(t) for t in rbt)
                src_color = "#44DDDD"
                for r in ais_records:
                    if (r.metadata.get("mmsi") or r.track_id) == key:
                        src = r.source_id or ""
                        if src in a_sources:
                            src_color = a_sources[src]
                        break
                matched_color = "#FFD700"  # 金色表示已匹配
                use_color = matched_color if m else src_color
                sc = self.ax.scatter(xs, ys,
                    c=use_color,
                    s=50 if m else 25, alpha=0.95 if m else 0.8,
                    ec="white", lw=1 if m else 0.5, marker="D",
                    picker=True, zorder=7 if m else 4)
                cx, cy = np.mean(xs), np.mean(ys)
                self._ppi_targets.append({
                    "scatter": sc, "type": "ais", "track": key,
                    "dist_m": f"{np.sqrt(cx*cx+cy*cy):.0f}m",
                    "az_deg": f"{np.rad2deg(np.arctan2(cx,cy))%360:.1f}",
                    "latlon": f"lat={cy:.4f}, lon={cx:.4f}",
                    "matched": m, "count": len(pts),
                })

            # lines
            for tid, aid in ms.items():
                rp = rbt.get(tid, []); ap = akey.get(aid, [])
                if rp and ap:
                    self.ax.plot([rp[-1][0], ap[-1][0]], [rp[-1][1], ap[-1][1]],
                                 c="#FFD700", lw=2, ls="--", alpha=0.8, zorder=4)

            # click interaction
            self._ppi_hover = self.ax.annotate("", xy=(0,0), xytext=(10,10),
                textcoords="offset points", c="white", fontsize=11,
                bbox=dict(boxstyle="round,pad=0.4", fc="#0a1a0a",
                          ec="#00FF00", alpha=0.9), zorder=20)
            self._ppi_hover.set_visible(False)

            def _on_ppi_click(event):
                if event.inaxes != self.ax: return
                for tgt in self._ppi_targets:
                    cont, _ = tgt["scatter"].contains(event)
                    if cont:
                        tag = " [matched]" if tgt["matched"] else ""
                        text = (f"  {tgt['type'].upper()}{tag} {tgt['track']}\n"
                                f"  dist: {tgt['dist_m']}  az: {tgt['az_deg']}\n"
                                f"  {tgt['latlon']}\n"
                                f"  points: {tgt['count']}")
                        self._ppi_hover.set_text(text)
                        self._ppi_hover.xy = (event.xdata, event.ydata)
                        self._ppi_hover.get_bbox_patch().set_edgecolor(
                            "#FF4444" if tgt["type"] == "radar" else "#00FFFF")
                        self._ppi_hover.set_visible(True)
                        self.draw_idle(); return
                if self._ppi_hover.get_visible():
                    self._ppi_hover.set_visible(False); self.draw_idle()

            if hasattr(self, '_ppi_click_conn') and self._ppi_click_conn:
                try:
                    self.mpl_disconnect(self._ppi_click_conn)
                except Exception:
                    import logging
                    logging.getLogger("seasync").warning(
                        "mpl_disconnect failed", exc_info=True)
            self._ppi_click_conn = self.mpl_connect("button_press_event", _on_ppi_click)

            # 图例
            legend_items = [
                ("#FFD700", "radar site"), ("#FF4444", "radar(matched)"), ("#66EE66", "radar"),
            ]
            ais_src_colors = {}
            for r in ais_records:
                src = r.source_id or ""
                key = r.metadata.get("mmsi") or r.track_id
                if src not in ais_src_colors:
                    idx = len(ais_src_colors) % len(_color_cycle)
                    short = src.replace("AIS_Trajectory_", "").replace("_", "")
                    short = short[:12] if len(short) > 12 else short
                    ais_src_colors[src] = (short, _color_cycle[idx])
            for _, (label, color) in sorted(ais_src_colors.items()):
                legend_items.append((color, f"AIS:{label}"))
            legend_items.append(("#FFD700", "matched"))

            self.ax.legend(handles=[mpatches.Patch(color=c, label=l) for c, l in legend_items],
                           loc="upper right", labelcolor="white",
                           facecolor="#0a1a0a", edgecolor="#3a7a3a", fontsize=9)
            info = f"origin {origin_lat:.4f}N {origin_lon:.4f}E | radar{len(r_pts)} ais{len(a_pts)}"
            if assoc_result: info += f" | {assoc_result.n_pairs} pairs"
            self.ax.text(0.98, 0.02, info, c="#ccc", fontsize=9, ha="right", va="bottom",
                         transform=self.ax.transAxes,
                         bbox=dict(fc="#0a1a0a", ec="none", alpha=0.7))
            margin = mr * 1.15
            self.ax.set_xlim(-margin, margin); self.ax.set_ylim(-margin, margin)
            self.ax.set_aspect("equal")
            self.ax.set_xlabel("distance (m)", c="#66AA66", fontsize=10)
            self.ax.set_ylabel("distance (m)", c="#66AA66", fontsize=10)
            self.ax.set_title(title, c="white", fontsize=14, pad=12)
            self.ax.tick_params(colors="#3a7a3a", labelsize=8)
            for s in self.ax.spines.values(): s.set_edgecolor("#2a5a2a")
            self.fig.subplots_adjust(left=0.1, right=0.95, top=0.92, bottom=0.1)
            self.draw()

        def render_ppi_frame(self, radar_records, ais_records,
                              origin_lat=37.53, origin_lon=121.42,
                              assoc_result=None,
                              time_range=(0, 1e18),
                              window_ratio=0.05,
                              title="ppi frame"):
            """逐帧PPI显示：只显示指定时间窗口内的点+逐帧匹配连线。

            Args:
                time_range: (t_min, t_max) 当前时间窗口范围（Unix秒）
                window_ratio: 窗口宽度占总时间长度的比例
            """
            from ..core.geo import ll_to_xy
            t_min, t_max = time_range

            # 1. 筛选窗口内的记录（雷达和AIS都按时间过滤）
            radar_in = [r for r in radar_records
                        if r.x is not None and t_min <= r.time <= t_max]
            ais_in = []
            for r in ais_records:
                if r.lat is not None and t_min <= r.time <= t_max:
                    ais_in.append(r)
                elif r.x is not None and t_min <= r.time <= t_max:
                    ais_in.append(r)

            # 计算 AIS 本地坐标（缓存）
            ais_xy = {}
            for r in ais_in:
                if r.lat is not None:
                    ais_xy[id(r)] = ll_to_xy(origin_lat, origin_lon, r.lat, r.lon)
                elif r.x is not None:
                    ais_xy[id(r)] = (r.x, r.y)

            # 2. 计算显示范围
            all_pts = [(r.x or 0, r.y or 0) for r in radar_in]
            all_pts += [ais_xy.get(id(r), (0, 0)) for r in ais_in]
            if not all_pts:
                self._save_user_limits()
                self.ax.clear(); self.ax.set_facecolor("#001a00"); self.fig.patch.set_facecolor("#0a1a0a")
                self.ax.text(0, 0, f"no data @ t={t_min:.0f}", c="white", ha="center", va="center", fontsize=14)
                for rk in [5, 10]:
                    self.ax.add_patch(plt.Circle((0, 0), rk*1000, fill=False, ec="#1a7a1a", lw=0.5, ls="--", alpha=0.5))
                self.ax.set_xlim(-15000, 15000); self.ax.set_ylim(-15000, 15000)
                self.ax.set_aspect("equal"); self.draw(); return

            mdist = max(np.sqrt(x*x + y*y) for x, y in all_pts)
            mr = max(np.ceil(mdist / 5000) * 5000, 5000)

            # 3. 绘制 PPI 背景
            self._save_user_limits()
            self.ax.clear(); self.ax.set_facecolor("#001a00"); self.fig.patch.set_facecolor("#0a1a0a")
            for rk in range(5, int(mr/1000) + 1, 5):
                rm = rk * 1000
                self.ax.add_patch(plt.Circle((0, 0), rm, fill=False, ec="#1a7a1a",
                    lw=1 if rk % 10 == 0 else 0.5, ls="-" if rk % 10 == 0 else "--", alpha=0.7))
                self.ax.text(0, rm, f"{rk}km", c="#3a7a3a", fontsize=9, ha="center", va="bottom")
            for az in range(0, 360, 45):
                r = np.deg2rad(az); dx, dy = mr * np.sin(r), mr * np.cos(r)
                self.ax.plot([0, dx], [0, dy], c="#1a7a1a", lw=0.5, alpha=0.5)
                self.ax.text(dx * 1.08, dy * 1.08, f"{az}", c="#3a7a3a", fontsize=10, ha="center", va="center")
            self.ax.scatter(0, 0, c="#FFD700", s=160, marker="X", ec="white", lw=2, zorder=10, label="radar site")

            # 4. 分组：雷达按 track_id，AIS按 MMSI
            rbt = {}
            for r in radar_in:
                rbt.setdefault(r.track_id, []).append(r)
            abt = {}
            for r in ais_in:
                key = r.metadata.get("mmsi") or r.track_id
                abt.setdefault(key, []).append(r)

            # 构建匹配映射（使用新字段 source1_id / source2_id）
            ms = {}
            if assoc_result and assoc_result.pairs:
                for p in assoc_result.pairs:
                    ms[p.source1_id] = p.source2_id

            # 5. 绘制雷达点
            for tid, pts in rbt.items():
                xs = [r.x for r in pts if r.x is not None]
                ys = [r.y for r in pts if r.y is not None]
                if not xs: continue
                m = tid in ms
                self.ax.scatter(xs, ys, c="#FF4444" if m else "#66EE66",
                    s=60 if m else 25, alpha=0.95 if m else 0.7,
                    ec="white" if m else "#AAFFAA", lw=1.2, zorder=5 if m else 3)

            # 6. 绘制AIS点（菱形）— 按源不同颜色
            from ..visualization.draw_command import COLOR_CYCLE as _color_cycle
            ais_src_colors = {}
            for r in ais_in:
                src = r.source_id or ""
                if src not in ais_src_colors:
                    idx = len(ais_src_colors) % len(_color_cycle)
                    ais_src_colors[src] = _color_cycle[idx]
            for key, pts in abt.items():
                xys = [ais_xy.get(id(r)) for r in pts if ais_xy.get(id(r))]
                xys = [p for p in xys if p is not None]
                if not xys: continue
                xs, ys = zip(*xys)
                m = any(key == sv for sv in ms.values())
                src_color = "#44DDDD"
                for r in pts:
                    src = r.source_id or ""
                    if src in ais_src_colors:
                        src_color = ais_src_colors[src]
                    break
                use_color = "#FFD700" if m else src_color
                self.ax.scatter(xs, ys, c=use_color,
                    s=60 if m else 25, alpha=0.95 if m else 0.8,
                    ec="white", lw=1.2, marker="D", zorder=7 if m else 4)

            # 7. 逐帧匹配连线
            for tid, aid in ms.items():
                rp = rbt.get(tid, [])
                ap = abt.get(aid, [])
                if not rp or not ap:
                    continue
                for rt in rp:
                    if rt.time < t_min or rt.time > t_max:
                        continue
                    best_a = min(ap, key=lambda a: abs(a.time - rt.time))
                    dt = abs(best_a.time - rt.time)
                    if dt > (t_max - t_min) * 3:
                        continue
                    rx = rt.x or 0
                    ry = rt.y or 0
                    axy = ais_xy.get(id(best_a))
                    if axy is None:
                        continue
                    self.ax.plot([rx, axy[0]], [ry, axy[1]],
                                 c="#FFD700", lw=0.8, ls="-", alpha=0.5, zorder=4)

            # 8. 信息栏 + 图例
            legend_items = [
                ("#FFD700", "radar site"), ("#FF4444", "radar(m)"), ("#66EE66", "radar"),
            ]
            for src, color in sorted(ais_src_colors.items()):
                short = src.replace("AIS_Trajectory_", "").replace("_", "")
                short = short[:12] if len(short) > 12 else short
                legend_items.append((color, f"AIS:{short}"))
            legend_items.append(("#FFD700", "matched"))
            self.ax.legend(handles=[mpatches.Patch(color=c, label=l) for c,l in legend_items],
                           loc="upper right", labelcolor="white",
                           facecolor="#0a1a0a", edgecolor="#3a7a3a", fontsize=9)
            n_pairs = assoc_result.n_pairs if assoc_result else 0
            info = (f"origin {origin_lat:.4f}N {origin_lon:.4f}E | "
                    f"time {t_min:.0f}-{t_max:.0f}s | "
                    f"radar{len(radar_in)} ais{len(ais_in)} | {n_pairs} pairs")
            self.ax.text(0.98, 0.02, info, c="#ccc", fontsize=9, ha="right", va="bottom",
                         transform=self.ax.transAxes, bbox=dict(fc="#0a1a0a", ec="none", alpha=0.7))
            margin = mr * 1.15
            self.ax.set_xlim(-margin, margin); self.ax.set_ylim(-margin, margin)
            self.ax.set_aspect("equal")
            self.ax.set_xlabel("distance (m)", c="#66AA66", fontsize=10)
            self.ax.set_ylabel("distance (m)", c="#66AA66", fontsize=10)
            self.ax.set_title(f"{title}  @ t={t_min:.0f}", c="white", fontsize=14, pad=12)
            self.ax.tick_params(colors="#3a7a3a", labelsize=8)
            for s in self.ax.spines.values(): s.set_edgecolor("#2a5a2a")
            self.fig.subplots_adjust(left=0.1, right=0.95, top=0.92, bottom=0.1)
            self.draw()
else:
    class MplCanvas:
        def __init__(self, *a, **kw): pass
        def render_scene(self, *a, **kw): pass
        def render_association(self, *a, **kw): pass
        def render_ppi(self, *a, **kw): pass
        def clear(self): pass
