"""
字段血缘追踪器

追踪MyBatis SQL中字段的来源和使用情况，支持：
- 字段级依赖关系分析
- 数据来源追溯
- 数据消费者追踪
- 变更影响范围评估

v4.0 新增功能
"""

import re
import logging
from typing import List, Dict, Optional, Tuple, Set
from dataclasses import dataclass, field
from collections import defaultdict

logger = logging.getLogger(__name__)


@dataclass
class FieldInfo:
    """字段信息"""
    table: str
    column: str
    alias: Optional[str] = None
    
    @property
    def full_name(self) -> str:
        """完整字段名"""
        return f"{self.table}.{self.column}"
    
    @property
    def display_name(self) -> str:
        """显示名称（带别名）"""
        if self.alias:
            return f"{self.full_name} AS {self.alias}"
        return self.full_name


@dataclass
class DataSource:
    """数据来源"""
    source_type: str  # USER_INPUT/API/CONFIG/OTHER_TABLE
    path: str  # 调用路径
    method: str  # Mapper方法
    sql_type: str  # INSERT/UPDATE
    
    def to_dict(self) -> dict:
        return {
            'source_type': self.source_type,
            'path': self.path,
            'method': self.method,
            'sql_type': self.sql_type
        }


@dataclass
class DataConsumer:
    """数据消费者"""
    consumer_type: str  # API/REPORT/SERVICE/OTHER_SQL
    path: str  # 使用路径
    method: str  # Mapper方法
    sql_type: str  # SELECT
    
    def to_dict(self) -> dict:
        return {
            'consumer_type': self.consumer_type,
            'path': self.path,
            'method': self.method,
            'sql_type': self.sql_type
        }


@dataclass
class FieldLineage:
    """字段血缘信息"""
    reads: List[Tuple[str, str, str]] = field(default_factory=list)  # (table, column, method)
    writes: List[Tuple[str, str, str]] = field(default_factory=list)
    
    def add_read(self, table: str, column: str, method: str):
        self.reads.append((table, column, method))
    
    def add_write(self, table: str, column: str, method: str):
        self.writes.append((table, column, method))
    
    def to_dict(self) -> dict:
        return {
            'reads_count': len(self.reads),
            'writes_count': len(self.writes),
            'reads': [{'table': t, 'column': c, 'method': m} for t, c, m in self.reads],
            'writes': [{'table': t, 'column': c, 'method': m} for t, c, m in self.writes]
        }


@dataclass
class ImpactAnalysis:
    """影响分析报告"""
    api_count: int = 0
    report_count: int = 0
    service_count: int = 0
    other_count: int = 0
    risk_level: str = "LOW"  # HIGH/MEDIUM/LOW
    consumers: List[DataConsumer] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)
    
    @property
    def total_impact(self) -> int:
        return self.api_count + self.report_count + self.service_count + self.other_count
    
    def to_dict(self) -> dict:
        return {
            'total_impact': self.total_impact,
            'api_count': self.api_count,
            'report_count': self.report_count,
            'service_count': self.service_count,
            'other_count': self.other_count,
            'risk_level': self.risk_level,
            'consumers_count': len(self.consumers),
            'recommendations': self.recommendations
        }


class FieldLineageTracker:
    """
    字段血缘追踪器
    
    职责：
    1. 从SQL语句中提取字段信息
    2. 构建字段依赖图
    3. 追踪字段来源和消费者
    4. 分析字段变更的影响范围
    """
    
    def __init__(self):
        """初始化字段血缘追踪器"""
        # 字段依赖图: {field_key: {'sources': [], 'consumers': []}}
        self.lineage_graph: Dict[str, Dict] = defaultdict(lambda: {
            'sources': [],
            'consumers': []
        })
        
        logger.info("Field Lineage Tracker initialized")
    
    def track_from_sql(self, sql_info: dict, mapper_method: str) -> FieldLineage:
        """
        从SQL语句追踪字段血缘
        
        Args:
            sql_info: SQL信息字典
                {
                    'sql_type': 'SELECT',
                    'sql_content': 'SELECT id, name FROM user WHERE ...',
                    'tables': ['user'],
                    'mapper_method': 'com.test.UserMapper.select'
                }
            mapper_method: Mapper方法名
        
        Returns:
            FieldLineage: 字段血缘信息
        """
        lineage = FieldLineage()
        
        # 解析SQL提取字段
        fields = self._extract_fields_from_sql(sql_info)
        
        if not fields:
            logger.debug(f"No fields extracted from SQL: {mapper_method}")
            return lineage
        
        for field_info in fields:
            if sql_info['sql_type'] in ['INSERT', 'UPDATE']:
                # 写入操作
                lineage.add_write(field_info.table, field_info.column, mapper_method)
                self._add_source(field_info, mapper_method, sql_info['sql_type'])
                
            elif sql_info['sql_type'] == 'SELECT':
                # 读取操作
                lineage.add_read(field_info.table, field_info.column, mapper_method)
                self._add_consumer(field_info, mapper_method, sql_info['sql_type'])
            
            logger.debug(f"Tracked field: {field_info.display_name} ({sql_info['sql_type']})")
        
        return lineage
    
    def get_field_sources(self, table: str, column: str) -> List[DataSource]:
        """
        获取字段的来源
        
        Args:
            table: 表名
            column: 列名
        
        Returns:
            数据来源列表
        """
        field_key = f"{table}.{column}"
        graph_data = self.lineage_graph.get(field_key, {})
        
        sources = []
        for source_data in graph_data.get('sources', []):
            sources.append(DataSource(
                source_type=source_data['source_type'],
                path=source_data['path'],
                method=source_data['method'],
                sql_type=source_data['sql_type']
            ))
        
        return sources
    
    def get_field_consumers(self, table: str, column: str) -> List[DataConsumer]:
        """
        获取字段的使用者
        
        Args:
            table: 表名
            column: 列名
        
        Returns:
            数据使用者列表
        """
        field_key = f"{table}.{column}"
        graph_data = self.lineage_graph.get(field_key, {})
        
        consumers = []
        for consumer_data in graph_data.get('consumers', []):
            consumers.append(DataConsumer(
                consumer_type=consumer_data['consumer_type'],
                path=consumer_data['path'],
                method=consumer_data['method'],
                sql_type=consumer_data['sql_type']
            ))
        
        return consumers
    
    def analyze_impact(self, table: str, column: str) -> ImpactAnalysis:
        """
        分析字段变更的影响范围
        
        Args:
            table: 表名
            column: 列名
        
        Returns:
            ImpactAnalysis: 影响分析报告
        """
        impact = ImpactAnalysis()
        
        # 获取所有消费者
        consumers = self.get_field_consumers(table, column)
        impact.consumers = consumers
        
        # 分类统计
        for consumer in consumers:
            if consumer.consumer_type == 'API':
                impact.api_count += 1
            elif consumer.consumer_type == 'REPORT':
                impact.report_count += 1
            elif consumer.consumer_type == 'SERVICE':
                impact.service_count += 1
            else:
                impact.other_count += 1
        
        # 风险评估
        total = impact.total_impact
        if total > 10:
            impact.risk_level = "HIGH"
            impact.recommendations.append("⚠️ 高风险：影响范围广，建议全面回归测试")
        elif total > 5:
            impact.risk_level = "MEDIUM"
            impact.recommendations.append("ℹ️ 中等风险：影响部分接口，建议重点测试")
        else:
            impact.risk_level = "LOW"
            impact.recommendations.append("✅ 低风险：影响范围小")
        
        # 添加具体建议
        if impact.api_count > 0:
            impact.recommendations.append(f"• 需要测试 {impact.api_count} 个API接口")
        if impact.report_count > 0:
            impact.recommendations.append(f"• 需要验证 {impact.report_count} 个报表")
        
        logger.info(f"Impact analysis for {table}.{column}: "
                   f"risk={impact.risk_level}, total_impact={total}")
        
        return impact
    
    def _extract_fields_from_sql(self, sql_info: dict) -> List[FieldInfo]:
        """
        从SQL中提取字段信息
        
        支持：
        - SELECT col1, col2 FROM table
        - INSERT INTO table (col1, col2) VALUES (...)
        - UPDATE table SET col1 = ?, col2 = ?
        """
        fields = []
        sql = sql_info['sql_content']
        sql_type = sql_info['sql_type']
        tables = sql_info.get('tables', [])
        
        if not tables:
            return fields
        
        primary_table = tables[0]  # 主表
        
        try:
            if sql_type == 'SELECT':
                fields = self._extract_select_fields(sql, primary_table)
            elif sql_type == 'INSERT':
                fields = self._extract_insert_fields(sql, primary_table)
            elif sql_type == 'UPDATE':
                fields = self._extract_update_fields(sql, primary_table)
        except Exception as e:
            logger.warning(f"Failed to extract fields from SQL: {e}")
        
        return fields
    
    def _extract_select_fields(self, sql: str, table: str) -> List[FieldInfo]:
        """提取SELECT语句的字段"""
        fields = []
        
        # 匹配 SELECT ... FROM
        select_match = re.search(r'SELECT\s+(.*?)\s+FROM', sql, re.IGNORECASE | re.DOTALL)
        if not select_match:
            return fields
        
        select_clause = select_match.group(1).strip()
        
        # 排除 SELECT *
        if select_clause == '*':
            # SELECT * 表示所有字段，这里不具体列出
            return fields
        
        # 分割字段
        for field_str in select_clause.split(','):
            field_str = field_str.strip()
            if not field_str:
                continue
            
            # 处理函数调用: COUNT(*), MAX(id) 等
            if '(' in field_str:
                continue
            
            # 处理别名: col AS alias 或 col alias
            alias = None
            col = field_str
            
            # 尝试匹配 AS 别名
            as_match = re.match(r'(\w+)(?:\s+AS\s+(\w+))?', field_str, re.IGNORECASE)
            if as_match:
                col = as_match.group(1)
                alias = as_match.group(2)
            else:
                # 简单别名: col alias
                parts = field_str.split()
                if len(parts) == 2 and parts[1].upper() not in ['FROM', 'WHERE', 'JOIN']:
                    col = parts[0]
                    alias = parts[1]
            
            fields.append(FieldInfo(table, col, alias))
        
        return fields
    
    def _extract_insert_fields(self, sql: str, table: str) -> List[FieldInfo]:
        """提取INSERT语句的字段"""
        fields = []
        
        # 匹配 INSERT INTO table (col1, col2, ...)
        insert_match = re.search(r'INSERT\s+INTO\s+\w+\s*\((.*?)\)', sql, re.IGNORECASE)
        if not insert_match:
            return fields
        
        columns_str = insert_match.group(1)
        
        for col in columns_str.split(','):
            col = col.strip().strip('`"\'')
            if col:
                fields.append(FieldInfo(table, col))
        
        return fields
    
    def _extract_update_fields(self, sql: str, table: str) -> List[FieldInfo]:
        """提取UPDATE语句的字段"""
        fields = []
        
        # 匹配 UPDATE table SET col1 = ?, col2 = ?
        update_match = re.search(r'UPDATE\s+\w+\s+SET\s+(.*?)\s+WHERE', sql, re.IGNORECASE | re.DOTALL)
        if not update_match:
            # 可能没有WHERE子句
            update_match = re.search(r'UPDATE\s+\w+\s+SET\s+(.*)', sql, re.IGNORECASE | re.DOTALL)
        
        if not update_match:
            return fields
        
        set_clause = update_match.group(1)
        
        for assignment in set_clause.split(','):
            assignment = assignment.strip()
            if '=' in assignment:
                col = assignment.split('=')[0].strip().strip('`"\'')
                if col:
                    fields.append(FieldInfo(table, col))
        
        return fields
    
    def _add_source(self, field_info: FieldInfo, method: str, sql_type: str):
        """添加数据来源"""
        field_key = field_info.full_name
        
        # 推断来源类型
        source_type = self._infer_source_type(method)
        
        self.lineage_graph[field_key]['sources'].append({
            'source_type': source_type,
            'path': f"{method} ({sql_type})",
            'method': method,
            'sql_type': sql_type
        })
    
    def _add_consumer(self, field_info: FieldInfo, method: str, sql_type: str):
        """添加数据消费者"""
        field_key = field_info.full_name
        
        # 推断消费者类型
        consumer_type = self._infer_consumer_type(method)
        
        self.lineage_graph[field_key]['consumers'].append({
            'consumer_type': consumer_type,
            'path': f"{method} ({sql_type})",
            'method': method,
            'sql_type': sql_type
        })
    
    def _infer_source_type(self, method: str) -> str:
        """推断数据来源类型"""
        method_lower = method.lower()
        
        if 'controller' in method_lower:
            return 'USER_INPUT'
        elif 'config' in method_lower:
            return 'CONFIG'
        else:
            return 'OTHER_TABLE'
    
    def _infer_consumer_type(self, method: str) -> str:
        """推断数据消费者类型"""
        method_lower = method.lower()
        
        if 'controller' in method_lower or 'api' in method_lower:
            return 'API'
        elif 'report' in method_lower or 'export' in method_lower:
            return 'REPORT'
        elif 'service' in method_lower:
            return 'SERVICE'
        else:
            return 'OTHER_SQL'
    
    def get_statistics(self) -> dict:
        """
        获取血缘追踪统计信息
        
        Returns:
            统计信息字典
        """
        total_fields = len(self.lineage_graph)
        fields_with_sources = sum(1 for data in self.lineage_graph.values() if data['sources'])
        fields_with_consumers = sum(1 for data in self.lineage_graph.values() if data['consumers'])
        
        return {
            'total_fields_tracked': total_fields,
            'fields_with_sources': fields_with_sources,
            'fields_with_consumers': fields_with_consumers,
            'average_sources_per_field': fields_with_sources / max(1, total_fields),
            'average_consumers_per_field': fields_with_consumers / max(1, total_fields)
        }
