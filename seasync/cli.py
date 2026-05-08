"""
SeaSync V2.2 — 命令行入口
用法：
    seasync demo       运行演示（模拟多目标数据）
    seasync run        运行完整处理（N 源模式，支持多 AIS）
    seasync gui        启动图形界面
    seasync version    显示版本

N 源示例：
    seasync run radar.csv ais_ship1.csv ais_ship2.csv ais_ship3.csv
"""

# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 荣火
import sys, os, argparse

# 确保能找到内部包
_pkg_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _pkg_dir not in sys.path:
    sys.path.insert(0, _pkg_dir)


def cmd_demo(args):
    """运行演示：生成模拟数据并执行完整流程。"""
    _run_demo()


def cmd_run(args):
    """处理指定数据文件（N 源模式，支持多 AIS）。"""
    from seasync import SeaSyncPipeline

    pipe = SeaSyncPipeline()
    source_ids = []

    # 第一个文件作为雷达
    if args.radar and os.path.exists(args.radar):
        sid = pipe.add_source(args.radar, source_type="radar")
        adapter = pipe._im.get_adapter(sid)
        recs = pipe.get_records(sid)
        types = set(r.metadata.get("target_type", "?") for r in recs[:10])
        print(f"  [雷达] {os.path.basename(args.radar)} → {adapter.__class__.__name__} ({len(recs)}条, {types})")
        source_ids.append(sid)

    # 后续文件作为AIS
    if args.ais:
        for ais_path in args.ais:
            if os.path.exists(ais_path):
                sid = pipe.add_source(ais_path, source_type="ais")
                adapter = pipe._im.get_adapter(sid)
                recs = pipe.get_records(sid)
                mmsi = recs[0].metadata.get('mmsi', '?') if recs else '?'
                print(f"  [AIS] {os.path.basename(ais_path)} → {adapter.__class__.__name__} ({len(recs)}条, MMSI={mmsi})")
                source_ids.append(sid)

    if len(source_ids) >= 2:
        n_ais = len(source_ids) - 1
        print(f"\n  [运行] N 源全流程处理 ({n_ais} 个 AIS 源)...")
        steps = pipe.run(source_ids=source_ids)

        origin = steps.get('origin', (None, None))
        if origin and origin[0]:
            print(f"  雷达原点: lat={origin[0]:.4f}, lon={origin[1]:.4f}")

        # N 源关联结果
        if "associations" in steps and steps["associations"]:
            total_pairs = 0
            print(f"\n  N 源关联 ({len(steps['associations'])} 组两两比较):")
            for pair_key, info in steps["associations"].items():
                if info["n_pairs"] > 0:
                    total_pairs += info["n_pairs"]
                    print(f"  ✅ {pair_key}: {info['n_pairs']} 对 (质量={info['quality']:.3f})")
            print(f"\n  关联总计: {total_pairs} 对")

        assoc = steps.get("association", {})
        events = steps.get("events", {})
        tracks = steps.get("tracks", {})
        print(f"  事件: {events.get('n_events', 0)}个")
        print(f"  轨迹: {tracks.get('n_tracks', 0)}条")

        # 为主雷达 + 每 AIS 生成可视化
        radar_sid = source_ids[0]
        ais_sids = source_ids[1:]
        for sid in ais_sids[:3]:  # 最多生成3张，避免过多
            try:
                from seasync.visualization import render_association
                radar_recs = pipe.get_records(radar_sid)
                ais_recs = pipe.get_records(sid)
                result = pipe.associate(radar_sid, sid)
                out = f"result_{os.path.basename(sid)}.png"
                render_association(radar_recs, ais_recs, result, output_path=out)
                print(f"  可视化: {out}")
            except Exception as e:
                print(f"  可视化({sid}): 跳过")
                break

        print(f"\n  ✅ 处理完成! (共 {len(source_ids)} 个数据源)")
    else:
        print("\n  请提供至少1个雷达文件 + 1个AIS文件")
        print("  用法: seasync run radar.csv ais1.csv [ais2.csv ...]")


def cmd_gui(args):
    """启动图形界面"""
    try:
        import sys, os
        sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
        from seasync.gui.main_window import launch_gui
        launch_gui()
    except Exception as e:
        print(f"GUI启动失败: {e}")
        print("请安装 PyQt5: pip install seasync[gui]")


def cmd_version(args):
    """显示版本"""
    from seasync import __version__
    print(f"SeaSync v{__version__}")


def _run_demo():
    """运行内置演示。"""
    _run_builtin_demo()


def _run_builtin_demo():
    """内置计算演示（不依赖外部文件）。"""
    import tempfile, math, numpy as np, pandas as pd

    print("=" * 55)
    print("  SeaSync V2.2 — 演示模式")
    print("=" * 55)

    np.random.seed(42)
    RADAR_LAT, RADAR_LON = 37.5330, 121.4232
    ships = [
        {"mmsi": 413203610, "lat": 37.5675, "lon": 121.4260, "sog": 0.5, "cog": 90},
        {"mmsi": 413204111, "lat": 37.5470, "lon": 121.4350, "sog": 1.2, "cog": 45},
        {"mmsi": 413205222, "lat": 37.5770, "lon": 121.4150, "sog": 0.3, "cog": 180},
    ]

    with tempfile.TemporaryDirectory() as tmp:
        print("\n[1/3] 生成模拟海试数据...")
        radar_rows = []
        for frame in range(1, 25):
            t = f"2025-03-05 10:{35 + frame // 2:02d}:{(frame * 5) % 60:02d}"
            for ship in ships:
                dlat, dlon = ship["lat"] - RADAR_LAT, ship["lon"] - RADAR_LON
                y, x = dlat * 1852 * 60, dlon * 1852 * 60 * math.cos(math.radians(RADAR_LAT))
                rng = math.sqrt(x ** 2 + y ** 2) + np.random.uniform(-2, 2)
                az = (math.degrees(math.atan2(x, y)) + 360) % 360 + np.random.uniform(-0.05, 0.05)
                ship["lat"] += ship["sog"] * 0.514 * 5 / 1852 / 60 * math.cos(math.radians(ship["cog"]))
                ship["lon"] += ship["sog"] * 0.514 * 5 / 1852 / 60 * math.sin(math.radians(ship["cog"])) / math.cos(math.radians(RADAR_LAT))
                radar_rows.append({"帧序号": frame, "起始时间(帧)": t, "目标类型": "AT",
                    "目标编号": ship["mmsi"], "目标方位(°)": round(az, 3), "目标距离(米)": round(rng, 1)})

        radar_path = os.path.join(tmp, "radar.csv")
        pd.DataFrame(radar_rows).to_csv(radar_path, index=False, encoding="utf-8-sig")

        ais_rows = []
        for i, ship in enumerate(ships):
            for step in range(8):
                t = f"2025-03-05 10:{40 + i}:{step * 5:02d}"
                ais_rows.append({"MMSI": ship["mmsi"], "时间": t,
                    "纬度": round(ship["lat"] + step * ship["sog"] * 0.00001, 6),
                    "经度": round(ship["lon"] + step * ship["sog"] * 0.00001, 6),
                    "SOG": ship["sog"], "COG": ship["cog"]})
        ais_path = os.path.join(tmp, "ais.csv")
        pd.DataFrame(ais_rows).to_csv(ais_path, index=False, encoding="utf-8-sig")

        print(f"  雷达: {len(radar_rows)}条  AIS: {len(ais_rows)}条")

        print("\n[2/3] 运行完整流程...")
        from seasync.engines import SeaSyncPipeline
        pipe = SeaSyncPipeline()
        sid_r = pipe.add_source(radar_path, source_type="radar")
        sid_a = pipe.add_source(ais_path, source_type="ais")
        steps = pipe.run(sid_r, sid_a)

        origin = steps.get('origin', (None, None))
        if origin and origin[0] is not None:
            print(f"  雷达原点: lat={origin[0]:.4f}, lon={origin[1]:.4f}")
        assoc = steps.get("association", {})
        print(f"  关联匹配: {assoc.get('n_pairs', 0)}对 (质量={assoc.get('quality', 0):.3f})")
        print(f"  未匹配雷达: {assoc.get('unmatched_radar', 0)}, AIS: {assoc.get('unmatched_ais', 0)}")

        print("\n[3/3] 生成可视化...")
        from seasync.visualization import render_association
        result = pipe.associate(sid_r, sid_a)
        img_path = os.path.join(tmp, "result.png")
        radar_recs = pipe.get_records(sid_r)
        ais_recs = pipe.get_records(sid_a)
        render_association(radar_recs, ais_recs, result, output_path=img_path)
        size = os.path.getsize(img_path)
        print(f"  关联图: {size / 1024:.0f}KB")

        print(f"\n  ✅ 演示完成!")
        print(f"  CLI: seasync run <radar.csv> <ais1.csv> [ais2.csv ais3.csv ...]")
        print(f"  GUI: seasync gui (需PyQt5)")


def main():
    parser = argparse.ArgumentParser(
        description="SeaSync V2.2 — 多源目标关联分析系统",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", help="子命令")

    # demo
    p_demo = sub.add_parser("demo", help="运行模拟数据演示")
    p_demo.set_defaults(func=cmd_demo)

    # run
    p_run = sub.add_parser("run", help="处理指定数据文件 (支持多AIS)")
    p_run.add_argument("radar", nargs="?", help="雷达数据文件路径")
    p_run.add_argument("ais", nargs="*", help="AIS数据文件路径(支持多个)")
    p_run.set_defaults(func=cmd_run)

    # gui
    p_gui = sub.add_parser("gui", help="启动图形界面")
    p_gui.set_defaults(func=cmd_gui)

    # version
    p_ver = sub.add_parser("version", help="显示版本号")
    p_ver.set_defaults(func=cmd_version)

    args = parser.parse_args()
    if args.command is None:
        parser.print_help()
        return

    args.func(args)


if __name__ == "__main__":
    main()
