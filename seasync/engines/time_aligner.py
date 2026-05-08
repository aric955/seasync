"""
SeaSync V2.2 TimeAligner — 时域对齐引擎。
使用互相关法（CCF）自动估算两个数据源间的时间偏移。
"""

# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 荣火
from __future__ import annotations
from typing import List, Tuple, Optional
import numpy as np

from ..core.data_models import TargetRecord, AlignmentResult


def _build_time_series(
    records: List[TargetRecord], bin_sec: float = 1.0
) -> Tuple[np.ndarray, np.ndarray]:
    """将记录列表转为等间隔密度时间序列（返回 times, counts）。"""
    if not records:
        return np.array([]), np.array([])
    times = np.array([r.time for r in records])
    t_min, t_max = times.min(), times.max()
    n_bins = max(1, int((t_max - t_min) / bin_sec) + 1)
    bins = np.linspace(t_min, t_max, n_bins + 1)
    counts, _ = np.histogram(times, bins=bins)
    bin_centers = (bins[:-1] + bins[1:]) / 2
    return bin_centers, counts.astype(float)


class TimeAligner:
    """时域对齐引擎。"""

    def __init__(self, bin_sec: float = 1.0) -> None:
        self.bin_sec = bin_sec

    def align(
        self,
        source_a: List[TargetRecord],
        source_b: List[TargetRecord],
    ) -> AlignmentResult:
        """计算 source_b 相对于 source_a 的时间偏移。"""
        if not source_a or not source_b:
            return AlignmentResult(
                offset=0.0, quality_score=0.0,
                suggestion="数据不足，无法对齐", needs_manual=True,
            )

        times_a, counts_a = _build_time_series(source_a, self.bin_sec)
        times_b, counts_b = _build_time_series(source_b, self.bin_sec)

        if len(counts_a) < 3 or len(counts_b) < 3:
            return AlignmentResult(
                offset=0.0, quality_score=0.0,
                suggestion="数据不足，无法对齐", needs_manual=True,
            )

        # 对齐长度
        min_len = min(len(counts_a), len(counts_b))
        if min_len < 3:
            return AlignmentResult(
                offset=0.0, quality_score=0.0,
                suggestion="数据不足，无法对齐", needs_manual=True,
            )
        
        ca = counts_a[:min_len]
        cb = counts_b[:min_len]

        # 归一化（处理标准差为0的情况）
        std_a = ca.std()
        std_b = cb.std()
        if std_a < 1e-9 or std_b < 1e-9:
            return AlignmentResult(
                offset=0.0, quality_score=0.0,
                suggestion="时间序列无变化，无法对齐", needs_manual=True,
            )
        
        ca = (ca - ca.mean()) / std_a
        cb = (cb - cb.mean()) / std_b

        try:
            from scipy.signal import correlate
            corr = correlate(ca, cb, mode="full")
            lags = np.arange(-(len(ca) - 1), len(cb))
            best_idx = int(np.argmax(corr))
            best_lag = lags[best_idx]
            offset = best_lag * self.bin_sec
            quality = float(np.max(corr) / (len(ca) + 1e-9))
        except ImportError:
            # 朴素滑动窗口
            best_corr = -1e9
            best_offset = 0.0
            for lag in range(-len(ca) + 1, len(cb)):
                s = lag if lag >= 0 else 0
                e = lag + len(ca) if lag >= 0 else len(ca)
                s2 = 0 if lag >= 0 else -lag
                e2 = len(cb) if lag >= 0 else len(cb) + lag
                part_a = ca[s:e]
                part_b = cb[s2:e2]
                if len(part_a) < 2 or len(part_b) < 2 or len(part_a) != len(part_b):
                    continue
                if np.std(part_a) < 1e-9 or np.std(part_b) < 1e-9:
                    continue
                corr = float(np.corrcoef(part_a, part_b)[0, 1])
                if corr > best_corr:
                    best_corr = corr
                    best_offset = lag * self.bin_sec
            offset = best_offset
            quality = best_corr

        needs_manual = abs(quality) < 0.3 or abs(offset) > 3600
        suggestion = (
            f"检测到时间偏移 {offset:+.1f}s，"
            f"质量分数 {quality:.3f}，{'建议手动确认' if needs_manual else '对齐质量良好'}。"
        )
        return AlignmentResult(
            offset=float(offset),
            quality_score=float(quality),
            suggestion=suggestion,
            needs_manual=needs_manual,
        )

    def apply_offset(
        self, records: List[TargetRecord], offset: float
    ) -> List[TargetRecord]:
        """对记录列表应用时间偏移（复制，不修改原数据）。"""
        import copy
        result = []
        for r in records:
            new_r = copy.deepcopy(r)
            new_r.time = r.time + offset
            result.append(new_r)
        return result
