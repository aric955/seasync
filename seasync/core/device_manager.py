"""
SeaSync V2.2 设备管理模块
解决痛点：
  S24 - 设备清单难以一次完备，第一次总漏东西 → 设备库与清单模板，基于历史智能推荐
  S25 - 设备出过什么故障、换过什么零件，没有完整档案 → 设备电子档案，全追溯
  S26 - 设备到了报废年限，是凑合用还是申请报废 → 设备状态预警，超期服役风险提示
"""

# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 荣火
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any, Tuple
from datetime import datetime, date
from enum import Enum
import logging

_logger = logging.getLogger(__name__)


class DeviceStatus(Enum):
    """设备状态枚举"""
    ACTIVE = "active"                    # 在用
    SPARE = "spare"                      # 备用
    MAINTENANCE = "maintenance"          # 维修中
    RETIRED = "retired"                  # 已报废
    LOST = "lost"                        # 丢失
    OVERDUE = "overdue"                  # 超期服役


class DeviceType(Enum):
    """设备类型枚举"""
    RADAR = "radar"
    AIS = "ais"
    GPS = "gps"
    OPTICAL = "optical"                  # 光电
    INFRARED = "infrared"                # 红外
    SONAR = "sonar"                      # 声呐
    BUOY = "buoy"                        # 浮标
    RELEASE = "release"                  # 释放器
    CABLE = "cable"                      # 缆绳
    COMPUTER = "computer"                # 工控机
    SENSOR = "sensor"                    # 传感器
    OTHER = "other"


@dataclass
class MaintenanceRecord:
    """设备维修/保养记录"""
    id: str                              # 记录ID
    device_id: str                       # 设备ID
    date: str                            # 日期 YYYY-MM-DD
    type: str                            # "maintenance"/"repair"/"replace"
    description: str                     # 描述
    parts_replaced: List[str] = field(default_factory=list)  # 更换零件列表
    technician: str = ""                 # 维修人员
    cost: float = 0.0                    # 费用
    next_maintenance_date: Optional[str] = None  # 下次保养日期


@dataclass
class DeploymentRecord:
    """设备使用/部署记录"""
    id: str
    device_id: str
    project_name: str                    # 项目名称
    start_date: str                      # 开始日期
    end_date: Optional[str] = None       # 结束日期（None表示仍在用）
    location: str = ""                   # 试验地点
    notes: str = ""                      # 备注


@dataclass
class Device:
    """设备电子档案"""
    # 基本信息
    id: str                              # 设备唯一ID（如 "RADAR-001"）
    name: str                            # 设备名称
    device_type: DeviceType              # 设备类型
    manufacturer: str = ""               # 制造商
    model: str = ""                      # 型号
    serial_number: str = ""              # 序列号
    
    # 时间信息
    purchase_date: str = ""              # 采购日期 YYYY-MM-DD
    commission_date: str = ""            # 投入使用日期
    warranty_expiry: str = ""            # 质保到期日
    expected_lifetime_years: float = 0.0 # 预期使用寿命（年）
    
    # 技术参数
    specifications: Dict[str, Any] = field(default_factory=dict)  # 技术参数
    operating_conditions: Dict[str, Any] = field(default_factory=dict)  # 工作条件
    
    # 状态信息
    status: DeviceStatus = DeviceStatus.ACTIVE
    current_location: str = ""           # 当前存放位置
    last_maintenance_date: str = ""      # 上次保养日期
    next_maintenance_date: str = ""      # 下次保养日期
    total_usage_hours: float = 0.0       # 累计使用时长（小时）
    
    # 关联信息
    tags: List[str] = field(default_factory=list)  # 标签（用于分类检索）
    notes: str = ""                      # 备注
    
    # 维修历史
    maintenance_history: List[MaintenanceRecord] = field(default_factory=list)
    deployment_history: List[DeploymentRecord] = field(default_factory=list)
    
    def get_age_years(self) -> float:
        """获取设备使用年限"""
        if not self.commission_date:
            return 0.0
        try:
            commission = datetime.strptime(self.commission_date, "%Y-%m-%d").date()
            today = date.today()
            return (today - commission).days / 365.25
        except ValueError:
            return 0.0
    
    def get_remaining_lifetime_years(self) -> float:
        """获取剩余使用寿命（年）"""
        if self.expected_lifetime_years <= 0:
            return -1.0  # 未知
        age = self.get_age_years()
        return max(0.0, self.expected_lifetime_years - age)
    
    def get_lifetime_usage_percent(self) -> float:
        """获取寿命使用百分比"""
        if self.expected_lifetime_years <= 0:
            return 0.0
        age = self.get_age_years()
        return min(100.0, (age / self.expected_lifetime_years) * 100.0)
    
    def is_overdue(self) -> bool:
        """是否超期服役"""
        if self.expected_lifetime_years <= 0:
            return False
        return self.get_age_years() >= self.expected_lifetime_years
    
    def get_maintenance_due_soon(self, days_ahead: int = 30) -> bool:
        """是否在指定天数内需要保养"""
        if not self.next_maintenance_date:
            return False
        try:
            next_date = datetime.strptime(self.next_maintenance_date, "%Y-%m-%d").date()
            today = date.today()
            delta = (next_date - today).days
            return 0 <= delta <= days_ahead
        except ValueError:
            return False
    
    def get_health_score(self) -> float:
        """计算设备健康评分（0-100）"""
        score = 100.0
        
        # 寿命因素（40%权重）
        if self.expected_lifetime_years > 0:
            usage_pct = self.get_lifetime_usage_percent()
            if usage_pct > 100:
                score -= 40  # 超期服役
            elif usage_pct > 80:
                score -= 20
            elif usage_pct > 60:
                score -= 10
        
        # 状态因素（30%权重）
        if self.status == DeviceStatus.MAINTENANCE:
            score -= 15
        elif self.status == DeviceStatus.OVERDUE:
            score -= 30
        
        # 保养及时性（30%权重）
        if self.next_maintenance_date:
            try:
                next_date = datetime.strptime(self.next_maintenance_date, "%Y-%m-%d").date()
                today = date.today()
                delta = (next_date - today).days
                if delta < 0:
                    score -= 20  # 已过期未保养
                elif delta <= 30:
                    score -= 10  # 即将到期
            except ValueError:
                pass
        
        return max(0.0, min(100.0, score))
    
    def get_alerts(self) -> List[str]:
        """获取设备预警信息列表"""
        alerts = []
        
        if self.is_overdue():
            alerts.append(f"⚠️ 超期服役：已使用{self.get_age_years():.1f}年，预期寿命{self.expected_lifetime_years:.1f}年")
        
        if self.get_maintenance_due_soon(30):
            alerts.append(f"🔧 即将保养：下次保养日期 {self.next_maintenance_date}")
        
        if self.next_maintenance_date:
            try:
                next_date = datetime.strptime(self.next_maintenance_date, "%Y-%m-%d").date()
                if next_date < date.today():
                    alerts.append(f"❌ 保养已过期：应于 {self.next_maintenance_date} 保养")
            except ValueError:
                pass
        
        if self.warranty_expiry:
            try:
                warranty = datetime.strptime(self.warranty_expiry, "%Y-%m-%d").date()
                if warranty < date.today():
                    alerts.append(f"📅 质保已过期：{self.warranty_expiry}")
                elif (warranty - date.today()).days <= 90:
                    alerts.append(f"📅 质保即将过期：{self.warranty_expiry}")
            except ValueError:
                pass
        
        if self.get_health_score() < 50:
            alerts.append(f"⚠️ 健康评分低：{self.get_health_score():.0f}/100")
        
        return alerts


@dataclass
class EquipmentListTemplate:
    """设备清单模板"""
    id: str
    name: str                            # 模板名称
    description: str = ""                # 模板描述
    experiment_type: str = ""            # 试验类型（如 "雷达试验", "声学试验"）
    category: str = ""                   # 分类（如 "核心设备", "备件", "工具"）
    
    # 模板设备列表
    items: List[Dict[str, Any]] = field(default_factory=list)
    # 每个item格式: {"device_type": "radar", "min_count": 1, "recommended_models": [...], "required": True}
    
    # 历史使用统计
    usage_count: int = 0                 # 使用次数
    last_used: str = ""                  # 最后使用日期
    success_rate: float = 1.0            # 成功率（无遗漏的比例）
    
    def get_recommended_devices(self, experiment_type: str = "") -> List[Dict[str, Any]]:
        """获取推荐设备列表"""
        if experiment_type and self.experiment_type != experiment_type:
            return []
        return self.items
    
    def add_item(self, device_type: str, min_count: int = 1, 
                 recommended_models: List[str] = None, required: bool = True):
        """添加设备到模板"""
        if recommended_models is None:
            recommended_models = []
        self.items.append({
            "device_type": device_type,
            "min_count": min_count,
            "recommended_models": recommended_models,
            "required": required,
        })


@dataclass
class ExperimentEquipmentList:
    """试验设备清单（基于模板生成）"""
    id: str
    experiment_name: str
    template_id: str = ""                # 使用的模板ID
    created_date: str = ""
    
    # 设备清单
    required_devices: List[Dict[str, Any]] = field(default_factory=list)
    # 格式: {"device_id": "...", "device_name": "...", "status": "ready"/"missing"/"maintenance"}
    
    # 检查结果
    check_date: str = ""
    all_ready: bool = False
    missing_count: int = 0
    notes: str = ""
    
    def check_readiness(self, device_manager: 'DeviceManager') -> bool:
        """检查设备是否就绪"""
        self.all_ready = True
        self.missing_count = 0
        
        for item in self.required_devices:
            device_id = item.get("device_id")
            if not device_id:
                item["status"] = "missing"
                self.all_ready = False
                self.missing_count += 1
                continue
            
            device = device_manager.get_device(device_id)
            if device is None:
                item["status"] = "missing"
                self.all_ready = False
                self.missing_count += 1
            elif device.is_overdue():
                item["status"] = "overdue"
                item["alert"] = "超期服役"
            elif device.status == DeviceStatus.MAINTENANCE:
                item["status"] = "maintenance"
                item["alert"] = "维修中"
            else:
                item["status"] = "ready"
        
        return self.all_ready
    
    def get_summary(self) -> str:
        """获取清单摘要"""
        ready = sum(1 for d in self.required_devices if d.get("status") == "ready")
        total = len(self.required_devices)
        return f"{ready}/{total} 设备就绪, {self.missing_count} 缺失"


class DeviceManager:
    """设备管理器 - CRUD操作 + 智能推荐 + 寿命预警"""
    
    def __init__(self):
        self.devices: Dict[str, Device] = {}
        self.templates: Dict[str, EquipmentListTemplate] = {}
        self.experiment_lists: Dict[str, ExperimentEquipmentList] = {}
    
    # ── 设备CRUD ─────────────────────────────────────
    
    def add_device(self, device: Device) -> str:
        """添加设备"""
        self.devices[device.id] = device
        _logger.info(f"设备已添加: {device.id} ({device.name})")
        return device.id
    
    def update_device(self, device_id: str, **kwargs) -> bool:
        """更新设备信息"""
        if device_id not in self.devices:
            _logger.warning(f"设备不存在: {device_id}")
            return False
        
        device = self.devices[device_id]
        for key, value in kwargs.items():
            if hasattr(device, key):
                setattr(device, key, value)
            else:
                _logger.warning(f"设备无此属性: {key}")
        return True
    
    def get_device(self, device_id: str) -> Optional[Device]:
        """获取设备"""
        return self.devices.get(device_id)
    
    def delete_device(self, device_id: str) -> bool:
        """删除设备（标记为报废）"""
        if device_id not in self.devices:
            return False
        self.devices[device_id].status = DeviceStatus.RETIRED
        _logger.info(f"设备已标记为报废: {device_id}")
        return True
    
    def list_devices(self, device_type: Optional[DeviceType] = None,
                     status: Optional[DeviceStatus] = None) -> List[Device]:
        """列出设备（可按类型和状态筛选）"""
        result = list(self.devices.values())
        if device_type:
            result = [d for d in result if d.device_type == device_type]
        if status:
            result = [d for d in result if d.status == status]
        return result
    
    def search_devices(self, query: str) -> List[Device]:
        """搜索设备（按名称、型号、序列号、标签）"""
        query_lower = query.lower()
        result = []
        for device in self.devices.values():
            if (query_lower in device.name.lower() or
                query_lower in device.model.lower() or
                query_lower in device.serial_number.lower() or
                any(query_lower in tag.lower() for tag in device.tags)):
                result.append(device)
        return result
    
    # ── 维修记录 ─────────────────────────────────────
    
    def add_maintenance_record(self, device_id: str, record: MaintenanceRecord) -> bool:
        """添加维修记录"""
        device = self.devices.get(device_id)
        if device is None:
            return False
        device.maintenance_history.append(record)
        device.last_maintenance_date = record.date
        device.next_maintenance_date = record.next_maintenance_date or ""
        return True
    
    def get_maintenance_history(self, device_id: str) -> List[MaintenanceRecord]:
        """获取维修历史"""
        device = self.devices.get(device_id)
        return device.maintenance_history if device else []
    
    # ── 部署记录 ─────────────────────────────────────
    
    def add_deployment_record(self, device_id: str, record: DeploymentRecord) -> bool:
        """添加部署记录"""
        device = self.devices.get(device_id)
        if device is None:
            return False
        device.deployment_history.append(record)
        return True
    
    # ── 设备清单模板 ──────────────────────────────────
    
    def add_template(self, template: EquipmentListTemplate) -> str:
        """添加设备清单模板"""
        self.templates[template.id] = template
        return template.id
    
    def get_template(self, template_id: str) -> Optional[EquipmentListTemplate]:
        """获取模板"""
        return self.templates.get(template_id)
    
    def list_templates(self, experiment_type: str = "") -> List[EquipmentListTemplate]:
        """列出模板"""
        if experiment_type:
            return [t for t in self.templates.values() if t.experiment_type == experiment_type]
        return list(self.templates.values())
    
    def create_experiment_list(self, template_id: str, experiment_name: str) -> ExperimentEquipmentList:
        """基于模板创建试验设备清单"""
        template = self.templates.get(template_id)
        if template is None:
            raise ValueError(f"模板不存在: {template_id}")
        
        exp_list = ExperimentEquipmentList(
            id=f"EXP-{len(self.experiment_lists)+1:03d}",
            experiment_name=experiment_name,
            template_id=template_id,
            created_date=date.today().strftime("%Y-%m-%d"),
        )
        
        # 从模板生成设备清单
        for item in template.items:
            device_type = item.get("device_type")
            # 查找匹配的设备
            matching_devices = self.list_devices(
                device_type=DeviceType(device_type) if device_type in DeviceType.__members__.values() else None
            )
            
            for dev in matching_devices[:item.get("min_count", 1)]:
                exp_list.required_devices.append({
                    "device_id": dev.id,
                    "device_name": dev.name,
                    "device_type": device_type,
                    "status": "pending",
                })
        
        self.experiment_lists[exp_list.id] = exp_list
        template.usage_count += 1
        template.last_used = exp_list.created_date
        
        return exp_list
    
    # ── 智能推荐 ─────────────────────────────────────
    
    def recommend_devices_for_experiment(self, experiment_type: str,
                                         count: int = 5) -> List[Device]:
        """基于历史试验智能推荐设备"""
        # 1. 从常用模板中推荐
        templates = self.list_templates(experiment_type)
        recommended_ids = set()
        for template in templates:
            for item in template.items:
                device_type = item.get("device_type")
                if device_type:
                    matching = self.list_devices(
                        device_type=DeviceType(device_type) if device_type in DeviceType.__members__.values() else None
                    )
                    for dev in matching[:item.get("min_count", 1)]:
                        recommended_ids.add(dev.id)
        
        # 2. 按健康评分排序
        recommended = []
        for dev_id in recommended_ids:
            dev = self.devices.get(dev_id)
            if dev and dev.status == DeviceStatus.ACTIVE:
                recommended.append(dev)
        
        recommended.sort(key=lambda d: d.get_health_score(), reverse=True)
        return recommended[:count]
    
    # ── 寿命预警 ─────────────────────────────────────
    
    def get_overdue_devices(self) -> List[Device]:
        """获取超期服役设备列表"""
        return [d for d in self.devices.values() if d.is_overdue()]
    
    def get_maintenance_due_devices(self, days_ahead: int = 30) -> List[Device]:
        """获取即将需要保养的设备"""
        return [d for d in self.devices.values() if d.get_maintenance_due_soon(days_ahead)]
    
    def get_all_alerts(self) -> Dict[str, List[str]]:
        """获取所有设备预警信息"""
        alerts = {}
        for device in self.devices.values():
            device_alerts = device.get_alerts()
            if device_alerts:
                alerts[device.id] = device_alerts
        return alerts
    
    def get_health_summary(self) -> Dict[str, Any]:
        """获取设备健康汇总"""
        total = len(self.devices)
        active = sum(1 for d in self.devices.values() if d.status == DeviceStatus.ACTIVE)
        overdue = sum(1 for d in self.devices.values() if d.is_overdue())
        maintenance = sum(1 for d in self.devices.values() if d.status == DeviceStatus.MAINTENANCE)
        
        avg_health = 0.0
        if total > 0:
            avg_health = sum(d.get_health_score() for d in self.devices.values()) / total
        
        return {
            "total_devices": total,
            "active_devices": active,
            "overdue_devices": overdue,
            "maintenance_devices": maintenance,
            "average_health_score": avg_health,
        }
