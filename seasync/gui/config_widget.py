"""
SeaSync V2.2 ConfigEditorWidget — GUI 配置编辑组件

提供可视化配置编辑器，支持：
- 文件选择 + 自动格式检测
- 模板推荐与加载
- 列映射编辑器
- 单位转换表
- 高级解析参数
- 配置模板的保存/应用/取消
"""

# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 荣火
from __future__ import annotations
import os
from typing import Optional, List, Dict, Any

from PyQt5 import QtWidgets, QtCore

from ..core.config_manager import (
    ConfigManager,
    DataConfig,
    ColumnMapping,
    UnitConversion,
    TimeFormat,
)
from ..core.format_detector import SmartFormatDetector, DetectedFormat


class ConfigEditorWidget(QtWidgets.QWidget):
    """配置编辑器组件，集成格式检测与模板管理。"""

    # ── 信号 ─────────────────────────────────────────────────
    config_applied = QtCore.pyqtSignal(object)     # DataConfig
    config_saved = QtCore.pyqtSignal(str)          # 模板路径
    config_cancelled = QtCore.pyqtSignal()
    file_selected = QtCore.pyqtSignal(str)         # 文件路径

    def __init__(self, config_manager: Optional[ConfigManager] = None,
                 detector: Optional[SmartFormatDetector] = None,
                 parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self._cm = config_manager or ConfigManager()
        self._detector = detector or SmartFormatDetector()
        self._current_file: str = ""
        self._current_config: Optional[DataConfig] = None
        self._last_detection: Optional[DetectedFormat] = None
        self._init_ui()

    def _init_ui(self) -> None:
        """构建界面布局。"""
        main_layout = QtWidgets.QVBoxLayout(self)
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(8)

        # ── 文件选择区 ────────────────────────────────────
        file_group = QtWidgets.QGroupBox("文件选择")
        file_layout = QtWidgets.QHBoxLayout(file_group)
        self._file_path_edit = QtWidgets.QLineEdit()
        self._file_path_edit.setPlaceholderText("选择数据文件...")
        self._file_path_edit.setReadOnly(True)
        btn_browse = QtWidgets.QPushButton("浏览...")
        btn_browse.clicked.connect(self._on_browse)
        btn_detect = QtWidgets.QPushButton("自动检测")
        btn_detect.clicked.connect(self._on_detect)
        file_layout.addWidget(self._file_path_edit, 1)
        file_layout.addWidget(btn_browse)
        file_layout.addWidget(btn_detect)
        main_layout.addWidget(file_group)

        # ── 检测结果信息 ───────────────────────────────────
        self._info_label = QtWidgets.QLabel("未选择文件")
        self._info_label.setStyleSheet("padding: 4px;")
        main_layout.addWidget(self._info_label)

        # ── 模板推荐区 ────────────────────────────────────
        template_group = QtWidgets.QGroupBox("模板推荐")
        template_layout = QtWidgets.QHBoxLayout(template_group)
        self._template_combo = QtWidgets.QComboBox()
        self._template_combo.setMinimumWidth(200)
        self._template_combo.setToolTip("根据文件特征推荐的配置模板")
        btn_apply_template = QtWidgets.QPushButton("应用模板")
        btn_apply_template.clicked.connect(self._on_apply_template)
        btn_refresh = QtWidgets.QPushButton("刷新列表")
        btn_refresh.clicked.connect(self._refresh_template_list)
        template_layout.addWidget(self._template_combo, 1)
        template_layout.addWidget(btn_apply_template)
        template_layout.addWidget(btn_refresh)
        main_layout.addWidget(template_group)

        # ── 列映射编辑器 ──────────────────────────────────
        map_group = QtWidgets.QGroupBox("列映射（源列名 → 标准列名）")
        map_layout = QtWidgets.QVBoxLayout(map_group)
        self._col_table = QtWidgets.QTableWidget(0, 3)
        self._col_table.setHorizontalHeaderLabels(["源列名", "标准列名", "数据类型"])
        self._col_table.horizontalHeader().setStretchLastSection(True)
        self._col_table.horizontalHeader().setSectionResizeMode(
            0, QtWidgets.QHeaderView.Stretch)
        self._col_table.horizontalHeader().setSectionResizeMode(
            1, QtWidgets.QHeaderView.Stretch)
        map_layout.addWidget(self._col_table)
        btn_row_layout = QtWidgets.QHBoxLayout()
        btn_add_row = QtWidgets.QPushButton("+ 添加行")
        btn_add_row.clicked.connect(lambda: self._add_table_row(self._col_table))
        btn_del_row = QtWidgets.QPushButton("− 删除行")
        btn_del_row.clicked.connect(
            lambda: self._remove_table_row(self._col_table))
        btn_row_layout.addWidget(btn_add_row)
        btn_row_layout.addWidget(btn_del_row)
        btn_row_layout.addStretch()
        map_layout.addLayout(btn_row_layout)
        main_layout.addWidget(map_group)

        # ── 单位转换表 ────────────────────────────────────
        unit_group = QtWidgets.QGroupBox("单位转换（列 → 原单位 → 目标单位）")
        unit_layout = QtWidgets.QVBoxLayout(unit_group)
        self._unit_table = QtWidgets.QTableWidget(0, 3)
        self._unit_table.setHorizontalHeaderLabels(["列名", "原单位", "目标单位"])
        self._unit_table.horizontalHeader().setStretchLastSection(True)
        self._unit_table.horizontalHeader().setSectionResizeMode(
            0, QtWidgets.QHeaderView.Stretch)
        self._unit_table.horizontalHeader().setSectionResizeMode(
            1, QtWidgets.QHeaderView.Stretch)
        unit_layout.addWidget(self._unit_table)
        btn_unit_layout = QtWidgets.QHBoxLayout()
        btn_add_unit = QtWidgets.QPushButton("+ 添加行")
        btn_add_unit.clicked.connect(lambda: self._add_table_row(self._unit_table))
        btn_del_unit = QtWidgets.QPushButton("− 删除行")
        btn_del_unit.clicked.connect(
            lambda: self._remove_table_row(self._unit_table))
        btn_unit_layout.addWidget(btn_add_unit)
        btn_unit_layout.addWidget(btn_del_unit)
        btn_unit_layout.addStretch()
        unit_layout.addLayout(btn_unit_layout)
        main_layout.addWidget(unit_group)

        # ── 高级设置 ──────────────────────────────────────
        adv_group = QtWidgets.QGroupBox("高级解析设置")
        adv_layout = QtWidgets.QGridLayout(adv_group)
        adv_layout.setSpacing(6)

        self._encoding_combo = QtWidgets.QComboBox()
        self._encoding_combo.addItems(
            ["utf-8", "utf-8-sig", "gbk", "gb2312", "gb18030", "latin-1", "auto"])
        self._encoding_combo.setCurrentText("utf-8")
        adv_layout.addWidget(QtWidgets.QLabel("编码:"), 0, 0)
        adv_layout.addWidget(self._encoding_combo, 0, 1)

        self._separator_combo = QtWidgets.QComboBox()
        self._separator_combo.addItems([", (逗号)", "\\t (制表符)", "; (分号)", "| (管道)", " (空格)", "auto"])
        self._separator_combo.setCurrentText(", (逗号)")
        adv_layout.addWidget(QtWidgets.QLabel("分隔符:"), 0, 2)
        adv_layout.addWidget(self._separator_combo, 0, 3)

        self._header_rows_spin = QtWidgets.QSpinBox()
        self._header_rows_spin.setRange(0, 10)
        self._header_rows_spin.setValue(1)
        adv_layout.addWidget(QtWidgets.QLabel("表头行数:"), 1, 0)
        adv_layout.addWidget(self._header_rows_spin, 1, 1)

        self._skip_rows_spin = QtWidgets.QSpinBox()
        self._skip_rows_spin.setRange(0, 1000)
        self._skip_rows_spin.setValue(0)
        adv_layout.addWidget(QtWidgets.QLabel("跳过行数:"), 1, 2)
        adv_layout.addWidget(self._skip_rows_spin, 1, 3)

        self._time_format_edit = QtWidgets.QLineEdit("auto")
        self._time_format_edit.setToolTip(
            "时间格式，如 %%Y-%%m-%%d %%H:%%M:%%S，或 auto 自动检测")
        adv_layout.addWidget(QtWidgets.QLabel("时间格式:"), 2, 0)
        adv_layout.addWidget(self._time_format_edit, 2, 1, 1, 3)

        main_layout.addWidget(adv_group)

        # ── 操作按钮 ──────────────────────────────────────
        btn_layout = QtWidgets.QHBoxLayout()
        btn_save = QtWidgets.QPushButton("另存为模板")
        btn_save.clicked.connect(self._on_save_template)
        btn_apply = QtWidgets.QPushButton("✔ 应用配置")
        btn_apply.clicked.connect(self._on_apply)
        btn_cancel = QtWidgets.QPushButton("取消")
        btn_cancel.clicked.connect(self._on_cancel)

        btn_layout.addWidget(btn_save)
        btn_layout.addStretch()
        btn_layout.addWidget(btn_apply)
        btn_layout.addWidget(btn_cancel)
        main_layout.addLayout(btn_layout)

        # 初始刷新模板列表
        self._refresh_template_list()

    # ── 文件选择与检测 ──────────────────────────────────────

    def _on_browse(self) -> None:
        """打开文件选择对话框。"""
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "选择数据文件", "",
            "所有支持格式 (*.csv *.xlsx *.nmea *.gpx *.kml *.txt *.h5 *.mat);;"
            "CSV (*.csv);;Excel (*.xlsx);;NMEA (*.nmea);;"
            "GPX (*.gpx);;文本 (*.txt);;HDF5 (*.h5 *.hdf5);;MATLAB (*.mat)"
        )
        if path:
            self._load_file(path)

    def _load_file(self, file_path: str) -> None:
        """加载并检测文件。"""
        self._current_file = file_path
        self._file_path_edit.setText(file_path)
        self.file_selected.emit(file_path)

        # 自动检测
        self._on_detect()

    def _on_detect(self) -> None:
        """对当前选择的文件执行格式检测。"""
        if not self._current_file or not os.path.exists(self._current_file):
            self._info_label.setText("请先选择有效的数据文件")
            return

        try:
            result = self._detector.detect(self._current_file)
            self._last_detection = result

            # 更新信息标签
            info_parts = [
                f"格式: {result.extension_description}",
                f"编码: {result.encoding} (置信度 {result.encoding_confidence:.0%})",
                f"分隔符: '{result.separator}'",
                f"列数: {result.column_count}",
                f"行数: {result.total_rows}",
                f"类型: {result.suggested_source_type}",
            ]
            if result.is_binary:
                info_parts.insert(1, f"魔数: {result.magic_description}")
            self._info_label.setText(" | ".join(info_parts))

            # 更新高级设置
            if result.encoding:
                idx = self._encoding_combo.findText(result.encoding)
                if idx >= 0:
                    self._encoding_combo.setCurrentIndex(idx)
            sep_display = self._sep_to_display(result.separator)
            idx = self._separator_combo.findText(sep_display, QtCore.Qt.MatchStartsWith)
            if idx >= 0:
                self._separator_combo.setCurrentIndex(idx)
            self._header_rows_spin.setValue(result.header_rows)
            self._col_table.setRowCount(0)
            for c in result.column_names[:30]:  # 最多30列
                row = self._col_table.rowCount()
                self._col_table.insertRow(row)
                self._col_table.setItem(row, 0, QtWidgets.QTableWidgetItem(c))
                self._col_table.setItem(row, 1, QtWidgets.QTableWidgetItem(""))
                self._col_table.setItem(row, 2, QtWidgets.QTableWidgetItem("float"))

            # 刷新模板推荐
            suggested = self._detector.suggest_template(result)
            self._refresh_template_list(suggested)

        except Exception as e:
            self._info_label.setText(f"检测失败: {e}")

    def _sep_to_display(self, sep: str) -> str:
        """分隔符转显示文本。"""
        mapping = {
            ",": ", (逗号)",
            "\t": "\\t (制表符)",
            ";": "; (分号)",
            "|": "| (管道)",
            " ": " (空格)",
        }
        return mapping.get(sep, sep)

    # ── 模板管理 ────────────────────────────────────────────

    def _refresh_template_list(self, select_name: str = "") -> None:
        """刷新模板下拉列表，可选选中某个模板。"""
        current = self._template_combo.currentText()
        self._template_combo.clear()
        self._template_combo.addItem("— 手动配置 —")
        for name in self._cm.list_templates():
            self._template_combo.addItem(name)

        # 优先选中推荐的模板
        target = select_name or current
        if target:
            idx = self._template_combo.findText(target)
            if idx >= 0:
                self._template_combo.setCurrentIndex(idx)

    def _on_apply_template(self) -> None:
        """将选中的模板应用到当前UI配置。"""
        name = self._template_combo.currentText()
        if not name or name == "— 手动配置 —":
            return

        config = self._cm.load_template(name)
        if config is None:
            QtWidgets.QMessageBox.warning(self, "加载失败", f"无法加载模板: {name}")
            return

        self._apply_config_to_ui(config)
        self._current_config = config
        self._info_label.setText(f"已应用模板: {name}")

    def _apply_config_to_ui(self, config: DataConfig) -> None:
        """将 DataConfig 的数据填充到 UI 控件。"""
        # 编码
        idx = self._encoding_combo.findText(config.encoding)
        if idx >= 0:
            self._encoding_combo.setCurrentIndex(idx)

        # 分隔符
        if config.separator and config.separator != "auto":
            sep_display = self._sep_to_display(config.separator)
            idx = self._separator_combo.findText(sep_display, QtCore.Qt.MatchStartsWith)
            if idx >= 0:
                self._separator_combo.setCurrentIndex(idx)

        # 数值参数
        self._header_rows_spin.setValue(config.header_rows)
        self._skip_rows_spin.setValue(config.skip_rows)
        self._time_format_edit.setText(config.time_format.source_format)

        # 列映射
        self._col_table.setRowCount(0)
        for m in config.column_mappings:
            row = self._col_table.rowCount()
            self._col_table.insertRow(row)
            self._col_table.setItem(row, 0, QtWidgets.QTableWidgetItem(m.source_column))
            self._col_table.setItem(row, 1, QtWidgets.QTableWidgetItem(m.standard_column))
            self._col_table.setItem(row, 2, QtWidgets.QTableWidgetItem(m.data_type))

        # 单位转换
        self._unit_table.setRowCount(0)
        for u in config.unit_conversions:
            row = self._unit_table.rowCount()
            self._unit_table.insertRow(row)
            self._unit_table.setItem(row, 0, QtWidgets.QTableWidgetItem(u.column))
            self._unit_table.setItem(row, 1, QtWidgets.QTableWidgetItem(u.source_unit))
            self._unit_table.setItem(row, 2, QtWidgets.QTableWidgetItem(u.target_unit))

    # ── 从 UI 读取配置 ──────────────────────────────────────

    def _read_config_from_ui(self) -> DataConfig:
        """从 UI 控件读取当前配置为 DataConfig。"""
        # 列映射
        mappings = []
        for r in range(self._col_table.rowCount()):
            src_item = self._col_table.item(r, 0)
            std_item = self._col_table.item(r, 1)
            typ_item = self._col_table.item(r, 2)
            src = src_item.text().strip() if src_item else ""
            std = std_item.text().strip() if std_item else ""
            if src and std:
                mappings.append(ColumnMapping(
                    source_column=src,
                    standard_column=std,
                    data_type=typ_item.text().strip() if typ_item else "float",
                ))

        # 单位转换
        conversions = []
        for r in range(self._unit_table.rowCount()):
            col_item = self._unit_table.item(r, 0)
            src_item = self._unit_table.item(r, 1)
            tgt_item = self._unit_table.item(r, 2)
            col = col_item.text().strip() if col_item else ""
            src = src_item.text().strip() if src_item else ""
            tgt = tgt_item.text().strip() if tgt_item else ""
            if col and src and tgt:
                conversions.append(UnitConversion(
                    column=col, source_unit=src, target_unit=tgt,
                ))

        # 分隔符
        sep_text = self._separator_combo.currentText()
        if "tab" in sep_text.lower() or "\\t" in sep_text:
            separator = "\t"
        elif "逗号" in sep_text or "," in sep_text:
            separator = ","
        elif "分号" in sep_text:
            separator = ";"
        elif "管道" in sep_text:
            separator = "|"
        elif "空格" in sep_text:
            separator = " "
        else:
            separator = ","

        return DataConfig(
            name=os.path.basename(self._current_file) if self._current_file else "",
            source_type=self._last_detection.suggested_source_type if self._last_detection else "",
            encoding=self._encoding_combo.currentText(),
            separator=separator,
            header_rows=self._header_rows_spin.value(),
            skip_rows=self._skip_rows_spin.value(),
            column_mappings=mappings,
            unit_conversions=conversions,
            time_format=TimeFormat(
                source_format=self._time_format_edit.text().strip() or "auto",
            ),
        )

    # ── 操作按钮回调 ──────────────────────────────────────

    def _on_save_template(self) -> None:
        """另存为模板。"""
        config = self._read_config_from_ui()
        if not config.column_mappings:
            QtWidgets.QMessageBox.warning(
                self, "提示", "请至少添加一列映射后再保存模板")
            return

        name, ok = QtWidgets.QInputDialog.getText(
            self, "保存模板", "模板名称:", text=config.name or "my_template")
        if not ok or not name:
            return

        config.name = name
        fmt, ok = QtWidgets.QInputDialog.getItem(
            self, "格式选择", "保存格式:", ["json", "yaml"], 0, False)
        if not ok:
            return

        try:
            path = self._cm.save_template(config, name=name, fmt=fmt)
            self._refresh_template_list(name)
            self._info_label.setText(f"模板已保存: {name}")
            self.config_saved.emit(path)
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "保存失败", str(e))

    def _on_apply(self) -> None:
        """应用当前配置。"""
        config = self._read_config_from_ui()
        self._current_config = config
        self.config_applied.emit(config)

    def _on_cancel(self) -> None:
        """取消编辑。"""
        self.config_cancelled.emit()

    # ── 表格工具方法 ────────────────────────────────────────

    @staticmethod
    def _add_table_row(table: QtWidgets.QTableWidget) -> None:
        """向表格末尾添加一行。"""
        row = table.rowCount()
        table.insertRow(row)
        for col in range(table.columnCount()):
            table.setItem(row, col, QtWidgets.QTableWidgetItem(""))

    @staticmethod
    def _remove_table_row(table: QtWidgets.QTableWidget) -> None:
        """删除表格的选中行。"""
        rows = set()
        for item in table.selectedItems():
            rows.add(item.row())
        for r in sorted(rows, reverse=True):
            table.removeRow(r)

    # ── 外部接口 ────────────────────────────────────────────

    def set_file(self, file_path: str) -> None:
        """外部设置文件路径并自动检测。"""
        if os.path.exists(file_path):
            self._load_file(file_path)

    def get_config(self) -> Optional[DataConfig]:
        """获取当前配置。"""
        return self._current_config

    def set_config(self, config: DataConfig) -> None:
        """外部设置配置并填充 UI。"""
        self._apply_config_to_ui(config)
        self._current_config = config

    def load_config(self, file_path: str) -> bool:
        """加载外部配置模板文件。"""
        config = self._cm.load_from_file(file_path)
        if config is None:
            return False
        self.set_config(config)
        return True
