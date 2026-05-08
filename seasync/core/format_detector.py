"""
SeaSync V2.2 SmartFormatDetector — 智能格式检测器

一站式检测文件的编码、格式、分隔符、列结构等元信息。
支持多种数据源类型（CSV、HDF5、MATLAB、NMEA、Excel 等）。
与 ConfigManager 集成，根据检测结果自动推荐配置模板。
"""

# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 荣火
from __future__ import annotations
import os
import re
import csv
from typing import Optional, List, Dict, Any, Tuple
from dataclasses import dataclass, field


# ── 魔数签名表 ──────────────────────────────────────────────────

_MAGIC_SIGNATURES: Dict[str, Tuple[bytes, int, str]] = {
    # (magic_bytes, offset, description)
    "\x89HDF\r\n\x1a\n": (b"\x89HDF\r\n\x1a\n", 0, "HDF5"),
    "MATLAB 5.0": (b"MATLAB 5.0", 0, "MATLAB 5.0 (mat)"),
    "MATLAB 7.3": (b"HDF5", 0, "MATLAB 7.3 (mat)"),  # 7.3 版本质是 HDF5
    "ZIP": (b"PK\x03\x04", 0, "ZIP"),
    "GZIP": (b"\x1f\x8b", 0, "GZIP"),
    "BZIP2": (b"BZh", 0, "BZIP2"),
    "XZ": (b"\xfd7zXZ\x00", 0, "XZ"),
    "PNG": (b"\x89PNG\r\n\x1a\n", 0, "PNG"),
    "JPEG": (b"\xff\xd8\xff", 0, "JPEG"),
    "PDF": (b"%PDF", 0, "PDF"),
    "TIFF": (b"II*\x00", 0, "TIFF"),
    "RIFF (AVI/WAV)": (b"RIFF", 0, "RIFF"),
    "NMEA": (b"$GP", 0, "NMEA Sentence"),
    "NetCDF": (b"CDF\x01", 0, "NetCDF"),
    "Shapefile": (b"\x00\x00\x27\x0a", 0, "Shapefile"),
    "KML/ZIP": (b"PK\x03\x04", 0, "KML (ZIP)"),
    "Excel (XLS)": (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1", 0, "Excel (XLS)"),
}

# CAT048魔数检测（特殊处理：需验证长度字段避免误匹配）
_CAT048_CACHE: dict = {}


def _check_cat048(file_path: str) -> bool:
    """检查是否为CAT-048格式。"""
    import struct
    if file_path in _CAT048_CACHE:
        return _CAT048_CACHE[file_path]
    try:
        with open(file_path, 'rb') as f:
            raw = f.read(15)
        if len(raw) < 15:
            return False
        if raw[0] != 0x30:
            return False
        length = struct.unpack('>H', raw[1:3])[0]
        ok = 15 <= length <= 500
        _CAT048_CACHE[file_path] = ok
        return ok
    except Exception:
        return False

# 扩展名 → 格式描述映射
_EXTENSION_MAP: Dict[str, str] = {
    ".csv": "CSV (逗号分隔)",
    ".tsv": "TSV (制表符分隔)",
    ".txt": "文本文件",
    ".log": "日志文件",
    ".nmea": "NMEA 0183 海用报文",
    ".gpx": "GPS Exchange Format (XML)",
    ".kml": "Google Earth KML (XML/ZIP)",
    ".json": "JSON 结构化数据",
    ".xml": "XML 标记语言",
    ".yaml": "YAML 结构化配置",
    ".yml": "YAML 结构化配置",
    ".h5": "HDF5 层次化数据格式",
    ".hdf5": "HDF5 层次化数据格式",
    ".mat": "MATLAB .mat 格式",
    ".xlsx": "Excel Open XML 格式",
    ".xls": "Excel 97-2003 格式",
    ".pkl": "Python Pickle 序列化",
    ".parquet": "Apache Parquet 列式存储",
    ".feather": "Apache Feather 列式存储",
    ".zip": "ZIP 压缩包",
    ".gz": "GZIP 压缩文件",
    ".bz2": "BZIP2 压缩文件",
    ".png": "PNG 图片",
    ".jpg": "JPEG 图片",
    ".jpeg": "JPEG 图片",
    ".pdf": "PDF 文档",
    ".geojson": "GeoJSON 地理数据",
    ".shp": "Shapefile 矢量数据",
}

# Python 内置 csv 模块可识别的方言分隔符
_DIALECT_SEPARATORS = [",", "\t", ";", "|", " "]


@dataclass
class DetectedFormat:
    """完整的文件格式检测结果。"""
    file_path: str = ""

    # 基础
    extension: str = ""
    extension_description: str = ""
    is_binary: bool = False
    file_size: int = 0

    # 编码
    encoding: str = "utf-8"
    encoding_confidence: float = 0.0

    # 文本检测
    is_text: bool = True
    line_count: int = 0
    sample_lines: List[str] = field(default_factory=list)

    # CSV/分隔符检测
    separator: str = ","
    has_header: bool = True
    header_rows: int = 1
    column_names: List[str] = field(default_factory=list)
    column_count: int = 0
    total_rows: int = 0

    # 魔数检测
    magic_signature: str = ""
    magic_description: str = ""

    # 时间列检测
    time_column: Optional[str] = None
    lat_column: Optional[str] = None
    lon_column: Optional[str] = None

    # 源类型推测
    suggested_source_type: str = "csv"
    suggested_template: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "file_path": self.file_path,
            "extension": self.extension,
            "extension_description": self.extension_description,
            "is_binary": self.is_binary,
            "file_size": self.file_size,
            "encoding": self.encoding,
            "encoding_confidence": self.encoding_confidence,
            "is_text": self.is_text,
            "line_count": self.line_count,
            "separator": self.separator,
            "has_header": self.has_header,
            "header_rows": self.header_rows,
            "column_names": self.column_names,
            "column_count": self.column_count,
            "total_rows": self.total_rows,
            "magic_signature": self.magic_signature,
            "magic_description": self.magic_description,
            "time_column": self.time_column,
            "lat_column": self.lat_column,
            "lon_column": self.lon_column,
            "suggested_source_type": self.suggested_source_type,
            "suggested_template": self.suggested_template,
        }


# ── 智能格式检测器 ──────────────────────────────────────────────

class SmartFormatDetector:
    """智能格式检测器。

    使用级联检测策略：
    1. detect_by_extension() — 扩展名快速判断
    2. detect_by_magic() — 魔数检测（二进制格式）
    3. detect_by_content() — 内容抽样检测（文本格式）
    """

    def __init__(self) -> None:
        pass

    def detect(self, file_path: str,
               sample_size: int = 65536) -> DetectedFormat:
        """一站式检测：返回完整的文件格式检测结果。

        Args:
            file_path: 文件路径
            sample_size: 抽样字节数

        Returns:
            DetectedFormat 实例
        """
        result = DetectedFormat(file_path=file_path)

        # 文件基本信息
        try:
            result.file_size = os.path.getsize(file_path)
        except OSError:
            result.file_size = 0

        # 1. 扩展名检测
        ext_result = self.detect_by_extension(file_path)
        result.extension = ext_result.get("extension", "")
        result.extension_description = ext_result.get("description", "")

        # 2. 魔数检测
        magic_result = self.detect_by_magic(file_path)
        result.magic_signature = magic_result.get("signature", "")
        result.magic_description = magic_result.get("description", "")
        result.is_binary = magic_result.get("is_binary", False)

        # 3. 内容抽样检测（含编码、分隔符、列结构）
        content_result = self.detect_by_content(file_path, sample_size)
        result.encoding = content_result.get("encoding", "utf-8")
        result.encoding_confidence = content_result.get("encoding_confidence", 0.0)
        result.separator = content_result.get("separator", ",")
        result.has_header = content_result.get("has_header", True)
        result.header_rows = content_result.get("header_rows", 1)
        result.column_names = content_result.get("column_names", [])
        result.column_count = content_result.get("column_count", 0)
        result.total_rows = content_result.get("total_rows", 0)
        result.line_count = content_result.get("line_count", 0)
        result.sample_lines = content_result.get("sample_lines", [])
        result.is_text = content_result.get("is_text", True)
        result.time_column = content_result.get("time_column")
        result.lat_column = content_result.get("lat_column")
        result.lon_column = content_result.get("lon_column")

        # 4. 自动推测源类型
        result.suggested_source_type = self._suggest_source_type(result)

        return result

    # ── 扩展名检测 ──────────────────────────────────────────

    def detect_by_extension(self, file_path: str) -> Dict[str, Any]:
        """根据文件扩展名快速判断格式。

        Returns:
            {"extension": ".csv", "description": "CSV (逗号分隔)"}
        """
        ext = os.path.splitext(file_path)[-1].lower()
        desc = _EXTENSION_MAP.get(ext, "未知格式")
        return {"extension": ext, "description": desc}

    # ── 魔数检测 ────────────────────────────────────────────

    def detect_by_magic(self, file_path: str,
                        max_bytes: int = 256) -> Dict[str, Any]:
        """通过文件头部魔数检测二进制格式。

        Returns:
            {"signature": "ZIP", "description": "ZIP", "is_binary": True}
        """
        result: Dict[str, Any] = {
            "signature": "",
            "description": "",
            "is_binary": False,
        }

        if not os.path.exists(file_path):
            return result

        try:
            with open(file_path, "rb") as f:
                header = f.read(max_bytes)

            # 是否为二进制
            result["is_binary"] = b"\x00" in header[:512]

            for sig_name, (magic, offset, desc) in _MAGIC_SIGNATURES.items():
                if len(header) >= offset + len(magic):
                    if header[offset:offset + len(magic)] == magic:
                        result["signature"] = sig_name
                        result["description"] = desc
                        result["is_binary"] = True
                        break

            # CAT-048 检测（需验证长度字段）
            if not result["signature"] and _check_cat048(file_path):
                result["signature"] = "CAT048"
                result["description"] = "CAT-048 ATC雷达数据"
                result["is_binary"] = True
        except OSError:
            pass

        return result

    # ── 内容检测 ────────────────────────────────────────────

    def detect_by_content(self, file_path: str,
                          sample_size: int = 65536) -> Dict[str, Any]:
        """通过内容抽样检测编码、分隔符、列名等。

        Returns:
            包含各项检测结果的字典
        """
        result: Dict[str, Any] = {
            "encoding": "utf-8",
            "encoding_confidence": 0.0,
            "is_text": True,
            "separator": ",",
            "has_header": True,
            "header_rows": 1,
            "column_names": [],
            "column_count": 0,
            "total_rows": 0,
            "line_count": 0,
            "sample_lines": [],
            "time_column": None,
            "lat_column": None,
            "lon_column": None,
        }

        if not os.path.exists(file_path):
            return result

        # 1. 编码检测
        encoding, confidence = self._detect_encoding(file_path, sample_size)
        result["encoding"] = encoding
        result["encoding_confidence"] = confidence

        # 2. 读取样本
        try:
            raw_sample, text_sample, line_count = self._read_sample(
                file_path, encoding, sample_size
            )
            result["is_text"] = True
            result["line_count"] = line_count
            result["sample_lines"] = text_sample[:20]
        except (UnicodeDecodeError, LookupError):
            result["is_text"] = False
            return result

        # 3. 二进制魔数检查（覆盖内容检测中的二进制）
        with open(file_path, "rb") as f:
            header = f.read(512)
        if b"\x00" in header:
            result["is_text"] = False
            return result

        # 4. 分隔符检测
        if text_sample:
            separator = self._detect_separator(text_sample)
            result["separator"] = separator

            # 5. CSV 解析列名
            col_result = self._parse_columns(text_sample, separator)
            result["column_names"] = col_result["column_names"]
            result["column_count"] = col_result["column_count"]
            result["has_header"] = col_result["has_header"]
            result["header_rows"] = col_result["header_rows"]
            result["total_rows"] = col_result["total_rows"]

            # 6. 关键列检测
            if result["column_names"]:
                cols_lower = [c.lower().strip() for c in result["column_names"]]
                col_originals = result["column_names"]
                idx = self._find_key_column_idx(
                    cols_lower,
                    ["time", "timestamp", "时间", "datetime", "帧时间", "起始时间"]
                )
                result["time_column"] = col_originals[idx] if idx is not None else None
                idx = self._find_key_column_idx(
                    cols_lower,
                    ["lat", "latitude", "纬度"]
                )
                result["lat_column"] = col_originals[idx] if idx is not None else None
                idx = self._find_key_column_idx(
                    cols_lower,
                    ["lon", "lng", "longitude", "经度"]
                )
                result["lon_column"] = col_originals[idx] if idx is not None else None

        return result

    # ── 编码检测 ────────────────────────────────────────────

    def _detect_encoding(self, file_path: str,
                         sample_size: int = 65536) -> Tuple[str, float]:
        """检测文件编码。优先使用 chardet，回退常见编码探测。"""
        try:
            with open(file_path, "rb") as f:
                raw = f.read(sample_size)

            # 尝试使用 chardet
            try:
                import chardet
                det = chardet.detect(raw)
                if det and det.get("encoding"):
                    enc = det["encoding"]
                    conf = det.get("confidence", 0.0)
                    # 归一化编码名
                    enc = enc.lower().replace(" ", "-")
                    if conf > 0.3:
                        return enc, conf
            except ImportError:
                pass

            # 手动探测常用编码
            encodings = ["utf-8", "utf-8-sig", "gbk", "gb2312", "gb18030",
                         "latin-1", "shift_jis", "euc-kr", "big5", "utf-16"]
            for enc in encodings:
                try:
                    raw.decode(enc)
                    confidence = 0.9 if enc == "utf-8" else 0.6
                    return enc, confidence
                except (UnicodeDecodeError, LookupError):
                    continue
            return "latin-1", 0.1  # 兜底

        except OSError:
            return "utf-8", 0.0

    def _read_sample(self, file_path: str, encoding: str,
                     sample_size: int) -> Tuple[bytes, List[str], int]:
        """读取文件样本，返回 (raw_bytes, text_lines, line_count)。"""
        with open(file_path, "rb") as f:
            raw = f.read(sample_size)

        # 解码为文本
        try:
            text = raw.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            text = raw.decode("utf-8", errors="replace")

        lines = text.splitlines()
        return raw, lines, len(lines)

    # ── 分隔符检测 ──────────────────────────────────────────

    def _detect_separator(self, lines: List[str]) -> str:
        """智能检测分隔符。"""
        if not lines:
            return ","

        # 跳过空行和注释行
        data_lines = [l for l in lines if l.strip() and not l.strip().startswith(("#", "//", "/*"))]
        if not data_lines:
            return ","

        # 对每个候选分隔符统计得分
        sep_scores: Dict[str, float] = {}
        for sep in _DIALECT_SEPARATORS:
            n_cols_list = []
            for line in data_lines[:10]:  # 前10行
                # 用 csv.reader 解析
                if sep == " ":
                    # 空格分隔：需要特殊处理（连续空格视为一个）
                    import re as _re
                    parts = _re.split(r"\s+", line.strip())
                else:
                    try:
                        reader = csv.reader([line], delimiter=sep)
                        parts = next(reader)
                    except Exception:
                        parts = [line]
                n_cols_list.append(len(parts))

            if n_cols_list:
                # 评分：列数一致性和平均列数
                consistency = n_cols_list.count(n_cols_list[0]) / len(n_cols_list)
                avg_cols = sum(n_cols_list) / len(n_cols_list)
                score = consistency * 10 + avg_cols * 3
                # 分隔符本身出现次数（希望分隔符在每行出现较多）
                sep_count = sum(line.count(sep) for line in data_lines[:5])
                score += min(sep_count / 5, 20)
                sep_scores[sep] = score

        if not sep_scores:
            return ","

        # 取最高分
        best_sep = max(sep_scores, key=sep_scores.get)
        score = sep_scores[best_sep]

        # 如果逗号和制表符分数接近，检查实际列数是否一致
        if best_sep in (",", "\t") and "," in sep_scores and "\t" in sep_scores:
            ratio = sep_scores[","] / max(sep_scores["\t"], 0.01)
            # 制表符胜出条件：分数明显更高，或列数更合理（>1）
            if sep_scores["\t"] > sep_scores[","] * 1.2:
                return "\t"

        # 如果空格分隔得分最高且列数>=3，可能是空格分隔
        if best_sep == " " and score > 5:
            return " "

        # 检查管道符 |
        if "|" in "".join(data_lines[:3]):
            # 测试管道符
            n_cols = []
            for line in data_lines[:5]:
                n_cols.append(len(line.split("|")))
            if n_cols and max(n_cols) >= 3 and n_cols.count(n_cols[0]) / len(n_cols) > 0.6:
                return "|"

        return best_sep if best_sep != " " else ","

    def _parse_columns(self, lines: List[str],
                       separator: str) -> Dict[str, Any]:
        """解析列名、列数、是否含表头。"""
        result: Dict[str, Any] = {
            "column_names": [],
            "column_count": 0,
            "has_header": True,
            "header_rows": 1,
            "total_rows": 0,
        }

        if not lines:
            return result

        # 跳过空行和注释
        data_lines = []
        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith(("#", "//")):
                continue
            data_lines.append(stripped)

        if not data_lines:
            return result

        # 用 csv.reader 解析
        try:
            reader = csv.reader(data_lines, delimiter=separator)
            rows = list(reader)
        except Exception:
            rows = [line.split(separator) for line in data_lines]

        if not rows:
            return result

        result["total_rows"] = len(rows)

        # 检查第一行是否为表头
        first_row = rows[0]
        result["column_names"] = [c.strip().lstrip("\ufeff") for c in first_row]
        result["column_count"] = len(first_row)

        # 判断表头：第一行包含更多非数字字符 or 已知关键词
        if len(rows) >= 2:
            header_keywords = {"time", "lat", "lon", "mmsi", "speed", "course",
                               "timestamp", "id", "name", "type", "frame",
                               "帧", "时间", "纬度", "经度", "目标", "航速", "航向"}
            first_text = sum(1 for c in first_row if c.strip().lower() in header_keywords)
            first_nonnum = sum(1 for c in first_row if not _is_numeric(c.strip()))
            second_nonnum = sum(1 for c in rows[1] if not _is_numeric(c.strip()))
            # 第一行更多非数字字符 or 包含表头关键词 → 有表头
            result["has_header"] = (first_nonnum >= second_nonnum) or (first_text > 0)
        else:
            # 只有一行数据 → 有表头（单行数据大概率是表头）
            has_num = any(_is_numeric(c.strip()) for c in first_row)
            result["has_header"] = not has_num

        return result

    def _find_key_column_idx(self, col_names_lower: List[str],
                             keywords: List[str]) -> Optional[int]:
        """在列名列表中查找关键词匹配的列索引。"""
        best_idx = None
        best_priority = -1
        for i, c in enumerate(col_names_lower):
            for pi, kw in enumerate(keywords):
                if c == kw and pi > best_priority:
                    best_idx, best_priority = i, pi
                elif best_idx is None and (c.startswith(kw) or kw in c):
                    if pi > best_priority:
                        best_idx, best_priority = i, pi
        return best_idx

    # ── 源类型推测 ──────────────────────────────────────────

    def _suggest_source_type(self, result: DetectedFormat) -> str:
        """根据检测结果推测源类型。"""
        # 0. 非文本文件（二进制）
        if not result.is_text:
            ext = result.extension.lower()
            # CAT-048 雷达数据
            if result.magic_signature == "CAT048":
                return "radar"
            if ext in ('.dat', '.data', '.bin', '.raw'):
                return "dat"
            return "binary"

        fname = os.path.basename(result.file_path).lower()
        cols_lower = [c.lower().strip() for c in result.column_names]

        # 1. 文件名关键词
        if any(kw in fname for kw in ("radar", "lidar", "plot", "target")):
            return "radar"
        if any(kw in fname for kw in ("ais", "nmea", "vdm", "ship")):
            return "ais"
        if any(kw in fname for kw in ("gps", "gpx", "rmc")):
            return "gps"

        # 2. 扩展名
        ext = result.extension.lower()
        if ext in (".nmea",):
            return "ais"

        # 3. 列名关键词
        radar_keywords = {"目标方位", "目标距离", "帧序号", "方位", "距离", "azimuth", "range"}
        ais_keywords = {"mmsi", "sog", "cog", "纬度", "经度", "latitude", "longitude"}
        radar_hits = sum(1 for c in cols_lower if any(k in c for k in radar_keywords))
        ais_hits = sum(1 for c in cols_lower if any(k in c for k in ais_keywords))

        if radar_hits >= 2 and radar_hits > ais_hits:
            return "radar"
        if ais_hits >= 2:
            return "ais"

        return "csv"

    def suggest_template(self, result: DetectedFormat) -> str:
        """根据检测结果推荐配置模板名（需 ConfigManager 配合）。"""
        source_type = result.suggested_source_type
        template_map = {
            "radar": "radar_default",
            "ais": "ais_default",
            "gps": "gps_default",
            "csv": "csv_default",
        }
        return template_map.get(source_type, "csv_default")


def _is_numeric(s: str) -> bool:
    """判断字符串是否为数值。"""
    if not s:
        return False
    try:
        float(s)
        return True
    except ValueError:
        return False
