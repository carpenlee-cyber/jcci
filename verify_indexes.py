"""
数据库索引优化验证脚本

验证所有性能优化索引是否已正确创建
"""

import sys
import os
import sqlite3

# 添加项目根目录到 Python 路径
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from src.jcci.database import SqliteHelper


def verify_indexes(db_helper):
    """验证数据库索引"""
    
    # 预期的索引列表
    expected_indexes = [
        'idx_methods_project_class',
        'idx_methods_name',
        'idx_methods_api_path',
        'idx_class_commit_project',
        'idx_class_name',
        'idx_field_class_project',
        'idx_import_path',
        'idx_mapper_namespace_method',
        'idx_mapper_sql_type',
        'idx_llm_cache_lookup',
    ]
    
    print("=" * 80)
    print("🔍 数据库索引验证")
    print("=" * 80)
    print()
    
    # 查询所有索引
    conn = db_helper.connect()
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_%'")
    existing_indexes = [row[0] for row in cursor.fetchall()]
    
    print(f"📊 现有索引数量: {len(existing_indexes)}")
    print()
    
    # 验证每个预期索引
    all_passed = True
    for idx_name in expected_indexes:
        if idx_name in existing_indexes:
            print(f"✅ {idx_name}")
        else:
            print(f"❌ {idx_name} - 缺失!")
            all_passed = False
    
    print()
    print("-" * 80)
    
    if all_passed:
        print("✅ 所有索引验证通过!")
    else:
        print("❌ 部分索引缺失，请检查数据库初始化")
    
    print()
    
    # 显示索引详细信息
    print("📋 索引详细信息:")
    print("-" * 80)
    
    for idx_name in expected_indexes:
        if idx_name in existing_indexes:
            cursor.execute(f"PRAGMA index_info({idx_name})")
            columns = cursor.fetchall()
            col_names = [col[2] for col in columns]
            print(f"  {idx_name}: ({', '.join(col_names)})")
    
    print()
    print("=" * 80)
    
    conn.close()
    return all_passed


def test_index_performance(db_helper):
    """测试索引性能提升"""
    
    print()
    print("=" * 80)
    print("⚡ 索引性能测试")
    print("=" * 80)
    print()
    
    conn = db_helper.connect()
    cursor = conn.cursor()
    
    # 测试1: methods 表查询性能
    print("🧪 测试1: methods 表 project_id + class_id 查询")
    cursor.execute("EXPLAIN QUERY PLAN SELECT * FROM methods WHERE project_id=1 AND class_id=1")
    plan = cursor.fetchall()
    print(f"   查询计划: {plan}")
    
    # 检查是否使用了索引
    uses_index = any('INDEX' in str(row).upper() or 'SEARCH' in str(row).upper() for row in plan)
    if uses_index:
        print("   ✅ 使用索引优化")
    else:
        print("   ⚠️  未使用索引（可能数据量太小）")
    
    print()
    
    # 测试2: class 表查询性能
    print("🧪 测试2: class 表 commit_or_branch + project_id 查询")
    cursor.execute("EXPLAIN QUERY PLAN SELECT * FROM class WHERE commit_or_branch='test' AND project_id=1")
    plan = cursor.fetchall()
    print(f"   查询计划: {plan}")
    
    uses_index = any('INDEX' in str(row).upper() or 'SEARCH' in str(row).upper() for row in plan)
    if uses_index:
        print("   ✅ 使用索引优化")
    else:
        print("   ⚠️  未使用索引（可能数据量太小）")
    
    print()
    
    # 测试3: llm_analysis_cache 表查询性能
    print("🧪 测试3: llm_analysis_cache 缓存查找")
    cursor.execute("""
        EXPLAIN QUERY PLAN 
        SELECT * FROM llm_analysis_cache 
        WHERE analysis_type='method' 
        AND direction='downwards' 
        AND class_name='Test' 
        AND method_name='test'
    """)
    plan = cursor.fetchall()
    print(f"   查询计划: {plan}")
    
    uses_index = any('INDEX' in str(row).upper() or 'SEARCH' in str(row).upper() for row in plan)
    if uses_index:
        print("   ✅ 使用索引优化")
    else:
        print("   ⚠️  未使用索引（可能数据量太小）")
    
    print()
    print("=" * 80)
    
    conn.close()


if __name__ == "__main__":
    # 创建临时数据库进行测试
    test_db_path = os.path.join(project_root, "test_indexes.db")
    
    try:
        # 创建数据库助手实例
        db_helper = SqliteHelper(test_db_path)
        
        # 验证索引
        passed = verify_indexes(db_helper)
        
        # 性能测试
        test_index_performance(db_helper)
        
        # 返回结果
        if passed:
            print("\n✅ 索引优化验证完成!")
            sys.exit(0)
        else:
            print("\n❌ 索引优化验证失败!")
            sys.exit(1)
    
    finally:
        # 清理测试数据库
        if os.path.exists(test_db_path):
            os.remove(test_db_path)
            print(f"\n🗑️  已清理测试数据库: {test_db_path}")
