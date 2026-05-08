"""
SeaSync V2.2 可视化输出测试 — 验证图片成功生成且内容有效。
"""

# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 荣火
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))  # tests/
import pytest
from test_helpers import generate_radar_csv, generate_ais_simple_csv


class TestRenderAssociation:
    """render_association 图像生成测试。"""

    ORIGIN_LAT, ORIGIN_LON = 37.53297, 121.42323

    @pytest.fixture
    def loaded_data(self, tmpdir):
        """准备带经纬度的雷达+AIS记录及关联结果。
        
        不预设原点，让 pipeline 在 associate_filtered 内通过 auto_detect_origin
        推算原点并重载适配器（此时记录会带 lat/lon）。
        在 associate_filtered 之后再 get_records 获取含经纬度的完整记录。
        """
        from seasync.engines import SeaSyncPipeline

        radar_path = generate_radar_csv(str(tmpdir), n_frames=5,
                                        origin_lat=self.ORIGIN_LAT,
                                        origin_lon=self.ORIGIN_LON)
        ais_path = generate_ais_simple_csv(str(tmpdir))

        # 不传 origin → auto_detect_origin 推算原点并更新适配器
        pipe = SeaSyncPipeline()
        sid_r = pipe.add_source(radar_path, source_type="radar")
        sid_a = pipe.add_source(ais_path, source_type="ais")

        # associate_filtered 触发 auto_detect → 适配器重载 → 记录带 lat/lon
        result = pipe.associate_filtered(sid_r, sid_a)

        # 此时 get_records 返回含经纬度的记录
        radar_recs = pipe.get_records(sid_r)
        ais_recs = pipe.get_records(sid_a)

        return radar_recs, ais_recs, result

    def test_render_association_to_file(self, tmpdir, loaded_data):
        """render_association 生成关联图，文件存在且 >10KB。"""
        from seasync.visualization import render_association
        radar_recs, ais_recs, result = loaded_data

        out_path = os.path.join(str(tmpdir), "association.png")
        returned = render_association(
            radar_recs, ais_recs,
            assoc_result=result,
            output_path=out_path,
        )
        assert returned == out_path
        assert os.path.isfile(out_path)
        assert os.path.getsize(out_path) > 10 * 1024, \
            f"关联图文件太小: {os.path.getsize(out_path)} bytes"

    def test_render_association_without_result(self, tmpdir, loaded_data):
        """无关联结果时 render_association 仍正常生成图片。"""
        from seasync.visualization import render_association
        radar_recs, ais_recs, _ = loaded_data

        out_path = os.path.join(str(tmpdir), "association_no_result.png")
        returned = render_association(
            radar_recs, ais_recs,
            assoc_result=None,
            output_path=out_path,
        )
        assert returned == out_path
        assert os.path.isfile(out_path)
        assert os.path.getsize(out_path) > 10 * 1024

    def test_render_association_in_memory(self, loaded_data):
        """render_association 无 output_path 时返回 None。"""
        from seasync.visualization import render_association
        radar_recs, ais_recs, result = loaded_data

        ret = render_association(radar_recs, ais_recs, assoc_result=result)
        assert ret is None


class TestRenderTracks:
    """render_tracks 轨迹图生成测试。"""

    ORIGIN_LAT, ORIGIN_LON = 37.53297, 121.42323

    @pytest.fixture
    def track_data(self, tmpdir):
        """加载雷达数据并通过 build_tracks 构建轨迹字典。"""
        from seasync.engines import SeaSyncPipeline

        radar_path = generate_radar_csv(str(tmpdir), n_frames=5,
                                        origin_lat=self.ORIGIN_LAT,
                                        origin_lon=self.ORIGIN_LON)
        ais_path = generate_ais_simple_csv(str(tmpdir))

        pipe = SeaSyncPipeline(origin_lat=self.ORIGIN_LAT,
                               origin_lon=self.ORIGIN_LON)
        pipe.add_source(radar_path, source_type="radar")
        sid_a = pipe.add_source(ais_path, source_type="ais")

        tm = pipe.build_tracks(sid_a)
        tracks = {tid: tm.get_track(tid) for tid in tm.list_track_ids()}
        return tracks

    def test_render_tracks_to_file(self, tmpdir, track_data):
        """render_tracks 生成轨迹图，文件存在且 >10KB。"""
        from seasync.visualization import render_tracks

        out_path = os.path.join(str(tmpdir), "tracks.png")
        returned = render_tracks(track_data, output_path=out_path)
        assert returned == out_path
        assert os.path.isfile(out_path)
        assert os.path.getsize(out_path) > 10 * 1024, \
            f"轨迹图文件太小: {os.path.getsize(out_path)} bytes"

    def test_render_tracks_empty(self, tmpdir):
        """空轨迹字典也应生成有效的图片。"""
        from seasync.visualization import render_tracks

        out_path = os.path.join(str(tmpdir), "empty_tracks.png")
        returned = render_tracks({}, output_path=out_path)
        assert returned == out_path
        assert os.path.isfile(out_path)
        # 空图可能略小，但应仍有内容
        assert os.path.getsize(out_path) > 1024

    def test_render_tracks_with_radar_data(self, tmpdir):
        """用雷达数据构建轨迹并生成图片。"""
        from seasync.engines import SeaSyncPipeline
        from seasync.visualization import render_tracks

        radar_path = generate_radar_csv(str(tmpdir), n_frames=5,
                                        origin_lat=self.ORIGIN_LAT,
                                        origin_lon=self.ORIGIN_LON)

        pipe = SeaSyncPipeline(origin_lat=self.ORIGIN_LAT,
                               origin_lon=self.ORIGIN_LON)
        pipe.add_source(radar_path, source_type="radar")

        tm = pipe.build_tracks()
        tracks = {tid: tm.get_track(tid) for tid in tm.list_track_ids()}
        assert len(tracks) > 0

        out_path = os.path.join(str(tmpdir), "radar_tracks.png")
        returned = render_tracks(tracks, output_path=out_path)
        assert returned == out_path
        assert os.path.isfile(out_path)
        assert os.path.getsize(out_path) > 10 * 1024
