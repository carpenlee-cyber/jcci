"""
调用链路分析器

提供批量构建方法调用链的能力，支持基线+增量数据合并。
"""

import json
import logging
import os
from typing import List, Dict, Any, Optional

from .index import UnifiedMethodIndex
from .builder import CallChainBuilder

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
