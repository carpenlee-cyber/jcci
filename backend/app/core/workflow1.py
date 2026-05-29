import sys
import os
import logging
import time

# 添加项目根目录到 Python 路径（jcci/）
# 当前文件: jcci/backend/app/core/workflow1.py
# 需要添加到路径: jcci/
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from jcci import JCCI
from jcci.utils.performance_monitor import (
    timer, 
    performance_monitor, 
    print_performance_report,
    get_performance_summary
)
from jcci.utils.tag_utils import extract_short_tag

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)


def workflow1(
    # 必需参数
    git_url: str,
    username: str,
    tag_old: str,
    tag_new: str,
    
    # 可选参数（带默认值）
    max_depth: int = 5,
    enable_streamlit: bool = True,
    streamlit_port: int = 8501,
    streamlit_host: str = "0.0.0.0",
    auto_open_browser: bool = True,
    
    # 高级参数
    log_level: str = "INFO",
    
    # 埋点参数
    user_ip: str = "",
    user_name: str = "网页",
    user_id: str = "web",
    project_code: str = "",
    task_stage: str = ""
):
    """
    Workflow1: 双向调用链路分析
    
    Args:
        git_url: Git仓库地址
        username: GitHub用户名
        tag_old: 基线版本tag/commit hash
        tag_new: 当前版本tag/commit hash
        max_depth: 调用链最大深度（默认5）
        enable_streamlit: 是否启动Web服务（默认True）
        streamlit_port: Streamlit端口（默认8501）
        streamlit_host: Streamlit主机（默认0.0.0.0）
        auto_open_browser: 是否自动打开浏览器（默认True）
        log_level: 日志级别（默认INFO）
    
    Returns:
        包含分析结果的字典
    """
    # 记录整体开始时间
    workflow_start_time = time.time()
    
    # 配置日志级别
    logging.basicConfig(
        level=getattr(logging, log_level.upper(), logging.INFO),
        format='%(asctime)s %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # 步骤1：配置参数
    with timer("Step 1: Parameter Configuration"):
        logger.info("\n")
        logger.info("步骤1：开始配置参数")
        logger.info("=" * 80)

        logger.info(f"  - git_url: {git_url}")
        logger.info(f"  - username: {username}")
        logger.info(f"  - tag_old (完整): {tag_old}")
        logger.info(f"  - tag_new (完整): {tag_new}")
        
        # 提取短标识符用于本地文件和数据库存储
        commit_old = extract_short_tag(tag_old)
        commit_new = extract_short_tag(tag_new)
        
        logger.info(f"  - commit_old (短标识): {commit_old}")
        logger.info(f"  - commit_new (短标识): {commit_new}")

        
    # 步骤2：调用analyze_two_commit_incremental
    with timer("Step 2: Incremental Analysis (JCCI)"):
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
    with timer("Step 3: Bidirectional Call Chain Analysis"):
        logger.info("\n")
        logger.info("步骤3：双向调用链路分析")
        logger.info("  - 向上分析（影响面）：谁调用了变更方法？→ 寻找受影响的入口 API")
        logger.info("  - 向下分析（功能风险）：变更方法调用了谁？→ 评估功能风险")

        from jcci.call_chain.analyzer import build_call_chains_for_changes

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
            with timer("Step 3.1: Initialize MyBatis Mapper Index and DAO Analyzer"):
                logger.info("\n正在初始化 MyBatis Mapper 索引和 DAO 分析器...")
                
                # ✅ 从 analyze_two_commit_incremental 的结果中获取源代码目录
                source_dir = result1.get('source_dir')
                
                if not source_dir or not os.path.exists(source_dir):
                    logger.warning(f"  ⚠️ 源代码目录不存在: {source_dir}，将跳过 SQL 级别追踪")
                    source_dir = None
                else:
                    logger.info(f"  ✓ 源代码目录: {source_dir}")
                
                # ✅ 构建类层次索引（CHA）
                with timer("Step 3.1.1: Build Class Hierarchy Index (CHA)"):
                    logger.info("\n构建类层次索引（CHA）...")
                    from jcci.call_chain.class_hierarchy import ClassHierarchyIndex
                    from jcci.database import SqliteHelper
                    from jcci.utils.path_utils import get_baseline_db_path
                    
                    # 从 git_url 提取项目名
                    project_name = git_url.split('/')[-1].split('.git')[0]
                    
                    # 构造基线数据库路径（使用统一路径管理）
                    db_path = get_baseline_db_path(project_name, commit_old)
                    
                    if not os.path.exists(db_path):
                        logger.error(f"基线数据库不存在: {db_path}")
                        raise FileNotFoundError(f"基线数据库不存在: {db_path}")
                    
                    db = SqliteHelper(db_path)
                    project_rows = db.select_data("SELECT project_id FROM project")
                    project_ids = [row['project_id'] for row in project_rows]
                    
                    class_hierarchy = ClassHierarchyIndex(db.connect(), project_ids)
                    logger.info(f"✓ 类层次索引构建完成：{len(class_hierarchy._class_hierarchy)} 个类，{len(class_hierarchy._interface_impls)} 个接口")
                
                # ✅ 构建 Mapper 索引和 DAO 分析器
                with timer("Step 3.1.2: Build Mapper Index and DAO Analyzer"):
                    logger.info("\n构建 Mapper 索引和 DAO 分析器...")
                    from jcci.call_chain.mapper_index import MapperMethodIndex
                    from jcci.call_chain.dao_analyzer import DaoAnalyzer
                    
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
            
            with timer("Step 3.2: Execute Bidirectional Analysis"):
                bidirectional_result = build_call_chains_for_changes(
                    username=username,
                    git_url=git_url,
                    commit_old=commit_old,    # 使用短标识符（与基线数据库文件名一致）
                    commit_new=commit_new,    # 使用短标识符
                    changed_methods=changed_methods,
                    max_depth=max_depth,  # ✅ 使用参数传入的max_depth
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
        if changed_methods:
            with timer("Step 4: Visualization and File Output"):
                logger.info("步骤4：调用链可视化展示")
                
                from jcci.call_chain.visualizer import CallChainVisualizer
                
                # 打印向上调用链（从双向结果中提取upwards部分）
                upwards_text = CallChainVisualizer.format_upwards_chains(
                    bidirectional_result['upwards']  # 提取upwards部分
                )
                
                # 打印向下调用链（从双向结果中提取downwards部分）
                downwards_text = CallChainVisualizer.format_downwards_chains(
                    bidirectional_result['downwards']  # 提取downwards部分
                )
                
                # 将结果写入文件（使用统一路径管理）
                from jcci.utils.path_utils import get_version_subdir, ensure_dir_exists, get_upwards_txt_path, get_downwards_txt_path
                
                version_subdir = get_version_subdir(project_name, commit_old, commit_new)
                ensure_dir_exists(version_subdir)
                
                # 写入向上调用链
                upwards_file = get_upwards_txt_path(project_name, commit_old, commit_new)
                with open(upwards_file, 'w', encoding='utf-8') as f:
                    f.write(upwards_text)
                
                # 写入向下调用链
                downwards_file = get_downwards_txt_path(project_name, commit_old, commit_new)
                with open(downwards_file, 'w', encoding='utf-8') as f:
                    f.write(downwards_text)
        
        # 步骤5：启动Streamlit Web服务（已弃用，改用 FastAPI 后端）
        if enable_streamlit:
            logger.warning("\n")
            logger.warning("⚠️ Streamlit 模式已弃用，请使用 FastAPI 后端服务")
        
        # ===== 打印性能报告 =====
        workflow_elapsed = time.time() - workflow_start_time
        logger.info("\n")
        logger.info("=" * 80)
        logger.info("📊 工作流执行完成 - 性能分析报告")
        logger.info("=" * 80)
        logger.info(f"总耗时: {workflow_elapsed:.3f}s")
        logger.info("")
        
        # 打印详细性能报告
        print_performance_report()
        
        # 打印性能摘要
        summary = get_performance_summary()
        logger.info(f"\n✅ 分析流程已成功完成！")
        logger.info(f"   总操作数: {summary['total_operations']}")
        logger.info(f"   总耗时: {summary['total_time']:.3f}s")
        logger.info(f"   平均耗时: {summary['average_time']:.3f}s")
        logger.info("=" * 80)
        
        return result1
