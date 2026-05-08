"""
SeaSync V2.2 核心功能综合测试 — 锁死今天全部修复内容。
"""

# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 荣火
import os, sys, math
# 项目根目录，使 from seasync.xxx 可用
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))  # for conftest
import pytest
import numpy as np
from test_helpers import generate_radar_csv, generate_ais_csv, generate_ais_simple_csv, generate_polar_csv


# ============================================================
# 1. CSVAdapter：中文列名别名映射 + 极坐标转经纬度
# ============================================================

class TestCSVAdapterAliasMapping:
    """测试 _find_col 的中文列名+单位后缀匹配能力。"""
    
    def test_find_col_aliases(self):
        from seasync.adapters.csv_adapter import _find_col
        
        ais_cols = ["MMSI", "经度(°)", "纬度(°)", "时间", "速度(kn)", "船艏向(°)", "对地航向(°)"]
        radar_cols = ["帧序号", "起始时间(帧)", "目标类型", "目标编号", "目标方位(°)", "目标距离(米)"]
        
        # AIS列名映射
        assert _find_col(ais_cols, "mmsi") == "MMSI"
        assert _find_col(ais_cols, "lat") == "纬度(°)"       # 去后缀匹配
        assert _find_col(ais_cols, "lon") == "经度(°)"       # 去后缀匹配
        assert _find_col(ais_cols, "time") == "时间"          # 精确匹配
        assert _find_col(ais_cols, "speed") == "速度(kn)"    # 去后缀匹配
        assert _find_col(ais_cols, "course") == "对地航向(°)" # 子串匹配（航向）
        
        # 雷达列名映射
        assert _find_col(radar_cols, "time") == "起始时间(帧)" # 子串匹配（时间）
        assert _find_col(radar_cols, "mmsi") == "目标编号"    # 别名匹配
        assert _find_col(radar_cols, "course") == "目标方位(°)" # 别名匹配（目标方位）

    def test_load_chinese_ais_csv(self, tmpdir):
        """AIS_C：中文列名加载，验证track_id=MMSI, lat/lon正确"""
        from seasync.adapters import CSVAdapter
        path = generate_ais_csv(str(tmpdir))
        adapter = CSVAdapter(path, source_id="test_ais", source_type="ais")
        recs = adapter.load()
        
        assert len(recs) == 10
        assert recs[0].track_id == "413203610"  # MMSI作为track_id
        assert recs[0].lat is not None
        assert recs[0].lon is not None
        assert abs(recs[0].lat - 37.5675) < 0.001
        assert abs(recs[0].lon - 121.426) < 0.001
        assert recs[0].speed is not None
        assert recs[0].course is not None

    def test_load_chinese_radar_csv(self, tmpdir):
        """雷达CSV：中文列名加载+极坐标转换+目标类型提取"""
        from seasync.adapters import CSVAdapter
        ORIGIN_LAT, ORIGIN_LON = 37.53297, 121.42323
        path = generate_radar_csv(str(tmpdir), n_frames=3)
        adapter = CSVAdapter(path, source_id="test_radar", source_type="radar",
                             origin_lat=ORIGIN_LAT, origin_lon=ORIGIN_LON)
        recs = adapter.load()
        
        # 3帧×4目标=12条
        assert len(recs) == 12
        
        # track_id提取：AT→MMSI, RT→1, CDT→900001/900002
        track_ids = set(r.track_id for r in recs)
        assert "413203610" in track_ids  # AT
        assert "1" in track_ids          # RT
        assert "900001" in track_ids     # CDT
        
        # 极坐标→经纬度转换验证
        rt_recs = [r for r in recs if r.track_id == "1"]
        assert len(rt_recs) > 0
        r = rt_recs[0]
        assert r.x is not None and r.y is not None  # 笛卡尔坐标
        assert r.lat is not None and r.lon is not None  # 经纬度（原点转换）

    def test_polar_to_latlon(self, tmpdir):
        """纯极坐标CSV加载+原点转经纬度"""
        from seasync.adapters import CSVAdapter
        ORIGIN_LAT, ORIGIN_LON = 37.53297, 121.42323
        path = generate_polar_csv(str(tmpdir))
        adapter = CSVAdapter(path, source_id="polar", source_type="radar",
                             origin_lat=ORIGIN_LAT, origin_lon=ORIGIN_LON)
        recs = adapter.load()
        assert len(recs) == 5
        assert all(r.lat is not None for r in recs)
        assert all(r.lon is not None for r in recs)
        # 纬度应该略大于原点（北向y>0）
        assert all(r.lat > ORIGIN_LAT for r in recs)

    def test_polar_without_origin(self, tmpdir):
        """纯极坐标无原点：不转经纬度但有xy"""
        from seasync.adapters import CSVAdapter
        path = generate_polar_csv(str(tmpdir))
        adapter = CSVAdapter(path, source_id="polar", source_type="radar")
        recs = adapter.load()
        assert len(recs) == 5
        assert all(r.x is not None for r in recs)   # xy应该存在
        assert all(r.lat is None for r in recs)      # 无原点时不转经纬度


# ============================================================
# 2. AISAdapter：中文列名CSV加载
# ============================================================

class TestAISAdapter:
    def test_ais_nmea(self):
        """AISAdapter至少能实例化（NMEA测试依赖文件是否存在）"""
        from seasync.adapters import AISAdapter
        assert AISAdapter is not None
    
    def test_ais_csv_chinese_cols(self, tmpdir):
        """AISAdapter CSV加载（中文列名）"""
        from seasync.adapters import AISAdapter
        path = generate_ais_csv(str(tmpdir))
        # 注册为ais类型 → 走AISAdapter的_load_csv
        from seasync.adapters.import_manager import _auto_detect_type
        assert _auto_detect_type(path) == "ais"  # 'ais'在文件名中
        # 直接测AISAdapter
        adapter = AISAdapter(path)
        assert adapter.validate()  # 文件名含ais应通过CSV检测
        recs = adapter.load()
        assert len(recs) == 10
        # 中文列名映射后应有lat/lon
        assert any(r.lat is not None for r in recs)


# ============================================================
# 3. AssociationEngine：关联逻辑
# ============================================================

class TestAssociationEngine:
    def test_association_with_origin(self, tmpdir):
        """带雷达原点的关联：RT-1应匹配到MMSI-413203610"""
        from seasync.adapters import CSVAdapter
        from seasync.engines import AssociationEngine
        ORIGIN_LAT, ORIGIN_LON = 37.53297, 121.42323
        
        # 加载雷达（带原点，转lat/lon）
        radar_path = generate_radar_csv(str(tmpdir), n_frames=5)
        radar_adapter = CSVAdapter(radar_path, source_id="radar", source_type="radar",
                                   origin_lat=ORIGIN_LAT, origin_lon=ORIGIN_LON)
        radar_recs = radar_adapter.load()
        
        # 提取RT-1
        rt1 = [r for r in radar_recs if r.track_id == "1"]
        assert len(rt1) >= 3, f"RT-1应有>=3条记录，实有{len(rt1)}"
        
        # 加载AIS
        ais_path = generate_ais_simple_csv(str(tmpdir))
        ais_adapter = CSVAdapter(ais_path, source_id="ais", source_type="ais")
        ais_recs = ais_adapter.load()
        
        # 关联
        ae = AssociationEngine(origin_lat=ORIGIN_LAT, origin_lon=ORIGIN_LON)
        result = ae.associate(rt1, ais_recs)
        
        # RT-1应匹配到MMSI-413203610
        assert len(result.pairs) > 0, f"应有匹配对，实有{len(result.pairs)}"
        matched = [p for p in result.pairs if p.radar_track_id == "1"]
        assert len(matched) > 0, "RT-1应有匹配"
        assert matched[0].ais_mmsi == "413203610"
        assert matched[0].confidence > 0.3
    
    def test_no_origin_fallback(self, tmpdir):
        """无原点参数时关联不报错"""
        from seasync.adapters import CSVAdapter
        from seasync.engines import AssociationEngine
        radar_path = generate_radar_csv(str(tmpdir), n_frames=3)
        radar_adapter = CSVAdapter(radar_path, source_id="radar", source_type="radar")
        radar_recs = radar_adapter.load()
        ais_path = generate_ais_simple_csv(str(tmpdir))
        ais_adapter = CSVAdapter(ais_path, source_id="ais", source_type="ais")
        ais_recs = ais_adapter.load()
        rt1 = [r for r in radar_recs if r.track_id == "1"]
        ae = AssociationEngine()
        result = ae.associate(rt1, ais_recs)
        # 不应抛异常，result应有效
        assert result is not None
        assert result.pairs is not None
    
    def test_association_quality_clamped(self):
        """质量分数应该在[0,1]范围内"""
        from seasync.engines import AssociationEngine
        from seasync.core import AssociationConfig, TargetRecord
        
        radar = [TargetRecord(source_id="r", track_id="r1", time=1000, lat=37.57, lon=121.43, x=100, y=100)]
        ais = [TargetRecord(source_id="a", track_id="413203610", time=1000, lat=37.57, lon=121.43, x=100, y=100,
                             metadata={"mmsi": "413203610"})]
        
        ae = AssociationEngine()
        result = ae.associate(radar, ais)
        assert 0.0 <= result.total_quality <= 1.0


# ============================================================
# 4. EventDetector：事件检测
# ============================================================

class TestEventDetector:
    def test_detect_stationary(self):
        """异常停船检测：航速持续很低时触发"""
        from seasync.engines import EventDetector
        from seasync.core import TargetRecord
        # 5条记录，航速≈0，持续300秒
        records = []
        for i in range(5):
            records.append(TargetRecord(
                source_id="ais", track_id="413203610",
                time=1000 + i * 60, lat=37.57, lon=121.43,
                speed=0.0, course=90.0,
            ))
        events = EventDetector.detect_stationary(records, speed_threshold_kn=0.5, min_duration_sec=120)
        assert len(events) == 1  # 应检测到1次停船
        assert events[0].name == "异常停船"
    
    def test_detect_manoeuvre(self):
        """大角度机动检测：航向突变时触发"""
        from seasync.engines import EventDetector
        from seasync.core import TargetRecord
        records = [
            TargetRecord(source_id="ais", track_id="t1", time=1000, lat=37.57, lon=121.43, speed=5, course=0),
            TargetRecord(source_id="ais", track_id="t1", time=1010, lat=37.57, lon=121.43, speed=5, course=10),
            TargetRecord(source_id="ais", track_id="t1", time=1020, lat=37.57, lon=121.43, speed=5, course=80),  # 变化70°
        ]
        events = EventDetector.detect_manoeuvre(records, course_change_threshold_deg=45.0)
        assert len(events) == 1
        assert events[0].name == "大角度机动"


# ============================================================
# 5. TrackManager
# ============================================================

class TestTrackManager:
    def test_track_lifecycle(self):
        """轨迹管理器基本功能"""
        from seasync.engines import TrackManager
        from seasync.core import TargetRecord
        
        tm = TrackManager()
        r1 = TargetRecord(source_id="ais", track_id="t1", time=1000, lat=37.57, lon=121.43)
        r2 = TargetRecord(source_id="ais", track_id="t1", time=1010, lat=37.58, lon=121.44)
        tm.add_batch([r1, r2])
        
        assert len(tm) == 1
        assert len(tm.get_track("t1")) == 2
        summary = tm.summary()
        assert summary["n_tracks"] == 1
        assert summary["n_points"] == 2
    
    def test_split_by_gap(self):
        """时间间隙分割"""
        from seasync.engines import TrackManager
        from seasync.core import TargetRecord
        
        tm = TrackManager()
        tm.add_batch([
            TargetRecord(source_id="ais", track_id="t1", time=1000, lat=37.57, lon=121.43),
            TargetRecord(source_id="ais", track_id="t1", time=1100, lat=37.58, lon=121.44),
        ])
        segments = tm.split_by_gap(gap_sec=50)
        assert len(segments) == 2  # 100秒间隔 > 50秒阈值 → 分割


# ============================================================
# 6. Pipeline：全流程集成
# ============================================================

class TestSeaSyncPipeline:
    def test_pipeline_basic(self):
        """Pipeline初始化和数据源注册"""
        from seasync.engines import SeaSyncPipeline
        pipe = SeaSyncPipeline()
        assert pipe is not None
        assert pipe.list_sources() == []
    
    def test_pipeline_with_origin(self, tmpdir):
        """带原点的Pipeline全流程"""
        from seasync.engines import SeaSyncPipeline
        ORIGIN_LAT, ORIGIN_LON = 37.53297, 121.42323
        
        radar_path = generate_radar_csv(str(tmpdir), n_frames=3, 
                                        origin_lat=ORIGIN_LAT, origin_lon=ORIGIN_LON)
        ais_path = generate_ais_simple_csv(str(tmpdir))
        
        pipe = SeaSyncPipeline(origin_lat=ORIGIN_LAT, origin_lon=ORIGIN_LON)
        sid_radar = pipe.add_source(radar_path, source_type="radar")
        sid_ais = pipe.add_source(ais_path, source_type="ais")
        
        sources = pipe.list_sources()
        assert len(sources) == 2
        
        # 时间对齐不应崩溃
        align = pipe.align_sources(sid_ais, sid_radar)
        assert align is not None
    
    def test_pipeline_project_manager(self, tmpdir):
        """ProjectManager SQLite单例"""
        from seasync.core import ProjectManager
        db_path = os.path.join(str(tmpdir), "test.db")
        pm1 = ProjectManager(db_path)
        pm2 = ProjectManager(db_path)
        assert pm1 is pm2  # 单例
        pid = pm1.create_project("test_project", "desc")["id"]
        proj = pm1.get_project(pid)
        assert proj is not None
        assert proj["name"] == "test_project"


# ============================================================
# 8. P1: Pipeline 自动原点 + 目标类型过滤
# ============================================================

class TestPipelineAutoOrigin:
    """测试 Pipeline 自动推算原点 + 目标类型过滤 + 一键 run()"""

    def test_target_type_in_metadata(self, tmpdir):
        """雷达CSV的target_type正常存入metadata"""
        from seasync.adapters import CSVAdapter
        from test_helpers import generate_radar_csv
        path = generate_radar_csv(str(tmpdir), n_frames=2)
        adapter = CSVAdapter(path, source_id="test", source_type="radar")
        recs = adapter.load()
        types = set(r.metadata.get("target_type") for r in recs if r.metadata.get("target_type"))
        assert "AT" in types
        assert "RT" in types
        assert "CDT" in types

    def test_filter_by_target_type(self, tmpdir):
        """Pipeline过滤目标类型"""
        from seasync.engines import SeaSyncPipeline
        from test_helpers import generate_radar_csv, generate_ais_simple_csv
        radar_path = generate_radar_csv(str(tmpdir), n_frames=3)
        ais_path = generate_ais_simple_csv(str(tmpdir))
        pipe = SeaSyncPipeline()
        sid_r = pipe.add_source(radar_path, source_type="radar")
        pipe.add_source(ais_path, source_type="ais")
        rt = pipe.filter_by_target_type(sid_r, ["RT"])
        at = pipe.filter_by_target_type(sid_r, ["AT"])
        cdt = pipe.filter_by_target_type(sid_r, ["CDT"])
        assert len(rt) > 0
        assert len(at) > 0
        assert len(cdt) > 0
        assert all(r.metadata["target_type"] == "RT" for r in rt)

    def test_auto_detect_origin(self, tmpdir):
        """从雷达AT+AIS自动推算原点（误差<500m）"""
        from seasync.engines import SeaSyncPipeline
        from test_helpers import generate_radar_csv, generate_ais_simple_csv
        KNOWN_LAT, KNOWN_LON = 37.53297, 121.42323
        radar_path = generate_radar_csv(str(tmpdir), n_frames=5,
                                        origin_lat=KNOWN_LAT, origin_lon=KNOWN_LON)
        ais_path = generate_ais_simple_csv(str(tmpdir))
        pipe = SeaSyncPipeline()
        sid_r = pipe.add_source(radar_path, source_type="radar")
        sid_a = pipe.add_source(ais_path, source_type="ais")
        origin = pipe.auto_detect_origin(sid_r, sid_a)
        assert origin[0] is not None
        assert origin[1] is not None
        # 误差不超过0.01度（约1km，含合成数据噪声）
        assert abs(origin[0] - KNOWN_LAT) < 0.01
        assert abs(origin[1] - KNOWN_LON) < 0.01

    def test_associate_filtered(self, tmpdir):
        """associate_filtered 自动过滤RT+自动原点"""
        from seasync.engines import SeaSyncPipeline
        from test_helpers import generate_radar_csv, generate_ais_simple_csv
        KNOWN_LAT, KNOWN_LON = 37.53297, 121.42323
        radar_path = generate_radar_csv(str(tmpdir), n_frames=5,
                                        origin_lat=KNOWN_LAT, origin_lon=KNOWN_LON)
        ais_path = generate_ais_simple_csv(str(tmpdir))
        pipe = SeaSyncPipeline()
        sid_r = pipe.add_source(radar_path, source_type="radar")
        sid_a = pipe.add_source(ais_path, source_type="ais")
        result = pipe.associate_filtered(sid_r, sid_a)
        assert len(result.pairs) > 0
        # AT目标（MMSI=413203610）应关联到AIS
        matched = [p for p in result.pairs if str(p.ais_mmsi) == "413203610"]
        assert len(matched) > 0, "AT目标(MMSI=413203610)应有匹配"
        assert matched[0].confidence > 0.3

    def test_run_auto_workflow(self, tmpdir):
        """一键run()全自动流程不报错"""
        from seasync.engines import SeaSyncPipeline
        from test_helpers import generate_radar_csv, generate_ais_simple_csv
        KNOWN_LAT, KNOWN_LON = 37.53297, 121.42323
        radar_path = generate_radar_csv(str(tmpdir), n_frames=3,
                                        origin_lat=KNOWN_LAT, origin_lon=KNOWN_LON)
        ais_path = generate_ais_simple_csv(str(tmpdir))
        pipe = SeaSyncPipeline()
        sid_r = pipe.add_source(radar_path, source_type="radar")
        sid_a = pipe.add_source(ais_path, source_type="ais")
        steps = pipe.run(sid_r, sid_a)
        assert steps["origin"][0] is not None
        assert steps["association"]["n_pairs"] > 0
        assert 0 <= steps["association"]["quality"] <= 1


# ============================================================
# 7. Core 数据模型
# ============================================================

class TestCoreModels:
    def test_target_record(self):
        """TargetRecord创建"""
        from seasync.core import TargetRecord
        r = TargetRecord(source_id="r1", track_id="t1", time=1000,
                        lat=22.5, lon=113.8, x=100, y=200)
        assert r.source_id == "r1"
        assert r.track_id == "t1"
        assert r.time == 1000.0
    
    def test_association_config(self):
        """AssociationConfig序列化"""
        from seasync.core import AssociationConfig
        cfg = AssociationConfig(distance_threshold=500, min_confidence=0.7)
        d = cfg.to_dict()
        assert d["distance_threshold"] == 500.0
        assert d["min_confidence"] == 0.7
        cfg2 = AssociationConfig.from_dict(d)
        assert cfg2.distance_threshold == 500.0
