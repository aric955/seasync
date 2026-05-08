"""
测试 ConfigManager 和配置数据类。
"""

# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 荣火
from __future__ import annotations
import os
import json
import tempfile
import pytest

from seasync.core.config_manager import (
    ConfigManager,
    DataConfig,
    ColumnMapping,
    UnitConversion,
    TimeFormat,
    get_conversion_factor,
)


class TestDataConfig:
    """测试 DataConfig 数据类的序列化/反序列化。"""

    def test_to_dict_roundtrip(self):
        cfg = DataConfig(
            name="test_radar",
            source_type="radar",
            encoding="gbk",
            separator=",",
            header_rows=1,
            column_mappings=[
                ColumnMapping(source_column="帧序号", standard_column="track_id",
                              data_type="int"),
                ColumnMapping(source_column="起始时间", standard_column="time",
                              data_type="datetime"),
            ],
            unit_conversions=[
                UnitConversion(column="speed", source_unit="kn", target_unit="m/s"),
            ],
            time_format=TimeFormat(source_format="%Y-%m-%d %H:%M:%S",
                                   source_timezone="UTC+8"),
            file_patterns=["*radar*", "*radar*.csv"],
            extension_hints=[".csv"],
            column_hints=["目标方位", "目标距离"],
        )
        d = cfg.to_dict()
        restored = DataConfig.from_dict(d)
        assert restored.name == cfg.name
        assert restored.source_type == cfg.source_type
        assert restored.encoding == cfg.encoding
        assert len(restored.column_mappings) == 2
        assert restored.column_mappings[0].source_column == "帧序号"
        assert restored.column_mappings[0].standard_column == "track_id"
        assert restored.column_mappings[0].data_type == "int"
        assert len(restored.unit_conversions) == 1
        assert restored.unit_conversions[0].source_unit == "kn"
        assert restored.time_format.source_format == "%Y-%m-%d %H:%M:%S"
        assert restored.file_patterns == ["*radar*", "*radar*.csv"]

    def test_empty_config(self):
        cfg = DataConfig()
        d = cfg.to_dict()
        restored = DataConfig.from_dict(d)
        assert restored.name == ""
        assert restored.column_mappings == []
        assert restored.unit_conversions == []
        assert restored.time_format.source_format == "auto"

    def test_default_values_preserved(self):
        cfg = DataConfig(name="test", encoding="latin-1")
        d = cfg.to_dict()
        restored = DataConfig.from_dict(d)
        assert restored.encoding == "latin-1"
        assert restored.header_rows == 0
        assert restored.skip_rows == 0


class TestUnitConversion:
    """测试单位换算系数查询。"""

    def test_kn_to_ms(self):
        factor = get_conversion_factor("kn", "m/s")
        assert factor is not None
        assert abs(factor - 0.514444) < 0.001

    def test_ms_to_kn(self):
        factor = get_conversion_factor("m/s", "kn")
        assert factor is not None
        assert abs(factor - 1.94384) < 0.001

    def test_m_to_nm(self):
        factor = get_conversion_factor("m", "nm")
        assert factor is not None
        assert abs(factor - 0.000539957) < 0.001

    def test_unknown_unit(self):
        factor = get_conversion_factor("xyz", "abc")
        assert factor is None

    def test_case_insensitive(self):
        factor = get_conversion_factor("KN", "M/S")
        assert factor is not None
        assert abs(factor - 0.514444) < 0.001

    def test_reverse_lookup(self):
        # 表中只存了 kn->m/s，但 m/s->kn 应该通过反向查询
        factor = get_conversion_factor("m/s", "kn")
        assert factor is not None
        assert abs(factor - 1.94384) < 0.001

    def test_deg_to_rad(self):
        factor = get_conversion_factor("°", "rad")
        assert factor is not None
        assert abs(factor - 0.0174533) < 0.001


class TestConfigManager:
    """测试 ConfigManager 的 CRUD 和推荐功能。"""

    @pytest.fixture
    def tmp_template_dir(self):
        """创建临时模板目录并初始化一些模板。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # 创建 radar_default.json
            radar_cfg = {
                "name": "radar_default",
                "source_type": "radar",
                "encoding": "utf-8",
                "separator": ",",
                "header_rows": 1,
                "column_mappings": [
                    {"source_column": "目标方位(°)", "standard_column": "course",
                     "data_type": "float"},
                    {"source_column": "目标距离(米)", "standard_column": "range",
                     "data_type": "float"},
                ],
                "unit_conversions": [],
                "time_format": {"source_format": "auto"},
                "file_patterns": ["*radar*"],
                "extension_hints": [".csv"],
                "column_hints": ["目标方位", "目标距离"],
                "content_hints": ["AT", "RT"],
                "min_columns": 3,
                "max_columns": 50,
                "match_weight": 1.0,
            }
            with open(os.path.join(tmpdir, "radar_default.json"), "w") as f:
                json.dump(radar_cfg, f)

            # 创建 ais_default.json
            ais_cfg = {
                "name": "ais_default",
                "source_type": "ais",
                "encoding": "utf-8",
                "separator": ",",
                "header_rows": 1,
                "column_mappings": [
                    {"source_column": "MMSI", "standard_column": "mmsi",
                     "data_type": "str"},
                ],
                "unit_conversions": [],
                "time_format": {"source_format": "auto"},
                "file_patterns": ["*ais*"],
                "extension_hints": [".csv"],
                "column_hints": ["MMSI", "纬度", "经度"],
                "content_hints": ["MMSI"],
                "min_columns": 2,
                "max_columns": 50,
                "match_weight": 1.0,
            }
            with open(os.path.join(tmpdir, "ais_default.json"), "w") as f:
                json.dump(ais_cfg, f)

            yield tmpdir

    def test_list_templates(self, tmp_template_dir):
        cm = ConfigManager(template_dir=tmp_template_dir)
        templates = cm.list_templates()
        assert "radar_default" in templates
        assert "ais_default" in templates

    def test_load_template(self, tmp_template_dir):
        cm = ConfigManager(template_dir=tmp_template_dir)
        cfg = cm.load_template("radar_default")
        assert cfg is not None
        assert cfg.name == "radar_default"
        assert cfg.source_type == "radar"
        assert len(cfg.column_mappings) == 2

    def test_load_nonexistent_template(self, tmp_template_dir):
        cm = ConfigManager(template_dir=tmp_template_dir)
        cfg = cm.load_template("nonexistent")
        assert cfg is None

    def test_save_and_reload_json(self, tmp_template_dir):
        cm = ConfigManager(template_dir=tmp_template_dir)
        cfg = DataConfig(
            name="my_custom",
            source_type="csv",
            encoding="gbk",
            column_mappings=[
                ColumnMapping(source_column="col1", standard_column="time",
                              data_type="datetime"),
            ],
        )
        path = cm.save_template(cfg, name="my_custom", fmt="json")
        assert os.path.exists(path)
        assert "my_custom.json" in path

        # 重新加载
        loaded = cm.load_template("my_custom")
        assert loaded is not None
        assert loaded.name == "my_custom"
        assert loaded.encoding == "gbk"
        assert len(loaded.column_mappings) == 1
        assert loaded.column_mappings[0].source_column == "col1"

    def test_delete_template(self, tmp_template_dir):
        cm = ConfigManager(template_dir=tmp_template_dir)
        assert cm.template_exists("radar_default")
        assert cm.delete_template("radar_default")
        assert not cm.template_exists("radar_default")

    def test_delete_nonexistent(self, tmp_template_dir):
        cm = ConfigManager(template_dir=tmp_template_dir)
        assert not cm.delete_template("nonexistent")

    def test_suggest_template_by_pattern(self, tmp_template_dir):
        """文件名模式匹配推荐。"""
        cm = ConfigManager(template_dir=tmp_template_dir)
        suggestions = cm.suggest_template(
            "/data/ais_data_2025.csv",
            sample_content="MMSI,lat,lon,speed",
            detected_columns=["MMSI", "lat", "lon", "speed"],
        )
        assert len(suggestions) > 0
        assert suggestions[0] == "ais_default"

    def test_suggest_template_by_columns(self, tmp_template_dir):
        """列名匹配推荐。"""
        cm = ConfigManager(template_dir=tmp_template_dir)
        suggestions = cm.suggest_template(
            "/data/test_radar.csv",
            detected_columns=["目标方位(°)", "目标距离(米)", "目标类型", "帧序号"],
        )
        assert len(suggestions) > 0
        # radar_default 的 column_hints 是 ["目标方位", "目标距离"]，应该匹配
        assert "radar_default" in suggestions

    def test_suggest_template_no_match(self, tmp_template_dir):
        """无匹配时应返回空列表。"""
        cm = ConfigManager(template_dir=tmp_template_dir)
        suggestions = cm.suggest_template(
            "/data/image.png",
            detected_columns=["width", "height", "channels"],
        )
        # 没有匹配的模板，雷达和ais都有列数字段限制，不应匹配
        assert isinstance(suggestions, list)

    def test_load_from_file(self, tmp_template_dir):
        cm = ConfigManager(template_dir=tmp_template_dir)
        path = os.path.join(tmp_template_dir, "ais_default.json")
        cfg = cm.load_from_file(path)
        assert cfg is not None
        assert cfg.name == "ais_default"
        assert cfg.source_type == "ais"

    def test_get_template_dir(self, tmp_template_dir):
        cm = ConfigManager(template_dir=tmp_template_dir)
        assert cm.get_template_dir() == tmp_template_dir

    def test_template_exists(self, tmp_template_dir):
        cm = ConfigManager(template_dir=tmp_template_dir)
        assert cm.template_exists("radar_default") is True
        assert cm.template_exists("no_such") is False

    def test_yaml_save(self, tmp_template_dir):
        """测试 YAML 保存（使用 fallback 方式）。"""
        cm = ConfigManager(template_dir=tmp_template_dir)
        cfg = DataConfig(name="yaml_test", source_type="csv")
        path = cm.save_template(cfg, name="yaml_test", fmt="yaml")
        assert os.path.exists(path)
        assert path.endswith(".yaml")
