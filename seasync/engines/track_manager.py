"""
SeaSync V2.2 TrackManager — 轨迹管理器。
维护、更新和查询多目标轨迹。
"""

# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 荣火
from __future__ import annotations
from typing import List, Dict, Optional, Tuple
from collections import defaultdict
import bisect
import numpy as np

from ..core.data_models import TargetRecord


class TrackManager:
    """管理多条轨迹的生命周期。"""

    def __init__(self, max_gap_sec: float = 60.0) -> None:
        # track_id → 按时间排序的记录列表
        self._tracks: Dict[str, List[TargetRecord]] = defaultdict(list)
        self._max_gap = max_gap_sec

    # ── 写入 ─────────────────────────────────────────────────

    def add(self, record: TargetRecord) -> None:
        """追加单条记录到对应轨迹（二分插入 O(log n)）。"""
        bisect.insort(
            self._tracks[record.track_id], record,
            key=lambda r: r.time,
        )

    def add_batch(self, records: List[TargetRecord]) -> None:
        """批量追加后按轨迹分别排序。"""
        by_track: Dict[str, List[TargetRecord]] = {}
        for r in records:
            by_track.setdefault(r.track_id, []).append(r)
        for tid, recs in by_track.items():
            self._tracks[tid].extend(recs)
            self._tracks[tid].sort(key=lambda r: r.time)

    def update_track_id(self, old_id: str, new_id: str) -> None:
        """合并轨迹：old_id → new_id。"""
        if old_id not in self._tracks:
            return
        self._tracks[new_id].extend(self._tracks[old_id])
        self._tracks[new_id].sort(key=lambda r: r.time)
        del self._tracks[old_id]

    # ── 查询 ─────────────────────────────────────────────────

    def get_track(self, track_id: str) -> List[TargetRecord]:
        return self._tracks.get(track_id, [])

    def list_track_ids(self) -> List[str]:
        return list(self._tracks.keys())

    def get_latest(self, track_id: str) -> Optional[TargetRecord]:
        track = self._tracks.get(track_id)
        if not track:
            return None
        return max(track, key=lambda r: r.time)

    def get_time_range(self) -> Tuple[float, float]:
        all_times = [r.time for tr in self._tracks.values() for r in tr]
        return (min(all_times), max(all_times)) if all_times else (0.0, 0.0)

    # ── 统计 ─────────────────────────────────────────────────

    def summary(self) -> Dict[str, int]:
        n_tracks = len(self._tracks)
        n_points = sum(len(t) for t in self._tracks.values())
        durations = []
        for tr in self._tracks.values():
            if len(tr) >= 2:
                durations.append(tr[-1].time - tr[0].time)
        avg_dur = float(np.mean(durations)) if durations else 0.0
        return {
            "n_tracks": n_tracks,
            "n_points": n_points,
            "avg_duration_sec": avg_dur,
            "max_duration_sec": float(max(durations)) if durations else 0.0,
        }

    # ── 过滤 ─────────────────────────────────────────────────

    def filter_by_source(self, source_id: str) -> List[TargetRecord]:
        """只保留指定数据源的记录。"""
        result = []
        for tr in self._tracks.values():
            for r in tr:
                if r.source_id == source_id:
                    result.append(r)
        return result

    def filter_by_time_range(self, t_start: float, t_end: float) -> "TrackManager":
        """返回时间范围内的轨迹管理器（新实例）。"""
        tm = TrackManager(max_gap_sec=self._max_gap)
        for tid, tr in self._tracks.items():
            filtered = [r for r in tr if t_start <= r.time <= t_end]
            for r in filtered:
                tm.add(r)
        return tm

    def split_by_gap(self, gap_sec: Optional[float] = None) -> List[List[TargetRecord]]:
        """按时间间隙分割轨迹，返回子轨迹列表。"""
        gap = gap_sec or self._max_gap
        all_records: List[Tuple[float, TargetRecord]] = []
        for tr in self._tracks.values():
            for r in tr:
                all_records.append((r.time, r))
        all_records.sort(key=lambda x: x[0])
        if not all_records:
            return []
        segments: List[List[TargetRecord]] = []
        current: List[TargetRecord] = []
        prev_time: Optional[float] = None
        for _, r in all_records:
            if prev_time is not None and r.time - prev_time > gap:
                if current:
                    segments.append(current)
                current = []
            current.append(r)
            prev_time = r.time
        if current:
            segments.append(current)
        return segments

    def __len__(self) -> int:
        return len(self._tracks)
