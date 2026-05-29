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
    获取向上调用链 JSON 文件路径
    
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
    获取向下调用链 JSON 文件路径
    
    Args:
        project_name: 项目名称
        commit_old: 旧版本标识符
        commit_new: 新版本标识符
    
    Returns:
        str: 向下调用链 JSON 文件完整路径
    """
    version_dir = get_version_subdir(project_name, commit_old, commit_new)
    return os.path.join(version_dir, "downwards_call_chains.json")


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
