"""
分析结果数据加载 API
"""
import os
import sys
import json
import sqlite3
import re
import threading
from typing import List, Dict, Optional
from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel
from typing import Any
from app.config import settings
from app.services.llm_service import llm_service, llm_status
from app.services.sql_analyzer import sql_analyzer

# 添加项目根目录到路径（用于导入 jcci 核心引擎）
_project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from jcci.utils.tag_utils import extract_short_tag as _extract_short_tag

router = APIRouter(prefix="/api/analysis", tags=["analysis"])


# ── 标签辅助函数 ──────────────────────────────────────────────
# _extract_short_tag 已从 jcci.utils.tag_utils 统一导入（见文件顶部）


def _get_full_baseline_from_tasks(task_db_path: str, short_name: str) -> str:
    """从任务表将短标签目录名映射回完整基线标签"""
    try:
        conn = sqlite3.connect(task_db_path)
        cursor = conn.cursor()
        cursor.execute('SELECT DISTINCT tag_old FROM analysis_tasks WHERE tag_old IS NOT NULL')
        for row in cursor.fetchall():
            full = row[0]
            short = _extract_short_tag(full)
            # 匹配：目录名以短标签结尾（如 mall_20260403_01）、精确相等、或完整标签等于目录名
            if short_name.endswith('_' + short) or short == short_name or full == short_name:
                conn.close()
                return full
        conn.close()
    except Exception:
        pass
    return short_name  # 回退


def _get_full_versions_from_tasks(task_db_path: str, baseline_full: str, baseline_dir: str) -> List[str]:
    """从任务表将版本目录名映射回完整版本标签"""
    versions = []
    try:
        conn = sqlite3.connect(task_db_path)
        cursor = conn.cursor()
        # 获取所有含 tag_new 的任务，在 Python 中做基线匹配
        cursor.execute('SELECT DISTINCT tag_new, tag_old FROM analysis_tasks WHERE tag_new IS NOT NULL')
        for row in cursor.fetchall():
            full_new = row[0]
            tag_old = row[1]
            # 基线匹配：完整标签相等 或 短标签一致（兼容任务列表和目录名两种基线来源）
            if tag_old != baseline_full and _extract_short_tag(tag_old) != _extract_short_tag(baseline_full):
                continue
            short_new = _extract_short_tag(full_new)
            version_dir = os.path.join(baseline_dir, short_new)
            if os.path.isdir(version_dir):
                versions.append(full_new)
        conn.close()
    except Exception:
        pass
    return versions


def _resolve_data_path(baseline: str, version: str) -> str:
    """接受完整标签或短标签, 映射到磁盘上的实际路径"""
    result_dir = settings.RESULT_DIR
    
    # 先尝试原始路径（短标签或目录名直接命中的情况）
    direct_path = os.path.join(result_dir, baseline, version)
    if os.path.exists(direct_path):
        return direct_path
    
    # 回退：转换为短标签再尝试（完整长标签的情况）
    baseline_short = _extract_short_tag(baseline)
    version_short = _extract_short_tag(version)
    short_path = os.path.join(result_dir, baseline_short, version_short)
    if os.path.exists(short_path):
        return short_path
    
    # 二次回退：扫描带项目前缀的目录名（如 mall_20031225_01）
    baseline_suffix = '_' + baseline_short
    for item in sorted(os.listdir(result_dir)):
        if item.endswith(baseline_suffix) and os.path.isdir(os.path.join(result_dir, item)):
            return os.path.join(result_dir, item, version_short)
    
    # 最终回退
    return short_path


class BaselineInfo(BaseModel):
    """基线信息"""
    name: str
    versions: List[str]


class VersionInfo(BaseModel):
    """版本信息"""
    baseline: str
    version: str
    has_upwards: bool
    has_downwards: bool
    has_text: bool


@router.get("/baselines", response_model=List[BaselineInfo])
async def list_baselines():
    """
    获取所有可用的基线列表及其版本。
    返回完整标签名（从任务表映射），若无任务记录则回退到磁盘目录名。
    """
    result_dir = settings.RESULT_DIR
    task_db_path = settings.DB_PATH
    
    if not os.path.exists(result_dir):
        return []
    
    baselines = []
    has_task_db = os.path.exists(task_db_path)
    
    # 扫描所有基线目录
    for item in sorted(os.listdir(result_dir)):
        baseline_path = os.path.join(result_dir, item)
        
        if item.startswith('.') or not os.path.isdir(baseline_path):
            continue
        
        # 映射为完整标签
        if has_task_db:
            baseline_full = _get_full_baseline_from_tasks(task_db_path, item)
        else:
            baseline_full = item
        
        # 获取该基线下的所有版本子目录
        if has_task_db and baseline_full != item:
            versions = _get_full_versions_from_tasks(task_db_path, baseline_full, baseline_path)
        else:
            versions = []
            for version in sorted(os.listdir(baseline_path)):
                version_path = os.path.join(baseline_path, version)
                if os.path.isdir(version_path) and not version.startswith('.'):
                    versions.append(version)
        
        if versions:
            baselines.append(BaselineInfo(
                name=baseline_full,
                versions=versions
            ))
    
    return baselines


@router.get("/{baseline}/{version}/info", response_model=VersionInfo)
async def get_version_info(baseline: str, version: str):
    """
    获取指定基线和版本的文件存在情况
    
    Args:
        baseline: 基线名称
        version: 版本名称
        
    Returns:
        版本信息
    """
    result_dir = settings.RESULT_DIR
    version_dir = _resolve_data_path(baseline, version)
    
    if not os.path.exists(version_dir):
        raise HTTPException(status_code=404, detail="Version not found")
    
    upwards_json = os.path.join(version_dir, "upwards_call_chains.json")
    downwards_json = os.path.join(version_dir, "downwards_call_chains.json")
    upwards_txt = os.path.join(version_dir, "upwards.txt")
    downwards_txt = os.path.join(version_dir, "downwards.txt")
    
    return VersionInfo(
        baseline=baseline,
        version=version,
        has_upwards=os.path.exists(upwards_json),
        has_downwards=os.path.exists(downwards_json),
        has_text=os.path.exists(upwards_txt) and os.path.exists(downwards_txt)
    )


@router.get("/{baseline}/{version}/upwards")
async def get_upwards_chains(baseline: str, version: str):
    """
    获取向上调用链数据
    
    Args:
        baseline: 基线名称
        version: 版本名称
        
    Returns:
        向上调用链 JSON 数据
    """
    result_dir = settings.RESULT_DIR
    filepath = os.path.join(_resolve_data_path(baseline, version), "upwards_call_chains.json")
    
    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="Upwards chains file not found")
    
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=500, detail=f"Invalid JSON: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{baseline}/{version}/downwards")
async def get_downwards_chains(baseline: str, version: str):
    """
    获取向下调用链数据
    
    Args:
        baseline: 基线名称
        version: 版本名称
        
    Returns:
        向下调用链 JSON 数据
    """
    result_dir = settings.RESULT_DIR
    filepath = os.path.join(_resolve_data_path(baseline, version), "downwards_call_chains.json")
    
    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="Downwards chains file not found")
    
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=500, detail=f"Invalid JSON: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{baseline}/{version}/text/upwards")
async def get_upwards_text(baseline: str, version: str):
    """
    获取向上调用链文本
    
    Args:
        baseline: 基线名称
        version: 版本名称
        
    Returns:
        文本内容
    """
    result_dir = settings.RESULT_DIR
    filepath = os.path.join(_resolve_data_path(baseline, version), "upwards.txt")
    
    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="Upwards text file not found")
    
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
        return {"content": content}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{baseline}/{version}/text/downwards")
async def get_downwards_text(baseline: str, version: str):
    """
    获取向下调用链文本
    
    Args:
        baseline: 基线名称
        version: 版本名称
        
    Returns:
        文本内容
    """
    result_dir = settings.RESULT_DIR
    filepath = os.path.join(_resolve_data_path(baseline, version), "downwards.txt")
    
    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="Downwards text file not found")
    
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
        return {"content": content}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class MethodAnalysisRequest(BaseModel):
    """方法分析请求"""
    method_info: Dict[str, Any]
    db_info: Optional[Dict[str, Any]] = None
    direction: str = "upwards"
    force_fresh: bool = False


class ChainAnalysisRequest(BaseModel):
    """调用链分析请求"""
    chain_data: Dict[str, Any]
    direction: str = "upwards"
    force_fresh: bool = False


class UpwardsSummaryRequest(BaseModel):
    """向上链批量分析请求"""
    force_fresh: bool = False


class CreateTaskRequest(BaseModel):
    """创建异步分析任务请求"""
    analysis_type: str  # 'method' | 'chain'
    direction: str = 'upwards'
    baseline: str = ''
    version: str = ''
    class_name: str = ''
    method_name: str = ''
    change_type: str = 'UNKNOWN'
    force_fresh: bool = False
    custom_system_prompt: str = ''
    custom_analysis_prompt: str = ''
    method_info: Optional[Dict[str, Any]] = None
    db_info: Optional[Dict[str, Any]] = None
    chain_data: Optional[Dict[str, Any]] = None
    selected_methods: Optional[List[Dict[str, Any]]] = None


class NodeStatusRequest(BaseModel):
    """批量节点状态查询请求"""
    baseline: str
    version: str
    nodes: List[Dict[str, Any]]


class BatchMethodRequest(BaseModel):
    """批量方法分析请求"""
    baseline: str = ''
    version: str = ''
    direction: str = 'upwards'
    force_fresh: bool = False
    methods: List[Dict[str, Any]] = []


@router.get("/default-prompts")
async def get_default_prompts(
    analysis_type: str = 'method',
    class_name: str = '',
    method_name: str = '',
    change_type: str = 'UNKNOWN',
    direction: str = 'upwards'
):
    """
    获取默认的系统提示词和分析提示词模板
    
    前端在 AI 分析配置页加载时调用，预填提示词编辑区。
    """
    method_info = {
        'class_name': class_name,
        'method_name': method_name,
        'change_type': change_type,
        'parameters': '[]',
        'return_type': ''
    }
    return llm_service.get_default_prompts(
        analysis_type=analysis_type,
        method_info=method_info,
        direction=direction
    )


@router.get("/method-code")
async def get_method_code(
    baseline: str = '',
    version: str = '',
    class_name: str = '',
    method_name: str = ''
):
    """
    获取方法的基线版本和当前版本源代码
    用于 AI 分析配置页的代码版本对比展示
    
    基线 DB 中 project 表记录了每次分析（基线/版本），每个 project_id
    对应 methods 表中的不同版本代码：
    - project_id=0: 基线版本代码 (commit_or_branch_new == commit_or_branch_old == baseline)
    - project_id>0: 各差异版本代码 (commit_or_branch_new == version)
    """
    import sqlite3
    
    result_dir = settings.RESULT_DIR
    base_db = os.path.join(result_dir, baseline, f"{baseline}_baseline.db")
    
    baseline_code = ''
    current_code = ''
    annotations = ''
    access_modifier = ''
    return_type = ''
    parameters = ''
    change_type_val = 'UNCHANGED'
    
    if not os.path.exists(base_db):
        return {
            'class_name': class_name,
            'method_name': method_name,
            'baseline': baseline,
            'version': version,
            'baseline_code': '',
            'current_code': '',
            'annotations': '',
            'access_modifier': '',
            'return_type': '',
            'parameters': ''
        }
    
    conn = sqlite3.connect(base_db)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # 从基线/版本名称中提取 commit 标识（如 mall_20260508_01 -> 20260508_01）
    from app.core.workflow1 import extract_short_tag
    baseline_commit = extract_short_tag(baseline)
    version_commit = extract_short_tag(version)
    
    # 查找版本对应的 project_id
    cursor.execute('''
        SELECT project_id FROM project
        WHERE commit_or_branch_new = ? AND commit_or_branch_old = ?
        LIMIT 1
    ''', (version_commit, baseline_commit))
    version_proj = cursor.fetchone()
    version_project_id = version_proj['project_id'] if version_proj else None
    
    # 查找基线 project_id (project_id=0，即 commit_or_branch_new==commit_or_branch_old==baseline)
    cursor.execute('''
        SELECT project_id FROM project
        WHERE commit_or_branch_new = ? AND commit_or_branch_old = ?
        LIMIT 1
    ''', (baseline_commit, baseline_commit))
    baseline_proj = cursor.fetchone()
    baseline_project_id = baseline_proj['project_id'] if baseline_proj else 0
    
    # 获取基线版本代码（project_id == baseline_project_id）
    cursor.execute('''
        SELECT m.body, m.annotations, m.access_modifier,
               m.return_type, m.parameters, m.change_type
        FROM methods m
        JOIN class c ON m.class_id = c.class_id
        WHERE c.class_name = ? AND m.method_name = ? AND m.project_id = ?
        LIMIT 1
    ''', (class_name, method_name, baseline_project_id))
    baseline_row = cursor.fetchone()
    
    if baseline_row:
        body_lines = _parse_body_to_lines(baseline_row['body'])
        baseline_code = '\n'.join(body_lines)
        annotations = baseline_row['annotations'] or ''
        access_modifier = baseline_row['access_modifier'] or ''
        return_type = baseline_row['return_type'] or ''
        parameters = baseline_row['parameters'] or ''
        change_type_val = baseline_row['change_type'] or 'UNCHANGED'
    
    # 获取版本代码（project_id == version_project_id，如果版本!=基线）
    if version_project_id is not None and version_project_id != baseline_project_id:
        cursor.execute('''
            SELECT m.body, m.change_type
            FROM methods m
            JOIN class c ON m.class_id = c.class_id
            WHERE c.class_name = ? AND m.method_name = ? AND m.project_id = ?
            LIMIT 1
        ''', (class_name, method_name, version_project_id))
        version_row = cursor.fetchone()
        
        if version_row:
            version_body_lines = _parse_body_to_lines(version_row['body'])
            current_code = '\n'.join(version_body_lines)
            # 用版本的 change_type 覆盖（如 MODIFIED）
            version_change = version_row['change_type'] or ''
            if version_change:
                change_type_val = version_change
        else:
            # 版本中无此方法（可能是 DELETED）
            current_code = ''
    else:
        # 版本=基线，或方法未变更
        current_code = baseline_code
    
    conn.close()
    
    return {
        'class_name': class_name,
        'method_name': method_name,
        'baseline': baseline,
        'version': version,
        'baseline_code': baseline_code,
        'current_code': current_code,
        'annotations': annotations,
        'access_modifier': access_modifier,
        'return_type': return_type,
        'parameters': parameters
    }


def _parse_body_to_lines(body):
    """将 DB 中的 body 字段解析为代码行列表"""
    if not body:
        return []
    try:
        return json.loads(body) if isinstance(body, str) else body
    except (json.JSONDecodeError, TypeError):
        return [body] if isinstance(body, str) else []


@router.get("/llm-status")
async def get_llm_status():
    """
    查询 LLM 分析状态
    
    Returns:
        当前 LLM 分析状态信息
    """
    return llm_status.to_dict()


@router.post("/analyze/method")
async def analyze_method(request: MethodAnalysisRequest):
    """
    分析方法变更和测试建议
    
    Args:
        request: 方法分析请求
        
    Returns:
        分析结果
    """
    # 并发防护：检查是否有正在进行的分析
    if not llm_status.start(f"方法分析: {request.method_info.get('class_name', '')}.{request.method_info.get('method_name', '')}"):
        raise HTTPException(status_code=409, detail="已有 LLM 分析正在执行中，请等待完成后再试")
    
    try:
        result = llm_service.analyze_method(
            method_info=request.method_info,
            db_info=request.db_info or {},
            direction=request.direction,
            force_fresh=request.force_fresh
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        llm_status.finish()


@router.post("/{baseline}/{version}/analyze/upwards-summary")
async def analyze_upwards_summary(baseline: str, version: str, request: UpwardsSummaryRequest):
    """
    批量分析所有向上调用链（影响面评估）
    
    加载向上调用链JSON，对每条链进行AI分析，
    汇总所有链路结果生成综合影响面报告。
    支持缓存和强制刷新。
    
    Args:
        baseline: 基线名称
        version: 版本名称
        request: 批量分析请求（force_fresh: 是否强制全新分析）
        
    Returns:
        汇总分析结果
    """
    result_dir = settings.RESULT_DIR
    filepath = os.path.join(_resolve_data_path(baseline, version), "upwards_call_chains.json")
    
    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="Upwards chains file not found")
    
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
    impact_chains = data.get('impact_chains', [])
    
    if not impact_chains:
        return {"result": "没有找到向上调用链", "from_cache": True}
    
    # 并发防护：检查是否有正在进行的分析
    if not llm_status.start(f"批量影响面分析: {baseline}/{version}"):
        raise HTTPException(status_code=409, detail="已有 LLM 分析正在执行中，请等待完成后再试")
    
    # 逐条分析每条链
    all_results = []
    any_fresh = False
    
    try:
        for idx, chain_data in enumerate(impact_chains, 1):
            method_info = chain_data.get('method_info', {})
            class_name = method_info.get('class_name', '')
            method_name = method_info.get('method_name', '')
            
            try:
                result = llm_service.analyze_chain(
                    chain_data=chain_data,
                    direction='upwards',
                    force_fresh=request.force_fresh
                )
                all_results.append({
                    'index': idx,
                    'method': f"{class_name}.{method_name}",
                    'change_type': method_info.get('change_type', 'UNKNOWN'),
                    'analysis': result['result'],
                    'from_cache': result.get('from_cache', False)
                })
                if not result.get('from_cache', False):
                    any_fresh = True
            except Exception as e:
                all_results.append({
                    'index': idx,
                    'method': f"{class_name}.{method_name}",
                    'change_type': method_info.get('change_type', 'UNKNOWN'),
                    'analysis': f"分析失败: {str(e)}",
                    'from_cache': False
                })
    finally:
        llm_status.finish()
    
    # 构建汇总报告
    summary_parts = []
    summary_parts.append("# 向上调用链批量影响面分析报告\n")
    summary_parts.append(f"**分析范围**: {baseline}/{version}\n")
    summary_parts.append(f"**总链路数**: {len(all_results)}\n")
    summary_parts.append(f"**分析模式**: {'强制全新分析' if request.force_fresh else '优先使用缓存'}\n")
    summary_parts.append("\n---\n")
    
    for r in all_results:
        cache_tag = "♻️缓存" if r['from_cache'] else "🆕全新"
        summary_parts.append(f"\n## {r['index']}. [{r['change_type']}] {r['method']} ({cache_tag})\n\n")
        summary_parts.append(r['analysis'])
        summary_parts.append("\n---\n")
    
    return {
        "result": "".join(summary_parts),
        "from_cache": not any_fresh,
        "chain_count": len(all_results),
        "individual_results": all_results
    }


@router.post("/analyze/chain")
async def analyze_chain(request: ChainAnalysisRequest):
    """
    分析调用链影响和风险
    
    Args:
        request: 调用链分析请求
        
    Returns:
        分析结果
    """
    # 并发防护：检查是否有正在进行的分析
    if not llm_status.start("调用链分析"):
        raise HTTPException(status_code=409, detail="已有 LLM 分析正在执行中，请等待完成后再试")
    
    try:
        result = llm_service.analyze_chain(
            chain_data=request.chain_data,
            direction=request.direction,
            force_fresh=request.force_fresh
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        llm_status.finish()


@router.get("/{baseline}/{version}/sql-summary")
async def get_sql_summary(baseline: str, version: str):
    """获取 SQL 分析汇总"""
    result_dir = settings.RESULT_DIR
    filepath = os.path.join(_resolve_data_path(baseline, version), "downwards_call_chains.json")

    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="Downwards chains file not found")

    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)

        call_chains = data.get('dependency_chains') or data.get('call_chains', [])
        dao_methods = sql_analyzer.extract_dao_methods(call_chains)
        summary = sql_analyzer.get_sql_summary(dao_methods)

        return {
            'summary': summary,
            'dao_methods_count': len(dao_methods)
        }
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=500, detail=f"Invalid JSON: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ========== 异步任务 API ==========

@router.post("/tasks")
async def create_analysis_task(request: CreateTaskRequest, background_tasks: BackgroundTasks):
    """
    创建异步 LLM 分析任务
    
    返回 task_id，前端通过 GET /tasks/{task_id} 轮询进度。
    """
    # 检查是否有同一方法的冲突任务
    conn = __import__('sqlite3').connect(settings.DB_PATH)
    conn.row_factory = __import__('sqlite3').Row
    cursor = conn.cursor()
    cursor.execute('''
        SELECT task_id FROM llm_analysis_tasks
        WHERE class_name = ? AND method_name = ?
          AND baseline = ? AND version = ?
          AND status IN ('pending', 'running')
        LIMIT 1
    ''', (request.class_name, request.method_name,
          request.baseline, request.version))
    existing = cursor.fetchone()
    conn.close()
    
    if existing:
        return {
            'task_id': existing['task_id'],
            'status': 'conflict',
            'message': '该方法已有分析任务正在执行中，返回已有任务ID'
        }
    
    # 创建任务
    task_id = llm_service.create_task(
        analysis_type=request.analysis_type,
        direction=request.direction,
        baseline=request.baseline,
        version=request.version,
        class_name=request.class_name,
        method_name=request.method_name,
        change_type=request.change_type,
        force_fresh=request.force_fresh,
        custom_system_prompt=request.custom_system_prompt,
        custom_analysis_prompt=request.custom_analysis_prompt,
        total_methods=len(request.selected_methods) if request.selected_methods else 1
    )
    
    # 后台执行
    if request.analysis_type == 'method':
        background_tasks.add_task(
            llm_service.run_method_task,
            task_id=task_id,
            method_info=request.method_info or {},
            db_info=request.db_info or {},
            direction=request.direction,
            baseline=request.baseline,
            version=request.version,
            force_fresh=request.force_fresh,
            custom_system_prompt=request.custom_system_prompt,
            custom_analysis_prompt=request.custom_analysis_prompt
        )
    elif request.analysis_type == 'chain':
        background_tasks.add_task(
            llm_service.run_chain_task,
            task_id=task_id,
            chain_data=request.chain_data or {},
            selected_methods=request.selected_methods or [],
            direction=request.direction,
            baseline=request.baseline,
            version=request.version,
            force_fresh=request.force_fresh,
            custom_system_prompt=request.custom_system_prompt,
            custom_analysis_prompt=request.custom_analysis_prompt
        )
    
    return {
        'task_id': task_id,
        'status': 'pending',
        'message': '任务已创建，正在排队分析中...'
    }


@router.post("/batch-methods")
async def create_batch_method_task(request: BatchMethodRequest, background_tasks: BackgroundTasks):
    """
    创建批量方法分析任务（逐方法调用 analyze_method）
    
    每完成一个方法分析，自动保存结果到 llm_analysis_results，
    前端轮询 nodes-status API 即可实时看到 Tree 节点标签更新。
    """
    if not request.methods:
        raise HTTPException(status_code=400, detail="methods 列表不能为空")
    
    task_id = llm_service.create_task(
        analysis_type='batch',
        direction=request.direction,
        baseline=request.baseline,
        version=request.version,
        total_methods=len(request.methods)
    )
    
    background_tasks.add_task(
        llm_service.run_batch_method_task,
        task_id=task_id,
        methods=request.methods,
        direction=request.direction,
        baseline=request.baseline,
        version=request.version,
        force_fresh=request.force_fresh
    )
    
    return {
        'task_id': task_id,
        'status': 'pending',
        'message': f'批量分析任务已创建，共 {len(request.methods)} 个方法'
    }


@router.get("/tasks/{task_id}")
async def get_analysis_task(task_id: str):
    """
    查询分析任务状态
    
    Returns:
        任务详情，含状态、进度、子结果列表
    """
    task = llm_service.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    
    # 如果有子结果，构建摘要
    sub_tasks = []
    for r in task.get('sub_results', []):
        sub_tasks.append({
            'result_id': r.get('result_id'),
            'class_name': r.get('class_name', ''),
            'method_name': r.get('method_name', ''),
            'status': 'completed',
            'from_cache': bool(r.get('from_cache'))
        })
    
    return {
        'task_id': task['task_id'],
        'analysis_type': task.get('analysis_type'),
        'status': task.get('status'),
        'progress': task.get('progress', 0.0),
        'total_methods': task.get('total_methods', 1),
        'completed_methods': task.get('completed_methods', 0),
        'current_stage': task.get('current_stage', ''),
        'error_message': task.get('error_message'),
        'custom_system_prompt': task.get('custom_system_prompt', ''),
        'custom_analysis_prompt': task.get('custom_analysis_prompt', ''),
        'baseline': task.get('baseline', ''),
        'version': task.get('version', ''),
        'class_name': task.get('class_name', ''),
        'method_name': task.get('method_name', ''),
        'change_type': task.get('change_type', 'UNKNOWN'),
        'direction': task.get('direction', ''),
        'sub_tasks': sub_tasks,
        'started_at': task.get('started_at'),
        'completed_at': task.get('completed_at'),
        'created_at': task.get('created_at')
    }


@router.get("/results/{result_id}")
async def get_analysis_result(result_id: str):
    """
    获取单个分析结果（含子结果列表，用于链分析的聚合/子方法切换）
    """
    result = llm_service.get_result(result_id)
    if not result:
        raise HTTPException(status_code=404, detail="Result not found")

    # 查询同一任务下的其他结果作为子结果（用于链分析 Tab 切换）
    sub_results = []
    task_id = result.get('task_id', '')
    if task_id:
        conn = __import__('sqlite3').connect(settings.DB_PATH)
        conn.row_factory = __import__('sqlite3').Row
        cursor = conn.cursor()
        cursor.execute('''
            SELECT result_id, class_name, method_name, analysis_result,
                   analysis_duration, from_cache, created_at
            FROM llm_analysis_results
            WHERE (task_id = ? OR parent_task_id = ?)
              AND result_id != ?
            ORDER BY created_at
        ''', (task_id, task_id, result_id))
        for row in cursor.fetchall():
            sub_results.append({
                'result_id': row['result_id'],
                'class_name': row['class_name'] or '',
                'method_name': row['method_name'] or '',
                'analysis_result': row['analysis_result'],
                'analysis_duration': row['analysis_duration'],
                'from_cache': bool(row['from_cache']),
                'created_at': row['created_at']
            })
        conn.close()

    return {
        'result_id': result['result_id'],
        'task_id': result.get('task_id'),
        'class_name': result.get('class_name'),
        'method_name': result.get('method_name'),
        'analysis_result': result['analysis_result'],
        'model_name': result.get('model_name'),
        'analysis_duration': result.get('analysis_duration'),
        'from_cache': bool(result.get('from_cache')),
        'created_at': result.get('created_at'),
        'sub_results': sub_results
    }


@router.post("/nodes-status")
async def get_nodes_status(request: NodeStatusRequest):
    """
    批量查询 Tree 节点的 AI 分析状态（三类：方法/向上链/向下链）
    """
    conn = __import__('sqlite3').connect(settings.DB_PATH)
    conn.row_factory = __import__('sqlite3').Row
    cursor = conn.cursor()
    
    nodes_status = []
    for node in request.nodes:
        class_name = node.get('class_name', '')
        method_name = node.get('method_name', '')
        change_type = node.get('change_type', 'UNKNOWN')
        
        status = {
            'class_name': class_name,
            'method_name': method_name,
            'change_type': change_type,
            'method_status': 'none',
            'upwards_chain_status': 'none',
            'downwards_chain_status': 'none',
            'running_task_id': None,
            'latest_method_result_id': None,
            'latest_upwards_chain_result_id': None,
            'latest_downwards_chain_result_id': None
        }
        
        # 检查方法分析缓存（含链分析的逐方法子结果 + 批量分析结果）
        cursor.execute('''
            SELECT r.result_id FROM llm_analysis_results r
            JOIN llm_analysis_tasks t ON r.task_id = t.task_id
            WHERE t.analysis_type IN ('method', 'batch', 'chain')
              AND r.class_name = ? AND r.method_name = ?
              AND (t.baseline = '' OR t.baseline = ?) AND (t.version = '' OR t.version = ?)
            ORDER BY r.created_at DESC LIMIT 1
        ''', (class_name, method_name, request.baseline, request.version))
        row = cursor.fetchone()
        if row:
            status['method_status'] = 'analyzed'
            status['latest_method_result_id'] = row['result_id']
        
        # 检查向上调用链分析缓存（仅 chain 类型的聚合结果，排除子结果和 batch 类型）
        cursor.execute('''
            SELECT r.result_id FROM llm_analysis_results r
            JOIN llm_analysis_tasks t ON r.task_id = t.task_id
            WHERE t.analysis_type = 'chain'
              AND t.direction = 'upwards'
              AND r.parent_task_id IS NULL
              AND r.class_name = ? AND r.method_name = ?
              AND (t.baseline = '' OR t.baseline = ?) AND (t.version = '' OR t.version = ?)
            ORDER BY r.created_at DESC LIMIT 1
        ''', (class_name, method_name, request.baseline, request.version))
        row = cursor.fetchone()
        if row:
            status['upwards_chain_status'] = 'analyzed'
            status['latest_upwards_chain_result_id'] = row['result_id']
        
        # 检查向下调用链分析缓存（仅 chain 类型的聚合结果，排除子结果和 batch 类型）
        cursor.execute('''
            SELECT r.result_id FROM llm_analysis_results r
            JOIN llm_analysis_tasks t ON r.task_id = t.task_id
            WHERE t.analysis_type = 'chain'
              AND t.direction = 'downwards'
              AND r.parent_task_id IS NULL
              AND r.class_name = ? AND r.method_name = ?
              AND (t.baseline = '' OR t.baseline = ?) AND (t.version = '' OR t.version = ?)
            ORDER BY r.created_at DESC LIMIT 1
        ''', (class_name, method_name, request.baseline, request.version))
        row = cursor.fetchone()
        if row:
            status['downwards_chain_status'] = 'analyzed'
            status['latest_downwards_chain_result_id'] = row['result_id']
        
        # 检查是否有运行中的任务（排除超时 30 分钟的僵尸任务）
        cursor.execute('''
            SELECT task_id FROM llm_analysis_tasks
            WHERE class_name = ? AND method_name = ?
              AND baseline = ? AND version = ?
              AND status IN ('pending', 'running')
              AND (started_at IS NULL OR datetime(started_at, '+30 minutes') > datetime('now', 'localtime'))
            LIMIT 1
        ''', (class_name, method_name, request.baseline, request.version))
        row = cursor.fetchone()
        if row:
            status['running_task_id'] = row['task_id']
        
        nodes_status.append(status)
    
    conn.close()
    return {'nodes': nodes_status}


@router.get("/{baseline}/{version}/chain-methods")
async def get_chain_methods(baseline: str, version: str, direction: str = 'upwards'):
    """
    获取调用链方法列表（供分析配置页使用）
    """
    result_dir = settings.RESULT_DIR
    filename = f"{direction}_call_chains.json"
    filepath = os.path.join(_resolve_data_path(baseline, version), filename)
    
    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail=f"{direction} call chains file not found")
    
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
    # 根据方向提取方法列表
    if direction == 'upwards':
        chains_data = data.get('impact_chains', [])
    else:
        chains_data = data.get('call_chains', data.get('dependency_chains', []))
    
    methods_with_cache = []
    seen = set()
    
    # 统一数据库连接，批量查询状态
    conn = __import__('sqlite3').connect(settings.DB_PATH)
    conn.row_factory = __import__('sqlite3').Row
    cursor = conn.cursor()
    
    for chain in chains_data:
        mi = chain.get('method_info', {})
        class_name = mi.get('class_name', '')
        method_name = mi.get('method_name', '')
        key = f"{class_name}.{method_name}"
        if key in seen:
            continue
        seen.add(key)
        
        # 查询状态（与 nodes-status API 逻辑一致）
        method_status = 'none'
        upwards_chain_status = 'none'
        downwards_chain_status = 'none'
        
        try:
            # 方法分析状态（含链分析的逐方法子结果 + 批量分析结果）
            cursor.execute('''
                SELECT r.result_id FROM llm_analysis_results r
                JOIN llm_analysis_tasks t ON r.task_id = t.task_id
                WHERE t.analysis_type IN ('method', 'batch', 'chain')
                  AND r.class_name = ? AND r.method_name = ?
                  AND (t.baseline = '' OR t.baseline = ?) AND (t.version = '' OR t.version = ?)
                ORDER BY r.created_at DESC LIMIT 1
            ''', (class_name, method_name, baseline, version))
            if cursor.fetchone():
                method_status = 'analyzed'
        except Exception:
            pass
        
        try:
            # 向上链分析状态（仅 chain 类型的聚合结果）
            cursor.execute('''
                SELECT r.result_id FROM llm_analysis_results r
                JOIN llm_analysis_tasks t ON r.task_id = t.task_id
                WHERE t.analysis_type = 'chain'
                  AND t.direction = 'upwards'
                  AND r.parent_task_id IS NULL
                  AND r.class_name = ? AND r.method_name = ?
                  AND (t.baseline = '' OR t.baseline = ?) AND (t.version = '' OR t.version = ?)
                ORDER BY r.created_at DESC LIMIT 1
            ''', (class_name, method_name, baseline, version))
            if cursor.fetchone():
                upwards_chain_status = 'analyzed'
        except Exception:
            pass
        
        try:
            # 向下链分析状态（仅 chain 类型的聚合结果）
            cursor.execute('''
                SELECT r.result_id FROM llm_analysis_results r
                JOIN llm_analysis_tasks t ON r.task_id = t.task_id
                WHERE t.analysis_type = 'chain'
                  AND t.direction = 'downwards'
                  AND r.parent_task_id IS NULL
                  AND r.class_name = ? AND r.method_name = ?
                  AND (t.baseline = '' OR t.baseline = ?) AND (t.version = '' OR t.version = ?)
                ORDER BY r.created_at DESC LIMIT 1
            ''', (class_name, method_name, baseline, version))
            if cursor.fetchone():
                downwards_chain_status = 'analyzed'
        except Exception:
            pass
        
        methods_with_cache.append({
            'class_name': class_name,
            'method_name': method_name,
            'signature': mi.get('method_signature', f"{method_name}()"),
            'change_type': mi.get('change_type', 'UNKNOWN'),
            'parameters': mi.get('parameters', '[]'),
            'return_type': mi.get('return_type', ''),
            'documentation': mi.get('documentation', ''),
            'method_status': method_status,
            'upwards_chain_status': upwards_chain_status,
            'downwards_chain_status': downwards_chain_status
        })
    
    conn.close()
    
    return {
        'methods': methods_with_cache,
        'total': len(methods_with_cache)
    }
