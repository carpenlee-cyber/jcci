"""
Mapper 方法索引

建立 MyBatis Mapper XML 与 Java Mapper 接口的关联，
支持向下调用链分析中的 SQL 级别追踪。

v3.2 新增：
- 扫描并解析所有 Mapper XML 文件（支持 MBG 和自定义 DAO）
- 将解析结果存入数据库 mapper_methods 表
- 关联 Java Mapper 接口方法
- 提供快速查询接口供调用链分析使用
"""

import os
import json
import glob
import logging
from typing import Dict, List, Optional
from ..mapper_parse import parse, MapperStatement
from ..database import SqliteHelper

logger = logging.getLogger(__name__)


class MapperMethodIndex:
    """
    Mapper 方法索引
    
    职责：
    1. 扫描项目中的 Mapper XML 文件（支持双路径：MBG + 自定义DAO）
    2. 解析 XML 提取 SQL 语句和方法映射
    3. 关联 Java Mapper 接口方法
    4. 提供查询接口供调用链分析使用
    """
    
    def __init__(self, db_helper: SqliteHelper, project_id: int, source_dir: str):
        """
        初始化 Mapper 方法索引
        
        Args:
            db_helper: 数据库助手
            project_id: 项目ID
            source_dir: 源代码根目录（用于查找 XML 文件）
        """
        self.db = db_helper
        self.project_id = project_id
        self.source_dir = source_dir
        self.mapper_map: Dict[str, dict] = {}  # full_method -> mapper_info
        
    def build_index(self):
        """
        构建 Mapper 方法索引
        
        步骤：
        1. 扫描 XML 文件（支持 mall 项目的双路径模式）
        2. 解析每个 XML
        3. 存入数据库
        4. 关联 Java 方法
        5. 构建内存索引
        """
        logger.info(f"Building Mapper method index for project {self.project_id}...")
        
        # 1. 扫描 XML 文件
        xml_files = self._scan_mapper_xml_files()
        logger.info(f"Found {len(xml_files)} Mapper XML files")
        
        if not xml_files:
            logger.warning("No Mapper XML files found, skipping index build")
            return
        
        # 2. 解析并存储
        total_statements = 0
        failed_files = []
        
        for xml_file in xml_files:
            try:
                statements = self._parse_and_store_xml(xml_file)
                total_statements += len(statements)
            except Exception as e:
                logger.error(f"Failed to parse {xml_file}: {e}")
                failed_files.append(xml_file)
        
        logger.info(f"Parsed {total_statements} SQL statements from {len(xml_files) - len(failed_files)} files")
        
        if failed_files:
            logger.warning(f"Failed to parse {len(failed_files)} files:")
            for f in failed_files[:5]:  # 只显示前5个
                logger.warning(f"  - {f}")
        
        # 3. 关联 Java 方法
        linked_count = self._link_java_methods()
        logger.info(f"Linked {linked_count} Java methods to Mapper XML statements")
        
        # 4. 构建内存索引
        self._build_memory_index()
        
        logger.info(f"Mapper index built: {len(self.mapper_map)} methods indexed")
    
    def _scan_mapper_xml_files(self) -> List[str]:
        """
        扫描项目中的 Mapper XML 文件（支持 mall 项目结构）
        
        Returns:
            XML 文件路径列表
        """
        xml_files = []
        
        # ✅ 模式1: MBG生成的Mapper (mall-mbg)
        mbg_pattern = os.path.join(self.source_dir, '**/mall-mbg/**/*Mapper.xml')
        matched = glob.glob(mbg_pattern, recursive=True)
        xml_files.extend(matched)
        logger.debug(f"Found {len(matched)} MBG Mapper XML files")
        
        # ✅ 模式2: 自定义DAO (各模块的dao目录)
        dao_pattern = os.path.join(self.source_dir, '**/dao/**/*.xml')
        matched = glob.glob(dao_pattern, recursive=True)
        xml_files.extend(matched)
        logger.debug(f"Found {len(matched)} custom DAO XML files")
        
        # ✅ 模式3: 通用匹配（兜底）
        general_pattern = os.path.join(self.source_dir, '**/*Mapper.xml')
        matched = glob.glob(general_pattern, recursive=True)
        xml_files.extend(matched)
        
        # 去重
        unique_files = list(set(xml_files))
        logger.info(f"Total unique XML files: {len(unique_files)}")
        
        return unique_files
    
    def _parse_and_store_xml(self, xml_file: str) -> List[dict]:
        """
        解析单个 XML 文件并存储到数据库
        
        Args:
            xml_file: XML 文件路径
            
        Returns:
            解析的语句列表
        """
        try:
            mapper = parse(xml_file)
            if not mapper:
                logger.warning(f"Failed to parse {xml_file}")
                return []
            
            statements = []
            for stmt in mapper.statements:
                if isinstance(stmt, MapperStatement):
                    stmt_dict = self._store_statement(mapper.namespace, stmt, xml_file)
                    statements.append(stmt_dict)
            
            return statements
            
        except Exception as e:
            logger.error(f"Error parsing {xml_file}: {e}", exc_info=True)
            return []
    
    def _store_statement(self, namespace: str, stmt: MapperStatement, xml_file: str) -> dict:
        """
        存储单个 SQL 语句到数据库
        
        Args:
            namespace: Mapper 命名空间
            stmt: 语句对象
            xml_file: XML 文件路径
            
        Returns:
            存储的语句信息
        """
        full_method = f"{namespace}.{stmt.id}"
        
        # 判断 Mapper 类型
        mapper_type = 'MBG' if '/mall-mbg/' in xml_file or '\\mall-mbg\\' in xml_file else 'CUSTOM'
        
        # 检查是否已存在
        existing = self.db.select_data(
            f"SELECT mapper_id FROM mapper_methods WHERE full_method = ? AND project_id = ?",
            (full_method, self.project_id)
        )
        
        # 确保tables和dynamic_conditions是列表类型后再转换为JSON
        if isinstance(stmt.tables, list):
            tables_json = json.dumps(stmt.tables) if stmt.tables else '[]'
        else:
            # 如果不是列表，尝试转换为列表
            logger.warning(f"stmt.tables is not a list: {type(stmt.tables)}, value: {stmt.tables}")
            tables_json = json.dumps([str(stmt.tables)]) if stmt.tables else '[]'
        
        # ✅ 确保xml_fragment是字符串
        xml_fragment = stmt.content if isinstance(stmt.content, str) else str(stmt.content) if stmt.content else ''
        
        if isinstance(stmt.dynamic_conditions, list):
            dynamic_conditions_json = json.dumps(stmt.dynamic_conditions) if stmt.dynamic_conditions else '[]'
        else:
            logger.warning(f"stmt.dynamic_conditions is not a list: {type(stmt.dynamic_conditions)}")
            dynamic_conditions_json = json.dumps([str(stmt.dynamic_conditions)]) if stmt.dynamic_conditions else '[]'
        
        if existing:
            # 更新
            self.db.execute(
                """UPDATE mapper_methods SET 
                    sql_type = ?,
                    parameter_type = ?,
                    result_type = ?,
                    result_map = ?,
                    sql_content = ?,
                    tables = ?,
                    xml_fragment = ?,
                    start_line = ?,
                    end_line = ?,
                    is_dynamic_sql = ?,
                    dynamic_conditions = ?
                    WHERE full_method = ? AND project_id = ?""",
                (
                    stmt.statement_tag.upper(),
                    stmt.parameter_type or '',
                    stmt.result_type or '',
                    stmt.result_map or '',
                    stmt.sql_content or '',
                    tables_json,
                    xml_fragment,  # ✅ 使用转换后的字符串
                    stmt.start,
                    stmt.end,
                    1 if stmt.dynamic_conditions else 0,
                    dynamic_conditions_json,
                    full_method,
                    self.project_id
                )
            )
        else:
            # 插入
            self.db.execute(
                """INSERT INTO mapper_methods 
                    (namespace, method_id, full_method, sql_type, parameter_type, 
                     result_type, result_map, sql_content, tables, xml_fragment,
                     start_line, end_line, project_id, mapper_type, is_dynamic_sql, dynamic_conditions)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    namespace,
                    stmt.id,
                    full_method,
                    stmt.statement_tag.upper(),
                    stmt.parameter_type or '',
                    stmt.result_type or '',
                    stmt.result_map or '',
                    stmt.sql_content or '',
                    tables_json,
                    xml_fragment,  # ✅ 使用转换后的字符串
                    stmt.start,
                    stmt.end,
                    self.project_id,
                    mapper_type,
                    1 if stmt.dynamic_conditions else 0,
                    dynamic_conditions_json
                )
            )
        
        return {
            'full_method': full_method,
            'sql_type': stmt.statement_tag.upper(),
            'tables': stmt.tables,
            'sql_content': stmt.sql_content,
            'is_dynamic': len(stmt.dynamic_conditions) > 0
        }
    
    def _link_java_methods(self) -> int:
        """
        关联 Java Mapper 接口方法
        
        通过方法名匹配，将 XML 中的 SQL 语句与 Java 接口方法关联
        
        Returns:
            成功关联的数量
        """
        # 查询所有 Mapper/Dao 接口的方法
        java_mappers = self.db.select_data(
            """SELECT m.method_id, m.method_name, c.class_name, c.package_name
                FROM methods m
                JOIN class c ON m.class_id = c.class_id
                WHERE (c.class_name LIKE '%Mapper' OR c.class_name LIKE '%Dao')
                AND m.project_id = ?""",
            (self.project_id,)
        )
        
        linked_count = 0
        for jm in java_mappers:
            full_method = f"{jm['package_name']}.{jm['class_name']}.{jm['method_name']}"
            
            # 在 mapper_methods 表中查找匹配
            mapper_stmt = self.db.select_data(
                "SELECT mapper_id FROM mapper_methods WHERE full_method = ? AND project_id = ?",
                (full_method, self.project_id)
            )
            
            if mapper_stmt:
                # 更新关联
                self.db.execute(
                    "UPDATE mapper_methods SET linked_method_id = ? WHERE full_method = ? AND project_id = ?",
                    (jm['method_id'], full_method, self.project_id)
                )
                linked_count += 1
        
        return linked_count
    
    def _build_memory_index(self):
        """构建内存索引，加速查询"""
        all_mappers = self.db.select_data(
            "SELECT * FROM mapper_methods WHERE project_id = ?",
            (self.project_id,)
        )
        
        for mapper in all_mappers:
            self.mapper_map[mapper['full_method']] = mapper
    
    def get_sql_by_java_method(self, package_class: str, method_name: str) -> Optional[dict]:
        """
        通过 Java 方法名获取对应的 SQL 信息
        
        Args:
            package_class: 完整类名，如 com.macro.mall.mapper.UmsMenuMapper
            method_name: 方法名，如 updateByPrimaryKeySelective
            
        Returns:
            SQL 信息字典，包含：
            - sql_type: SELECT/INSERT/UPDATE/DELETE
            - tables: 涉及的表名列表
            - sql_content: SQL 语句内容
            - is_dynamic_sql: 是否为动态SQL
            - dynamic_conditions: 动态SQL条件列表
        """
        full_method = f"{package_class}.{method_name}"
        
        # 优先从内存索引查询
        if full_method in self.mapper_map:
            return self._parse_mapper_info(self.mapper_map[full_method])
        
        # 否则从数据库查询
        result = self.db.select_data(
            "SELECT * FROM mapper_methods WHERE full_method = ? AND project_id = ?",
            (full_method, self.project_id)
        )
        
        if result:
            mapper_info = result[0]
            # 缓存到内存索引
            self.mapper_map[full_method] = mapper_info
            return self._parse_mapper_info(mapper_info)
        
        return None
    
    def _parse_mapper_info(self, mapper_info: dict) -> dict:
        """
        解析数据库中的 mapper_info，反序列化 JSON 字段
        
        Args:
            mapper_info: 数据库查询结果
            
        Returns:
            解析后的字典
        """
        result = dict(mapper_info)
        
        # 反序列化 JSON 字段
        if isinstance(result.get('tables'), str):
            try:
                result['tables'] = json.loads(result['tables'])
            except:
                result['tables'] = []
        
        if isinstance(result.get('dynamic_conditions'), str):
            try:
                result['dynamic_conditions'] = json.loads(result['dynamic_conditions'])
            except:
                result['dynamic_conditions'] = []
        
        return result
    
    def get_mapper_methods_by_namespace(self, namespace: str) -> List[dict]:
        """
        获取指定命名空间的所有 Mapper 方法
        
        Args:
            namespace: Mapper 命名空间
            
        Returns:
            Mapper 方法列表
        """
        results = self.db.select_data(
            "SELECT * FROM mapper_methods WHERE namespace = ? AND project_id = ?",
            (namespace, self.project_id)
        )
        
        return [self._parse_mapper_info(r) for r in results]
    
    def get_statistics(self) -> dict:
        """
        获取索引统计信息
        
        Returns:
            统计信息字典
        """
        stats = self.db.select_data(
            """SELECT 
                COUNT(*) as total_methods,
                SUM(CASE WHEN sql_type = 'SELECT' THEN 1 ELSE 0 END) as select_count,
                SUM(CASE WHEN sql_type = 'INSERT' THEN 1 ELSE 0 END) as insert_count,
                SUM(CASE WHEN sql_type = 'UPDATE' THEN 1 ELSE 0 END) as update_count,
                SUM(CASE WHEN sql_type = 'DELETE' THEN 1 ELSE 0 END) as delete_count,
                SUM(CASE WHEN is_dynamic_sql = 1 THEN 1 ELSE 0 END) as dynamic_sql_count,
                SUM(CASE WHEN mapper_type = 'MBG' THEN 1 ELSE 0 END) as mbg_count,
                SUM(CASE WHEN mapper_type = 'CUSTOM' THEN 1 ELSE 0 END) as custom_count
            FROM mapper_methods
            WHERE project_id = ?""",
            (self.project_id,)
        )
        
        if stats:
            return stats[0]
        
        return {
            'total_methods': 0,
            'select_count': 0,
            'insert_count': 0,
            'update_count': 0,
            'delete_count': 0,
            'dynamic_sql_count': 0,
            'mbg_count': 0,
            'custom_count': 0
        }
