# MyBatis Mapper 链路追踪实施方案

## 一、问题分析

### 1.1 当前不足

根据技术文档 v3.2 的要求，当前 JCCI 在 MyBatis Mapper 链路追踪方面存在以下不足：

1. **mapper_parse.py 功能不完整**：
   - 已有 XML 解析器（使用 ElementTree）
   - 但解析结果未存储到数据库
   - 缺少 SQL 语句提取和表名分析

2. **缺少 Mapper 方法索引**：
   - 没有建立 Java Mapper 接口方法与 XML SQL 的关联
   - 无法通过 Java 方法名快速定位对应的 SQL

3. **向下分析未集成 DAO 层**：
   - `DownwardsCallChainBuilder` 预留了 `dao_analyzer` 参数但未实现
   - 无法展示 SQL 级别的调用链

4. **接口-实现类映射问题**：
   - Service 层通常使用接口注入（如 `@Autowired UserService userService`）
   - 向下分析时需要通过 CHA 解析到实现类（`UserServiceImpl`）
   - 实现类中才包含对 Mapper 的实际调用

### 1.2 用户期望效果

```
向下调用链 (增强版):
  UserService.updateUser (MODIFIED)
    --> UserMapper.updateById (UNCHANGED)
      --> SQL:UPDATE [表: user]
        SQL: UPDATE user SET phone_number = #{phoneNumber}, updated_at = now() WHERE id = #{id}
        📝 影响表: user
        🔍 操作类型: UPDATE
        ⚠️ 风险: 字段 phone_number 被修改，需确认索引影响
    --> RedisTemplate.delete (UNCHANGED)
      --> [第三方库，终止展开]
```

---

## 二、实施方案

### 阶段 1: 数据库扩展（P0 - 必须）

#### 2.1.1 新增 mapper_methods 表

```sql
CREATE TABLE IF NOT EXISTS mapper_methods (
    mapper_id INTEGER PRIMARY KEY AUTOINCREMENT,
    namespace TEXT NOT NULL,              -- Mapper 命名空间，如 com.macro.mall.mapper.UmsMenuMapper
    method_id TEXT NOT NULL,              -- XML 中的 id，如 selectById
    full_method TEXT NOT NULL,            -- 完整方法名，如 com.macro.mall.mapper.UmsMenuMapper.selectById
    sql_type TEXT NOT NULL,               -- SELECT/INSERT/UPDATE/DELETE
    parameter_type TEXT,                  -- 参数类型
    result_type TEXT,                     -- 返回类型
    result_map TEXT,                      -- resultMap 引用
    sql_content TEXT,                     -- SQL 语句内容
    tables TEXT,                          -- JSON 数组，涉及的表名 ["ums_menu"]
    xml_fragment TEXT,                    -- XML 片段（用于调试）
    start_line INTEGER,                   -- XML 文件起始行号
    end_line INTEGER,                     -- XML 文件结束行号
    project_id INTEGER NOT NULL,          -- 项目ID
    java_method_id INTEGER,               -- 关联的 Java 方法ID（后续填充）
    change_type TEXT DEFAULT 'UNCHANGED', -- 变更类型
    UNIQUE(namespace, method_id, project_id)
);

CREATE INDEX idx_mapper_full_method ON mapper_methods(full_method);
CREATE INDEX idx_mapper_namespace ON mapper_methods(namespace);
CREATE INDEX idx_mapper_java_method ON mapper_methods(java_method_id);
```

#### 2.1.2 扩展现有表

```sql
-- methods 表增加字段（如果不存在）
ALTER TABLE methods ADD COLUMN is_mapper_interface INTEGER DEFAULT 0;
ALTER TABLE methods ADD COLUMN mapper_xml_path TEXT;

-- class 表增加字段
ALTER TABLE class ADD COLUMN implements TEXT;  -- JSON 数组，如 ["com.example.UserService"]
```

### 阶段 2: Mapper 解析器增强（P0 - 必须）

#### 2.2.1 增强 mapper_parse.py

**文件**: `jcci/src/jcci/mapper_parse.py`

**目标**: 
1. 提取 SQL 语句内容
2. 提取涉及的表名
3. 支持动态 SQL 标签（`<if>`, `<foreach>` 等）

```python
import xml.etree.ElementTree as ET
import re
import json
from typing import List, Dict, Optional

class Mapper(object):
    def __init__(self, namespace, result_maps, sqls, statements):
        self.namespace = namespace
        self.result_maps = result_maps
        self.sqls = sqls
        self.statements = statements


class MapperElement(object):
    def __init__(self, id, type, start, end, content):
        self.id = id
        self.name = id
        self.type = type
        self.start = start
        self.end = end
        self.content = content
        self.diff_impact = None


class MapperStatement(MapperElement):
    def __init__(self, id, type, start_line, end_line, content, statement_tag, 
                 result_map, include_sql, parameter_type=None, result_type=None,
                 sql_content=None, tables=None):
        super(MapperStatement, self).__init__(id, type, start_line, end_line, content)
        self.statement_tag = statement_tag
        self.result_map = result_map
        self.include_sql = include_sql
        self.parameter_type = parameter_type
        self.result_type = result_type
        self.sql_content = sql_content  # 新增：SQL 语句内容
        self.tables = tables or []      # 新增：涉及的表名列表


def extract_value(string, tag):
    pattern = tag + r'\s*=\s*[\'"](\w+)[\'"]'
    match = re.search(pattern, string)
    if match:
        value = match.group(1)
        return value
    else:
        return None


def check_string(tag, id_str, string):
    pattern = r'^' + tag + '.*?id\s*=\s*[\'"]' + id_str + '[\'"]'
    match = re.search(pattern, string)
    return bool(match)


def extract_tables_from_sql(sql_text: str) -> List[str]:
    """
    从 SQL 文本中提取表名
    
    Args:
        sql_text: SQL 语句文本
        
    Returns:
        表名列表，如 ['user', 'order']
    """
    if not sql_text:
        return []
    
    # 匹配 FROM, INTO, UPDATE, JOIN 后面的表名
    patterns = [
        r'(?:FROM|INTO)\s+[`"\']?(\w+)[`"\']?',
        r'(?:UPDATE)\s+[`"\']?(\w+)[`"\']?',
        r'(?:JOIN)\s+[`"\']?(\w+)[`"\']?\s+(?:ON|USING)',
    ]
    
    tables = set()
    for pattern in patterns:
        matches = re.findall(pattern, sql_text, re.IGNORECASE)
        tables.update(matches)
    
    # 过滤掉常见的 SQL 关键字
    keywords = {'SELECT', 'WHERE', 'AND', 'OR', 'SET', 'VALUES', 'GROUP', 'ORDER'}
    tables = {t for t in tables if t.upper() not in keywords}
    
    return sorted(list(tables))


def extract_sql_content(element) -> str:
    """
    从 XML 元素中提取 SQL 内容（去除标签，保留纯 SQL）
    
    Args:
        element: XML 元素
        
    Returns:
        清理后的 SQL 文本
    """
    # 递归提取所有文本内容
    sql_parts = []
    
    if element.text:
        sql_parts.append(element.text.strip())
    
    for child in element:
        # 处理动态 SQL 标签
        if child.tag in ['if', 'foreach', 'choose', 'when', 'otherwise']:
            sql_parts.append(extract_sql_content(child))
        elif child.tag == 'include':
            # <include> 标签暂时跳过（需要解析引用的 <sql>）
            pass
        else:
            # 其他标签（如 #{}, ${}）保留占位符
            if child.tail:
                sql_parts.append(child.tail.strip())
    
    # 合并并清理
    sql_text = ' '.join(sql_parts)
    # 移除多余空白
    sql_text = re.sub(r'\s+', ' ', sql_text).strip()
    
    return sql_text


def parse(filepath: str) -> Optional[Mapper]:
    """
    解析 MyBatis Mapper XML 文件
    
    Args:
        filepath: XML 文件路径
        
    Returns:
        Mapper 对象，解析失败返回 None
    """
    # 读取XML文件内容
    try:
        with open(filepath, "r", encoding="utf-8") as file:
            xml_content = file.read()
    except Exception as e:
        print(f"Failed to read file {filepath}: {e}")
        return None

    # 解析XML文件
    try:
        tree = ET.ElementTree(ET.fromstring(xml_content))
        root = tree.getroot()
    except Exception as e:
        print(f"Failed to parse XML {filepath}: {e}")
        return None

    # 获取namespace
    try:
        namespace = root.attrib["namespace"]
        if namespace is None:
            return None
    except KeyError:
        return None
    
    # 存储resultMap和每条语句的id以及对应的起始行号和截止行号
    result_map_info = []
    sql_info = []
    statement_info = []

    # 获取resultMap的id以及起始行号和截止行号
    for element in root.findall(".//resultMap"):
        result_map_id = element.attrib["id"]
        start_line = 0
        end_line = 0
        for i, line in enumerate(xml_content.splitlines(), start=1):
            if check_string('<resultMap', result_map_id, line.strip()):
                start_line = i
            if f'</resultMap>' in line and start_line != 0:
                end_line = i
                break
        content = xml_content.splitlines()[start_line - 1: end_line]
        result_map_info.append(MapperElement(result_map_id, 'resultMap', start_line, end_line, content))

    # 获取sql片段的id以及起始行号和截止行号
    for sql_element in root.findall(".//sql"):
        sql_id = sql_element.attrib["id"]
        start_line = 0
        end_line = 0
        for i, line in enumerate(xml_content.splitlines(), start=1):
            if check_string('<sql', sql_id, line.strip()):
                start_line = i
            if f'</sql>' in line and start_line != 0:
                end_line = i
                break
        content = xml_content.splitlines()[start_line - 1: end_line]
        sql_info.append(MapperElement(sql_id, 'sql', start_line, end_line, content))

    # 获取每条语句的id以及起始行号和截止行号（增强版）
    statements = root.findall(".//select") + root.findall(".//insert") + \
                 root.findall(".//update") + root.findall(".//delete")
    
    for statement_element in statements:
        statement_id = statement_element.attrib["id"]
        start_line = 0
        end_line = 0
        result_map = None
        include_sql = None
        parameter_type = statement_element.get('parameterType')
        result_type = statement_element.get('resultType') or statement_element.get('resultMap')
        
        for i, line in enumerate(xml_content.splitlines(), start=1):
            if check_string('<' + statement_element.tag, statement_id, line.strip()):
                start_line = i
            if f'resultMap' in line and start_line != 0:
                result_map = extract_value(line, 'resultMap')
            if line.strip().startswith('<include') and start_line != 0:
                include_sql = extract_value(line, 'refid')
            if f'</{statement_element.tag}>' in line and start_line != 0:
                end_line = i
                break
        
        content = xml_content.splitlines()[start_line - 1: end_line]
        
        # 新增：提取 SQL 内容和表名
        sql_content = extract_sql_content(statement_element)
        tables = extract_tables_from_sql(sql_content)
        
        statement_info.append(MapperStatement(
            statement_id, 'statement', start_line, end_line, content, 
            statement_element.tag, result_map, include_sql,
            parameter_type=parameter_type,
            result_type=result_type,
            sql_content=sql_content,
            tables=tables
        ))

    return Mapper(namespace, result_map_info, sql_info, statement_info)
```

### 阶段 3: Mapper 索引构建器（P1 - 核心）

#### 2.3.1 新建 mapper_index.py

**文件**: `jcci/src/jcci/call_chain/mapper_index.py`

**功能**:
1. 解析所有 Mapper XML 文件
2. 将解析结果存入数据库
3. 关联 Java Mapper 接口方法
4. 提供快速查询接口

```python
"""
Mapper 方法索引

建立 MyBatis Mapper XML 与 Java Mapper 接口的关联，
支持向下调用链分析中的 SQL 级别追踪。
"""

import os
import json
import logging
from typing import Dict, List, Optional
from ..mapper_parse import parse, MapperStatement
from ..database import SqliteHelper

logger = logging.getLogger(__name__)


class MapperMethodIndex:
    """
    Mapper 方法索引
    
    职责：
    1. 扫描项目中的 Mapper XML 文件
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
        1. 扫描 XML 文件
        2. 解析每个 XML
        3. 存入数据库
        4. 关联 Java 方法
        """
        logger.info(f"Building Mapper method index for project {self.project_id}...")
        
        # 1. 扫描 XML 文件
        xml_files = self._scan_mapper_xml_files()
        logger.info(f"Found {len(xml_files)} Mapper XML files")
        
        # 2. 解析并存储
        total_statements = 0
        for xml_file in xml_files:
            statements = self._parse_and_store_xml(xml_file)
            total_statements += len(statements)
        
        logger.info(f"Parsed {total_statements} SQL statements")
        
        # 3. 关联 Java 方法
        self._link_java_methods()
        
        # 4. 构建内存索引
        self._build_memory_index()
        
        logger.info(f"Mapper index built: {len(self.mapper_map)} methods indexed")
    
    def _scan_mapper_xml_files(self) -> List[str]:
        """
        扫描项目中的 Mapper XML 文件
        
        Returns:
            XML 文件路径列表
        """
        xml_files = []
        
        # 常见 Mapper XML 存放路径
        search_patterns = [
            '**/*Mapper.xml',
            '**/mapper/**/*.xml',
            '**/dao/**/*.xml',
        ]
        
        for pattern in search_patterns:
            import glob
            matched = glob.glob(os.path.join(self.source_dir, pattern), recursive=True)
            xml_files.extend(matched)
        
        # 去重
        return list(set(xml_files))
    
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
        
        # 检查是否已存在
        existing = self.db.select_data(
            f"SELECT mapper_id FROM mapper_methods WHERE full_method = '{full_method}' AND project_id = {self.project_id}"
        )
        
        if existing:
            # 更新
            self.db.execute(
                f"""UPDATE mapper_methods SET 
                    sql_type = '{stmt.statement_tag.upper()}',
                    parameter_type = '{stmt.parameter_type or ''}',
                    result_type = '{stmt.result_type or ''}',
                    result_map = '{stmt.result_map or ''}',
                    sql_content = ?,
                    tables = ?,
                    xml_fragment = ?,
                    start_line = {stmt.start},
                    end_line = {stmt.end}
                    WHERE full_method = '{full_method}' AND project_id = {self.project_id}""",
                (stmt.sql_content or '', json.dumps(stmt.tables), stmt.content)
            )
        else:
            # 插入
            self.db.execute(
                f"""INSERT INTO mapper_methods 
                    (namespace, method_id, full_method, sql_type, parameter_type, 
                     result_type, result_map, sql_content, tables, xml_fragment,
                     start_line, end_line, project_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    namespace,
                    stmt.id,
                    full_method,
                    stmt.statement_tag.upper(),
                    stmt.parameter_type or '',
                    stmt.result_type or '',
                    stmt.result_map or '',
                    stmt.sql_content or '',
                    json.dumps(stmt.tables),
                    stmt.content,
                    stmt.start,
                    stmt.end,
                    self.project_id
                )
            )
        
        return {
            'full_method': full_method,
            'sql_type': stmt.statement_tag.upper(),
            'tables': stmt.tables,
            'sql_content': stmt.sql_content
        }
    
    def _link_java_methods(self):
        """
        关联 Java Mapper 接口方法
        
        通过方法名匹配，将 XML 中的 SQL 语句与 Java 接口方法关联
        """
        # 查询所有 Mapper 接口的方法
        java_mappers = self.db.select_data(
            f"""SELECT m.method_id, m.method_name, c.class_name, c.package_name
                FROM methods m
                JOIN class c ON m.class_id = c.class_id
                WHERE c.class_name LIKE '%Mapper' OR c.class_name LIKE '%Dao'
                AND m.project_id = {self.project_id}"""
        )
        
        linked_count = 0
        for jm in java_mappers:
            full_method = f"{jm['package_name']}.{jm['class_name']}.{jm['method_name']}"
            
            # 在 mapper_methods 表中查找匹配
            mapper_stmt = self.db.select_data(
                f"SELECT mapper_id FROM mapper_methods WHERE full_method = '{full_method}' AND project_id = {self.project_id}"
            )
            
            if mapper_stmt:
                # 更新关联
                self.db.execute(
                    f"UPDATE mapper_methods SET java_method_id = {jm['method_id']} WHERE full_method = '{full_method}' AND project_id = {self.project_id}"
                )
                linked_count += 1
        
        logger.info(f"Linked {linked_count} Java methods to Mapper XML statements")
    
    def _build_memory_index(self):
        """构建内存索引，加速查询"""
        all_mappers = self.db.select_data(
            f"SELECT * FROM mapper_methods WHERE project_id = {self.project_id}"
        )
        
        for mapper in all_mappers:
            self.mapper_map[mapper['full_method']] = mapper
    
    def get_sql_by_java_method(self, package_class: str, method_name: str) -> Optional[dict]:
        """
        通过 Java 方法名获取对应的 SQL 信息
        
        Args:
            package_class: 完整类名，如 com.macro.mall.mapper.UmsMenuMapper
            method_name: 方法名，如 selectById
            
        Returns:
            SQL 信息字典，包含 sql_type, tables, sql_content 等
        """
        full_method = f"{package_class}.{method_name}"
        
        # 优先从内存索引查询
        if full_method in self.mapper_map:
            return self.mapper_map[full_method]
        
        # 否则从数据库查询
        result = self.db.select_data(
            f"SELECT * FROM mapper_methods WHERE full_method = '{full_method}' AND project_id = {self.project_id}"
        )
        
        if result:
            mapper_info = result[0]
            # 缓存到内存索引
            self.mapper_map[full_method] = mapper_info
            return mapper_info
        
        return None
    
    def get_mapper_methods_by_namespace(self, namespace: str) -> List[dict]:
        """
        获取指定命名空间的所有 Mapper 方法
        
        Args:
            namespace: Mapper 命名空间
            
        Returns:
            Mapper 方法列表
        """
        return self.db.select_data(
            f"SELECT * FROM mapper_methods WHERE namespace = '{namespace}' AND project_id = {self.project_id}"
        )
```

### 阶段 4: DAO 分析器（P1 - 核心）

#### 2.4.1 新建 dao_analyzer.py

**文件**: `jcci/src/jcci/call_chain/dao_analyzer.py`

**功能**:
1. 识别 Mapper/DAO 层方法调用
2. 获取对应的 SQL 信息
3. 生成 SQL 节点用于调用链展示

```python
"""
DAO 层分析器

负责分析 MyBatis Mapper/DAO 层方法调用，
提取 SQL 语句信息并生成调用链节点。
"""

import logging
from typing import Optional, Dict
from .models import CallChainNode
from .mapper_index import MapperMethodIndex

logger = logging.getLogger(__name__)


class DaoAnalyzer:
    """
    DAO 层分析器
    
    职责：
    1. 判断一个方法是否为 Mapper/DAO 层方法
    2. 获取该方法对应的 SQL 信息
    3. 生成 SQL 级别的调用链节点
    """
    
    def __init__(self, mapper_index: MapperMethodIndex):
        """
        初始化 DAO 分析器
        
        Args:
            mapper_index: Mapper 方法索引
        """
        self.mapper_index = mapper_index
    
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
            method_signature: 方法签名，如 selectById(Long)
            method_id: 可选的方法ID
            
        Returns:
            SQL 信息字典，包含：
            - sql_type: SELECT/INSERT/UPDATE/DELETE
            - tables: 涉及的表名列表
            - sql_content: SQL 语句内容
            - risk_level: 风险等级
            - warning: 警告信息
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
        
        # 风险评估
        risk_level, warning = self._assess_risk(sql_type, tables, sql_content)
        
        return {
            'sql_type': sql_type,
            'tables': tables,
            'sql_content': sql_content,
            'risk_level': risk_level,
            'warning': warning,
            'mapper_method': f"{package_class}.{method_name}"
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
        from .models import ChangeType
        
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
        sql_node.is_leaf = True  # SQL 节点是叶子节点
        
        return sql_node
    
    def _assess_risk(self, sql_type: str, tables: list, sql_content: str) -> tuple:
        """
        评估 SQL 操作的风险等级
        
        Args:
            sql_type: SQL 类型
            tables: 涉及的表
            sql_content: SQL 内容
            
        Returns:
            (risk_level, warning) 元组
        """
        risk_level = 'LOW'
        warnings = []
        
        if sql_type == 'DELETE':
            risk_level = 'HIGH'
            warnings.append(f"⚠️ DELETE 操作会影响表: {', '.join(tables)}")
        
        elif sql_type == 'UPDATE':
            risk_level = 'MEDIUM'
            # 检查是否有 WHERE 条件
            if 'WHERE' not in sql_content.upper():
                risk_level = 'CRITICAL'
                warnings.append("🔴 UPDATE 操作缺少 WHERE 条件，可能更新全表！")
            else:
                warnings.append(f"⚠️ UPDATE 操作会影响表: {', '.join(tables)}")
        
        elif sql_type == 'INSERT':
            risk_level = 'LOW'
            warnings.append(f"📝 INSERT 操作会插入数据到表: {', '.join(tables)}")
        
        elif sql_type == 'SELECT':
            risk_level = 'LOW'
        
        warning = '; '.join(warnings) if warnings else ''
        
        return risk_level, warning
```

### 阶段 5: 向下调用链集成（P2 - 集成）

#### 2.5.1 增强 DownwardsCallChainBuilder

**文件**: `jcci/src/jcci/call_chain/downwards_builder.py`

**修改内容**: 在 `_dfs_expand` 后处理 Mapper 节点，添加 SQL 子节点

```python
"""
向下调用链构建器（增强版 - 支持 MyBatis Mapper 链路）

负责构建"这个方法调用了谁"的调用链（功能风险分析）。
v3.2 新增：支持 MyBatis Mapper SQL 级别追踪
"""

import logging
from typing import Optional
from .builder import CallChainBuilder
from .dao_analyzer import DaoAnalyzer
from .mapper_index import MapperMethodIndex

logger = logging.getLogger(__name__)


class DownwardsCallChainBuilder(CallChainBuilder):
    """
    向下调用链构建器（增强版）
    
    继承自 CallChainBuilder，增加：
    1. Mapper/DAO 层方法识别
    2. SQL 级别调用链展开
    3. 接口-实现类映射支持（通过 CHA）
    """
    
    def __init__(self, unified_index, max_depth: int = 10,
                 dao_analyzer: Optional[DaoAnalyzer] = None,
                 class_hierarchy=None):
        """
        初始化向下调用链构建器
        
        Args:
            unified_index: UnifiedMethodIndex 实例
            max_depth: 最大递归深度
            dao_analyzer: DAO 分析器实例（可选）
            class_hierarchy: 类层次索引（用于 CHA，可选）
        """
        super().__init__(unified_index, max_depth=max_depth, dao_analyzer=dao_analyzer)
        self.dao_analyzer = dao_analyzer
        self.class_hierarchy = class_hierarchy
        logger.info(f"Downwards call chain builder initialized (max_depth={max_depth}, "
                   f"dao_analyzer={'enabled' if dao_analyzer else 'disabled'})")
    
    def _dfs_expand(self, node, path_visited, current_depth):
        """
        重写 DFS 展开逻辑，增加 Mapper SQL 节点处理
        
        Args:
            node: 当前节点
            path_visited: 路径访问集合
            current_depth: 当前深度
        """
        # 1. 执行原有的 DFS 展开
        super()._dfs_expand(node, path_visited, current_depth)
        
        # 2. 如果启用了 DAO 分析器，检查是否需要添加 SQL 节点
        if self.dao_analyzer and node.children:
            self._add_sql_nodes_for_mapper_calls(node)
    
    def _add_sql_nodes_for_mapper_calls(self, parent_node):
        """
        为 Mapper 调用节点添加 SQL 子节点
        
        Args:
            parent_node: 父节点（可能是 Service 调用 Mapper 的节点）
        """
        for child in parent_node.children:
            # 检查是否为 Mapper/DAO 方法
            if self.dao_analyzer.is_dao_method(child.package_class, child.method_name):
                # 获取 SQL 信息
                sql_info = self.dao_analyzer.analyze(
                    child.package_class,
                    child.method_signature,
                    child.db_method_id
                )
                
                if sql_info:
                    # 创建 SQL 节点
                    sql_node = self.dao_analyzer.create_sql_node(child, sql_info)
                    
                    # 添加到 Mapper 节点的子节点
                    child.children.append(sql_node)
                    child.is_leaf = False  # Mapper 节点不再是叶子
                    
                    logger.debug(f"Added SQL node for {child.package_class}.{child.method_name}: "
                               f"{sql_info['sql_type']} on {sql_info.get('tables', [])}")
```

### 阶段 6: Workflow 集成（P2 - 集成）

#### 2.6.1 修改 workflow1.py 和 workflow2.py

**文件**: `jcci/src/jcci/workflow/workflow1.py` 和 `workflow2.py`

**修改位置**: 在调用 `build_call_chains_for_changes` 之前，初始化 Mapper 索引和 DAO 分析器

```python
# 在 workflow1.py 的 main() 函数中，调用链分析部分之前添加：

from jcci.call_chain.mapper_index import MapperMethodIndex
from jcci.call_chain.dao_analyzer import DaoAnalyzer
from jcci.call_chain.downwards_builder import DownwardsCallChainBuilder

# ... 原有代码 ...

# 在 Step 6: 双向调用链分析 之前添加：

logger.info("\n" + "="*80)
logger.info("Step 5.5: 构建 MyBatis Mapper 索引")
logger.info("="*80)

# 确定源码目录
source_dir = os.path.dirname(git_url) if git_url else '.'
if not os.path.exists(source_dir):
    source_dir = '.'

# 构建 Mapper 索引（仅对增量 project_id）
mapper_index = MapperMethodIndex(sqlite, project_id, source_dir)
try:
    mapper_index.build_index()
    logger.info(f"✅ Mapper 索引构建完成: {len(mapper_index.mapper_map)} 个方法")
except Exception as e:
    logger.warning(f"⚠️ Mapper 索引构建失败: {e}")
    mapper_index = None

# 创建 DAO 分析器
dao_analyzer = None
if mapper_index:
    dao_analyzer = DaoAnalyzer(mapper_index)
    logger.info("✅ DAO 分析器初始化完成")

# Step 6: 双向调用链分析
logger.info("\n" + "="*80)
logger.info("Step 6: 双向调用链分析（向上影响面 + 向下功能风险）")
logger.info("="*80)

# 获取变更方法列表
changed_methods = result1.get('change_summary', {}).get('methods', [])

# 调用双向分析（传入 dao_analyzer）
bidirectional_result = build_call_chains_for_changes(
    username=username,
    git_url=git_url,
    commit_old=commit_old,
    commit_new=commit_new,
    changed_methods=changed_methods,
    max_depth=5,
    output_dir=output_dir,
    enable_cha=True,
    enable_entry_detection=True,
    dao_analyzer=dao_analyzer  # 新增：传入 DAO 分析器
)
```

#### 2.6.2 修改 analyzer.py 中的 build_call_chains_for_changes

**文件**: `jcci/src/jcci/call_chain/analyzer.py`

**修改**: 接收 `dao_analyzer` 参数并传递给 DownwardsCallChainBuilder

```python
def build_call_chains_for_changes(username, git_url, commit_old, commit_new, 
                                  changed_methods, max_depth=5, output_dir=None,
                                  enable_cha=True, enable_entry_detection=True,
                                  dao_analyzer=None):  # 新增参数
    """
    为变更方法构建双向调用链
    
    Args:
        ...
        dao_analyzer: 可选的 DAO 分析器实例
    """
    # ... 原有代码 ...
    
    # 4. 构建向下调用链（使用 DownwardsCallChainBuilder）
    logger.info(f"\n开始向下调用链分析（功能风险）...")
    
    downwards_builder = DownwardsCallChainBuilder(
        unified_index=unified_index,
        max_depth=max_depth,
        dao_analyzer=dao_analyzer,  # 传入 DAO 分析器
        class_hierarchy=class_hierarchy
    )
    
    # ... 后续代码不变 ...
```

---

## 三、关键技术点说明

### 3.1 接口-实现类映射对向下分析的影响

**问题场景**:
```java
// Service 接口
public interface UserService {
    void updateUser(User user);
}

// Service 实现
@Service
public class UserServiceImpl implements UserService {
    @Autowired
    private UserMapper userMapper;
    
    @Override
    public void updateUser(User user) {
        userMapper.updateById(user);  // 实际调用在这里
    }
}

// Controller 调用
@RestController
public class UserController {
    @Autowired
    private UserService userService;  // 注入的是接口
    
    @PostMapping("/update")
    public Result update(@RequestBody User user) {
        userService.updateUser(user);  // 静态分析看到的是接口调用
    }
}
```

**影响**:
1. **向上分析**（谁调用了变更方法）：
   - 如果 `UserServiceImpl.updateUser` 被修改
   - 需要找到所有调用 `UserService.updateUser`（接口）的地方
   - 通过 CHA 可以正确追溯到 `UserController.update`

2. **向下分析**（变更方法调用了谁）：
   - 如果 `UserServiceImpl.updateUser` 被修改
   - 需要分析它调用了 `UserMapper.updateById`
   - 然后进一步分析 SQL 语句
   - **关键点**: 必须从实现类（`UserServiceImpl`）出发，而不是接口

**解决方案**:
- 在向下分析时，如果起始方法是接口，先通过 CHA 找到所有实现类
- 对每个实现类分别构建向下调用链
- 合并结果并去重

### 3.2 CHA 在向下分析中的应用

修改 `analyzer.py` 中的向下分析部分：

```python
# 对于每个变更方法，检查是否为接口方法
for method_info in methods_to_analyze:
    package_class = method_info['class_name']
    method_signature = method_info['method_signature']
    
    # 如果是接口或抽象类，通过 CHA 找到实现类
    if class_hierarchy and class_hierarchy.is_interface_or_abstract_class(package_class):
        impl_methods = class_hierarchy.resolve_interface_call(
            package_class, method_signature
        )
        
        if impl_methods:
            logger.info(f"接口方法 {package_class}.{method_signature} "
                       f"有 {len(impl_methods)} 个实现:")
            for impl in impl_methods:
                logger.info(f"  - {impl['package_class']}.{impl['method_signature']}")
            
            # 对所有实现类构建向下调用链
            for impl in impl_methods:
                root_node = downwards_builder.build(
                    impl['package_class'],
                    impl['method_signature']
                )
                # 收集结果...
        else:
            # 没有找到实现类，按原逻辑处理
            root_node = downwards_builder.build(package_class, method_signature)
    else:
        # 非接口方法，直接构建
        root_node = downwards_builder.build(package_class, method_signature)
```

---

## 四、测试验证

### 4.1 单元测试

创建测试文件 `test_mapper_integration.py`:

```python
#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
测试 MyBatis Mapper 链路集成功能
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from jcci.database import SqliteHelper
from jcci.call_chain.mapper_index import MapperMethodIndex
from jcci.call_chain.dao_analyzer import DaoAnalyzer


def test_mapper_parsing(db_path, project_id, source_dir):
    """测试 Mapper XML 解析"""
    print("="*80)
    print("测试 1: Mapper XML 解析")
    print("="*80)
    
    sqlite = SqliteHelper(db_path)
    mapper_index = MapperMethodIndex(sqlite, project_id, source_dir)
    
    # 构建索引
    mapper_index.build_index()
    
    # 验证索引
    print(f"\n索引大小: {len(mapper_index.mapper_map)} 个方法")
    
    # 测试查询
    test_methods = [
        ('com.macro.mall.mapper.UmsMenuMapper', 'selectById'),
        ('com.macro.mall.mapper.OmsOrderMapper', 'getList'),
    ]
    
    for package_class, method_name in test_methods:
        sql_info = mapper_index.get_sql_by_java_method(package_class, method_name)
        if sql_info:
            print(f"\n✅ {package_class}.{method_name}")
            print(f"   SQL 类型: {sql_info['sql_type']}")
            print(f"   涉及表: {sql_info.get('tables', [])}")
            print(f"   SQL 内容: {sql_info.get('sql_content', '')[:100]}...")
        else:
            print(f"\n❌ {package_class}.{method_name} - 未找到")
    
    return len(mapper_index.mapper_map) > 0


def test_dao_analyzer(db_path, project_id, source_dir):
    """测试 DAO 分析器"""
    print("\n" + "="*80)
    print("测试 2: DAO 分析器")
    print("="*80)
    
    sqlite = SqliteHelper(db_path)
    mapper_index = MapperMethodIndex(sqlite, project_id, source_dir)
    mapper_index.build_index()
    
    dao_analyzer = DaoAnalyzer(mapper_index)
    
    # 测试分析
    test_cases = [
        ('com.macro.mall.mapper.UmsMenuMapper', 'updateById', 'updateById(Long)'),
    ]
    
    for package_class, method_name, signature in test_cases:
        result = dao_analyzer.analyze(package_class, signature)
        if result:
            print(f"\n✅ {package_class}.{method_name}")
            print(f"   SQL 类型: {result['sql_type']}")
            print(f"   风险等级: {result['risk_level']}")
            print(f"   警告: {result['warning']}")
        else:
            print(f"\n❌ {package_class}.{method_name} - 分析失败")
    
    return True


if __name__ == "__main__":
    if len(sys.argv) >= 4:
        db_path = sys.argv[1]
        project_id = int(sys.argv[2])
        source_dir = sys.argv[3]
        
        test1_pass = test_mapper_parsing(db_path, project_id, source_dir)
        test2_pass = test_dao_analyzer(db_path, project_id, source_dir)
        
        print("\n" + "="*80)
        print(f"测试结果: {'✅ 全部通过' if test1_pass and test2_pass else '❌ 有失败'}")
        print("="*80)
    else:
        print("用法: python test_mapper_integration.py <db_path> <project_id> <source_dir>")
```

### 4.2 集成测试

运行完整的 workflow1.py 或 workflow2.py，验证输出中是否包含 SQL 级别的调用链：

```bash
cd c:\Users\carpe\VisualStudioProject\TestPlatform\jcci
python src/jcci/workflow/workflow1.py mall 20260508_01 20260508_02
```

检查 `downwards.txt` 输出，应该看到类似：

```
向下调用链 1：MODIFIED方法 UmsMenuController.updateHidden

UmsMenuController.updateHidden (MODIFIED)
  --> UmsMenuService.updateHidden (UNCHANGED)
    --> UmsMenuServiceImpl.updateHidden (UNCHANGED) [CHA_RESOLVED]
      --> UmsMenuMapper.updateHidden (UNCHANGED)
        --> SQL:UPDATE [表: ums_menu]
          SQL: UPDATE ums_menu SET hidden = #{hidden} WHERE id = #{id}
          📝 影响表: ums_menu
          🔍 操作类型: UPDATE
          ⚠️ 风险: 字段 hidden 被修改，需确认索引影响
```

---

## 五、实施计划

### 第一阶段：基础架构（1-2天）
- [ ] 创建数据库迁移脚本
- [ ] 增强 `mapper_parse.py`
- [ ] 创建 `mapper_index.py`
- [ ] 创建 `dao_analyzer.py`

### 第二阶段：集成开发（1-2天）
- [ ] 增强 `DownwardsCallChainBuilder`
- [ ] 修改 `analyzer.py` 支持 DAO 分析器
- [ ] 修改 `workflow1.py` 和 `workflow2.py`
- [ ] 处理接口-实现类映射（CHA 集成）

### 第三阶段：测试优化（1天）
- [ ] 编写单元测试
- [ ] 运行集成测试
- [ ] 性能优化
- [ ] 文档更新

### 第四阶段：部署验证（0.5天）
- [ ] 在实际项目中测试
- [ ] 收集反馈
- [ ] 修复问题

---

## 六、预期效果

完成实施后，JCCI 将能够：

1. ✅ **完整追踪 MyBatis Mapper 链路**：
   - Java Controller → Service → Mapper → SQL
   - 展示 SQL 语句、涉及表、操作类型

2. ✅ **智能风险评估**：
   - 自动识别高风险操作（如无 WHERE 的 UPDATE）
   - 标记受影响的表和字段

3. ✅ **正确处理接口-实现类映射**：
   - 向上分析：通过 CHA 追溯接口调用方
   - 向下分析：通过 CHA 展开接口实现

4. ✅ **提升分析准确性**：
   - 减少假阴性（漏报）
   - 提供更详细的影响面信息

---

## 七、注意事项

1. **性能考虑**：
   - Mapper XML 解析可能较慢，建议缓存结果
   - 大型项目中可能有数百个 XML 文件

2. **兼容性**：
   - 确保向后兼容，不破坏现有功能
   - DAO 分析器为可选组件

3. **错误处理**：
   - XML 解析失败不应中断整个分析流程
   - 记录详细日志便于调试

4. **扩展性**：
   - 未来可扩展支持 JPA/Hibernate
   - 可添加 SQL 语法分析（如 EXPLAIN）

---

**文档版本**: v1.0  
**创建日期**: 2026-05-11  
**作者**: Lingma AI Assistant
