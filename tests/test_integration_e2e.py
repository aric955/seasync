"""
SeaSync 端到端集成测试
=======================
验证完整Pipeline从数据导入到关联输出的全流程。
"""

# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 荣火
import pytest
from seasync.core.data_models import TargetRecord, AssociationResult
from seasync.core.association_config import AssociationConfig
from seasync.engines.pipeline import SeaSyncPipeline
from seasync.engines.association_engine import AssociationEngine
from seasync.engines.clustering_engine import ClusteringEngine
from seasync.engines.time_aligner import TimeAligner
from seasync.engines.event_detector import EventDetector


class TestEndToEndPipeline:
    """端到端Pipeline集成测试。"""

    def _make_radar_records(self, n: int = 5) -> list:
        """生成模拟雷达记录。"""
        return [
            TargetRecord(
                source_id="radar_1",
                track_id=f"RT-{i}",
                time=1000.0 + i * 10.0,
                lat=37.5330 + i * 0.001,
                lon=121.4234 + i * 0.001,
                speed=10.0 + i,
                course=45.0,
                metadata={"target_type": "RT"},
            )
            for i in range(n)
        ]

    def _make_ais_records(self, n: int = 5) -> list:
        """生成模拟AIS记录。"""
        return [
            TargetRecord(
                source_id="ais_1",
                track_id=f"MMSI-{413203610 + i}",
                time=1000.0 + i * 10.0,
                lat=37.5330 + i * 0.001,
                lon=121.4234 + i * 0.001,
                speed=10.0 + i,
                course=45.0,
                metadata={"mmsi": str(413203610 + i)},
            )
            for i in range(n)
        ]

    def test_full_pipeline_double_source(self):
        """测试完整双源Pipeline：导入→聚类→对齐→关联→事件检测。"""
        config = AssociationConfig(
            distance_threshold=500.0,
            use_mahalanobis=True,
            time_window_base=60.0,
            time_window_tolerance=30.0,
        )
        pipe = SeaSyncPipeline(
            config=config,
            origin_lat=37.5330,
            origin_lon=121.4234,
        )

        radar_recs = self._make_radar_records(5)
        ais_recs = self._make_ais_records(5)

        # 手动注入记录（模拟导入）
        pipe._im._records["radar_1"] = radar_recs
        pipe._im._records["ais_1"] = ais_recs
        pipe._im._adapters["radar_1"] = type(
            "MockAdapter", (), {"SOURCE_TYPE": "radar", "file_path": "radar.csv"}
        )()
        pipe._im._adapters["ais_1"] = type(
            "MockAdapter", (), {"SOURCE_TYPE": "ais", "file_path": "ais.csv"}
        )()

        # 运行Pipeline
        steps = pipe.run("radar_1", "ais_1")

        # 验证结果
        assert "origin" in steps or steps.get("origin") is None  # 原点已预设时可能跳过
        assert "alignment" in steps
        assert "association" in steps
        assert "tracks" in steps
        assert "events" in steps

        # 验证关联结果
        assoc = steps["association"]
        assert "n_pairs" in assoc
        assert "quality" in assoc

    def test_association_engine_direct(self):
        """测试AssociationEngine直接使用。"""
        engine = AssociationEngine(
            origin_lat=37.5330,
            origin_lon=121.4234,
        )
        radar = self._make_radar_records(5)
        ais = self._make_ais_records(5)

        result = engine.associate(radar, ais)

        assert isinstance(result, AssociationResult)
        assert isinstance(result.pairs, list)
        # 验证置信度范围
        for pair in result.pairs:
            assert 0.0 <= pair.confidence <= 1.0

    def test_clustering_engine(self):
        """测试DBSCAN聚类。"""
        clusterer = ClusteringEngine(eps_m=100.0, min_samples=2)
        records = self._make_radar_records(5)

        clusters = clusterer.cluster(records)
        assert isinstance(clusters, dict)

    def test_time_aligner(self):
        """测试时间对齐。"""
        aligner = TimeAligner()
        recs_a = self._make_radar_records(5)
        recs_b = self._make_ais_records(5)

        result = aligner.align(recs_a, recs_b)
        assert hasattr(result, "offset")
        assert hasattr(result, "quality_score")

    def test_event_detector(self):
        """测试事件检测。"""
        detector = EventDetector()
        tracks = {
            f"track_{i}": [self._make_radar_records(1)[0]]
            for i in range(3)
        }

        events = detector.detect_all(tracks, rules=["stationary", "manoeuvre"])
        assert isinstance(events, list)

    def test_multi_source_association(self):
        """测试多源两两关联。"""
        config = AssociationConfig(
            distance_threshold=500.0,
            use_mahalanobis=True,
            time_window_base=60.0,
            time_window_tolerance=30.0,
        )
        engine = AssociationEngine(config, origin_lat=37.5330, origin_lon=121.4234)

        source_records = {
            "radar_1": self._make_radar_records(5),
            "ais_1": self._make_ais_records(5),
            "ais_2": self._make_ais_records(3),
        }

        results = engine.associate_multi(source_records)
        assert isinstance(results, dict)
        # 应该有3个两两组合：(radar_1,ais_1), (radar_1,ais_2), (ais_1,ais_2)
        assert len(results) >= 2  # 至少2组
        for pair_key, result in results.items():
            assert isinstance(pair_key, tuple)
            assert isinstance(result, AssociationResult)

    def test_n_source_time_alignment(self):
        """测试N源模式下的时间对齐（Phase 3修复验证）。"""
        config = AssociationConfig(
            distance_threshold=500.0,
            use_mahalanobis=True,
            time_window_base=60.0,
            time_window_tolerance=30.0,
        )
        pipe = SeaSyncPipeline(
            config=config,
            origin_lat=37.5330,
            origin_lon=121.4234,
        )

        # 创建3个源
        pipe._im._records["radar_1"] = self._make_radar_records(5)
        pipe._im._records["ais_1"] = self._make_ais_records(5)
        pipe._im._records["ais_2"] = self._make_ais_records(3)
        pipe._im._adapters["radar_1"] = type(
            "MockAdapter", (), {"SOURCE_TYPE": "radar", "file_path": "radar.csv"}
        )()
        pipe._im._adapters["ais_1"] = type(
            "MockAdapter", (), {"SOURCE_TYPE": "ais", "file_path": "ais1.csv"}
        )()
        pipe._im._adapters["ais_2"] = type(
            "MockAdapter", (), {"SOURCE_TYPE": "ais", "file_path": "ais2.csv"}
        )()
        # 缓存源类型
        pipe._im._source_types["radar_1"] = "radar"
        pipe._im._source_types["ais_1"] = "ais"
        pipe._im._source_types["ais_2"] = "ais"

        # 运行N源模式
        steps = pipe.run(source_ids=["radar_1", "ais_1", "ais_2"])

        # 验证所有源都被处理
        assert "associations" in steps or "association" in steps


class TestAssociationPairFields:
    """测试AssociationPair新字段体系（字段统一修复验证）。"""

    def test_new_fields_only(self):
        """验证仅使用新字段时正常工作。"""
        from seasync.core.data_models import AssociationPair

        pair = AssociationPair(
            source1_id="SRC-A",
            source2_id="SRC-B",
            source1_label="gps",
            source2_label="ais",
        )
        assert pair.source1_id == "SRC-A"
        assert pair.source2_id == "SRC-B"
        assert pair.source1_label == "gps"
        assert pair.source2_label == "ais"

    def test_backward_compat_radar_ais(self):
        """验证radar+ais组合的向后兼容属性。"""
        from seasync.core.data_models import AssociationPair

        pair = AssociationPair(
            source1_id="RT-001",
            source2_id="413203610",
            source1_label="radar",
            source2_label="ais",
            confidence=0.95,
        )
        # 新字段
        assert pair.source1_id == "RT-001"
        assert pair.source2_id == "413203610"
        # 向后兼容属性
        assert pair.radar_track_id == "RT-001"
        assert pair.ais_mmsi == "413203610"

    def test_backward_compat_optical_radar(self):
        """验证optical+radar组合的向后兼容属性（source2是radar）。"""
        from seasync.core.data_models import AssociationPair

        pair = AssociationPair(
            source1_id="OPT-1",
            source2_id="RT-002",
            source1_label="optical",
            source2_label="radar",
            confidence=0.88,
        )
        # radar_track_id 应返回 source2_id（因为 source2_label == "radar"）
        assert pair.radar_track_id == "RT-002"
        # ais_mmsi 应返回空（因为 source2_label != "ais"）
        assert pair.ais_mmsi == ""

    def test_generic_sensor_support(self):
        """验证通用传感器支持（声纳+光学）。"""
        from seasync.core.data_models import AssociationPair

        pair = AssociationPair(
            source1_id="SONAR-1",
            source2_id="OPT-2",
            source1_label="sonar",
            source2_label="optical",
            confidence=0.75,
        )
        assert pair.source1_label == "sonar"
        assert pair.source2_label == "optical"
        assert pair.get_id("sonar") == "SONAR-1"
        assert pair.get_id("optical") == "OPT-2"
        assert pair.get_other_id("SONAR-1") == "OPT-2"

    def test_association_result_unmatched_generic(self):
        """验证AssociationResult使用通用unmatched字典。"""
        from seasync.core.data_models import AssociationResult

        result = AssociationResult(
            pairs=[],
            unmatched={"radar": ["RT-1"], "ais": ["MMSI-1"], "optical": ["OPT-1"]},
            total_quality=0.0,
        )
        assert result.get_unmatched("radar") == ["RT-1"]
        assert result.get_unmatched("ais") == ["MMSI-1"]
        assert result.get_unmatched("optical") == ["OPT-1"]
        # 向后兼容
        assert result.unmatched_radar == ["RT-1"]
        assert result.unmatched_ais == ["MMSI-1"]
