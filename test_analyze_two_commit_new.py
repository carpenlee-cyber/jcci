import sys
import os

# 添加 src 目录到模块搜索路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from jcci import JCCI


def demo_analyze_two_commit_incremental():
    """
    演示如何使用新版analyze_two_commit_new功能
    特性：
    1. 无需branch参数
    2. 自动复用基线数据
    3. 不同基线使用独立数据库
    4. 输出方法级变更详情
    """
    print("\n" + "="*60)
    print("开始演示analyze_two_commit_new功能...")
    print("="*60)
    
    # 创建JCCI实例
    commit_analyze = JCCI('https://github.com/carpenlee-cyber/mall.git', 'carpenlee-cyber')
    
    # 第一次分析：解析基线commit1 + 目标commit2
    print("\n【第1次分析】分析 commit2 vs commit1（需要解析基线）")
    print("-" * 60)
    try:
        result1 = commit_analyze.analyze_two_commit_incremental(
            'f2ace8377d2767195bbbf2ffa5c092eddc307895',  # commit_new
            '83abb8e12940519121e74d372e47a4df30e216dc'   # commit_old (基线)
        )
        print("✓ 分析完成！")
        print(f"  - CCI文件: {result1['cci_file_path']}")
        print(f"  - 影响API数: {len(result1['impacted_api_list'])}")
        print(f"  - 方法变更数: {len(result1['method_changes'])}")
        
        # 显示方法变更详情
        if result1['method_changes']:
            print("\n  方法变更详情:")
            for i, change in enumerate(result1['method_changes'][:5], 1):  # 只显示前5个
                print(f"    {i}. [{change['change_type']}] {change['method_signature']}")
                if change['change_type'] == 'MODIFIED':
                    print(f"       - 旧版本行号: {change['old_start_line']}")
                    print(f"       - 新版本行号: {change['new_start_line']}")
        
    except Exception as e:
        print(f"✗ 分析过程中发生错误: {e}")
        import traceback
        traceback.print_exc()
    
    # # 第二次分析：复用基线commit1，仅解析commit3
    # print("\n【第2次分析】分析 commit3 vs commit1（应复用基线，速度更快）")
    # print("-" * 60)
    # try:
    #     result2 = commit_analyze.analyze_two_commit_incremental(
    #         '248196a1106deddd7fc5c4e8bfacdfb22d4808fa',  # commit_new (示例)
    #         '83abb8e12940519121e74d372e47a4df30e216dc'   # commit_old (同一基线，应复用)
    #     )
    #     print("✓ 分析完成！")
    #     print(f"  - CCI文件: {result2['cci_file_path']}")
    #     print(f"  - 影响API数: {len(result2['impacted_api_list'])}")
    #     print(f"  - 方法变更数: {len(result2['method_changes'])}")
        
    #     # 显示方法变更详情
    #     if result1['method_changes']:
    #         print("\n  方法变更详情:")
    #         for i, change in enumerate(result2['method_changes'][:5], 1):  # 只显示前5个
    #             print(f"    {i}. [{change['change_type']}] {change['method_signature']}")
    #             if change['change_type'] == 'MODIFIED':
    #                 print(f"       - 旧版本行号: {change['old_start_line']}")
    #                 print(f"       - 新版本行号: {change['new_start_line']}")
        
    # except Exception as e:
    #     print(f"✗ 分析过程中发生错误: {e}")
    
    # # 第三次分析：基线变更为commit2，创建新数据库
    # print("\n【第3次分析】分析 commit3 vs commit2（基线变更，创建新数据库）")
    # print("-" * 60)
    # try:
    #     result3 = commit_analyze.analyze_two_commit_incremental(
    #         '248196a1106deddd7fc5c4e8bfacdfb22d4808fa',  # commit_new
    #         'f9add0f8f9668f4669c9fad6817acc428734e876'   # commit_old (新基线)
    #     )
    #     print("✓ 分析完成！")
    #     print(f"  - CCI文件: {result3['cci_file_path']}")
    #     print(f"  - 影响API数: {len(result3['impacted_api_list'])}")
    #     print(f"  - 方法变更数: {len(result3['method_changes'])}")
        
    #     # 显示方法变更详情
    #     if result3['method_changes']:
    #         print("\n  方法变更详情:")
    #         for i, change in enumerate(result3['method_changes'][:5], 1):  # 只显示前5个
    #             print(f"    {i}. [{change['change_type']}] {change['method_signature']}")
    #             if change['change_type'] == 'MODIFIED':
    #                 print(f"       - 旧版本行号: {change['old_start_line']}")
    #                 print(f"       - 新版本行号: {change['new_start_line']}")
        
    # except Exception as e:
    #     print(f"✗ 分析过程中发生错误: {e}")
    
    # print("\n" + "="*60)
    # print("演示完成！")
    # print("="*60)


if __name__ == "__main__":
    # 运行新测试
    demo_analyze_two_commit_incremental()
