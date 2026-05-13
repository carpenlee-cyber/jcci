"""
向上调用链构建器

负责构建"谁调用了这个方法"的调用链（影响面分析）。
支持 CHA、注解感知入口发现、覆盖率统计。
"""

import json
import logging
from typing import Set, Optional, Dict, List, Any
from .models import CallChainNode
from .parser import InvocationPointParser

logger = logging.getLogger(__name__)


class ReverseCallerIndex:
    """
    反向调用索引（增强版）
    支持 Class Hierarchy Analysis (CHA) 解析接口调用
    """
    
    def __init__(self, unified_index, class_hierarchy=None):
        """
        初始化反向调用索引
        
        Args:
            unified_index: UnifiedMethodIndex 实例
            class_hierarchy: 可选的 ClassHierarchyIndex 实例
        """
        self._reverse_index: Dict[str, List[dict]] = {}
        self._class_hierarchy = class_hierarchy
        self._build_reverse_index(unified_index)
        logger.info(f"Reverse caller index built: {len(self._reverse_index)} callee keys")
    
    def _build_reverse_index(self, unified_index):
        """
        扫描统一索引中所有方法的 method_invocation_map，
        建立反向调用关系，支持接口方法到实现类的映射
        """
        for key, methods in unified_index._unified_index.items():
            for method in methods:
                caller_info = self._extract_caller_info(method)
                invocation_map_json = method.get('method_invocation_map', '{}')
                
                if not invocation_map_json or invocation_map_json == '{}':
                    continue
                
                callable_points = InvocationPointParser.parse(invocation_map_json)
                
                for point in callable_points:
                    callee_package_class = point['package_class']
                    callee_signature = point['signature']
                    
                    if self._class_hierarchy:
                        impl_methods = self._class_hierarchy.resolve_interface_call(
                            callee_package_class, 
                            callee_signature
                        )
                        
                        for impl in impl_methods:
                            impl_key = f"{impl['package_class']}|{impl['method_signature']}"
                            self._add_caller(impl_key, caller_info, point['lines'], 
                                           call_type='CHA_RESOLVED')
                    
                    callee_key = f"{callee_package_class}|{callee_signature}"
                    self._add_caller(callee_key, caller_info, point['lines'],
                                   call_type='DIRECT')
    
    def _extract_caller_info(self, method: dict) -> dict:
        """提取调用者信息"""
        package_name = method.get('package_name', '')
        class_name = method.get('class_name', '')
        method_name = method.get('method_name', '')
        parameters = method.get('parameters', '[]')
        
        package_class = f"{package_name}.{class_name}"
        
        try:
            params = json.loads(parameters) if isinstance(parameters, str) else parameters
            if isinstance(params, list):
                param_types = [p.get('parameter_type', '') for p in params]
                signature = f"{method_name}({','.join(param_types)})"
            else:
                signature = f"{method_name}()"
        except:
            signature = f"{method_name}()"
        
        return {
            'method_id': method.get('method_id'),
            'package_class': package_class,
            'method_signature': signature,
            'method_name': method_name,
            'class_name': class_name
        }
    
    def _add_caller(self, callee_key: str, caller_info: dict, lines: List[int],
                   call_type: str = 'DIRECT'):
        """添加调用者到反向索引，保留多调用点行号"""
        if callee_key not in self._reverse_index:
            self._reverse_index[callee_key] = []
        
        unique_lines = sorted(list(set(lines)))
        
        existing = None
        for entry in self._reverse_index[callee_key]:
            if (entry['package_class'] == caller_info['package_class'] and 
                entry['method_signature'] == caller_info['method_signature']):
                existing = entry
                break
        
        if existing:
            existing_lines = set(existing.get('invocation_lines', []))
            existing_lines.update(unique_lines)
            existing['invocation_lines'] = sorted(list(existing_lines))
            existing['multi_call_sites'] = len(existing['invocation_lines']) > 1
        else:
            new_entry = {
                **caller_info,
                'invocation_lines': unique_lines,  # 使用去重后的行号
                'call_type': call_type,
                'multi_call_sites': len(unique_lines) > 1
            }
            self._reverse_index[callee_key].append(new_entry)
    
    def query_callers(self, package_class: str, method_signature: str) -> List[dict]:
        """
        查询调用了指定方法的所有调用者（含 CHA 解析）
        """
        key = f"{package_class}|{method_signature}"
        results = []
        seen_keys = set()
        
        direct_callers = self._reverse_index.get(key, [])
        for caller in direct_callers:
            caller_key = f"{caller['package_class']}|{caller['method_signature']}"
            if caller_key not in seen_keys:
                results.append(caller)
                seen_keys.add(caller_key)
        
        return results


class UpwardsCallChainBuilder:
    """
    向上调用链构建器（增强版）
    支持 CHA、注解感知入口发现、覆盖率统计
    """
    
    def __init__(self, 
                 reverse_index: ReverseCallerIndex,
                 entry_detector=None,
                 max_depth: int = 10):
        """
        初始化向上调用链构建器
        
        Args:
            reverse_index: ReverseCallerIndex 实例
            entry_detector: 可选的 AnnotationAwareEntryDetector 实例
            max_depth: 最大深度
        """
        self.reverse_index = reverse_index
        self.entry_detector = entry_detector
        self.max_depth = max_depth
        self._coverage_stats = {
            'total_query_methods': 0,
            'methods_with_callers': 0,
            'methods_without_callers': 0,
            'cha_resolved_calls': 0,
            'direct_calls': 0,
            'cyclic_paths': 0,
            'depth_limited_paths': 0
        }
        self._limitations = []
    
    def build(self, package_class: str, method_signature: str) -> CallChainNode:
        """构建向上调用链"""
        root = self._create_node(package_class, method_signature, depth=0)
        
        # 分类根节点类型，并获取API路径信息
        root.root_type = self._classify_root(package_class, method_signature, has_callers=False)
        
        # 如果是HTTP API入口，从entry_detector中获取API路径
        if self.entry_detector and root.root_type == 'HTTP_API':
            entry_info = self.entry_detector.is_entry_method(package_class, method_signature)
            if entry_info and 'api_paths' in entry_info:
                root.api_paths = entry_info['api_paths']
        
        path_visited = {f"{package_class}|{method_signature}"}
        self._dfs_expand(root, path_visited, current_depth=0)
        
        root._analysis_meta = {
            'coverage_stats': self._coverage_stats.copy(),
            'limitations': self._limitations.copy(),
            'is_complete': len(self._limitations) == 0
        }
        
        return root
    
    def _dfs_expand(self, node: CallChainNode, path_visited: Set[str], current_depth: int):
        """反向 DFS（增强版）"""
        self._coverage_stats['total_query_methods'] += 1
        
        if current_depth >= self.max_depth:
            node.is_leaf = True
            node.root_type = 'DEPTH_LIMITED'
            self._coverage_stats['depth_limited_paths'] += 1
            self._limitations.append(f"Depth limit reached at {node.node_id}")
            return
        
        callers = self.reverse_index.query_callers(node.package_class, node.method_signature)
        
        if not callers:
            node.is_leaf = True
            self._coverage_stats['methods_without_callers'] += 1
            
            node.root_type = self._classify_root(
                node.package_class, 
                node.method_signature,
                has_callers=False
            )
            return
        
        self._coverage_stats['methods_with_callers'] += 1
        
        for caller in callers:
            if caller.get('call_type') == 'CHA_RESOLVED':
                self._coverage_stats['cha_resolved_calls'] += 1
            else:
                self._coverage_stats['direct_calls'] += 1
        
        sorted_callers = sorted(
            callers,
            key=lambda c: min(c['invocation_lines']) if c.get('invocation_lines') else 999999
        )
        
        for caller in sorted_callers:
            caller_key = f"{caller['package_class']}|{caller['method_signature']}"
            
            if caller_key in path_visited:
                parent = self._create_node_from_caller(caller, current_depth + 1)
                parent.is_cyclic = True
                parent.is_leaf = True
                parent.root_type = 'CYCLIC'
                node.children.append(parent)
                self._coverage_stats['cyclic_paths'] += 1
                continue
            
            parent = self._create_node_from_caller(caller, current_depth + 1)
            
            if caller.get('multi_call_sites'):
                parent.has_multiple_call_sites = True
            
            node.children.append(parent)
            
            path_visited.add(caller_key)
            self._dfs_expand(parent, path_visited, current_depth + 1)
            path_visited.discard(caller_key)
        
        if not node.children:
            node.is_leaf = True
    
    def _classify_root(self, package_class: str, method_signature: str, 
                       has_callers: bool) -> str:
        """分类根节点类型"""
        if self.entry_detector:
            temp_node = CallChainNode(
                node_id="temp",
                package_class=package_class,
                method_signature=method_signature,
                method_name=method_signature.split('(')[0],
                class_name=package_class.split('.')[-1],
                depth=0
            )
            entry_type = self.entry_detector.classify_root_node(temp_node, has_callers)
            return entry_type
        return 'UNKNOWN'
    
    def _create_node(self, package_class: str, method_signature: str, depth: int) -> CallChainNode:
        """创建节点（增强字段）"""
        method_name = method_signature.split('(')[0]
        class_name = package_class.split('.')[-1]
        node_id = f"{depth}|{package_class}|{method_signature}"
        
        node = CallChainNode(
            node_id=node_id,
            package_class=package_class,
            method_signature=method_signature,
            method_name=method_name,
            class_name=class_name,
            depth=depth
        )
        node.root_type = 'UNKNOWN'
        node.has_multiple_call_sites = False
        return node
    
    def _create_node_from_caller(self, caller: dict, depth: int) -> CallChainNode:
        """从调用者信息创建节点"""
        node_id = f"{depth}|{caller['package_class']}|{caller['method_signature']}"
        
        node = CallChainNode(
            node_id=node_id,
            package_class=caller['package_class'],
            method_signature=caller['method_signature'],
            method_name=caller['method_name'],
            class_name=caller['class_name'],
            depth=depth,
            invocation_lines=caller.get('invocation_lines', []),
            db_method_id=caller.get('method_id')
        )
        node.call_type = caller.get('call_type', 'DIRECT')
        node.has_multiple_call_sites = caller.get('multi_call_sites', False)
        return node
