"""
DAO 层分析器

负责分析 MyBatis Mapper/DAO 层方法调用，
提取 SQL 语句信息并生成调用链节点。

v3.2 新增：
- 识别 Mapper/DAO 层方法
- 获取对应的 SQL 信息
- 生成 SQL 级别的调用链节点
- 风险评估（DELETE=HIGH, UPDATE无WHERE=CRITICAL）

v4.0 增强：
- SQL性能分析集成
- 性能评分和优化建议
- 字段血缘追踪
"""

import re
import logging
from typing import Optional, Dict
from .models import CallChainNode, ChangeType
from .mapper_index import MapperMethodIndex
from .sql_performance_analyzer import SqlPerformanceAnalyzer
from .field_lineage_tracker import FieldLineageTracker

logger = logging.getLogger(__name__)


class DaoAnalyzer:
    """
    DAO 层分析器
    
    职责：
    1. 判断一个方法是否为 Mapper/DAO 层方法
    2. 获取该方法对应的 SQL 信息
    3. 生成 SQL 级别的调用链节点
    4. 评估 SQL 操作的风险等级
    """
    
    def __init__(self, mapper_index: MapperMethodIndex):
        """
        初始化 DAO 分析器
        
        Args:
            mapper_index: Mapper 方法索引
        """
        self.mapper_index = mapper_index
        # ✅ v4.0 新增：SQL性能分析器
        self.performance_analyzer = SqlPerformanceAnalyzer()
        # ✅ v4.0 新增：字段血缘追踪器
        self.lineage_tracker = FieldLineageTracker()
    
    def is_dao_method(self, package_class: str, method_name: str) -> bool:
        """
        判断是否为 DAO/Mapper 层方法
        
        Args:
            package_class: 完整类名
            method_name: 方法名
            
        Returns:
            True 如果是 DAO 方法
        """
        # 通过类名判断
        class_name = package_class.split('.')[-1]
        if class_name.endswith(('Mapper', 'Dao', 'Repository')):
            return True
        
        # 通过包名判断
        if '.mapper.' in package_class or '.dao.' in package_class:
            return True
        
        # 通过索引验证（最准确）
        sql_info = self.mapper_index.get_sql_by_java_method(package_class, method_name)
        return sql_info is not None
    
    def analyze(self, package_class: str, method_signature: str, 
                method_id: int = None) -> Optional[Dict]:
        """
        分析 DAO 方法，获取 SQL 信息
        
        Args:
            package_class: 完整类名
            method_signature: 方法签名，如 updateByPrimaryKeySelective(UmsMenu)
            method_id: 可选的方法ID
            
        Returns:
            SQL 信息字典，包含：
            - sql_type: SELECT/INSERT/UPDATE/DELETE
            - tables: 涉及的表名列表
            - sql_content: SQL 语句内容
            - risk_level: 风险等级 (LOW/MEDIUM/HIGH/CRITICAL)
            - warning: 警告信息
            - is_dynamic_sql: 是否为动态SQL
            - dynamic_conditions: 动态SQL条件列表
            - mapper_method: 完整的 Mapper 方法名
        """
        method_name = method_signature.split('(')[0]
        
        # 获取 SQL 信息
        sql_info = self.mapper_index.get_sql_by_java_method(package_class, method_name)
        
        if not sql_info:
            return None
        
        # 解析 SQL 信息
        tables = sql_info.get('tables', [])
        if isinstance(tables, str):
            import json
            try:
                tables = json.loads(tables)
            except:
                tables = []
        
        sql_type = sql_info.get('sql_type', 'UNKNOWN')
        sql_content = sql_info.get('sql_content', '')
        is_dynamic = sql_info.get('is_dynamic_sql', False)
        dynamic_conditions = sql_info.get('dynamic_conditions', [])
        
        # v3.3: 分析SQL特征（WHERE、LIMIT、预估行数）
        has_where = self._check_has_where(sql_content, sql_type)
        has_limit = self._check_has_limit(sql_content)
        estimated_rows = self._estimate_affected_rows(sql_content, sql_type, has_where, has_limit)
        
        # 风险评估
        risk_level, warning = self._assess_risk(sql_type, tables, sql_content, is_dynamic)
        
        # ✅ v4.0 新增：性能分析
        performance_report = self.performance_analyzer.analyze({
            'sql_type': sql_type,
            'sql_content': sql_content,
            'tables': tables,
            'mapper_method': f"{package_class}.{method_name}"
        })
        
        # ✅ v4.0 新增：字段血缘追踪
        field_lineage = self.lineage_tracker.track_from_sql({
            'sql_type': sql_type,
            'sql_content': sql_content,
            'tables': tables,
            'mapper_method': f"{package_class}.{method_name}"
        }, f"{package_class}.{method_name}")
        
        return {
            'method_signature': method_signature,
            'sql_type': sql_type,
            'tables': tables,
            'sql_content': sql_content,
            'risk_level': risk_level,
            'warning': warning,
            'is_dynamic_sql': is_dynamic,
            'dynamic_conditions': dynamic_conditions,
            'mapper_method': f"{package_class}.{method_name}",
            # v3.3: SQL特征分析
            'has_where': has_where,
            'has_limit': has_limit,
            'estimated_rows': estimated_rows,
            # ✅ v4.0 新增：性能分析结果
            'performance_score': performance_report.score,
            'performance_level': performance_report.level,
            'performance_issues': [issue.to_dict() for issue in performance_report.issues],
            # ✅ v4.0 新增：字段血缘信息
            'field_lineage': field_lineage.to_dict()
        }
    
    def create_sql_node(self, parent_node: CallChainNode, 
                       sql_info: Dict) -> CallChainNode:
        """
        创建 SQL 级别的调用链节点
        
        Args:
            parent_node: 父节点（Mapper 方法节点）
            sql_info: SQL 信息
            
        Returns:
            SQL 节点
        """
        sql_type = sql_info['sql_type']
        tables = sql_info.get('tables', [])
        table_str = ', '.join(tables) if tables else 'UNKNOWN'
        
        # 截断 SQL 内容用于显示
        sql_content = sql_info.get('sql_content', '')
        display_sql = sql_content[:100] + '...' if len(sql_content) > 100 else sql_content
        
        node_id = f"{parent_node.depth + 1}|SQL|{sql_type}:{table_str}"
        
        sql_node = CallChainNode(
            node_id=node_id,
            package_class=table_str,
            method_signature=display_sql,
            method_name=f"SQL:{sql_type}",
            class_name=table_str,
            depth=parent_node.depth + 1,
            invocation_lines=[],
            change_type=ChangeType.UNCHANGED.value,
            node_type='SQL'
        )
        
        # 附加 SQL 详细信息
        sql_node.sql_details = sql_info
        sql_node.dao_info = sql_info  # 也设置 dao_info，确保叶子节点在 JSON 序列化时携带 DAO 数据
        sql_node.is_leaf = True  # SQL 节点是叶子节点
        
        return sql_node
    
    def _assess_risk(self, sql_type: str, tables: list, sql_content: str, 
                    is_dynamic: bool = False) -> tuple:
        """
        评估 SQL 操作的风险等级
        
        Args:
            sql_type: SQL 类型
            tables: 涉及的表
            sql_content: SQL 内容
            is_dynamic: 是否为动态SQL
            
        Returns:
            (risk_level, warning) 元组
        """
        risk_level = 'LOW'
        warnings = []
        
        if sql_type == 'DELETE':
            risk_level = 'HIGH'
            warnings.append(f"⚠️ DELETE 操作会影响表: {', '.join(tables)}")
            
            # 检查是否有 WHERE 条件
            if 'WHERE' not in sql_content.upper():
                risk_level = 'CRITICAL'
                warnings.append("🔴 DELETE 操作缺少 WHERE 条件，可能删除全表数据！")
        
        elif sql_type == 'UPDATE':
            risk_level = 'MEDIUM'
            
            # 检查是否有 WHERE 条件
            if 'WHERE' not in sql_content.upper():
                risk_level = 'CRITICAL'
                warnings.append("🔴 UPDATE 操作缺少 WHERE 条件，可能更新全表！")
            else:
                warnings.append(f"⚠️ UPDATE 操作会影响表: {', '.join(tables)}")
                
                # 检查是否批量更新（CASE WHEN）
                if 'CASE' in sql_content.upper() and 'WHEN' in sql_content.upper():
                    warnings.append("ℹ️ 批量更新操作，需确认事务一致性")
        
        elif sql_type == 'INSERT':
            risk_level = 'LOW'
            warnings.append(f"📝 INSERT 操作会插入数据到表: {', '.join(tables)}")
            
            # 检查是否批量插入
            if '<foreach>' in sql_content or 'FOREACH' in sql_content:
                warnings.append("ℹ️ 批量插入操作")
        
        elif sql_type == 'SELECT':
            risk_level = 'LOW'
            
            # 检查是否有性能风险
            if 'WHERE' not in sql_content.upper() and 'LIMIT' not in sql_content.upper():
                risk_level = 'MEDIUM'
                warnings.append("⚠️ SELECT 操作缺少 WHERE 或 LIMIT，可能返回大量数据")
        
        # 动态SQL额外提示
        if is_dynamic:
            warnings.append("ℹ️ 动态SQL，实际执行的SQL取决于运行时条件")
        
        warning = '; '.join(warnings) if warnings else ''
        
        return risk_level, warning
    
    def _check_has_where(self, sql_content: str, sql_type: str) -> bool:
        """
        v3.3: 检查SQL是否有WHERE条件
        
        Args:
            sql_content: SQL语句内容
            sql_type: SQL类型
            
        Returns:
            bool: 是否有WHERE条件
        """
        if not sql_content:
            return False
        
        sql_upper = sql_content.upper()
        
        # SELECT/UPDATE/DELETE 需要检查 WHERE
        if sql_type in ('SELECT', 'UPDATE', 'DELETE'):
            return 'WHERE' in sql_upper
        
        # INSERT 不需要 WHERE
        return True
    
    def _check_has_limit(self, sql_content: str) -> bool:
        """
        v3.3: 检查SQL是否有LIMIT限制
        
        Args:
            sql_content: SQL语句内容
            
        Returns:
            bool: 是否有LIMIT
        """
        if not sql_content:
            return False
        
        sql_upper = sql_content.upper()
        return 'LIMIT' in sql_upper or 'ROWNUM' in sql_upper or 'FETCH FIRST' in sql_upper
    
    def _estimate_affected_rows(self, sql_content: str, sql_type: str, 
                                has_where: bool, has_limit: bool) -> str:
        """
        v3.3: 预估受影响的行数
        
        Args:
            sql_content: SQL语句内容
            sql_type: SQL类型
            has_where: 是否有WHERE条件
            has_limit: 是否有LIMIT限制
            
        Returns:
            str: ONE/MANY/ALL/UNKNOWN
        """
        if not sql_content:
            return 'UNKNOWN'
        
        sql_upper = sql_content.upper()
        
        # DELETE/UPDATE 无 WHERE → 可能影响全表
        if sql_type in ('DELETE', 'UPDATE') and not has_where:
            return 'ALL'
        
        # 有 LIMIT → 影响行数可控
        if has_limit:
            # 尝试提取 LIMIT 值
            limit_match = re.search(r'LIMIT\s+(\d+)', sql_upper)
            if limit_match:
                limit_val = int(limit_match.group(1))
                if limit_val == 1:
                    return 'ONE'
                elif limit_val <= 10:
                    return 'FEW'
                else:
                    return 'MANY'
            return 'FEW'
        
        # SELECT 有 WHERE → 通常影响少量行
        if sql_type == 'SELECT' and has_where:
            # 检查是否有主键查询
            if re.search(r'WHERE\s+\w+\s*=\s*#\{', sql_content):
                return 'ONE'
            return 'MANY'
        
        # INSERT → 通常插入一行（除非批量）
        if sql_type == 'INSERT':
            if '<foreach>' in sql_content or 'FOREACH' in sql_content:
                return 'MANY'
            return 'ONE'
        
        return 'UNKNOWN'
