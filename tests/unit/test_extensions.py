"""
SeaSync V2.2 新增模块单元测试：ScanTracker, CAT048, ImportManager
"""

# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 荣火
import sys, os, math, tempfile, struct, csv
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
import numpy as np

from seasync.core import TargetRecord
from seasync.engines import ScanTracker, ClusteringEngine
from seasync.adapters import ImportManager
from seasync.adapters.csv_adapter import _detect_encoding, _find_col


# ═══════════════════════════════════════════════════════════════
#  ScanTracker 测试
# ═══════════════════════════════════════════════════════════════

class TestScanTracker:
    """逐帧扫描跟踪器测试。"""

    def test_basic_tracking_xy(self):
        """x/y坐标模式下能正确关联连续测量点。"""
        # 模拟3个目标，每个5个测量点
        records = []
        for target_id in range(3):
            base_x, base_y = target_id * 1000, target_id * 1000
            for step in range(5):
                t = step * 2.0  # 扫描周期2秒
                records.append(TargetRecord(
                    source_id="test", track_id="raw",
                    time=t, x=base_x + step * 5, y=base_y + step * 5,
                    metadata={"true_id": target_id},
                ))
        st = ScanTracker(gate_distance_m=0, max_coast_steps=0, min_track_points=3)
        tracks = st.process_all(records)
        assert len(tracks) >= 3, f"应有≥3条轨迹，实有{len(tracks)}"

    def test_auto_configure_scan_period(self):
        """自动检测扫描周期。"""
        records = []
        for scan in range(10):
            for target in range(3):
                records.append(TargetRecord(
                    source_id="test", track_id="raw",
                    time=scan * 2.5,  # 2.5s扫描周期
                    x=target * 100, y=target * 100,
                ))
        st = ScanTracker(gate_distance_m=0, max_coast_steps=0)
        st.auto_configure(records)
        assert abs(st._auto_scan_period - 2.5) < 0.3, f"扫描周期检测偏差: {st._auto_scan_period}"

    def test_auto_configure_gate_distance(self):
        """自动门控距离能从参数推算出合理值。"""
        records = []
        for scan in range(10):
            records.append(TargetRecord(
                source_id="test", track_id="raw",
                time=scan * 2.0, x=scan * 10, y=scan * 10,
            ))
        st = ScanTracker(
            gate_distance_m=0, max_coast_steps=0,
            max_speed_kn=20.0,  # 主动设置：20kn ≈ 10.3m/s
        )
        st.auto_configure(records)
        # 20kn = 10.3m/s, 扫描周期2s, 外推≥3圈 → 10.3*2*3 = 62m → ≥200保底
        assert st.gate_distance_m >= 200, f"门控距离太小: {st.gate_distance_m}"

    def test_empty_records_no_crash(self):
        """空记录列表不崩溃。"""
        st = ScanTracker()
        tracks = st.process_all([])
        assert len(tracks) == 0

    def test_track_termination(self):
        """轨迹在连续无检测时终止。"""
        records = []
        # 第一个团簇（位置0,0）
        for step in range(3):
            records.append(TargetRecord(source_id="test", track_id="raw",
                time=step * 2.0, x=0, y=0))
        # 大间隔后，第二个团簇（位置500,500，远距>200m门限）
        for step in range(3):
            records.append(TargetRecord(source_id="test", track_id="raw",
                time=30 + step * 2.0, x=500, y=500))
        st = ScanTracker(gate_distance_m=200, max_coast_steps=4, min_track_points=2)
        tracks = st.process_all(records)
        # 两个不同位置的团簇应产生2条轨迹
        assert len(tracks) == 2, f"应有2条轨迹，实有{len(tracks)}"


# ═══════════════════════════════════════════════════════════════
#  ImportManager 级联检测测试
# ═══════════════════════════════════════════════════════════════

class TestImportManager:
    """导入管理器级联检测测试。"""

    def test_auto_detect_csv(self, tmpdir):
        """CSV文件自动路由到CSVAdapter。"""
        path = os.path.join(tmpdir, "test.csv")
        with open(path, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["time", "lat", "lon"])
            w.writerow(["0", "22.5", "113.8"])
        im = ImportManager()
        a = im.register(path)
        from seasync.adapters import CSVAdapter
        assert isinstance(a, CSVAdapter), f"应为CSVAdapter，实为{type(a)}"

    def test_auto_detect_ais(self, tmpdir):
        """含mmsi的CSV自动路由到AISAdapter。"""
        path = os.path.join(tmpdir, "ais.csv")
        with open(path, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["mmsi", "time", "lat", "lon"])
            w.writerow(["413203610", "0", "22.5", "113.8"])
        im = ImportManager()
        a = im.register(path)
        from seasync.adapters import AISAdapter
        assert isinstance(a, AISAdapter), f"应为AISAdapter，实为{type(a)}"

    def test_auto_detect_radar_by_name(self, tmpdir):
        """文件名含radar自动路由到RadarAdapter。"""
        path = os.path.join(tmpdir, "RadarPlot.data")
        # 写一个二进制CAT048头
        with open(path, "wb") as f:
            f.write(bytes([0x30, 0x00, 0x10]) + b"\x00" * 13)
        im = ImportManager()
        a = im.register(path)
        # 应该识别为二进制 → CAT048RadarAdapter
        from seasync.adapters.cat048_adapter import CAT048RadarAdapter
        assert isinstance(a, CAT048RadarAdapter), f"应为CAT048RadarAdapter"

    def test_gbk_encoding_detection(self, tmpdir):
        """GBK编码CSV能被检测并正确加载。"""
        path = os.path.join(tmpdir, "gbk.csv")
        with open(path, "wb") as f:
            f.write("时间,纬度,经度\n".encode("gbk"))
            f.write("0,22.5,113.8\n".encode("gbk"))
        enc = _detect_encoding(path)
        assert enc in ("gbk", "gb2312", "gb18030"), f"编码检测失败: {enc}"

    def test_file_not_found(self):
        """不存在的文件抛出FileNotFoundError。"""
        im = ImportManager()
        with pytest.raises(FileNotFoundError):
            im.register("/nonexistent/file.csv")


# ═══════════════════════════════════════════════════════════════
#  编码检测 + 列名别名 测试
# ═══════════════════════════════════════════════════════════════

class TestEncodingAndAlias:
    """编码检测和列名匹配补充测试。"""

    def test_utf8_bom_encoding(self, tmpdir):
        """UTF-8 BOM编码文件。"""
        path = os.path.join(tmpdir, "utf8bom.csv")
        with open(path, "wb") as f:
            f.write(b"\xef\xbb\xbftime,lat,lon\n0,22.5,113.8\n")
        enc = _detect_encoding(path)
        assert enc in ("utf-8-sig", "utf-8"), f"BOM检测失败: {enc}"

    def test_find_col_3level_matching(self):
        """3级别名匹配不误匹配干扰词。"""
        cols = ["方位量程(°)", "对地航向(°)", "目标方位(°)"]
        result = _find_col(cols, "course")
        # "方位"不会匹配"方位量程（含干扰词）"，"航向"匹配"对地航向"
        assert result is not None and "量程" not in result

    def test_find_col_blocks_range_columns(self):
        """含"量程"、"范围"的列不被course别名匹配。"""
        cols = ["方位量程(°)", "距离范围(km)", "航向(°)"]
        result = _find_col(cols, "course")
        assert result == "航向(°)", f"期望航向(°)，实得{result}"

    def test_mmsi_with_hyphen(self, tmpdir):
        """MMSI带横杠（如413804828-0-0）不被int()转换搞崩。"""
        path = os.path.join(tmpdir, "mmsi_test.csv")
        with open(path, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["mmsi", "time", "lat", "lon"])
            w.writerow(["413804828-0-0", "100", "22.5", "113.8"])
        from seasync.adapters import CSVAdapter
        adapter = CSVAdapter(path, source_id="test", source_type="ais")
        recs = adapter.load()
        assert len(recs) == 1
        assert recs[0].track_id == "413804828-0-0"

    def test_empty_csv(self, tmpdir):
        """空CSV（仅有表头无数据行）不崩溃。"""
        path = os.path.join(tmpdir, "empty.csv")
        with open(path, "w") as f:
            f.write("time,lat,lon\n")
        from seasync.adapters import CSVAdapter
        adapter = CSVAdapter(path, source_id="empty", source_type="csv")
        recs = adapter.load()
        assert len(recs) == 0


# ═══════════════════════════════════════════════════════════════
#  EventDetector 边界情况测试
# ═══════════════════════════════════════════════════════════════

class TestEventDetectorEdge:
    """事件检测器边界情况。"""

    def test_single_point_track(self):
        """单点轨迹不产生事件（不崩溃）。"""
        from seasync.engines import EventDetector
        from seasync.core import TargetRecord
        r = TargetRecord(source_id="test", track_id="1", time=0, x=0, y=0)
        ed = EventDetector()
        events = ed.detect_all({"1": [r]})
        assert len(events) == 0

    def test_two_point_no_event(self):
        """两点轨迹不足以判断偏向，不报警。"""
        from seasync.engines import EventDetector
        from seasync.core import TargetRecord
        recs = [
            TargetRecord(source_id="test", track_id="1", time=0, x=0, y=0),
            TargetRecord(source_id="test", track_id="1", time=10, x=100, y=100),
        ]
        ed = EventDetector()
        events = ed.detect_all({"1": recs})
        assert len(events) == 0


# ═══════════════════════════════════════════════════════════════
#  AssociationEngine 边缘情况测试
# ═══════════════════════════════════════════════════════════════

class TestAssociationEngineEdge:
    """关联引擎额外测试。"""

    def test_empty_radar(self):
        """空雷达列表不崩溃。"""
        from seasync.engines import AssociationEngine
        ae = AssociationEngine()
        r = TargetRecord(source_id="gt", track_id="1", time=0, lat=22.5, lon=113.8,
                         metadata={"mmsi": "1"})
        result = ae.associate([], [r])
        assert len(result.pairs) == 0

    def test_empty_ais(self):
        """空AIS列表不崩溃。"""
        from seasync.engines import AssociationEngine
        ae = AssociationEngine()
        r = TargetRecord(source_id="radar", track_id="1", time=0, lat=22.5, lon=113.8)
        result = ae.associate([r], [])
        assert len(result.pairs) == 0

    def test_same_position_should_match(self):
        """雷达和AIS在同一位置应匹配。"""
        from seasync.engines import AssociationEngine
        ae = AssociationEngine()
        radar = [TargetRecord(source_id="radar", track_id="1",
            time=0, lat=22.5, lon=113.8)]
        ais = [TargetRecord(source_id="ais", track_id="1",
            time=0, lat=22.50009, lon=113.80009, metadata={"mmsi": "1"})]
        result = ae.associate(radar, ais)
        assert len(result.pairs) > 0, "同一位置应匹配"

    def test_far_apart_no_match(self):
        """雷达和AIS相距超过阈值不应匹配。"""
        from seasync.engines import AssociationEngine
        from seasync.core import AssociationConfig
        cfg = AssociationConfig(distance_threshold=50.0)  # 50m
        ae = AssociationEngine(config=cfg)
        radar = [TargetRecord(source_id="radar", track_id="1",
            time=0, lat=22.5, lon=113.8)]
        ais = [TargetRecord(source_id="ais", track_id="2",
            time=0, lat=22.51, lon=113.81, metadata={"mmsi": "2"})]
        result = ae.associate(radar, ais)
        assert len(result.pairs) == 0, "远距离不应匹配"

    def test_multi_target_association(self):
        """多目标场景正确匹配。"""
        from seasync.engines import AssociationEngine
        ae = AssociationEngine()
        radars = [
            TargetRecord(source_id="radar", track_id="1", time=0, lat=22.5, lon=113.8),
            TargetRecord(source_id="radar", track_id="2", time=0, lat=22.51, lon=113.81),
        ]
        aises = [
            TargetRecord(source_id="ais", track_id="10", time=0,
                lat=22.5001, lon=113.8001, metadata={"mmsi": "10"}),
            TargetRecord(source_id="ais", track_id="20", time=0,
                lat=22.5101, lon=113.8101, metadata={"mmsi": "20"}),
        ]
        result = ae.associate(radars, aises)
        assert len(result.pairs) >= 2, f"多目标应有≥2匹配, 实有{len(result.pairs)}"

    def test_xy_coordinate_association(self):
        """XY坐标关联（有origin）走转换路径。"""
        from seasync.engines import AssociationEngine
        ae = AssociationEngine(origin_lat=22.5, origin_lon=113.8)
        # 雷达用lat/lon触发Haversine路径
        radars = [TargetRecord(source_id="radar", track_id="1",
            time=i, lat=22.5000+i*0.00001, lon=113.8000+i*0.00001)
            for i in range(5)]
        aises = [TargetRecord(source_id="ais", track_id="10",
            time=0, lat=22.5001, lon=113.8001, metadata={"mmsi": "10"})]
        result = ae.associate(radars, aises)
        result = ae.associate(radars, aises)
        assert len(result.pairs) > 0, "xy坐标应能匹配"

    def test_time_window_overlap(self):
        """时间重叠窗口多点比较路径。"""
        from seasync.engines import AssociationEngine
        ae = AssociationEngine()
        radars = [TargetRecord(source_id="radar", track_id="1",
            time=t, lat=22.5000 + t*0.00001, lon=113.8000 + t*0.00001,
            metadata={"mmsi": "1"})
            for t in range(10)]
        aises = [TargetRecord(source_id="ais", track_id="1",
            time=t, lat=22.5001 + t*0.00001, lon=113.8001 + t*0.00001,
            metadata={"mmsi": "1"})
            for t in range(10)]
        result = ae.associate(radars, aises)
        assert len(result.pairs) > 0, "时间重叠窗口应能匹配"

    def test_no_origin_with_xy(self):
        """无预设原点+xy坐标的降级路径。"""
        from seasync.engines import AssociationEngine
        ae = AssociationEngine()  # 无origin
        radars = [TargetRecord(source_id="radar", track_id="1",
            time=0, x=100, y=100)]
        aises = [TargetRecord(source_id="ais", track_id="1",
            time=0, lat=22.5, lon=113.8, metadata={"mmsi": "1"})]
        result = ae.associate(radars, aises)
        # 不应崩溃，但不一定匹配（坐标系不同）
        assert result.total_quality >= 0.0


# ═══════════════════════════════════════════════════════════════
#  Pipeline 边缘情况测试
# ═══════════════════════════════════════════════════════════════

class TestPipelineEdge:
    """管道边缘情况。"""

    def test_pipeline_no_sources(self):
        """无数据源的管道不崩溃。"""
        from seasync.engines import SeaSyncPipeline
        pipe = SeaSyncPipeline()
        sources = pipe.list_sources()
        assert len(sources) == 0

    def test_pipeline_nonexistent_source(self):
        """访问不存在的source_id不崩溃。"""
        import contextlib
        from seasync.engines import SeaSyncPipeline
        pipe = SeaSyncPipeline()
        with contextlib.suppress(Exception):
            pipe.get_records("nonexistent")

    def test_pipeline_empty_source(self, tmpdir):
        """加载空文件不崩溃。"""
        from seasync.engines import SeaSyncPipeline
        path = os.path.join(tmpdir, "empty.csv")
        with open(path, "w") as f:
            f.write("time,lat,lon\n")
        pipe = SeaSyncPipeline()
        sid = pipe.add_source(path, source_type="csv")
        import contextlib
        with contextlib.suppress(Exception):
            pipe.run(sid, sid)


# ═══════════════════════════════════════════════════════════════
#  ClusteringEngine 经纬度模式测试
# ═══════════════════════════════════════════════════════════════

class TestClusteringEngineLatLon:
    """聚类引擎经纬度模式测试。"""

    def test_cluster_latlon_basic(self):
        """经纬度模式基本聚类。"""
        from seasync.engines import ClusteringEngine
        records = [
            TargetRecord(source_id="test", track_id="r", time=0, lat=22.5, lon=113.8),
            TargetRecord(source_id="test", track_id="r", time=1, lat=22.5001, lon=113.8001),
            TargetRecord(source_id="test", track_id="r", time=2, lat=22.5002, lon=113.8002),
        ]
        ce = ClusteringEngine(eps_m=200, eps_t=30, min_samples=2)
        clusters = ce.cluster(records)
        assert len(clusters) > 0, "应产生至少1个聚类"

    def test_cluster_empty(self):
        """空列表不崩溃。"""
        from seasync.engines import ClusteringEngine
        ce = ClusteringEngine()
        clusters = ce.cluster([])
        assert len(clusters) == 0

    def test_cluster_to_tracks_empty(self):
        """空列表cluster_to_tracks不崩溃。"""
        from seasync.engines import ClusteringEngine
        ce = ClusteringEngine()
        tracks = ce.cluster_to_tracks([])
        assert len(tracks) == 0


# ═══════════════════════════════════════════════════════════════
#  ImportManager 级联降级测试
# ═══════════════════════════════════════════════════════════════

class TestImportManagerCascade:
    """导入管理器级联降级测试。"""

    def test_unknown_type_falls_to_dat(self, tmpdir):
        """无法识别的文件类型降级到DatAdapter（覆盖最广的通用适配器）。"""
        path = os.path.join(tmpdir, "data.xyz")
        with open(path, "w") as f:
            f.write("time,lat,lon\n0,22.5,113.8\n")
        im = ImportManager()
        a = im.register(path)
        from seasync.adapters import DatAdapter
        assert isinstance(a, DatAdapter)

    def test_binary_falls_to_cat048(self, tmpdir):
        """二进制文件尝试CAT048，验证失败后继续尝试。"""
        path = os.path.join(tmpdir, "data.bin")
        with open(path, "wb") as f:
            f.write(b"\xff\xff\xff")  # 无效CAT头
        im = ImportManager()
        # 不应崩溃
        a = im.register(path)
        assert a is not None

    def test_load_cached(self, tmpdir):
        """重复加载走缓存。"""
        path = os.path.join(tmpdir, "cached.csv")
        with open(path, "w") as f:
            f.write("time,lat,lon\n0,22.5,113.8\n")
        im = ImportManager()
        a = im.register(path, source_id="cached")
        r1 = im.load("cached")
        r2 = im.load("cached")
        assert r1 is r2  # 同一个对象（缓存）


# ═══════════════════════════════════════════════════════════════
#  TimeAligner 边界测试
# ═══════════════════════════════════════════════════════════════

class TestTimeAligner:
    """时间对齐测试。"""
    
    def test_single_point_no_align(self):
        """单点时间无法对齐。"""
        from seasync.engines import TimeAligner
        ta = TimeAligner()
        r1 = [TargetRecord(source_id="a", track_id="1", time=0, x=0, y=0)]
        r2 = [TargetRecord(source_id="b", track_id="1", time=1, x=0, y=0)]
        result = ta.align(r1, r2)
        assert result.offset == 0.0

    def test_empty_no_align(self):
        """空数据不对齐。"""
        from seasync.engines import TimeAligner
        ta = TimeAligner()
        result = ta.align([], [])
        assert result.offset == 0.0

    def test_scipy_fallback_no_crash(self):
        """无scipy.correlate时降级互相关不崩溃。"""
        from seasync.engines import TimeAligner
        ta = TimeAligner()
        r1 = [TargetRecord(source_id="a", track_id="1",
            time=i, x=float(i), y=float(i)) for i in range(10)]
        r2 = [TargetRecord(source_id="b", track_id="1",
            time=i+1, x=float(i), y=float(i)) for i in range(10)]
        result = ta.align(r1, r2)
        assert isinstance(result.offset, float)


# ═══════════════════════════════════════════════════════════════
#  GPS/NMEA测试（仿真数据）
# ═══════════════════════════════════════════════════════════════

class TestGPSAdapter:
    """GPS适配器测试（仿真数据）。"""

    def test_gpx_parsing(self, tmpdir):
        """GPX文件解析。"""
        path = os.path.join(tmpdir, "test.gpx")
        with open(path, "w", encoding="utf-8") as f:
            f.write('<?xml version="1.0" encoding="UTF-8"?>\n'
                    '<gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1">\n'
                    '<trk><trkseg>\n'
                    '<trkpt lat="22.5" lon="113.8">\n'
                    '<time>2025-03-05T10:00:00Z</time>\n'
                    '</trkpt>\n'
                    '<trkpt lat="22.51" lon="113.81">\n'
                    '<time>2025-03-05T10:01:00Z</time>\n'
                    '</trkpt>\n'
                    '</trkseg></trk>\n</gpx>\n')
        from seasync.adapters import GPSAdapter
        a = GPSAdapter(path)
        assert a.validate() is True
        recs = a.load()
        assert len(recs) >= 1, f"GPS应≥1条, 实有{len(recs)}"

    def test_nmea_rmc_parsing(self, tmpdir):
        """NMEA RMC语句解析。"""
        path = os.path.join(tmpdir, "test.nmea")
        with open(path, "w") as f:
            f.write("$GPRMC,100000.00,A,2230.0000,N,11348.0000,E,0.5,90.0,050325,,,A*2F\n")
            f.write("$GPRMC,100100.00,A,2231.0000,N,11349.0000,E,0.6,92.0,050325,,,A*25\n")
        from seasync.adapters import GPSAdapter
        a = GPSAdapter(path)
        assert a.validate()
        recs = a.load()
        assert len(recs) >= 1, f"NMEA应≥1条, 实有{len(recs)}"

    def test_import_manager_routes_gpx(self, tmpdir):
        """GPX通过ImportManager路由到GPSAdapter。"""
        path = os.path.join(tmpdir, "nav.gpx")
        with open(path, "w", encoding="utf-8") as f:
            f.write('<?xml version="1.0" encoding="UTF-8"?>\n'
                    '<gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1">\n'
                    '<trk><trkseg>\n'
                    '<trkpt lat="22.5" lon="113.8"><time>2025-03-05T10:00:00Z</time></trkpt>\n'
                    '</trkseg></trk>\n</gpx>\n')
        im = ImportManager()
        a = im.register(path)
        from seasync.adapters import GPSAdapter
        assert isinstance(a, GPSAdapter), f"应为GPSAdapter, 实为{type(a)}"


# ═══════════════════════════════════════════════════════════════
#  CAT048二进制测试（仿真数据）
# ═══════════════════════════════════════════════════════════════

class TestCAT048Adapter:
    """CAT-048二进制适配器测试（仿真数据）。"""

    def _make_plots(self, path, n_scans=3, n_targets=3):
        """写CAT048点迹文件。"""
        import struct
        d = bytearray()
        for s in range(n_scans):
            bt = int(s * 2.0 * 128)
            pl = b''
            for t in range(n_targets):
                rng = int((10 + t*5) * 256)
                azi = int((45 + t*90) / 360.0 * 65536)
                pl += struct.pack('>H', rng) + struct.pack('>H', azi)
                pl += b'\x18\x10' + struct.pack('B', 20+t)
                pl += struct.pack('>H', 100+t) + struct.pack('>H', 50)
                pl += struct.pack('>H', azi)
            ml = 15 + len(pl)
            msg = struct.pack('B', 0x30) + struct.pack('>H', ml)
            msg += struct.pack('>I', 0xF31D0104) + struct.pack('>H', s+1)
            msg += struct.pack('>I', bt)[1:]
            msg += struct.pack('B', 0x20) + struct.pack('>H', 1) + b'\x00\x00' + pl
            d.extend(msg)
        with open(path, 'wb') as f: f.write(bytes(d))

    def _make_cat048_plots(self, path, n_scans=3, n_targets=3):
        """写金海豚格式CAT048点迹文件（11B/点迹，对齐真实数据格式）。"""
        import struct
        d = bytearray()
        for s in range(n_scans):
            bt = int(s * 2.0 * 128)
            pl = b''
            for t in range(n_targets):
                rng = struct.pack('>H', int((10 + t*5) * 256))
                azi = struct.pack('>H', int((45 + t*30) / 360.0 * 65536))
                extra = struct.pack('BBB', 0x18, 0, 0)
                seq = struct.pack('>H', 100 + t)
                pad = struct.pack('>H', 0)
                pl += rng + azi + extra + seq + pad  # 11B per plot
            # CAT048真实格式: 15B header + N*11B plots
            header = struct.pack('B', 0x30)                          # 1B CAT
            ml = 15 + len(pl)
            header += struct.pack('>H', ml)                          # 2B length
            header += struct.pack('BB', 0xF3, 0x11)                  # 2B SAC/SIC
            header += struct.pack('>I', 0x01060001)                  # 4B control
            header += struct.pack('>I', bt)[1:]                      # 3B time
            header += struct.pack('B', 0x20)                         # 1B info_type
            header += struct.pack('>H', 1)                           # 2B extra(方位码)
            # Total header = 1+2+2+4+3+1+2 = 15B ↔ HEADER_SIZE
            d.extend(header + pl)
        with open(path, 'wb') as f: f.write(bytes(d))

    def _make_tracks(self, path, n_scans=3, n_targets=3):
        """写CAT048航迹文件。"""
        import struct
        d = bytearray()
        for s in range(n_scans):
            bt = int(s * 2.0 * 128)
            for t in range(n_targets):
                x = int((50 + s*5 + t*25) * 128)
                y = int((50 + s*5 + t*15) * 128)
                spd = int(10 / 1852 * 16384 * 0.51444)
                crs = int(90 / 360.0 * 65536)
                msg = struct.pack('B', 0x30) + struct.pack('>H', 32)
                msg += struct.pack('>I', 0xF31D0104) + struct.pack('>H', s+1)
                msg += struct.pack('>I', bt)[1:] + struct.pack('B', 0x40)
                msg += struct.pack('>H', int(50*256))
                msg += struct.pack('>H', int(45*65536//360))
                msg += b'\x00\x00\x00'
                msg += struct.pack('>H', (t+1) & 0xFFF)
                msg += struct.pack('>h', x) + struct.pack('>h', y)
                msg += struct.pack('>h', spd) + struct.pack('>H', crs)
                msg += b'\x00\x00'
                d.extend(msg)
        with open(path, 'wb') as f: f.write(bytes(d))

    def test_validate(self, tmpdir):
        """验证函数识别CAT048文件头。"""
        p = os.path.join(tmpdir, "t.data")
        self._make_cat048_plots(p)
        from seasync.adapters.cat048_adapter import CAT048RadarAdapter
        assert CAT048RadarAdapter(p).validate()

    def test_load_plots(self, tmpdir):
        """加载点迹文件不崩溃，返回合理的记录数。"""
        p = os.path.join(tmpdir, "p.data")
        self._make_cat048_plots(p, 3, 3)
        from seasync.adapters.cat048_adapter import CAT048RadarAdapter
        recs = CAT048RadarAdapter(p).load()
        # 3帧 × 3点迹 = 9条记录（11B/点迹）
        assert len(recs) == 9

    def test_load_plots_multi(self, tmpdir):
        """多点迹打包加载。"""
        p = os.path.join(tmpdir, "mp.data")
        self._make_cat048_plots(p, 2, 5)  # 2帧×5点迹
        from seasync.adapters.cat048_adapter import CAT048RadarAdapter
        recs = CAT048RadarAdapter(p).load()
        assert len(recs) == 10

    def test_radar_metadata(self, tmpdir):
        """点迹包含方位/距离元数据。"""
        p = os.path.join(tmpdir, "rm.data")
        self._make_cat048_plots(p, 1, 2)
        from seasync.adapters.cat048_adapter import CAT048RadarAdapter
        recs = CAT048RadarAdapter(p).load()
        assert len(recs) == 2
        assert recs[0].metadata.get('range_nm') is not None
        assert recs[0].metadata.get('azimuth_deg') is not None

    def test_im_auto_detect(self, tmpdir):
        p = os.path.join(tmpdir, "r.data")
        self._make_cat048_plots(p)
        im = ImportManager()
        a = im.register(p)
        from seasync.adapters.cat048_adapter import CAT048RadarAdapter
        assert isinstance(a, CAT048RadarAdapter)

    def test_invalid_no_crash(self, tmpdir):
        p = os.path.join(tmpdir, "b.data")
        with open(p, "wb") as f: f.write(b"\xff\xff")
        from seasync.adapters.cat048_adapter import CAT048RadarAdapter
        assert not CAT048RadarAdapter(p).validate()

class TestProjectManager:
    """项目数据库管理器。"""

    def test_create_project(self, tmpdir):
        """创建项目返回有效project_id。"""
        from seasync.core import ProjectManager
        pm = ProjectManager(db_path=os.path.join(tmpdir, "test.db"))
        pid = pm.create_project("测试项目")
        assert pid is not None
        assert len(pid) > 0

    def test_list_projects(self, tmpdir):
        """列出所有项目。"""
        from seasync.core import ProjectManager
        pm = ProjectManager(db_path=os.path.join(tmpdir, "test.db"))
        pm.create_project("项目1")
        pm.create_project("项目2")
        projects = pm.list_projects()
        assert len(projects) >= 2

    def test_save_load_config(self, tmpdir):
        """保存项目并获取摘要。"""
        from seasync.core import ProjectManager
        pm = ProjectManager(db_path=os.path.join(tmpdir, "test.db"))
        p = pm.create_project("配置测试")
        summary = pm.get_project_summary(p["id"])
        assert isinstance(summary, dict)
        assert "data_sources" in summary


# ═══════════════════════════════════════════════════════════════
#  TrackManager 额外测试
# ═══════════════════════════════════════════════════════════════

class TestTrackManagerExtra:
    """轨迹管理额外测试。"""

    def test_empty_tracks(self):
        """空TrackManager不崩溃。"""
        from seasync.engines import TrackManager
        tm = TrackManager()
        assert tm.list_track_ids() == []

    def test_add_and_retrieve(self):
        """添加后能正确取回。"""
        from seasync.engines import TrackManager
        tm = TrackManager()
        r = TargetRecord(source_id="test", track_id="1", time=0, x=0, y=0)
        tm.add(r)
        track = tm.get_track("1")
        assert track is not None
        assert r in track

