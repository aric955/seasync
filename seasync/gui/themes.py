"""
SeaSync V2.2 主题系统 — 统一配色、字体、圆角、阴影。
支持深色/浅色主题切换。

设计原则：
- 使用温和、有层次感的深色（参考 VS Code / JetBrains 深色主题）
- 避免纯黑死黑，保持视觉层次
- 全局 QSS 统一控制，减少局部 setStyleSheet 冲突
- 高对比度文字确保可读性
"""

# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 荣火
from __future__ import annotations
from typing import Dict
from PyQt5 import QtWidgets, QtGui


class SeaSyncTheme:
    """SeaSync 统一主题配置 — 现代深色主题。"""

    # 主色调 — 深海蓝
    PRIMARY = "#0EA5E9"          # 亮蓝（主强调色）
    PRIMARY_DARK = "#0284C7"     # 深蓝（悬停/按下）
    PRIMARY_LIGHT = "#38BDF8"    # 浅蓝（高亮）

    # 背景色 — 温和深色，避免纯黑
    BG_DARKEST = "#1E1E2E"       # 最深背景（窗口底色）
    BG_DARK = "#252535"          # 主背景（面板底色）
    BG_CARD = "#2D2D44"          # 卡片背景
    BG_INPUT = "#1A1A28"         # 输入框背景（稍深以区分）
    BG_HOVER = "#3A3A55"         # 悬停背景

    # 文字色 — 确保高对比度可读性
    TEXT_PRIMARY = "#E8E8F0"     # 主文字（近白）
    TEXT_SECONDARY = "#A0A0B8"   # 次要文字
    TEXT_MUTED = "#6E6E88"       # 弱化文字
    TEXT_ACCENT = "#38BDF8"      # 强调文字

    # 状态色
    SUCCESS = "#22C55E"          # 成功绿
    WARNING = "#F59E0B"          # 警告橙
    ERROR = "#EF4444"            # 错误红
    INFO = "#3B82F6"             # 信息蓝

    # 边框
    BORDER = "#3E3E5E"           # 普通边框
    BORDER_FOCUS = "#0EA5E9"     # 聚焦边框
    BORDER_RADIUS = 6            # 圆角半径
    BORDER_RADIUS_SMALL = 4      # 小圆角

    # 字体
    FONT_FAMILY = "Microsoft YaHei, PingFang SC, Noto Sans SC, sans-serif"
    FONT_SIZE_SMALL = 11
    FONT_SIZE_NORMAL = 12
    FONT_SIZE_LARGE = 13
    FONT_SIZE_TITLE = 14
    FONT_SIZE_HERO = 20

    # 间距
    SPACING_XS = 4
    SPACING_SM = 8
    SPACING_MD = 10
    SPACING_LG = 14
    SPACING_XL = 20

    @classmethod
    def apply_global(cls, app: QtWidgets.QApplication) -> None:
        """应用全局样式到 QApplication。"""
        app.setStyle("Fusion")
        app.setStyleSheet(cls._global_qss())

        # 设置全局字体
        font = QtGui.QFont("Microsoft YaHei", cls.FONT_SIZE_NORMAL)
        font.setStyleStrategy(QtGui.QFont.PreferAntialias)
        app.setFont(font)

    @classmethod
    def _global_qss(cls) -> str:
        """生成全局 QSS 样式表。"""
        return f"""
        /* ===== 全局基础 ===== */
        QWidget {{
            font-family: {cls.FONT_FAMILY};
            font-size: {cls.FONT_SIZE_NORMAL}px;
            color: {cls.TEXT_PRIMARY};
            background-color: {cls.BG_DARK};
            outline: none;
        }}

        /* ===== QMainWindow ===== */
        QMainWindow {{
            background-color: {cls.BG_DARKEST};
        }}

        /* ===== QMenuBar ===== */
        QMenuBar {{
            background-color: {cls.BG_DARKEST};
            border-bottom: 1px solid {cls.BORDER};
            padding: 2px 6px;
        }}
        QMenuBar::item {{
            background: transparent;
            padding: 5px 12px;
            border-radius: {cls.BORDER_RADIUS_SMALL}px;
            color: {cls.TEXT_PRIMARY};
        }}
        QMenuBar::item:selected {{
            background-color: {cls.BG_HOVER};
        }}
        QMenuBar::item:pressed {{
            background-color: {cls.PRIMARY_DARK};
        }}

        /* ===== QMenu ===== */
        QMenu {{
            background-color: {cls.BG_CARD};
            border: 1px solid {cls.BORDER};
            border-radius: {cls.BORDER_RADIUS_SMALL}px;
            padding: 4px;
        }}
        QMenu::item {{
            padding: 6px 20px;
            border-radius: {cls.BORDER_RADIUS_SMALL}px;
            color: {cls.TEXT_PRIMARY};
        }}
        QMenu::item:selected {{
            background-color: {cls.PRIMARY};
            color: white;
        }}
        QMenu::separator {{
            height: 1px;
            background-color: {cls.BORDER};
            margin: 4px 8px;
        }}

        /* ===== QPushButton ===== */
        QPushButton {{
            background-color: {cls.PRIMARY};
            color: white;
            border: none;
            border-radius: {cls.BORDER_RADIUS}px;
            padding: 6px 16px;
            font-weight: 500;
            min-height: 28px;
        }}
        QPushButton:hover {{
            background-color: {cls.PRIMARY_LIGHT};
        }}
        QPushButton:pressed {{
            background-color: {cls.PRIMARY_DARK};
        }}
        QPushButton:disabled {{
            background-color: {cls.BG_CARD};
            color: {cls.TEXT_MUTED};
        }}

        /* ===== QLineEdit / QSpinBox / QDoubleSpinBox ===== */
        QLineEdit, QSpinBox, QDoubleSpinBox {{
            background-color: {cls.BG_INPUT};
            border: 1px solid {cls.BORDER};
            border-radius: {cls.BORDER_RADIUS_SMALL}px;
            padding: 5px 8px;
            color: {cls.TEXT_PRIMARY};
            selection-background-color: {cls.PRIMARY};
        }}
        QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus {{
            border-color: {cls.BORDER_FOCUS};
        }}
        QSpinBox::up-button, QDoubleSpinBox::up-button {{
            background-color: {cls.BG_CARD};
            border: none;
            border-radius: 2px;
            width: 16px;
        }}
        QSpinBox::down-button, QDoubleSpinBox::down-button {{
            background-color: {cls.BG_CARD};
            border: none;
            border-radius: 2px;
            width: 16px;
        }}

        /* ===== QSlider ===== */
        QSlider::groove:horizontal {{
            height: 4px;
            background-color: {cls.BG_CARD};
            border-radius: 2px;
        }}
        QSlider::sub-page:horizontal {{
            background-color: {cls.PRIMARY};
            border-radius: 2px;
        }}
        QSlider::handle:horizontal {{
            background-color: {cls.PRIMARY_LIGHT};
            width: 14px;
            height: 14px;
            margin: -5px 0;
            border-radius: 7px;
            border: 2px solid {cls.BG_DARK};
        }}
        QSlider::handle:horizontal:hover {{
            background-color: white;
            border-color: {cls.PRIMARY};
        }}

        /* ===== QComboBox ===== */
        QComboBox {{
            background-color: {cls.BG_INPUT};
            border: 1px solid {cls.BORDER};
            border-radius: {cls.BORDER_RADIUS_SMALL}px;
            padding: 5px 8px;
            min-width: 80px;
            color: {cls.TEXT_PRIMARY};
        }}
        QComboBox:focus {{
            border-color: {cls.BORDER_FOCUS};
        }}
        QComboBox::drop-down {{
            border: none;
            width: 20px;
        }}
        QComboBox QAbstractItemView {{
            background-color: {cls.BG_CARD};
            border: 1px solid {cls.BORDER};
            border-radius: {cls.BORDER_RADIUS_SMALL}px;
            selection-background-color: {cls.PRIMARY};
            selection-color: white;
            color: {cls.TEXT_PRIMARY};
        }}

        /* ===== QGroupBox ===== */
        QGroupBox {{
            background-color: {cls.BG_CARD};
            border: 1px solid {cls.BORDER};
            border-radius: {cls.BORDER_RADIUS}px;
            margin-top: 8px;
            padding-top: 8px;
            padding-bottom: 8px;
            padding-left: 10px;
            padding-right: 10px;
            font-weight: 500;
            color: {cls.TEXT_ACCENT};
        }}
        QGroupBox::title {{
            subcontrol-origin: margin;
            left: 10px;
            padding: 0 6px;
            color: {cls.TEXT_ACCENT};
        }}

        /* ===== QTabWidget ===== */
        QTabWidget::pane {{
            background-color: {cls.BG_DARK};
            border: 1px solid {cls.BORDER};
            border-radius: {cls.BORDER_RADIUS}px;
            top: -1px;
        }}
        QTabBar::tab {{
            background-color: {cls.BG_CARD};
            border: 1px solid {cls.BORDER};
            border-bottom: none;
            border-top-left-radius: {cls.BORDER_RADIUS_SMALL}px;
            border-top-right-radius: {cls.BORDER_RADIUS_SMALL}px;
            padding: 6px 16px;
            margin-right: 2px;
            color: {cls.TEXT_SECONDARY};
        }}
        QTabBar::tab:selected {{
            background-color: {cls.BG_DARK};
            color: {cls.TEXT_PRIMARY};
            border-bottom: 2px solid {cls.PRIMARY};
        }}
        QTabBar::tab:hover:!selected {{
            background-color: {cls.BG_HOVER};
            color: {cls.TEXT_PRIMARY};
        }}

        /* ===== QTableWidget ===== */
        QTableWidget {{
            background-color: {cls.BG_DARK};
            border: 1px solid {cls.BORDER};
            border-radius: {cls.BORDER_RADIUS_SMALL}px;
            gridline-color: {cls.BORDER};
            color: {cls.TEXT_PRIMARY};
        }}
        QTableWidget::item {{
            padding: 5px 8px;
            border-bottom: 1px solid {cls.BORDER};
            color: {cls.TEXT_PRIMARY};
        }}
        QTableWidget::item:selected {{
            background-color: {cls.PRIMARY};
            color: white;
        }}
        QHeaderView::section {{
            background-color: {cls.BG_CARD};
            color: {cls.TEXT_ACCENT};
            padding: 6px 8px;
            border: none;
            border-bottom: 2px solid {cls.PRIMARY};
            font-weight: 500;
        }}
        QHeaderView::section:hover {{
            background-color: {cls.BG_HOVER};
        }}

        /* ===== QScrollBar ===== */
        QScrollBar:vertical {{
            background-color: {cls.BG_DARKEST};
            width: 8px;
            border-radius: 4px;
        }}
        QScrollBar::handle:vertical {{
            background-color: {cls.BG_CARD};
            border-radius: 4px;
            min-height: 28px;
        }}
        QScrollBar::handle:vertical:hover {{
            background-color: {cls.PRIMARY};
        }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
            height: 0px;
        }}
        QScrollBar:horizontal {{
            background-color: {cls.BG_DARKEST};
            height: 8px;
            border-radius: 4px;
        }}
        QScrollBar::handle:horizontal {{
            background-color: {cls.BG_CARD};
            border-radius: 4px;
            min-width: 28px;
        }}
        QScrollBar::handle:horizontal:hover {{
            background-color: {cls.PRIMARY};
        }}

        /* ===== QSplitter ===== */
        QSplitter::handle {{
            background-color: {cls.BORDER};
        }}
        QSplitter::handle:horizontal {{
            width: 2px;
        }}
        QSplitter::handle:vertical {{
            height: 2px;
        }}
        QSplitter::handle:hover {{
            background-color: {cls.PRIMARY};
        }}

        /* ===== QProgressBar ===== */
        QProgressBar {{
            background-color: {cls.BG_CARD};
            border: 1px solid {cls.BORDER};
            border-radius: {cls.BORDER_RADIUS_SMALL}px;
            text-align: center;
            color: {cls.TEXT_PRIMARY};
            height: 18px;
        }}
        QProgressBar::chunk {{
            background-color: {cls.PRIMARY};
            border-radius: {cls.BORDER_RADIUS_SMALL}px;
        }}

        /* ===== QStatusBar ===== */
        QStatusBar {{
            background-color: {cls.BG_DARKEST};
            border-top: 1px solid {cls.BORDER};
            color: {cls.TEXT_SECONDARY};
        }}
        QStatusBar::item {{
            border: none;
        }}

        /* ===== QListWidget ===== */
        QListWidget {{
            background-color: {cls.BG_DARK};
            border: 1px solid {cls.BORDER};
            border-radius: {cls.BORDER_RADIUS_SMALL}px;
            outline: none;
            color: {cls.TEXT_PRIMARY};
        }}
        QListWidget::item {{
            padding: 6px 10px;
            border-radius: {cls.BORDER_RADIUS_SMALL}px;
            margin: 1px 3px;
            color: {cls.TEXT_PRIMARY};
        }}
        QListWidget::item:selected {{
            background-color: {cls.PRIMARY};
            color: white;
        }}
        QListWidget::item:hover {{
            background-color: {cls.BG_HOVER};
        }}

        /* ===== QCheckBox ===== */
        QCheckBox {{
            spacing: 6px;
            color: {cls.TEXT_PRIMARY};
        }}
        QCheckBox::indicator {{
            width: 16px;
            height: 16px;
            border: 2px solid {cls.BORDER};
            border-radius: 3px;
            background-color: {cls.BG_INPUT};
        }}
        QCheckBox::indicator:checked {{
            background-color: {cls.PRIMARY};
            border-color: {cls.PRIMARY};
        }}
        QCheckBox::indicator:hover {{
            border-color: {cls.PRIMARY};
        }}

        /* ===== QRadioButton ===== */
        QRadioButton {{
            spacing: 6px;
            color: {cls.TEXT_PRIMARY};
        }}
        QRadioButton::indicator {{
            width: 16px;
            height: 16px;
            border: 2px solid {cls.BORDER};
            border-radius: 8px;
            background-color: {cls.BG_INPUT};
        }}
        QRadioButton::indicator:checked {{
            background-color: {cls.PRIMARY};
            border-color: {cls.PRIMARY};
        }}
        QRadioButton::indicator:hover {{
            border-color: {cls.PRIMARY};
        }}

        /* ===== QToolTip ===== */
        QToolTip {{
            background-color: {cls.BG_CARD};
            color: {cls.TEXT_PRIMARY};
            border: 1px solid {cls.BORDER};
            border-radius: {cls.BORDER_RADIUS_SMALL}px;
            padding: 5px 8px;
        }}

        /* ===== QLabel ===== */
        QLabel {{
            color: {cls.TEXT_PRIMARY};
            background: transparent;
        }}

        /* ===== QTextEdit / QPlainTextEdit ===== */
        QTextEdit, QPlainTextEdit {{
            background-color: {cls.BG_DARKEST};
            color: {cls.TEXT_PRIMARY};
            border: 1px solid {cls.BORDER};
            border-radius: {cls.BORDER_RADIUS_SMALL}px;
            padding: 6px;
            selection-background-color: {cls.PRIMARY};
        }}
        """

    @classmethod
    def get_button_style(cls, variant: str = "primary") -> str:
        """获取按钮样式（用于动态设置，尽量使用全局QSS，此方法仅作备用）。"""
        styles = {
            "primary": f"""
                QPushButton {{
                    background-color: {cls.PRIMARY};
                    color: white;
                    border: none;
                    border-radius: {cls.BORDER_RADIUS}px;
                    padding: 6px 16px;
                    font-weight: 500;
                }}
                QPushButton:hover {{ background-color: {cls.PRIMARY_LIGHT}; }}
                QPushButton:pressed {{ background-color: {cls.PRIMARY_DARK}; }}
            """,
            "secondary": f"""
                QPushButton {{
                    background-color: transparent;
                    border: 1px solid {cls.BORDER};
                    color: {cls.TEXT_PRIMARY};
                    border-radius: {cls.BORDER_RADIUS}px;
                    padding: 6px 16px;
                }}
                QPushButton:hover {{
                    background-color: {cls.BG_HOVER};
                    border-color: {cls.PRIMARY};
                }}
            """,
            "danger": f"""
                QPushButton {{
                    background-color: {cls.ERROR};
                    color: white;
                    border: none;
                    border-radius: {cls.BORDER_RADIUS}px;
                    padding: 6px 16px;
                }}
            """,
            "success": f"""
                QPushButton {{
                    background-color: {cls.SUCCESS};
                    color: white;
                    border: none;
                    border-radius: {cls.BORDER_RADIUS}px;
                    padding: 6px 16px;
                }}
            """,
        }
        return styles.get(variant, styles["primary"])

    @classmethod
    def get_card_style(cls) -> str:
        """获取卡片样式。"""
        return f"""
            background-color: {cls.BG_CARD};
            border: 1px solid {cls.BORDER};
            border-radius: {cls.BORDER_RADIUS}px;
        """

    @classmethod
    def get_matplotlib_colors(cls) -> Dict[str, str]:
        """获取 Matplotlib 主题配色。"""
        return {
            "bg": cls.BG_DARKEST,
            "axes_bg": cls.BG_DARK,
            "text": cls.TEXT_PRIMARY,
            "grid": cls.BORDER,
            "primary": cls.PRIMARY,
            "accent": cls.PRIMARY_LIGHT,
        }
