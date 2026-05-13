"""
向下调用链构建器（增强版 - 支持 CHA 接口解析）

负责构建"这个方法调用了谁"的调用链（功能风险分析）。
v3.2 新增：
1. 支持 MyBatis Mapper SQL 级别追踪
2. ✅ 修复缺陷3：在展开子节点时主动解析接口调用（CHA）
"""

import logging
from typing import Optional, Set
from .builder import CallChainBuilder
from .models import CallChainNode
from .parser import InvocationPointParser

logger = logging.getLogger(__name__)


class DownwardsCallChainBuilder(CallChainBuilder):
    """
    向下调用链构建器（增强版）
    
    继承自 CallChainBuilder，增加：
    1. Mapper/DAO 层方法识别
    2. SQL 级别调用链展开
    3. ✅ 接口-实现类映射支持（通过 CHA，修复缺陷3）
    """
    
    def __init__(self, unified_index, max_depth: int = 10,
                 dao_analyzer=None, class_hierarchy=None):
        """
        初始化向下调用链构建器
        
        Args:
            unified_index: UnifiedMethodIndex 实例
            max_depth: 最大递归深度
            dao_analyzer: DAO 分析器实例（可选）
            class_hierarchy: 类层次索引（用于 CHA，可选）
        """
        super().__init__(unified_index, max_depth=max_depth, dao_analyzer=dao_analyzer)
        self.class_hierarchy = class_hierarchy
        logger.info(f"Downwards call chain builder initialized (max_depth={max_depth}, "
                   f"dao_analyzer={'enabled' if dao_analyzer else 'disabled'}, "
                   f"cha={'enabled' if class_hierarchy else 'disabled'})")
    
    def _dfs_expand(self, node: CallChainNode, path_visited: Set[str], current_depth: int):
        """
        ✅ 修复缺陷3：重写 DFS 展开逻辑，增加接口调用解析和 SQL 节点生成
        
        Args:
            node: 当前节点
            path_visited: 路径访问集合
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
            return
        
        # 3. 更新节点信息
        node.db_method_id = method_data.get('method_id')
        
        # ✅ 修复：在解析invocation_map之前，先检查是否为接口调用
        # 如果是接口，即使没有invocation_map，也应该通过CHA解析实现类
        if self.class_hierarchy and self._is_interface_call(node.package_class):
            
            # 通过 CHA 找到所有实现类方法
            impl_methods = self.class_hierarchy.resolve_interface_call(
                node.package_class, 
                node.method_signature
            )
            
            if impl_methods:
                logger.debug(f"  Found {len(impl_methods)} implementations")
                
                # 对每个实现类创建子节点
                for impl in impl_methods:
                    impl_key = f"{impl['package_class']}|{impl['method_signature']}"
                    
                    # 环检测
                    if impl_key in path_visited:
                        continue
                    
                    # 创建实现类节点
                    impl_point = {
                        'package_class': impl['package_class'],
                        'signature': impl['method_signature'],
                        'lines': []
                    }
                    
                    impl_method_data = self.unified_index.query_method(
                        impl['package_class'], impl['method_signature']
                    )
                    
                    impl_node = self._create_node(impl_point, current_depth + 1, impl_method_data)
                    impl_node.cha_resolved = True  # 标记为 CHA 解析
                    impl_node.original_interface = node.package_class  # 记录原始接口
                    node.children.append(impl_node)
                    
                    # 递归展开实现类
                    path_visited.add(impl_key)
                    self._dfs_expand(impl_node, path_visited, current_depth + 1)
                    path_visited.discard(impl_key)
                
                return  # 已处理接口调用，直接返回
            else:
                logger.debug(f"  No implementations found via CHA")
        
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
        
        # 6. 递归构建子树（✅ 增加 CHA 接口解析）
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
            
            # ✅ 修复缺陷3：如果调用的是接口，通过 CHA 解析实现类
            if self.class_hierarchy and self._is_interface_call(point['package_class']):
                logger.debug(f"Detected interface call: {point['package_class']}.{point['signature']}")
                
                # 通过 CHA 找到所有实现类方法
                impl_methods = self.class_hierarchy.resolve_interface_call(
                    point['package_class'], 
                    point['signature']
                )
                
                if impl_methods:
                    logger.debug(f"  Found {len(impl_methods)} implementations")
                    
                    # 对每个实现类创建子节点
                    for impl in impl_methods:
                        impl_key = f"{impl['package_class']}|{impl['method_signature']}"
                        
                        # 环检测
                        if impl_key in path_visited:
                            continue
                        
                        # 创建实现类节点
                        impl_point = {
                            'package_class': impl['package_class'],
                            'signature': impl['method_signature'],
                            'lines': point['lines']
                        }
                        
                        impl_method_data = self.unified_index.query_method(
                            impl['package_class'], impl['method_signature']
                        )
                        
                        impl_node = self._create_node(impl_point, current_depth + 1, impl_method_data)
                        impl_node.cha_resolved = True  # 标记为 CHA 解析
                        impl_node.original_interface = point['package_class']  # 记录原始接口
                        node.children.append(impl_node)
                        
                        # 递归展开实现类
                        path_visited.add(impl_key)
                        self._dfs_expand(impl_node, path_visited, current_depth + 1)
                        path_visited.discard(impl_key)
                    
                    continue  # 已处理接口调用，跳过原有逻辑
            
            # 6.2 非接口调用，使用原有逻辑
            child_method_data = self.unified_index.query_method(
                point['package_class'], point['signature']
            )
            child = self._create_node(point, current_depth + 1, child_method_data)
            node.children.append(child)
            
            # 6.3 递归下探
            path_visited.add(child_key)
            self._dfs_expand(child, path_visited, current_depth + 1)
            path_visited.discard(child_key)  # 回溯
        
        # 7. ✅ 新增：如果是 Mapper/DAO 方法，添加 SQL 子节点
        if self.dao_analyzer and self.dao_analyzer.is_dao_method(node.package_class, node.method_name):
            sql_info = self.dao_analyzer.analyze(
                node.package_class,
                node.method_signature,
                node.db_method_id
            )
            
            if sql_info:
                sql_node = self.dao_analyzer.create_sql_node(node, sql_info)
                node.children.append(sql_node)
                node.is_leaf = False  # Mapper 节点不再是叶子
                
                logger.debug(f"Added SQL node for {node.package_class}.{node.method_name}: "
                           f"{sql_info['sql_type']} on {sql_info.get('tables', [])}")
        
        # 8. 如果没有子节点，标记为叶子
        if not node.children:
            node.is_leaf = True
    
    def _is_interface_call(self, package_class: str) -> bool:
        """
        判断是否为接口调用
        
        Args:
            package_class: 完整类名
            
        Returns:
            True 如果是接口或抽象类
        """
        if not self.class_hierarchy:
            return False
        
        return self.class_hierarchy.is_interface_or_abstract_class(package_class)
