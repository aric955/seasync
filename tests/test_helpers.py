"""
SeaSync V2.2 测试夹具 — 合成数据生成器。
生成与真实海试数据格式一致的中文列名CSV。
"""

# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 荣火
from __future__ import annotations
import os, math, tempfile
from typing import Tuple


def generate_radar_csv(tmpdir: str, filename: str = "test_radar.csv",
                       n_frames: int = 10, origin_lat: float = 37.53297,
                       origin_lon: float = 121.42323) -> str:
    """生成CutDataTarget格式的雷达CSV（中文列名+极坐标+目标类型）。"""
    import pandas as pd
    import numpy as np

    rows = []
    # 模拟 AT 目标（MMSI已知的AIS确认目标）
    at_mmsi = 413203610
    at_az = 8.0    # 方位角°
    at_rng = 3875  # 距离米

    # 模拟 RT 目标（雷达跟踪）— 接近AT位置以便关联匹配
    rt_az = 8.0
    rt_rng = 3880

    # 模拟 CDT 目标（杂波）
    cdt_az = 352.0
    cdt_rng = 3334

    for frame in range(1, n_frames + 1):
        # 时间递进：5秒间隔
        if frame % 2 == 1:
            t = f"2025-03-05 10:{35 + (frame * 5) // 60:02d}:{(frame * 5) % 60:02d}"
        else:
            t = f"2025-03-05 10:{35 + (frame * 5) // 60:02d}:{(frame * 5) % 60:02d}"
        # 每帧3-4个目标
        noise = np.random.uniform(-0.1, 0.1)
        # AT（AIS目标）
        rows.append([frame, t, t, -1, "", "AT", at_mmsi,
                     at_az + noise, at_rng + noise * 10,
                     at_az - 2, at_rng - 10, at_az + 2, at_rng + 30,
                     344.0, 0.0, 1, 0.51, 0.46, 0.02, 0.06])
        # RT（雷达跟踪）
        rows.append([frame, t, t, -1, "", "RT", 1,
                     rt_az + noise, rt_rng + noise * 10,
                     rt_az - 1.5, rt_rng - 5, rt_az + 2.5, rt_rng + 40,
                     344.0, 0.0, 0, 0.82, 0.45, 0.03, 0.07])
        # CDT（杂波1）
        rows.append([frame, t, t, -1, "", "CDT", 900001,
                     cdt_az + noise, cdt_rng + noise * 10,
                     cdt_az - 2, cdt_rng - 30, cdt_az + 1.5, cdt_rng + 20,
                     344.0, 0.0, 0, 0.23, 0.13, 0.04, 0.08])
        # CDT（杂波2）
        rows.append([frame, t, t, -1, "", "CDT", 900002,
                     cdt_az + noise + 5, cdt_rng + noise * 10 + 100,
                     cdt_az + 4, cdt_rng + 80, cdt_az + 7, cdt_rng + 120,
                     344.0, 0.0, 0, 0.59, 0.25, 0.04, 0.08])

    cols = [
        "帧序号", "起始时间(帧)", "截止时间(帧)", "匹配编号", "光电匹配时间",
        "目标类型", "目标编号", "目标方位(°)", "目标距离(米)",
        "[外接矩形]起始角度(°)", "[外接矩形]起始距离(米)",
        "[外接矩形]结束角度(°)", "[外接矩形]结束距离(米)",
        "角度修正(°)", "距离修正(米)", "是否为切片目标",
        "x_center", "y_center", "w", "h",
    ]
    df = pd.DataFrame(rows, columns=cols)
    path = os.path.join(tmpdir, filename)
    df.to_csv(path, index=False, encoding="utf-8-sig")
    return path


def generate_ais_csv(tmpdir: str, filename: str = "test_ais.csv",
                     mmsi: int = 413203610,
                     lat: float = 37.5675, lon: float = 121.426) -> str:
    """生成AIS_Trajectory格式的AIS CSV（中英混列名+经纬度）。"""
    import pandas as pd
    import numpy as np

    n_points = 10
    rows = []
    for i in range(n_points):
        t = f"2025-03-05 10:{40 + i}:{i * 6:02d}"
        lat_i = lat + np.random.uniform(-0.0005, 0.0005)
        lon_i = lon + np.random.uniform(-0.0005, 0.0005)
        speed = np.random.uniform(0, 0.3)
        cog = np.random.uniform(60, 180)
        heading = np.random.uniform(60, 180)
        rows.append([mmsi, lon_i, lat_i, t, speed, heading, cog, "锚泊", 182.0, 0, 0.0, 8.0, 3875])

    cols = [
        "MMSI", "经度(°)", "纬度(°)", "时间", "速度(kn)",
        "船艏向(°)", "对地航向(°)", "航行状态", "相对视角(°)",
        "姿态信息", "浪高(m)", "方位角(°)", "距离(m)",
    ]
    df = pd.DataFrame(rows, columns=cols)
    path = os.path.join(tmpdir, filename)
    df.to_csv(path, index=False, encoding="utf-8-sig")
    return path


def generate_ais_simple_csv(tmpdir: str, filename: str = "test_ais_simple.csv",
                            mmsi: int = 413203610) -> str:
    """生成简单格式的AIS CSV（英文列名，方便单元测试）。"""
    import pandas as pd
    n_points = 5
    rows = []
    for i in range(n_points):
        rows.append({
            "mmsi": mmsi,
            "timestamp": f"2025-03-05 10:35:{5 + i * 5:02d}",
            "lat": 37.5675,
            "lon": 121.426,
            "sog": 0.2,
            "cog": 90.0,
        })
    df = pd.DataFrame(rows)
    path = os.path.join(tmpdir, filename)
    df.to_csv(path, index=False)
    return path


def generate_polar_csv(tmpdir: str, filename: str = "test_polar.csv",
                       origin_lat: float = 37.53297,
                       origin_lon: float = 121.42323) -> str:
    """生成纯极坐标雷达CSV（无lat/lon，无目标类型）。"""
    import pandas as pd
    n_points = 5
    rows = []
    for i in range(n_points):
        rows.append([f"2025-03-05 10:{35 + i}:00",
                     3800 + i * 10,    # range_m
                     8.0 + i * 0.01])  # azimuth_deg
    df = pd.DataFrame(rows, columns=["time", "range_m", "azimuth_deg"])
    path = os.path.join(tmpdir, filename)
    df.to_csv(path, index=False)
    return path
