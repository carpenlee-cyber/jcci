
import sys
import os

# 添加项目根目录到 Python 路径（jcci/）
# 当前文件: jcci/src/jcci/workflow/workflow1.py
# 需要添加到路径: jcci/
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from src.jcci import JCCI

def workflow1():
    # 步骤1：配置参数
    print("\n" + "=" * 80)
    print("步骤1：开始配置参数")
    print("=" * 80)

    # 配置参数
    git_url = 'https://github.com/carpenlee-cyber/mall.git'
    username = 'carpenlee-cyber'
    commit_old = '83fe3e707b99d135deb9de071ce87fe4b07c563f'  # Commits on Jun 9, 2025
    commit_new = 'f9add0f8f9668f4669c9fad6817acc428734e876'  # Commits on Jan 11, 2026


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


    # 步骤3：调用链路分析
    print("\n" + "=" * 80)
    print("步骤3：调用链路分析，开始构建变更方法的调用链路")
    print("=" * 80)

    from src.jcci.call_chain.analyzer import build_call_chains_for_changes

    # 获取变更方法列表
    changed_methods = result1.get('change_summary', {}).get('methods', [])

    if not changed_methods:
        print("⚠️ 没有变更的方法，跳过调用链路分析")
    else:
        # 构建调用链
        call_chain_result = build_call_chains_for_changes(
            username=username,
            git_url=git_url,
            commit_old=commit_old,
            commit_new=commit_new,
            changed_methods=changed_methods,
            max_depth=5
        )
        

if __name__ == "__main__":
    workflow1()
