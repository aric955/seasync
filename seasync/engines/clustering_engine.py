"""
SeaSync V2.2 ClusteringEngine — 自适应DBSCAN聚类引擎。
对雷达原始点迹进行凝聚，生成稳定航迹。
"""

# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 荣火
from __future__ import annotations
from typing import List, Dict, Tuple
import numpy as np
import pandas as pd

from ..core.data_models import TargetRecord
from ..core.geo import haversine_m_np as _haversine_m, meters_per_deg_lat


class ClusteringEngine:
    """DBSCAN 自适应聚类。"""

    def __init__(
        self,
        eps_m: float = 100.0,      # 空间半径（米）
        eps_t: float = 30.0,       # 时间窗口（秒）
        min_samples: int = 3,      # 最小点数
    ) -> None:
        self.eps_m = eps_m
        self.eps_t = eps_t
        self.min_samples = min_samples

    def cluster(self, records: List[TargetRecord]) -> Dict[int, List[TargetRecord]]:
        """对点迹列表进行聚类，返回 {cluster_id: [records]}。

        自动选择坐标空间：
        - 有 lat/lon：用 Haversine 距离（经纬度空间）
        - 仅有 x/y：用欧氏距离（米）
        - 都有时优先用 lat/lon
        """
        if not records:
            return {}

        # 判断坐标空间
        has_latlon = any(r.lat is not None for r in records[:10])
        has_xy = any(r.x is not None for r in records[:10])

        if has_latlon:
            # 经纬度空间：用 Haversine
            pts = []
            for r in records:
                lat = r.lat if r.lat is not None else 0.0
                lon = r.lon if r.lon is not None else 0.0
                pts.append([lat, lon, r.time])
            X = np.array(pts)
            t_scale = self.eps_m / max(self.eps_t, 1.0) / meters_per_deg_lat()  # 时间→度
            X_norm = X.copy()
            X_norm[:, 2] = X[:, 2] * t_scale
            labels = self._dbscan_haversine(X_norm)
        elif has_xy:
            # 笛卡尔空间：用欧氏距离（原方法）
            pts = []
            for r in records:
                x = r.x if r.x is not None else 0.0
                y = r.y if r.y is not None else 0.0
                pts.append([x, y, r.time])
            X = np.array(pts)
            t_scale = self.eps_m / max(self.eps_t, 1.0)
            X_norm = X.copy()
            X_norm[:, 2] = X[:, 2] * t_scale
            labels = self._dbscan(X_norm)
        else:
            return {}
        clusters: Dict[int, List[TargetRecord]] = {}
        for i, label in enumerate(labels):
            clusters.setdefault(label, []).append(records[i])
        return clusters

    def _dbscan(self, X: np.ndarray) -> np.ndarray:
        """DBSCAN 实现。"""
        n = len(X)
        labels = np.full(n, -1, dtype=int)
        cluster_id = 0

        # 构建 KDTree 加速近邻查询
        try:
            from scipy.spatial import KDTree
            tree = KDTree(X)
        except ImportError:
            tree = None

        for i in range(n):
            if labels[i] != -1:
                continue
            # 找邻域
            neighbors = self._range_query(X, i, tree)
            if len(neighbors) < self.min_samples:
                continue
            # 扩展聚类
            labels[i] = cluster_id
            seeds = set(neighbors)
            seeds.discard(i)
            while seeds:
                q = seeds.pop()
                if labels[q] == -1:
                    labels[q] = cluster_id
                    n_q = self._range_query(X, q, tree)
                    if len(n_q) >= self.min_samples:
                        seeds.update(n_q)
            cluster_id += 1

        # 标记噪声点（-1 → -2 更明确）
        labels[labels == -1] = -2
        return labels

    def _dbscan_haversine(self, X: np.ndarray) -> np.ndarray:
        """Haversine 版 DBSCAN（经纬度空间）。"""
        n = len(X)
        labels = np.full(n, -1, dtype=int)
        cluster_id = 0

        try:
            from scipy.spatial import KDTree
            # 用经纬度直接做 KDTree（小范围近似平面）
            tree = KDTree(X[:, :2])
        except ImportError:
            tree = None

        for i in range(n):
            if labels[i] != -1:
                continue
            if tree is not None:
                eps_deg = self.eps_m / meters_per_deg_lat()
                neighbors = set(tree.query_ball_point(X[i, :2], eps_deg))
            else:
                dists = np.array([_haversine_m(X[i, 0], X[i, 1], X[j, 0], X[j, 1]) for j in range(n)])
                neighbors = set(np.where(dists <= self.eps_m)[0])
            if len(neighbors) < self.min_samples:
                continue
            labels[i] = cluster_id
            seeds = set(neighbors)
            seeds.discard(i)
            while seeds:
                q = seeds.pop()
                if labels[q] == -1:
                    labels[q] = cluster_id
                    if tree is not None:
                        n_q = set(tree.query_ball_point(X[q, :2], eps_deg))
                    else:
                        dists_q = np.array([_haversine_m(X[q, 0], X[q, 1], X[j, 0], X[j, 1]) for j in range(n)])
                        n_q = set(np.where(dists_q <= self.eps_m)[0])
                    if len(n_q) >= self.min_samples:
                        seeds.update(n_q)
            cluster_id += 1
        labels[labels == -1] = -2
        return labels

    def cluster_to_tracks(self, records: List[TargetRecord]) -> Dict[str, List[TargetRecord]]:
        """聚类并将每个簇作为一条轨迹返回，用于后续关联。"""
        clusters = self.cluster(records)
        tracks: Dict[str, List[TargetRecord]] = {}
        for cid, members in clusters.items():
            if cid < 0:
                continue  # 跳过噪声点
            tid = f"CLUSTER_{cid}"
            tracks[tid] = sorted(members, key=lambda r: r.time)
        return tracks

    def _range_query(
        self, X: np.ndarray, i: int, tree
    ) -> set:
        """返回距离 i 在 eps 内的所有点索引。"""
        if tree is not None:
            indices = tree.query_ball_point(X[i], self.eps_m)
            return set(indices)
        # 朴素 O(n)
        dists = np.linalg.norm(X - X[i], axis=1)
        return set(np.where(dists <= self.eps_m)[0])

    def fit_transform(
        self, records: List[TargetRecord]
    ) -> Tuple[Dict[int, List[TargetRecord]], List[Tuple[float, float]]]:
        """聚类并计算每个簇的质心轨迹（简化：取中位数）。"""
        clusters = self.cluster(records)
        centroids: List[Tuple[float, float]] = []
        for cluster_records in clusters.values():
            if cluster_records:
                lats = [r.lat for r in cluster_records if r.lat is not None]
                lons = [r.lon for r in cluster_records if r.lon is not None]
                cx = float(np.median(lats)) if lats else 0.0
                cy = float(np.median(lons)) if lons else 0.0
                centroids.append((cx, cy))
            else:
                centroids.append((0.0, 0.0))
        return clusters, centroids
