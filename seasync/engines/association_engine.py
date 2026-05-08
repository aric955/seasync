"""
SeaSync V2.2 AssociationEngine — 多目标关联引擎。
核心算法：
  1. 基于速度/航向约束的轨迹预测（卡尔曼滤波）
  2. 动态马氏距离关联度量
  3. 匈牙利算法全局最优分配
"""

# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 荣火
from __future__ import annotations
from typing import List, Tuple, Dict, Optional, Set
import numpy as np

from ..core.data_models import (
    TargetRecord,
    AssociationPair,
    AssociationResult,
)
from ..core.association_config import AssociationConfig
from ..core.geo import haversine_m_np as _haversine_m
from ..core.logger import log


class KalmanFilter:
    """2D 恒速 KalmanFilter（位置 + 速度）。"""

    def __init__(self, dt: float = 1.0) -> None:
        # 状态: [x, y, vx, vy]
        self.x = np.zeros(4)
        self.P = np.eye(4) * 1e3  # 初始协方差
        self.dt = dt
        # 状态转移矩阵
        self.F = np.array([
            [1, 0, dt, 0],
            [0, 1, 0, dt],
            [0, 0, 1, 0],
            [0, 0, 0, 1],
        ])
        # 观测矩阵（仅观测位置）
        self.H = np.array([[1, 0, 0, 0], [0, 1, 0, 0]])
        # 过程噪声（标准 CV 模型 Q 矩阵）
        dt2 = dt ** 2
        dt3 = dt ** 3
        dt4 = dt ** 4
        sigma2 = 5.0  # 加速度噪声方差
        self.Q = np.array([
            [dt4 / 4, 0, dt3 / 2, 0],
            [0, dt4 / 4, 0, dt3 / 2],
            [dt3 / 2, 0, dt2, 0],
            [0, dt3 / 2, 0, dt2],
        ]) * sigma2
        # 观测噪声
        self.R = np.eye(2) * 10.0

    def predict(self, dt: Optional[float] = None) -> Tuple[float, float]:
        if dt is not None:
            F = np.array([[1, 0, dt, 0], [0, 1, 0, dt], [0, 0, 1, 0], [0, 0, 0, 1]])
            self.x = F @ self.x
            self.P = F @ self.P @ F.T
        else:
            self.x = self.F @ self.x
            self.P = self.F @ self.P @ self.F.T + self.Q
        return float(self.x[0]), float(self.x[1])

    def update(self, zx: float, zy: float) -> None:
        z = np.array([zx, zy])
        y = z - self.H @ self.x
        S = self.H @ self.P @ self.H.T + self.R
        K = self.P @ self.H.T @ np.linalg.inv(S)
        self.x = self.x + K @ y
        self.P = (np.eye(4) - K @ self.H) @ self.P


class AssociationEngine:
    """多目标关联引擎。"""

    def __init__(self, config: Optional[AssociationConfig] = None,
                 origin_lat: Optional[float] = None,
                 origin_lon: Optional[float] = None) -> None:
        self.cfg = config or AssociationConfig()
        # 雷达站原点（已知时，AIS经纬度转本地米使用）
        self._origin_lat = origin_lat
        self._origin_lon = origin_lon
        # KF 统计
        self._kf_stats = {"kf_hits": 0, "haversine_fallback": 0}

    # ── 卡尔曼滤波辅助 ─────────────────────────────────────

    def _predict_with_kf(
        self, records: List[TargetRecord]
    ) -> Optional[Tuple[float, float, float, float, np.ndarray]]:
        """对轨迹观测序列运行卡尔曼滤波，返回预测位置和不确定性。

        Args:
            records: 同一条轨迹的观测序列（将按时间排序）

        Returns:
            (pred_lat, pred_lon, pred_x, pred_y, cov_2x2) 或 None（不足2个观测点）
        """
        if len(records) < 2:
            return None

        # 按时间排序
        sorted_recs = sorted(records, key=lambda r: r.time)

        # 选取有 lat/lon 的记录
        valid = [r for r in sorted_recs if r.lat is not None]
        if len(valid) < 2:
            return None

        # 使用 x/y 空间（米）运行 KF，若 origin 已知则用 ll_to_xy
        from ..core.geo import ll_to_xy, xy_to_ll

        kf = KalmanFilter()
        prev_time = valid[0].time
        olat = self._origin_lat or 0.0
        olon = self._origin_lon or 0.0
        has_origin = self._origin_lat is not None

        for r in valid:
            dt = max(r.time - prev_time, 0.1)
            prev_time = r.time
            if has_origin:
                # 经纬度 → 本地 xy(米)
                zx, zy = ll_to_xy(olat, olon, r.lat, r.lon)
            else:
                # 无 origin 时用 lat/lon 当作 x/y（小范围近似，仅用于内部计算）
                zx, zy = r.lat, r.lon
            kf.predict(dt=dt)
            kf.update(zx, zy)

        # 预测下一位置
        pred_x, pred_y = kf.predict()

        # 协方差矩阵（位置部分 2x2）
        cov = kf.P[:2, :2]  # 2x2

        # 转回经纬度
        if has_origin:
            pred_lat, pred_lon = xy_to_ll(olat, olon, pred_x, pred_y)
        else:
            pred_lat, pred_lon = pred_x, pred_y

        return (pred_lat, pred_lon, pred_x, pred_y, cov)

    @staticmethod
    def _mahalanobis_dist(
        obs_lat: float, obs_lon: float,
        pred_lat: float, pred_lon: float,
        cov: np.ndarray,
        has_origin: bool = False,
        origin_lat: float = 0.0,
        origin_lon: float = 0.0,
    ) -> float:
        """计算观测与预测之间的马氏距离。

        使用 KF 协方差矩阵做加权距离，自动处理不同方向的不确定性差异。
        注意：当 has_origin=True 时，cov 在 xy(米) 空间，diff 也必须转到 xy 空间。
        """
        from ..core.geo import ll_to_xy
        if has_origin:
            ox, oy = ll_to_xy(origin_lat, origin_lon, obs_lat, obs_lon)
            px, py = ll_to_xy(origin_lat, origin_lon, pred_lat, pred_lon)
            dx = ox - px
            dy = oy - py
        else:
            dx = obs_lon - pred_lon
            dy = obs_lat - pred_lat
        diff = np.array([dx, dy])
        try:
            inv_cov = np.linalg.inv(cov + np.eye(2) * 1e-6)  # 正则化
            return float(np.sqrt(diff @ inv_cov @ diff))
        except np.linalg.LinAlgError:
            return float(np.hypot(dx, dy))  # 退化到欧氏距离

    @staticmethod
    def _group_ais_fast(ais_records: List[TargetRecord]) -> Dict[str, List[TargetRecord]]:
        """快速GT分组（大数据量时用dict of lists替代逐条append）。"""
        from collections import defaultdict
        result: Dict[str, list] = defaultdict(list)
        for r in ais_records:
            mmsi = r.metadata.get("mmsi") or r.track_id
            key = mmsi if mmsi != "None" else r.track_id
            result[key].append(r)
        return dict(result)

    def associate(
        self,
        records_a: List[TargetRecord],
        records_b: List[TargetRecord],
        label_a: str = "radar",
        label_b: str = "ais",
    ) -> AssociationResult:
        """执行两源关联（通用化，支持任意 sensor 对）。

        Args:
            records_a: 第一组传感器记录（如雷达）
            records_b: 第二组传感器记录（如 AIS）
            label_a:   第一组标签（影响返回的 unmatched 键名）
            label_b:   第二组标签

        Returns:
            AssociationResult（通用字段 + 向后兼容字段）
        """
        import math as _math

        # ── 1. 按 track_id 分组 ──────────────────────────────
        tracks_a: Dict[str, List[TargetRecord]] = {}
        for r in records_a:
            tracks_a.setdefault(r.track_id, []).append(r)

        # 第二组用 metadata.mmsi 作为 track_id（AIS 场景）
        tracks_b: Dict[str, List[TargetRecord]] = {}
        for r in records_b:
            mmsi = r.metadata.get("mmsi") or r.track_id
            track_key = mmsi if mmsi != "None" else r.track_id
            tracks_b.setdefault(track_key, []).append(r)

        # ── 2. 预计算轨迹元数据 ──
        _cache_b: Dict[str, tuple] = {}
        for bid, recs in tracks_b.items():
            tmin, tmax, llat, llon = 1e18, -1e18, None, None
            for r in recs:
                if r.lat is None:
                    continue
                tmin = min(tmin, r.time)
                tmax = max(tmax, r.time)
                if llat is None or r.time >= tmax:
                    llat, llon = r.lat, r.lon
            if llat is not None:
                _cache_b[bid] = (tmin, tmax, llat, llon)

        # ── 3. 构造代价矩阵 ──
        ids_a = list(tracks_a.keys())
        ids_b = [b for b in list(tracks_b.keys()) if b in _cache_b]
        n, m = len(ids_a), len(ids_b)
        cost_matrix = np.full((n, m), 1e9, dtype=float)

        # 3a. 提取雷达目标的 MMSI（AT 类型目标自带 MMSI）
        radar_mmsi: Dict[str, Optional[str]] = {}
        for tid in ids_a:
            recs = tracks_a.get(tid, [])
            mmsi = recs[0].metadata.get("mmsi") if recs else None
            radar_mmsi[tid] = mmsi if mmsi and mmsi != "None" else None

        # 3a. 预计算 KF 预测（A侧每个轨迹）
        a_kf_cache: Dict[str, Optional[Tuple]] = {}
        if self.cfg.use_mahalanobis:
            for aid in ids_a:
                a_kf_cache[aid] = self._predict_with_kf(tracks_a[aid])

        has_origin = self._origin_lat is not None

        for i, aid in enumerate(ids_a):
            # ── MMSI 优先匹配 ──
            a_mmsi = radar_mmsi.get(aid)
            if a_mmsi:
                mm_match_idx = None
                for j, bid in enumerate(ids_b):
                    if bid == a_mmsi:
                        mm_match_idx = j
                        break
                if mm_match_idx is not None:
                    cost_matrix[i, mm_match_idx] = 0.0
                    continue  # 同MMSI → 强制匹配，跳过空间距离计算

            track = tracks_a[aid]
            a_tmin, a_tmax, a_llat, a_llon = 1e18, -1e18, None, None
            for r in track:
                if r.lat is None:
                    continue
                a_tmin = min(a_tmin, r.time)
                a_tmax = max(a_tmax, r.time)
                a_llat, a_llon = r.lat, r.lon
            if a_llat is None:
                continue

            # KF 预测数据
            kf_result = a_kf_cache.get(aid) if self.cfg.use_mahalanobis else None

            for j, bid in enumerate(ids_b):
                b_tmin, b_tmax, b_llat, b_llon = _cache_b[bid]
                ov_s = max(a_tmin, b_tmin)
                ov_e = min(a_tmax, b_tmax)
                ov_duration = ov_e - ov_s

                # 时间窗口有效性检查
                if ov_duration < 0:
                    continue  # 无时间重叠，跳过

                # 方法A：多点 Haversine（有重叠窗口时）
                if ov_duration > self.cfg.time_window_base:
                    a_lats, a_lons, a_times = [], [], []
                    for rr in track:
                        if rr.lat is not None and ov_s <= rr.time <= ov_e:
                            a_lats.append(rr.lat); a_lons.append(rr.lon)
                            a_times.append(rr.time)
                    b_lats, b_lons, b_times = [], [], []
                    for br in tracks_b[bid]:
                        if br.lat is not None and ov_s <= br.time <= ov_e:
                            b_lats.append(br.lat); b_lons.append(br.lon)
                            b_times.append(br.time)

                    if len(a_lats) >= 2 and len(b_lats) >= 2:
                        b_arr = np.column_stack([b_lats, b_lons, b_times])
                        dists = []
                        for k in range(len(a_lats)):
                            dt = np.abs(b_arr[:, 2] - a_times[k])
                            if dt.min() > self.cfg.time_window_tolerance:
                                continue  # 无时间容差内匹配
                            nearest = b_arr[dt.argmin()]
                            dists.append(_haversine_m(a_lats[k], a_lons[k],
                                                       float(nearest[0]), float(nearest[1])))
                        if not dists:
                            continue
                        dist = float(np.mean(dists))
                        if dist < self.cfg.distance_threshold:
                            cost_matrix[i, j] = dist
                            continue

                # 方法B：KF 预测 + 马氏距离（有 KF 预测时，要求时间重叠≥0）
                if kf_result is not None and ov_duration >= 0:
                    pred_lat, pred_lon, pred_x, pred_y, cov = kf_result
                    # 计算观测点与 KF 预测点之间的马氏距离
                    m_dist = self._mahalanobis_dist(
                        b_llat, b_llon, pred_lat, pred_lon, cov, has_origin,
                        origin_lat=self._origin_lat or 0.0,
                        origin_lon=self._origin_lon or 0.0,
                    )
                    # 马氏距离单位与 Haversine 可比，使用 distance_threshold
                    if m_dist < self.cfg.distance_threshold:
                        cost_matrix[i, j] = m_dist
                        self._kf_stats["kf_hits"] += 1
                        continue

                # 方法C：单点 Haversine（兜底，要求时间重叠≥0）
                if ov_duration >= 0:
                    dist = _haversine_m(a_llat, a_llon, b_llat, b_llon)
                    if dist < self.cfg.distance_threshold:
                        cost_matrix[i, j] = dist

        # 匈牙利算法
        row_ind, col_ind = self._hungarian(cost_matrix)

        pairs: List[AssociationPair] = []
        matched_a: Set[str] = set()
        matched_b: Set[str] = set()

        for i, j in zip(row_ind, col_ind):
            if cost_matrix[i, j] < 1e8:
                pairs.append(AssociationPair(
                    source1_id=ids_a[i],
                    source2_id=ids_b[j],
                    source1_label=label_a,
                    source2_label=label_b,
                    confidence=float(max(0.0, 1.0 - cost_matrix[i, j] / self.cfg.distance_threshold)),
                    method="kalman_mahalanobis" if self.cfg.use_mahalanobis and a_kf_cache.get(ids_a[i]) else "haversine",
                    verified=False,
                ))
                matched_a.add(ids_a[i])
                matched_b.add(ids_b[j])

        unmatched_a = [xid for xid in ids_a if xid not in matched_a]
        unmatched_b = [xid for xid in ids_b if xid not in matched_b]
        total_quality = float(np.mean([p.confidence for p in pairs])) if pairs else 0.0

        return AssociationResult(
            pairs=pairs,
            unmatched={label_a: unmatched_a, label_b: unmatched_b},
            total_quality=total_quality,
        )

    def associate_multi(
        self,
        source_records: Dict[str, List[TargetRecord]],
        pairs: Optional[List[Tuple[str, str]]] = None,
    ) -> Dict[str, AssociationResult]:
        """多源关联：对指定传感器对逐一执行关联。

        Args:
            source_records: {source_id: [TargetRecord, ...]}
            pairs: 要关联的传感器对列表，如 [("radar","ais"), ("ais","gps")]
                   默认自动对所有两两组合执行关联

        Returns:
            {(src1, src2): AssociationResult}
        """
        if pairs is None:
            # 自动对所有两两组合执行关联
            ids = list(source_records.keys())
            pairs = []
            for i in range(len(ids)):
                for j in range(i + 1, len(ids)):
                    pairs.append((ids[i], ids[j]))

        results = {}
        for src1, src2 in pairs:
            recs1 = source_records.get(src1, [])
            recs2 = source_records.get(src2, [])
            if not recs1 or not recs2:
                continue
            try:
                result = self.associate(recs1, recs2, label_a=src1, label_b=src2)
                results[(src1, src2)] = result
            except Exception as e:
                log.warning("多源关联失败 (%s ↔ %s): %s", src1, src2, e)
                results[(src1, src2)] = AssociationResult(
                    pairs=[],
                    unmatched={src1: [], src2: []},
                    total_quality=0.0,
                )
        return results

    @staticmethod
    def _hungarian(cost: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        """调用 scipy.optimize.linear_sum_assignment（无 scipy 时用朴素版）。"""
        try:
            from scipy.optimize import linear_sum_assignment
            row_ind, col_ind = linear_sum_assignment(cost)
            return row_ind, col_ind
        except ImportError:
            return AssociationEngine._hungarian_naive(cost)

    @staticmethod
    def _hungarian_naive(cost: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        """朴素匈牙利算法（O(n³)），无 scipy 时降级使用。"""
        n, m = cost.shape
        INF = 1e9
        u, v = np.zeros(n + 1), np.zeros(m + 1)
        p, way = np.zeros(m + 1, dtype=int), np.zeros(m + 1, dtype=int)

        for i in range(1, n + 1):
            p[0] = i
            j0 = 0
            minv = np.full(m + 1, INF)
            used = np.zeros(m + 1, dtype=bool)
            while True:
                used[j0] = True
                i0 = p[j0]
                delta = INF
                j1 = 0
                for j in range(1, m + 1):
                    if not used[j]:
                        cur = cost[i0 - 1, j - 1] - u[i0] - v[j]
                        if cur < minv[j]:
                            minv[j] = cur
                            way[j] = j0
                        if minv[j] < delta:
                            delta = minv[j]
                            j1 = j
                for j in range(m + 1):
                    if used[j]:
                        u[p[j]] += delta
                        v[j] -= delta
                    else:
                        minv[j] -= delta
                j0 = j1
                if p[j0] == 0:
                    break
            while True:
                j1 = way[j0]
                p[j0] = p[j1]
                j0 = j1
                if j1 == 0:
                    break
        ans_i = [p[j] - 1 for j in range(1, m + 1) if p[j] != 0]
        ans_j = [j - 1 for j in range(1, m + 1) if p[j] != 0]
        return np.array(ans_i, dtype=int), np.array(ans_j, dtype=int)
