"""
测试 SmartFormatDetector 的格式检测功能。
"""

# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 荣火
from __future__ import annotations
import os
import tempfile
import pytest

from seasync.core.format_detector import SmartFormatDetector, DetectedFormat


class TestDetectByExtension:
    """测试扩展名检测。"""

    def test_csv_extension(self):
        detector = SmartFormatDetector()
        result = detector.detect_by_extension("data.csv")
        assert result["extension"] == ".csv"
        assert "CSV" in result["description"]

    def test_nmea_extension(self):
        detector = SmartFormatDetector()
        result = detector.detect_by_extension("track.nmea")
        assert result["extension"] == ".nmea"
        assert "NMEA" in result["description"]

    def test_hdf5_extension(self):
        detector = SmartFormatDetector()
        result = detector.detect_by_extension("data.h5")
        assert result["extension"] == ".h5"
        assert "HDF5" in result["description"]

    def test_unknown_extension(self):
        detector = SmartFormatDetector()
        result = detector.detect_by_extension("data.xyz")
        assert result["extension"] == ".xyz"
        assert "未知" in result["description"] or "未知" in result["description"]


class TestDetectByContent:
    """测试内容抽样检测。"""

    @pytest.fixture
    def csv_file_basic(self):
        """基本 CSV 文件。"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv",
                                         delete=False, encoding="utf-8") as f:
            f.write("time,lat,lon,speed,course\n")
            f.write("2025-01-01 10:00:00,37.5,121.4,12.5,90.0\n")
            f.write("2025-01-01 10:01:00,37.6,121.5,12.3,91.0\n")
            f.write("2025-01-01 10:02:00,37.7,121.6,12.1,92.0\n")
            path = f.name
        yield path
        os.unlink(path)

    @pytest.fixture
    def csv_file_tab_sep(self):
        """制表符分隔的 CSV。"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".tsv",
                                         delete=False, encoding="utf-8") as f:
            f.write("time\tlat\tlon\tspeed\n")
            f.write("2025-01-01 10:00:00\t37.5\t121.4\t12.5\n")
            f.write("2025-01-01 10:01:00\t37.6\t121.5\t12.3\n")
            path = f.name
        yield path
        os.unlink(path)

    @pytest.fixture
    def csv_file_chinese(self):
        """中文列名 CSV。"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv",
                                         delete=False, encoding="utf-8-sig") as f:
            f.write("帧序号,起始时间,目标方位(°),目标距离(米),目标类型\n")
            f.write("1,2025-03-05 10:35:00,8.0,3875.0,AT\n")
            f.write("2,2025-03-05 10:35:05,8.1,3876.0,AT\n")
            path = f.name
        yield path
        os.unlink(path)

    @pytest.fixture
    def csv_file_gbk(self):
        """GBK 编码的 CSV。"""
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
            content = "时间,纬度,经度,航速\n2025-01-01,37.5,121.4,12.5\n".encode("gbk")
            f.write(content)
            path = f.name
        yield path
        os.unlink(path)

    @pytest.fixture
    def csv_file_semicolon(self):
        """分号分隔的 CSV。"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv",
                                         delete=False, encoding="utf-8") as f:
            f.write("time;lat;lon;speed\n")
            f.write("2025-01-01;37.5;121.4;12.5\n")
            path = f.name
        yield path
        os.unlink(path)

    def test_detect_encoding_utf8(self, csv_file_basic):
        detector = SmartFormatDetector()
        result = detector.detect(csv_file_basic)
        assert result.encoding.startswith("utf-8") or "utf" in result.encoding
        assert result.encoding_confidence > 0

    def test_detect_separator_comma(self, csv_file_basic):
        detector = SmartFormatDetector()
        result = detector.detect(csv_file_basic)
        assert result.separator == ","

    def test_detect_separator_tab(self, csv_file_tab_sep):
        detector = SmartFormatDetector()
        result = detector.detect(csv_file_tab_sep)
        assert result.separator == "\t"

    def test_detect_separator_semicolon(self, csv_file_semicolon):
        detector = SmartFormatDetector()
        result = detector.detect(csv_file_semicolon)
        assert result.separator == ";"

    def test_detect_columns(self, csv_file_basic):
        detector = SmartFormatDetector()
        result = detector.detect(csv_file_basic)
        assert result.column_count == 5
        assert "time" in result.column_names
        assert "lat" in result.column_names
        assert "lon" in result.column_names

    def test_detect_chinese_columns(self, csv_file_chinese):
        detector = SmartFormatDetector()
        result = detector.detect(csv_file_chinese)
        assert result.column_count == 5
        assert "帧序号" in result.column_names
        assert "目标方位(°)" in result.column_names

    def test_detect_key_columns(self, csv_file_basic):
        detector = SmartFormatDetector()
        result = detector.detect(csv_file_basic)
        assert result.time_column == "time"
        assert result.lat_column == "lat"
        assert result.lon_column == "lon"

    def test_detect_header(self, csv_file_basic):
        detector = SmartFormatDetector()
        result = detector.detect(csv_file_basic)
        assert result.has_header is True
        assert result.header_rows == 1

    def test_detect_not_binary(self, csv_file_basic):
        detector = SmartFormatDetector()
        result = detector.detect(csv_file_basic)
        assert result.is_binary is False
        assert result.is_text is True

    def test_suggest_source_type_radar(self, csv_file_chinese):
        detector = SmartFormatDetector()
        result = detector.detect(csv_file_chinese)
        assert result.suggested_source_type == "radar"

    def test_suggest_source_type_csv(self, csv_file_basic):
        detector = SmartFormatDetector()
        result = detector.detect(csv_file_basic)
        assert result.suggested_source_type in ("csv", "ais")

    def test_suggest_template(self, csv_file_basic):
        detector = SmartFormatDetector()
        result = detector.detect(csv_file_basic)
        template = detector.suggest_template(result)
        assert isinstance(template, str)
        assert "_default" in template or template == ""

    def test_detect_encoding_gbk(self, csv_file_gbk):
        detector = SmartFormatDetector()
        result = detector.detect(csv_file_gbk)
        # 可能检测到 gbk 或 gb2312
        assert "gb" in result.encoding

    def test_file_not_exist(self):
        detector = SmartFormatDetector()
        result = detector.detect("/not/exist/file.csv")
        assert result.file_size == 0
        assert result.column_count == 0

    def test_total_rows(self, csv_file_basic):
        detector = SmartFormatDetector()
        result = detector.detect(csv_file_basic)
        assert result.total_rows == 4  # 表头 + 3行数据


class TestDetectByMagic:
    """测试魔数检测。"""

    @pytest.fixture
    def zip_file(self):
        """创建一个小型 ZIP 文件用于测试。"""
        import zipfile
        with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as f:
            path = f.name
        with zipfile.ZipFile(path, "w") as zf:
            zf.writestr("test.txt", "hello")
        yield path
        os.unlink(path)

    @pytest.fixture
    def gzip_file(self):
        """创建一个小型 GZIP 文件。"""
        import gzip
        with tempfile.NamedTemporaryFile(suffix=".gz", delete=False) as f:
            path = f.name
        with gzip.open(path, "wt") as gf:
            gf.write("hello world")
        yield path
        os.unlink(path)

    def test_detect_zip_magic(self, zip_file):
        detector = SmartFormatDetector()
        result = detector.detect_by_magic(zip_file)
        assert result["signature"] == "ZIP" or result["signature"] == "KML/ZIP"
        assert result["is_binary"] is True

    def test_detect_gzip_magic(self, gzip_file):
        detector = SmartFormatDetector()
        result = detector.detect_by_magic(gzip_file)
        assert result["signature"] == "GZIP"
        assert result["is_binary"] is True

    def test_magic_not_found(self):
        detector = SmartFormatDetector()
        # 不存在的文件
        result = detector.detect_by_magic("/nonexistent/file.xyz")
        assert result["signature"] == ""


class TestDetectedFormat:
    """测试 DetectedFormat 数据类。"""

    def test_to_dict(self):
        fmt = DetectedFormat(
            file_path="/test/data.csv",
            extension=".csv",
            extension_description="CSV",
            encoding="utf-8",
            encoding_confidence=0.95,
            separator=",",
            column_names=["time", "lat", "lon"],
            column_count=3,
            total_rows=100,
            suggested_source_type="csv",
        )
        d = fmt.to_dict()
        assert d["file_path"] == "/test/data.csv"
        assert d["encoding"] == "utf-8"
        assert d["column_count"] == 3
        assert d["suggested_source_type"] == "csv"

    def test_default_values(self):
        fmt = DetectedFormat()
        assert fmt.file_path == ""
        assert fmt.encoding == "utf-8"
        assert fmt.separator == ","
        assert fmt.is_text is True
        assert fmt.is_binary is False
        assert fmt.column_names == []
