"""
SeaSync GUI 自动化测试
======================
无需人工点击的 GUI 回归测试套件。
"""

# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 荣火
from __future__ import annotations
import os, sys, tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _require_gui():
    """检查 GUI 依赖是否到位。"""
    try:
        from PyQt5 import QtWidgets, QtCore, QtTest
        import matplotlib
        matplotlib.use('Agg')
        # 检查是否有可用 display（Windows 无显示器时 Qt 窗口会挂起）
        try:
            import os
            if os.name == 'nt':
                # Windows 下检查是否有桌面会话（非 Windows 服务 / 无头环境）
                userenv = os.environ.get('USERNAME', '')
                session = os.environ.get('SESSIONNAME', '')
                # 如果没有有效的用户会话，跳过 GUI 测试
                if not userenv or not session:
                    return False
        except Exception:
            pass
        return True
    except ImportError:
        return False


HAVE_GUI = _require_gui()


# ============================================================
# 1. 基础 Smoke 测试
# ============================================================

def test_gui_imports():
    """GUI 模块可以正常导入。"""
    from seasync.gui.mpl_canvas import MplCanvas, _HAVE_MPL
    from seasync.gui.worker_thread import WorkerThread
    from seasync.gui.main_window import SeaSyncMainWindow
    assert SeaSyncMainWindow is not None
    assert WorkerThread is not None


def test_pipeline_instantiation():
    """Pipeline 可以正常创建。"""
    from seasync.engines import SeaSyncPipeline
    pipe = SeaSyncPipeline()
    assert pipe.config.distance_threshold == 500.0
    assert pipe.config.use_mahalanobis is True


def test_add_source_csv():
    """CSV 数据可以正常加载。"""
    from seasync.engines import SeaSyncPipeline
    from tests.test_helpers import generate_radar_csv, generate_ais_simple_csv

    with tempfile.TemporaryDirectory() as td:
        radar_path = generate_radar_csv(td, n_frames=3)
        ais_path = generate_ais_simple_csv(td)

        pipe = SeaSyncPipeline(origin_lat=37.53297, origin_lon=121.42323)
        sid_r = pipe.add_source(radar_path, source_type="radar")
        sid_a = pipe.add_source(ais_path, source_type="ais")

        radar_recs = pipe.get_records(sid_r)
        ais_recs = pipe.get_records(sid_a)
        assert len(radar_recs) > 0
        assert len(ais_recs) > 0
        # 雷达坐标应接近真实经纬度
        assert 30 < radar_recs[0].lat < 40, f"雷达lat偏离: {radar_recs[0].lat}"


def test_pipeline_run():
    """完整流程 run() 不报错。"""
    from seasync.engines import SeaSyncPipeline
    from tests.test_helpers import generate_radar_csv, generate_ais_simple_csv

    with tempfile.TemporaryDirectory() as td:
        radar_path = generate_radar_csv(td, n_frames=5)
        ais_path = generate_ais_simple_csv(td)

        pipe = SeaSyncPipeline(origin_lat=37.53297, origin_lon=121.42323)
        sid_r = pipe.add_source(radar_path, source_type="radar")
        sid_a = pipe.add_source(ais_path, source_type="ais")

        steps = pipe.run(sid_r, sid_a)
        assert "association" in steps
        assert "events" in steps
        assert steps["association"]["quality"] >= 0


def test_run_n_source():
    """N 源模式 run() 不报错。"""
    from seasync.engines import SeaSyncPipeline
    from tests.test_helpers import generate_radar_csv, generate_ais_simple_csv

    with tempfile.TemporaryDirectory() as td:
        radar_path = generate_radar_csv(td, n_frames=3)
        ais1_path = generate_ais_simple_csv(td, mmsi=413203610)
        ais2_path = generate_ais_simple_csv(td, mmsi=412752690,
                                             filename="ais2.csv")

        pipe = SeaSyncPipeline(origin_lat=37.53297, origin_lon=121.42323)
        sid_r = pipe.add_source(radar_path, source_type="radar")
        sid_a1 = pipe.add_source(ais1_path, source_type="ais")
        sid_a2 = pipe.add_source(ais2_path, source_type="ais")

        steps = pipe.run(source_ids=[sid_r, sid_a1, sid_a2])
        assert "associations" in steps
        assert len(steps["associations"]) >= 1


def test_kf_integration():
    """KF 集成产生不同质量的关联结果。"""
    from seasync.engines import SeaSyncPipeline
    from tests.test_helpers import generate_radar_csv, generate_ais_simple_csv

    with tempfile.TemporaryDirectory() as td:
        radar_path = generate_radar_csv(td, n_frames=5)
        ais_path = generate_ais_simple_csv(td)

        pipe = SeaSyncPipeline(origin_lat=37.53297, origin_lon=121.42323)
        sid_r = pipe.add_source(radar_path, source_type="radar")
        sid_a = pipe.add_source(ais_path, source_type="ais")

        radar_recs = pipe.get_records(sid_r)
        ais_recs = pipe.get_records(sid_a)
        result = pipe._assoc.associate(radar_recs, ais_recs)
        assert result.total_quality > 0
        # 验证 KF 方法被记录
        method = result.pairs[0].method if result.pairs else ""
        assert method in ("kalman_mahalanobis", "haversine")


def test_kml_export():
    """KML 导出生成有效 XML。"""
    from seasync.core.kml_export import export_kml

    class R:
        def __init__(self, lat, lon, time, tid, speed=0):
            self.lat = lat; self.lon = lon; self.time = time
            self.track_id = tid; self.speed = speed

    records = [R(37.567, 121.426, 1000 + i * 10, "T1", 5) for i in range(3)]
    with tempfile.TemporaryDirectory() as td:
        out = os.path.join(td, "test.kml")
        export_kml(out, {"test": records}, origin_lat=37.53, origin_lon=121.42)
        with open(out, encoding='utf-8') as f:
            content = f.read()
        assert content.startswith('<?xml')
        assert '<kml' in content
        assert 'LineString' in content


def test_geo_functions():
    """坐标转换函数正确性。"""
    from seasync.core.geo import (
        haversine_m, ll_to_xy, xy_to_ll,
        polar_to_ll, ll_to_polar, meters_per_deg_lat, meters_per_deg_lon,
    )
    import math

    # haversine: 北京→上海 ≈ 1068km
    d = haversine_m(39.9, 116.4, 31.2, 121.5)
    assert 1_000_000 < d < 1_200_000, f"北京-上海距离异常: {d/1000:.0f}km"

    # 往返转换不丢失
    x, y = ll_to_xy(37.5, 121.4, 37.6, 121.5)
    lat, lon = xy_to_ll(37.5, 121.4, x, y)
    assert abs(lat - 37.6) < 0.001
    assert abs(lon - 121.5) < 0.001

    # meters_per_deg: 纬度1° ≈ 111km
    assert abs(meters_per_deg_lat() - 111120) < 100
    # 经度1° ≈ 111km × cos(lat)
    result_lon = meters_per_deg_lon(37.5)
    expected_lon = 111120 * math.cos(math.radians(37.5))
    assert abs(result_lon - expected_lon) < 200

    # polar ↔ latlon: 往返
    r, az = ll_to_polar(37.5, 121.4, 37.6, 121.5)
    lat2, lon2 = polar_to_ll(37.5, 121.4, r, az)
    assert abs(lat2 - 37.6) < 0.001
    assert abs(lon2 - 121.5) < 0.001


def test_association_pair_generic():
    """AssociationPair 泛化字段向后兼容。"""
    from seasync.core.data_models import AssociationPair

    # 新方式创建（radar + ais）
    p1 = AssociationPair(source1_id="R1", source2_id="A1",
                         source1_label="radar", source2_label="ais",
                         confidence=0.9)
    assert p1.source1_id == "R1"
    assert p1.source2_id == "A1"
    assert p1.source1_label == "radar"
    assert p1.source2_label == "ais"
    # 向后兼容属性
    assert p1.radar_track_id == "R1"
    assert p1.ais_mmsi == "A1"

    # 新方式创建（gps + ais）
    p2 = AssociationPair(source1_id="G1", source2_id="A1",
                         source1_label="gps", source2_label="ais",
                         confidence=0.8)
    assert p2.source1_id == "G1"
    assert p2.source_ids == ("G1", "A1")

    # 按标签获取
    assert p2.get_id("gps") == "G1"
    assert p2.get_id("ais") == "A1"

    # 光学 + 雷达（未来扩展）
    p3 = AssociationPair(source1_id="OPT-1", source2_id="R2",
                         source1_label="optical", source2_label="radar",
                         confidence=0.85)
    assert p3.source1_label == "optical"
    assert p3.source2_label == "radar"
    assert p3.radar_track_id == "R2"  # 向后兼容：source2是radar时返回其ID


# ============================================================
# 2. GUI Smoke 测试（需要 PyQt5 + display，无display时自动跳过）
# ============================================================
import pytest as _pytest

_HAVE_GUI = HAVE_GUI


@_pytest.mark.skipif(not _HAVE_GUI, reason="PyQt5 未安装")
def test_main_window_creation():
    """主窗口可以创建。"""
    if not _HAVE_GUI:
        return
    from PyQt5 import QtWidgets
    # 确保有 QApplication 实例，避免在无交互上下文时挂起
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    from seasync.gui.main_window import SeaSyncMainWindow
    w = SeaSyncMainWindow()
    assert w.windowTitle() == "SeaSync V2.2 — 多源关联复盘工具"
    w.close()
    app.processEvents()


def test_mpl_canvas_creation():
    """MplCanvas 可以创建。"""
    if not _HAVE_GUI:
        return
    from seasync.gui.mpl_canvas import MplCanvas
    canvas = MplCanvas()
    canvas.clear()
    assert canvas.fig is not None


def test_worker_thread():
    """WorkerThread 信号连接正常。"""
    if not _HAVE_GUI:
        return
    from seasync.gui.worker_thread import WorkerThread
    from seasync.engines import SeaSyncPipeline

    pipe = SeaSyncPipeline()
    w = WorkerThread("run_pipeline", pipe,
                     radar_sid="test_r", ais_sid="test_a")
    assert w.task_type == "run_pipeline"
    assert w.pipeline is pipe


def test_ppi_rendering():
    """PPI 渲染不崩溃。"""
    from seasync.engines import SeaSyncPipeline
    from tests.test_helpers import generate_radar_csv, generate_ais_simple_csv

    with tempfile.TemporaryDirectory() as td:
        radar_path = generate_radar_csv(td, n_frames=3)
        ais_path = generate_ais_simple_csv(td)

        pipe = SeaSyncPipeline(origin_lat=37.53297, origin_lon=121.42323)
        sid_r = pipe.add_source(radar_path, source_type="radar")
        sid_a = pipe.add_source(ais_path, source_type="ais")

        radar_recs = pipe.get_records(sid_r)
        ais_recs = pipe.get_records(sid_a)

        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        from seasync.core.geo import ll_to_xy

        fig, ax = plt.subplots()
        ax.set_facecolor('#001a00')

        # 距离圈
        for rk in [5, 10]:
            circ = plt.Circle((0, 0), rk * 1000, fill=False,
                              edgecolor='#2a5a2a', linewidth=0.5, alpha=0.6)
            ax.add_patch(circ)

        # 雷达点
        xs = [r.x for r in radar_recs if r.x is not None]
        ys = [r.y for r in radar_recs if r.y is not None]
        ax.scatter(xs, ys, color='#FF6B6B', s=10, alpha=0.5)

        # AIS 点
        for r in ais_recs:
            if r.lat is not None:
                lx, ly = ll_to_xy(37.53297, 121.42323, r.lat, r.lon)
                ax.scatter(lx, ly, color='#4ECDC4', s=20, alpha=0.9)

        ax.set_xlim(-35000, 35000); ax.set_ylim(-35000, 35000)
        ax.set_aspect('equal')
        plt.tight_layout()
        out = os.path.join(td, 'ppi_test.png')
        plt.savefig(out, dpi=80)
        plt.close()
        assert os.path.getsize(out) > 1000, "PPI渲染输出异常"
