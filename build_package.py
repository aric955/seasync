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
SeaSync V2.2 — 一键打包脚本
生成独立可执行文件，可在任意 Windows 电脑上运行（无需安装 Python）

使用方法:
    python build_package.py

输出:
    dist/SeaSync_V2.2.exe — 单文件可执行程序
"""
import subprocess
import sys
import os
import shutil
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.resolve()
DIST_DIR = PROJECT_ROOT / "dist"
BUILD_DIR = PROJECT_ROOT / "build"


def clean_previous_builds():
    """清理之前的构建产物。"""
    print("[1/5] 清理之前的构建产物...")
    for d in [BUILD_DIR, DIST_DIR]:
        if d.exists():
            shutil.rmtree(d)
            print(f"  已删除: {d}")
    print("  ✓ 清理完成")


def run_pyinstaller():
    """运行 PyInstaller 打包。"""
    print("\n[2/5] 运行 PyInstaller 打包...")
    spec_file = PROJECT_ROOT / "build_onefile.spec"

    cmd = [
        sys.executable, "-m", "PyInstaller",
        str(spec_file),
        "--clean",
        "--noconfirm",
    ]

    print(f"  命令: {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=PROJECT_ROOT, capture_output=False)

    if result.returncode != 0:
        print("\n✗ PyInstaller 打包失败!")
        sys.exit(1)

    print("  ✓ 打包完成")


def verify_output():
    """验证输出文件。"""
    print("\n[3/5] 验证输出文件...")
    exe_path = DIST_DIR / "SeaSync_V2.2.exe"

    if not exe_path.exists():
        print(f"✗ 未找到输出文件: {exe_path}")
        sys.exit(1)

    size_mb = exe_path.stat().st_size / (1024 * 1024)
    print(f"  ✓ 输出文件: {exe_path}")
    print(f"  ✓ 文件大小: {size_mb:.1f} MB")


def create_distribution_package():
    """创建分发包（包含使用说明）。"""
    print("\n[4/5] 创建分发包...")

    package_dir = PROJECT_ROOT / "SeaSync_V2.2_分发包"
    if package_dir.exists():
        shutil.rmtree(package_dir)
    package_dir.mkdir()

    # 复制可执行文件
    exe_src = DIST_DIR / "SeaSync_V2.2.exe"
    exe_dst = package_dir / "SeaSync_V2.2.exe"
    shutil.copy2(exe_src, exe_dst)

    # 复制使用说明
    manual_src = PROJECT_ROOT / "用户使用说明书.md"
    if manual_src.exists():
        shutil.copy2(manual_src, package_dir / "使用说明.md")

    # 创建示例数据目录
    (package_dir / "示例数据").mkdir()

    # 创建启动说明
    readme = package_dir / "请先读我.txt"
    readme.write_text(
        "SeaSync V2.2 — 多源目标关联分析系统\n"
        "====================================\n\n"
        "【运行方式】\n"
        "  双击 SeaSync_V2.2.exe 即可启动\n\n"
        "【系统要求】\n"
        "  - Windows 10/11 64位\n"
        "  - 无需安装 Python 或其他依赖\n\n"
        "【详细说明】\n"
        "  请查看 使用说明.md\n\n"
        "【技术支持】\n"
        "  如有问题请联系开发团队\n",
        encoding="utf-8"
    )

    print(f"  ✓ 分发包已创建: {package_dir}")


def print_summary():
    """打印打包摘要。"""
    print("\n" + "=" * 60)
    print("SeaSync V2.2 打包完成!")
    print("=" * 60)
    print(f"\n输出文件:")
    print(f"  {DIST_DIR / 'SeaSync_V2.2.exe'}")
    print(f"\n分发包:")
    print(f"  {PROJECT_ROOT / 'SeaSync_V2.2_分发包'}")
    print(f"\n使用方式:")
    print(f"  将 'SeaSync_V2.2_分发包' 文件夹复制到任意电脑")
    print(f"  双击 SeaSync_V2.2.exe 即可运行")
    print("=" * 60)


def main():
    print("=" * 60)
    print("SeaSync V2.2 — 打包工具")
    print("=" * 60)

    # 检查 PyInstaller
    try:
        import PyInstaller
    except ImportError:
        print("\n✗ 未安装 PyInstaller，正在安装...")
        subprocess.run([sys.executable, "-m", "pip", "install", "pyinstaller"], check=True)
        print("  ✓ PyInstaller 安装完成")

    clean_previous_builds()
    run_pyinstaller()
    verify_output()
    create_distribution_package()
    print_summary()


if __name__ == "__main__":
    main()
