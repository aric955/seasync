"""
SeaSync V2.2 EventDetector — 事件检测引擎。
支持多种规则检测：碰撞预警、偏离航道、异常停船等。
"""

# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 荣火
from __future__ import annotations
from typing import List, Dict, Tuple, Optional
import uuid
import numpy as np

from ..core.data_models import TargetRecord, EventRecord
from ..core.geo import haversine_m_np as _haversine_m


class EventDetector:
    """事件检测引擎。"""

    def __init__(self) -> None:
        self._handlers: Dict[str, callable] = {}

    # ── 内置检测规则 ─────────────────────────────────────────

    @staticmethod
    def detect_collision_risk(
        track_a: List[TargetRecord],
        track_b: List[TargetRecord],
        distance_threshold_m: float = 500.0,
    ) -> List[EventRecord]:
        """检测两轨迹间是否存在碰撞风险（最近距离 < 阈值）。"""
        events = []
        for ra in track_a:
            if ra.lat is None or ra.lon is None:
                continue
            for rb in track_b:
                if rb.lat is None or rb.lon is None:
                    continue
                dist = _haversine_m(ra.lat, ra.lon, rb.lat, rb.lon)
                if dist < distance_threshold_m:
                    events.append(EventRecord(
                        id=str(uuid.uuid4()),
                        time=min(ra.time, rb.time),
                        name="碰撞预警",
                        severity="warning",
                        description=(
                            f"轨迹 {ra.track_id} 与 {rb.track_id} "
                            f"在 t={min(ra.time,rb.time):.1f}s 距离 {dist:.1f}m（阈值 {distance_threshold_m}m）"
                        ),
                        evidence_path="",
                        auto_detected=True,
                    ))
        return events

    @staticmethod
    def detect_stationary(
        track: List[TargetRecord],
        speed_threshold_kn: float = 0.5,
        min_duration_sec: float = 300.0,
    ) -> List[EventRecord]:
        """检测异常停船事件（长时间低速或零速）。"""
        if len(track) < 2:
            return []
        events = []
        stationary_start: Optional[float] = None
        last_record: Optional[TargetRecord] = None
        for r in sorted(track, key=lambda x: x.time):
            speed = r.speed if r.speed is not None else 0.0
            if speed < speed_threshold_kn:
                if stationary_start is None:
                    stationary_start = r.time
                last_record = r
            else:
                if stationary_start is not None and last_record is not None:
                    dur = last_record.time - stationary_start
                    if dur >= min_duration_sec:
                        events.append(EventRecord(
                            id=str(uuid.uuid4()),
                            time=stationary_start,
                            name="异常停船",
                            severity="info",
                            description=(
                                f"轨迹 {track[0].track_id} 在 "
                                f"{stationary_start:.1f}s 至 {last_record.time:.1f}s "
                                f"（持续 {dur:.0f}s）速度 < {speed_threshold_kn}kn"
                            ),
                            auto_detected=True,
                        ))
                stationary_start = None
        # 循环结束时如果仍在停船状态，也触发事件
        if stationary_start is not None and last_record is not None:
            dur = last_record.time - stationary_start
            if dur >= min_duration_sec:
                events.append(EventRecord(
                    id=str(uuid.uuid4()),
                    time=stationary_start,
                    name="异常停船",
                    severity="info",
                    description=(
                        f"轨迹 {track[0].track_id} 在 "
                        f"{stationary_start:.1f}s 至 {last_record.time:.1f}s "
                        f"（持续 {dur:.0f}s）速度 < {speed_threshold_kn}kn"
                    ),
                    auto_detected=True,
                ))
        return events

    @staticmethod
    def detect_manoeuvre(
        track: List[TargetRecord],
        course_change_threshold_deg: float = 45.0,
        min_speed_kn: float = 1.0,
    ) -> List[EventRecord]:
        """检测大角度机动（急转）。"""
        if len(track) < 3:
            return []
        events = []
        prev_course: Optional[float] = None
        prev_record: Optional[TargetRecord] = None
        for r in sorted(track, key=lambda x: x.time):
            if r.course is None or r.speed is None or r.speed < min_speed_kn:
                prev_course = None
                prev_record = r
                continue
            if prev_course is not None and prev_record is not None:
                delta = abs(r.course - prev_course)
                delta = min(delta, 360 - delta)  # 取小角
                if delta > course_change_threshold_deg:
                    events.append(EventRecord(
                        id=str(uuid.uuid4()),
                        time=r.time,
                        name="大角度机动",
                        severity="info",
                        description=(
                            f"轨迹 {r.track_id} 在 t={r.time:.1f}s "
                            f"航向变化 {delta:.1f}°（阈值 {course_change_threshold_deg}°）"
                        ),
                        auto_detected=True,
                    ))
            prev_course = r.course
            prev_record = r
        return events

    @staticmethod
    def detect_area_violation(
        track: List[TargetRecord],
        boundary_lat: Tuple[float, float],
        boundary_lon: Tuple[float, float],
    ) -> List[EventRecord]:
        """检测是否进入/离开指定区域。"""
        events = []
        for r in track:
            if r.lat is None or r.lon is None:
                continue
            lat_min, lat_max = boundary_lat
            lon_min, lon_max = boundary_lon
            inside = lat_min <= r.lat <= lat_max and lon_min <= r.lon <= lon_max
            if not inside:
                events.append(EventRecord(
                    id=str(uuid.uuid4()),
                    time=r.time,
                    name="区域违规",
                    severity="warning",
                    description=(
                        f"轨迹 {r.track_id} 在 t={r.time:.1f}s "
                        f"位置 ({r.lat:.5f}, {r.lon:.5f}) 超出边界区域"
                    ),
                    auto_detected=True,
                ))
        return events

    # ── 统一检测接口 ─────────────────────────────────────────

    def detect_all(
        self,
        tracks: Dict[str, List[TargetRecord]],
        rules: Optional[List[str]] = None,
        **kwargs,
    ) -> List[EventRecord]:
        """对多条轨迹运行所有或指定规则。"""
        rules = rules or ["stationary", "manoeuvre"]
        all_events: List[EventRecord] = []
        track_ids = list(tracks.keys())

        if "stationary" in rules:
            for tid, tr in tracks.items():
                all_events.extend(self.detect_stationary(tr, **kwargs))

        if "manoeuvre" in rules:
            for tid, tr in tracks.items():
                all_events.extend(self.detect_manoeuvre(tr, **kwargs))

        if "collision" in rules and len(track_ids) >= 2:
            for i in range(len(track_ids)):
                for j in range(i + 1, len(track_ids)):
                    all_events.extend(self.detect_collision_risk(
                        tracks[track_ids[i]], tracks[track_ids[j]], **kwargs
                    ))

        return all_events


