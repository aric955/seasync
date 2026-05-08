"""
SeaSync V2.2 ConfigManager — 配置管理系统
数据配置 / 列映射 / 单位转换 / 时间格式 的模板化管理。
支持 JSON / YAML 格式的配置模板读写。
"""

# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 荣火
from __future__ import annotations
import os
import json
import glob
from dataclasses import dataclass, field, asdict
from typing import List, Optional, Dict, Any
from .logger import log_exception


# ── 配置数据结构 ────────────────────────────────────────────────

@dataclass
class ColumnMapping:
    """列映射：将源列名映射到统一的标准列名。"""
    source_column: str          # 源文件中的原始列名
    standard_column: str        # 映射到的标准列名
    data_type: str = "float"    # 数据类型：float / int / str / datetime
    default_value: Any = None   # 缺失时的默认值
    transform: str = ""         # 可选的转换表达式（如 "lambda x: x*0.514"）


@dataclass
class UnitConversion:
    """单位转换配置。"""
    column: str              # 列名
    source_unit: str         # 原始单位（如 "kn"）
    target_unit: str         # 目标单位（如 "m/s"）
    conversion_factor: Optional[float] = None  # 换算系数，None则查表


@dataclass
class TimeFormat:
    """时间格式配置。"""
    source_format: str = "auto"       # 源时间格式："auto"/"%Y-%m-%d %H:%M:%S"/...
    source_timezone: str = "UTC+8"    # 源时区
    target_timezone: str = "UTC"      # 目标时区（统一用UTC）
    column_name: str = "time"         # 时间列名


@dataclass
class DataConfig:
    """完整的数据源配置。"""
    # 基本描述
    name: str = ""
    description: str = ""
    source_type: str = ""       # radar / ais / gps / csv

    # 文件解析参数
    encoding: str = "utf-8"
    separator: str = ","
    header_rows: int = 0        # 表头行数
    skip_rows: int = 0          # 头部跳过行数
    skip_footer: int = 0        # 尾部跳过行数
    comment_char: str = ""

    # 列映射与转换
    column_mappings: List[ColumnMapping] = field(default_factory=list)
    unit_conversions: List[UnitConversion] = field(default_factory=list)
    time_format: TimeFormat = field(default_factory=TimeFormat)

    # 匹配规则（用于自动推荐）
    file_patterns: List[str] = field(default_factory=list)     # glob 模式，如 "*radar*"
    extension_hints: List[str] = field(default_factory=list)   # 扩展名，如 [".csv"]
    column_hints: List[str] = field(default_factory=list)      # 必须包含的列名
    content_hints: List[str] = field(default_factory=list)     # 内容必须包含的关键词
    min_columns: int = 0
    max_columns: int = 999

    # 置信度权重
    match_weight: float = 1.0

    def to_dict(self) -> Dict[str, Any]:
        """序列化为字典（递归处理嵌套 dataclass）。"""
        d = asdict(self)
        return d

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> DataConfig:
        """从字典恢复。"""
        # 手动构建嵌套 dataclass，避免类型推断问题
        mappings = []
        for m in d.get("column_mappings", []):
            mappings.append(ColumnMapping(**m))
        conversions = []
        for c in d.get("unit_conversions", []):
            conversions.append(UnitConversion(**c))
        tf = TimeFormat(**d.get("time_format", {}))
        return cls(
            name=d.get("name", ""),
            description=d.get("description", ""),
            source_type=d.get("source_type", ""),
            encoding=d.get("encoding", "utf-8"),
            separator=d.get("separator", ","),
            header_rows=d.get("header_rows", 0),
            skip_rows=d.get("skip_rows", 0),
            skip_footer=d.get("skip_footer", 0),
            comment_char=d.get("comment_char", ""),
            column_mappings=mappings,
            unit_conversions=conversions,
            time_format=tf,
            file_patterns=d.get("file_patterns", []),
            extension_hints=d.get("extension_hints", []),
            column_hints=d.get("column_hints", []),
            content_hints=d.get("content_hints", []),
            min_columns=d.get("min_columns", 0),
            max_columns=d.get("max_columns", 999),
            match_weight=d.get("match_weight", 1.0),
        )


# ── 单位换算系数表 ──────────────────────────────────────────────

_UNIT_FACTORS: Dict[str, Dict[str, float]] = {
    "kn": {"m/s": 0.514444, "km/h": 1.852, "mph": 1.15078},
    "m/s": {"kn": 1.94384, "km/h": 3.6, "mph": 2.23694},
    "km/h": {"kn": 0.539957, "m/s": 0.277778, "mph": 0.621371},
    "m": {"km": 0.001, "nm": 0.000539957, "ft": 3.28084},
    "km": {"m": 1000, "nm": 0.539957, "ft": 3280.84},
    "nm": {"m": 1852, "km": 1.852, "ft": 6076.12},
    "°": {"rad": 0.0174533, "deg": 1.0},
    "deg": {"rad": 0.0174533, "°": 1.0},
    "rad": {"deg": 57.2958, "°": 57.2958},
    "m/s²": {"kn/s": 1.94384},
    "s": {"ms": 1000, "min": 1 / 60, "h": 1 / 3600},
    "min": {"s": 60, "h": 1 / 60},
    "h": {"s": 3600, "min": 60},
}


def get_conversion_factor(source_unit: str, target_unit: str) -> Optional[float]:
    """查询单位换算系数。"""
    src = source_unit.strip().lower()
    tgt = target_unit.strip().lower()
    if src in _UNIT_FACTORS and tgt in _UNIT_FACTORS[src]:
        return _UNIT_FACTORS[src][tgt]
    # 反向
    if tgt in _UNIT_FACTORS and src in _UNIT_FACTORS[tgt]:
        return 1.0 / _UNIT_FACTORS[tgt][src]
    return None


# ── 配置管理器 ──────────────────────────────────────────────────

class ConfigManager:
    """配置模板管理器。

    管理 config/templates/ 下的 JSON/YAML 配置模板。
    支持模板的 CRUD、搜索推荐、格式转换。
    """

    def __init__(self, template_dir: Optional[str] = None) -> None:
        self._template_dir = template_dir or self._default_template_dir()
        self._cache: Dict[str, DataConfig] = {}
        self._ensure_dir()

    @staticmethod
    def _default_template_dir() -> str:
        """默认模板目录（相对于项目根）。"""
        # 尝试多种路径
        candidates = [
            os.path.join(os.path.dirname(__file__), "..", "..", "config", "templates"),
            os.path.join(os.getcwd(), "config", "templates"),
        ]
        for p in candidates:
            absp = os.path.abspath(p)
            if os.path.isdir(absp):
                return absp
        # 都不存在则用第一个
        return os.path.abspath(candidates[0])

    def _ensure_dir(self) -> None:
        """确保模板目录存在。"""
        os.makedirs(self._template_dir, exist_ok=True)

    # ── 模板 CRUD ────────────────────────────────────────────

    def save_template(self, config: DataConfig, name: Optional[str] = None,
                      fmt: str = "json") -> str:
        """保存配置模板到文件。

        Args:
            config: DataConfig 实例
            name: 模板名（不含扩展名），默认用 config.name
            fmt: "json" 或 "yaml"

        Returns:
            保存的文件路径
        """
        name = name or config.name or "untitled"
        ext = ".yaml" if fmt == "yaml" else ".json"
        filepath = os.path.join(self._template_dir, f"{name}{ext}")

        data = config.to_dict()

        if fmt == "yaml":
            self._save_yaml(data, filepath)
        else:
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

        self._cache[name] = config
        return filepath

    def load_template(self, name: str) -> Optional[DataConfig]:
        """按模板名（不带扩展名）加载配置。

        Args:
            name: 模板名（如 "radar_default"）

        Returns:
            DataConfig 实例，未找到返回 None
        """
        if name in self._cache:
            return self._cache[name]

        # 尝试 .json 和 .yaml
        for ext in (".json", ".yaml", ".yml"):
            filepath = os.path.join(self._template_dir, f"{name}{ext}")
            if os.path.exists(filepath):
                cfg = self._load_file(filepath)
                if cfg:
                    self._cache[name] = cfg
                return cfg
        return None

    def load_from_file(self, filepath: str) -> Optional[DataConfig]:
        """从任意路径加载配置文件。"""
        if not os.path.exists(filepath):
            return None
        return self._load_file(filepath)

    def _load_file(self, filepath: str) -> Optional[DataConfig]:
        """加载单个配置文件。"""
        try:
            ext = os.path.splitext(filepath)[-1].lower()
            if ext in (".yaml", ".yml"):
                data = self._load_yaml(filepath)
            elif ext == ".json":
                with open(filepath, "r", encoding="utf-8") as f:
                    data = json.load(f)
            else:
                return None
            return DataConfig.from_dict(data) if isinstance(data, dict) else None
        except Exception:
            log_exception(f"加载模板失败: {name}", exc_info=True)
            return None

    def list_templates(self, pattern: str = "*.json") -> List[str]:
        """列出模板名（不含扩展名）。

        Args:
            pattern: glob 模式，如 "*.json", "*.yaml"

        Returns:
            模板名列表
        """
        names: List[str] = []
        for ext_pat in ("*.json", "*.yaml", "*.yml"):
            full_pattern = os.path.join(self._template_dir, ext_pat)
            for fp in glob.glob(full_pattern):
                name = os.path.splitext(os.path.basename(fp))[0]
                if name not in names:
                    names.append(name)
        return sorted(names)

    def delete_template(self, name: str) -> bool:
        """删除模板。"""
        for ext in (".json", ".yaml", ".yml"):
            filepath = os.path.join(self._template_dir, f"{name}{ext}")
            if os.path.exists(filepath):
                os.remove(filepath)
                self._cache.pop(name, None)
                return True
        return False

    def template_exists(self, name: str) -> bool:
        """检查模板是否存在。"""
        for ext in (".json", ".yaml", ".yml"):
            if os.path.exists(os.path.join(self._template_dir, f"{name}{ext}")):
                return True
        return name in self._cache

    # ── 模板推荐 ────────────────────────────────────────────

    def suggest_template(self, file_path: str,
                         sample_content: Optional[str] = None,
                         detected_columns: Optional[List[str]] = None) -> List[str]:
        """根据文件特征推荐最匹配的模板。

        Args:
            file_path: 数据文件路径
            sample_content: 文件开头内容（可选）
            detected_columns: 检测到的列名列表（可选）

        Returns:
            按匹配度降序排列的模板名列表
        """
        candidates: List[tuple] = []  # (name, score)

        ext = os.path.splitext(file_path)[-1].lower()
        fname = os.path.basename(file_path).lower()

        for name in self.list_templates():
            cfg = self.load_template(name)
            if cfg is None:
                continue

            score = 0.0

            # 1. 文件名模式匹配
            for pat in cfg.file_patterns:
                import fnmatch
                if fnmatch.fnmatch(fname, pat):
                    score += 30.0 * cfg.match_weight

            # 2. 扩展名匹配
            if ext in cfg.extension_hints:
                score += 20.0 * cfg.match_weight

            # 3. 列名匹配
            if detected_columns:
                dc_lower = [c.lower() for c in detected_columns]
                hit = sum(1 for h in cfg.column_hints if h.lower() in dc_lower)
                if cfg.column_hints:
                    score += (hit / len(cfg.column_hints)) * 25.0 * cfg.match_weight

                # 列数限制
                n_cols = len(detected_columns)
                if n_cols < cfg.min_columns or n_cols > cfg.max_columns:
                    score -= 50.0

            # 4. 内容关键词匹配
            if sample_content and cfg.content_hints:
                sc_lower = sample_content.lower()
                hit = sum(1 for h in cfg.content_hints if h.lower() in sc_lower)
                if cfg.content_hints:
                    score += (hit / len(cfg.content_hints)) * 25.0 * cfg.match_weight

            if score > 0:
                candidates.append((name, score))

        # 按分数降序排列
        candidates.sort(key=lambda x: -x[1])
        return [c[0] for c in candidates]

    # ── YAML 支持 ────────────────────────────────────────────

    @staticmethod
    def _save_yaml(data: dict, filepath: str) -> None:
        """保存字典为 YAML 格式。"""
        try:
            import yaml
            with open(filepath, "w", encoding="utf-8") as f:
                yaml.dump(data, f, allow_unicode=True, default_flow_style=False,
                          sort_keys=False)
        except ImportError:
            # 无 PyYAML 时 fallback：手动生成近似 YAML
            ConfigManager._save_yaml_fallback(data, filepath)

    @staticmethod
    def _save_yaml_fallback(data: dict, filepath: str) -> None:
        """手动生成 YAML 格式（不含 PyYAML 时使用）。"""
        lines = []
        for k, v in data.items():
            if isinstance(v, list):
                lines.append(f"{k}:")
                for item in v:
                    if isinstance(item, dict):
                        lines.append("  - " + json.dumps(item, ensure_ascii=False))
                    else:
                        lines.append(f"  - {item}")
            elif isinstance(v, dict):
                lines.append(f"{k}:")
                for sk, sv in v.items():
                    lines.append(f"  {sk}: {sv}")
            else:
                lines.append(f"{k}: {v}")
        with open(filepath, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

    @staticmethod
    def _load_yaml(filepath: str) -> Optional[dict]:
        """加载 YAML 文件。"""
        try:
            import yaml
            with open(filepath, "r", encoding="utf-8") as f:
                return yaml.safe_load(f)
        except ImportError:
            # 无 PyYAML 时尝试 JSON 回退
            return None
        except Exception:
            log_exception(f"加载模板失败: {name}", exc_info=True)
            return None

    # ── 工具方法 ─────────────────────────────────────────────

    def get_template_dir(self) -> str:
        """返回模板目录路径。"""
        return self._template_dir

    def __repr__(self) -> str:
        return f"<ConfigManager dir={self._template_dir} templates={len(self.list_templates())}>"
