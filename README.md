# SeaSync V2.2 — 多源目标关联分析系统

> 航海雷达与 AIS 等多传感器数据的时空匹配与融合分析工具  
> **单机离线 · 多格式兼容 · 全自动流程**

---

## 概述

SeaSync（Sea Synchronization）是一款专为海上试验数据**事后分析**设计的离线单机工具。它能够将来自不同传感器（雷达、AIS、GPS 等）的原始数据文件，自动完成时空对准和目标关联，并以可视化和标准报告呈现结果。

**核心理念**：拖入原始数据 → 自动分析 → 查看结果 → 导出报告。全程数据不出本地。

### 适用场景

- 海上实船试验数据的多传感器关联分析
- 雷达与 AIS 的目标身份匹配与验证
- 科研院校的多源融合算法教学与基线测试
- 事后复盘、报告编写

### 主要能力

| 能力 | 说明 |
|------|------|
| 多格式兼容 | 支持 10 种数据格式（CSV/DAT/MAT/XLSX/NMEA/GPX/TXT/CAT048 等） |
| 智能关联引擎 | 卡尔曼滤波 + 马氏距离 + 匈牙利算法，MMSI 优先匹配 |
| 时间对齐 | 互相关法（CCF）自动对齐不同传感器的时间偏差 |
| 轨迹聚类 | DBSCAN 凝聚原始点迹为完整航迹 |
| 事件检测 | 碰撞预警、停船检测、机动检测、区域违规 |
| 可视化 | PyQt5 GUI + Matplotlib，支持 2D 平面视图和 PPI 极坐标显示 |
| 报告导出 | 一键生成 Markdown/Word 分析报告；KML 轨迹导出 |

---

## 快速开始

### 安装

```bash
# 克隆仓库
git clone https://github.com/your-org/seasync.git
cd seasync

# 安装依赖
pip install -r requirements.txt

# 启动 GUI（可选依赖: PyQt5, matplotlib）
python launch_gui.py
```

### Python API 示例

```python
from seasync import SeaSyncPipeline

# 创建处理管线
pipeline = SeaSyncPipeline()

# 注册数据源
pipeline.add_source("radar.csv", source_type="radar")
pipeline.add_source("ais.csv", source_type="ais")

# 执行关联
result = pipeline.associate("radar.csv", "ais.csv")

# 查看结果
print(f"关联完成: {result.n_pairs} 对, 质量: {result.total_quality:.3f}")
for pair in result.pairs:
    print(f"  {pair.source1_id} ↔ {pair.source2_id} (置信度: {pair.confidence:.3f})")
```

### 命令行

```bash
python -m seasync --input radar.csv --input ais.csv --associate
```

---

## 系统要求

| 项目 | 最低配置 | 推荐配置 |
|------|---------|---------|
| 操作系统 | Windows 10 / Ubuntu 20.04 | Windows 10/11, Ubuntu 22.04 |
| Python | 3.10+ | 3.11+ |
| 内存 | 8 GB | 16 GB |
| 硬盘 | 1 GB 安装空间 | SSD，预留 100 GB 以上 |

---

## 架构总览

```
┌──────────────────────────────────────┐
│     GUI 层 (PyQt5 + Matplotlib)      │
├──────────────────────────────────────┤
│     Pipeline 层 (SeaSyncPipeline)    │
│ 导入 → 坐标转换 → 聚类 → 对齐 → 关联 │
├──────────────────────────────────────┤
│     引擎层 (Engines)                 │
│ Association · Clustering · TimeAlign │
│ EventDetect · ScanTrack · TrackMgr  │
├──────────────────────────────────────┤
│     适配层 (Adapters)                │
│ Radar · AIS · GPS · CSV · DAT · MAT │
│ XLSX · TXT · CAT048 · ImportManager │
├──────────────────────────────────────┤
│     核心层 (Core)                    │
│ 数据模型 · 地理工具 · 配置 · SQLite   │
└──────────────────────────────────────┘
```

---

## 版本说明

| 版本 | 说明 | 许可 |
|------|------|------|
| **标准版 V2.2** | 本仓库包含的版本。基础导入/关联/可视化/报告 | **AGPL v3** |
| 专业版 V2.3 | 手动修正闭环、图表报告、伪关联检测、事件增强 | 商业授权 |
| 企业版 V2.4 | SDF机制、服务器模式、案例库、自动调优、Notebook导出 | 商业授权 |

---

## 许可证

```
Copyright (C) 2026 荣火

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU Affero General Public License as published
by the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
GNU Affero General Public License for more details.

You should have received a copy of the GNU Affero General Public License
along with this program. If not, see <https://www.gnu.org/licenses/>.
```

完整授权条款见 [LICENSE](LICENSE) 文件。

---

## 联系方式

- 作者：荣火
- 邮箱：li_jingjun@163.com

---

## 致谢

本项目的算法验证使用了以下公开数据集：
- MTAD（多目标航迹关联数据集）
- 雷达对海探测试验数据集
- 金海豚挑战赛数据集
