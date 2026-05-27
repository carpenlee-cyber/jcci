"""
埋点功能验证测试

验证以下内容：
1. 数据库表结构包含新字段
2. workflow1 函数接受新参数
3. task_manager.submit_task 接受新参数
"""

import sqlite3
import os
import sys

# 添加项目路径
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

def test_database_schema():
    """测试数据库表结构"""
    print("=" * 80)
    print("测试1: 数据库表结构")
    print("=" * 80)
    
    db_path = os.path.join(os.path.dirname(__file__), "task_manager.db")
    
    if not os.path.exists(db_path):
        print("❌ 数据库文件不存在")
        return False
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # 检查表是否存在
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='analysis_tasks'")
    if not cursor.fetchone():
        print("❌ analysis_tasks 表不存在")
        conn.close()
        return False
    
    # 获取所有字段
    cursor.execute("PRAGMA table_info(analysis_tasks)")
    columns = {col[1]: col[2] for col in cursor.fetchall()}
    
    # 检查必需的新字段
    required_fields = {
        'project_code': 'TEXT',
        'task_stage': 'TEXT',
        'user_ip': 'TEXT',
        'user_name': 'TEXT',
        'user_id': 'TEXT'
    }
    
    all_passed = True
    for field, expected_type in required_fields.items():
        if field in columns:
            actual_type = columns[field]
            if actual_type == expected_type:
                print(f"✅ {field}: {actual_type}")
            else:
                print(f"⚠️  {field}: 期望 {expected_type}, 实际 {actual_type}")
                all_passed = False
        else:
            print(f"❌ {field}: 缺失")
            all_passed = False
    
    conn.close()
    
    if all_passed:
        print("\n✅ 数据库表结构测试通过")
    else:
        print("\n❌ 数据库表结构测试失败")
    
    return all_passed


def test_workflow1_signature():
    """测试 workflow1 函数签名"""
    print("\n" + "=" * 80)
    print("测试2: workflow1 函数签名")
    print("=" * 80)
    
    try:
        from webapp.workflow1 import workflow1
        import inspect
        
        sig = inspect.signature(workflow1)
        params = list(sig.parameters.keys())
        
        required_params = ['user_ip', 'user_name', 'user_id', 'project_code', 'task_stage']
        
        all_passed = True
        for param in required_params:
            if param in params:
                default = sig.parameters[param].default
                print(f"✅ {param}: 存在 (默认值: {repr(default)})")
            else:
                print(f"❌ {param}: 缺失")
                all_passed = False
        
        if all_passed:
            print("\n✅ workflow1 函数签名测试通过")
        else:
            print("\n❌ workflow1 函数签名测试失败")
        
        return all_passed
        
    except Exception as e:
        print(f"❌ 导入或检查失败: {e}")
        return False


def test_submit_task_signature():
    """测试 submit_task 函数签名"""
    print("\n" + "=" * 80)
    print("测试3: submit_task 函数签名")
    print("=" * 80)
    
    try:
        from webapp.task_manager import AsyncTaskManager
        import inspect
        
        sig = inspect.signature(AsyncTaskManager.submit_task)
        params = list(sig.parameters.keys())
        
        required_params = ['project_code', 'task_stage', 'user_ip', 'user_name', 'user_id']
        
        all_passed = True
        for param in required_params:
            if param in params:
                default = sig.parameters[param].default
                print(f"✅ {param}: 存在 (默认值: {repr(default)})")
            else:
                print(f"❌ {param}: 缺失")
                all_passed = False
        
        if all_passed:
            print("\n✅ submit_task 函数签名测试通过")
        else:
            print("\n❌ submit_task 函数签名测试失败")
        
        return all_passed
        
    except Exception as e:
        print(f"❌ 导入或检查失败: {e}")
        return False


def main():
    print("\n🧪 开始埋点功能验证测试\n")
    
    results = []
    
    # 运行测试
    results.append(("数据库表结构", test_database_schema()))
    results.append(("workflow1 函数签名", test_workflow1_signature()))
    results.append(("submit_task 函数签名", test_submit_task_signature()))
    
    # 总结
    print("\n" + "=" * 80)
    print("测试总结")
    print("=" * 80)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for test_name, result in results:
        status = "✅ 通过" if result else "❌ 失败"
        print(f"{test_name}: {status}")
    
    print(f"\n总计: {passed}/{total} 测试通过")
    
    if passed == total:
        print("\n🎉 所有测试通过！埋点功能已成功实现。")
        return 0
    else:
        print("\n⚠️  部分测试失败，请检查上述错误。")
        return 1


if __name__ == "__main__":
    sys.exit(main())
