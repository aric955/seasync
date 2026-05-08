"""
SeaSync WorkerThread — 后台处理线程。
将长时间运行的 Pipeline 计算移到后台，避免 GUI 冻结。
"""

# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 荣火
from __future__ import annotations
from typing import Optional, List, Dict
from PyQt5 import QtCore


class WorkerThread(QtCore.QThread):
    """执行长时间运算的后台线程。"""

    finished = QtCore.pyqtSignal(object)          # 传递结果
    error = QtCore.pyqtSignal(str)               # 传递错误信息
    progress = QtCore.pyqtSignal(str)            # 传递进度消息

    def __init__(self, task_type: str, pipeline,
                 radar_sid: Optional[str] = None,
                 ais_sid: Optional[str] = None,
                 all_sids: Optional[List[str]] = None,
                 params: Optional[Dict[str, float]] = None):
        super().__init__()
        self.task_type = task_type
        self.pipeline = pipeline
        self.radar_sid = radar_sid
        self.ais_sid = ais_sid
        self.all_sids = all_sids
        self.params = params or {}

    def run(self):
        """线程主函数，在后台执行。"""
        try:
            if self.task_type == "run_pipeline":
                self._run_pipeline()
            elif self.task_type == "multi_associate":
                self._run_multi_associate()
            else:
                raise ValueError(f"未知任务类型: {self.task_type}")
        except Exception as e:
            import traceback
            self.error.emit(f"{self.task_type} 失败: {e}\n{traceback.format_exc()[-500:]}")

    def _run_pipeline(self):
        """执行完整流程（N 源模式优先）。"""
        if hasattr(self.pipeline, 'config'):
            cfg = self.pipeline.config
            if hasattr(cfg, 'distance_threshold'):
                cfg.distance_threshold = self.params.get("distance_threshold", 500.0)
            if hasattr(cfg, 'time_window_base'):
                cfg.time_window_base = self.params.get("time_window_base", 5.0)
            if hasattr(cfg, 'time_window_tolerance'):
                cfg.time_window_tolerance = self.params.get("time_window_tolerance", 2.0)
            if hasattr(cfg, 'min_confidence'):
                cfg.min_confidence = self.params.get("min_confidence", 0.6)
            if hasattr(cfg, 'use_mahalanobis'):
                cfg.use_mahalanobis = self.params.get("use_mahalanobis", True)

        def _progress(stage, pct, msg):
            self.progress.emit(f"[{pct:3.0f}%] {msg}")

        self.progress.emit("正在运行处理流程...")

        # N 源模式优先
        if self.all_sids and len(self.all_sids) >= 2:
            steps = self.pipeline.run(source_ids=self.all_sids, progress_callback=_progress)
        else:
            steps = self.pipeline.run(self.radar_sid, self.ais_sid, progress_callback=_progress)

        steps["_radar_sid"] = self.radar_sid
        steps["_ais_sid"] = self.ais_sid
        self.finished.emit(steps)

    def _run_multi_associate(self):
        """执行多源关联。"""
        self.progress.emit("正在执行多源关联...")
        total = len(self.all_sids) if self.all_sids else 0
        processed = 0
        results = {}
        source_records = {sid: self.pipeline.get_records(sid) for sid in (self.all_sids or [])}
        for i in range(len(self.all_sids or [])):
            for j in range(i + 1, len(self.all_sids or [])):
                s1, s2 = self.all_sids[i], self.all_sids[j]
                recs1 = source_records.get(s1, [])
                recs2 = source_records.get(s2, [])
                if not recs1 or not recs2:
                    continue
                try:
                    self.progress.emit(f"  关联 {s1[:12]} ↔ {s2[:12]} ...")
                    result = self.pipeline._assoc.associate(recs1, recs2, label_a=s1, label_b=s2)
                    results[(s1, s2)] = result
                    processed += 1
                    pct = (processed / max(total - 1, 1)) * 100
                    self.progress.emit(f"    → {len(result.pairs)}对, 质量={result.total_quality:.3f}")
                except Exception as e:
                    self.progress.emit(f"    → 失败: {e}")

        min_conf = getattr(self.pipeline.config, 'min_confidence', 0.6)
        if min_conf > 0:
            for pair in results:
                r = results[pair]
                if r.pairs:
                    r.pairs = [p for p in r.pairs if p.confidence >= min_conf]

        self.progress.emit(f"多源关联完成: {len(results)}组, {processed}对")
        self.finished.emit(results)
