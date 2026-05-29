"""
SQL 增强分析服务
"""
from typing import Dict, List, Optional


class SQLAnalyzer:
    """SQL 分析服务 - 提取和展示 DAO 方法的 SQL 信息"""

    @staticmethod
    def extract_dao_methods(call_chains: List[Dict]) -> List[Dict]:
        """从调用链中提取所有 DAO 方法"""
        dao_methods = []
        for chain in call_chains:
            method_info = chain.get('method_info', {})
            dao_info = method_info.get('dao_info')
            if dao_info and dao_info.get('is_dao'):
                dao_methods.append({
                    'method_info': method_info,
                    'dao_info': dao_info,
                    'chain_data': chain
                })
        return dao_methods

    @staticmethod
    def analyze_performance(dao_info: Dict) -> Dict:
        """分析 SQL 性能"""
        return {
            'score': dao_info.get('performance_score', 0),
            'level': dao_info.get('performance_level', 'UNKNOWN'),
            'issues': dao_info.get('performance_issues', []),
            'has_issues': len(dao_info.get('performance_issues', [])) > 0
        }

    @staticmethod
    def trace_field_lineage(dao_info: Dict) -> Dict:
        """追踪字段血缘关系"""
        field_lineage = dao_info.get('field_lineage', {})
        return {
            'sources': field_lineage.get('sources', []),
            'consumers': field_lineage.get('consumers', []),
            'statistics': field_lineage.get('statistics', {}),
            'impact_analysis': field_lineage.get('impact_analysis')
        }

    @staticmethod
    def get_sql_summary(dao_methods: List[Dict]) -> Dict:
        """获取 SQL 方法汇总统计"""
        sql_type_count = {}
        performance_level_count = {}
        total_tables = set()

        for dao_method in dao_methods:
            dao_info = dao_method['dao_info']
            sql_type = dao_info.get('sql_type', 'UNKNOWN')
            sql_type_count[sql_type] = sql_type_count.get(sql_type, 0) + 1
            perf_level = dao_info.get('performance_level', 'UNKNOWN')
            performance_level_count[perf_level] = performance_level_count.get(perf_level, 0) + 1
            table_name = dao_info.get('table_name')
            if table_name:
                total_tables.add(table_name)

        return {
            'total_dao_methods': len(dao_methods),
            'sql_type_distribution': sql_type_count,
            'performance_level_distribution': performance_level_count,
            'tables_involved': list(total_tables),
            'total_tables': len(total_tables)
        }

    @staticmethod
    def filter_dao_methods(
        dao_methods: List[Dict],
        sql_types: Optional[List[str]] = None,
        performance_levels: Optional[List[str]] = None,
        min_score: int = 0
    ) -> List[Dict]:
        """过滤 DAO 方法"""
        filtered = []
        for dao_method in dao_methods:
            dao_info = dao_method['dao_info']
            sql_type = dao_info.get('sql_type', 'UNKNOWN')
            perf_level = dao_info.get('performance_level', 'UNKNOWN')
            perf_score = dao_info.get('performance_score', 0)
            if sql_types and sql_type not in sql_types:
                continue
            if performance_levels and perf_level not in performance_levels:
                continue
            if perf_score < min_score:
                continue
            filtered.append(dao_method)
        return filtered


sql_analyzer = SQLAnalyzer()
