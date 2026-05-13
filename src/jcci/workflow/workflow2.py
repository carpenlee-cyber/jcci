
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
# 当前文件: jcci/src/jcci/workflow/workflow2.py
# 需要添加到路径: jcci/
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from src.jcci import JCCI  # noqa: E402


def extract_short_tag(tag: str) -> str:
    """
    从tag或commit hash中提取短标识符
    
    规则：
    - Commit Hash (40位十六进制): 截取前8位
    - Git Tag (长度>11): 截取后11位
    - 短标识符 (长度<=11): 保持不变
    
    例如：
    - dd6569c3558f79af5b21aad601349e0f029b9a6d -> dd6569c3 (commit hash)
    - MIX_LJ01.BUP_BUP3_UAT_UAT_00.00.01_SUMMER_20260403_01 -> 20260403_01 (tag)
    - d9501e9 -> d9501e9 (短标识符)
    
    Args:
        tag: 完整的tag或commit hash字符串
        
    Returns:
        短标识符
    """
    import re
    
    # 判断是否为40位commit hash（十六进制字符串）
    if len(tag) == 40 and re.match(r'^[0-9a-f]{40}$', tag, re.IGNORECASE):
        # Commit hash：截取前8位
        return tag[:8]
    elif '_' in tag or len(tag) > 11:
        # Git Tag（包含下划线或长度>11）：取最后11个字符
        return tag[-11:]
    else:
        # 短标识符：保持不变
        return tag


def workflow2():
    # 步骤1：配置参数
    logger.info("\n")
    logger.info("步骤1：开始配置参数")
    logger.info("=" * 80)

    # 配置参数 - 支持tag和commit hash
    git_url = 'https://github.com/carpenlee-cyber/mall.git'
    username = 'carpenlee-cyber'
    
    # # 方式1：使用commit hash（用于开发测试）
    tag_old = 'dd6569c3558f79af5b21aad601349e0f029b9a6d'
    tag_new = 'dd94f3b4b317e604eee9b96252160e1a5c69785d'    
    
    # 方式2：使用长tag名称（生产环境示例）
    # tag_old = 'baseline_20260508_01'
    # tag_new = 'baseline_fix1_20260508_02'
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
    
    logger.info(f"变更方法总数: {len(changed_methods)}")
    if changed_methods:
        logger.info("变更方法列表:")
        for method in changed_methods[:10]:  # 只显示前10个
            logger.info(f"  - [{method.get('change_type', 'UNKNOWN')}] {method.get('class_name', '')}.{method.get('method_name', '')}")
        if len(changed_methods) > 10:
            logger.info(f"  ... 还有 {len(changed_methods) - 10} 个方法")

    if not changed_methods:
        logger.warning("没有变更的方法，跳过调用链路分析")
    else:       
        # 执行双向分析
        logger.info("\n正在初始化 MyBatis Mapper 索引和 DAO 分析器...")
        
        # ✅ 从 analyze_two_commit_incremental 的结果中获取源代码目录
        source_dir = result1.get('source_dir')
        
        if not source_dir or not os.path.exists(source_dir):
            logger.warning(f"  ⚠️ 源代码目录不存在: {source_dir}，将跳过 SQL 级别追踪")
            source_dir = None
        else:
            logger.info(f"  ✓ 源代码目录: {source_dir}")
        
        # ✅ 构建类层次索引（CHA）
        logger.info("\n构建类层次索引（CHA）...")
        from src.jcci.call_chain.class_hierarchy import ClassHierarchyIndex
        from src.jcci.database import SqliteHelper
        
        # 从 git_url 提取项目名
        project_name = git_url.split('/')[-1].split('.git')[0]
        
        # 构造基线数据库路径
        output_base = os.path.join(project_root, "src", "jcci", "analyze_result")
        db_path = os.path.join(output_base, f"{project_name}_{commit_old}", f"{project_name}_{commit_old}_baseline.db")
        
        if not os.path.exists(db_path):
            logger.error(f"基线数据库不存在: {db_path}")
            raise FileNotFoundError(f"基线数据库不存在: {db_path}")
        
        db = SqliteHelper(db_path)
        result = db.select_data("SELECT project_id FROM project")
        project_ids = [row['project_id'] for row in result]
        
        class_hierarchy = ClassHierarchyIndex(db.connect(), project_ids)
        logger.info(f"✓ 类层次索引构建完成：{len(class_hierarchy._class_hierarchy)} 个类，{len(class_hierarchy._interface_impls)} 个接口")
        
        # ✅ 构建 Mapper 索引和 DAO 分析器
        logger.info("\n构建 Mapper 索引和 DAO 分析器...")
        from src.jcci.call_chain.mapper_index import MapperMethodIndex
        from src.jcci.call_chain.dao_analyzer import DaoAnalyzer
        
        if source_dir and os.path.exists(source_dir):
            # 使用第一个 project_id（通常是基线 project_id=0）
            baseline_project_id = project_ids[0] if project_ids else 0
            mapper_index = MapperMethodIndex(db, baseline_project_id, source_dir)
            mapper_index.build_index()  # ✅ 构建索引
            dao_analyzer = DaoAnalyzer(mapper_index)
            logger.info(f"✓ Mapper 索引和 DAO 分析器构建完成")
        else:
            logger.warning("⚠️ 源代码目录不可用，跳过 Mapper 索引构建，dao_info 将为 null")
            dao_analyzer = None
        
        bidirectional_result = build_call_chains_for_changes(
            username=username,
            git_url=git_url,
            commit_old=commit_old,    # 使用短标识符（与基线数据库文件名一致）
            commit_new=commit_new,    # 使用短标识符
            changed_methods=changed_methods,
            max_depth=5,
            source_dir=source_dir,  # ✅ 传递源代码目录用于 Mapper 索引构建
            class_hierarchy=class_hierarchy,  # ✅ 传递类层次索引用于 CHA 解析
            dao_analyzer=dao_analyzer  # ✅ 传递 DAO 分析器用于 SQL 追踪
        )
        
        # 检查双向分析结果
        logger.info(f"\n双向分析结果摘要:")
        logger.info(f"  向上分析 - 成功: {bidirectional_result['upwards']['metadata']['successful_chains']}, "
                   f"失败: {bidirectional_result['upwards']['metadata']['failed_chains']}")
        logger.info(f"  向下分析 - 成功: {bidirectional_result['downwards']['metadata']['successful_chains']}, "
                   f"失败: {bidirectional_result['downwards']['metadata']['failed_chains']}")
        
        # 步骤4：可视化展示调用链
        logger.info("步骤4：调用链可视化展示")
        
        from src.jcci.call_chain.visualizer import CallChainVisualizer
        
        # 打印向上调用链（从双向结果中提取upwards部分）
        upwards_text = CallChainVisualizer.format_upwards_chains(
            bidirectional_result['upwards']  # 提取upwards部分
        )
        logger.info(upwards_text)
        
        # 打印向下调用链（从双向结果中提取downwards部分）
        downwards_text = CallChainVisualizer.format_downwards_chains(
            bidirectional_result['downwards']  # 提取downwards部分
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
    workflow2()
