"""
SeaSync V2.2 MainWindow — PyQt5 图形界面主窗口。
应用现代深色主题，统一配色、圆角、阴影效果。
"""

# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 荣火
from __future__ import annotations
import os, sys
from typing import Optional, List, Dict
from PyQt5 import QtWidgets, QtCore, QtGui

from ..engines import SeaSyncPipeline
from ..visualization.draw_command import DrawScene, DrawCommand, DrawType, get_sensor_color
from ..core.data_models import TargetRecord
from .mpl_canvas import MplCanvas, _HAVE_MPL
from .worker_thread import WorkerThread
from .themes import SeaSyncTheme


class SeaSyncMainWindow(QtWidgets.QMainWindow):
    """SeaSync 主窗口 — 现代深色主题。"""

    def __init__(self, pipeline: Optional[SeaSyncPipeline] = None) -> None:
        super().__init__()
        self.pipeline = pipeline or SeaSyncPipeline()
        self._processing = False
        self._source_map: Dict[str, tuple] = {}
        self._params = {
            "gate_distance_m": 500.0, "max_coast_steps": 5,
            "min_track_points": 3, "distance_threshold": 500.0,
            "max_speed_kn": 30.0, "time_window_base": 5.0,
            "time_window_tolerance": 2.0,
        }
        self._param_widgets: Dict[str, QtWidgets.QSlider] = {}
        self._worker: Optional[WorkerThread] = None
        self._temp_files: List[str] = []
        self._init_ui()

        # 时间轴状态
        self._ppi_frame_data: dict = {}
        self._ppi_time_range: tuple = (0, 1)
        self._play_timer: QtCore.QTimer = QtCore.QTimer()
        self._play_timer.setInterval(200)
        self._play_timer.timeout.connect(self._on_play_step)

    def _init_ui(self) -> None:
        self.setWindowTitle("SeaSync V2.2 — 多源关联复盘工具")
        self.resize(1600, 1000)
        self.setMinimumSize(1200, 800)

        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        outer_splitter = QtWidgets.QSplitter(QtCore.Qt.Vertical)
        outer_splitter.setHandleWidth(2)
        main_layout = QtWidgets.QVBoxLayout(central)
        main_layout.setContentsMargins(SeaSyncTheme.SPACING_SM, SeaSyncTheme.SPACING_SM,
                                        SeaSyncTheme.SPACING_SM, SeaSyncTheme.SPACING_SM)
        main_layout.setSpacing(SeaSyncTheme.SPACING_SM)
        main_layout.addWidget(outer_splitter)

        top_widget = QtWidgets.QWidget()
        top_layout = QtWidgets.QVBoxLayout(top_widget)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(SeaSyncTheme.SPACING_SM)

        # ── 菜单栏 ──
        menubar = self.menuBar()
        menubar.setNativeMenuBar(False)
        file_menu = menubar.addMenu("文件")
        file_menu.addAction("导入数据", self._on_add_file)
        file_menu.addAction("导出报告", self._on_export_report)
        file_menu.addAction("导出 KML", self._on_export_kml)
        file_menu.addAction("导出结果 CSV/JSON", self._on_export_result)
        process_menu = menubar.addMenu("处理")
        process_menu.addAction("运行完整流程", self._on_run_pipeline)
        process_menu.addAction("多源关联", self._on_multi_associate)
        process_menu.addAction("数据配置", self._on_open_config)

        # ── 左侧：数据源列表 ──
        left = QtWidgets.QWidget()
        left.setObjectName("left_panel")
        left_layout = QtWidgets.QVBoxLayout(left)
        left_layout.setContentsMargins(SeaSyncTheme.SPACING_MD, SeaSyncTheme.SPACING_MD,
                                        SeaSyncTheme.SPACING_MD, SeaSyncTheme.SPACING_MD)
        left_layout.setSpacing(SeaSyncTheme.SPACING_SM)

        # 标题栏
        left_header = QtWidgets.QLabel("数据源")
        left_header.setStyleSheet(f"font-size: {SeaSyncTheme.FONT_SIZE_TITLE}px; font-weight: bold;")
        left_layout.addWidget(left_header)

        self._source_list = QtWidgets.QListWidget()
        self._source_list.setMinimumWidth(200)
        self._source_list.setMaximumWidth(280)
        left_layout.addWidget(self._source_list)

        # 操作按钮组
        btn_group = QtWidgets.QWidget()
        btn_layout = QtWidgets.QVBoxLayout(btn_group)
        btn_layout.setContentsMargins(0, 0, 0, 0)
        btn_layout.setSpacing(SeaSyncTheme.SPACING_SM)

        for text, cb, variant in [
            ("+ 添加文件", self._on_add_file, "primary"),
            ("− 移除选中", self._on_remove_file, "secondary"),
            ("⚙ 数据配置", self._on_open_config, "secondary"),
            ("🔗 多源关联", self._on_multi_associate, "secondary"),
        ]:
            btn = QtWidgets.QPushButton(text)
            btn.clicked.connect(cb)
            btn_layout.addWidget(btn)

        left_layout.addWidget(btn_group)
        left_layout.addStretch()

        # ── 中间：画布 + 自定义缩放工具条 ──
        self._canvas = MplCanvas() if _HAVE_MPL else QtWidgets.QLabel("可视化区域")
        self._canvas.setMinimumSize(400, 300)
        center = QtWidgets.QWidget()
        center.setMinimumSize(400, 300)
        center_layout = QtWidgets.QVBoxLayout(center)
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.setSpacing(0)

        # 自定义缩放工具条
        if _HAVE_MPL:
            zoom_bar = QtWidgets.QWidget()
            zoom_layout = QtWidgets.QHBoxLayout(zoom_bar)
            zoom_layout.setContentsMargins(4, 2, 4, 2)
            zoom_layout.setSpacing(4)

            btn_zoom_out = QtWidgets.QPushButton("−")
            btn_zoom_out.setFixedSize(28, 28)
            btn_zoom_out.setToolTip("缩小")
            btn_zoom_out.clicked.connect(self._canvas.zoom_out)

            btn_zoom_in = QtWidgets.QPushButton("+")
            btn_zoom_in.setFixedSize(28, 28)
            btn_zoom_in.setToolTip("放大")
            btn_zoom_in.clicked.connect(self._canvas.zoom_in)

            btn_home = QtWidgets.QPushButton("⌂")
            btn_home.setFixedSize(28, 28)
            btn_home.setToolTip("重置视图")
            btn_home.clicked.connect(self._canvas.zoom_reset)

            zoom_layout.addWidget(btn_zoom_out)
            zoom_layout.addWidget(btn_zoom_in)
            zoom_layout.addWidget(btn_home)
            zoom_layout.addStretch()
            center_layout.addWidget(zoom_bar)
        center_layout.addWidget(self._canvas, 1)

        # ── 右侧：参数面板 ──
        right = QtWidgets.QWidget()
        right.setObjectName("right_panel")
        right.setMinimumWidth(260)
        right.setMaximumWidth(320)
        right_layout = QtWidgets.QVBoxLayout(right)
        right_layout.setContentsMargins(SeaSyncTheme.SPACING_MD, SeaSyncTheme.SPACING_MD,
                                         SeaSyncTheme.SPACING_MD, SeaSyncTheme.SPACING_MD)
        right_layout.setSpacing(SeaSyncTheme.SPACING_SM)

        # 标题栏
        right_header = QtWidgets.QLabel("参数配置")
        right_header.setStyleSheet(f"font-size: {SeaSyncTheme.FONT_SIZE_TITLE}px; font-weight: bold;")
        right_layout.addWidget(right_header)

        param_groups = [
            ("跟踪器", [
                ("gate_distance_m", "门控距离(m)", 50, 5000, 500),
                ("max_coast_steps", "最大外推(帧)", 2, 200, 5),
                ("min_track_points", "最小轨迹点数", 2, 20, 3),
                ("max_speed_kn", "最大航速(节)", 1, 60, 30),
            ]),
            ("关联参数", [
                ("distance_threshold", "关联阈值(m)", 50, 5000, 500),
                ("min_confidence", "最低置信度(0.00~1.00)", 0, 100, 60),
                ("time_window_base", "时间窗口(s)", 1, 60, 5),
                ("time_window_tolerance", "时间容差(s)", 0, 10, 2),
            ]),
        ]
        _DROPDOWN_OPTIONS = {
            "distance_threshold": ["50", "100", "200", "500", "1000", "2000", "5000"],
            "time_window_base": ["1", "2", "5", "10", "20", "30", "60"],
            "time_window_tolerance": ["0", "1", "2", "5", "10"],
            "max_speed_kn": ["5", "10", "15", "20", "30", "40", "60"],
            "gate_distance_m": ["50", "100", "200", "500", "1000", "2000", "5000"],
            "max_coast_steps": ["1", "2", "3", "5", "10", "20", "50", "100", "200"],
            "min_track_points": ["2", "3", "5", "10", "20"],
        }
        self._param_widgets = {}
        for group_name, items in param_groups:
            grp = QtWidgets.QGroupBox(group_name)
            grp_layout = QtWidgets.QVBoxLayout(grp)
            grp_layout.setSpacing(SeaSyncTheme.SPACING_SM)
            for key, label, min_v, max_v, default in items:
                h = QtWidgets.QHBoxLayout()
                lbl = QtWidgets.QLabel(label)
                h.addWidget(lbl)
                if key in _DROPDOWN_OPTIONS:
                    combo = QtWidgets.QComboBox()
                    options = _DROPDOWN_OPTIONS[key]
                    combo.addItems(options)
                    idx = 0
                    for i, opt in enumerate(options):
                        if int(opt) >= default:
                            idx = i; break
                    combo.setCurrentIndex(idx)
                    combo.currentTextChanged.connect(
                        lambda txt, k=key: self._on_param_change(k, int(txt), None))
                    h.addWidget(combo)
                    self._param_widgets[key] = combo
                else:
                    slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
                    slider.setRange(min_v, max_v)
                    slider.setValue(default)
                    if key == "min_confidence":
                        val_label = QtWidgets.QLabel(f"{default/100:.2f}")
                    else:
                        val_label = QtWidgets.QLabel(str(default))
                    val_label.setStyleSheet("font-weight: 500; min-width: 40px;")
                    slider.valueChanged.connect(
                        lambda v, k=key, vl=val_label: self._on_param_change(k, v, vl))
                    h.addWidget(slider)
                    h.addWidget(val_label)
                    self._param_widgets[key] = slider
                self._params[key] = float(default) / 100 if key == "min_confidence" else float(default)
                grp_layout.addLayout(h)
            if group_name == "关联参数":
                self._mahalanobis_cb = QtWidgets.QCheckBox("使用马氏距离(KF)")
                self._mahalanobis_cb.setChecked(True)
                self._mahalanobis_cb.toggled.connect(
                    lambda checked: self._on_param_change("use_mahalanobis", checked, None))
                grp_layout.addWidget(self._mahalanobis_cb)
                self._params["use_mahalanobis"] = True
            right_layout.addWidget(grp)

        right_layout.addStretch()

        # 运行按钮
        self._btn_run = QtWidgets.QPushButton("▶ 运行流程")
        self._btn_run.setMinimumHeight(40)
        self._btn_run.clicked.connect(self._on_run_pipeline)
        self._set_btn_red()
        right_layout.addWidget(self._btn_run)

        self._btn_ppi = QtWidgets.QPushButton("📡 PPI 显示")
        self._btn_ppi.setMinimumHeight(36)
        self._btn_ppi.setObjectName("secondary")
        self._btn_ppi.clicked.connect(self._on_ppi_view)
        right_layout.addWidget(self._btn_ppi)

        # 时间轴控件
        self._time_group = QtWidgets.QGroupBox("时间轴")
        self._time_group.setVisible(False)
        tl = QtWidgets.QVBoxLayout(self._time_group)
        self._time_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self._time_slider.setRange(0, 100)
        self._time_slider.setValue(0)
        self._time_slider.valueChanged.connect(self._on_time_slider_change)
        tl.addWidget(self._time_slider)
        hb = QtWidgets.QHBoxLayout()
        self._btn_play = QtWidgets.QPushButton("▶ 播放")
        self._btn_play.setCheckable(True)
        self._btn_play.toggled.connect(self._on_play_toggle)
        self._time_label = QtWidgets.QLabel("--")
        self._time_label.setStyleSheet("font-family: monospace;")
        hb.addWidget(self._btn_play)
        hb.addWidget(self._time_label)
        hb.addStretch()
        tl.addLayout(hb)
        right_layout.addWidget(self._time_group)

        # 布局
        h_splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        h_splitter.setHandleWidth(2)
        h_splitter.addWidget(left)
        h_splitter.addWidget(center)
        h_splitter.addWidget(right)
        h_splitter.setStretchFactor(0, 1)
        h_splitter.setStretchFactor(1, 5)
        h_splitter.setStretchFactor(2, 1)
        top_layout.addWidget(h_splitter)
        outer_splitter.addWidget(top_widget)

        # 底部日志
        bottom = QtWidgets.QWidget()
        bottom.setObjectName("bottom_panel")
        bottom_layout = QtWidgets.QVBoxLayout(bottom)
        bottom_layout.setContentsMargins(SeaSyncTheme.SPACING_MD, SeaSyncTheme.SPACING_SM,
                                          SeaSyncTheme.SPACING_MD, SeaSyncTheme.SPACING_SM)
        bottom_layout.setSpacing(SeaSyncTheme.SPACING_SM)

        log_header = QtWidgets.QLabel("输出日志")
        log_header.setStyleSheet(f"font-size: {SeaSyncTheme.FONT_SIZE_LARGE}px; font-weight: bold;")
        bottom_layout.addWidget(log_header)

        self._log_output = QtWidgets.QTextEdit()
        self._log_output.setReadOnly(True)
        self._log_output.setMaximumHeight(160)
        self._log_output.setStyleSheet(
            "font: 13px 'Consolas', 'Courier New', monospace;"
        )
        bottom_layout.addWidget(self._log_output)
        outer_splitter.addWidget(bottom)
        outer_splitter.setStretchFactor(0, 5)
        outer_splitter.setStretchFactor(1, 1)

        self.statusBar().showMessage("就绪")
        self._log("SeaSync V2.2 已启动 — 添加数据源后点击运行流程")

    # ── 按钮状态 ──

    def _set_btn_red(self) -> None:
        self._btn_run.setText("▶ 运行流程")
        self._btn_run.setEnabled(True)

    def _set_btn_green(self) -> None:
        self._btn_run.setText("▶▶ 运行中...")

    def _set_btn_done(self) -> None:
        self._btn_run.setText("✓ 完成")
        self._btn_run.setEnabled(True)
        QtCore.QTimer.singleShot(1200, self._set_btn_red)

    # ── 日志 ──

    def _log(self, msg: str) -> None:
        from datetime import datetime
        self._log_output.append(f"[{datetime.now():%H:%M:%S}] {msg}")
        from ..core.logger import log
        log.info("%s", msg)

    # ── 处理状态 ──

    def _set_processing(self, processing: bool, message: str = "") -> None:
        self._processing = processing
        if processing:
            for btn in self.findChildren(QtWidgets.QPushButton):
                if btn != self._btn_run:
                    btn.setEnabled(False)
            self._set_btn_green()
            if message:
                self.statusBar().showMessage(f"⏳ {message}...")
        else:
            for btn in self.findChildren(QtWidgets.QPushButton):
                btn.setEnabled(True)
            self._set_btn_done()
            self.statusBar().showMessage("✓ 完成", 3000)

    def _on_worker_error(self, err_msg: str) -> None:
        self._log(f"✗ {err_msg}")
        self._worker = None
        self._set_processing(False)

    def _cleanup_temp_files(self) -> None:
        for tp in list(self._temp_files):
            try:
                if os.path.exists(tp):
                    os.remove(tp)
                    self._log(f"  → 清理临时文件: {os.path.basename(tp)}")
            except Exception:
                pass
        self._temp_files.clear()

    # ── 参数 ──

    def _on_param_change(self, key: str, value, label: QtWidgets.QLabel = None) -> None:
        if key == "min_confidence":
            self._params[key] = value / 100.0
            if label:
                label.setText(f"{value / 100:.2f}")
        elif key == "use_mahalanobis":
            self._params[key] = bool(value)
        else:
            self._params[key] = float(value)
            if label:
                label.setText(str(value))

    # ── 文件操作 ──

    def _on_add_file(self) -> None:
        files, _ = QtWidgets.QFileDialog.getOpenFileNames(
            self, "选择数据文件", "",
            "支持格式 (*.csv *.dat *.mat *.nmea *.gpx *.kml)"
        )
        if not files:
            return
        from ..adapters.import_manager import _auto_detect_type
        from ..visualization.draw_command import clear_sensor_color_cache
        clear_sensor_color_cache()
        loaded = 0
        for f in files:
            try:
                if not self.pipeline:
                    continue
                size_mb = os.path.getsize(f) / 1e6
                if size_mb > 50:
                    self._log(f"⏳ {os.path.basename(f)} ({size_mb:.0f}MB) 大文件，自动限制记录数...")
                stype = _auto_detect_type(f)
                QtWidgets.QApplication.processEvents()
                sid = self.pipeline.add_source(f, source_type=stype)
                QtWidgets.QApplication.processEvents()
                rec_count = len(self.pipeline.get_records(sid))
                display = f"{os.path.basename(f)} [{sid[:10]}·{stype}]"
                self._source_map[display] = (sid, stype)
                self._source_list.addItem(display)
                self._log(f"✓ {os.path.basename(f)} → {stype} ({rec_count}条)")
                loaded += 1
                QtWidgets.QApplication.processEvents()
            except Exception as e:
                self._log(f"✗ {os.path.basename(f)}: {e}")
        if loaded:
            self.update_view()

    def _on_remove_file(self) -> None:
        cur = self._source_list.currentItem()
        if cur and self.pipeline:
            text = cur.text()
            if text in self._source_map:
                sid = self._source_map[text][0]
                try:
                    self.pipeline._im.remove(sid)
                except Exception:
                    pass
                del self._source_map[text]
            self._source_list.takeItem(self._source_list.row(cur))
            from ..visualization.draw_command import clear_sensor_color_cache
            clear_sensor_color_cache()
            self.update_view()

    # ── 运行流程 ──

    def _on_run_pipeline(self) -> None:
        if not self.pipeline:
            self._log("未配置处理管线"); return
        all_sids = self._get_all_source_ids()
        if len(all_sids) < 2:
            self._log("需要至少 2 个数据源"); return
        self._cleanup_temp_files()
        self._set_processing(True, "正在运行流程")
        self._worker = WorkerThread(
            task_type="run_pipeline",
            pipeline=self.pipeline,
            all_sids=all_sids,
            params=self._params,
        )
        self._worker.finished.connect(self._on_pipeline_finished)
        self._worker.error.connect(self._on_worker_error)
        self._worker.progress.connect(self._log)
        self._worker.finished.connect(self._worker.deleteLater)
        self._worker.error.connect(lambda: self._worker and self._worker.deleteLater())
        self._worker.start()

    def _on_pipeline_finished(self, steps: dict) -> None:
        try:
            n_events = steps.get("events", {}).get("n_events", 0)
            n_tracks = steps.get("tracks", {}).get("n_tracks", 0)
            origin = steps.get('origin', (None, None))
            if "associations" in steps and steps["associations"]:
                total_pairs = sum(info["n_pairs"] for info in steps["associations"].values())
                self._log(f"流程完成: N源关联{total_pairs}对, 事件{n_events}个, 轨迹{n_tracks}条")
                for pair_key, info in steps["associations"].items():
                    if info["n_pairs"] > 0:
                        self._log(f"  ✅ {pair_key}: {info['n_pairs']}对 (质量={info['quality']:.3f})")
            else:
                assoc = steps.get("association", {})
                self._log(f"流程完成: 关联{assoc.get('n_pairs', 0)}对, 事件{n_events}个, 轨迹{n_tracks}条")
            if origin[0]:
                self._log(f"  雷达原点: {origin[0]:.4f}, {origin[1]:.4f}")
            if _HAVE_MPL and self.pipeline:
                all_sids = self._get_all_source_ids()
                radar_sids = [s for s in all_sids if self.pipeline.get_source_type(s) == "radar"]
                ais_sids = [s for s in all_sids if self.pipeline.get_source_type(s) == "ais"]
                if not radar_sids:
                    radar_sids = all_sids[:1]
                if not ais_sids:
                    ais_sids = all_sids[1:2]
                main_radar = radar_sids[0] if radar_sids else None
                if main_radar:
                    radar_recs = self.pipeline.get_records(main_radar)
                    all_ais_recs = []
                    for sid in ais_sids:
                        all_ais_recs.extend(self.pipeline.get_records(sid))
                    from ..core.data_models import AssociationResult
                    merged_pairs = []
                    assocs = steps.get("associations", {})
                    for pair_key, info in assocs.items():
                        r = info.get("result") if isinstance(info, dict) else None
                        from ..core.data_models import AssociationResult as _AR
                        if isinstance(r, _AR):
                            merged_pairs.extend(r.pairs)
                    if merged_pairs:
                        merged_result = AssociationResult(pairs=merged_pairs)
                    else:
                        result = steps.get("association", {}).get("result")
                        merged_result = result if result else self.pipeline.associate(main_radar, ais_sids[0] if ais_sids else "")
                    # 如果没有关联结果，回退到显示多源数据视图
                    if merged_result and hasattr(merged_result, 'pairs') and len(merged_result.pairs) > 0:
                        self._canvas.render_association(
                            radar_recs, all_ais_recs, merged_result,
                            title=f"N 源关联: {len(merged_result.pairs)} 对, {len(ais_sids)} 个 AIS"
                        )
                    else:
                        self._log("未找到关联对，显示多源数据视图")
                        self.update_view()
                else:
                    self.update_view()
            else:
                self.update_view()
        finally:
            self._worker = None
            self._set_processing(False)
            self._cleanup_temp_files()

    # ── 多源关联 ──

    def _on_multi_associate(self) -> None:
        if not self.pipeline:
            self._log("未配置处理管线"); return
        all_sids = self._get_all_source_ids()
        if len(all_sids) < 2:
            self._log("需要至少 2 个数据源"); return
        self._set_processing(True, "正在多源关联")
        self._worker = WorkerThread(
            task_type="multi_associate",
            pipeline=self.pipeline,
            all_sids=all_sids,
        )
        self._worker.finished.connect(self._on_multi_finished)
        self._worker.error.connect(self._on_worker_error)
        self._worker.progress.connect(self._log)
        self._worker.finished.connect(self._worker.deleteLater)
        self._worker.error.connect(lambda: self._worker and self._worker.deleteLater())
        self._worker.start()

    def _on_multi_finished(self, results: dict) -> None:
        try:
            if not results:
                self._log("无关联结果"); return
            for (s1, s2), result in results.items():
                self._log(f"  {s1[:8]} ↔ {s2[:8]}: {len(result.pairs)}对, 质量={result.total_quality:.3f}")
            self._log(f"多源关联完成: {len(results)}组")
        finally:
            self._worker = None
            self._set_processing(False)
            self._cleanup_temp_files()
            self.update_view()

    # ── 配置 ──

    def _on_open_config(self) -> None:
        from .config_widget import ConfigEditorWidget
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle("数据配置编辑器")
        dialog.setMinimumSize(700, 600)
        layout = QtWidgets.QVBoxLayout(dialog)
        editor = ConfigEditorWidget(parent=dialog)
        layout.addWidget(editor)
        dialog.exec_()

    # ── 导出 ──

    def _on_export_report(self) -> None:
        from ..report import ReportGenerator
        has_docx = False
        try:
            import docx
            has_docx = True
        except ImportError:
            pass
        filters = "Markdown (*.md)"
        if has_docx:
            filters = "Word 文档 (*.docx);;Markdown (*.md)"
        path, selected_filter = QtWidgets.QFileDialog.getSaveFileName(
            self, "导出报告", "", filters)
        if not path:
            return
        try:
            all_sids = self._get_all_source_ids()
            if not all_sids:
                QtWidgets.QMessageBox.warning(self, "无数据源", "请先导入数据源后再导出报告。")
                return
            if not self.pipeline or not self.pipeline._im._records:
                QtWidgets.QMessageBox.warning(self, "无数据", "请先导入数据并运行流程后再导出报告。")
                return
            assoc_result = None
            if len(all_sids) >= 2 and self.pipeline:
                try:
                    assocs = self.pipeline._assoc.associate_multi({
                        sid: self.pipeline.get_records(sid) for sid in all_sids
                    })
                    for key, result in assocs.items():
                        if result.pairs:
                            assoc_result = result
                            break
                    if assoc_result is None:
                        sid_a, sid_b = all_sids[0], all_sids[1]
                        label_a = self.pipeline.get_source_type(sid_a)
                        label_b = self.pipeline.get_source_type(sid_b)
                        assoc_result = self.pipeline._assoc.associate(
                            self.pipeline.get_records(sid_a),
                            self.pipeline.get_records(sid_b),
                            label_a=label_a, label_b=label_b,
                        )
                except Exception as e:
                    self._log(f"⚠ 获取关联结果失败: {e}")
            events = []
            if hasattr(self.pipeline, '_events') and self.pipeline._events:
                events = self.pipeline._events
            rg = ReportGenerator(output_dir=os.path.dirname(path) or os.getcwd())
            generated_path = rg.generate(
                project_name="SeaSync 处理报告",
                assoc_result=assoc_result,
                events=events,
                pipeline=self.pipeline,
                summary={
                    "数据源数量": len(all_sids),
                    "数据源列表": ", ".join(all_sids),
                    "参数": str(self._params),
                },
            )
            if generated_path and os.path.exists(generated_path):
                import shutil
                if generated_path != path:
                    shutil.copy2(generated_path, path)
                    try:
                        os.remove(generated_path)
                    except Exception:
                        pass
                self._log(f" 报告已导出: {os.path.basename(path)}")
                if assoc_result:
                    self._log(f"   关联对: {assoc_result.n_pairs}, 质量: {assoc_result.total_quality:.3f}")
                if events:
                    self._log(f"   事件: {len(events)} 项")
                QtWidgets.QMessageBox.information(
                    self, "导出成功",
                    f"报告已导出到:\n{path}\n\n"
                    f"关联对: {assoc_result.n_pairs if assoc_result else 0}\n"
                    f"事件: {len(events)} 项"
                )
            else:
                QtWidgets.QMessageBox.warning(
                    self, "导出失败",
                    "报告生成失败，请检查 python-docx 是否已安装。\n"
                    "已降级导出为 Markdown 格式。"
                )
        except Exception as e:
            self._log(f"✗ 报告导出失败: {e}")
            QtWidgets.QMessageBox.critical(
                self, "错误",
                f"报告导出失败:\n{e}"
            )

    def _on_export_kml(self) -> None:
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "导出 KML 轨迹", "sea_trial.kml", "KML (*.kml)")
        if not path or not self.pipeline:
            return
        try:
            from ..core.kml_export import export_kml
            trajectories: Dict[str, list] = {}
            for display, (sid, stype) in self._source_map.items():
                try:
                    recs = self.pipeline.get_records(sid)
                    trajectories[display] = recs
                except Exception:
                    pass
            olat = getattr(self.pipeline, '_origin_lat', None)
            olon = getattr(self.pipeline, '_origin_lon', None)
            export_kml(path, trajectories,
                       origin_lat=olat, origin_lon=olon,
                       title=f"SeaSync - {display}")
            self._log(f"KML已导出: {path} ({len(trajectories)}条轨迹)")
            self.statusBar().showMessage(f"KML: {path}", 5000)
        except Exception as e:
            self._log(f"KML导出失败: {e}")

    def _on_export_result(self) -> None:
        import json, csv
        path, fmt = QtWidgets.QFileDialog.getSaveFileName(
            self, "导出关联结果", "association_result.csv",
            "CSV (*.csv);;JSON (*.json)")
        if not path or not self.pipeline:
            return
        try:
            all_sids = [info[0] for info in self._source_map.values()]
            if len(all_sids) < 2:
                self._log("需要至少2个数据源才能导出")
                return
            results = self.pipeline.associate_multi(all_sids)
            is_json = path.lower().endswith('.json')
            if is_json:
                data = {}
                for (s1, s2), r in results.items():
                    data[f"{s1}_{s2}"] = {
                        "n_pairs": len(r.pairs),
                        "quality": r.total_quality,
                        "pairs": [{
                            "source1_id": p.source1_id,
                            "source2_id": p.source2_id,
                            "source1_label": p.source1_label,
                            "source2_label": p.source2_label,
                            "confidence": p.confidence,
                            "method": p.method,
                        } for p in r.pairs],
                    }
                with open(path, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
            else:
                with open(path, 'w', newline='', encoding='utf-8-sig') as f:
                    w = csv.writer(f)
                    w.writerow(["source1", "source2", "source1_id", "source2_id",
                                "confidence", "method", "quality"])
                    for (s1, s2), r in results.items():
                        for p in r.pairs:
                            w.writerow([s1, s2, p.source1_id, p.source2_id,
                                        f"{p.confidence:.4f}", p.method,
                                        f"{r.total_quality:.3f}"])
            self._log(f"关联结果已导出: {path}")
            self.statusBar().showMessage(f"已导出 {len(results)}组", 3000)
        except Exception as e:
            self._log(f"导出失败: {e}")

    # ── 视图 ──

    def update_view(self) -> None:
        if not _HAVE_MPL or not self.pipeline:
            self.statusBar().showMessage("视图已刷新")
            return
        sources = self.pipeline.list_sources()
        if not sources:
            self._canvas.clear()
            return
        try:
            all_recs = self.pipeline._im.load_all()
            scene = DrawScene(viewport=(0, 0, 1000, 1000), title="多源数据视图")
            all_xs, all_ys = [], []
            use_latlon = False
            for sid, recs in all_recs.items():
                with_lat = sum(1 for r in recs if r.lat is not None)
                if with_lat > 0:
                    use_latlon = True
                    break
            for sid, recs in all_recs.items():
                if len(recs) > 5000:
                    import random
                    random.seed(42)
                    recs = random.sample(recs, 5000)
                stype = "unknown"
                for display, (sid2, st) in self._source_map.items():
                    if sid2 == sid:
                        stype = st; break
                if stype == "unknown":
                    try:
                        stype = self.pipeline._im._adapters[sid].metadata().type
                    except Exception:
                        pass
                color = get_sensor_color(stype, sid)
                scene.legend_items.append((f"{stype}[{sid[:12]}]", color))
                for r in recs:
                    if use_latlon and r.lat is not None and r.lon is not None:
                        x, y = float(r.lon), float(r.lat)
                    elif r.x is not None and r.y is not None:
                        x, y = float(r.x), float(r.y)
                    else:
                        continue
                    scene.add(DrawCommand(DrawType.POINT, points=[(x, y)],
                            color=color, track_id=r.track_id, source_id=sid, z_order=1))
                    all_xs.append(x); all_ys.append(y)
            if all_xs and all_ys:
                min_x, max_x = min(all_xs), max(all_xs)
                min_y, max_y = min(all_ys), max(all_ys)
                # 添加 10% 边距，避免数据贴边；如果数据范围为0，设置最小范围
                x_pad = max((max_x - min_x) * 0.1, 0.001)
                y_pad = max((max_y - min_y) * 0.1, 0.001)
                scene.viewport = (min_x - x_pad, min_y - y_pad, max_x + x_pad, max_y + y_pad)
            self._canvas.render_scene(scene, "多源数据视图",
                                      coord_mode="latlon" if use_latlon else "xy")
        except Exception as e:
            self._canvas.clear()
            self._log(f"刷新视图失败: {e}")

    # ── PPI ──

    def _on_ppi_view(self) -> None:
        if not _HAVE_MPL or not self.pipeline:
            return
        radar_sid = self._find_source_by_type("radar")
        if not radar_sid:
            self._log("PPI 显示需要至少一个雷达数据源")
            return
        radar_recs = self.pipeline.get_records(radar_sid)
        ais_recs = []
        for _, (sid, st) in self._source_map.items():
            if st == "ais":
                ais_recs.extend(self.pipeline.get_records(sid))
        origin_lat = getattr(self.pipeline, '_origin_lat', None)
        origin_lon = getattr(self.pipeline, '_origin_lon', None)
        if origin_lat is None and radar_sid is not None:
            try:
                adapter = self.pipeline._im.get_adapter(radar_sid)
                if hasattr(adapter, '_origin_lat') and adapter._origin_lat is not None:
                    origin_lat = adapter._origin_lat
                    origin_lon = adapter._origin_lon
            except Exception:
                pass
        if origin_lat is None:
            origin_lat, origin_lon = 37.53, 121.42
        try:
            assoc_result = None
            try:
                ais_sid = self._find_source_by_type("ais")
                if radar_sid and ais_sid:
                    assoc_result = self.pipeline.associate(radar_sid, ais_sid)
            except Exception:
                pass
            self._log(f"PPI: 雷达源={radar_sid}, AIS源列表={[(sid,st) for _, (sid,st) in self._source_map.items() if st=='ais']}")
            self._log(f"PPI: AIS记录数={len(ais_recs)}, 有lat={sum(1 for r in ais_recs if r.lat is not None)}")
            self._canvas.render_ppi(
                radar_recs, ais_recs,
                origin_lat=origin_lat, origin_lon=origin_lon,
                max_range_km=30.0,
                assoc_result=assoc_result,
                title="SeaSync 雷达 PPI 显示",
            )
            self._log(f"PPI 显示: {len(radar_recs)}雷达记录, {len(ais_recs)}AIS记录")
            self.statusBar().showMessage(f"📡 PPI 视图 (原点: {origin_lat:.4f}, {origin_lon:.4f})")
            radar_times = [r.time for r in radar_recs if r.time is not None]
            if radar_times:
                t0, t1 = min(radar_times), max(radar_times)
                self._ppi_time_range = (t0, t1)
                self._ppi_frame_data = {
                    "radar_recs": radar_recs, "ais_recs": ais_recs,
                    "origin_lat": origin_lat, "origin_lon": origin_lon,
                    "assoc_result": assoc_result,
                }
                self._time_slider.setValue(0)
                self._time_group.setVisible(True)
                self._time_label.setText(f"t={t0:.0f} / {t1-t0:.0f}s")
        except Exception as e:
            self._log(f"✗ PPI 渲染失败: {e}")
            import traceback
            self._log(traceback.format_exc()[-200:])
            self.statusBar().showMessage("⚠️ PPI 渲染出错，查看日志")

    def _on_time_slider_change(self, pos: int) -> None:
        data = self._ppi_frame_data
        if not data:
            return
        t0, t1 = self._ppi_time_range
        window_s = max((t1 - t0) * 0.05, 5.0)
        frac = pos / 100.0
        t_center = t0 + frac * (t1 - t0)
        t_win = (t_center - window_s / 2, t_center + window_s / 2)
        self._canvas.render_ppi_frame(
            data["radar_recs"], data["ais_recs"],
            origin_lat=data["origin_lat"], origin_lon=data["origin_lon"],
            assoc_result=data["assoc_result"],
            time_range=t_win,
            title="SeaSync PPI 逐帧",
        )
        self._time_label.setText(f"t={t_center:.0f} / {t1-t0:.0f}s")

    def _on_play_toggle(self, checked: bool) -> None:
        if checked:
            self._btn_play.setText("⏸ 暂停")
            self._play_timer.start()
        else:
            self._btn_play.setText("▶ 播放")
            self._play_timer.stop()

    def _on_play_step(self) -> None:
        v = self._time_slider.value()
        if v >= self._time_slider.maximum():
            self._time_slider.setValue(0)
        else:
            self._time_slider.setValue(v + 2)

    def _get_selected_source_ids(self) -> List[str]:
        ids = []
        for item in self._source_list.selectedItems():
            if item.text() in self._source_map:
                ids.append(self._source_map[item.text()][0])
        return ids

    def _get_all_source_ids(self) -> List[str]:
        return [info[0] for info in self._source_map.values()]

    def _find_source_by_type(self, stype: str) -> Optional[str]:
        for display, (sid, st) in self._source_map.items():
            if st == stype:
                return sid
        return None


def launch_gui() -> None:
    """启动 SeaSync 图形界面。"""
    import sys as _sys
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication(_sys.argv)
    # 应用主题
    SeaSyncTheme.apply_global(app)
    win = SeaSyncMainWindow()
    win.show()
    _sys.exit(app.exec_())


if __name__ == "__main__":
    launch_gui()
