"""
调用链路数据模型

定义 CallChainNode 数据结构，用于表示调用链路中的节点。
v4.0 新增：ChangeType 枚举、DaoInfo 模型
"""

from dataclasses import dataclass, field
from typing import List, Optional
from enum import Enum


class ChangeType(str, Enum):
    """
    方法变更状态枚举
    
    定义：
    - UNCHANGED:  基线存在，增量也存在，且经外部 diff 判定无变更
    - ADDED:      基线不存在，增量存在
    - MODIFIED:   基线存在，增量存在，且经外部 diff 判定有变更
    - DELETED:    基线存在，增量标记为删除（已被索引过滤，理论上不出现在调用链中）
    - UNKNOWN:    无法判定变更状态（如基线数据未记录 change_type）
    
    与索引合并的关系：
    - 统一索引合并后，每个方法保留其最终来源的 change_type
    - 增量覆盖基线时，以增量数据的 change_type 为准
    - 若增量数据无 change_type 字段，继承基线值；若基线也无，则为 UNKNOWN
    """
    UNCHANGED = "UNCHANGED"
    ADDED = "ADDED"
    MODIFIED = "MODIFIED"
    DELETED = "DELETED"
    UNKNOWN = "UNKNOWN"
    
    @classmethod
    def from_raw(cls, raw: Optional[str]) -> "ChangeType":
        """从原始字符串安全转换，无法识别时返回 UNKNOWN"""
        if not raw:
            return cls.UNKNOWN
        try:
            return cls(raw.upper())
        except ValueError:
            return cls.UNKNOWN


@dataclass
class DaoInfo:
    """
    DAO 方法透视信息
    
    当调用链节点被识别为 DAO 层方法时填充此对象。
    若数据库中无 SQL 映射，仅通过命名推导，则 sql_statement 为 null，
    但 entity_name 可能通过命名推导获得，此时 entity_source = 'INFERRED'。
    """
    is_dao: bool = True
    dao_type: str = "UNKNOWN"              # MYBATIS / JPA / JDBC / MYBATIS_PLUS / UNKNOWN
    entity_name: Optional[str] = None      # 实体类名：如 "UmsAdmin"
    entity_class: Optional[str] = None     # 实体全限定名：如 "com.macro.mall.model.UmsAdmin"
    entity_source: str = "UNKNOWN"         # INFERRED（命名推导）/ MAPPED（数据库映射）/ UNKNOWN
    table_name: Optional[str] = None       # 表名：如 "ums_admin"
    sql_type: Optional[str] = None         # SELECT / INSERT / UPDATE / DELETE / BATCH / UNKNOWN
    sql_statement: Optional[str] = None    # 完整 SQL（含占位符）
    mapped_statement_id: Optional[str] = None  # MyBatis namespace.id
    
    def to_dict(self) -> dict:
        """转换为字典（用于 JSON 序列化）"""
        return {
            "is_dao": self.is_dao,
            "dao_type": self.dao_type,
            "entity_name": self.entity_name,
            "entity_class": self.entity_class,
            "entity_source": self.entity_source,
            "table_name": self.table_name,
            "sql_type": self.sql_type,
            "sql_statement": self.sql_statement,
            "mapped_statement_id": self.mapped_statement_id
        }


@dataclass
class CallChainNode:
    """
    调用链路节点（v3.1 增强版）
    
    Attributes:
        node_id: 唯一标识，格式: "{depth}|{package_class}|{method_signature}"
        package_class: 完整类名，如 "com.macro.mall.service.UmsMenuService"
        method_signature: 方法签名，如 "list(int,int)"
        method_name: 方法名，如 "list"
        class_name: 类名，如 "UmsMenuService"
        depth: 深度（根节点为 0）
        invocation_lines: 调用发生的行号列表
        children: 子节点列表
        is_cyclic: 是否检测到环
        is_leaf: 是否为叶子节点
        db_method_id: 数据库中的 method_id
        
        v3.1 新增字段：
        root_type: 根节点类型分类（HTTP_API, SCHEDULED_TASK, NO_STATIC_CALLER等）
        call_type: 调用类型（DIRECT / CHA_RESOLVED）
        has_multiple_call_sites: 同一调用者内多处调用
        entry_annotation: 入口注解（如 @RequestMapping）
        
        v4.0 新增字段：
        change_type: ChangeType 枚举值字符串
        dao_info: DAO 透视信息（非 DAO 方法为 null）
    """
    node_id: str
    package_class: str
    method_signature: str
    method_name: str
    class_name: str
    depth: int = 0
    invocation_lines: List[int] = field(default_factory=list)
    children: List['CallChainNode'] = field(default_factory=list)
    is_cyclic: bool = False
    is_leaf: bool = False
    db_method_id: Optional[int] = None
    
    # v3.1 新增字段
    root_type: str = 'UNKNOWN'
    call_type: str = 'DIRECT'
    has_multiple_call_sites: bool = False
    entry_annotation: Optional[str] = None
    api_paths: List[str] = field(default_factory=list)  # API路径列表，如 ["[POST]/coupon/delete/{id}"]
    
    # v4.0 新增字段
    change_type: str = "UNKNOWN"
    dao_info: Optional[DaoInfo] = None
    
    def to_dict(self) -> dict:
        """
        转换为字典（用于 JSON 序列化，v3.1 增强版）
        
        Returns:
            dict: 节点的字典表示，包含所有字段和递归的子节点
        """
        base = {
            "node_id": self.node_id,
            "package_class": self.package_class,
            "method_signature": self.method_signature,
            "method_name": self.method_name,
            "class_name": self.class_name,
            "depth": self.depth,
            "invocation_lines": self.invocation_lines,
            "is_cyclic": self.is_cyclic,
            "is_leaf": self.is_leaf,
            "db_method_id": self.db_method_id,
            # v3.1 新增
            "root_type": self.root_type,
            "call_type": self.call_type,
            "has_multiple_call_sites": self.has_multiple_call_sites,
            "api_paths": self.api_paths,  # API路径列表
            # v4.0 新增
            "change_type": self.change_type,
            "dao_info": self.dao_info.to_dict() if self.dao_info else None,
            "children": [child.to_dict() for child in self.children]
        }
        if self.entry_annotation:
            base["entry_annotation"] = self.entry_annotation
        return base
