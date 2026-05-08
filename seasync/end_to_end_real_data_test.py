"""
SeaSync V2.2 真实数据端到端测试
================================
使用 雷达对海探测试验与目标特性数据 进行全流程验证。

数据来源：E:\数据\雷达对海探测试验与目标特性数据-刘宁波\
"""

# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 荣火
from __future__ import annotations
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

DATA_BASE = r"E:\数据\雷达对海探测试验与目标特性数据-刘宁波"

# 自动发现所有含 CutDataTarget 的测试目录
TEST_DIRS: list[str] = []
for d in sorted(os.listdir(DATA_BASE)):
    full = os.path.join(DATA_BASE, d)
    if os.path.isdir(full) and os.path.exists(os.path.join(full, "CutDataTarget.csv")):
        TEST_DIRS.append(d)

# 已知原点基准（可从 run() 自动推算获取，此处缓存避免每次重新推算）
KNOWN_ORIGINS = {
    "20250305103638_2003_AT_413203610_1": (37.5331, 121.4199),
}


def get_ais_files(case_dir: str) -> list[str]:
    """返回目录中所有 AIS_Trajectory_*.csv 文件的完整路径。"""
    return sorted([
        os.path.join(case_dir, f)
        for f in os.listdir(case_dir)
        if f.startswith("AIS_Trajectory_") and f.endswith(".csv")
    ])


def test_single_case(case_dir: str) -> dict:
    """对单个目录运行完整测试，返回统计结果。"""
    from seasync.engines import SeaSyncPipeline

    radar_file = os.path.join(case_dir, "CutDataTarget.csv")
    ais_files = get_ais_files(case_dir)
    name = os.path.basename(case_dir)

    print(f"\n{'='*55}")
    print(f"  用例: {name}")
    print(f"  雷达: {os.path.getsize(radar_file)/1024:.0f}KB")
    print(f"  AIS: {len(ais_files)}个轨迹文件")
    print(f"{'='*55}")

    result = {
        "n_ais": len(ais_files),
        "n_radar_records": 0,
        "n_ais_records": 0,
        "n_pairs_preset": 0,
        "n_pairs_auto": 0,
        "quality_preset": 0.0,
        "quality_auto": 0.0,
        "origin_auto": None,
        "ais_results": [],
    }

    # ── 预设原点 ──
    origin = KNOWN_ORIGINS.get(name, (37.53, 121.42))
    pipe = SeaSyncPipeline(origin_lat=origin[0], origin_lon=origin[1])
    sid_r = pipe.add_source(radar_file, source_type="radar")
    rad_recs = pipe.get_records(sid_r)
    result["n_radar_records"] = len(rad_recs)

    for af in ais_files:
        sid = pipe.add_source(af, source_type="ais")
        recs = pipe.get_records(sid)
        result["n_ais_records"] += len(recs)

    # 完整流程
    all_sids = [s["source_id"] for s in pipe._im.list_sources()]
    radar_sid = [s for s in all_sids if s == "CutDataTarget"][0]
    ais_sids = [s for s in all_sids if s != "CutDataTarget"]

    steps = pipe.run(radar_sid, ais_sids[0] if ais_sids else "")
    assoc = steps.get("association", {})
    result["n_pairs_preset"] = assoc.get("n_pairs", 0)
    result["quality_preset"] = assoc.get("quality", 0)
    result["n_events"] = steps.get("events", {}).get("n_events", 0)
    result["n_tracks"] = steps.get("tracks", {}).get("n_tracks", 0)
    print(f"  [预设] 关联{result['n_pairs_preset']}对, 质量={result['quality_preset']:.3f}, "
          f"事件{result['n_events']}个, 轨迹{result['n_tracks']}条")

    # 两两关联全部AIS
    for asid in ais_sids:
        try:
            ar = pipe.associate(radar_sid, asid)
            if ar and ar.pairs:
                mmsi = ar.pairs[0].ais_mmsi
                result["ais_results"].append({
                    "ais_id": asid, "n_pairs": len(ar.pairs),
                    "quality": ar.total_quality, "mmsi": mmsi,
                })
        except Exception:
            pass

    # ── 自动推算原点 ──
    pipe2 = SeaSyncPipeline()
    sid_r2 = pipe2.add_source(radar_file, source_type="radar")
    sid_a2 = pipe2.add_source(ais_files[0], source_type="ais") if ais_files else None
    try:
        steps2 = pipe2.run(sid_r2, sid_a2)
        assoc2 = steps2.get("association", {})
        result["n_pairs_auto"] = assoc2.get("n_pairs", 0)
        result["quality_auto"] = assoc2.get("quality", 0)
        result["origin_auto"] = steps2.get("origin", None)
        o = result["origin_auto"]
        org_str = f"原点=({o[0]:.4f},{o[1]:.4f})" if o and o[0] is not None else "原点=未知"
        print(f"  [自动] 关联{result['n_pairs_auto']}对, 质量={result['quality_auto']:.3f}, {org_str}")
    except Exception as e:
        print(f"  [自动] 失败: {e}")

    # 打印各AIS关联详情
    if result["ais_results"]:
        print(f"  [逐源] 有匹配的AIS: {len(result['ais_results'])}/{len(ais_files)}")
        for r in result["ais_results"][:5]:
            print(f"    → {r['ais_id'][:16]}: {r['n_pairs']}对, 质量={r['quality']:.3f}, MMSI={r['mmsi']}")
        if len(result["ais_results"]) > 5:
            print(f"    ... 还有{len(result['ais_results'])-5}个")

    return result


def summarize(results: dict):
    """打印综合报告。"""
    print(f"\n{'='*55}")
    print(f"  SeaSync 真实数据端到端测试 — 综合报告")
    print(f"  测试时间: {__import__('datetime').datetime.now():%Y-%m-%d %H:%M}")
    print(f"  数据目录: {DATA_BASE}")
    print(f"  测试用例: {len(results)}个")
    print(f"{'='*55}")

    total_pairs = 0
    ok = 0
    for name, r in results.items():
        has_match = r["n_pairs_preset"] > 0 or r["n_pairs_auto"] > 0
        status = "✅" if has_match else "⚠️"
        total_pairs += max(r["n_pairs_preset"], r["n_pairs_auto"])
        if has_match:
            ok += 1
        print(f"  {status} {name[:30]:30s} "
              f"预设={r['n_pairs_preset']}对(q={r['quality_preset']:.2f}) "
              f"| 自动={r['n_pairs_auto']}对(q={r['quality_auto']:.2f}) "
              f"| 有匹配AIS={sum(1 for a in r['ais_results'] if a['n_pairs']>0)}/{r['n_ais']}")

    print(f"{'='*55}")
    print(f"  通过: {ok}/{len(results)}  |  总关联对: {total_pairs}")
    if ok == len(results):
        print(f"  ✅ 所有测试通过！SeaSync 真实数据处理正常。")
    else:
        print(f"  ⚠️ {len(results)-ok}个用例无匹配，请检查数据或参数。")
    print(f"{'='*55}")


if __name__ == "__main__":
    print("SeaSync V2.2 真实数据端到端测试")
    print(f"发现 {len(TEST_DIRS)} 个含 CutDataTarget 的目录\n")

    all_results = {}
    for d in TEST_DIRS:
        case_dir = os.path.join(DATA_BASE, d)
        try:
            all_results[d] = test_single_case(case_dir)
        except Exception as e:
            import traceback
            print(f"\n✗ {d[:30]} 异常: {e}")
            traceback.print_exc()

    summarize(all_results)
