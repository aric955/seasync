"""
SeaSync V2.2 ScanTracker — 逐帧扫描多目标跟踪器。
将离散的传感器测量点凝聚成连续轨迹，适用于：
- 雷达/ESM逐帧扫描数据（每帧多个目标）
- 无track_id的分立测量点
- 极坐标→经纬度转换后的传感器数据
"""

# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 荣火
from __future__ import annotations
from typing import List, Dict, Optional, Tuple
import math
import numpy as np

from ..core.data_models import TargetRecord
from ..core.geo import haversine_m_np as _haversine_m, xy_to_ll, meters_per_deg_lat, meters_per_deg_lon


class ScanTracker:
    """逐帧扫描多目标跟踪器。
    
    工作原理：
    1. 接收按时间排序的测量点（所有目标混合）
    2. 每个时间步，将测量点与已有轨迹关联（最近邻门控）
    3. 未关联的测量点初始化新轨迹
    4. 长时间未更新的轨迹终止

    自适应参数（auto_configure）：
    - 扫描周期：从时间间隔直方图峰值检测
    - 检测概率：从每圈点迹密度估计
    - 门控距离：基于目标最大速度×外推圈数
    - 外推步数：基于检测概率自适应
    """

    def __init__(
        self,
        gate_distance_m: float = 500.0,  # 关联门限（米），0=自动
        max_coast_steps: int = 5,        # 最大持续帧数（未更新则终止），0=自动
        min_track_points: int = 3,       # 最小轨迹点数（太短不输出）
        auto_scan_period: float = 0.0,   # 扫描周期（秒），0=自动检测
        max_speed_kn: float = 30.0,      # 目标最大航速（节），用于自动门限
    ) -> None:
        self.gate_distance_m = gate_distance_m
        self.max_coast_steps = max_coast_steps
        self.min_track_points = min_track_points
        self._auto_scan_period = auto_scan_period
        self._max_speed_kn = max_speed_kn
        self._next_track_id: int = 0
        self._tracks: Dict[str, dict] = {}  # track_id → {records, last_time, coast, kf}

    def auto_configure(self, records: List[TargetRecord]) -> None:
        """从数据中自动检测雷达参数并设置跟踪参数。"""
        if len(records) < 10:
            return
        times = sorted(set(r.time for r in records))
        if len(times) < 5:
            return
        diffs = [times[i+1] - times[i] for i in range(len(times)-1)]
        # 过滤同一圈内的微小时差(<0.1s)和异常值(>100s)
        diffs = [d for d in diffs if 0.1 < d < 100]
        if not diffs:
            return
        buckets = {}
        for d in diffs:
            bucket = round(d * 2) / 2.0
            buckets[bucket] = buckets.get(bucket, 0) + 1
        scan_period = max(buckets, key=buckets.get)
        self._auto_scan_period = scan_period
        total_dur = max(times) - min(times)
        n_scans = max(int(total_dur / max(scan_period, 0.01)), 1)
        pps = len(records) / n_scans
        seqs = set(r.metadata.get('seq', -1) for r in records)
        if len(seqs) > 1 and -1 not in seqs:
            est_t = len(seqs)
        else:
            # 无seq信息时，用平均每圈点数×2估计（假设每圈一半目标被检测）
            est_t = max(int(pps * 2), 3)
        pd = min(pps / max(est_t, 1), 1.0)
        max_ms = self._max_speed_kn * 0.51444
        if self.gate_distance_m <= 0:
            min_gate = max_ms * scan_period * max(1/max(pd, 0.01), 3)
            self.gate_distance_m = max(min_gate, 200.0)
        if self.max_coast_steps <= 0:
            self.max_coast_steps = min(max(int(1.0 / max(pd, 0.001) * 0.5), 3), 200)
        self._pd = pd
        self._n_scans = n_scans
        self._plots_per_scan = pps

    def process_scan(
        self, measurements: List[TargetRecord]
    ) -> None:
        """处理一批同一时刻的测量点。"""
        if not measurements:
            return

        scan_time = measurements[0].time
        # 确保同一批
        for m in measurements:
            assert abs(m.time - scan_time) < 0.01, "process_scan要求同一时刻的点"

        remaining = list(measurements)

        # 判断坐标模式：有lat/lon用Haversine，否则用欧氏距离
        has_latlon = any(m.lat is not None for m in measurements[:10])

        def _dist(m1, m2):
            if has_latlon:
                return _haversine_m(m1.lat or 0, m1.lon or 0, m2.lat or 0, m2.lon or 0)
            dx = (m1.x or 0) - (m2.x or 0)
            dy = (m1.y or 0) - (m2.y or 0)
            return math.sqrt(dx * dx + dy * dy)

        # 1. 预测已有轨迹到当前时间，门控关联
        updated = set()
        for tid, track in list(self._tracks.items()):
            if track.get('terminated'):
                continue
            last = track['records'][-1]
            dt = scan_time - track['last_time']
            if dt < 0:
                continue  # 数据乱序

            # 预测：用速度外推（简单线性）
            if has_latlon:
                pred_lat = last.lat
                pred_lon = last.lon
                if track.get('vx') is not None and dt > 0:
                    pred_lat, pred_lon = xy_to_ll(last.lat, last.lon,
                                                    track['vx'] * dt, track['vy'] * dt)
            else:
                pred_lat, pred_lon = 0, 0  # 占位不用

            # 门控：找最近的测量点
            best_dist, best_idx = self.gate_distance_m + 1, -1
            for i, m in enumerate(remaining):
                d = _dist(last, m)
                if d < best_dist:
                    best_dist, best_idx = d, i

            if best_idx >= 0:
                # 匹配 → 更新轨迹
                track['records'].append(remaining[best_idx])
                track['last_time'] = scan_time
                track['coast'] = 0
                # 估算速度
                n1, n2 = track['records'][-2], track['records'][-1]
                dt_t = n2.time - n1.time
                if has_latlon:
                    track['vx'] = (n2.lon - n1.lon) / max(dt_t, 0.001) * meters_per_deg_lon((n1.lat + n2.lat) / 2)
                    track['vy'] = (n2.lat - n1.lat) / max(dt_t, 0.001) * meters_per_deg_lat()
                else:
                    track['vx'] = ((n2.x or 0) - (n1.x or 0)) / max(dt_t, 0.001)
                    track['vy'] = ((n2.y or 0) - (n1.y or 0)) / max(dt_t, 0.001)
                remaining.pop(best_idx)
                updated.add(tid)

        # 2. 未匹配的测量点 → 新轨迹
        for m in remaining:
            tid = f"ST_{self._next_track_id}"
            self._next_track_id += 1
            self._tracks[tid] = {
                'records': [m],
                'last_time': scan_time,
                'coast': 0,
                'vx': None,
                'vy': None,
                'terminated': False,
            }

        # 3. 未更新的轨迹增加coast计数
        for tid, track in self._tracks.items():
            if track.get('terminated'):
                continue
            if tid not in updated:
                track['coast'] += 1
                if track['coast'] >= self.max_coast_steps:
                    track['terminated'] = True

    def get_active_tracks(self) -> Dict[str, List[TargetRecord]]:
        """返回活跃轨迹（未终止的）。"""
        return {
            tid: t['records']
            for tid, t in self._tracks.items()
            if not t.get('terminated')
        }

    def get_completed_tracks(self) -> Dict[str, List[TargetRecord]]:
        """返回已完成轨迹（已终止且点足够）。"""
        return {
            tid: t['records']
            for tid, t in self._tracks.items()
            if t.get('terminated') and len(t['records']) >= self.min_track_points
        }

    def get_all_tracks(self) -> Dict[str, List[TargetRecord]]:
        """返回所有轨迹。"""
        return {
            tid: t['records']
            for tid, t in self._tracks.items()
            if len(t['records']) >= self.min_track_points and not t.get('terminated', False)
        }

    def process_all(
        self, records: List[TargetRecord]
    ) -> Dict[str, List[TargetRecord]]:
        """批量处理所有测量点（自动按时间分组）。"""
        # 自动检测参数
        self.auto_configure(records)

        from collections import defaultdict
        by_time = defaultdict(list)
        for r in records:
            by_time[r.time].append(r)

        for t in sorted(by_time.keys()):
            self.process_scan(by_time[t])

        # 返回已完成轨迹 + 活跃轨迹
        result = self.get_completed_tracks()
        for tid, recs in self.get_active_tracks().items():
            if len(recs) >= self.min_track_points:
                result[tid] = recs
        return result
