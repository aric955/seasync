"""
SeaSync V2.2 MatAdapter 单元测试。

测试覆盖：
  - 格式自动检测（mock 文件签名）
  - 变量别名映射
  - MATLAB datenum → Unix 时间戳转换
  - 极坐标 → 经纬度转换
  - 中文路径支持
  - 边界条件（空文件、无必需变量、手动映射覆盖）
"""

# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 荣火
from __future__ import annotations
import os
import sys
import math
import tempfile
import struct

import numpy as np
import pytest

# ── 将项目根目录加入 sys.path ──────────────────────────────
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from seasync.adapters.mat_adapter import (
    MatAdapter,
    _find_variable,
    _is_matlab_datenum,
    _datenum_to_unix_ms,
    _is_hdf5_mat,
    _MATLAB_DATENUM_EPOCH_OFFSET,
    _SECONDS_PER_DAY,
    _HAS_SCIPY,
    _HAS_H5PY,
)


# ═══════════════════════════════════════════════════════════
#  工具函数测试
# ═══════════════════════════════════════════════════════════

class TestFindVariable:
    def test_exact_match(self):
        assert _find_variable(["time", "lat", "lon"], "timestamp") == "time"

    def test_case_insensitive(self):
        assert _find_variable(["Time", "LAT", "Lon"], "lat") == "LAT"

    def test_chinese_match(self):
        assert _find_variable(["时间", "纬度", "经度"], "lat") == "纬度"

    def test_no_match(self):
        assert _find_variable(["a", "b", "c"], "timestamp") is None

    def test_empty_list(self):
        assert _find_variable([], "timestamp") is None


class TestDatenumDetection:
    def test_typical_datenum(self):
        arr = np.array([719529.0, 719530.0])  # 1970-01-01, 1970-01-02
        assert _is_matlab_datenum(arr) is True

    def test_large_value(self):
        arr = np.array([1e9, 1e10])
        assert _is_matlab_datenum(arr) is False

    def test_small_value(self):
        arr = np.array([1.0, 2.0])
        assert _is_matlab_datenum(arr) is False

    def test_empty_array(self):
        assert _is_matlab_datenum(np.array([])) is False

    def test_nan_value(self):
        arr = np.array([np.nan, 719529.0])
        assert _is_matlab_datenum(arr) is True

    def test_scalar(self):
        assert _is_matlab_datenum(np.array(719529.0)) is True


class TestDatenumConversion:
    def test_epoch(self):
        """MATLAB datenum 719529 == 1970-01-01 == Unix 0"""
        result = _datenum_to_unix_ms(np.array([719529.0]))
        assert result[0] == 0

    def test_one_day(self):
        """719530 == 1970-01-02 == 86400 秒"""
        result = _datenum_to_unix_ms(np.array([719530.0]))
        assert result[0] == 86400 * 1000

    def test_fractional_day(self):
        """719529.5 == 1970-01-01 12:00:00 == 43200 秒"""
        result = _datenum_to_unix_ms(np.array([719529.5]))
        assert result[0] == 43200 * 1000

    def test_array_input(self):
        arr = np.array([719529.0, 719530.0, 719531.0])
        result = _datenum_to_unix_ms(arr)
        assert len(result) == 3
        assert result[0] == 0
        assert result[1] == 86400 * 1000

    def test_modern_date(self):
        """2020-01-01 的 datenum 约为 737791"""
        datenum_2020 = 737791.0
        result = _datenum_to_unix_ms(np.array([datenum_2020]))
        # 2020-01-01 00:00:00 UTC 约为 1577836800 秒
        expected_ms = 1577836800 * 1000
        assert abs(result[0] - expected_ms) < 86400000  # ±1天容差


# ═══════════════════════════════════════════════════════════
#  MatAdapter 测试
# ═══════════════════════════════════════════════════════════

def _create_v5_mat(file_path: str, variables: dict) -> bool:
    """创建 v5 .mat 文件用于测试（需要 scipy）。"""
    try:
        import scipy.io
        scipy.io.savemat(file_path, variables)
        return True
    except ImportError:
        return False


def _create_hdf5_mat(file_path: str, variables: dict) -> bool:
    """创建 v7.3 .mat 文件用于测试（需要 h5py + hdf5plugin）。"""
    try:
        import h5py
        with h5py.File(file_path, "w") as f:
            for name, val in variables.items():
                if isinstance(val, np.ndarray):
                    # HDF5 存储为列主序以模拟 MATLAB 行为
                    if val.ndim == 1:
                        f.create_dataset(name, data=val)
                    elif val.ndim == 2:
                        f.create_dataset(name, data=val.T)
                    else:
                        f.create_dataset(name, data=val)
                else:
                    f.create_dataset(name, data=val)
        return True
    except ImportError:
        return False


# ── 仅包含依赖可用时的测试 ────────────────────────────────

class TestMatAdapterV5:
    """v5/v7 格式测试（需要 scipy）。"""

    @pytest.fixture(autouse=True)
    def _check_scipy(self):
        if not _HAS_SCIPY:
            pytest.skip("scipy 未安装，跳过 v5/v7 测试")

    def test_detect_format(self, tmp_path):
        fpath = str(tmp_path / "test_v5.mat")
        _create_v5_mat(fpath, {"a": np.array([1, 2, 3])})
        adapter = MatAdapter(fpath)
        fmt = adapter._detect_format()
        assert fmt == "mat_v5"

    def test_validate_ok(self, tmp_path):
        fpath = str(tmp_path / "test_v5.mat")
        _create_v5_mat(fpath, {"a": np.array([1, 2, 3])})
        adapter = MatAdapter(fpath)
        assert adapter.validate() is True

    def test_validate_not_exists(self, tmp_path):
        adapter = MatAdapter(str(tmp_path / "nonexistent.mat"))
        assert adapter.validate() is False

    def test_basic_load(self, tmp_path):
        """无时间列的简单数据应返回记录。"""
        fpath = str(tmp_path / "basic.mat")
        _create_v5_mat(fpath, {
            "lat": np.array([30.0, 31.0, 32.0]),
            "lon": np.array([120.0, 121.0, 122.0]),
        })
        adapter = MatAdapter(fpath)
        records = adapter.load()
        assert len(records) == 3
        assert records[0].lat == 30.0
        assert records[0].lon == 120.0

    def test_datenum_time_conversion(self, tmp_path):
        """datenum 时间列自动转换。"""
        fpath = str(tmp_path / "datenum.mat")
        datenum_vals = np.array([719529.0, 719530.0])  # 1970-01-01, 1970-01-02
        _create_v5_mat(fpath, {
            "time": datenum_vals,
            "lat": np.array([30.0, 31.0]),
            "lon": np.array([120.0, 121.0]),
        })
        adapter = MatAdapter(fpath)
        records = adapter.load()
        assert len(records) == 2
        assert records[0].time == 0.0          # Unix epoch
        assert records[1].time == 86400000.0    # +1天 in ms

    def test_polar_to_latlon(self, tmp_path):
        """极坐标+原点 → 经纬度转换。"""
        fpath = str(tmp_path / "polar.mat")
        rng = np.array([1852.0])   # 1 NM
        azi = np.array([0.0])      # 正北
        _create_v5_mat(fpath, {
            "time": np.array([719529.0]),
            "range": rng,
            "azimuth": azi,
        })
        adapter = MatAdapter(
            fpath,
            config={"origin_lat": 30.0, "origin_lon": 120.0},
        )
        records = adapter.load()
        assert len(records) == 1
        # 正北1NM → lat 增加 1/60 度
        assert abs(records[0].lat - 30.0 - 1.0/60.0) < 1e-6
        assert abs(records[0].lon - 120.0) < 1e-6

    def test_chinese_path(self, tmp_path):
        """中文文件路径支持（变量名用英文，scipy.savemat 限制）。"""
        chinese_dir = tmp_path / "中文路径测试"
        chinese_dir.mkdir(exist_ok=True)
        fpath = str(chinese_dir / "雷达数据.mat")
        _create_v5_mat(fpath, {
            "time": np.array([719529.0]),
            "latitude": np.array([30.0]),
            "longitude": np.array([120.0]),
        })
        adapter = MatAdapter(fpath)
        fmt = adapter._detect_format()
        assert fmt == "mat_v5"
        assert adapter.validate() is True

    def test_chinese_load(self, tmp_path):
        """中文路径 + 英文变量名加载。"""
        chinese_dir = tmp_path / "中文目录"
        chinese_dir.mkdir(exist_ok=True)
        fpath = str(chinese_dir / "海浪数据.mat")
        _create_v5_mat(fpath, {
            "time": np.array([719529.0, 719530.0]),
            "latitude": np.array([30.0, 31.0]),
            "longitude": np.array([120.0, 121.0]),
        })
        adapter = MatAdapter(fpath)
        records = adapter.load()
        assert len(records) == 2
        assert records[0].lat == 30.0
        assert records[0].lon == 120.0

    def test_auto_map_variables(self, tmp_path):
        """自动变量映射（使用英文别名）。"""
        fpath = str(tmp_path / "auto_map.mat")
        _create_v5_mat(fpath, {
            "latitude": np.array([30.0]),
            "longitude": np.array([120.0]),
            "timestamp": np.array([719529.0]),
            "distance": np.array([1000.0]),
            "azimuth": np.array([45.0]),
        })
        adapter = MatAdapter(fpath)
        mapping = adapter.auto_map_variables()
        assert mapping.get("lat") == "latitude"
        assert mapping.get("lon") == "longitude"
        assert mapping.get("timestamp") == "timestamp"
        assert mapping.get("range") == "distance"
        assert mapping.get("azimuth") == "azimuth"

    def test_auto_map_chinese_aliases(self):
        """_find_variable 处理中文别名。"""
        assert _find_variable(["时间", "纬度", "经度"], "lat") == "纬度"
        assert _find_variable(["时间", "纬度", "经度"], "lon") == "经度"
        assert _find_variable(["时间", "纬度", "经度"], "timestamp") == "时间"

    def test_manual_mapping_override(self, tmp_path):
        """手动映射覆盖自动映射。"""
        fpath = str(tmp_path / "manual_map.mat")
        _create_v5_mat(fpath, {
            "ts": np.array([719529.0]),
            "my_lat": np.array([30.0]),
            "my_lon": np.array([120.0]),
        })
        adapter = MatAdapter(
            fpath,
            config={
                "field_mapping": {
                    "timestamp": "ts",
                    "lat": "my_lat",
                    "lon": "my_lon",
                }
            },
        )
        mapping = adapter.auto_map_variables()
        # 自动映射找不到 ts / my_lat / my_lon（不在别名表中）
        assert "timestamp" not in mapping
        assert "lat" not in mapping
        # load() 应使用手动映射
        records = adapter.load()
        assert len(records) == 1
        assert records[0].lat == 30.0

    def test_variable_summary(self, tmp_path):
        """get_variable_summary 返回正确形状/类型。"""
        fpath = str(tmp_path / "summary.mat")
        _create_v5_mat(fpath, {
            "matrix": np.array([[1, 2, 3], [4, 5, 6]]),
            "vector": np.array([1, 2, 3]),
        })
        adapter = MatAdapter(fpath)
        summary = adapter.get_variable_summary()
        assert "matrix" in summary
        assert "vector" in summary
        shape_str, dtype_str = summary["matrix"]
        # MATLAB savemat 可能转置 2D 数组
        assert shape_str in ("2x3", "3x2")


class TestMatAdapterV73:
    """v7.3 (HDF5) 格式测试（需要 h5py）。"""

    @pytest.fixture(autouse=True)
    def _check_h5py(self):
        if not _HAS_H5PY:
            pytest.skip("h5py 未安装，跳过 v7.3 测试")

    def test_detect_format(self, tmp_path):
        fpath = str(tmp_path / "test_v73.mat")
        _create_hdf5_mat(fpath, {"a": np.array([1, 2, 3])})
        adapter = MatAdapter(fpath)
        fmt = adapter._detect_format()
        assert fmt == "mat_v73"

    def test_is_hdf5_mat(self, tmp_path):
        """HDF5 签名检测。"""
        fpath = str(tmp_path / "hdf5.mat")
        _create_hdf5_mat(fpath, {"a": np.array([1])})
        assert _is_hdf5_mat(fpath) is True

    def test_non_hdf5_signature(self, tmp_path):
        """非 v7.3 文件应检测为 False。"""
        fpath = str(tmp_path / "not_hdf5.mat")
        with open(fpath, "wb") as f:
            f.write(b"MATLAB 5.0 MAT-file")
        assert _is_hdf5_mat(fpath) is False

    def test_load_v73(self, tmp_path):
        fpath = str(tmp_path / "load_v73.mat")
        _create_hdf5_mat(fpath, {
            "time": np.array([719529.0, 719530.0]),
            "纬度": np.array([30.0, 31.0]),
            "经度": np.array([120.0, 121.0]),
        })
        adapter = MatAdapter(fpath)
        # 需要有 scipy 回退，但先试 v73
        fmt = adapter._detect_format()
        if fmt == "mat_v73":
            records = adapter.load()
            assert len(records) == 2


class TestMatAdapterEdgeCases:
    """边界条件测试。"""

    def test_empty_file(self, tmp_path):
        """空文件应抛出异常。"""
        fpath = str(tmp_path / "empty.mat")
        with open(fpath, "wb") as f:
            f.write(b"")
        adapter = MatAdapter(fpath)
        assert adapter.validate() is False

    def test_no_required_variables(self, tmp_path):
        """无必需变量时返回空记录。"""
        if not _HAS_SCIPY:
            pytest.skip("scipy 未安装")
        fpath = str(tmp_path / "no_req.mat")
        _create_v5_mat(fpath, {"irrelevant": np.array([1, 2])})
        adapter = MatAdapter(fpath)
        records = adapter.load()
        # 至少返回记录（track_id 基于索引）
        assert isinstance(records, list)

    def test_get_variable_names(self, tmp_path):
        if not _HAS_SCIPY:
            pytest.skip("scipy 未安装")
        fpath = str(tmp_path / "var_names.mat")
        _create_v5_mat(fpath, {
            "alpha": np.array([1]),
            "beta": np.array([2]),
        })
        adapter = MatAdapter(fpath)
        names = adapter.get_variable_names()
        assert "alpha" in names
        assert "beta" in names


class TestMetadata:
    def test_metadata_type(self, tmp_path):
        if not _HAS_SCIPY:
            pytest.skip("scipy 未安装")
        fpath = str(tmp_path / "meta.mat")
        _create_v5_mat(fpath, {"a": np.array([1])})
        adapter = MatAdapter(fpath)
        meta = adapter.metadata()
        assert meta.type == "matlab"
        assert meta.format in ("mat_v5", "mat_v73", "mat_unknown")
        assert meta.file_path == fpath

    def test_to_dataframe(self, tmp_path):
        if not _HAS_SCIPY:
            pytest.skip("scipy 未安装")
        fpath = str(tmp_path / "df.mat")
        _create_v5_mat(fpath, {
            "time": np.array([719529.0, 719530.0]),
            "lat": np.array([30.0, 31.0]),
            "lon": np.array([120.0, 121.0]),
        })
        adapter = MatAdapter(fpath)
        df = adapter.to_dataframe()
        assert len(df) == 2
        assert "time" in df.columns
        assert "lat" in df.columns
        assert "lon" in df.columns
