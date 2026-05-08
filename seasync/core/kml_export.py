"""
SeaSync KML 导出模块
====================
生成 Google Earth 兼容的 KML 轨迹文件。
无额外依赖，纯 Python 实现。
"""

# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 荣火
from __future__ import annotations
from typing import List, Optional, Dict
import xml.etree.ElementTree as ET
from datetime import datetime, timezone


KML_NS = "http://www.opengis.net/kml/2.2"


def _el(parent: ET.Element, tag: str, text: str = "", **attrs) -> ET.Element:
    """创建 KML 子元素。"""
    elem = ET.SubElement(parent, f"{{{KML_NS}}}{tag}", **attrs)
    if text:
        elem.text = text
    return elem


def export_kml(
    output_path: str,
    trajectories: Dict[str, list],   # {source_label: [TargetRecord, ...]}
    origin_lat: Optional[float] = None,
    origin_lon: Optional[float] = None,
    title: str = "SeaSync 实海试验数据",
) -> str:
    """将多条轨迹导出为 KML 文件。

    Args:
        output_path: 输出文件路径 (.kml)
        trajectories: {label: [TargetRecord, ...]}
        origin_lat/lon: 雷达站原点（可选，用于标注）
        title: KML 文档标题

    Returns:
        输出文件路径
    """
    ET.register_namespace("", KML_NS)
    root = ET.Element(f"{{{KML_NS}}}kml")
    doc = ET.SubElement(root, "Document" if 0 else f"{{{KML_NS}}}Document")
    _el(doc, "name", title)

    # 雷达站点标注（如果有）
    if origin_lat and origin_lon:
        pm = _el(doc, "Placemark")
        _el(pm, "name", "雷达站")
        _el(pm, "description", f"雷达原点 ({origin_lat:.4f}, {origin_lon:.4f})")
        pt = _el(pm, "Point")
        _el(pt, "coordinates", f"{origin_lon},{origin_lat},0")

    # 每条轨迹一个 Folder
    COLORS = [
        "ff0000cc", "ff00cc00", "ffffcc00", "ffcc0000",
        "ff00cccc", "ffcc00cc", "ffcccc00", "ff0088ff",
        "ff88ff00", "ffff0088",
    ]

    for idx, (label, records) in enumerate(trajectories.items()):
        if not records:
            continue
        folder = _el(doc, "Folder")
        _el(folder, "name", label)

        # 按 track_id 分组
        by_track: Dict[str, list] = {}
        for r in records:
            tid = getattr(r, 'track_id', 'track')
            by_track.setdefault(tid, []).append(r)

        for ti, (tid, recs) in enumerate(by_track.items()):
            valid = [r for r in recs if r.lat is not None and r.lon is not None]
            if len(valid) < 2:
                continue

            sorted_recs = sorted(valid, key=lambda r: r.time)
            pm = _el(folder, "Placemark")
            _el(pm, "name", f"{label}-{tid}")
            desc_parts = [f"source: {label}", f"track: {tid}",
                          f"points: {len(sorted_recs)}"]
            if sorted_recs[0].speed is not None:
                desc_parts.append(f"speed: {sorted_recs[-1].speed:.1f}kn")
            _el(pm, "description", "\n".join(desc_parts))

            # 轨迹颜色
            ci = (idx * len(by_track) + ti) % len(COLORS)
            style = _el(pm, "Style")
            line_style = _el(style, "LineStyle")
            _el(line_style, "color", COLORS[ci])
            _el(line_style, "width", "3")

            # 时间戳
            ts_start = datetime.fromtimestamp(sorted_recs[0].time, tz=timezone.utc)
            ts_end = datetime.fromtimestamp(sorted_recs[-1].time, tz=timezone.utc)
            tsp = _el(pm, "TimeSpan")
            _el(tsp, "begin", ts_start.isoformat())
            _el(tsp, "end", ts_end.isoformat())

            # 坐标串
            coords = "\n".join(f"{r.lon:.6f},{r.lat:.6f},0" for r in sorted_recs)
            ls = _el(pm, "LineString")
            _el(ls, "coordinates", f"\n{coords}\n")

            # 标记点（起点+终点）
            for name, rec, sym in [("起点", sorted_recs[0], "start"),
                                    ("终点", sorted_recs[-1], "end")]:
                pm2 = _el(folder, "Placemark")
                _el(pm2, "name", f"{label}-{tid}-{name}")
                pt = _el(pm2, "Point")
                _el(pt, "coordinates", f"{rec.lon:.6f},{rec.lat:.6f},0")

    tree = ET.ElementTree(root)
    tree.write(output_path, encoding="utf-8", xml_declaration=True)
    return output_path
