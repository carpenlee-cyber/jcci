"""
MyBatis Mapper 链路追踪功能验证脚本

验证步骤：
1. 解析 mall 项目的 XML 文件
2. 构建 Mapper 索引
3. 测试 SQL 提取和风险评估
4. 验证向下调用链中的 SQL 节点生成
"""

import os
import sys
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent))

from src.jcci.mapper_parse import parse, extract_tables_from_sql
from src.jcci.call_chain.dao_analyzer import DaoAnalyzer
from src.jcci.call_chain.mapper_index import MapperMethodIndex
from src.jcci.database import SqliteHelper


def test_xml_parsing():
    """测试 XML 解析功能"""
    print("=" * 60)
    print("测试 1: MyBatis XML 解析")
    print("=" * 60)
    
    # 查找 mall 项目中的 XML 文件
    mall_path = r"c:\Users\carpe\VisualStudioProject\TestPlatform\mall"
    
    if not os.path.exists(mall_path):
        print(f"⚠️  mall 项目不存在: {mall_path}")
        return False
    
    # 查找第一个 Mapper XML
    xml_files = []
    for root, dirs, files in os.walk(mall_path):
        for file in files:
            if file.endswith('Mapper.xml'):
                xml_files.append(os.path.join(root, file))
                if len(xml_files) >= 3:
                    break
        if len(xml_files) >= 3:
            break
    
    if not xml_files:
        print("❌ 未找到 Mapper XML 文件")
        return False
    
    print(f"\n✓ 找到 {len(xml_files)} 个 Mapper XML 文件\n")
    
    # 解析每个 XML
    for i, xml_file in enumerate(xml_files[:3], 1):
        print(f"[{i}] 解析: {os.path.basename(xml_file)}")
        
        try:
            mapper = parse(xml_file)
            
            if mapper:
                print(f"    命名空间: {mapper.namespace}")
                print(f"    语句数量: {len(mapper.statements)}")
                
                # 显示前2个语句
                for stmt in mapper.statements[:2]:
                    print(f"      - {stmt.statement_tag.upper()}: {stmt.id}")
                    if hasattr(stmt, 'tables') and stmt.tables:
                        print(f"        表名: {', '.join(stmt.tables)}")
                    if hasattr(stmt, 'sql_content') and stmt.sql_content:
                        sql_preview = stmt.sql_content[:80].replace('\n', ' ')
                        print(f"        SQL: {sql_preview}...")
                
                print(f"    ✓ 解析成功\n")
            else:
                print(f"    ❌ 解析失败\n")
                
        except Exception as e:
            print(f"    ❌ 错误: {e}\n")
    
    return True


def test_table_extraction():
    """测试表名提取功能"""
    print("\n" + "=" * 60)
    print("测试 2: SQL 表名提取")
    print("=" * 60)
    
    test_cases = [
        ("SELECT * FROM ums_menu WHERE id = #{id}", ["ums_menu"]),
        ("UPDATE ums_menu SET hidden = #{hidden} WHERE id = #{id}", ["ums_menu"]),
        ("DELETE FROM ums_resource WHERE id = #{id}", ["ums_resource"]),
        ("INSERT INTO ums_admin (username, password) VALUES (#{username}, #{password})", ["ums_admin"]),
        ("SELECT m.* FROM ums_menu m JOIN ums_admin_menu_relation amr ON m.id = amr.menu_id", ["ums_menu", "ums_admin_menu_relation"]),
    ]
    
    all_passed = True
    
    for sql, expected_tables in test_cases:
        tables = extract_tables_from_sql(sql)
        passed = set(tables) == set(expected_tables)
        
        status = "✓" if passed else "❌"
        print(f"\n{status} SQL: {sql[:60]}...")
        print(f"   期望: {expected_tables}")
        print(f"   实际: {tables}")
        
        if not passed:
            all_passed = False
    
    return all_passed


def test_risk_assessment():
    """测试风险评估功能"""
    print("\n" + "=" * 60)
    print("测试 3: SQL 风险评估")
    print("=" * 60)
    
    # 创建临时数据库和分析器
    import tempfile
    temp_dir = tempfile.mkdtemp()
    db_path = os.path.join(temp_dir, 'test.db')
    db_helper = SqliteHelper(db_path)
    
    # 创建表
    db_helper.update_data("""
        CREATE TABLE IF NOT EXISTS mapper_methods (
            mapper_id INTEGER PRIMARY KEY AUTOINCREMENT,
            full_method TEXT,
            sql_type TEXT,
            tables TEXT,
            sql_content TEXT,
            project_id INTEGER DEFAULT 0,
            is_dynamic_sql INTEGER DEFAULT 0,
            dynamic_conditions TEXT
        )
    """)
    
    index = MapperMethodIndex(db_helper, 0, temp_dir)
    analyzer = DaoAnalyzer(index)
    
    # 测试用例
    test_cases = [
        ("DELETE FROM user", "CRITICAL", "缺少 WHERE"),
        ("UPDATE user SET status = 1", "CRITICAL", "缺少 WHERE"),
        ("SELECT * FROM user", "MEDIUM", None),  # 无WHERE的SELECT是MEDIUM风险
        ("SELECT * FROM user WHERE id = 1", "LOW", None),
        ("INSERT INTO user (name) VALUES ('test')", "LOW", None),
    ]
    
    all_passed = True
    
    for sql, expected_risk, expected_warning_keyword in test_cases:
        # 模拟 SQL 信息
        sql_type = sql.split()[0].upper()
        tables = extract_tables_from_sql(sql)
        is_dynamic = False
        
        risk_level, warning = analyzer._assess_risk(sql_type, tables, sql, is_dynamic)
        
        risk_passed = risk_level == expected_risk
        warning_passed = True
        if expected_warning_keyword:
            warning_passed = expected_warning_keyword in warning
        
        passed = risk_passed and warning_passed
        status = "✓" if passed else "❌"
        
        print(f"\n{status} SQL: {sql[:50]}")
        print(f"   风险等级: {risk_level} (期望: {expected_risk})")
        if warning:
            print(f"   警告: {warning[:80]}")
        
        if not passed:
            all_passed = False
    
    # 清理
    import shutil
    shutil.rmtree(temp_dir)
    
    return all_passed


def test_performance_analysis():
    """测试SQL性能分析功能"""
    print("\n" + "=" * 60)
    print("测试 4: SQL性能分析 (v4.0 新增)")
    print("=" * 60)
    
    from src.jcci.call_chain.sql_performance_analyzer import SqlPerformanceAnalyzer
    
    analyzer = SqlPerformanceAnalyzer()
    
    # 测试用例
    test_cases = [
        {
            'name': '全表扫描',
            'sql_info': {
                'sql_type': 'SELECT',
                'sql_content': 'SELECT * FROM ums_menu',
                'tables': ['ums_menu']
            },
            'expected_issues': 2,  # FULL_TABLE_SCAN + SELECT_STAR
            'expected_max_score': 70
        },
        {
            'name': 'LIKE通配符',
            'sql_info': {
                'sql_type': 'SELECT',
                'sql_content': "SELECT * FROM user WHERE name LIKE '%test%'",
                'tables': ['user']
            },
            'expected_issues': 2,  # SELECT_STAR + LIKE_WILDCARD
            'expected_max_score': 70
        },
        {
            'name': '正常查询',
            'sql_info': {
                'sql_type': 'SELECT',
                'sql_content': 'SELECT id, name FROM user WHERE id = #{id}',
                'tables': ['user']
            },
            'expected_issues': 0,
            'expected_min_score': 90
        },
    ]
    
    all_passed = True
    
    for test_case in test_cases:
        report = analyzer.analyze(test_case['sql_info'])
        
        issues_passed = len(report.issues) == test_case['expected_issues']
        score_passed = True
        if 'expected_max_score' in test_case:
            score_passed = report.score <= test_case['expected_max_score']
        elif 'expected_min_score' in test_case:
            score_passed = report.score >= test_case['expected_min_score']
        
        passed = issues_passed and score_passed
        status = "✓" if passed else "❌"
        
        print(f"\n{status} {test_case['name']}")
        print(f"   问题数: {len(report.issues)} (期望: {test_case['expected_issues']})")
        print(f"   性能评分: {report.score}/100 ({report.level})")
        
        if report.issues:
            print(f"   检测到的问题:")
            for issue in report.issues:
                print(f"     - [{issue.severity}] {issue.message}")
        
        if not passed:
            all_passed = False
    
    return all_passed


def test_field_lineage():
    """测试字段血缘追踪功能"""
    print("\n" + "=" * 60)
    print("测试 5: 字段血缘追踪 (v4.0 新增)")
    print("=" * 60)
    
    from src.jcci.call_chain.field_lineage_tracker import FieldLineageTracker
    
    tracker = FieldLineageTracker()
    
    # 测试用例1: INSERT语句
    insert_sql = {
        'sql_type': 'INSERT',
        'sql_content': 'INSERT INTO ums_user (username, password, email) VALUES (#{username}, #{password}, #{email})',
        'tables': ['ums_user'],
        'mapper_method': 'com.macro.mall.mapper.UmsUserMapper.insert'
    }
    
    lineage1 = tracker.track_from_sql(insert_sql, insert_sql['mapper_method'])
    
    print(f"\n✓ INSERT语句字段提取")
    print(f"   写入字段数: {len(lineage1.writes)}")
    print(f"   字段列表: {[f'{t}.{c}' for t, c, m in lineage1.writes]}")
    
    insert_passed = len(lineage1.writes) == 3
    
    # 测试用例2: SELECT语句
    select_sql = {
        'sql_type': 'SELECT',
        'sql_content': 'SELECT id, username, email FROM ums_user WHERE id = #{id}',
        'tables': ['ums_user'],
        'mapper_method': 'com.macro.mall.mapper.UmsUserMapper.selectByPrimaryKey'
    }
    
    lineage2 = tracker.track_from_sql(select_sql, select_sql['mapper_method'])
    
    print(f"\n✓ SELECT语句字段提取")
    print(f"   读取字段数: {len(lineage2.reads)}")
    print(f"   字段列表: {[f'{t}.{c}' for t, c, m in lineage2.reads]}")
    
    select_passed = len(lineage2.reads) == 3
    
    # 测试用例3: 影响分析
    impact = tracker.analyze_impact('ums_user', 'username')
    
    print(f"\n✓ 字段影响分析")
    print(f"   总影响数: {impact.total_impact}")
    print(f"   风险等级: {impact.risk_level}")
    print(f"   建议: {impact.recommendations[0] if impact.recommendations else '无'}")
    
    impact_passed = impact.risk_level in ['LOW', 'MEDIUM', 'HIGH']
    
    # 测试用例4: 统计信息
    stats = tracker.get_statistics()
    
    print(f"\n✓ 血缘追踪统计")
    print(f"   追踪字段总数: {stats['total_fields_tracked']}")
    print(f"   有来源的字段: {stats['fields_with_sources']}")
    print(f"   有消费者的字段: {stats['fields_with_consumers']}")
    
    stats_passed = stats['total_fields_tracked'] > 0
    
    return insert_passed and select_passed and impact_passed and stats_passed


def main():
    """主函数"""
    print("\n" + "=" * 60)
    print("MyBatis Mapper 链路追踪功能验证")
    print("=" * 60 + "\n")
    
    results = []
    
    # 测试 1: XML 解析
    try:
        result1 = test_xml_parsing()
        results.append(("XML 解析", result1))
    except Exception as e:
        print(f"❌ XML 解析测试异常: {e}")
        results.append(("XML 解析", False))
    
    # 测试 2: 表名提取
    try:
        result2 = test_table_extraction()
        results.append(("表名提取", result2))
    except Exception as e:
        print(f"❌ 表名提取测试异常: {e}")
        results.append(("表名提取", False))
    
    # 测试 3: 风险评估
    try:
        result3 = test_risk_assessment()
        results.append(("风险评估", result3))
    except Exception as e:
        print(f"❌ 风险评估测试异常: {e}")
        results.append(("风险评估", False))
    
    # 测试 4: 性能分析
    try:
        result4 = test_performance_analysis()
        results.append(("性能分析", result4))
    except Exception as e:
        print(f"❌ 性能分析测试异常: {e}")
        results.append(("性能分析", False))
    
    # 测试 5: 字段血缘
    try:
        result5 = test_field_lineage()
        results.append(("字段血缘", result5))
    except Exception as e:
        print(f"❌ 字段血缘测试异常: {e}")
        results.append(("字段血缘", False))
    
    # 汇总结果
    print("\n" + "=" * 60)
    print("测试结果汇总")
    print("=" * 60)
    
    for test_name, passed in results:
        status = "✅ 通过" if passed else "❌ 失败"
        print(f"{test_name:20s} {status}")
    
    total = len(results)
    passed = sum(1 for _, p in results if p)
    
    print(f"\n总计: {passed}/{total} 测试通过")
    
    if passed == total:
        print("\n🎉 所有测试通过！MyBatis Mapper 功能正常工作。")
        return 0
    else:
        print(f"\n⚠️  {total - passed} 个测试失败，需要修复。")
        return 1


if __name__ == '__main__':
    sys.exit(main())
