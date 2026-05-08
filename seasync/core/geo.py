"""
SeaSync 地理空间工具模块
========================
统一坐标转换和距离计算，消除各模块的重复实现和错误。

提供函数：
  - haversine_m()        球面距离（米）
  - ll_to_xy()           经纬度 → 平面米
  - xy_to_ll()           平面米 → 经纬度
  - polar_to_ll()        雷达极坐标 → 经纬度
  - ll_to_polar()        经纬度 → 雷达极坐标
  - meters_per_deg_lat() 纬度1度 ≈ 米
  - meters_per_deg_lon() 经度1度（给定纬度）≈ 米
"""

# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 荣火
from __future__ import annotations
import math
import numpy as np

EARTH_RADIUS_M = 6_371_000.0
NM_TO_M = 1852.0          # 海里 → 米
DEG_TO_NM = 60.0          # 1 度 ≈ 60 海里


# ============================================================================
# 球面距离
# ============================================================================

def haversine_m(lat1: float, lon1: float,
                lat2: float, lon2: float) -> float:
    """Haversine 球面距离，返回 米（纯标量）。

    用地球平均半径（6,371km），适用于多数无人艇场景。
    """
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1))
         * math.cos(math.radians(lat2))
         * math.sin(dlon / 2) ** 2)
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(min(a, 1.0)))


def haversine_m_np(lat1, lon1, lat2, lon2) -> np.ndarray:
    """Haversine 球面距离，支持 numpy 数组广播。

    用于 DBSCAN、关联引擎等需要向量化计算的场景。
    """
    R = np.float64(EARTH_RADIUS_M)
    lat1r, lat2r = np.radians(lat1), np.radians(lat2)
    dlat = np.radians(np.asarray(lat2) - np.asarray(lat1))
    dlon = np.radians(np.asarray(lon2) - np.asarray(lon1))
    a = (np.sin(dlat / 2) ** 2
         + np.cos(lat1r) * np.cos(lat2r) * np.sin(dlon / 2) ** 2)
    return R * 2 * np.arcsin(np.sqrt(np.clip(a, 0, 1)))


# ============================================================================
# 经纬度 ↔ 平面米（简化墨卡托，以 origin 为基准）
# ============================================================================

def meters_per_deg_lat() -> float:
    """纬度1度对应的米数（≈111,111 米）。"""
    return NM_TO_M * DEG_TO_NM


def meters_per_deg_lon(lat: float) -> float:
    """给定纬度下，经度1度对应的米数。"""
    return NM_TO_M * DEG_TO_NM * math.cos(math.radians(abs(lat) + 1e-9))


def ll_to_xy(origin_lat: float, origin_lon: float,
             lat: float, lon: float) -> tuple[float, float]:
    """经纬度 → 平面米坐标（以 origin 为原点的简化墨卡托投影）。

    返回 (x, y)，其中：
      - x ≈ 东西方向位移（经度方向，正为东）
      - y ≈ 南北方向位移（纬度方向，正为北）
    """
    dlat = lat - origin_lat
    dlon = lon - origin_lon
    y = dlat * meters_per_deg_lat()
    x = dlon * meters_per_deg_lon(origin_lat)
    return x, y


def xy_to_ll(origin_lat: float, origin_lon: float,
             x: float, y: float) -> tuple[float, float]:
    """平面米坐标 → 经纬度（origin 原点的逆投影）。

    返回 (lat, lon)。
    """
    lat = origin_lat + y / meters_per_deg_lat()
    lon = origin_lon + x / meters_per_deg_lon(origin_lat)
    return lat, lon


# ============================================================================
# 雷达极坐标 ↔ 经纬度
# ============================================================================

def polar_to_ll(origin_lat: float, origin_lon: float,
                range_nm: float, azimuth_deg: float) -> tuple[float, float]:
    """雷达极坐标 → 经纬度。

    Args:
        origin_lat: 雷达安装点纬度
        origin_lon: 雷达安装点经度
        range_nm:   距雷达距离（海里）
        azimuth_deg: 方位角（度，0=北，顺时针）

    Returns:
        (lat, lon) 目标经纬度
    """
    az_rad = math.radians(azimuth_deg)
    d_nm = range_nm
    dlat_deg = d_nm * math.cos(az_rad) / DEG_TO_NM
    dlon_deg = (d_nm * math.sin(az_rad)
                / (DEG_TO_NM * math.cos(math.radians(origin_lat + 1e-9))))
    return origin_lat + dlat_deg, origin_lon + dlon_deg


def ll_to_polar(origin_lat: float, origin_lon: float,
                lat: float, lon: float) -> tuple[float, float]:
    """经纬度 → 雷达极坐标（距雷达海里数，方位角度）。

    Returns:
        (range_nm, azimuth_deg)
    """
    dlat_deg = lat - origin_lat
    dlon_deg = lon - origin_lon
    x_nm = dlon_deg * DEG_TO_NM * math.cos(math.radians((lat + origin_lat) / 2 + 1e-9))
    y_nm = dlat_deg * DEG_TO_NM
    r_nm = math.hypot(x_nm, y_nm)
    az_deg = math.degrees(math.atan2(x_nm, y_nm)) % 360
    return r_nm, az_deg
