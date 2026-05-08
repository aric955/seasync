"""
SeaSync 统一日志系统
====================
替换散落在各模块的 print() 调用。
支持三种输出：文件日志（自动轮转）、控制台、GUI 回调。

用法：
    from ..core.logger import log
    log.info("流程启动")
    log.error("加载失败: %s", path)
    log.debug("关联矩阵 shape=%s", str(m.shape))
    log.log_json("关联完成", level="info", n_pairs=15, quality=0.85)

GUI 集成：
    from ..core.logger import log
    log.set_gui_callback(lambda msg: text_edit.append(msg))
"""

# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 荣火
from __future__ import annotations
import os
import sys
import json
import logging
import logging.handlers
from typing import Callable, Optional, Dict, Any

_LOG_DIR = None          # 日志目录，默认 ~/.seasync/logs/
_LOG_FILE = "seasync.log"
_MAX_BYTES = 10 * 1024 * 1024  # 10MB 轮转
_BACKUP_COUNT = 3
_LOG_LEVEL = logging.INFO


class LogManager:
    """日志管理器（单例）。"""

    _instance: Optional["LogManager"] = None

    def __new__(cls) -> "LogManager":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self._initialized = True
        self._logger = logging.getLogger("seasync")
        self._logger.setLevel(_LOG_LEVEL)
        self._logger.handlers.clear()
        self._gui_callback: Optional[Callable[[str], None]] = None

        # 文件 Handler（自动创建目录）
        self._file_handler: Optional[logging.Handler] = None
        self._setup_file_handler()

        # 控制台 Handler
        self._console_handler = logging.StreamHandler(sys.stdout)
        self._console_handler.setLevel(_LOG_LEVEL)
        self._console_handler.setFormatter(
            logging.Formatter("[%(asctime)s] %(levelname)-5s %(message)s",
                              datefmt="%H:%M:%S")
        )
        self._logger.addHandler(self._console_handler)

        # GUI 自定义 Handler（惰性创建）
        self._gui_handler: Optional[_GuiHandler] = None

    # ── 文件日志 ─────────────────────────────────────────────

    def set_log_dir(self, log_dir: str) -> None:
        """设置日志目录并重建文件 Handler。"""
        global _LOG_DIR
        if _LOG_DIR == log_dir:
            return
        _LOG_DIR = log_dir
        if self._file_handler:
            self._logger.removeHandler(self._file_handler)
            self._file_handler.close()
        self._setup_file_handler()

    def _setup_file_handler(self) -> None:
        """创建 RotatingFileHandler。"""
        log_dir = _LOG_DIR or self._default_log_dir()
        try:
            os.makedirs(log_dir, exist_ok=True)
        except (OSError, PermissionError):
            return  # 无法创建日志目录
        log_path = os.path.join(log_dir, _LOG_FILE)
        try:
            fh = logging.handlers.RotatingFileHandler(
                log_path, maxBytes=_MAX_BYTES, backupCount=_BACKUP_COUNT,
                encoding="utf-8",
            )
            fh.setLevel(_LOG_LEVEL)
            fh.setFormatter(
                logging.Formatter("%(asctime)s [%(levelname)-5s] %(message)s",
                                  datefmt="%Y-%m-%d %H:%M:%S")
            )
            self._file_handler = fh
            self._logger.addHandler(fh)
        except (OSError, PermissionError, IOError):
            pass  # 无法写入日志文件时不抛异常

    @staticmethod
    def _default_log_dir() -> str:
        """默认日志目录：~/.seasync/logs/"""
        return os.path.join(os.path.expanduser("~"), ".seasync", "logs")

    # ── GUI 回调 ─────────────────────────────────────────────

    def set_gui_callback(self, callback: Callable[[str], None]) -> None:
        """设置 GUI 日志回调（主线程安全）。"""
        self._gui_callback = callback
        if self._gui_handler is None:
            self._gui_handler = _GuiHandler(callback)
            self._gui_handler.setLevel(_LOG_LEVEL)
            self._logger.addHandler(self._gui_handler)
        else:
            self._gui_handler.set_callback(callback)

    # ── 便捷方法 ─────────────────────────────────────────────

    def _safe_log(self, level: int, msg: str, *args) -> None:
        """安全日志方法，捕获文件写入异常。"""
        try:
            self._logger.log(level, msg, *args)
        except (OSError, IOError) as e:
            # 沙箱/权限限制导致文件写入失败时，仅输出到控制台
            if "Bad file descriptor" not in str(e) and "Restricted" not in str(e):
                try:
                    print(f"[{logging.getLevelName(level)}] {msg % args if args else msg}")
                except Exception:
                    pass  # 完全静默

    def info(self, msg: str, *args) -> None:
        self._safe_log(logging.INFO, msg, *args)

    def warning(self, msg: str, *args) -> None:
        self._safe_log(logging.WARNING, msg, *args)

    def error(self, msg: str, *args) -> None:
        self._safe_log(logging.ERROR, msg, *args)

    def debug(self, msg: str, *args) -> None:
        self._safe_log(logging.DEBUG, msg, *args)

    def set_level(self, level: int) -> None:
        self._logger.setLevel(level)
        self._console_handler.setLevel(level)
        if self._file_handler:
            self._file_handler.setLevel(level)

    def get_logger(self) -> logging.Logger:
        """返回标准 logging.Logger 实例，供高级用法。"""
        return self._logger

    def log_json(self, event: str, level: str = "info", **kwargs: Any) -> None:
        """输出结构化 JSON 日志，便于日志分析和监控。

        Args:
            event: 事件名称，如 "association_complete", "file_loaded"
            level: 日志级别，如 "info", "warning", "error", "debug"
            **kwargs: 任意结构化数据，如 n_pairs=15, quality=0.85

        示例：
            log.log_json("关联完成", level="info", n_pairs=15, quality=0.85)
            # 输出：{"event": "关联完成", "level": "info", "n_pairs": 15, "quality": 0.85}
        """
        import datetime
        record = {
            "event": event,
            "level": level,
            "timestamp": datetime.datetime.now().isoformat(),
            **kwargs,
        }
        json_str = json.dumps(record, ensure_ascii=False)
        log_method = getattr(self._logger, level.lower(), self._logger.info)
        log_method("[JSON] %s", json_str)


class _GuiHandler(logging.Handler):
    """将日志记录转发到 GUI 回调的 Handler。"""

    def __init__(self, callback: Callable[[str], None]) -> None:
        super().__init__()
        self._callback = callback

    def set_callback(self, callback: Callable[[str], None]) -> None:
        self._callback = callback

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            if self._callback:
                self._callback(msg)
        except Exception:
            self.handleError(record)


# ── 全局单例 ────────────────────────────────────────────────

log = LogManager()


def log_exception(msg: str = "", exc_info: bool = False) -> None:
    """轻量级异常日志（可被任何模块安全调用，不会因 import 失败而崩溃）。"""
    try:
        log.warning(msg)
        if exc_info:
            import traceback; log.debug("%s", traceback.format_exc()[-200:])
    except Exception:
        pass  # 日志自身出错不应该影响主流程
