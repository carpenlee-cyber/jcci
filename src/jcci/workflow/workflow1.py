
import sys
import os
import logging
import time

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


def extract_short_tag(tag: str) -> str:
    """
    从长tag中提取短标识符（最后11个字符）
    
    例如：
    MIX_LJ01.BUP_BUP3_UAT_UAT_00.00.01_SUMMER_20260403_01 -> 20260403_01
    
    Args:
        tag: 完整的tag字符串
        
    Returns:
        短标识符（最后11个字符）
    """
    if len(tag) <= 11:
        return tag
    return tag[-11:]


def workflow1():
    # 步骤1：配置参数
    logger.info("\n")
    logger.info("步骤1：开始配置参数")
    logger.info("=" * 80)

    # 配置参数 - 支持tag和commit hash
    git_url = 'https://github.com/carpenlee-cyber/mall.git'
    username = 'carpenlee-cyber'
    
    # # 方式1：使用commit hash（用于开发测试）
    # tag_old = 'dd6569c3558f79af5b21aad601349e0f029b9a6d'
    # tag_new = '0db78d7f79c48b7349346c1380408f60ba0c3c54'    
    
    # 方式2：使用长tag名称（生产环境示例）
    tag_old = 'baseline_20260508_01'
    tag_new = 'baseline_fix1_20260508_02'
    # tag_old = 'MIX_LJ01.BUP_BUP3_UAT_UAT_00.00.01_SUMMER_20260403_01'
    # tag_new = 'MIX_LJ01.BUP_BUP3_UAT_UAT_00.00.01_SUMMER_20260403_02'
    
    # 提取短标识符用于本地文件和数据库存储（最后11个字符）
    # 对于短commit hash（<=11字符），保持不变
    commit_old = extract_short_tag(tag_old)  # d9501e9
    commit_new = extract_short_tag(tag_new)  # 78e3a22

    logger.info(f"  - git_url: {git_url}")
    logger.info(f"  - username: {username}")
    logger.info(f"  - tag_old (完整): {tag_old}")
    logger.info(f"  - tag_new (完整): {tag_new}")
    logger.info(f"  - commit_old (短标识): {commit_old}")
    logger.info(f"  - commit_new (短标识): {commit_new}")

        
    # 步骤2：调用analyze_two_commit_incremental
    logger.info("\n")
    logger.info("步骤2：调用JCI新方法, 第一次调用（预期为首次分析，将创建 JSON 缓存）, 重复调用将使用缓存")
    logger.info(f"  - 使用完整tag调用Git: {tag_old}..{tag_new}")
    
    jcci1 = JCCI(git_url, username)
    result1 = jcci1.analyze_two_commit_incremental(
        commit_new=tag_new,  # 使用完整tag进行Git操作
        commit_old=tag_old   # 使用完整tag进行Git操作
    )

    if result1.get('is_duplicate', False):
        logger.warning("检测到重复调用，将使用缓存结果")
    else:
        logger.info("首次调用完成，结果已缓存")


    # 步骤3：双向调用链路分析
    logger.info("\n")
    logger.info("步骤3：双向调用链路分析")
    logger.info("  - 向上分析（影响面）：谁调用了变更方法？→ 寻找受影响的入口 API")
    logger.info("  - 向下分析（功能风险）：变更方法调用了谁？→ 评估功能风险")

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
            commit_old=commit_old,    # 使用短标识符（与基线数据库文件名一致）
            commit_new=commit_new,    # 使用短标识符
            changed_methods=changed_methods,
            max_depth=5
        )
        
        # 步骤4：可视化展示调用链
        logger.info("步骤4：调用链可视化展示")
        
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
        
        # 将结果写入文件（使用新的目录结构：基线目录/版本子目录）
        baseline_dir = os.path.join(project_root, "src", "jcci", "analyze_result", f"mall_{commit_old}")
        version_subdir = os.path.join(baseline_dir, commit_new)
        os.makedirs(version_subdir, exist_ok=True)
        
        # 写入向上调用链
        upwards_file = os.path.join(version_subdir, "upwards.txt")
        with open(upwards_file, 'w', encoding='utf-8') as f:
            f.write(upwards_text)
        logger.info(f"向上调用链已保存到: {upwards_file}")
        
        # 写入向下调用链
        downwards_file = os.path.join(version_subdir, "downwards.txt")
        with open(downwards_file, 'w', encoding='utf-8') as f:
            f.write(downwards_text)
        logger.info(f"向下调用链已保存到: {downwards_file}")
        
        # 步骤5：启动Streamlit Web服务进行可视化展示和LLM分析
        logger.info("\n")
        logger.info("步骤5：启动Streamlit Web服务")
        logger.info("=" * 80)
        logger.info("  - 提供可视化的调用链展示界面")
        logger.info("  - 支持点击方法/调用链进行AI智能分析")
        logger.info("  - 自动查询数据库获取详细信息")
        logger.info("  - 集成LLM生成测试建议和变更分析")
        logger.info("=" * 80)
        
        import subprocess
        import webbrowser
        import threading
        import socket
        
        streamlit_script = os.path.join(os.path.dirname(__file__), "streamlit_app.py")
        
        if os.path.exists(streamlit_script):
            # 尝试导入配置
            try:
                sys.path.insert(0, os.path.dirname(__file__))
                from config import STREAMLIT_PORT, STREAMLIT_HOST
            except ImportError:
                STREAMLIT_PORT = 8501
                STREAMLIT_HOST = "0.0.0.0"
                logger.warning("未找到config.py，使用默认配置")
            
            logger.info(f"启动Streamlit服务: {streamlit_script}")
            logger.info(f"服务地址: http://{STREAMLIT_HOST}:{STREAMLIT_PORT}")
            
            # 获取本地IP用于分享
            try:
                hostname = socket.gethostname()
                local_ip = socket.gethostbyname(hostname)
                logger.info(f"局域网访问: http://{local_ip}:{STREAMLIT_PORT}")
            except:
                pass
            
            logger.info("按 Ctrl+C 停止服务")
            
            # 在后台启动Streamlit
            def start_streamlit():
                subprocess.run([
                    sys.executable, "-m", "streamlit", "run", 
                    streamlit_script,
                    "--server.port", str(STREAMLIT_PORT),
                    "--server.address", STREAMLIT_HOST,
                    "--server.headless", "true"
                ])
            
            # 延迟2秒后自动打开浏览器
            def open_browser():
                time.sleep(2)
                # 使用baseline参数实现基线隔离
                webbrowser.open(f"http://localhost:{STREAMLIT_PORT}/?baseline=mall_{commit_old}")
            
            # 启动浏览器打开线程
            browser_thread = threading.Thread(target=open_browser, daemon=True)
            browser_thread.start()
            
            # 启动Streamlit（阻塞）
            try:
                start_streamlit()
            except KeyboardInterrupt:
                logger.info("\nStreamlit服务已停止")
        else:
            logger.warning(f"Streamlit脚本不存在: {streamlit_script}")


if __name__ == "__main__":
    workflow1()
