"""
SeaSync V2.2 - 多源目标关联分析系统
Copyright (C) 2026 荣火

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU Affero General Public License as published
by the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU Affero General Public License for more details.

You should have received a copy of the GNU Affero General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>.
"""

#!/usr/bin/env python
"""启动 SeaSync V2.2 GUI（可靠启动，带错误诊断）。"""
import sys
import os
import traceback

# 1) 确保项目路径在 sys.path 中
_PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _PROJECT_ROOT)

# 2) 设置 Qt 平台插件路径（防止 PyQt5 找不到 qwindows.dll）
_QT_PLUGIN_CANDIDATES = [
    os.path.join(_PROJECT_ROOT, "seasync", "gui", "Qt5", "plugins"),
    os.path.join(os.path.dirname(os.path.dirname(__file__)),
                 "Roaming", "Python", "Python314", "site-packages", "PyQt5", "Qt5", "plugins"),
    # pip install location
    os.path.join(sys.prefix, "Lib", "site-packages", "PyQt5", "Qt5", "plugins"),
]
# 最可能的路径
_APPROACH_PLUGINS = os.path.join(
    os.path.expanduser("~"),
    "AppData", "Roaming", "Python", "Python314",
    "site-packages", "PyQt5", "Qt5", "plugins", "platforms"
)
if os.path.isdir(_APPROACH_PLUGINS):
    os.environ.setdefault("QT_QPA_PLATFORM_PLUGIN_PATH", _APPROACH_PLUGINS)

# 3) 设置控制台编码（防止中文乱码）
# 注意：打包为 exe (console=False) 时 sys.stdout 可能为 None
if sys.platform == "win32" and sys.stdout is not None and hasattr(sys.stdout, "buffer"):
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
if sys.platform == "win32" and sys.stderr is not None and hasattr(sys.stderr, "buffer"):
    import io
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")


def main():
    """主函数：捕获所有异常并显示给用户。"""
    try:
        from PyQt5 import QtWidgets, QtCore
        from seasync.gui.main_window import SeaSyncMainWindow
        from seasync.gui.themes import SeaSyncTheme

        # 确保仅一个 QApplication
        app = QtWidgets.QApplication.instance()
        if app is None:
            app = QtWidgets.QApplication(sys.argv)
        else:
            print("复用了已有的 QApplication")

        # 应用全局主题
        SeaSyncTheme.apply_global(app)

        # 创建窗口
        window = SeaSyncMainWindow()
        window.resize(1400, 900)
        window.show()

        print("SeaSync GUI 已启动 — 请勿关闭此窗口")
        sys.exit(app.exec_())

    except SyntaxError as e:
        _show_error(f"Python 语法错误:\n{e}\n\n请检查最近修改的代码文件。")
    except ImportError as e:
        _show_error(f"导入模块失败:\n{e}\n\n请确认 PyQt5 已安装: pip install PyQt5")
    except Exception as e:
        _show_error(f"启动失败:\n{e}\n\n{traceback.format_exc()}")


def _show_error(msg: str) -> None:
    """显示错误消息（同时打印到控制台和弹窗）。"""
    print("=" * 60, flush=True)
    print("SeaSync 启动错误", flush=True)
    print("=" * 60, flush=True)
    print(msg, flush=True)
    print("=" * 60, flush=True)
    # 尝试弹窗（可能失败，但值得一试）
    try:
        from PyQt5 import QtWidgets
        if not QtWidgets.QApplication.instance():
            _app = QtWidgets.QApplication(sys.argv)
        QtWidgets.QMessageBox.critical(None, "SeaSync 启动错误", msg)
    except Exception:
        input("\n按回车键退出...")
    sys.exit(1)


if __name__ == "__main__":
    main()
