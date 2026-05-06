
import sys
import os
import logging

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# 添加项目根目录到 Python 路径（jcci/）
# 当前文件: jcci/src/jcci/workflow/workflow1.py
# 需要添加到路径: jcci/
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from src.jcci import JCCI  # noqa: E402

def workflow1():
    # 步骤1：配置参数
    logger.info("\n" + "=" * 80)
    logger.info("步骤1：开始配置参数")
    logger.info("=" * 80)

    # 配置参数
    git_url = 'https://github.com/carpenlee-cyber/mall.git'
    username = 'carpenlee-cyber'
    commit_old = 'd9501e9'  # Update README.md
    commit_new = '78e3a22'  # test: 添加双向调用链分析测试方法


    logger.info(f"  - git_url: {git_url}")
    logger.info(f"  - username: {username}")
    logger.info(f"  - commit_old: {commit_old}")
    logger.info(f"  - commit_new: {commit_new}")

        
    # 步骤2：调用analyze_two_commit_incremental
    logger.info("\n" + "=" * 80)
    logger.info("步骤2：调用JCI新方法, 第一次调用（预期为首次分析，将创建 JSON 缓存）, 重复调用将使用缓存")
    logger.info("=" * 80)
    
    jcci1 = JCCI(git_url, username)
    result1 = jcci1.analyze_two_commit_incremental(
        commit_new=commit_new,
        commit_old=commit_old
    )

    if result1.get('is_duplicate', False):
        logger.warning("检测到重复调用，将使用缓存结果")
    else:
        logger.info("首次调用完成，结果已缓存")


    # 步骤3：双向调用链路分析
    logger.info("\n" + "=" * 80)
    logger.info("步骤3：双向调用链路分析")
    logger.info("  - 向上分析（影响面）：谁调用了变更方法？→ 寻找受影响的入口 API")
    logger.info("  - 向下分析（功能风险）：变更方法调用了谁？→ 评估功能风险")
    logger.info("=" * 80)

    from src.jcci.call_chain.analyzer import build_call_chains_for_changes

    # 获取变更方法列表
    changed_methods = result1.get('change_summary', {}).get('methods', [])

    if not changed_methods:
        logger.warning("没有变更的方法，跳过调用链路分析")
    else:       
        # 执行双向分析
        bidirectional_result = build_call_chains_for_changes(
            username=username,
            git_url=git_url,
            commit_old=commit_old,
            commit_new=commit_new,
            changed_methods=changed_methods,
            max_depth=5
        )
        
        # 步骤4：可视化展示调用链
        logger.info("\n" + "=" * 80)
        logger.info("步骤4：调用链可视化展示")
        logger.info("=" * 80)
        
        from src.jcci.call_chain.visualizer import CallChainVisualizer
        
        # 打印向上调用链
        upwards_text = CallChainVisualizer.format_upwards_chains(
            bidirectional_result['upwards']
        )
        logger.info(upwards_text)
        
        # 打印向下调用链
        downwards_text = CallChainVisualizer.format_downwards_chains(
            bidirectional_result['downwards']
        )
        logger.info(downwards_text)
        

if __name__ == "__main__":
    workflow1()
