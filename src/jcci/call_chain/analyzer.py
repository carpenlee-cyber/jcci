"""
调用链路分析器

提供批量构建方法调用链的能力，支持基线+增量数据合并。
v3.1 新增：支持双向分析（向上影响面分析 + 向下功能风险分析）
"""

import json
import logging
import os
from typing import List, Dict, Any, Optional

from .index import UnifiedMethodIndex
from .builder import CallChainBuilder
from .upwards_builder import ReverseCallerIndex, UpwardsCallChainBuilder
from .downwards_builder import DownwardsCallChainBuilder

logger = logging.getLogger(__name__)


def _get_baseline_db_path(username: str, project_name: str, commit_old: str) -> str:
    """
    构造基线数据库路径
    
    Args:
        username: Git 用户名
        project_name: 项目名称
        commit_old: 旧版本 commit hash
    
    Returns:
        str: 基线数据库完整路径
    """
    from src.jcci import config
    
    commit_short = commit_old[:7] if len(commit_old) > 7 else commit_old
    db_filename = f"{username}_{project_name}_baseline_{commit_short}.db"
    return os.path.join(config.db_path, db_filename)


def _extract_method_signature(method_name: str, parameters_json: str) -> str:
    """
    从方法名和参数 JSON 提取方法签名
    
    Args:
        method_name: 方法名
        parameters_json: 参数的 JSON 字符串，如 '[{"parameter_type": "Long"}]'
    
    Returns:
        str: 方法签名，如 "delete(Long)"
    """
    try:
        params = json.loads(parameters_json) if parameters_json else []
        param_types = [p.get('parameter_type', '') for p in params]
        return f"{method_name}({','.join(param_types)})"
    except (json.JSONDecodeError, AttributeError):
        # 如果解析失败，返回简单形式
        return f"{method_name}()"


def _resolve_package_class(db, class_name: str, incremental_project_id: int) -> Optional[str]:
    """
    解析完整的 package_class（先查增量，再查基线）
    
    Args:
        db: 数据库连接对象
        class_name: 类名
        incremental_project_id: 增量 project_id
    
    Returns:
        str: 完整的 package_class，如 "com.macro.mall.service.impl.UmsAdminServiceImpl"
             或 None（如果找不到）
    """
    # 方案A: 先查增量 project_id
    sql_incremental = f'''
        SELECT DISTINCT package_name FROM class 
        WHERE class_name = "{class_name}" AND project_id = {incremental_project_id}
    '''
    
    result_list = db.select_data(sql_incremental)
    result = result_list[0] if result_list else None
    
    if result:
        package_name = result['package_name'] if isinstance(result, dict) else result[0]
        return f"{package_name}.{class_name}"
    
    # 再查基线 (project_id = 0)
    sql_baseline = f'''
        SELECT DISTINCT package_name FROM class 
        WHERE class_name = "{class_name}" AND project_id = 0
    '''
    
    result_list = db.select_data(sql_baseline)
    result = result_list[0] if result_list else None
    
    if result:
        package_name = result['package_name'] if isinstance(result, dict) else result[0]
        return f"{package_name}.{class_name}"
    
    return None


def build_call_chains_for_changes(
    username: str,
    git_url: str,
    commit_old: str,
    commit_new: str,
    changed_methods: List[Dict[str, Any]],
    max_depth: int = 5,
    output_dir: Optional[str] = None
) -> Dict[str, Any]:
    """
    为变更的方法批量构建调用链
    
    Args:
        username: Git 用户名
        git_url: Git 仓库 URL
        commit_old: 旧版本 commit hash
        commit_new: 新版本 commit hash
        changed_methods: 变更方法列表（来自 change_summary.methods）
            格式: [
                {
                    'class_name': 'UmsAdminServiceImpl',
                    'method_name': 'delete',
                    'parameters': '[{"parameter_type": "Long"}]',
                    'return_type': 'CommonResult',
                    'change_type': 'MODIFIED'
                },
                ...
            ]
        max_depth: 调用链最大深度（默认 5）
        output_dir: 输出目录（默认为 analyze_result）
    
    Returns:
        dict: 包含元数据和所有调用链的结果
            {
                "metadata": {
                    "username": "...",
                    "git_url": "...",
                    "commit_old": "...",
                    "commit_new": "...",
                    "total_methods": 10,
                    "successful_chains": 8,
                    "failed_chains": 2,
                    "output_file": "/path/to/result.json"
                },
                "call_chains": [
                    {
                        "method_info": {...},
                        "chain": {...}  # CallChainNode.to_dict()
                    },
                    ...
                ],
                "failed_methods": [
                    {
                        "method_info": {...},
                        "error": "错误信息"
                    },
                    ...
                ]
            }
    """
    # === 步骤1: 准备阶段 ===
   
    # 提取项目名称
    project_name = git_url.split('/')[-1].split('.git')[0]
    
    # 构造基线数据库路径
    baseline_db_path = _get_baseline_db_path(username, project_name, commit_old)
    logger.info(f"基线数据库路径: {baseline_db_path}")
    
    if not os.path.exists(baseline_db_path):
        raise FileNotFoundError(f"基线数据库不存在: {baseline_db_path}")
    
    # 设置默认输出目录
    if output_dir is None:
        output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'analyze_result')
    
    os.makedirs(output_dir, exist_ok=True)
    
    # === 步骤2: 构建统一索引（一次性，复用）===
    logger.info("\n[1/4] 构建统一方法索引...")
    try:
        index = UnifiedMethodIndex(
            db_path=baseline_db_path,
            commit_old=commit_old,
            commit_new=commit_new
        )
        logger.info("✓ 统一索引构建完成")
        logger.info(f"  - 增量 project_id: {index.project_id}")
        logger.info(f"  - 基线 project_id: {index.baseline_project_id}")
        logger.info(f"  - 索引方法数: {len(index._unified_index)}")
    except Exception as e:
        logger.error(f"✗ 统一索引构建失败: {e}")
        raise
    
    # === 步骤3: 创建调用链构建器 ===
    logger.info("\n[2/4] 创建调用链构建器...")
    builder = CallChainBuilder(index, max_depth=max_depth)
    logger.info(f"✓ 调用链构建器创建完成 (max_depth={max_depth})")
    
    # === 步骤4: 批量构建调用链 ===
    logger.info(f"\n[3/4] 开始批量构建 {len(changed_methods)} 个方法的调用链...")
    
    call_chains = []
    failed_methods = []
    
    for idx, method_info in enumerate(changed_methods, 1):
        class_name = method_info.get('class_name', '')
        method_name = method_info.get('method_name', '')
        parameters_json = method_info.get('parameters', '')
        change_type = method_info.get('change_type', 'UNKNOWN')
        
        logger.info(f"\n  方法 [{idx}/{len(changed_methods)}] 处理: {class_name}.{method_name} ({change_type})")
        
        try:
            # 4.1 解析完整的 package_class
            package_class = _resolve_package_class(
                index.db, 
                class_name, 
                index.project_id
            )
            
            if not package_class:
                raise ValueError(f"无法找到类 {class_name} 的完整包名")
            
            logger.info(f"    - package_class: {package_class}")
            
            # 4.2 构造方法签名
            method_signature = _extract_method_signature(method_name, parameters_json)
            logger.info(f"    - method_signature: {method_signature}")
            
            # 4.3 构建调用链
            chain = builder.build(package_class, method_signature)
            
            # 4.4 记录成功结果
            call_chains.append({
                "method_info": method_info,
                "package_class": package_class,
                "method_signature": method_signature,
                "chain": chain.to_dict()
            })
            
            logger.info(f"    ✓ 调用链构建成功 (节点数: {count_nodes(chain)})")
        
        except Exception as e:
            # 错误处理方案A: 跳过该方法，记录警告
            logger.warning(f"    ✗ 调用链构建失败: {e}")
            failed_methods.append({
                "method_info": method_info,
                "error": str(e)
            })
    
    # === 步骤5: 结果组织与保存 ===
    logger.info("\n[4/4] 整理结果并保存...")
    
    # 构造输出文件名
    commit_old_short = commit_old[:7] if len(commit_old) > 7 else commit_old
    commit_new_short = commit_new[:7] if len(commit_new) > 7 else commit_new
    output_filename = f"{commit_old_short}..{commit_new_short}_call_chains.json"
    output_filepath = os.path.join(output_dir, output_filename)
    
    # 组织结果
    result = {
        "metadata": {
            "username": username,
            "git_url": git_url,
            "project_name": project_name,
            "commit_old": commit_old,
            "commit_new": commit_new,
            "total_methods": len(changed_methods),
            "successful_chains": len(call_chains),
            "failed_chains": len(failed_methods),
            "output_file": output_filepath,
            "max_depth": max_depth
        },
        "call_chains": call_chains,
        "failed_methods": failed_methods
    }
    
    # 保存到 JSON 文件
    with open(output_filepath, 'w', encoding='utf-8') as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    
    logger.info(f"✓ 结果已保存到: {output_filepath}")
    
    # 打印格式化的 JSON 到控制台
    logger.info(f"调用链路分析结果摘要：{json.dumps(result["metadata"], indent=2, ensure_ascii=False)}")
    logger.info("执行完成！")

    
    return result


def count_nodes(node) -> int:
    """
    递归计算调用链节点数
    
    Args:
        node: CallChainNode 实例
    
    Returns:
        int: 节点总数
    """
    count = 1
    for child in node.children:
        count += count_nodes(child)
    return count


ANALYSIS_LIMITATIONS = [
    {
        "id": "DYNAMIC_DISPATCH",
        "severity": "HIGH",
        "description": "无法覆盖通过反射、Lambda、方法引用、动态代理发起的调用",
        "examples": ["Spring AOP 代理方法", "MyBatis Mapper 动态绑定", "反射调用 invoke()"],
        "impact": "向上分析可能遗漏实际调用者，结果属于'过于乐观的下界'"
    },
    {
        "id": "INTERFACE_RESOLUTION",
        "severity": "MEDIUM", 
        "description": "CHA 解析基于静态类层次，无法处理运行时类型确定",
        "examples": ["条件分支中不同实现类赋值", "工厂模式返回类型"],
        "impact": "可能包含不可达调用路径（假阳性），或遗漏某些实现类（假阴性）"
    },
    {
        "id": "FRAMEWORK_CALLS",
        "severity": "MEDIUM",
        "description": "框架代码（Spring DispatcherServlet、定时任务调度器等）通常不在分析范围内",
        "examples": ["HTTP 请求由 DispatcherServlet 转发", "@Scheduled 由 Spring 调度器触发"],
        "impact": "Controller 方法可能显示为'无静态调用者'，需结合注解识别"
    },
    {
        "id": "NATIVE_CODE",
        "severity": "LOW",
        "description": "JNI 调用、Native 方法无法追踪",
        "examples": ["System.arraycopy()", "文件 IO 的 Native 实现"],
        "impact": "不影响常规业务代码分析"
    }
]


def build_upwards_call_chains(
    username: str,
    git_url: str,
    commit_old: str,
    commit_new: str,
    changed_methods: List[Dict[str, Any]],
    max_depth: int = 10,
    output_dir: Optional[str] = None,
    enable_cha: bool = True,
    enable_entry_detection: bool = True
) -> Dict[str, Any]:
    """
    向上影响分析（增强版）：谁调用了变更方法？
    
    Args:
        username: Git 用户名
        git_url: Git 仓库 URL
        commit_old: 旧版本 commit hash
        commit_new: 新版本 commit hash
        changed_methods: 变更方法列表
        max_depth: 调用链最大深度
        output_dir: 输出目录
        enable_cha: 是否启用 CHA（类层次分析）
        enable_entry_detection: 是否启用入口检测
    
    Returns:
        dict: 包含元数据和所有向上调用链的结果
    """
    project_name = git_url.split('/')[-1].split('.git')[0]
    baseline_db_path = _get_baseline_db_path(username, project_name, commit_old)
    logger.info(f"基线数据库路径: {baseline_db_path}")
    
    if not os.path.exists(baseline_db_path):
        raise FileNotFoundError(f"基线数据库不存在: {baseline_db_path}")
    
    if output_dir is None:
        output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'analyze_result')
    
    os.makedirs(output_dir, exist_ok=True)
    
    logger.info("\n[1/5] 构建统一方法索引...")
    try:
        index = UnifiedMethodIndex(
            db_path=baseline_db_path,
            commit_old=commit_old,
            commit_new=commit_new
        )
        logger.info("✓ 统一索引构建完成")
    except Exception as e:
        logger.error(f"✗ 统一索引构建失败: {e}")
        raise
    
    logger.info("\n[2/5] 构建类层次索引（CHA）...")
    class_hierarchy = None
    if enable_cha:
        try:
            from .class_hierarchy import ClassHierarchyIndex
            conn = index.get_db_connection()
            if hasattr(conn, 'connect'):
                db_conn = conn.connect()
            else:
                db_conn = conn
            
            project_ids = [index.baseline_project_id, index.project_id]
            class_hierarchy = ClassHierarchyIndex(db_conn, project_ids)
            logger.info("✓ 类层次索引构建完成（CHA 支持已启用）")
            
            if hasattr(conn, 'connect'):
                try:
                    db_conn.close()
                except:
                    pass
        except Exception as e:
            logger.warning(f"类层次索引构建失败，CHA 功能将禁用: {e}")
            enable_cha = False
    
    logger.info("\n[3/5] 构建反向调用索引...")
    reverse_index = ReverseCallerIndex(index, class_hierarchy)
    
    logger.info("\n[4/5] 构建入口发现器...")
    entry_detector = None
    if enable_entry_detection:
        try:
            from .entry_detector import AnnotationAwareEntryDetector
            conn = index.get_db_connection()
            if hasattr(conn, 'connect'):
                db_conn = conn.connect()
            else:
                db_conn = conn
            
            project_ids = [index.baseline_project_id, index.project_id]
            entry_detector = AnnotationAwareEntryDetector(db_conn, project_ids)
            logger.info("✓ 注解感知入口发现已启用")
            
            if hasattr(conn, 'connect'):
                try:
                    db_conn.close()
                except:
                    pass
        except Exception as e:
            logger.warning(f"入口发现器构建失败: {e}")
    
    logger.info("\n[5/5] 开始批量构建向上调用链...")
    builder = UpwardsCallChainBuilder(
        reverse_index=reverse_index,
        entry_detector=entry_detector,
        max_depth=max_depth
    )
    
    results = []
    failed = []
    global_coverage = {
        'total_methods': 0,
        'methods_with_callers': 0,
        'methods_without_callers': 0,
        'cha_resolved_calls': 0,
        'direct_calls': 0,
        'cyclic_paths': 0,
        'depth_limited_paths': 0,
        'entry_points_found': 0
    }
    
    for idx, method_info in enumerate(changed_methods, 1):
        class_name = method_info.get('class_name', '')
        method_name = method_info.get('method_name', '')
        parameters_json = method_info.get('parameters', '')
        
        logger.info(f"\n  方法 [{idx}/{len(changed_methods)}] 向上分析: {class_name}.{method_name}")
        
        try:
            package_class = _resolve_package_class(
                index.db, 
                class_name, 
                index.project_id
            )
            
            if not package_class:
                raise ValueError(f"无法找到类 {class_name} 的完整包名")
            
            method_signature = _extract_method_signature(method_name, parameters_json)
            
            chain = builder.build(package_class, method_signature)
            
            meta = getattr(chain, '_analysis_meta', {})
            stats = meta.get('coverage_stats', {})
            for key in global_coverage:
                if key in stats:
                    global_coverage[key] += stats[key]
            
            entry_count = _count_entry_points(chain)
            global_coverage['entry_points_found'] += entry_count
            
            chain_dict = chain.to_dict()
            chain_dict['_analysis_meta'] = meta
            
            results.append({
                "direction": "upwards",
                "method_info": method_info,
                "package_class": package_class,
                "method_signature": method_signature,
                "chain": chain_dict,
                "entry_points": _extract_entry_points(chain),
                "has_incomplete_paths": len(meta.get('limitations', [])) > 0
            })
            
            logger.info(f"    ✓ 向上分析成功 (入口点: {entry_count})")
        
        except Exception as e:
            logger.warning(f"    ✗ 向上分析失败: {e}")
            failed.append({
                "method": method_info,
                "error": str(e)
            })
    
    coverage_rate = 0.0
    if global_coverage['total_methods'] > 0:
        coverage_rate = (global_coverage['methods_with_callers'] / 
                        global_coverage['total_methods'] * 100)
    
    commit_old_short = commit_old[:7] if len(commit_old) > 7 else commit_old
    commit_new_short = commit_new[:7] if len(commit_new) > 7 else commit_new
    output_filename = f"{commit_old_short}..{commit_new_short}_upwards_call_chains.json"
    output_filepath = os.path.join(output_dir, output_filename)
    
    result = {
        "metadata": {
            "direction": "upwards",
            "analysis_version": "3.1",
            "username": username,
            "git_url": git_url,
            "project_name": project_name,
            "commit_old": commit_old,
            "commit_new": commit_new,
            "total_methods": len(changed_methods),
            "successful_chains": len(results),
            "failed_chains": len(failed),
            "output_file": output_filepath,
            "max_depth": max_depth,
            "features_enabled": {
                "class_hierarchy_analysis": enable_cha,
                "entry_detection": enable_entry_detection
            },
            "coverage_stats": {
                **global_coverage,
                "coverage_rate_percent": round(coverage_rate, 2),
                "interpretation": (
                    "覆盖率表示成功找到至少一个调用者的方法比例。"
                    "低覆盖率可能意味着大量调用通过动态绑定/框架发起。"
                )
            }
        },
        "impact_chains": results,
        "failed": failed,
        "analysis_limitations": ANALYSIS_LIMITATIONS,
        "recommendations": _generate_recommendations(global_coverage, enable_cha)
    }
    
    with open(output_filepath, 'w', encoding='utf-8') as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    
    logger.info(f"✓ 向上分析结果已保存到: {output_filepath}")
    
    return result


def build_downwards_call_chains(
    username: str,
    git_url: str,
    commit_old: str,
    commit_new: str,
    changed_methods: List[Dict[str, Any]],
    max_depth: int = 10,
    output_dir: Optional[str] = None
) -> Dict[str, Any]:
    """
    向下调用链分析（功能风险分析）
    
    Args:
        username: Git 用户名
        git_url: Git 仓库 URL
        commit_old: 旧版本 commit hash
        commit_new: 新版本 commit hash
        changed_methods: 变更方法列表
        max_depth: 调用链最大深度
        output_dir: 输出目录
    
    Returns:
        dict: 包含元数据和所有向下调用链的结果
    """
    project_name = git_url.split('/')[-1].split('.git')[0]
    baseline_db_path = _get_baseline_db_path(username, project_name, commit_old)
    logger.info(f"基线数据库路径: {baseline_db_path}")
    
    if not os.path.exists(baseline_db_path):
        raise FileNotFoundError(f"基线数据库不存在: {baseline_db_path}")
    
    if output_dir is None:
        output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'analyze_result')
    
    os.makedirs(output_dir, exist_ok=True)
    
    logger.info("\n[1/3] 构建统一方法索引...")
    index = UnifiedMethodIndex(
        db_path=baseline_db_path,
        commit_old=commit_old,
        commit_new=commit_new
    )
    logger.info("✓ 统一索引构建完成")
    
    logger.info("\n[2/3] 创建向下调用链构建器...")
    builder = DownwardsCallChainBuilder(index, max_depth=max_depth)
    logger.info(f"✓ 向下调用链构建器创建完成 (max_depth={max_depth})")
    
    logger.info("\n[3/3] 开始批量构建向下调用链...")
    results = []
    failed = []
    
    for idx, method_info in enumerate(changed_methods, 1):
        class_name = method_info.get('class_name', '')
        method_name = method_info.get('method_name', '')
        parameters_json = method_info.get('parameters', '')
        
        logger.info(f"\n  方法 [{idx}/{len(changed_methods)}] 向下分析: {class_name}.{method_name}")
        
        try:
            package_class = _resolve_package_class(
                index.db, 
                class_name, 
                index.project_id
            )
            
            if not package_class:
                raise ValueError(f"无法找到类 {class_name} 的完整包名")
            
            method_signature = _extract_method_signature(method_name, parameters_json)
            
            chain = builder.build(package_class, method_signature)
            
            results.append({
                "direction": "downwards",
                "method_info": method_info,
                "package_class": package_class,
                "method_signature": method_signature,
                "chain": chain.to_dict()
            })
            
            logger.info(f"    ✓ 向下分析成功 (节点数: {count_nodes(chain)})")
        
        except Exception as e:
            logger.warning(f"    ✗ 向下分析失败: {e}")
            failed.append({
                "method": method_info,
                "error": str(e)
            })
    
    commit_old_short = commit_old[:7] if len(commit_old) > 7 else commit_old
    commit_new_short = commit_new[:7] if len(commit_new) > 7 else commit_new
    output_filename = f"{commit_old_short}..{commit_new_short}_downwards_call_chains.json"
    output_filepath = os.path.join(output_dir, output_filename)
    
    result = {
        "metadata": {
            "direction": "downwards",
            "analysis_version": "3.1",
            "username": username,
            "git_url": git_url,
            "project_name": project_name,
            "commit_old": commit_old,
            "commit_new": commit_new,
            "total_methods": len(changed_methods),
            "successful_chains": len(results),
            "failed_chains": len(failed),
            "output_file": output_filepath,
            "max_depth": max_depth
        },
        "call_chains": results,
        "failed": failed,
        "analysis_limitations": [l for l in ANALYSIS_LIMITATIONS 
                               if l['id'] in ['DYNAMIC_DISPATCH', 'INTERFACE_RESOLUTION']]
    }
    
    with open(output_filepath, 'w', encoding='utf-8') as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    
    logger.info(f"✓ 向下分析结果已保存到: {output_filepath}")
    
    return result


def build_call_chains_for_changes(
    username: str,
    git_url: str,
    commit_old: str,
    commit_new: str,
    changed_methods: List[Dict[str, Any]],
    max_depth: int = 5,
    output_dir: Optional[str] = None
) -> Dict[str, Any]:
    """
    为变更的方法批量构建双向调用链（向上 + 向下）
    
    Args:
        username: Git 用户名
        git_url: Git 仓库 URL
        commit_old: 旧版本 commit hash
        commit_new: 新版本 commit hash
        changed_methods: 变更方法列表
        max_depth: 调用链最大深度
        output_dir: 输出目录
    
    Returns:
        dict: 包含向上和向下分析结果的组合结果
    """
    logger.info("=" * 80)
    logger.info("开始双向调用链分析（向上影响面 + 向下功能风险）")
    logger.info("=" * 80)
    
    upwards_result = build_upwards_call_chains(
        username=username,
        git_url=git_url,
        commit_old=commit_old,
        commit_new=commit_new,
        changed_methods=changed_methods,
        max_depth=max_depth,
        output_dir=output_dir,
        enable_cha=True,
        enable_entry_detection=True
    )
    
    downwards_result = build_downwards_call_chains(
        username=username,
        git_url=git_url,
        commit_old=commit_old,
        commit_new=commit_new,
        changed_methods=changed_methods,
        max_depth=max_depth,
        output_dir=output_dir
    )
    
    combined_result = {
        "metadata": {
            "analysis_type": "bidirectional",
            "username": username,
            "git_url": git_url,
            "commit_old": commit_old,
            "commit_new": commit_new,
            "total_methods": len(changed_methods),
            "upwards_metadata": upwards_result['metadata'],
            "downwards_metadata": downwards_result['metadata']
        },
        "upwards": upwards_result,
        "downwards": downwards_result
    }
    
    logger.info("=" * 80)
    logger.info("双向调用链分析完成！")
    logger.info(f"向上分析: {upwards_result['metadata']['successful_chains']} 成功, "
               f"{upwards_result['metadata']['failed_chains']} 失败")
    logger.info(f"向下分析: {downwards_result['metadata']['successful_chains']} 成功, "
               f"{downwards_result['metadata']['failed_chains']} 失败")
    logger.info("=" * 80)
    
    return combined_result


def _count_entry_points(chain) -> int:
    """统计调用链中的入口点数量"""
    count = 0
    def traverse(node):
        nonlocal count
        if node.root_type in ['HTTP_API', 'SCHEDULED_TASK', 'EVENT_LISTENER',
                              'MESSAGE_CONSUMER', 'CONTROLLER_BY_CONVENTION']:
            count += 1
        for child in node.children:
            traverse(child)
    traverse(chain)
    return count


def _extract_entry_points(chain) -> List[dict]:
    """提取调用链中的所有入口点信息"""
    entries = []
    def traverse(node):
        if node.root_type in ['HTTP_API', 'SCHEDULED_TASK', 'EVENT_LISTENER',
                              'MESSAGE_CONSUMER', 'CONTROLLER_BY_CONVENTION']:
            entries.append({
                "package_class": node.package_class,
                "method_signature": node.method_signature,
                "root_type": node.root_type,
                "depth_from_change": node.depth
            })
        for child in node.children:
            traverse(child)
    traverse(chain)
    return entries


def _generate_recommendations(coverage_stats: dict, enable_cha: bool) -> List[str]:
    """基于覆盖率生成建议"""
    recommendations = []
    
    coverage_rate = coverage_stats.get('coverage_rate_percent', 0)
    
    if coverage_rate < 30:
        recommendations.append(
            "覆盖率较低（<30%），建议检查是否存在大量动态绑定调用（如 MyBatis Mapper、"
            "Spring AOP）。考虑结合运行时分析补充静态分析盲区。"
        )
    
    if coverage_stats.get('cha_resolved_calls', 0) > 0 and not enable_cha:
        recommendations.append(
            "检测到接口调用但 CHA 未启用，建议启用 enable_cha=True 以提高覆盖率。"
        )
    
    if coverage_stats.get('depth_limited_paths', 0) > 0:
        recommendations.append(
            f"存在 {coverage_stats['depth_limited_paths']} 条路径因深度限制被截断，"
            "如需完整分析请增加 max_depth。"
        )
    
    if coverage_stats.get('entry_points_found', 0) == 0 and coverage_stats['methods_with_callers'] > 0:
        recommendations.append(
            "未识别到框架入口点（Controller/Scheduler），建议确认注解数据是否完整加载。"
        )
    
    if not recommendations:
        recommendations.append("分析结果看起来完整，未发现明显问题。")
    
    return recommendations
