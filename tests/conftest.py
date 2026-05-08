"""
pytest conftest — 自动添加项目根目录到 sys.path。
"""

# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 荣火
import os, sys
# 优先使用 v22 版本的 seasync（避免与 workspace-root 的旧包冲突）
_v22_path = os.path.join(os.path.dirname(__file__), "..")
if _v22_path not in sys.path:
    sys.path.insert(0, _v22_path)
