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
    一次 SQLite 连接批量建立 {短标签→完整标签} 双向映射，避免逐目录查询。
    """
    result_dir = settings.RESULT_DIR
    task_db_path = settings.DB_PATH
   
    if not os.path.exists(result_dir):
        return []
   
    # ── 一次性读取所有磁盘目录 ──
    disk_dirs: Dict[str, set] = {}  # baseline_dir → {version_dir, ...}
    for item in sorted(os.listdir(result_dir)):
        baseline_path = os.path.join(result_dir, item)
        if item.startswith('.') or not os.path.isdir(baseline_path):
            continue
        versions = set()
        for version in sorted(os.listdir(baseline_path)):
            version_path = os.path.join(baseline_path, version)
            if os.path.isdir(version_path) and not version.startswith('.'):
                versions.add(version)
        if versions:
            disk_dirs[item] = versions
   
    if not disk_dirs:
        return []
   
    # ── 一次性从任务表建立完整标签↔短标签映射 ──
    has_task_db = os.path.exists(task_db_path)
    short_to_full: Dict[str, str] = {}       # 短标签 → 完整标签
    full_to_versions: Dict[str, List[tuple]] = {}  # 完整基线 → [(完整版本, 短版本), ...]
   
    if has_task_db:
        try:
            conn = sqlite3.connect(task_db_path)
            cursor = conn.cursor()
            # 一次性查询所有 tag_old, tag_new
            cursor.execute('SELECT DISTINCT tag_old, tag_new FROM analysis_tasks WHERE tag_old IS NOT NULL AND tag_new IS NOT NULL')
            for row in cursor.fetchall():
                old_full = row[0]
                new_full = row[1]
                old_short = _extract_short_tag(old_full)
                new_short = _extract_short_tag(new_full)
                # 短→完整 映射
                if old_short not in short_to_full:
                    short_to_full[old_short] = old_full
                if new_short not in short_to_full:
                    short_to_full[new_short] = new_full
                # 完整基线→版本列表
                if old_full not in full_to_versions:
                    full_to_versions[old_full] = []
                full_to_versions[old_full].append((new_full, new_short))
            conn.close()
        except Exception:
            pass
   
    # ── 组装基线列表 ──
    baselines = []
    seen_full_names = set()
   
    for dir_name, disk_versions in disk_dirs.items():
        # 解析目录名 → 完整基线标签
        if has_task_db:
            # 策略1: 目录名自身就是完整标签
            if dir_name in full_to_versions:
                baseline_full = dir_name
            else:
                # 策略2: 目录名的短标签匹配
                dir_short = _extract_short_tag(dir_name)
                baseline_full = short_to_full.get(dir_short, dir_name)
        else:
            baseline_full = dir_name
       
        if baseline_full in seen_full_names:
            continue
        seen_full_names.add(baseline_full)
       
        # 解析版本列表 → 完整版本标签
        versions = []
        if has_task_db and baseline_full in full_to_versions:
            # 使用任务表中的完整版本标签
            for new_full, new_short in full_to_versions[baseline_full]:
                if new_short in disk_versions:
                    versions.append(new_full)
       
        # 补全：磁盘有但任务表没有的版本（用目录名）
        if not versions:
            task_versions_set = set()
            if has_task_db and baseline_full in full_to_versions:
                task_versions_set = {ns for _, ns in full_to_versions[baseline_full]}
            for dv in sorted(disk_versions):
                if dv not in task_versions_set:
                    # 尝试映射为完整标签
                    dv_short = _extract_short_tag(dv)
                    versions.append(short_to_full.get(dv_short, dv))
       
        if versions:
            baselines.append(BaselineInfo(name=baseline_full, versions=versions))
   
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
   
    upwards_json_gz = os.path.join(version_dir, "upwards_call_chains.json.gz")
    downwards_json_gz = os.path.join(version_dir, "downwards_call_chains.json.gz")
    upwards_json = os.path.join(version_dir, "upwards_call_chains.json")
    downwards_json = os.path.join(version_dir, "downwards_call_chains.json")
    upwards_txt = os.path.join(version_dir, "upwards.txt")
    downwards_txt = os.path.join(version_dir, "downwards.txt")
   
    return VersionInfo(
        baseline=baseline,
        version=version,
        has_upwards=os.path.exists(upwards_json_gz) or os.path.exists(upwards_json),
        has_downwards=os.path.exists(downwards_json_gz) or os.path.exists(downwards_json),
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
    from jcci.utils.path_utils import load_call_chains_json_from_dir
    data_dir = _resolve_data_path(baseline, version)
    try:
        data = load_call_chains_json_from_dir(data_dir, "upwards")
        return data
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Upwards chains file not found")
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=500, detail=f"Invalid JSON: {str(e)}")
    except HTTPException:
        raise
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
    from jcci.utils.path_utils import load_call_chains_json_from_dir
    data_dir = _resolve_data_path(baseline, version)
    try:
        data = load_call_chains_json_from_dir(data_dir, "downwards")
        return data
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Downwards chains file not found")
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=500, detail=f"Invalid JSON: {str(e)}")
    except HTTPException:
        raise
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
    except HTTPException:
        raise
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
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))







class MethodAnalysisRequest(BaseModel):
    """方法分析请求"""
    method_info: Dict[str, Any]
    db_info: Optional[Dict[str, Any]] = None
    direction: str = "upwards"
    force_fresh: bool = False
    baseline: str = ''
    version: str = ''







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




@router.get("/method-code")
async def get_method_code(
    baseline: str = '',
    version: str = '',
    class_name: str = '',
    method_name: str = '',
    signature: str = '',
    class_id: int = None,
    method_id: int = None
):
    """
    获取方法的基线版本和当前版本源代码
    用于 AI 分析配置页的代码版本对比展示




    基线 DB 中 project 表记录了每次分析（基线/版本），每个 project_id
    对应 methods 表中的不同版本代码：
    - project_id=0: 基线版本代码 (commit_or_branch_new == commit_or_branch_old == baseline)
    - project_id>0: 各差异版本代码 (commit_or_branch_new == version)




    支持通过 signature 参数精确定位重载方法（同名不同参）。
    """
    import sqlite3
    import os as _os
   
    print(f"[method-code] 请求: baseline={baseline}, version={version}, class={class_name}, method={method_name}", flush=True)
   
    result_dir = settings.RESULT_DIR
   
    # 将完整 tag 或短标签映射到磁盘上的实际基线目录
    # （复用 _resolve_data_path 的三级回退逻辑：直接路径 → 短标签 → 前缀扫描）
    baseline_short = _extract_short_tag(baseline)
   
    # 1) 直接路径
    candidate = os.path.join(result_dir, baseline)
    if os.path.isdir(candidate):
        baseline_dir = candidate
        baseline_dirname = baseline
    # 2) 短标签路径
    elif os.path.isdir(os.path.join(result_dir, baseline_short)):
        baseline_dir = os.path.join(result_dir, baseline_short)
        baseline_dirname = baseline_short
    # 3) 扫描带项目前缀的目录 (如 mall_SHAb42d_...)
    else:
        baseline_suffix = '_' + baseline_short
        found = None
        for item in sorted(os.listdir(result_dir)):
            if item.endswith(baseline_suffix) and os.path.isdir(os.path.join(result_dir, item)):
                found = item
                break
        if found:
            baseline_dir = os.path.join(result_dir, found)
            baseline_dirname = found
        else:
            baseline_dir = os.path.join(result_dir, baseline_short)
            baseline_dirname = baseline_short
   
    base_db = os.path.join(baseline_dir, f"{baseline_dirname}_baseline.db")
    print(f"[method-code] RESULT_DIR={result_dir}", flush=True)
    print(f"[method-code] baseline_dir={baseline_dir}, baseline_dirname={baseline_dirname}", flush=True)
    print(f"[method-code] base_db={base_db}, exists={os.path.exists(base_db)}", flush=True)
   
    baseline_code = ''
    current_code = ''
    annotations = ''
    access_modifier = ''
    return_type = ''
    parameters = ''
    change_type_val = 'UNCHANGED'
   
    if not os.path.exists(base_db):
        print(f"[method-code] DB 不存在: {base_db}", flush=True)
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
   
    # ── 提前解析 commit 标识和 project_id（供 ID 查询路径和文本路径共用） ──
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
    
    # 查找基线 project_id
    cursor.execute('''
        SELECT project_id FROM project
        WHERE commit_or_branch_new = ? AND commit_or_branch_old = ?
        LIMIT 1
    ''', (baseline_commit, baseline_commit))
    baseline_proj = cursor.fetchone()
    baseline_project_id = baseline_proj['project_id'] if baseline_proj else 0
   
    # ── 解析 signature 中的参数类型列表（用于重载方法精确匹配） ──
    sig_param_types = _parse_signature_param_types(signature) if signature else []

    # ── ID 精确查询路径（优先使用，跳过文本匹配） ──
    if class_id is not None and method_id is not None:
        print(f"[method-code] 使用ID精确查询: class_id={class_id}, method_id={method_id}", flush=True)
        
        # 基线代码：用(class_id, method_id, baseline_project_id)查询（可靠）
        cursor.execute('''
            SELECT m.body, m.annotations, m.access_modifier,
                   m.return_type, m.parameters, m.change_type, m.documentation,
                   m.method_name, c.class_name
            FROM methods m
            JOIN class c ON m.class_id = c.class_id
            WHERE m.class_id = ? AND m.method_id = ? AND m.project_id = ?
            LIMIT 1
        ''', (class_id, method_id, baseline_project_id))
        row = cursor.fetchone()
        if row:
            body_lines = _parse_body_to_lines(row['body'])
            code = '\n'.join(body_lines)
            baseline_code = code
            annotations = row['annotations'] or ''
            access_modifier = row['access_modifier'] or ''
            return_type = row['return_type'] or ''
            parameters = row['parameters'] or ''
            documentation_val = row['documentation'] or ''
            if isinstance(documentation_val, str) and documentation_val != 'None':
                documentation = documentation_val
            change_type_val = row['change_type'] or 'UNCHANGED'
            if not method_name:
                method_name = row['method_name'] or ''
            if not class_name:
                class_name = row['class_name'] or ''

        # 版本代码：不用(class_id, method_id)查（跨project ID不同！），
        # 用 类名+方法名+project_id+参数签名 查询（支持重载方法）
        if class_name and method_name:
            short_cls = class_name
            pkg = ''
            if '.' in class_name:
                parts = class_name.rsplit('.', 1)
                pkg = parts[0]
                short_cls = parts[1]

            if version_project_id is not None:
                version_rows = _query_method_rows(cursor, short_cls, pkg, method_name, version_project_id)
            else:
                # 无project_id时，查询所有非基线project的记录（取第一个）
                if pkg:
                    cursor.execute('''
                        SELECT m.body, m.annotations, m.access_modifier,
                               m.return_type, m.parameters, m.change_type, m.documentation
                        FROM methods m
                        JOIN class c ON m.class_id = c.class_id
                        WHERE c.class_name = ? AND c.package_name = ? AND m.method_name = ?
                          AND m.project_id != ?
                        ORDER BY m.project_id DESC
                    ''', (short_cls, pkg, method_name, baseline_project_id))
                else:
                    cursor.execute('''
                        SELECT m.body, m.annotations, m.access_modifier,
                               m.return_type, m.parameters, m.change_type, m.documentation
                        FROM methods m
                        JOIN class c ON m.class_id = c.class_id
                        WHERE c.class_name = ? AND m.method_name = ?
                          AND m.project_id != ?
                        ORDER BY m.project_id DESC
                    ''', (short_cls, method_name, baseline_project_id))
                version_rows = cursor.fetchall()

            if version_rows:
                version_row = _match_method_by_params(version_rows, sig_param_types)
                if version_row:
                    body_lines = _parse_body_to_lines(version_row['body'])
                    current_code = '\n'.join(body_lines)
                    version_change = version_row['change_type'] or ''
                    if version_change:
                        change_type_val = version_change
                    version_doc = version_row['documentation'] if 'documentation' in version_row else ''
                    if isinstance(version_doc, str) and version_doc != 'None' and not documentation:
                        documentation = version_doc

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
            'parameters': parameters,
            'documentation': documentation
        }
   
    # class_name 可能是全限定名 (如 com.macro.mall.controller.PmsProductAttributeController)
    # DB 中 class 表的 class_name 存储的是短类名，package_name 存储包名
    short_class_name = class_name
    package_name = ''
    if '.' in class_name:
        parts = class_name.rsplit('.', 1)
        package_name = parts[0]
        short_class_name = parts[1]
   
    # 从基线/版本名称中提取 commit 标识
    print(f"[method-code] baseline_commit={baseline_commit}, version_commit={version_commit}", flush=True)
    print(f"[method-code] short_class_name={short_class_name}, package_name={package_name}", flush=True)
   
    print(f"[method-code] signature={signature}, sig_param_types={sig_param_types}", flush=True)
    print(f"[method-code] version_project_id={version_project_id}", flush=True)
    print(f"[method-code] baseline_project_id={baseline_project_id}", flush=True)
   
    # ── 查询方法（移除 LIMIT 1，获取所有同名方法后按参数类型精确匹配） ──
    baseline_row = None
    version_row = None
    documentation = ''
   
    # 基线代码查询
    baseline_rows = _query_method_rows(cursor, short_class_name, package_name, method_name, baseline_project_id)
    if baseline_rows:
        baseline_row = _match_method_by_params(baseline_rows, sig_param_types)
    print(f"[method-code] baseline_row found={baseline_row is not None}, total_rows={len(baseline_rows)}, sig_param_types={sig_param_types}", flush=True)
   
    if baseline_row:
        body_lines = _parse_body_to_lines(baseline_row['body'])
        baseline_code = '\n'.join(body_lines)
        annotations = baseline_row['annotations'] or ''
        access_modifier = baseline_row['access_modifier'] or ''
        return_type = baseline_row['return_type'] or ''
        parameters = baseline_row['parameters'] or ''
        documentation_val = baseline_row['documentation'] or ''
        if isinstance(documentation_val, str) and documentation_val != 'None':
            documentation = documentation_val
        change_type_val = baseline_row['change_type'] or 'UNCHANGED'
   
    # 版本代码查询
    if version_project_id is not None and version_project_id != baseline_project_id:
        version_rows = _query_method_rows(cursor, short_class_name, package_name, method_name, version_project_id)
        if version_rows:
            version_row = _match_method_by_params(version_rows, sig_param_types)
        print(f"[method-code] version_row found={version_row is not None}, total_rows={len(version_rows)}", flush=True)
   
        if version_row:
            version_body_lines = _parse_body_to_lines(version_row['body'])
            current_code = '\n'.join(version_body_lines)
            # 用版本的 change_type 覆盖（如 MODIFIED）
            version_change = version_row['change_type'] or ''
            if version_change:
                change_type_val = version_change
            # 版本 documentation 可能更新
            version_doc = version_row['documentation'] if 'documentation' in version_row else ''
            if isinstance(version_doc, str) and version_doc != 'None' and not documentation:
                documentation = version_doc
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
        'parameters': parameters,
        'documentation': documentation
    }




def _parse_body_to_lines(body):
    """将 DB 中的 body 字段解析为代码行列表"""
    if not body:
        return []
    try:
        return json.loads(body) if isinstance(body, str) else body
    except (json.JSONDecodeError, TypeError):
        return [body] if isinstance(body, str) else []




def _parse_signature_param_types(signature: str):
    """
    从方法签名中提取参数类型列表。
    例：'getEdlBusTag(com.cmb.dto.RemitDto, com.cmb.dto.OutRemitOprDto)'
    → ['com.cmb.dto.RemitDto', 'com.cmb.dto.OutRemitOprDto']
    无参方法：'delete()' → []
    """
    if not signature:
        return []
    # 提取括号内的参数
    paren_idx = signature.find('(')
    if paren_idx < 0:
        return []
    # 精确查找右括号位置，兼容签名后有额外内容的情况
    # （前端传入的 signature 可能是完整树节点标签，含 📝 MODIFIED 等后缀）
    paren_end_idx = signature.find(')', paren_idx)
    if paren_end_idx < 0:
        return []
    params_str = signature[paren_idx + 1:paren_end_idx]
    if not params_str.strip():
        return []
    # 按逗号分割，注意泛型如 List<com.xx.Yy>
    param_types = []
    depth = 0
    current = []
    for ch in params_str:
        if ch == '<':
            depth += 1
        elif ch == '>':
            depth -= 1
        if ch == ',' and depth == 0:
            param_types.append(''.join(current).strip())
            current = []
        else:
            current.append(ch)
    if current:
        param_types.append(''.join(current).strip())
    return param_types




def _extract_param_types_from_json(parameters_json: str):
    """
    从 DB parameters JSON 中提取参数类型列表。
    '[{"parameter_type":"int","parameter_name":"id"}]' → ['int']
    """
    if not parameters_json:
        return []
    try:
        params_list = json.loads(parameters_json) if isinstance(parameters_json, str) else parameters_json
        if not isinstance(params_list, list):
            return []
        return [p.get('parameter_type', '') for p in params_list if isinstance(p, dict)]
    except (json.JSONDecodeError, TypeError):
        return []




def _match_param_types(sig_types: list, db_types: list) -> bool:
    """
    判断签名参数类型与 DB 参数类型是否匹配。
    支持完整类名与短类名的交叉匹配。
    """
    if len(sig_types) != len(db_types):
        return False
    for st, dt in zip(sig_types, db_types):
        # 精确匹配
        if st == dt:
            continue
        # 短类名匹配（签名用全限定名，DB 可能用短类名或反过来）
        st_short = st.rsplit('.', 1)[-1] if '.' in st else st
        dt_short = dt.rsplit('.', 1)[-1] if '.' in dt else dt
        if st_short == dt_short:
            continue
        return False
    return True



def _resolve_method_ids_from_db(db_path: str, class_name: str, method_name: str, parameters_json: str):
    """
    从基线数据库查询 class_id 和 method_id。
    使用 class_name + method_name + parameters 精确匹配。
    
    Args:
        db_path: 基线数据库路径
        class_name: 类名（可能是短类名或全限定名）
        method_name: 方法名
        parameters_json: methods 表中的 parameters JSON 字符串，用于区分重载方法
    
    Returns:
        (class_id, method_id) 或 (None, None)
    """
    import json
    import sqlite3
    if not os.path.exists(db_path):
        return None, None
    
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # 解析类名
        short_class_name = class_name
        package_name = ''
        if '.' in class_name:
            parts = class_name.rsplit('.', 1)
            package_name = parts[0]
            short_class_name = parts[1]
        
        # 解析参数类型列表
        param_types = _extract_param_types_from_json(parameters_json) if parameters_json else []
        
        # 查询匹配的方法
        if package_name:
            cursor.execute('''
                SELECT c.class_id, m.method_id, m.parameters, m.method_name
                FROM methods m
                JOIN class c ON m.class_id = c.class_id
                WHERE c.class_name = ? AND c.package_name = ? AND m.method_name = ?
                ORDER BY m.method_id
            ''', (short_class_name, package_name, method_name))
        else:
            cursor.execute('''
                SELECT c.class_id, m.method_id, m.parameters, m.method_name
                FROM methods m
                JOIN class c ON m.class_id = c.class_id
                WHERE c.class_name = ? AND m.method_name = ?
                ORDER BY m.method_id
            ''', (short_class_name, method_name))
        
        rows = cursor.fetchall()
        conn.close()
        
        if not rows:
            return None, None
        if len(rows) == 1:
            return rows[0]['class_id'], rows[0]['method_id']
        
        # 重载方法：按参数类型精确匹配
        if param_types:
            for row in rows:
                db_types = _extract_param_types_from_json(row['parameters'] or '')
                if _match_param_types(param_types, db_types):
                    return row['class_id'], row['method_id']
        
        # 回退：返回第一个
        return rows[0]['class_id'], rows[0]['method_id']
    except Exception as e:
        print(f"[resolve_method_ids] 查询失败: {e}")
        return None, None




def _query_method_rows(cursor, short_class_name: str, package_name: str, method_name: str, project_id: int):
    """查询指定 class/method/project 的所有行（不含 LIMIT）"""
    if package_name:
        cursor.execute('''
            SELECT m.body, m.annotations, m.access_modifier,
                   m.return_type, m.parameters, m.change_type, m.documentation
            FROM methods m
            JOIN class c ON m.class_id = c.class_id
            WHERE c.class_name = ? AND c.package_name = ? AND m.method_name = ? AND m.project_id = ?
        ''', (short_class_name, package_name, method_name, project_id))
    else:
        cursor.execute('''
            SELECT m.body, m.annotations, m.access_modifier,
                   m.return_type, m.parameters, m.change_type, m.documentation
            FROM methods m
            JOIN class c ON m.class_id = c.class_id
            WHERE c.class_name = ? AND m.method_name = ? AND m.project_id = ?
        ''', (short_class_name, method_name, project_id))
    return cursor.fetchall()




def _match_method_by_params(rows, sig_param_types: list):
    """
    从同名方法行列表中按参数类型精确匹配。
    - 只有 1 行 → 直接返回（无重载）
    - 多行 + 有签名参数 → 按参数类型匹配
    - 多行 + 无签名参数 → 返回第一行（兼容旧调用）
    """
    if not rows:
        return None
    if len(rows) == 1:
        return rows[0]
    if sig_param_types:
        for row in rows:
            db_types = _extract_param_types_from_json(row['parameters'] or '')
            if _match_param_types(sig_param_types, db_types):
                return row
    # 回退：返回第一行
    return rows[0]




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
    # 并发防护：检查是否有正在进行的单方法分析（批量分析不阻塞）
    task_desc = f"方法分析: {request.method_info.get('class_name', '')}.{request.method_info.get('method_name', '')}"
    if not llm_status.start(task_desc):
        raise HTTPException(status_code=409, detail="已有 LLM 分析正在执行中，请等待完成后再试")

    try:
        result = llm_service.analyze_method(
            method_info=request.method_info,
            db_info=request.db_info or {},
            direction=request.direction,
            force_fresh=request.force_fresh,
            baseline=request.baseline,
            version=request.version
        )
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        llm_status.finish()




@router.get("/{baseline}/{version}/sql-summary")
async def get_sql_summary(baseline: str, version: str):
    """获取 SQL 分析汇总（v4.2: 优先使用预计算的 SQL 摘要文件）"""
    data_dir = _resolve_data_path(baseline, version)
   
    # v4.2: 优先尝试 SQL 摘要文件（KB 级）
    sql_summary_filepath = os.path.join(data_dir, "downwards_sql_summary.json")
    if os.path.exists(sql_summary_filepath):
        try:
            with open(sql_summary_filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return {
                'summary': {
                    'total_sql_impacts': data.get('metadata', {}).get('total_sql_impacts', 0),
                    'total_sql_operations': data.get('metadata', {}).get('total_sql_operations', 0),
                    'sql_impacts': data.get('sql_impacts', [])
                },
                'source': 'precomputed'
            }
        except Exception as e:
            logger = __import__('logging').getLogger(__name__)
            logger.warning(f"SQL 摘要文件读取失败，回退到大 JSON: {e}")
   
    # Fallback: 旧格式大 JSON
    from jcci.utils.path_utils import load_call_chains_json_from_dir
    try:
        data = load_call_chains_json_from_dir(data_dir, "downwards")
        call_chains = data.get('dependency_chains') or data.get('call_chains', [])
        dao_methods = sql_analyzer.extract_dao_methods(call_chains)
        summary = sql_analyzer.get_sql_summary(dao_methods)




        return {
            'summary': summary,
            'dao_methods_count': len(dao_methods),
            'source': 'legacy'
        }
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=500, detail=f"Invalid JSON: {str(e)}")
    except HTTPException:
        raise
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
            force_fresh=request.force_fresh
        )
    # elif request.analysis_type == 'chain':
    #     background_tasks.add_task(
    #         llm_service.run_chain_task,
    #         task_id=task_id,
    #         chain_data=request.chain_data or {},
    #         selected_methods=request.selected_methods or [],
    #         direction=request.direction,
    #         baseline=request.baseline,
    #         version=request.version,
    #         force_fresh=request.force_fresh,
    #         custom_system_prompt=request.custom_system_prompt,
    #         custom_analysis_prompt=request.custom_analysis_prompt
    #     )
   
    return {
        'task_id': task_id,
        'status': 'pending',
        'message': '任务已创建，正在排队分析中...'
    }







@router.post("/batch-methods")
async def create_batch_method_task(request: BatchMethodRequest, background_tasks: BackgroundTasks):
    """
    创建批量方法分析任务（支持并发执行）

    改造说明：
    - 启用并发模式后，使用线程池并发调用多个 LLM API KEY
    - 负载均衡器自动分配请求到不同的 API KEY
    - 前端轮询 nodes-status API 可实时看到 Tree 节点标签更新

    配置项：
    - LLM_CONCURRENT_ENABLED: 是否启用并发（默认 True）
    - LLM_CONCURRENT_WORKERS: 并发线程数（默认 5）
    """
    if not request.methods:
        raise HTTPException(status_code=400, detail="methods 列表不能为空")

    # 检查是否超过最大并发任务数
    max_tasks = settings.LLM_MAX_CONCURRENT_TASKS
    if llm_status.get_task_count() >= max_tasks:
        raise HTTPException(
            status_code=429,
            detail=f"当前有 {llm_status.get_task_count()} 个批量任务正在执行，已达到最大并发数 {max_tasks}，请稍后重试"
        )

    task_id = llm_service.create_task(
        analysis_type='batch',
        direction=request.direction,
        baseline=request.baseline,
        version=request.version,
        total_methods=len(request.methods)
    )

    # 注册批量任务状态
    llm_status.start_task(task_id, f"批量分析: {len(request.methods)} 个方法")

    # 后台执行（支持并发）
    background_tasks.add_task(
        _run_batch_task_with_cleanup,
        task_id=task_id,
        methods=request.methods,
        direction=request.direction,
        baseline=request.baseline,
        version=request.version,
        force_fresh=request.force_fresh
    )

    concurrent_info = ""
    if settings.LLM_CONCURRENT_ENABLED and len(request.methods) > 1:
        concurrent_info = f"，并发度={settings.LLM_CONCURRENT_WORKERS}"

    return {
        'task_id': task_id,
        'status': 'pending',
        'message': f'批量分析任务已创建，共 {len(request.methods)} 个方法{concurrent_info}',
        'concurrent_enabled': settings.LLM_CONCURRENT_ENABLED,
        'concurrent_workers': settings.LLM_CONCURRENT_WORKERS
    }


def _run_batch_task_with_cleanup(
    task_id: str,
    methods: List[Dict],
    direction: str,
    baseline: str,
    version: str,
    force_fresh: bool
):
    """批量任务执行包装器，确保任务完成后清理状态"""
    try:
        llm_service.run_batch_method_task(
            task_id=task_id,
            methods=methods,
            direction=direction,
            baseline=baseline,
            version=version,
            force_fresh=force_fresh
        )
    finally:
        llm_status.finish_task(task_id)







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
        # 检查任务类型：batch 类型任务每个方法独立，不需要子结果
        import sqlite3
        conn = sqlite3.connect(settings.DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute('SELECT analysis_type FROM llm_analysis_tasks WHERE task_id = ?', (task_id,))
        task_row = cursor.fetchone()
        is_batch = task_row and task_row['analysis_type'] == 'batch'


        if not is_batch:
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
        class_id = node.get('class_id')
        method_id = node.get('method_id')
       
        status = {
            'class_name': class_name,
            'method_name': method_name,
            'change_type': change_type,
            'class_id': class_id,
            'method_id': method_id,
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







# ── 入口节点提取辅助函数 ──────────────────────────────────




_ENTRY_ROOT_TYPES = {'HTTP_API', 'SCHEDULED_TASK', 'EVENT_LISTENER', 'MESSAGE_CONSUMER', 'CONTROLLER_BY_CONVENTION'}


def _find_endpoint_nodes(children: list, direction: str) -> list:
    """
    递归查找端点节点。
    - upwards: 查找 root_type 为入口类型 (HTTP_API 等) 的节点
    - downwards: 查找有 dao_info 的 DAO/Mapper 节点（含 SQL 信息），或叶子节点
    """
    endpoints = []
    for child in children:
        if direction == 'upwards':
            if child.get('root_type') in _ENTRY_ROOT_TYPES:
                endpoints.append({
                    'class_name': child.get('class_name', ''),
                    'method_name': child.get('method_name', ''),
                    'api_paths': child.get('api_paths', []),
                    'documentation': child.get('documentation', ''),
                    'root_type': child.get('root_type', '')
                })
        else:
            # downwards: 优先收集有 dao_info 的 DAO/Mapper 节点
            di = child.get('dao_info')
            if di and isinstance(di, dict) and di.get('sql_type'):
                # Mapper/DAO 节点有 SQL 信息，作为端点（跳过递归其 SQL 子节点）
                endpoints.append({
                    'class_name': child.get('class_name', ''),
                    'method_name': child.get('method_name', ''),
                    'api_paths': [],
                    'documentation': child.get('documentation', ''),
                    'dao_sql_type': di.get('sql_type', ''),
                    'dao_tables': di.get('tables', []) if isinstance(di.get('tables'), list) else [],
                    'dao_method_signature': di.get('method_signature', ''),
                    'dao_sql_content': di.get('sql_content', ''),
                    'dao_mapper_method': di.get('mapper_method', '')
                })
                continue  # 已作为端点，不再递归 SQL 子节点
            # 普通叶子节点（无子节点或被标记为叶子）
            grand_children = child.get('children', [])
            if not grand_children or child.get('is_leaf'):
                endpoints.append({
                    'class_name': child.get('class_name', ''),
                    'method_name': child.get('method_name', ''),
                    'api_paths': [],
                    'documentation': child.get('documentation', ''),
                    'dao_sql_type': di.get('sql_type', '') if di else '',
                    'dao_tables': di.get('tables', []) if di and isinstance(di.get('tables'), list) else [],
                    'dao_method_signature': di.get('method_signature', '') if di else '',
                    'dao_sql_content': di.get('sql_content', '') if di else '',
                    'dao_mapper_method': di.get('mapper_method', '') if di else ''
                })
        # 继续递归子节点
        if child.get('children'):
            endpoints.extend(_find_endpoint_nodes(child['children'], direction))
    return endpoints


def _find_node_documentation(chain_tree: dict, package_class: str, method_signature: str) -> str:
    """
    在调用链树中递归查找匹配节点的 documentation。
    用于兼容旧版 JSON（entry_points 中无 documentation 字段）的回退逻辑。
    """
    if not chain_tree or not package_class or not method_signature:
        return ''
    if (chain_tree.get('package_class') == package_class
            and chain_tree.get('method_signature') == method_signature):
        doc = chain_tree.get('documentation', '')
        return doc if doc and doc != 'None' else ''
    for child in chain_tree.get('children', []):
        result = _find_node_documentation(child, package_class, method_signature)
        if result:
            return result
    return ''


@router.get("/{baseline}/{version}/chain-methods")
async def get_chain_methods(baseline: str, version: str, direction: str = 'upwards',
                             offset: int = 0, limit: int = 100):
    """
    获取调用链方法列表（供分析配置页使用）。
    支持分页：offset 为起始位置，limit 为每次返回数量。
    """
    data_dir = _resolve_data_path(baseline, version)
   
    # 解析基线数据库路径，用于查询 class_id/method_id
    _db_path_for_id = None
    _baseline_short = _extract_short_tag(baseline)
    for _db_candidate in [
        os.path.join(settings.RESULT_DIR, _baseline_short, f"{_baseline_short}_baseline.db"),
        os.path.join(settings.RESULT_DIR, baseline, f"{baseline}_baseline.db"),
    ]:
        if os.path.exists(_db_candidate):
            _db_path_for_id = _db_candidate
            break
    if not _db_path_for_id:
        _suffix = '_' + _baseline_short
        for _item in sorted(os.listdir(settings.RESULT_DIR)):
            if _item.endswith(_suffix) and os.path.isdir(os.path.join(settings.RESULT_DIR, _item)):
                _db_candidate = os.path.join(settings.RESULT_DIR, _item, f"{_item}_baseline.db")
                if os.path.exists(_db_candidate):
                    _db_path_for_id = _db_candidate
                    break
   
    # 辅助函数：查询 class_id/method_id
    def _resolve_ids(_cls_name, _mtd_name, _params_json):
        if not _db_path_for_id:
            return None, None
        return _resolve_method_ids_from_db(_db_path_for_id, _cls_name, _mtd_name, _params_json)
   
    # v4.2: 优先尝试索引文件
    index_filename = f"{direction}_index.json"
    index_filepath = os.path.join(data_dir, index_filename)
    if os.path.exists(index_filepath):
        try:
            with open(index_filepath, 'r', encoding='utf-8') as f:
                index_data = json.load(f)
           
            index_methods = index_data.get('methods', [])
            methods_with_cache = []
            seen = set()
           
            conn = __import__('sqlite3').connect(settings.DB_PATH)
            conn.row_factory = __import__('sqlite3').Row
            cursor = conn.cursor()
           
            for im in index_methods:
                class_name = im.get('class_name', '')
                method_name = im.get('method_name', '')
                key = f"{class_name}.{method_name}"
                if key in seen:
                    continue
                seen.add(key)
               
                # 查询 AI 分析状态（与 nodes-status API 逻辑一致）
                method_status = 'none'
                upwards_chain_status = 'none'
                downwards_chain_status = 'none'
               
                try:
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
                    'signature': im.get('method_signature', f"{method_name}()"),
                    'change_type': im.get('change_type', 'UNKNOWN'),
                    'parameters': '[]',
                    'return_type': '',
                    'documentation': '',
                    'method_status': method_status,
                    'upwards_chain_status': upwards_chain_status,
                    'downwards_chain_status': downwards_chain_status,
                    'endpoints': [],
                    'class_id': _resolve_ids(class_name, method_name, '[]')[0],
                    'method_id': _resolve_ids(class_name, method_name, '[]')[1]
                })
           
            conn.close()
           
            # 向下方向：从 JSON 补充 endpoints（索引文件不含链数据）
            if direction == 'downwards':
                try:
                    from jcci.utils.path_utils import load_call_chains_json_from_dir
                    chain_data = load_call_chains_json_from_dir(data_dir, "downwards")
                except FileNotFoundError:
                    chain_data = None
               
                if chain_data:
                    chains_list = chain_data.get('call_chains', chain_data.get('dependency_chains', []))
                    # 构建 class_name.method_name -> chain 映射
                    chain_map = {}
                    for c in chains_list:
                        mi = c.get('method_info', {})
                        k = f"{mi.get('class_name', '')}.{mi.get('method_name', '')}"
                        chain_map[k] = c
                    # 为每个方法提取 endpoints
                    for m in methods_with_cache:
                        k = f"{m['class_name']}.{m['method_name']}"
                        c = chain_map.get(k)
                        if c:
                            cr = c.get('chain', {})
                            di = cr.get('dao_info')
                            if di and isinstance(di, dict) and di.get('sql_type'):
                                # 链根节点自身就是 DAO/Mapper，直接作为端点
                                m['endpoints'] = [{
                                    'class_name': cr.get('class_name', ''),
                                    'method_name': cr.get('method_name', ''),
                                    'api_paths': [],
                                    'documentation': cr.get('documentation', ''),
                                    'dao_sql_type': di.get('sql_type', ''),
                                    'dao_tables': di.get('tables', []) if isinstance(di.get('tables'), list) else [],
                                    'dao_method_signature': di.get('method_signature', ''),
                                    'dao_sql_content': di.get('sql_content', ''),
                                    'dao_mapper_method': di.get('mapper_method', '')
                                }]
                            else:
                                chain_children = cr.get('children', [])
                                m['endpoints'] = _find_endpoint_nodes(chain_children, direction)
           
            total = len(methods_with_cache)
            # 分页切片
            paged = methods_with_cache[offset:offset + limit]
           
            return {
                'methods': paged,
                'total': total,
                'offset': offset,
                'limit': limit,
                'has_more': (offset + limit) < total,
                'source': 'index'
            }
        except Exception as e:
            logger = __import__('logging').getLogger(__name__)
            logger.warning(f"索引文件读取失败，回退到大 JSON: {e}")
   
    # Fallback: 从 JSON 加载
    from jcci.utils.path_utils import load_call_chains_json_from_dir
    try:
        data = load_call_chains_json_from_dir(data_dir, direction)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"{direction} call chains file not found")
    except HTTPException:
        raise
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
       
        # 提取端点节点（入口或出口）
        # 1) 优先使用 chain 顶层 entry_points（最准确）
        raw_entry_points = chain.get('entry_points', [])
        if raw_entry_points:
            endpoints = []
            chain_tree = chain.get('chain', {})
            for ep in raw_entry_points:
                # 从 package_class 提取短类名
                pkg = ep.get('package_class', '')
                short_cls = pkg.split('.')[-1] if '.' in pkg else pkg
                # 从 method_signature 提取方法名（去掉参数部分）
                sig = ep.get('method_signature', '')
                short_mth = sig.split('(')[0] if '(' in sig else sig
                # documentation: 优先从 entry_points 取，回退到 chain 树节点
                doc = ep.get('documentation', '')
                if not doc:
                    sig_for_match = ep.get('method_signature', '')
                    doc = _find_node_documentation(chain_tree, pkg, sig_for_match)
                endpoints.append({
                    'class_name': short_cls,
                    'method_name': short_mth,
                    'api_paths': ep.get('api_paths', []),
                    'documentation': doc,
                    'root_type': ep.get('root_type', '')
                })
        # 2) 向下方向：优先检查链根节点自身是否有 dao_info（直接 DAO 方法）
        elif direction == 'downwards':
            cr = chain.get('chain', {})
            di = cr.get('dao_info')
            if di and isinstance(di, dict) and di.get('sql_type'):
                # 链根节点自身就是 DAO/Mapper，直接作为端点
                endpoints = [{
                    'class_name': cr.get('class_name', ''),
                    'method_name': cr.get('method_name', ''),
                    'api_paths': [],
                    'documentation': cr.get('documentation', ''),
                    'dao_sql_type': di.get('sql_type', ''),
                    'dao_tables': di.get('tables', []) if isinstance(di.get('tables'), list) else [],
                    'dao_method_signature': di.get('method_signature', ''),
                    'dao_sql_content': di.get('sql_content', ''),
                    'dao_mapper_method': di.get('mapper_method', '')
                }]
            else:
                # 根节点不是 DAO，递归查找 children
                chain_children = cr.get('children', [])
                endpoints = _find_endpoint_nodes(chain_children, direction)
        # 3) 否则检查链根节点自身是否为入口
        elif chain.get('chain', {}).get('root_type') in _ENTRY_ROOT_TYPES:
            cr = chain['chain']
            endpoints = [{
                'class_name': cr.get('class_name', ''),
                'method_name': cr.get('method_name', ''),
                'api_paths': cr.get('api_paths', []),
                'documentation': cr.get('documentation', ''),
                'root_type': cr.get('root_type', '')
            }]
        # 4) 否则递归遍历 children 树
        else:
            chain_children = chain.get('chain', {}).get('children', [])
            endpoints = _find_endpoint_nodes(chain_children, direction)




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
            'downwards_chain_status': downwards_chain_status,
            'endpoints': endpoints,
            'class_id': _resolve_ids(class_name, method_name, mi.get('parameters', '[]'))[0],
            'method_id': _resolve_ids(class_name, method_name, mi.get('parameters', '[]'))[1]
        })
   
    conn.close()
   
    total = len(methods_with_cache)
    # 分页切片
    paged = methods_with_cache[offset:offset + limit]
   
    return {
        'methods': paged,
        'total': total,
        'offset': offset,
        'limit': limit,
        'has_more': (offset + limit) < total,
        'source': 'legacy'
    }







# ── v4.2: 按需单链加载 API ──




@router.get("/{baseline}/{version}/chain/{direction}")
async def get_single_chain(baseline: str, version: str, direction: str, class_name: str = '', method_name: str = ''):
    """
    v4.2: 按需加载单条调用链（KB-MB 级，而非加载整个 GB 级文件）。
   
    优先从独立单链文件加载，回退到大 JSON。
    """
    if not class_name or not method_name:
        raise HTTPException(status_code=400, detail="class_name and method_name are required")
   
    if direction not in ('upwards', 'downwards'):
        raise HTTPException(status_code=400, detail="direction must be 'upwards' or 'downwards'")
   
    data_dir = _resolve_data_path(baseline, version)
   
    # v4.2: 优先尝试独立单链文件
    # 索引文件中记录了 chain_file，但我们通过扫描目录来查找
    chain_dir = os.path.join(data_dir, direction)
    if os.path.isdir(chain_dir):
        # 尝试匹配文件名（文件名包含完整类名和方法签名）
        for filename in os.listdir(chain_dir):
            if not filename.endswith('.json'):
                continue
            # 从文件名提取信息: package_class.method_signature.json
            name_no_ext = filename[:-5]
            # 检查是否包含目标类名和方法名
            if f".{class_name}." in name_no_ext or name_no_ext.endswith(f".{class_name}"):
                # 进一步检查方法名
                if method_name in name_no_ext:
                    try:
                        with open(os.path.join(chain_dir, filename), 'r', encoding='utf-8') as f:
                            chain_data = json.load(f)
                        return {
                            'chain': chain_data,
                            'source': 'individual',
                            'filename': filename
                        }
                    except Exception:
                        continue
   
    # Fallback: 从 JSON 中查找
    from jcci.utils.path_utils import load_call_chains_json_from_dir
    try:
        data = load_call_chains_json_from_dir(data_dir, direction)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"{direction} call chains file not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
   
    chains_list = data.get('impact_chains' if direction == 'upwards' else 'call_chains',
                          data.get('dependency_chains', []))
   
    for chain in chains_list:
        mi = chain.get('method_info', {})
        if mi.get('class_name') == class_name and mi.get('method_name') == method_name:
            return {
                'chain': chain.get('chain', {}),
                'source': 'legacy'
            }
   
    raise HTTPException(status_code=404, detail=f"Chain not found for {class_name}.{method_name}")