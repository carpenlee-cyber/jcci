"""
调用链路数据模型

定义 CallChainNode 数据结构，用于表示调用链路中的节点。
"""

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class CallChainNode:
    """
    调用链路节点
    
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
    
    def to_dict(self) -> dict:
        """
        转换为字典（用于 JSON 序列化）
        
        Returns:
            dict: 节点的字典表示，包含所有字段和递归的子节点
        """
        return {
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
            "children": [child.to_dict() for child in self.children]
        }
