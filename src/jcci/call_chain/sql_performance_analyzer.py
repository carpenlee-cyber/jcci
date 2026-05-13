"""
SQL性能分析器

自动检测SQL语句的性能问题，包括：
- 全表扫描
- SELECT *
- LIKE通配符
- 嵌套子查询
- OR条件过多
- N+1查询问题

v4.0 新增功能
"""

import re
import logging
from typing import List, Dict, Optional
from dataclasses import dataclass, field
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


@dataclass
class PerformanceIssue:
    """性能问题"""
    rule: str
    severity: str  # HIGH/MEDIUM/LOW
    message: str
    suggestion: str
    affected_tables: List[str] = field(default_factory=list)
    
    def to_dict(self) -> dict:
        return {
            'rule': self.rule,
            'severity': self.severity,
            'message': self.message,
            'suggestion': self.suggestion,
            'affected_tables': self.affected_tables
        }


@dataclass
class PerformanceReport:
    """性能报告"""
    issues: List[PerformanceIssue] = field(default_factory=list)
    score: int = 100  # 性能评分 (0-100, 越高越好)
    
    def add_issues(self, issues: List[PerformanceIssue]):
        self.issues.extend(issues)
    
    def calculate_score(self):
        """计算性能评分"""
        penalty = 0
        for issue in self.issues:
            if issue.severity == 'HIGH':
                penalty += 20
            elif issue.severity == 'MEDIUM':
                penalty += 10
            else:
                penalty += 5
        
        self.score = max(0, 100 - penalty)
    
    @property
    def level(self) -> str:
        """性能等级"""
        if self.score >= 90:
            return "EXCELLENT"
        elif self.score >= 70:
            return "GOOD"
        elif self.score >= 50:
            return "FAIR"
        else:
            return "POOR"
    
    def to_dict(self) -> dict:
        return {
            'score': self.score,
            'level': self.level,
            'issues_count': len(self.issues),
            'issues': [issue.to_dict() for issue in self.issues]
        }


class PerformanceRule(ABC):
    """性能规则基类"""
    
    @abstractmethod
    def check(self, sql_info: dict) -> List[PerformanceIssue]:
        """检查SQL是否存在性能问题"""
        pass
    
    @property
    @abstractmethod
    def rule_name(self) -> str:
        """规则名称"""
        pass
    
    @property
    @abstractmethod
    def severity(self) -> str:
        """严重程度: HIGH/MEDIUM/LOW"""
        pass


class FullTableScanRule(PerformanceRule):
    """全表扫描检测规则"""
    
    @property
    def rule_name(self):
        return "FULL_TABLE_SCAN"
    
    @property
    def severity(self):
        return "HIGH"
    
    def check(self, sql_info: dict) -> List[PerformanceIssue]:
        issues = []
        sql = sql_info['sql_content'].upper()
        
        # 检测SELECT无WHERE条件
        if sql_info['sql_type'] == 'SELECT':
            if 'WHERE' not in sql and 'LIMIT' not in sql:
                issues.append(PerformanceIssue(
                    rule=self.rule_name,
                    severity=self.severity,
                    message=f"⚠️ 全表扫描: SELECT语句缺少WHERE或LIMIT条件",
                    suggestion="添加WHERE条件或LIMIT子句限制返回行数",
                    affected_tables=sql_info.get('tables', [])
                ))
        
        return issues


class SelectStarRule(PerformanceRule):
    """SELECT * 检测规则"""
    
    @property
    def rule_name(self):
        return "SELECT_STAR"
    
    @property
    def severity(self):
        return "MEDIUM"
    
    def check(self, sql_info: dict) -> List[PerformanceIssue]:
        issues = []
        sql = sql_info['sql_content']
        
        # 检测 SELECT *
        if re.search(r'SELECT\s+\*', sql, re.IGNORECASE):
            issues.append(PerformanceIssue(
                rule=self.rule_name,
                severity=self.severity,
                message=f"⚠️ 使用SELECT *: 建议明确指定需要的列",
                suggestion="替换为具体的列名，如 SELECT id, name FROM ...",
                affected_tables=sql_info.get('tables', [])
            ))
        
        return issues


class LikeWildcardRule(PerformanceRule):
    """LIKE通配符检测规则"""
    
    @property
    def rule_name(self):
        return "LIKE_WILDCARD"
    
    @property
    def severity(self):
        return "HIGH"
    
    def check(self, sql_info: dict) -> List[PerformanceIssue]:
        issues = []
        sql = sql_info['sql_content']
        
        # 检测 LIKE '%...%'
        if re.search(r"LIKE\s+'%", sql, re.IGNORECASE):
            issues.append(PerformanceIssue(
                rule=self.rule_name,
                severity=self.severity,
                message=f"⚠️ LIKE前缀通配符: 无法使用索引，性能差",
                suggestion="考虑使用全文索引或调整查询逻辑",
                affected_tables=sql_info.get('tables', [])
            ))
        
        return issues


class NestedSubqueryRule(PerformanceRule):
    """嵌套子查询检测规则"""
    
    @property
    def rule_name(self):
        return "NESTED_SUBQUERY"
    
    @property
    def severity(self):
        return "MEDIUM"
    
    def check(self, sql_info: dict) -> List[PerformanceIssue]:
        issues = []
        sql = sql_info['sql_content'].upper()
        
        # 检测嵌套SELECT
        select_count = sql.count('SELECT')
        if select_count > 1:
            issues.append(PerformanceIssue(
                rule=self.rule_name,
                severity=self.severity,
                message=f"⚠️ 嵌套子查询: 检测到{select_count}层SELECT嵌套",
                suggestion="考虑使用JOIN替代子查询，提升性能",
                affected_tables=sql_info.get('tables', [])
            ))
        
        return issues


class OrConditionRule(PerformanceRule):
    """OR条件过多检测规则"""
    
    @property
    def rule_name(self):
        return "OR_CONDITION"
    
    @property
    def severity(self):
        return "LOW"
    
    def check(self, sql_info: dict) -> List[PerformanceIssue]:
        issues = []
        sql = sql_info['sql_content'].upper()
        
        # 统计OR数量
        or_count = sql.count(' OR ')
        if or_count >= 3:
            issues.append(PerformanceIssue(
                rule=self.rule_name,
                severity=self.severity,
                message=f"⚠️ OR条件过多: 检测到{or_count}个OR条件",
                suggestion="考虑使用IN子句替代多个OR条件",
                affected_tables=sql_info.get('tables', [])
            ))
        
        return issues


class SqlPerformanceAnalyzer:
    """
    SQL性能分析器
    
    职责：
    1. 应用多个性能规则检测SQL问题
    2. 生成性能报告和优化建议
    3. 检测N+1查询问题
    """
    
    def __init__(self):
        """初始化性能分析器"""
        self.rules = self._load_rules()
        logger.info(f"SQL Performance Analyzer initialized with {len(self.rules)} rules")
    
    def _load_rules(self) -> List[PerformanceRule]:
        """加载所有性能规则"""
        return [
            FullTableScanRule(),
            SelectStarRule(),
            LikeWildcardRule(),
            NestedSubqueryRule(),
            OrConditionRule(),
        ]
    
    def analyze(self, sql_info: dict) -> PerformanceReport:
        """
        分析SQL语句的性能问题
        
        Args:
            sql_info: SQL信息字典
                {
                    'sql_type': 'SELECT',
                    'sql_content': 'SELECT * FROM ...',
                    'tables': ['ums_menu'],
                    'mapper_method': 'com.test.Mapper.select'
                }
        
        Returns:
            PerformanceReport: 性能报告
        """
        report = PerformanceReport()
        
        # 应用所有规则
        for rule in self.rules:
            try:
                issues = rule.check(sql_info)
                report.add_issues(issues)
            except Exception as e:
                logger.warning(f"Rule {rule.rule_name} failed: {e}")
        
        # 计算风险评分
        report.calculate_score()
        
        logger.debug(f"Performance analysis: score={report.score}, "
                    f"level={report.level}, issues={len(report.issues)}")
        
        return report
    
    def detect_n_plus_one(self, call_chain_node) -> List[dict]:
        """
        检测N+1查询问题
        
        Args:
            call_chain_node: 调用链节点（需要遍历子树）
        
        Returns:
            N+1问题列表
        """
        issues = []
        self._traverse_for_n_plus_one(call_chain_node, [], issues)
        return issues
    
    def _traverse_for_n_plus_one(self, node, path: list, issues: list):
        """
        遍历调用链检测N+1查询
        
        简化版检测：识别Mapper方法在循环中被多次调用
        """
        current_path = path + [node]
        
        # 检测当前节点是否为循环结构（简化判断）
        # TODO: 更精确的循环检测需要解析Java代码
        is_loop = self._is_likely_loop(node)
        
        if is_loop:
            # 检查循环内的子节点是否有Mapper调用
            mapper_calls = []
            for child in getattr(node, 'children', []):
                if self._is_mapper_call(child):
                    mapper_calls.append(child)
            
            if len(mapper_calls) > 0:
                issues.append({
                    'type': 'N_PLUS_ONE',
                    'severity': 'HIGH',
                    'message': f"⚠️ N+1查询: 循环内执行{len(mapper_calls)}次数据库查询",
                    'suggestion': "使用批量查询替代循环查询，如使用 <foreach> 标签",
                    'loop_node': node.node_id,
                    'mapper_calls': [m.node_id for m in mapper_calls]
                })
        
        # 递归遍历子节点
        for child in getattr(node, 'children', []):
            self._traverse_for_n_plus_one(child, current_path, issues)
    
    def _is_likely_loop(self, node) -> bool:
        """
        判断节点是否可能是循环结构
        
        简化判断：根据方法名启发式判断
        """
        method_name = getattr(node, 'method_name', '').lower()
        
        # 常见的循环相关方法名
        loop_keywords = ['foreach', 'for', 'loop', 'iterate', 'batch']
        
        return any(keyword in method_name for keyword in loop_keywords)
    
    def _is_mapper_call(self, node) -> bool:
        """判断节点是否为Mapper调用"""
        class_name = getattr(node, 'class_name', '')
        return class_name.endswith(('Mapper', 'Dao', 'Repository'))
