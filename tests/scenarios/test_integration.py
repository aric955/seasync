"""
SeaSync V2.2 端到端集成测试 — 模拟真实海试数据全流程。
"""

# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 荣火
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))  # tests/
import pytest
from test_helpers import generate_radar_csv, generate_ais_simple_csv


class TestPipelineIntegration:
    """SeaSyncPipeline 完整流程：数据注册 → 原点推算 → 关联 → 一键运行。"""

    @pytest.fixture
    def known_origin(self):
        return (37.53297, 121.42323)

    def test_add_source_roundtrip(self, tmpdir, known_origin):
        """add_source 注册后 list_sources 能正确返回。"""
        from seasync.engines import SeaSyncPipeline
        radar_path = generate_radar_csv(str(tmpdir), n_frames=3,
                                        origin_lat=known_origin[0],
                                        origin_lon=known_origin[1])
        ais_path = generate_ais_simple_csv(str(tmpdir))

        pipe = SeaSyncPipeline()
        sid_r = pipe.add_source(radar_path, source_type="radar")
        sid_a = pipe.add_source(ais_path, source_type="ais")

        sources = pipe.list_sources()
        assert len(sources) == 2
        sids = [s["source_id"] for s in sources]
        assert sid_r in sids
        assert sid_a in sids

    def test_auto_detect_origin_returns_valid(self, tmpdir, known_origin):
        """auto_detect_origin 返回非空且离真实原点不远。"""
        from seasync.engines import SeaSyncPipeline
        radar_path = generate_radar_csv(str(tmpdir), n_frames=5,
                                        origin_lat=known_origin[0],
                                        origin_lon=known_origin[1])
        ais_path = generate_ais_simple_csv(str(tmpdir))

        pipe = SeaSyncPipeline()
        sid_r = pipe.add_source(radar_path, source_type="radar")
        sid_a = pipe.add_source(ais_path, source_type="ais")

        origin = pipe.auto_detect_origin(sid_r, sid_a)
        assert origin[0] is not None
        assert origin[1] is not None
        # 误差不超 0.01 度（约 1 km）
        assert abs(origin[0] - known_origin[0]) < 0.01
        assert abs(origin[1] - known_origin[1]) < 0.01

    def test_associate_filtered_yields_pairs(self, tmpdir, known_origin):
        """associate_filtered 自动过滤 RT 后产出关联对。"""
        from seasync.engines import SeaSyncPipeline
        radar_path = generate_radar_csv(str(tmpdir), n_frames=5,
                                        origin_lat=known_origin[0],
                                        origin_lon=known_origin[1])
        ais_path = generate_ais_simple_csv(str(tmpdir))

        pipe = SeaSyncPipeline()
        sid_r = pipe.add_source(radar_path, source_type="radar")
        sid_a = pipe.add_source(ais_path, source_type="ais")

        result = pipe.associate_filtered(sid_r, sid_a)
        assert len(result.pairs) > 0, "应有至少一个关联对"
        assert 0.0 <= result.total_quality <= 1.0

        # 验证有匹配对：AT目标（MMSI=413203610）应匹配到AIS
        matched_at = [p for p in result.pairs if str(p.ais_mmsi) == "413203610"]
        assert len(matched_at) > 0, "AT目标(MMSI=413203610) 应有匹配"
        assert matched_at[0].confidence > 0.5

    def test_preprocess_radar_returns_clusters(self, tmpdir, known_origin):
        """雷达预处理（聚类）返回非空簇。"""
        from seasync.engines import SeaSyncPipeline
        radar_path = generate_radar_csv(str(tmpdir), n_frames=3,
                                        origin_lat=known_origin[0],
                                        origin_lon=known_origin[1])
        ais_path = generate_ais_simple_csv(str(tmpdir))
        pipe = SeaSyncPipeline()
        sid_r = pipe.add_source(radar_path, source_type="radar")
        pipe.add_source(ais_path, source_type="ais")
        clusters = pipe.preprocess_radar(sid_r)
        assert isinstance(clusters, dict)
        assert len(clusters) > 0, "应有至少一个聚类"

    def test_align_sources_returns_result(self, tmpdir, known_origin):
        """时间对齐返回 AlignmentResult，offset 符合预期。"""
        from seasync.engines import SeaSyncPipeline
        radar_path = generate_radar_csv(str(tmpdir), n_frames=3,
                                        origin_lat=known_origin[0],
                                        origin_lon=known_origin[1])
        ais_path = generate_ais_simple_csv(str(tmpdir))
        pipe = SeaSyncPipeline()
        sid_r = pipe.add_source(radar_path, source_type="radar")
        sid_a = pipe.add_source(ais_path, source_type="ais")

        align = pipe.align_sources(sid_a, sid_r)
        assert align is not None
        assert hasattr(align, "offset")
        assert hasattr(align, "needs_manual")

    def test_run_full_workflow(self, tmpdir, known_origin):
        """一键 run() 产出所有中间步骤结果，无异常。"""
        from seasync.engines import SeaSyncPipeline
        radar_path = generate_radar_csv(str(tmpdir), n_frames=5,
                                        origin_lat=known_origin[0],
                                        origin_lon=known_origin[1])
        ais_path = generate_ais_simple_csv(str(tmpdir))

        pipe = SeaSyncPipeline()
        sid_r = pipe.add_source(radar_path, source_type="radar")
        sid_a = pipe.add_source(ais_path, source_type="ais")

        steps = pipe.run(sid_r, sid_a)

        # 自动推算原点
        assert "origin" in steps
        lat, lon = steps["origin"]
        assert lat is not None and lon is not None

        # 时间对齐
        assert "alignment" in steps
        assert steps["alignment"] is not None

        # 聚类
        assert "clusters" in steps
        assert len(steps["clusters"]) > 0

        # 关联
        assoc = steps["association"]
        assert assoc["n_pairs"] > 0
        assert 0.0 <= assoc["quality"] <= 1.0

        # 轨迹
        assert "tracks" in steps
        assert steps["tracks"]["n_tracks"] > 0

        # 事件检测
        assert "events" in steps
        assert steps["events"]["n_events"] >= 0
        assert isinstance(steps["events"]["by_type"], dict)

    def test_run_with_preset_origin(self, tmpdir, known_origin):
        """预设原点时 run() 跳过 auto_detect，流程仍完整。"""
        from seasync.engines import SeaSyncPipeline
        radar_path = generate_radar_csv(str(tmpdir), n_frames=3,
                                        origin_lat=known_origin[0],
                                        origin_lon=known_origin[1])
        ais_path = generate_ais_simple_csv(str(tmpdir))

        pipe = SeaSyncPipeline(origin_lat=known_origin[0],
                               origin_lon=known_origin[1])
        sid_r = pipe.add_source(radar_path, source_type="radar")
        sid_a = pipe.add_source(ais_path, source_type="ais")

        steps = pipe.run(sid_r, sid_a)
        # 有预设原点时 steps 里不应有 "origin"
        assert "origin" not in steps or steps["origin"] == (known_origin[0], known_origin[1])
        assert steps["association"]["n_pairs"] > 0

    def test_associate_filtered_with_preset_origin(self, tmpdir, known_origin):
        """预设原点 + associate_filtered：跳过原点推算，直接关联。"""
        from seasync.engines import SeaSyncPipeline
        radar_path = generate_radar_csv(str(tmpdir), n_frames=5,
                                        origin_lat=known_origin[0],
                                        origin_lon=known_origin[1])
        ais_path = generate_ais_simple_csv(str(tmpdir))

        pipe = SeaSyncPipeline(origin_lat=known_origin[0],
                               origin_lon=known_origin[1])
        sid_r = pipe.add_source(radar_path, source_type="radar")
        sid_a = pipe.add_source(ais_path, source_type="ais")

        result = pipe.associate_filtered(sid_r, sid_a)
        assert len(result.pairs) > 0
        assert 0.0 <= result.total_quality <= 1.0

    def test_filter_by_target_type_accuracy(self, tmpdir, known_origin):
        """按类型过滤雷达目标，确保过滤正确。"""
        from seasync.engines import SeaSyncPipeline
        radar_path = generate_radar_csv(str(tmpdir), n_frames=3,
                                        origin_lat=known_origin[0],
                                        origin_lon=known_origin[1])
        pipe = SeaSyncPipeline()
        sid_r = pipe.add_source(radar_path, source_type="radar")

        rt = pipe.filter_by_target_type(sid_r, ["RT"])
        at = pipe.filter_by_target_type(sid_r, ["AT"])
        cdt = pipe.filter_by_target_type(sid_r, ["CDT"])
        assert len(rt) > 0
        assert len(at) > 0
        assert len(cdt) > 0
        assert all(r.metadata["target_type"] == "RT" for r in rt)
        assert all(r.metadata["target_type"] == "AT" for r in at)
        assert all(r.metadata["target_type"] == "CDT" for r in cdt)
        # 各类型之间无交叉
        rt_ids = set(r.track_id for r in rt)
        at_ids = set(r.track_id for r in at)
        cdt_ids = set(r.track_id for r in cdt)
        assert rt_ids.isdisjoint(at_ids)
        assert rt_ids.isdisjoint(cdt_ids)

    def test_build_tracks_from_ais(self, tmpdir, known_origin):
        """build_tracks 从 AIS 源构建 TrackManager。"""
        from seasync.engines import SeaSyncPipeline
        radar_path = generate_radar_csv(str(tmpdir), n_frames=3,
                                        origin_lat=known_origin[0],
                                        origin_lon=known_origin[1])
        ais_path = generate_ais_simple_csv(str(tmpdir))
        pipe = SeaSyncPipeline()
        pipe.add_source(radar_path, source_type="radar")
        sid_a = pipe.add_source(ais_path, source_type="ais")
        tm = pipe.build_tracks(sid_a)
        assert len(tm) > 0
        summary = tm.summary()
        assert summary["n_tracks"] >= 1
