# -*- coding: UTF-8 -*-
"""
JCCI 统一路径管理模块

提供项目所有路径的统一计算函数，避免硬编码路径导致的错误。

使用方式:
    from jcci.utils.path_utils import (
        PROJECT_ROOT,
        RESULT_DIR,
        get_baseline_dir,
        get_version_subdir,
        get_baseline_db_path,
        ensure_dir_exists
    )
"""
import os


# ==================== 常量定义 ====================

# 项目根目录（jcci/ 目录，即 path_utils.py 向上3级）
# path_utils.py 位置: jcci/jcci/utils/path_utils.py
# 向上1级: jcci/jcci/utils/
# 向上2级: jcci/jcci/
# 向上3级: jcci/ (项目根目录)
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 分析结果目录
RESULT_DIR = os.path.join(PROJECT_ROOT, "jcci", "analyze_result")


# ==================== 路径计算函数 ====================

def get_baseline_dir(project_name: str, commit_old: str) -> str:
    """
    获取基线目录路径
    
    Args:
        project_name: 项目名称（如 mall）
        commit_old: 旧版本标识符（如 baseline_20260508_01 或 dd6569c3...）
    
    Returns:
        str: 基线目录完整路径
        例如: c:\\...\\jcci\\analyze_result\\mall_20260508_01
    """
    return os.path.join(RESULT_DIR, f"{project_name}_{commit_old}")


def get_version_subdir(project_name: str, commit_old: str, commit_new: str) -> str:
    """
    获取版本子目录路径
    
    Args:
        project_name: 项目名称
        commit_old: 旧版本标识符
        commit_new: 新版本标识符
    
    Returns:
        str: 版本子目录完整路径
        例如: c:\\...\\jcci\\analyze_result\\mall_20260508_01\\20260508_02
    """
    baseline_dir = get_baseline_dir(project_name, commit_old)
    return os.path.join(baseline_dir, commit_new)


def get_baseline_db_path(project_name: str, commit_old: str) -> str:
    """
    获取基线数据库文件路径
    
    Args:
        project_name: 项目名称
        commit_old: 旧版本标识符
    
    Returns:
        str: 基线数据库完整路径
        例如: c:\\...\\jcci\\analyze_result\\mall_20260508_01\\mall_20260508_01_baseline.db
    """
    baseline_dir = get_baseline_dir(project_name, commit_old)
    db_filename = f"{project_name}_{commit_old}_baseline.db"
    return os.path.join(baseline_dir, db_filename)


def get_analysis_cache_path(project_name: str, commit_old: str, commit_new: str) -> str:
    """
    获取分析结果缓存文件路径（JSON）
    
    Args:
        project_name: 项目名称
        commit_old: 旧版本标识符
        commit_new: 新版本标识符
    
    Returns:
        str: 缓存文件完整路径
        例如: c:\\...\\jcci\\analyze_result\\mall_20260508_01\\20260508_02\\analysis_result.json
    """
    version_dir = get_version_subdir(project_name, commit_old, commit_new)
    return os.path.join(version_dir, "analysis_result.json")


def get_upwards_txt_path(project_name: str, commit_old: str, commit_new: str) -> str:
    """
    获取向上调用链文本文件路径
    
    Args:
        project_name: 项目名称
        commit_old: 旧版本标识符
        commit_new: 新版本标识符
    
    Returns:
        str: 向上调用链文件完整路径
        例如: c:\\...\\jcci\\analyze_result\\mall_20260508_01\\20260508_02\\upwards.txt
    """
    version_dir = get_version_subdir(project_name, commit_old, commit_new)
    return os.path.join(version_dir, "upwards.txt")


def get_downwards_txt_path(project_name: str, commit_old: str, commit_new: str) -> str:
    """
    获取向下调用链文本文件路径
    
    Args:
        project_name: 项目名称
        commit_old: 旧版本标识符
        commit_new: 新版本标识符
    
    Returns:
        str: 向下调用链文件完整路径
        例如: c:\\...\\jcci\\analyze_result\\mall_20260508_01\\20260508_02\\downwards.txt
    """
    version_dir = get_version_subdir(project_name, commit_old, commit_new)
    return os.path.join(version_dir, "downwards.txt")


def get_upwards_json_path(project_name: str, commit_old: str, commit_new: str) -> str:
    """
    获取向上调用链 JSON 文件路径（旧格式）
    
    Args:
        project_name: 项目名称
        commit_old: 旧版本标识符
        commit_new: 新版本标识符
    
    Returns:
        str: 向上调用链 JSON 文件完整路径
    """
    version_dir = get_version_subdir(project_name, commit_old, commit_new)
    return os.path.join(version_dir, "upwards_call_chains.json")


def get_downwards_json_path(project_name: str, commit_old: str, commit_new: str) -> str:
    """
    获取向下调用链 JSON 文件路径（旧格式）
    
    Args:
        project_name: 项目名称
        commit_old: 旧版本标识符
        commit_new: 新版本标识符
    
    Returns:
        str: 向下调用链 JSON 文件完整路径
    """
    version_dir = get_version_subdir(project_name, commit_old, commit_new)
    return os.path.join(version_dir, "downwards_call_chains.json")


def get_upwards_json_gz_path(project_name: str, commit_old: str, commit_new: str) -> str:
    """
    获取向上调用链压缩 JSON 文件路径（v5.0 新增）
    
    Args:
        project_name: 项目名称
        commit_old: 旧版本标识符
        commit_new: 新版本标识符
    
    Returns:
        str: 向上调用链 .json.gz 文件完整路径
    """
    version_dir = get_version_subdir(project_name, commit_old, commit_new)
    return os.path.join(version_dir, "upwards_call_chains.json.gz")


def get_downwards_json_gz_path(project_name: str, commit_old: str, commit_new: str) -> str:
    """
    获取向下调用链压缩 JSON 文件路径（v5.0 新增）
    
    Args:
        project_name: 项目名称
        commit_old: 旧版本标识符
        commit_new: 新版本标识符
    
    Returns:
        str: 向下调用链 .json.gz 文件完整路径
    """
    version_dir = get_version_subdir(project_name, commit_old, commit_new)
    return os.path.join(version_dir, "downwards_call_chains.json.gz")


# ==================== 统一读写函数（v5.0 新增） ====================

def save_call_chains_json(direction: str, data: dict, project_name: str, 
                           commit_old: str, commit_new: str) -> str:
    """
    以紧凑 GZIP 格式保存调用链数据（v5.0 新增）
    
    会自动将链中的节点从标准格式转换为紧凑格式，
    然后以 GZIP 压缩写入 .json.gz 文件。
    
    Args:
        direction: 'upwards' 或 'downwards'
        data: 调用链结果字典（标准格式，含 metadata/impact_chains 或 metadata/call_chains）
        project_name: 项目名称
        commit_old: 旧版本标识符
        commit_new: 新版本标识符
    
    Returns:
        str: 输出文件路径
    """
    import json
    import gzip

    # 选择路径函数
    if direction == 'upwards':
        filepath = get_upwards_json_gz_path(project_name, commit_old, commit_new)
        chains_key = 'impact_chains'
    elif direction == 'downwards':
        filepath = get_downwards_json_gz_path(project_name, commit_old, commit_new)
        chains_key = 'call_chains'
    else:
        raise ValueError(f"direction must be 'upwards' or 'downwards', got: {direction}")
    
    ensure_dir_exists(os.path.dirname(filepath))
    
    # 将链数据中的 CallChainNode dict 转为紧凑格式
    compact_data = dict(data)
    if chains_key in compact_data:
        compact_chains = []
        for chain_entry in compact_data[chains_key]:
            compact_entry = dict(chain_entry)
            if 'chain' in compact_entry:
                # chain 字段是从 CallChainNode.to_dict() 生成的
                compact_entry['chain'] = _compact_chain_node_dict(compact_entry['chain'])
            compact_chains.append(compact_entry)
        compact_data[chains_key] = compact_chains
    
    # 以 GZIP 紧凑 JSON 写入
    with gzip.open(filepath, 'wt', encoding='utf-8') as f:
        json.dump(compact_data, f, separators=(',', ':'), ensure_ascii=False)
    
    return filepath


def load_call_chains_json(direction: str, project_name: str, 
                           commit_old: str, commit_new: str) -> dict:
    """
    统一加载调用链 JSON 数据（v5.0 新增）
    
    优先读取 .json.gz 压缩格式，不存在时回退到旧 .json 格式。
    自动将紧凑格式还原为标准格式以兼容前端。
    
    Args:
        direction: 'upwards' 或 'downwards'
        project_name: 项目名称
        commit_old: 旧版本标识符
        commit_new: 新版本标识符
    
    Returns:
        dict: 调用链数据（标准格式，与旧 .json 格式结构一致）
    
    Raises:
        FileNotFoundError: 两种格式均不存在
    """
    gz_path = get_upwards_json_gz_path(project_name, commit_old, commit_new) if direction == 'upwards' \
              else get_downwards_json_gz_path(project_name, commit_old, commit_new)

    return load_call_chains_json_from_dir(os.path.dirname(gz_path), direction)


def load_call_chains_json_from_dir(data_dir: str, direction: str) -> dict:
    """
    从数据目录加载调用链 JSON（v5.0 新增）
    
    优先读取 .json.gz 压缩格式，不存在时回退到旧 .json 格式。
    自动将紧凑格式还原为标准格式以兼容前端。

    Args:
        data_dir: 版本数据目录（如 .../mall_xxx/yyy/）
        direction: 'upwards' 或 'downwards'

    Returns:
        dict: 调用链数据（标准格式）

    Raises:
        FileNotFoundError: 两种格式均不存在
    """
    import json
    import gzip

    filename = f"{direction}_call_chains"
    gz_path = os.path.join(data_dir, f"{filename}.json.gz")
    json_path = os.path.join(data_dir, f"{filename}.json")

    # 优先读取 .gz 新格式
    if os.path.exists(gz_path):
        with gzip.open(gz_path, 'rt', encoding='utf-8') as f:
            data = json.load(f)
        # 将紧凑格式还原为标准格式
        data = _expand_call_chains_data(data, direction)
        return data

    # 回退到旧 .json 格式
    if os.path.exists(json_path):
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data

    raise FileNotFoundError(f"Call chains file not found for {direction}: {gz_path} or {json_path}")


def _compact_chain_node_dict(node_dict: dict) -> dict:
    """
    将单个标准节点字典转为紧凑格式（递归处理 children）
    
    与 CallChainNode.to_compact_dict() 逻辑一致，但操作纯 dict。
    """
    compact = {}
    
    # 必须保留的字段
    for key in ('package_class', 'method_signature', 'method_name'):
        if key in node_dict:
            compact[key] = node_dict[key]
    
    # 条件保留的字段（非默认值才保留）
    if node_dict.get('depth', 0) != 0:
        compact['depth'] = node_dict['depth']
    
    invocation_lines = node_dict.get('invocation_lines', [])
    if invocation_lines:
        compact['invocation_lines'] = invocation_lines
    
    if node_dict.get('is_cyclic', False):
        compact['is_cyclic'] = True
    
    if node_dict.get('is_leaf', False):
        compact['is_leaf'] = True
    
    if node_dict.get('db_method_id') is not None:
        compact['db_method_id'] = node_dict['db_method_id']
    
    root_type = node_dict.get('root_type', 'UNKNOWN')
    if root_type != 'UNKNOWN':
        compact['root_type'] = root_type
    
    call_type = node_dict.get('call_type', 'DIRECT')
    if call_type != 'DIRECT':
        compact['call_type'] = call_type
    
    if node_dict.get('has_multiple_call_sites', False):
        compact['has_multiple_call_sites'] = True
    
    if node_dict.get('entry_annotation'):
        compact['entry_annotation'] = node_dict['entry_annotation']
    
    api_paths = node_dict.get('api_paths', [])
    if api_paths:
        compact['api_paths'] = api_paths
    
    change_type = node_dict.get('change_type', 'UNCHANGED')
    if change_type not in ('UNCHANGED',):
        compact['change_type'] = change_type
    
    if node_dict.get('dao_info'):
        compact['dao_info'] = node_dict['dao_info']
    
    if node_dict.get('documentation'):
        compact['documentation'] = node_dict['documentation']
    
    # _analysis_meta: 仅在 upwards 链中存在，始终保留
    if '_analysis_meta' in node_dict:
        compact['_analysis_meta'] = node_dict['_analysis_meta']
    
    # 递归处理 children
    children = node_dict.get('children', [])
    if children:
        compact['children'] = [_compact_chain_node_dict(child) for child in children]
    
    return compact


def _expand_call_chains_data(data: dict, direction: str) -> dict:
    """
    将从 .json.gz 加载的紧凑数据还原为标准格式
    
    恢复 node_id、class_name 和所有默认值字段。
    """
    from jcci.call_chain.models import CallChainNode
    
    chains_key = 'impact_chains' if direction == 'upwards' else 'call_chains'
    
    if chains_key in data:
        expanded_chains = []
        for chain_entry in data[chains_key]:
            expanded_entry = dict(chain_entry)
            if 'chain' in expanded_entry:
                expanded_entry['chain'] = CallChainNode.expand_compact_dict(expanded_entry['chain'])
            expanded_chains.append(expanded_entry)
        data[chains_key] = expanded_chains
    
    return data


# ==================== 工具函数 ====================

def ensure_dir_exists(dir_path: str) -> None:
    """
    确保目录存在，不存在则创建
    
    Args:
        dir_path: 目录路径
    """
    if dir_path and not os.path.exists(dir_path):
        os.makedirs(dir_path, exist_ok=True)


def list_baseline_dirs() -> list:
    """
    列出所有可用的基线目录
    
    Returns:
        list: 基线目录名称列表（不包含隐藏目录）
    """
    if not os.path.exists(RESULT_DIR):
        return []
    
    return [
        d for d in os.listdir(RESULT_DIR)
        if os.path.isdir(os.path.join(RESULT_DIR, d)) and not d.startswith('.')
    ]


def list_version_subdirs(project_name: str, commit_old: str) -> list:
    """
    列出指定基线下的所有版本子目录
    
    Args:
        project_name: 项目名称
        commit_old: 旧版本标识符
    
    Returns:
        list: 版本子目录名称列表
    """
    baseline_dir = get_baseline_dir(project_name, commit_old)
    
    if not os.path.exists(baseline_dir):
        return []
    
    return [
        d for d in os.listdir(baseline_dir)
        if os.path.isdir(os.path.join(baseline_dir, d)) and not d.startswith('.')
    ]


# ==================== 测试代码 ====================

if __name__ == "__main__":
    # 测试路径计算
    print("=" * 80)
    print("JCCI 路径管理模块测试")
    print("=" * 80)
    
    print(f"\n📁 项目根目录: {PROJECT_ROOT}")
    print(f"📊 分析结果目录: {RESULT_DIR}")
    
    # 测试示例
    project_name = "mall"
    commit_old = "20260508_01"
    commit_new = "20260508_02"
    
    print(f"\n📋 示例参数:")
    print(f"   项目名: {project_name}")
    print(f"   旧版本: {commit_old}")
    print(f"   新版本: {commit_new}")
    
    print(f"\n🔗 生成的路径:")
    print(f"   基线目录: {get_baseline_dir(project_name, commit_old)}")
    print(f"   版本子目录: {get_version_subdir(project_name, commit_old, commit_new)}")
    print(f"   基线数据库: {get_baseline_db_path(project_name, commit_old)}")
    print(f"   分析缓存: {get_analysis_cache_path(project_name, commit_old, commit_new)}")
    print(f"   向上调用链(TXT): {get_upwards_txt_path(project_name, commit_old, commit_new)}")
    print(f"   向下调用链(TXT): {get_downwards_txt_path(project_name, commit_old, commit_new)}")
    print(f"   向上调用链(JSON): {get_upwards_json_path(project_name, commit_old, commit_new)}")
    print(f"   向下调用链(JSON): {get_downwards_json_path(project_name, commit_old, commit_new)}")
    
    print(f"\n✅ 所有路径计算完成！")
