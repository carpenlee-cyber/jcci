"""
类层次索引（Class Hierarchy Index）

支持 CHA（Class Hierarchy Analysis）解析接口和抽象类的实现类映射。
解决静态分析中接口调用向上分析时的"假阴性"问题。
"""

import json
import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class ClassHierarchyIndex:
    """
    类层次索引：支持 CHA（Class Hierarchy Analysis）
    解决接口/实现类方法调用关系缺失问题
    """
    
    def __init__(self, db_connection, project_ids: List[int]):
        """
        初始化类层次索引
        
        Args:
            db_connection: 数据库连接对象
            project_ids: 项目ID列表（通常包含基线和增量）
        """
        self._class_hierarchy: Dict[str, dict] = {}
        self._interface_impls: Dict[str, List[str]] = {}
        self._method_override_map: Dict[str, List[dict]] = {}
        self._build_hierarchy(db_connection, project_ids)
        logger.info(f"Class hierarchy index built: {len(self._class_hierarchy)} classes, "
                   f"{len(self._interface_impls)} interfaces")
    
    def _build_hierarchy(self, db_connection, project_ids: List[int]):
        """
        从数据库加载类层次信息
        
        假设数据库表结构：
        - class_table: class_id, project_id, package_name, class_name, super_class, interfaces(JSON)
        - method_table: method_id, class_id, method_name, parameters, is_abstract
        """
        cursor = db_connection.cursor()
        
        placeholders = ','.join(['?'] * len(project_ids))
        query = f"""
            SELECT c.class_id, c.package_name, c.class_name, c.super_class, c.interfaces 
            FROM class c
            WHERE c.project_id IN ({placeholders})
        """
        
        cursor.execute(query, project_ids)
        rows = cursor.fetchall()
        
        for row in rows:
            if isinstance(row, dict):
                class_id = row['class_id']
                package_name = row['package_name']
                class_name = row['class_name']
                super_class = row.get('super_class')
                interfaces_json = row.get('interfaces')
            else:
                class_id, package_name, class_name, super_class, interfaces_json = row
            
            package_class = f"{package_name}.{class_name}"
            interfaces = json.loads(interfaces_json) if interfaces_json else []
            
            self._class_hierarchy[package_class] = {
                'class_id': class_id,
                'super_class': super_class,
                'interfaces': interfaces,
                'methods': []
            }
            
            for iface in interfaces:
                if iface not in self._interface_impls:
                    self._interface_impls[iface] = []
                if package_class not in self._interface_impls[iface]:
                    self._interface_impls[iface].append(package_class)
        
        self._load_methods(db_connection, project_ids)
        self._build_override_resolution()
    
    def _load_methods(self, db_connection, project_ids: List[int]):
        """加载所有方法信息"""
        cursor = db_connection.cursor()
        
        placeholders = ','.join(['?'] * len(project_ids))
        query = f"""
            SELECT m.method_id, c.package_name, c.class_name, 
                   m.method_name, m.parameters, m.is_abstract
            FROM methods m
            JOIN class c ON m.class_id = c.class_id
            WHERE c.project_id IN ({placeholders})
        """
        
        cursor.execute(query, project_ids)
        rows = cursor.fetchall()
        
        for row in rows:
            if isinstance(row, dict):
                method_id = row['method_id']
                package_name = row['package_name']
                class_name = row['class_name']
                method_name = row['method_name']
                parameters = row['parameters']
                is_abstract = row.get('is_abstract', False)
            else:
                method_id, package_name, class_name, method_name, parameters, is_abstract = row
            
            package_class = f"{package_name}.{class_name}"
            
            method_info = {
                'method_id': method_id,
                'package_class': package_class,
                'method_name': method_name,
                'parameters': parameters,
                'is_abstract': is_abstract
            }
            
            if package_class in self._class_hierarchy:
                self._class_hierarchy[package_class]['methods'].append(method_info)
                
                sig_key = self._build_signature_key(method_name, parameters)
                method_key = f"{package_class}|{sig_key}"
                
                if self._is_interface_or_abstract(package_class):
                    if method_key not in self._method_override_map:
                        self._method_override_map[method_key] = []
                    self._method_override_map[method_key].append(method_info)
    
    def _build_override_resolution(self):
        """
        CHA 核心：为每个接口/抽象类方法，找到所有实现类中的重写方法
        """
        for method_key, abstract_methods in list(self._method_override_map.items()):
            package_class, sig_key = method_key.rsplit('|', 1)
            
            impl_classes = self._get_all_implementations(package_class)
            
            for impl_class in impl_classes:
                for method in self._class_hierarchy.get(impl_class, {}).get('methods', []):
                    impl_sig_key = self._build_signature_key(
                        method['method_name'], 
                        method['parameters']
                    )
                    if impl_sig_key == sig_key:
                        existing_ids = [m['method_id'] for m in self._method_override_map[method_key]]
                        if method['method_id'] not in existing_ids:
                            self._method_override_map[method_key].append(method)
    
    def _get_all_implementations(self, class_name: str) -> List[str]:
        """获取一个接口/抽象类的所有实现类（递归）"""
        result = []
        direct_impls = self._interface_impls.get(class_name, [])
        result.extend(direct_impls)
        
        for impl in direct_impls:
            result.extend(self._get_all_implementations(impl))
        
        return list(set(result))
    
    def resolve_interface_call(self, package_class: str, method_signature: str) -> List[dict]:
        """
        CHA 解析：给定一个接口/抽象类方法，返回所有可能的实现类方法
        
        Args:
            package_class: 接口或抽象类的完整类名
            method_signature: 方法签名，如 "list(Long,Integer)"
        
        Returns:
            List[dict]: 实现类方法列表
        """
        sig_key = self._build_signature_key_from_sig(method_signature)
        method_key = f"{package_class}|{sig_key}"
        
        return self._method_override_map.get(method_key, [])
    
    def is_interface_or_abstract_class(self, package_class: str) -> bool:
        """判断一个类是否为接口或抽象类"""
        return self._is_interface_or_abstract(package_class)
    
    def get_all_concrete_methods(self, package_class: str, method_signature: str) -> List[dict]:
        """
        获取一个方法的所有具体实现（包括自身和子类重写）
        用于向上分析时扩展查询范围
        """
        if not self.is_interface_or_abstract_class(package_class):
            return [{'package_class': package_class, 'method_signature': method_signature}]
        
        return self.resolve_interface_call(package_class, method_signature)
    
    @staticmethod
    def _build_signature_key(method_name: str, parameters: str) -> str:
        """从数据库参数格式构建签名键"""
        try:
            params = json.loads(parameters) if isinstance(parameters, str) else parameters
            if isinstance(params, list):
                param_types = [p.get('parameter_type', '') for p in params]
                return f"{method_name}({','.join(param_types)})"
        except:
            pass
        return f"{method_name}()"
    
    @staticmethod
    def _build_signature_key_from_sig(method_signature: str) -> str:
        """从方法签名字符串构建签名键"""
        return method_signature
    
    def _is_interface_or_abstract(self, package_class: str) -> bool:
        """判断类是否为接口或抽象类"""
        class_info = self._class_hierarchy.get(package_class, {})
        interfaces = class_info.get('interfaces', [])
        
        if interfaces:
            return True
        
        class_name = package_class.split('.')[-1]
        if class_name.endswith(('Service', 'Mapper', 'Dao', 'Repository')):
            return True
        
        return False
