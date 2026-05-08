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
"""演示真实数据加载与处理流程 - 自动打开GUI并加载指定数据文件"""
import sys
import os
import traceback
sys.path.insert(0, os.path.dirname(__file__))

from PyQt5 import QtWidgets, QtCore, QtTest

def demo():
    # 创建应用实例
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication(sys.argv)
    
    # 导入主窗口
    from seasync.gui.main_window import SeaSyncMainWindow
    window = SeaSyncMainWindow()
    window.show()
    
    # 等待窗口显示
    QtTest.QTest.qWait(1000)
    print("=== SeaSync GUI 演示 ===")
    print("GUI窗口已显示")
    
    # 定义真实数据文件路径
    data_dir = r"E:\数据\雷达对海探测试验与目标特性数据-刘宁波\20250305103638_2003_AT_413203610_1"
    radar_file = os.path.join(data_dir, "CutDataTarget.csv")
    ais_file = os.path.join(data_dir, "AIS_Trajectory_413203610.csv")
    
    print(f"数据目录: {data_dir}")
    print(f"雷达文件: {radar_file}")
    print(f"AIS文件: {ais_file}")
    
    # 检查文件是否存在
    if not os.path.exists(radar_file):
        print(f"错误: 雷达文件不存在: {radar_file}")
        return
    if not os.path.exists(ais_file):
        print(f"错误: AIS文件不存在: {ais_file}")
        return
    
    # 自动检测文件类型并加载
    from seasync.adapters.import_manager import _auto_detect_type
    
    print("\n1. 加载雷达数据...")
    try:
        radar_type = _auto_detect_type(radar_file)
        print(f"  检测类型: {radar_type}")
        radar_id = window.pipeline.add_source(radar_file, source_type=radar_type)
        display = f"{os.path.basename(radar_file)} [{radar_id[:8]}·{radar_type}]"
        window._source_map[display] = (radar_id, radar_type)
        window._source_list.addItem(display)
        window._log(f"加载: {os.path.basename(radar_file)} → {radar_type}适配器")
        print(f"  加载成功, ID: {radar_id[:8]}")
    except Exception as e:
        print(f"  雷达加载失败: {e}")
        traceback.print_exc()
        return
    
    print("\n2. 加载AIS数据...")
    try:
        ais_type = _auto_detect_type(ais_file)
        print(f"  检测类型: {ais_type}")
        ais_id = window.pipeline.add_source(ais_file, source_type=ais_type)
        display = f"{os.path.basename(ais_file)} [{ais_id[:8]}·{ais_type}]"
        window._source_map[display] = (ais_id, ais_type)
        window._source_list.addItem(display)
        window._log(f"加载: {os.path.basename(ais_file)} → {ais_type}适配器")
        print(f"  加载成功, ID: {ais_id[:8]}")
    except Exception as e:
        print(f"  AIS加载失败: {e}")
        traceback.print_exc()
        return
    
    print("\n3. 运行完整处理流程...")
    try:
        # 设置处理参数（使用默认值）
        if hasattr(window, '_config'):
            window._config.gate_distance = 100.0  # 米
            window._config.max_coast_steps = 3
            window._config.association_threshold = 10.0
            print("  已设置默认处理参数")
        
        # 执行流程
        window._on_run_pipeline()
        print("  流程执行完成")
        
        # 检查关联结果
        if window.pipeline and hasattr(window.pipeline, 'association_engine'):
            assoc = window.pipeline.association_engine
            if hasattr(assoc, 'get_association_results'):
                results = assoc.get_association_results()
                print(f"  关联结果数量: {len(results) if results else 0}")
        
        # 更新可视化
        if hasattr(window, '_update_visualization'):
            window._update_visualization()
            print("  可视化已更新")
            
    except Exception as e:
        print(f"  流程执行失败: {e}")
        traceback.print_exc()
        return
    
    print("\n4. 生成报告...")
    try:
        if hasattr(window, '_on_generate_report'):
            window._on_generate_report()
            print("  报告生成完成")
    except Exception as e:
        print(f"  报告生成失败: {e}")
        # 非关键错误，继续
    
    print("\n=== 演示完成 ===")
    print("GUI窗口将保持打开，请查看可视化结果。")
    print("关闭窗口或等待30秒后自动退出。")
    
    # 30秒后自动退出
    QtCore.QTimer.singleShot(30000, app.quit)
    
    # 进入事件循环
    sys.exit(app.exec_())

if __name__ == "__main__":
    demo()