"""
SeaSync V2.2 Pipeline — 全流程处理管道。
Orchestrate: 导入 → 坐标转换 → 聚类 → 时间对齐 → 关联 → 事件检测 → 报告。
"""

# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 荣火
from __future__ import annotations
from typing import List, Dict, Optional, Any
import copy

from ..core.data_models import (
    TargetRecord,
    AssociationResult,
    AlignmentResult,
    EventRecord,
)
from ..core.association_config import AssociationConfig
from ..core.logger import log
from ..core.project_manager import ProjectManager
from ..adapters.import_manager import ImportManager
from ..engines.association_engine import AssociationEngine
from ..engines.clustering_engine import ClusteringEngine
from ..engines.time_aligner import TimeAligner
from ..engines.track_manager import TrackManager
from ..engines.event_detector import EventDetector


class SeaSyncPipeline:
    """SeaSync 全流程管道。

    ═══════════════════════════════════════════════════════
    N 源模式（标准用法，推荐）：
    ═══════════════════════════════════════════════════════

        pipe = SeaSyncPipeline()
        pipe.add_source("radar.csv", source_type="radar")
        pipe.add_source("ais_ship1.csv", source_type="ais")
        pipe.add_source("ais_ship2.csv", source_type="ais")
        pipe.add_source("ais_ship3.csv", source_type="ais")

        # 一键运行 N 源全流程
        steps = pipe.run(source_ids=["radar", "ais_ship1", "ais_ship2", "ais_ship3"])

    ═══════════════════════════════════════════════════════
    双源模式（向后兼容）：
    ═══════════════════════════════════════════════════════

        pipe = SeaSyncPipeline()
        pipe.add_source("radar.csv", source_type="radar")
        pipe.add_source("ais.csv", source_type="ais")
        steps = pipe.run("radar_sid", "ais_sid")
    """

    def __init__(
        self,
        config: Optional[AssociationConfig] = None,
        project_id: Optional[str] = None,
        db_path: Optional[str] = None,
        origin_lat: Optional[float] = None,
        origin_lon: Optional[float] = None,
    ) -> None:
        self.config = config or AssociationConfig()
        self.project_id = project_id
        self._origin_lat = origin_lat
        self._origin_lon = origin_lon
        self._im = ImportManager()
        self._assoc = AssociationEngine(self.config, origin_lat=origin_lat, origin_lon=origin_lon)
        self._cluster = ClusteringEngine(
            eps_m=config.sensor_uncertainty.get("radar", 20.0) * 5
            if config else 100.0,
            min_samples=3,
        )
        self._aligner = TimeAligner()
        self._detector = EventDetector()
        # 可选持久化
        self._pm: Optional[ProjectManager] = None
        if project_id or db_path:
            self._pm = ProjectManager(db_path)
            if project_id:
                self._pm.get_project(project_id)

    # ── 自动推算雷达站原点 ──────────────────────────────────

    def auto_detect_origin(
        self, radar_source_id: str, ais_source_id: str
    ) -> tuple:
        """从雷达AT+AIS数据交叉推算雷达站经纬度原点。"""
        import numpy as np
        from ..core.geo import xy_to_ll

        radar_recs = self.get_records(radar_source_id)
        ais_recs = self.get_records(ais_source_id)

        # 按MMSI索引AIS数据（取每条轨迹的最新lat/lon）
        ais_by_mmsi = {}
        for r in ais_recs:
            mmsi = r.metadata.get("mmsi") or r.track_id
            if mmsi and r.lat is not None:
                if mmsi not in ais_by_mmsi or r.time > ais_by_mmsi[mmsi].time:
                    ais_by_mmsi[mmsi] = r

        # 找雷达中有MMSI且有极坐标xy的记录
        origins = []
        for r in radar_recs:
            mmsi = r.metadata.get("mmsi")
            if not mmsi or r.x is None or r.y is None:
                continue
            ais_tgt = ais_by_mmsi.get(mmsi)
            if ais_tgt is None:
                continue
            # 反推雷达站原点：AIS的lat/lon减去极坐标xy偏移
            olat, olon = xy_to_ll(ais_tgt.lat, ais_tgt.lon, -r.x, -r.y)
            origins.append((olat, olon))

        if not origins:
            return (None, None)

        # 取中位数抗噪
        lats = np.median([o[0] for o in origins])
        lons = np.median([o[1] for o in origins])
        self._origin_lat, self._origin_lon = float(lats), float(lons)
        # 同步更新关联引擎
        self._assoc._origin_lat = self._origin_lat
        self._assoc._origin_lon = self._origin_lon

        # 用新原点重新加载雷达源（以获得lat/lon）
        adapter = self._im._adapters.get(radar_source_id)
        if adapter is not None and hasattr(adapter, '_origin_lat'):
            adapter._origin_lat = self._origin_lat
            adapter._origin_lon = self._origin_lon
            # 重载所有源（clear_cache后重载雷达+AIS，否则AIS缓存丢失）
            all_sids = list(self._im._adapters.keys())
            self._im.clear_cache()
            for sid in all_sids:
                try:
                    self._im.load(sid)
                except Exception:
                    pass

        return (self._origin_lat, self._origin_lon)

    # ── 按目标类型过滤 ──────────────────────────────────────

    def filter_by_target_type(
        self, source_id: str, target_types: list
    ) -> List['TargetRecord']:
        """按 metadata['target_type'] 过滤数据源记录。"""
        all_recs = self.get_records(source_id)
        return [r for r in all_recs if r.metadata.get("target_type") in target_types]

    # ── 数据导入阶段 ─────────────────────────────────────────

    def add_source(self, file_path: str, source_type: Optional[str] = None) -> str:
        """注册数据文件，返回 source_id。"""
        import os
        sid = os.path.splitext(os.path.basename(file_path))[0]
        adapter = self._im.register(file_path, source_type=source_type, source_id=sid)
        # 若已有原点，立即传播到适配器（确保加载时使用正确坐标）
        if self._origin_lat is not None and hasattr(adapter, '_origin_lat'):
            adapter._origin_lat = self._origin_lat
            adapter._origin_lon = self._origin_lon
        self._im.load(sid)
        return sid

    def list_sources(self) -> List[Dict[str, str]]:
        return self._im.list_sources()

    def get_records(self, source_id: str) -> List[TargetRecord]:
        return self._im.load(source_id)

    # ── 预处理：聚类（雷达点迹凝聚） ─────────────────────────

    def preprocess_radar(
        self, radar_source_id: str
    ) -> Dict[int, List[TargetRecord]]:
        """对雷达点迹进行 DBSCAN 聚类，返回簇。"""
        records = self.get_records(radar_source_id)
        return self._cluster.cluster(records)

    def cluster_source(
        self, source_id: str, min_points: int = 3
    ) -> Dict[str, List[TargetRecord]]:
        """对数据源执行轨迹凝聚，返回 {track_id: [records]}。
        
        适用于传感器量测数据（无track_id的分立测量点）。
        """
        records = self.get_records(source_id)
        # 使用可调参数
        self._cluster.min_samples = min_points
        return self._cluster.cluster_to_tracks(records)

    def cluster_and_associate(
        self, radar_source_id: str, ais_source_id: str,
        min_cluster_points: int = 3,
    ) -> 'AssociationResult':
        """先对雷达数据做轨迹凝聚，再执行关联。"""
        from ..engines.association_engine import AssociationEngine

        # 1. 轨迹凝聚
        tracks = self.cluster_source(radar_source_id, min_cluster_points)
        radar_recs = []
        for tid, members in tracks.items():
            radar_recs.extend(members)

        if not radar_recs:
            from ..core.data_models import AssociationResult, AssociationPair
            return AssociationResult(pairs=[], unmatched={"radar": [], "ais": []},
                                     unmatched_radar=[], unmatched_ais=[], total_quality=0.0)

        # 2. 关联
        ais_recs = self.get_records(ais_source_id)
        ae = AssociationEngine(origin_lat=self._origin_lat, origin_lon=self._origin_lon)
        return ae.associate(radar_recs, ais_recs)

    # ── 时间对齐阶段 ─────────────────────────────────────────

    def align_sources(
        self, source_a_id: str, source_b_id: str
    ) -> AlignmentResult:
        """计算 source_b 相对于 source_a 的时间偏移。"""
        recs_a = self.get_records(source_a_id)
        recs_b = self.get_records(source_b_id)
        result = self._aligner.align(recs_a, recs_b)
        # 若需要偏移，自动应用
        if not result.needs_manual and abs(result.offset) > 0.1:
            recs_b_aligned = self._aligner.apply_offset(recs_b, result.offset)
            # 更新缓存
            self._im._records[source_b_id] = recs_b_aligned
        return result

    # ── 关联阶段 ─────────────────────────────────────────────

    def associate(
        self, radar_source_id: str, ais_source_id: str
    ) -> AssociationResult:
        """执行雷达-AIS 关联（自动过滤低置信度结果）。"""
        radar_recs = self.get_records(radar_source_id)
        ais_recs = self.get_records(ais_source_id)
        result = self._assoc.associate(radar_recs, ais_recs)
        # 按 min_confidence 过滤低置信度关联对
        min_conf = getattr(self.config, 'min_confidence', 0.6)
        if min_conf > 0 and result.pairs:
            result.pairs = [p for p in result.pairs if p.confidence >= min_conf]
        # 持久化
        if self._pm and self.project_id:
            self._pm.save_association_result(self.project_id, result, self.config)
        return result

    def associate_multi(
        self, source_ids: List[str],
        pairs: Optional[List[Tuple[str, str]]] = None,
    ) -> Dict[tuple, AssociationResult]:
        """多源关联：对多个数据源两两执行关联。

        Args:
            source_ids: 要关联的source_id列表
            pairs: 指定关联对，如 [("radar_id","ais_id")]
                   默认自动对所有两两组合执行关联

        Returns:
            {(src1, src2): AssociationResult}
        """
        source_records = {sid: self.get_records(sid) for sid in source_ids}
        results = self._assoc.associate_multi(source_records, pairs)
        # 按 min_confidence 过滤
        min_conf = getattr(self.config, 'min_confidence', 0.6)
        if min_conf > 0:
            for pair in results:
                r = results[pair]
                if r.pairs:
                    r.pairs = [p for p in r.pairs if p.confidence >= min_conf]
        if self._pm and self.project_id:
            for pair, result in results.items():
                self._pm.save_association_result(
                    f"{self.project_id}_{pair[0]}_{pair[1]}", result, self.config)
        return results

    def associate_filtered(
        self, radar_source_id: str, ais_source_id: str,
        radar_records_override: Optional[List[TargetRecord]] = None
    ) -> AssociationResult:
        """自动过滤雷达目标类型后执行关联。
        
        若雷达数据包含 target_type 元信息，自动只保留 RT 类型（雷达跟踪目标）。
        若关联引擎无 origin 但数据可推算，自动推算。
        """
        # 自动推算原点（若无预设）
        if self._origin_lat is None:
            self.auto_detect_origin(radar_source_id, ais_source_id)
        else:
            # 有预设原点时，确保雷达数据用该原点重新加载
            adapter = self._im._adapters.get(radar_source_id)
            if adapter is not None and hasattr(adapter, '_origin_lat'):
                cur_lat = getattr(adapter, '_origin_lat', None)
                if cur_lat is None or abs(cur_lat) < 0.01:
                    adapter._origin_lat = self._origin_lat
                    adapter._origin_lon = self._origin_lon
                    self._im.clear_cache()
                    self._im.load(radar_source_id)

        if radar_records_override is not None:
            radar_recs = radar_records_override
        else:
            radar_recs = self.get_records(radar_source_id)
            # 检测是否有 target_type 信息，有则过滤（只保留AT+RT，排除CDT杂波）
            has_types = any("target_type" in r.metadata for r in radar_recs[:5])
            if has_types:
                radar_filtered = self.filter_by_target_type(radar_source_id, ["AT", "RT"])
                if radar_filtered:
                    radar_recs = radar_filtered

        ais_recs = self.get_records(ais_source_id)
        result = self._assoc.associate(radar_recs, ais_recs)
        if self._pm and self.project_id:
            self._pm.save_association_result(self.project_id, result, self.config)
        return result

    # ── 轨迹管理 ─────────────────────────────────────────────

    def build_tracks(
        self, source_id: Optional[str] = None
    ) -> TrackManager:
        """从数据构建轨迹管理器。"""
        tm = TrackManager()
        if source_id:
            tm.add_batch(self.get_records(source_id))
        else:
            # 从所有已注册数据源加载 TargetRecord 列表（而非裸 dict）
            all_records = self._im.load_all()
            for records in all_records.values():
                tm.add_batch(records)
        return tm

    # ── 事件检测 ─────────────────────────────────────────────

    def detect_events(
        self,
        tracks: Dict[str, List[TargetRecord]],
        rules: Optional[List[str]] = None,
        **kwargs,
    ) -> List[EventRecord]:
        """运行事件检测。"""
        events = self._detector.detect_all(tracks, rules=rules, **kwargs)
        if self._pm and self.project_id:
            for ev in events:
                self._pm.add_event(self.project_id, ev)
        return events

    # ── 完整流水线执行 ───────────────────────────────────────

    def run(
        self,
        radar_source_id: Optional[str] = None,
        ais_source_id: Optional[str] = None,
        source_ids: Optional[List[str]] = None,
        detect_rules: Optional[List[str]] = None,
        progress_callback=None,
    ) -> Dict[str, Any]:
        """一键运行完整流程（N 源模式为推荐用法）。

        使用方式：
            # 推荐：N 源模式（支持任意数量的数据源两两关联）
            pipe.run(source_ids=["radar1", "ais1", "ais2", "ais3", "gps1"])

            # 向后兼容：传统双源模式
            pipe.run("radar_sid", "ais_sid")

        Args:
            radar_source_id: 雷达源 ID（双源模式）
            ais_source_id:   AIS 源 ID（双源模式）
            source_ids:      多源 ID 列表（N 源模式）
            detect_rules:    事件检测规则列表
            progress_callback: 可选回调函数 fn(stage_name: str, pct: float, msg: str)

        Returns:
            steps dict，含 "association"（N 源时含 "associations"）
        """
        def _emit(stage: str, pct: float, msg: str) -> None:
            if progress_callback is not None:
                try:
                    progress_callback(stage, pct, msg)
                except Exception:
                    pass

        steps: Dict[str, Any] = {}

        # ── 确定参与流程的源 ──
        if source_ids is not None:
            # N 源模式
            all_ids = list(source_ids)
            radar_ids = [s for s in all_ids if self.get_source_type(s) == "radar"]
            non_radar_ids = [s for s in all_ids if self.get_source_type(s) != "radar"]
            primary_radar = radar_ids[0] if radar_ids else all_ids[0]
            primary_ais = non_radar_ids[0] if non_radar_ids else (radar_ids[1] if len(radar_ids) > 1 else all_ids[0])
        else:
            # 双源模式（向后兼容）
            all_ids = [radar_source_id, ais_source_id] if radar_source_id and ais_source_id else []
            primary_radar = radar_source_id
            primary_ais = ais_source_id

        if not all_ids or len(all_ids) < 2:
            log.warning("run() 需要至少 2 个数据源")
            return steps

        # ── 0. 自动推算原点 ──
        _emit("origin", 10, "正在推算雷达站原点...")
        if self._origin_lat is None:
            origin = self.auto_detect_origin(primary_radar, primary_ais)
            steps["origin"] = origin
            if origin and origin[0] is not None:
                log.info("自动推算雷达站原点: lat=%.4f, lon=%.4f", origin[0], origin[1])
            else:
                log.warning("无法自动推算雷达站原点，关联可能不准确")
        else:
            _emit("origin", 10, f"使用预设原点: {self._origin_lat:.4f}, {self._origin_lon:.4f}")

        # ── 1. 时间对齐 ──
        _emit("alignment", 25, "正在对齐时间轴...")
        if source_ids is not None:
            # N 源模式：对齐所有源到primary_radar
            aligned_count = 0
            # 首先对齐primary
            align_result = self.align_sources(primary_radar, primary_ais)
            steps["alignment"] = align_result
            aligned_count += 1
            # 对齐其余非primary源（包括其他雷达源和非雷达源）
            other_sources = [s for s in all_ids if s not in (primary_radar, primary_ais)]
            for other_id in other_sources:
                try:
                    other_align = self.align_sources(primary_radar, other_id)
                    aligned_count += 1
                    log.info("N源时间对齐: %s → %s, 偏移=%.2fs", primary_radar, other_id, other_align.offset)
                except Exception as e:
                    log.warning("N源时间对齐失败 (%s): %s", other_id, e)
            _emit("alignment", 30, f"时间对齐完成: {aligned_count}个源已对齐")
        else:
            # 双源模式（向后兼容）
            align_result = self.align_sources(primary_radar, primary_ais)
            steps["alignment"] = align_result
            _emit("alignment", 30, f"时间对齐完成: 偏移={align_result.offset:+.2f}s")

        # ── 2. 雷达聚类 ──
        _emit("clustering", 40, "正在执行雷达点迹聚类...")
        clustered_records: Dict[str, List[TargetRecord]] = {}
        for rid in (radar_ids if source_ids is not None else [primary_radar]):
            try:
                clusters = self.preprocess_radar(rid)
                if rid not in steps:
                    steps["clusters"] = {}
                steps["clusters"][rid] = {k: len(v) for k, v in clusters.items()}
                clustered_list: List[TargetRecord] = []
                for cluster_id, records in clusters.items():
                    for r in records:
                        new_r = TargetRecord(
                            source_id=r.source_id,
                            track_id=cluster_id,
                            time=r.time,
                            x=r.x, y=r.y, lat=r.lat, lon=r.lon,
                            speed=r.speed, course=r.course,
                            metadata=r.metadata.copy(),
                        )
                        clustered_list.append(new_r)
                if clustered_list:
                    clustered_records[rid] = clustered_list
                _emit("clustering", 50, f"聚类完成 ({rid}): {len(clusters)}个簇")
            except Exception as e:
                log.warning("聚类失败 (%s): %s", rid, e)

        # ── 3. 关联 ──
        _emit("association", 55, "正在执行多源关联...")
        if source_ids is not None:
            # N 源模式：多源两两关联
            multi_results = self.associate_multi(all_ids)
            _emit("association", 70, f"关联完成: {len(multi_results)}组, 共{sum(len(r.pairs) for r in multi_results.values())}对")
            steps["associations"] = {
                f"{s1}↔{s2}": {
                    "n_pairs": len(r.pairs),
                    "quality": r.total_quality,
                    "result": r,
                }
                for (s1, s2), r in multi_results.items()
            }
            # 用 primary radar × primary ais 的结果做展示
            primary_key = (primary_radar, primary_ais)
            alt_key = (primary_ais, primary_radar)
            assoc_result = multi_results.get(primary_key) or multi_results.get(alt_key)
            if assoc_result is None and multi_results:
                assoc_result = next(iter(multi_results.values()))
            steps["association"] = {
                "n_pairs": len(assoc_result.pairs) if assoc_result else 0,
                "quality": assoc_result.total_quality if assoc_result else 0.0,
                "result": assoc_result,
            } if assoc_result else {"n_pairs": 0, "quality": 0.0, "result": None}
        else:
            # 双源模式：associate_filtered（含自动过滤+聚类覆盖）
            radar_override = clustered_records.get(primary_radar)
            assoc_result = self.associate_filtered(
                primary_radar, primary_ais,
                radar_records_override=radar_override,
            )
            _emit("association", 70, f"关联完成: {len(assoc_result.pairs)}对, 质量={assoc_result.total_quality:.3f}")
            steps["association"] = {
                "n_pairs": len(assoc_result.pairs),
                "unmatched_radar": len(assoc_result.unmatched_radar),
                "unmatched_ais": len(assoc_result.unmatched_ais),
                "quality": assoc_result.total_quality,
                "result": assoc_result,
            }

        # ── 4. 轨迹管理 ──
        _emit("tracks", 80, "正在构建轨迹...")
        track_source = primary_ais or (all_ids[1] if len(all_ids) > 1 else all_ids[0])
        tm = self.build_tracks(track_source)
        tracks_dict = {tid: tm.get_track(tid) for tid in tm.list_track_ids()}
        steps["tracks"] = tm.summary()
        _emit("tracks", 85, f"轨迹构建完成: {len(tm.list_track_ids())}条")

        # ── 5. 事件检测 ──
        _emit("events", 90, "正在检测事件...")
        events = self.detect_events(
            tracks_dict,
            rules=detect_rules or ["stationary", "manoeuvre", "collision"],
        )
        steps["events"] = {
            "n_events": len(events),
            "by_type": self._group_events_by_type(events),
        }
        _emit("events", 100, f"事件检测完成: {len(events)}个事件")

        return steps

    @staticmethod
    def _group_events_by_type(events: List[EventRecord]) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for e in events:
            counts[e.name] = counts.get(e.name, 0) + 1
        return counts

    @staticmethod
    def _guess_source_type(source_id: str) -> str:
        """根据 source_id 猜测源类型（降级方案）。
        
        注：优先使用 ImportManager.get_source_type() 获取缓存的类型。
        """
        sid_lower = source_id.lower()
        if "radar" in sid_lower or "cutdata" in sid_lower or "cut_data" in sid_lower or "polar" in sid_lower:
            return "radar"
        if "ais" in sid_lower:
            return "ais"
        if "gps" in sid_lower or "nmea" in sid_lower or "gpx" in sid_lower:
            return "gps"
        return "other"

    def get_source_type(self, source_id: str) -> str:
        """获取源类型（优先使用 ImportManager 缓存的推断结果）。"""
        return self._im.get_source_type(source_id)
