
import sys
import os

# 添加项目根目录到 Python 路径（jcci/）
# 当前文件: jcci/src/jcci/workflow/workflow1.py
# 需要添加到路径: jcci/
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from src.jcci import JCCI  # noqa: E402

def workflow1():
    # 步骤1：配置参数
    print("\n" + "=" * 80)
    print("步骤1：开始配置参数")
    print("=" * 80)

    # 配置参数
    git_url = 'https://github.com/carpenlee-cyber/mall.git'
    username = 'carpenlee-cyber'
    commit_old = 'd9501e9'  # Update README.md
    commit_new = '78e3a22'  # test: 添加双向调用链分析测试方法


    print(f"  - git_url: {git_url}")
    print(f"  - username: {username}")
    print(f"  - commit_old: {commit_old}")
    print(f"  - commit_new: {commit_new}")

        
    # 步骤2：调用analyze_two_commit_incremental
    print("\n" + "=" * 80)
    print("步骤2：调用JCI新方法, 第一次调用（预期为首次分析，将创建 JSON 缓存）, 重复调用将使用缓存")
    print("=" * 80)
    
    jcci1 = JCCI(git_url, username)
    result1 = jcci1.analyze_two_commit_incremental(
        commit_new=commit_new,
        commit_old=commit_old
    )

    if result1.get('is_duplicate', False):
        print("[WARNING] 检测到重复调用，将使用缓存结果")
    else:
        print("[SUCCESS] 首次调用完成，结果已缓存")


    # 步骤3：双向调用链路分析
    print("\n" + "=" * 80)
    print("步骤3：双向调用链路分析")
    print("  - 向上分析（影响面）：谁调用了变更方法？→ 寻找受影响的入口 API")
    print("  - 向下分析（功能风险）：变更方法调用了谁？→ 评估功能风险")
    print("=" * 80)

    from src.jcci.call_chain.analyzer import build_call_chains_for_changes

    # 获取变更方法列表
    changed_methods = result1.get('change_summary', {}).get('methods', [])

    if not changed_methods:
        print("⚠️ 没有变更的方法，跳过调用链路分析")
    else:
        print(f"\n发现 {len(changed_methods)} 个变更方法，开始双向分析...\n")
        
        # 执行双向分析
        bidirectional_result = build_call_chains_for_changes(
            username=username,
            git_url=git_url,
            commit_old=commit_old,
            commit_new=commit_new,
            changed_methods=changed_methods,
            max_depth=5
        )
        
        # 打印摘要
        upwards_meta = bidirectional_result['upwards']['metadata']
        downwards_meta = bidirectional_result['downwards']['metadata']
        
        print("\n" + "=" * 80)
        print("分析结果摘要")
        print("=" * 80)
        
        print(f"\n【向上分析 - 影响面】")
        print(f"  [成功] {upwards_meta['successful_chains']}")
        print(f"  [失败] {upwards_meta['failed_chains']}")
        print(f"  覆盖率: {upwards_meta['coverage_stats']['coverage_rate_percent']}%")
        print(f"  入口点: {upwards_meta['coverage_stats']['entry_points_found']}")
        print(f"  CHA解析: {upwards_meta['coverage_stats']['cha_resolved_calls']}")
        
        print(f"\n【向下分析 - 功能风险】")
        print(f"  [成功] {downwards_meta['successful_chains']}")
        print(f"  [失败] {downwards_meta['failed_chains']}")
        
        print(f"\n建议:")
        for rec in bidirectional_result['upwards'].get('recommendations', []):
            print(f"  - {rec}")
        
        print("\n" + "=" * 80)
        print("[完成] 双向分析完成！")
        print("=" * 80)
        
        # 步骤4：可视化展示调用链
        print("\n" + "=" * 80)
        print("步骤4：调用链可视化展示")
        print("=" * 80)
        
        from src.jcci.call_chain.visualizer import CallChainVisualizer
        
        # 打印向上调用链
        upwards_text = CallChainVisualizer.format_upwards_chains(
            bidirectional_result['upwards']
        )
        print(upwards_text)
        
        # 打印向下调用链
        downwards_text = CallChainVisualizer.format_downwards_chains(
            bidirectional_result['downwards']
        )
        print(downwards_text)
        

if __name__ == "__main__":
    workflow1()
