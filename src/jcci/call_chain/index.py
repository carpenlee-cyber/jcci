"""
统一方法索引

负责加载基线和增量数据，构建统一的方法索引。
支持基于基线+增量合并数据的快速查询。
"""

import json
import logging
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class UnifiedMethodIndex:
    """
    统一方法索引
    
    核心职责：
    1. 批量预加载基线和增量的所有方法到内存
    2. 版本合并：增量覆盖基线，过滤删除的方法
    3. 快速查询：支持精确重载匹配
    
    Attributes:
        db_path: 数据库路径
        project_id: 项目ID（0=基线，>0=增量）
        commit_old: 旧版本commit
        commit_new: 新版本commit
        baseline_index: 基线索引 {(package_class, method_name): [methods]}
        incremental_index: 增量子引 {(package_class, method_name): [methods]}
        _unified_index: 统一索引 {(package_class, method_name): [methods]}
    """
    
    def __init__(self, db_path: str, commit_old: str, commit_new: str, db_connection=None):
        """
        初始化统一方法索引
        
        Args:
            db_path: SQLite数据库路径（基线数据库）
            commit_old: 旧版本commit hash
            commit_new: 新版本commit hash
            db_connection: 可选的数据库连接（用于测试）
        """
        self.db_path = db_path
        self.commit_old = commit_old[:7] if len(commit_old) > 7 else commit_old
        self.commit_new = commit_new[:7] if len(commit_new) > 7 else commit_new
        
        # 如果提供了数据库连接，使用它；否则创建新连接
        if db_connection:
            self.db = db_connection
        else:
            from jcci.database import SqliteHelper
            self.db = SqliteHelper(db_path)
        
        # 自动查询增量 project_id
        self._query_project_id()
        
        self.baseline_index: Dict[Tuple[str, str], List[dict]] = {}
        self.incremental_index: Dict[Tuple[str, str], List[dict]] = {}
        self._unified_index: Dict[Tuple[str, str], List[dict]] = {}
        
        # 构建索引
        self._load_and_build_index()
    
    def _query_project_id(self):
        """从 project 表查询增量 project_id"""
        # 使用字符串格式化，因为 SqliteHelper.select_data 不支持参数化查询
        sql = f'''
            SELECT project_id FROM project 
            WHERE commit_or_branch_new = "{self.commit_new}" 
              AND commit_or_branch_old = "{self.commit_old}"
            ORDER BY project_id DESC 
            LIMIT 1
        '''
        
        result = self.db.select_data(sql)
        row = result[0] if result else None
        
        if not row:
            raise ValueError(
                f"No project found for commit range {self.commit_old}..{self.commit_new}"
            )
        
        self.project_id = row['project_id'] if isinstance(row, dict) else row[0]
        logger.info(f"Found incremental project_id={self.project_id} for {self.commit_old}..{self.commit_new}")
        
        # 基线 project_id 固定为 0
        self.baseline_project_id = 0
    
    def _load_and_build_index(self):
        """加载数据并构建统一索引"""
        logger.info("Building unified method index...")
        
        # Step 1: 加载基线数据（project_id=0）
        self._load_project_methods(project_id=self.baseline_project_id, commit=self.commit_old, is_baseline=True)
        
        # Step 2: 加载增量数据（project_id > 0）
        if self.project_id > 0:
            self._load_project_methods(project_id=self.project_id, commit=self.commit_new, is_baseline=False)
        
        # Step 3: 构建统一索引
        self._build_unified_index()
        
        logger.info(f"Unified index built: {len(self._unified_index)} unique methods")
    
    def _load_project_methods(self, project_id: int, commit: str, is_baseline: bool):
        """
        从数据库加载指定项目的方法
        
        Args:
            project_id: 项目ID
            commit: commit hash
            is_baseline: 是否为基线数据
        """
        logger.info(f"Loading methods for project_id={project_id}, commit={commit}")
        
        # 查询所有方法（包括 change_type）
        sql = '''
            SELECT m.method_id, c.package_name, c.class_name, 
                   m.method_name, m.parameters, m.method_invocation_map,
                   m.change_type
            FROM methods m
            JOIN class c ON m.class_id = c.class_id
            WHERE m.project_id = ?
            AND c.commit_or_branch = ?
        '''
        
        # 如果是测试模式（提供了 mock db），直接使用
        if hasattr(self.db, 'cursor') and callable(getattr(self.db, 'cursor')):
            cursor = self.db.cursor()
        else:
            # 正常模式：使用 SqliteHelper
            conn = self.db.connect()
            cursor = conn.cursor()
        
        cursor.execute(sql, (project_id, commit))
        rows = cursor.fetchall()
        
        # 构建索引
        target_index = self.baseline_index if is_baseline else self.incremental_index
        
        for row in rows:
            method_id, package_name, class_name, method_name, parameters, \
                invocation_map, change_type = row
            
            package_class = f"{package_name}.{class_name}"
            key = (package_class, method_name)
            
            method_data = {
                'method_id': method_id,
                'package_name': package_name,
                'class_name': class_name,
                'method_name': method_name,
                'parameters': parameters,
                'method_invocation_map': invocation_map,
                'change_type': change_type
            }
            
            if key not in target_index:
                target_index[key] = []
            
            target_index[key].append(method_data)
        
        # 关闭连接（如果不是 mock）
        if not hasattr(self.db, 'call_count'):  # 不是 MockDatabase
            try:
                conn.close()
            except Exception:
                pass
        
        logger.info(f"Loaded {len(rows)} methods for project_id={project_id}")
    
    def _build_unified_index(self):
        """
        构建统一索引：增量覆盖基线
        
        规则：
        1. 先复制所有基线方法（排除 DELETED）
        2. 用增量方法覆盖/添加
        """
        self._unified_index = {}
        
        # Step 1: 复制基线方法（过滤删除的）
        for key, methods in self.baseline_index.items():
            active_methods = [
                m for m in methods 
                if m.get('change_type') != 'DELETED'
            ]
            if active_methods:
                self._unified_index[key] = active_methods
        
        # Step 2: 用增量覆盖
        for key, methods in self.incremental_index.items():
            self._unified_index[key] = methods  # 直接覆盖
        
        logger.info(f"Unified index: {len(self._unified_index)} unique method keys")
    
    def query_method(self, package_class: str, method_signature: str) -> Optional[dict]:
        """
        查询方法（支持精确重载匹配）
        
        匹配策略：
        1. 提取目标签名的参数类型列表
        2. 与候选方法的 parameters JSON 比对
        3. 完全匹配 → 返回
        4. 无匹配 → 返回第一个（记录告警）
        
        Args:
            package_class: 完整类名，如 "com.test.Service"
            method_signature: 方法签名，如 "process(int,String)"
        
        Returns:
            dict: 方法数据，或 None（如果不存在）
        """
        # 提取方法名
        method_name = method_signature.split('(')[0]
        key = (package_class, method_name)
        
        candidates = self._unified_index.get(key, [])
        if not candidates:
            return None
        
        # 如果只有一个候选，直接返回
        if len(candidates) == 1:
            return candidates[0]
        
        # 精确重载匹配
        target_params = self._extract_param_types(method_signature)
        
        for candidate in candidates:
            try:
                params = json.loads(candidate['parameters']) if candidate['parameters'] else []
                candidate_types = [p['parameter_type'] for p in params]
                if candidate_types == target_params:
                    return candidate
            except (json.JSONDecodeError, KeyError) as e:
                logger.warning(f"Failed to parse parameters for {candidate.get('method_id')}: {e}")
                continue
        
        # 无精确匹配，返回第一个
        # logger.warning(
        #     f"No exact overload match for {method_signature}, "
        #     f"using first candidate (method_id={candidates[0]['method_id']})"
        # )
        return candidates[0]
    
    def _extract_param_types(self, method_signature: str) -> List[str]:
        """
        从方法签名中提取参数类型列表
        
        示例：
        - "process(int,String)" -> ["int", "String"]
        - "getValue()" -> []
        - "process(List<String>,Map<String,Integer>)" -> ["List<String>", "Map<String,Integer>"]
        
        Args:
            method_signature: 方法签名
        
        Returns:
            List[str]: 参数类型列表
        """
        # 提取括号内的内容
        start = method_signature.find('(')
        end = method_signature.rfind(')')
        
        if start == -1 or end == -1 or start >= end:
            return []
        
        params_str = method_signature[start + 1:end].strip()
        
        if not params_str:
            return []
        
        # 处理泛型：需要正确分割逗号
        param_types = []
        current = ""
        angle_bracket_depth = 0
        
        for char in params_str:
            if char == '<':
                angle_bracket_depth += 1
                current += char
            elif char == '>':
                angle_bracket_depth -= 1
                current += char
            elif char == ',' and angle_bracket_depth == 0:
                param_types.append(current.strip())
                current = ""
            else:
                current += char
        
        if current.strip():
            param_types.append(current.strip())
        
        return param_types
    
    def get_db_connection(self):
        """
        获取数据库连接（供外部组件使用，如 DaoAnalyzer）
        
        Returns:
            数据库连接对象
        """
        # 如果是测试模式（Mock），直接返回
        if hasattr(self.db, 'call_count'):
            return self.db
        
        # 正常模式：返回 SqliteHelper 实例
        return self.db
