# -*- coding: UTF-8 -*-
import xml.etree.ElementTree as ET
import re
from typing import List, Dict, Optional, Set

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
                 sql_content=None, tables=None, dynamic_conditions=None):
        super(MapperStatement, self).__init__(id, type, start_line, end_line, content)
        self.statement_tag = statement_tag
        self.result_map = result_map
        self.include_sql = include_sql
        self.parameter_type = parameter_type  # 新增：参数类型
        self.result_type = result_type  # 新增：返回类型
        self.sql_content = sql_content  # 新增：SQL语句内容（已解析include）
        self.tables = tables or []  # 新增：涉及的表名列表
        self.dynamic_conditions = dynamic_conditions or []  # 新增：动态SQL条件

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


def extract_sql_content(element, sql_fragments: Dict[str, str] = None, 
                       dynamic_conditions: List[str] = None) -> str:
    """
    递归提取 SQL 内容，支持 <include> 解析和动态SQL条件记录
    
    Args:
        element: XML元素
        sql_fragments: SQL片段字典 {refid: sql_content}
        dynamic_conditions: 动态SQL条件列表（用于记录）
        
    Returns:
        提取的SQL文本
    """
    if sql_fragments is None:
        sql_fragments = {}
    if dynamic_conditions is None:
        dynamic_conditions = []
    
    sql_parts = []
    
    # 处理元素的文本内容
    if element.text and element.text.strip():
        sql_parts.append(element.text.strip())
    
    # 递归处理子元素
    for child in element:
        if child.tag == 'include':
            # ✅ 修复缺陷1：解析 <include> 引用的SQL片段
            refid = child.get('refid', '')
            if refid in sql_fragments:
                sql_parts.append(sql_fragments[refid])
            else:
                # 如果找不到引用，保留占位符以便调试
                sql_parts.append(f"/* include: {refid} */")
        
        elif child.tag in ['if', 'foreach', 'choose', 'when', 'otherwise']:
            # ✅ 修复缺陷3：记录动态SQL条件
            if child.tag == 'if':
                condition = child.get('test', '')
                dynamic_conditions.append(condition)
                sql_parts.append(f"/* IF: {condition} */")
            elif child.tag == 'foreach':
                collection = child.get('collection', '')
                dynamic_conditions.append(f"FOREACH: {collection}")
                sql_parts.append(f"/* FOREACH: {collection} */")
            
            # 递归提取内部SQL
            sql_parts.append(extract_sql_content(child, sql_fragments, dynamic_conditions))
        
        elif child.tag in ['where', 'set', 'trim']:
            # 处理特殊标签
            sql_parts.append(extract_sql_content(child, sql_fragments, dynamic_conditions))
        
        # 处理元素的尾部文本
        if child.tail and child.tail.strip():
            sql_parts.append(child.tail.strip())
    
    return ' '.join(sql_parts)


def extract_tables_from_sql(sql_text: str) -> List[str]:
    """
    从 SQL 文本中提取表名（增强版，支持复杂SQL）
    
    Args:
        sql_text: SQL语句文本
        
    Returns:
        表名列表
    """
    if not sql_text:
        return []
    
    # ✅ 建议1：增强正则，支持更多模式
    patterns = [
        # FROM / INTO / UPDATE
        r'(?:FROM|INTO|UPDATE)\s+[`"\']?(\w+)[`"\']?',
        # JOIN (支持别名)
        r'(?:JOIN)\s+[`"\']?(\w+)[`"\']?(?:\s+\w+)?(?:\s+(?:ON|USING|,)|$)',
        # 子查询中的FROM（简单处理）
        r'(?:FROM|JOIN)\s*\(\s*SELECT.*?FROM\s+[`"\']?(\w+)[`"\']?',
    ]
    
    tables = set()
    for pattern in patterns:
        matches = re.findall(pattern, sql_text, re.IGNORECASE | re.DOTALL)
        tables.update(matches)
    
    # 过滤SQL关键字
    keywords = {'SELECT', 'WHERE', 'AND', 'OR', 'SET', 'VALUES', 'GROUP', 'ORDER', 
                'BY', 'HAVING', 'LIMIT', 'OFFSET', 'UNION', 'ALL', 'DISTINCT',
                'CASE', 'WHEN', 'THEN', 'END', 'IF', 'ELSE', 'NULL', 'NOT',
                'IN', 'EXISTS', 'BETWEEN', 'LIKE', 'IS', 'AS', 'ON'}
    tables = {t for t in tables if t.upper() not in keywords}
    
    return sorted(list(tables))

def parse(filepath: str) -> Optional[Mapper]:
    """
    解析 MyBatis Mapper XML 文件（修复版：支持 <include> 和动态SQL）
    
    Args:
        filepath: XML文件路径
        
    Returns:
        Mapper对象，解析失败返回None
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
    
    # 存储resultMap、SQL片段和语句信息
    result_map_info = []
    sql_info = []
    statement_info = []

    # ✅ 修复缺陷2：先提取所有 <sql> 片段建立索引
    sql_fragments = {}
    for sql_element in root.findall(".//sql"):
        sql_id = sql_element.attrib.get("id")
        if sql_id:
            # 递归提取SQL片段内容（支持嵌套include）
            sql_fragments[sql_id] = extract_sql_content(sql_element, sql_fragments)
            
            # 保留原有的行号信息
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

    # ✅ 修复缺陷1&2：解析 <select>/<insert>/<update>/<delete>，传入 sql_fragments
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
        
        # ✅ 新增：提取SQL内容和表名（支持include和动态SQL）
        dynamic_conditions = []
        sql_content = extract_sql_content(statement_element, sql_fragments, dynamic_conditions)
        tables = extract_tables_from_sql(sql_content)
        
        statement_info.append(MapperStatement(
            statement_id, 'statement', start_line, end_line, content, 
            statement_element.tag, result_map, include_sql,
            parameter_type=parameter_type,
            result_type=result_type,
            sql_content=sql_content,
            tables=tables,
            dynamic_conditions=dynamic_conditions
        ))

    return Mapper(namespace, result_map_info, sql_info, statement_info)
