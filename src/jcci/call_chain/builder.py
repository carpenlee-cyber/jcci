"""
调用链构建器

负责基于统一索引和解析器，构建完整的调用链路树。
使用 DFS 递归算法展开调用关系。
v4.0 新增：支持可选注入 DaoAnalyzer，透传 change_type 和 dao_info
"""

import logging
from typing import Set, Optional
from .models import CallChainNode, ChangeType
from .parser import InvocationPointParser

logger = logging.getLogger(__name__)


class CallChainBuilder:
    """
    调用链构建器
    
    核心算法：DFS 递归展开
    - 从起始方法开始
    - 解析 method_invocation_map 提取调用点
    - 按行号排序
    - 对每个调用点递归下探
    - 环检测和深度限制
    
    Attributes:
        unified_index: 统一方法索引
        max_depth: 最大深度限制（默认 10）
    """
    
    def __init__(self, unified_index, max_depth: int = 10,
                 dao_analyzer=None):
        """
        初始化调用链构建器
        
        Args:
            unified_index: UnifiedMethodIndex 实例
            max_depth: 最大递归深度
            dao_analyzer: 可选的 DaoAnalyzer 实例（v4.0 新增）
        """
        self.unified_index = unified_index
        self.max_depth = max_depth
        self.dao_analyzer = dao_analyzer  # v4.0: 可选注入，非强制依赖
    
    def build(self, package_class: str, method_signature: str) -> CallChainNode:
        """
        构建调用链
        
        Args:
            package_class: 完整类名，如 "com.test.Controller"
            method_signature: 方法签名，如 "handleRequest()"
        
        Returns:
            CallChainNode: 调用链树的根节点
        """
        # 创建根节点
        method_name = method_signature.split('(')[0]
        class_name = package_class.split('.')[-1]
        node_id = f"0|{package_class}|{method_signature}"
        
        # 查询根方法的 method_data（用于 change_type 和 DAO 分析）
        root_method_data = self.unified_index.query_method(package_class, method_signature)
        
        root = self._create_node(
            point={'package_class': package_class, 'signature': method_signature, 'lines': []},
            depth=0,
            method_data=root_method_data
        )
        
        # 开始 DFS 展开
        path_visited: Set[str] = {f"{package_class}|{method_signature}"}
        self._dfs_expand(root, path_visited, current_depth=0)
        
        return root
    
    def _dfs_expand(self, node: CallChainNode, path_visited: Set[str], current_depth: int):
        """
        深度优先展开节点
        
        Args:
            node: 当前节点
            path_visited: 路径级已访问集合（用于环检测）
            current_depth: 当前深度
        """
        # 1. 深度限制检查
        if current_depth >= self.max_depth:
            node.is_leaf = True
            logger.debug(f"Max depth {self.max_depth} reached at {node.node_id}")
            return
        
        # 2. 从统一索引查询当前方法
        method_data = self.unified_index.query_method(
            node.package_class, 
            node.method_signature
        )
        
        if not method_data:
            node.is_leaf = True
            logger.debug(f"Method not found: {node.package_class}.{node.method_signature}")
            return
        
        # 3. 更新节点信息
        node.db_method_id = method_data.get('method_id')
        
        # 4. 解析 method_invocation_map
        invocation_map_json = method_data.get('method_invocation_map', '{}')
        callable_points = InvocationPointParser.parse(invocation_map_json)
        
        if not callable_points:
            node.is_leaf = True
            return
        
        # 5. 按行号排序
        sorted_points = sorted(
            callable_points, 
            key=lambda p: min(p['lines']) if p['lines'] else 999999
        )
        
        # 6. 递归构建子树
        for point in sorted_points:
            child_key = f"{point['package_class']}|{point['signature']}"
            
            # 6.1 环检测
            if child_key in path_visited:
                child = self._create_node(point, current_depth + 1)
                child.is_cyclic = True
                child.is_leaf = True
                node.children.append(child)
                logger.debug(f"Cycle detected: {child_key}")
                continue
            
            # 6.2 创建子节点（传入 method_data 用于 change_type 和 DAO 分析）
            child_method_data = self.unified_index.query_method(
                point['package_class'], point['signature']
            )
            child = self._create_node(point, current_depth + 1, child_method_data)
            node.children.append(child)
            
            # 6.3 递归下探
            path_visited.add(child_key)
            self._dfs_expand(child, path_visited, current_depth + 1)
            path_visited.discard(child_key)  # 回溯
        
        # 7. 如果没有子节点，标记为叶子
        if not node.children:
            node.is_leaf = True
    
    def _create_node(self, point: dict, depth: int, 
                     method_data: Optional[dict] = None) -> CallChainNode:
        """
        创建调用链节点，注入 change_type 和 DAO 信息
        
        Args:
            point: 调用点信息 {'package_class', 'signature', 'lines'}
            depth: 节点深度
            method_data: 可选的方法数据（用于 change_type 和 DAO 分析）
        
        Returns:
            CallChainNode: 新创建的节点
        """
        package_class = point['package_class']
        signature = point['signature']
        lines = point['lines']
        
        method_name = signature.split('(')[0]
        class_name = package_class.split('.')[-1]
        node_id = f"{depth}|{package_class}|{signature}"
        
        node = CallChainNode(
            node_id=node_id,
            package_class=package_class,
            method_signature=signature,
            method_name=method_name,
            class_name=class_name,
            depth=depth,
            invocation_lines=lines
        )
        
        if method_data:
            # v4.0: 显式枚举转换，永不为 null
            raw_change_type = method_data.get('change_type')
            node.change_type = ChangeType.from_raw(raw_change_type).value
            
            node.db_method_id = method_data.get('method_id')
            
            # v4.0: DAO 分析（仅在注入 analyzer 且存在 method_id 时）
            if self.dao_analyzer and node.db_method_id:
                node.dao_info = self.dao_analyzer.analyze(
                    package_class, signature, node.db_method_id
                )
        
        return node
