"""
SeaSync V2.2 - 多源目标关联分析系统
Copyright (C) 2026 荣火

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU Affero General Public License as published
by the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU Affero General Public License for more details.

You should have received a copy of the GNU Affero General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>.
"""

#!/usr/bin/env python
"""
SeaSync V2.2 — 快速演示脚本
运行方式：python demo.py

自动生成模拟海试CSV数据，演示完整处理流程（自动原点推算、关联、事件检测、可视化）。
"""
import sys, os, tempfile, math, random
sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _gen_demo_data(tmpdir: str):
    """生成模拟海试CSV文件，返回(雷达路径, AIS路径)"""
    import pandas as pd
    import numpy as np

    np.random.seed(42)
    RADAR_LAT, RADAR_LON = 37.5330, 121.4232

    # 模拟3艘船
    ships = [
        {"mmsi": 413203610, "lat": 37.5675, "lon": 121.4260, "sog": 0.5, "cog": 90},
        {"mmsi": 413204111, "lat": 37.5470, "lon": 121.4350, "sog": 1.2, "cog": 45},
        {"mmsi": 413205222, "lat": 37.5770, "lon": 121.4150, "sog": 0.3, "cog": 180},
    ]

    # 雷达数据（极坐标格式）
    radar_rows = []
    for frame in range(1, 25):
        t = f"2025-03-05 10:{35 + frame // 2:02d}:{(frame * 5) % 60:02d}"
        for ship in ships:
            dlat = ship["lat"] - RADAR_LAT
            dlon = ship["lon"] - RADAR_LON
            y = dlat * 1852 * 60
            x = dlon * 1852 * 60 * math.cos(math.radians(RADAR_LAT))
            rng = math.sqrt(x ** 2 + y ** 2) + np.random.uniform(-2, 2)
            az = (math.degrees(math.atan2(x, y)) + 360) % 360 + np.random.uniform(-0.05, 0.05)
            # 船随时间缓慢移动
            ship["lat"] += ship["sog"] * 0.514 * 5 / 1852 / 60 * math.cos(math.radians(ship["cog"]))
            ship["lon"] += ship["sog"] * 0.514 * 5 / 1852 / 60 * math.sin(math.radians(ship["cog"])) / math.cos(math.radians(RADAR_LAT))

            radar_rows.append({
                "帧序号": frame, "起始时间(帧)": t, "截止时间(帧)": t,
                "目标类型": "AT", "目标编号": ship["mmsi"],
                "目标方位(°)": round(az, 3), "目标距离(米)": round(rng, 1),
            })
    radar_df = pd.DataFrame(radar_rows)
    radar_path = os.path.join(tmpdir, "demo_radar.csv")
    radar_df.to_csv(radar_path, index=False, encoding="utf-8-sig")

    # AIS数据
    ais_rows = []
    for i, ship in enumerate(ships):
        for step in range(8):
            t = f"2025-03-05 10:{40 + i}:{step * 5:02d}"
            ais_rows.append({
                "MMSI": ship["mmsi"], "时间": t,
                "纬度": round(ship["lat"] + step * ship["sog"] * 0.00001, 6),
                "经度": round(ship["lon"] + step * ship["sog"] * 0.00001, 6),
                "SOG": ship["sog"], "COG": ship["cog"],
            })
    ais_df = pd.DataFrame(ais_rows)
    ais_path = os.path.join(tmpdir, "demo_ais.csv")
    ais_df.to_csv(ais_path, index=False, encoding="utf-8-sig")

    return radar_path, ais_path


def main():
    print("=" * 55)
    print("  SeaSync V2.2 — 快速演示")
    print("=" * 55)

    with tempfile.TemporaryDirectory() as tmpdir:
        # 生成模拟数据
        print("\n[1/4] 生成模拟海试数据...")
        radar_path, ais_path = _gen_demo_data(tmpdir)
        print(f"  雷达: {os.path.basename(radar_path)} ({72}条)")
        print(f"  AIS:  {os.path.basename(ais_path)} ({24}条)")

        # 导入
        print("\n[2/4] 导入数据...")
        from seasync.engines import SeaSyncPipeline
        pipe = SeaSyncPipeline()
        sid_ais = pipe.add_source(ais_path, source_type="ais")
        sid_radar = pipe.add_source(radar_path, source_type="radar")
        print(f"  雷达适配器: {pipe._im.get_adapter(sid_radar).__class__.__name__}")
        print(f"  AIS适配器:  {pipe._im.get_adapter(sid_ais).__class__.__name__}")

        # 全流程
        print("\n[3/4] 运行全流程...")
        steps = pipe.run(sid_radar, sid_ais)
        origin = steps.get("origin")
        assoc = steps["association"]
        print(f"  雷达原点: lat={origin[0]:.4f}, lon={origin[1]:.4f}")
        print(f"  关联匹配: {assoc['n_pairs']}对 (质量={assoc['quality']:.3f})")
        print(f"  未匹配雷达: {assoc['unmatched_radar']}, 未匹配AIS: {assoc['unmatched_ais']}")

        # 可视化
        print("\n[4/4] 生成可视化...")
        from seasync.visualization import render_association, render_tracks
        radar_recs = pipe.filter_by_target_type(sid_radar, ["AT"])
        ais_recs = pipe.get_records(sid_ais)
        img_path = os.path.join(tmpdir, "result.png")
        result = pipe.associate(sid_radar, sid_ais)
        render_association(radar_recs, ais_recs, result, output_path=img_path)
        print(f"  关联图: {img_path}")

        print(f"\n{'=' * 55}")
        print(f"  ✅ 演示完成！")
        print(f"  命令行: python -m seasync run <radar.csv> <ais.csv>")
        print(f"  GUI:    python -m seasync gui (需PyQt5)")
        print(f"{'=' * 55}")


if __name__ == "__main__":
    main()
