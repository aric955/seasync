"""
统一列名常量
所有数据适配器输出的 DataFrame 应包含以下标准列。
"""

# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 荣火

REQUIRED_COLUMNS = {
    "time": "float64",
    "lat": "float64",
    "lon": "float64",
    "x": "float64",
    "y": "float64",
    "speed": "float64",
    "course": "float64",
    "mmsi": "object",
    "track_id": "object",
    "source_id": "object",
}
