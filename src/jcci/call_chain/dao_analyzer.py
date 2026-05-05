"""
DAO 层方法识别与透视分析器（独立策略组件）

职责：
1. 识别方法是否属于 DAO 层
2. 解析对应的 Entity 和 SQL 信息
3. 在缺少映射表时降级为命名推导模式

使用方式：
    analyzer = DaoAnalyzer(db_conn)
    builder = CallChainBuilder(index, dao_analyzer=analyzer)
"""
import logging
import re
import sqlite3
from typing import Optional, Dict
from dataclasses import dataclass, field

from src.jcci.call_chain.models import DaoInfo

logger = logging.getLogger(__name__)


@dataclass
class SchemaHealth:
    """数据库 Schema 健康状态"""
    has_entity_table: bool = False
    has_sql_table: bool = False
    has_required_columns: bool = False
    is_healthy: bool = False
    error_message: Optional[str] = None


class SqlResolver:
    """SQL 解析器（内部使用，DaoAnalyzer 已做缓存层）"""
    
    def __init__(self, db_conn: sqlite3.Connection):
        self.db_conn = db_conn


class EntityResolver:
    """Entity 解析器（内部使用，DaoAnalyzer 已做缓存层）"""
    
    def __init__(self, db_conn: sqlite3.Connection):
        self.db_conn = db_conn


class DaoAnalyzer:
    """
    DAO 层方法识别与透视分析器（独立策略组件）
    
    职责：
    1. 识别方法是否属于 DAO 层
    2. 解析对应的 Entity 和 SQL 信息
    3. 在缺少映射表时降级为命名推导模式
    
    使用方式：
        analyzer = DaoAnalyzer(db_conn)
        builder = CallChainBuilder(index, dao_analyzer=analyzer)
    """
    
    # DAO 类名后缀与框架类型映射（按优先级排序）
    DAO_SUFFIX_PATTERNS = [
        (r'.*Mapper$', 'MYBATIS'),
        (r'.*Dao$', 'MYBATIS'),      # 默认 MYBATIS，但包名可覆盖
        (r'.*DAO$', 'JDBC'),
        (r'.*Repository$', 'JPA'),
    ]
    
    # 包名与框架类型映射（优先级高于后缀）
    DAO_PACKAGE_PATTERNS = [
        (r'\.repository\.', 'JPA'),
        (r'\.mapper\.', 'MYBATIS'),
        (r'\.dao\.', 'MYBATIS'),
    ]
    
    def __init__(self, db_conn: sqlite3.Connection):
        self.db_conn = db_conn
        self.sql_resolver = SqlResolver(db_conn)
        self.entity_resolver = EntityResolver(db_conn)
        
        try:
            self._schema_health = self._check_schema_health()
        except Exception as e:
            logger.error("Failed to initialize DaoAnalyzer: %s", e)
            self._schema_health = SchemaHealth(
                is_healthy=False,
                error_message=f"Initialization failed: {e}"
            )
        
        self._load_mapping_cache()
    
    def _check_schema_health(self) -> SchemaHealth:
        """
        Schema 健康检查：验证表存在性及关键列完整性
        
        检查项：
        1. dao_entity_mapping 表是否存在
        2. method_sql_mapping 表是否存在  
        3. 关键列（method_id, sql_statement, entity_class）是否存在
        """
        health = SchemaHealth()
        cursor = self.db_conn.cursor()
        
        try:
            # 检查表存在
            cursor.execute("""
                SELECT name FROM sqlite_master 
                WHERE type='table' AND name IN ('dao_entity_mapping', 'method_sql_mapping')
            """)
            tables = {row[0] for row in cursor.fetchall()}
            health.has_entity_table = 'dao_entity_mapping' in tables
            health.has_sql_table = 'method_sql_mapping' in tables
            
            if not (health.has_entity_table and health.has_sql_table):
                health.error_message = "Missing required mapping tables"
                logger.warning("DAO Schema unhealthy: %s", health.error_message)
                return health
            
            # 检查关键列（PRAGMA 是 SQLite 特有，安全且轻量）
            cursor.execute("PRAGMA table_info(dao_entity_mapping)")
            entity_cols = {row[1] for row in cursor.fetchall()}
            
            cursor.execute("PRAGMA table_info(method_sql_mapping)")
            sql_cols = {row[1] for row in cursor.fetchall()}
            
            required_entity = {'method_id', 'entity_name'}
            required_sql = {'method_id', 'sql_statement'}
            
            has_entity_cols = required_entity.issubset(entity_cols)
            has_sql_cols = required_sql.issubset(sql_cols)
            
            health.has_required_columns = has_entity_cols and has_sql_cols
            
            if not health.has_required_columns:
                missing = []
                if not has_entity_cols:
                    missing.append("dao_entity_mapping missing required columns")
                if not has_sql_cols:
                    missing.append("method_sql_mapping missing required columns")
                health.error_message = "; ".join(missing)
                logger.warning("DAO Schema incomplete: %s", health.error_message)
                return health
            
            health.is_healthy = True
            logger.info("DAO Schema healthy, full resolution mode enabled")
            
        except sqlite3.Error as e:
            health.error_message = f"Schema check failed: {e}"
            logger.error(health.error_message)
        
        return health
    
    def _load_mapping_cache(self):
        """预加载映射数据到内存（仅 Schema 健康时）"""
        self._entity_cache: Dict[int, dict] = {}
        self._sql_cache: Dict[int, dict] = {}
        
        if not self._schema_health.is_healthy:
            logger.info("Skipping mapping cache load (schema unhealthy)")
            return
        
        try:
            cursor = self.db_conn.cursor()
            
            # 预加载 Entity 映射
            cursor.execute("SELECT method_id, entity_name, entity_class, table_name FROM dao_entity_mapping")
            for row in cursor.fetchall():
                self._entity_cache[row[0]] = {
                    'entity_name': row[1],
                    'entity_class': row[2],
                    'table_name': row[3]
                }
            
            # 预加载 SQL 映射
            cursor.execute("SELECT method_id, sql_type, sql_statement, mapped_statement_id FROM method_sql_mapping")
            for row in cursor.fetchall():
                self._sql_cache[row[0]] = {
                    'sql_type': row[1],
                    'sql_statement': row[2],
                    'mapped_statement_id': row[3]
                }
            
            logger.info("Loaded %d entity mappings and %d SQL mappings", 
                       len(self._entity_cache), len(self._sql_cache))
                       
        except sqlite3.Error as e:
            logger.error("Failed to load mapping cache: %s", e)
            self._schema_health.is_healthy = False
    
    def analyze(self, package_class: str, method_signature: str, 
                method_id: Optional[int]) -> Optional[DaoInfo]:
        """
        分析给定方法是否为 DAO 方法，返回透视信息。
        
        Returns:
            DaoInfo: 如果是 DAO 方法
            None: 如果不是 DAO 方法
        """
        dao_type = self._detect_dao_type(package_class)
        if not dao_type:
            return None
        
        # 基础 DAO 信息
        inferred_entity = self._infer_entity_name(package_class, dao_type)
        
        dao_info = DaoInfo(
            is_dao=True,
            dao_type=dao_type,
            entity_name=inferred_entity,
            entity_source="INFERRED" if inferred_entity else "UNKNOWN"
        )
        
        # 完整模式：从缓存加载精确映射
        if method_id and self._schema_health.is_healthy:
            if method_id in self._entity_cache:
                entity_data = self._entity_cache[method_id]
                dao_info.entity_name = entity_data.get('entity_name') or dao_info.entity_name
                dao_info.entity_class = entity_data.get('entity_class')
                dao_info.table_name = entity_data.get('table_name')
                dao_info.entity_source = "MAPPED"
            
            if method_id in self._sql_cache:
                sql_data = self._sql_cache[method_id]
                dao_info.sql_type = sql_data.get('sql_type')
                dao_info.sql_statement = sql_data.get('sql_statement')
                dao_info.mapped_statement_id = sql_data.get('mapped_statement_id')
        
        return dao_info
    
    def _detect_dao_type(self, package_class: str) -> Optional[str]:
        """
        通过类名后缀和包名检测 DAO 类型。
        
        优先级：
        1. 包名匹配（最高优先级，可覆盖后缀误判）
        2. 类名后缀匹配
        3. 若冲突（如包名指示 JPA 但后缀为 Dao），以包名为准
        4. 若均无法明确判定，返回 UNKNOWN 而非猜测
        """
        class_name = package_class.split('.')[-1]
        
        # 第一步：包名检测（高优先级）
        package_type = None
        for pattern, dao_type in self.DAO_PACKAGE_PATTERNS:
            if re.search(pattern, package_class):
                package_type = dao_type
                break
        
        # 第二步：后缀检测
        suffix_type = None
        for pattern, dao_type in self.DAO_SUFFIX_PATTERNS:
            if re.match(pattern, class_name):
                suffix_type = dao_type
                break
        
        # 第三步：冲突解决
        if package_type and suffix_type:
            if package_type == suffix_type:
                return package_type
            # 冲突时，包名优先，但记录日志
            logger.debug(
                "DAO type conflict for %s: package suggests %s, suffix suggests %s. "
                "Using package type.", package_class, package_type, suffix_type
            )
            return package_type
        
        if package_type:
            return package_type
        if suffix_type:
            return suffix_type
        
        return None
    
    def _infer_entity_name(self, package_class: str, dao_type: str) -> Optional[str]:
        """
        通过命名约定推导 Entity 名称。
        
        规则：
        - UmsAdminMapper → UmsAdmin
        - UmsAdminDao → UmsAdmin
        - UmsAdminRepository → UmsAdmin
        
        失败时返回 None，不强行猜测。
        """
        class_name = package_class.split('.')[-1]
        
        suffixes = ['Mapper', 'Dao', 'DAO', 'Repository']
        for suffix in suffixes:
            if class_name.endswith(suffix):
                return class_name[:-len(suffix)]
        
        return None
