"""
JCCI 调用链分析与LLM智能分析平台

基于Streamlit构建的Web界面，用于：
1. 展示双向调用链分析结果
2. 支持点击方法/调用链进行智能分析
3. 集成LLM提供测试建议和变更分析

注意：使用前需要创建 config.py 文件（参考 config.py.template）
"""

# 标准库导入
import json
import logging
import os
import sqlite3
import time
import uuid
from typing import Dict, List, Optional

# 第三方库导入
import requests
import streamlit as st

# 导入配置
try:
    from config import (
        LLM_API_URL,
        LLM_API_KEY,
        LLM_MODEL,
        DB_PATH,
        RESULT_DIR,
        STREAMLIT_PORT,
        STREAMLIT_HOST
    )
except ImportError:
    st.error("""
    ❌ 配置文件不存在！
    
    请按照以下步骤操作：
    1. 复制 config.py.template 为 config.py
    2. 编辑 config.py，填入你的API Key和路径配置
    3. 重新启动应用
    """)
    st.stop()

# 导入任务管理器
from task_manager import get_task_manager

logger = logging.getLogger(__name__)


# ==================== 页面导航辅助函数 ====================
def navigate_to(page: str):
    """
    导航到指定页面
    
    Args:
        page: 页面名称 ('submit', 'tasks', 'view')
    """
    # 设置 session state 标记
    st.session_state.navigate_to = page
    # 重新运行以触发导航
    st.rerun()


def check_navigation():
    """
    检查是否有导航请求，如果有则更新 URL
    """
    if 'navigate_to' in st.session_state:
        target_page = st.session_state.navigate_to
        del st.session_state.navigate_to
        
        # 构建新的 URL
        if target_page == 'submit':
            new_url = '?page=submit'
        elif target_page == 'tasks':
            new_url = '?page=tasks'
        else:
            new_url = f'?baseline={target_page}'
        
        # 使用 JavaScript 跳转（这是唯一能修改 URL 的方式）
        st.markdown(
            f"""
            <script>
                window.location.replace('{new_url}');
            </script>
            """,
            unsafe_allow_html=True
        )
        # 如果 JavaScript 不执行，至少重新渲染页面
        st.rerun()


# ==================== 任务管理页面 ====================
def render_task_submission_page():
    """渲染任务提交页面"""
    
    st.markdown("""
    ### 📝 填写分析参数
    
    请填写以下信息以启动代码变更分析任务。任务将在后台异步执行，完成后您可以访问结果页面。
    """)
    
    # 表单输入
    with st.form("submit_task_form"):
        col1, col2 = st.columns(2)
        
        with col1:
            git_url = st.text_input(
                "Git 仓库地址",
                value="https://github.com/carpenlee-cyber/mall.git",
                placeholder="https://github.com/username/repo.git",
                help="Git 仓库的 HTTPS 或 SSH 地址"
            )
            username = st.text_input(
                "Git 用户名",
                value="carpenlee-cyber",
                placeholder="your_username",
                help="Git 用户名（用于认证）"
            )
        
        with col2:
            tag_old = st.text_input(
                "旧版本标签",
                value="baseline_20260508_01",
                placeholder="v1.0.0 或 commit hash",
                help="对比的起始版本"
            )
            tag_new = st.text_input(
                "新版本标签",
                value="baseline_fix1_20260508_02",
                placeholder="v2.0.0 或 commit hash",
                help="对比的目标版本"
            )
        
        max_depth = st.slider(
            "最大分析深度",
            min_value=1,
            max_value=10,
            value=5,
            help="调用链分析的最大深度（建议 3-7）"
        )
        
        submitted = st.form_submit_button("🚀 提交分析任务", type="primary")
    
    if submitted:
        # 验证输入
        if not all([git_url, username, tag_old, tag_new]):
            st.error("❌ 请填写所有必填字段")
            return
        
        try:
            # 获取任务管理器
            task_manager = get_task_manager(DB_PATH)
            
            # 提交任务（显示加载动画）
            with st.spinner("⏳ 正在提交任务，请稍候..."):
                task_id, result_url = task_manager.submit_task(
                    git_url=git_url,
                    username=username,
                    tag_old=tag_old,
                    tag_new=tag_new,
                    max_depth=max_depth
                )
            
            # 检查是否是已有的完成任务
            if result_url:
                # 任务已完成，直接显示结果
                st.success("✅ 发现已完成的分析任务！")
                st.info(f"""
                ### 📊 任务信息
                
                - **任务 ID**: `{task_id}`
                - **状态**: ✅ 已完成
                - **结果**: 可以直接访问
                
                该分析任务已经完成，您可以直接查看结果，无需重新分析。
                """)
                
            else:
                # 新任务或正在执行的任务
                st.success("✅ 任务提交成功！")
                st.info(f"""
                ### 📊 任务信息
                
                - **任务 ID**: `{task_id}`
                - **状态**: 正在后台执行
                - **预计时间**: 根据代码规模，可能需要几分钟到几十分钟
                
                """)
                 
                # 设置 session state
                st.session_state.task_submitted = True
                st.session_state.task_id = task_id
                
                # 延迟 2 秒后自动跳转，让用户看到成功消息
                # 使用 JavaScript + setTimeout 实现延迟跳转
                st.markdown(
                    """
                    <script>
                        setTimeout(function() {
                            window.location.replace('?page=tasks');
                        }, 2000);  // 2秒后跳转
                    </script>
                    """,
                    unsafe_allow_html=True
                )
            
        except Exception as e:           
            logger.error(f"提交任务失败: {e}", exc_info=True)


def render_task_list_page():
    """渲染任务列表页面"""
  
    st.markdown("""
    ### 📊 查看所有分析任务
    
    这里显示最近提交的分析任务及其状态。点击任务可查看详细信息和访问结果。
    """)
    
    # 获取任务管理器
    task_manager = get_task_manager(DB_PATH)
    
    # 获取任务列表
    tasks = task_manager.list_tasks(limit=50)
    
    if not tasks:
        st.info("📭 暂无任务记录")
        
        if st.button("➕ 提交新任务"):
            navigate_to('submit')
        return
    
    # 显示任务统计
    total = len(tasks)
    completed = sum(1 for t in tasks if t['status'] == 'completed')
    running = sum(1 for t in tasks if t['status'] == 'running')
    failed = sum(1 for t in tasks if t['status'] == 'failed')
    pending = sum(1 for t in tasks if t['status'] == 'pending')
    
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("总任务数", total)
    col2.metric("已完成", completed)
    col3.metric("运行中", running)
    col4.metric("失败", failed)
    
    st.markdown("---")
    
    # 显示任务列表
    for task in tasks:
        status = task['status']
        
        # 根据状态设置图标和颜色
        if status == 'completed':
            icon = "✅"
            color = "green"
        elif status == 'running':
            icon = "🔄"
            color = "blue"
        elif status == 'failed':
            icon = "❌"
            color = "red"
        else:
            icon = "⏳"
            color = "gray"
        
        with st.expander(f"{icon} 任务 {task['task_id']} - {task.get('tag_old', '')} → {task.get('tag_new', '')}", expanded=False):
            col1, col2 = st.columns([3, 1])
            
            with col1:
                st.markdown(f"**状态**: <span style='color:{color}'>{status.upper()}</span>", unsafe_allow_html=True)
                st.markdown(f"**Git 仓库**: `{task.get('git_url', 'N/A')}`")
                st.markdown(f"**版本对比**: `{task.get('tag_old', 'N/A')}` → `{task.get('tag_new', 'N/A')}`")
                st.markdown(f"**分析深度**: {task.get('max_depth', 5)}")
                st.markdown(f"**创建时间**: {task.get('created_at', 'N/A')}")
                
                if task.get('progress') is not None:
                    st.progress(task['progress'] / 100.0)
                    st.caption(f"进度: {task['progress']:.1f}%")
                
                if status == 'completed' and task.get('result_url'):
                    st.success(f"✅ 分析完成！")
                    st.markdown(f"**访问链接**: [{task['result_url']}]({task['result_url']})")                    
                                    
                if status == 'failed' and task.get('error_message'):
                    st.error(f"❌ 错误: {task['error_message']}")
            
            with col2:
                if status == 'running' or status == 'pending':
                    if st.button("🔄 刷新", key=f"refresh_{task['task_id']}"):
                        st.rerun()
    

# ==================== 用户会话管理 ====================
def get_user_session_id():
    """获取或创建用户会话ID"""
    if 'user_session_id' not in st.session_state:
        # 基于IP和时间戳生成唯一ID
        session_id = str(uuid.uuid4())[:8]
        st.session_state.user_session_id = session_id
    return st.session_state.user_session_id


def get_session_db_path(commit_range: str = None) -> str:
    """
    获取当前会话的数据库路径
    
    Args:
        commit_range: commit范围标识符（格式：baseline..version），用于确定基线数据库
        
    Returns:
        str: 会话专用的数据库路径
    """
    if 'session_db_path' not in st.session_state or commit_range:
        # 根据commit范围确定基线数据库
        if commit_range:
            # 从commit范围提取基线标识符（格式：mall_20260403_01..20260404_01）
            if '..' in commit_range:
                baseline_name = commit_range.split('..')[0]
            else:
                baseline_name = commit_range
            
            # 构造基线数据库文件名
            db_filename = f"{baseline_name}_baseline.db"
            
            # 首先尝试在analyze_result的基线目录中查找
            baseline_dir = os.path.join(RESULT_DIR, baseline_name)
            db_path = os.path.join(baseline_dir, db_filename)
            
            # 验证数据库文件是否存在
            if not os.path.exists(db_path):
                st.error(f"❌ 基线数据库不存在: {db_path}")
                st.error("💡 提示：请确保已运行workflow1.py生成基线数据库")
                st.stop()
            
            st.session_state.session_db_path = db_path
            st.session_state.current_commit_range = commit_range
        else:
            # 默认使用配置中的数据库路径
            st.session_state.session_db_path = DB_PATH
    
    return st.session_state.session_db_path


# 页面配置
st.set_page_config(
    page_title="JCCI 调用链分析平台",
    page_icon="🔗",
    layout="wide",
    initial_sidebar_state="expanded"
)


# ==================== 数据加载函数 ====================
@st.cache_data(ttl=3600)
def load_json_file(filepath: str) -> Dict:
    """加载JSON文件（带缓存）"""
    if not os.path.exists(filepath):
        return {}
    with open(filepath, 'r', encoding='utf-8') as f:
        return json.load(f)


def load_text_file(filepath: str) -> str:
    """加载文本文件（不缓存，确保实时刷新）"""
    if not os.path.exists(filepath):
        return ""
    with open(filepath, 'r', encoding='utf-8') as f:
        return f.read()


@st.cache_data(ttl=3600)
def query_database(query: str, params: tuple = (), db_path: str = None) -> List[Dict]:
    """查询数据库（带缓存）"""
    if db_path is None:
        db_path = get_session_db_path()
    
    if not os.path.exists(db_path):
        return []
    
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    try:
        cursor.execute(query, params)
        rows = cursor.fetchall()
        return [dict(row) for row in rows]
    except Exception as e:
        st.error(f"数据库查询错误: {e}")
        return []
    finally:
        conn.close()


def get_method_info_from_db(class_name: str, method_name: str) -> Dict:
    """从数据库获取方法的详细信息"""
    # 先查找class_id
    class_query = """
        SELECT class_id, filepath, package_name, class_type, 
               is_controller, controller_base_url, change_type
        FROM class
        WHERE class_name = ?
        LIMIT 1
    """
    classes = query_database(class_query, (class_name,))
    
    if not classes:
        return {}
    
    class_info = classes[0]
    class_id = class_info['class_id']
    
    # 再查找method
    method_query = """
        SELECT m.*, c.filepath, c.package_name, c.class_type,
               c.is_controller, c.controller_base_url
        FROM methods m
        JOIN class c ON m.class_id = c.class_id
        WHERE m.class_id = ? AND m.method_name = ?
        ORDER BY m.project_id DESC
        LIMIT 1
    """
    methods = query_database(method_query, (class_id, method_name))
    
    if methods:
        method_info = methods[0]
        method_info['class_info'] = class_info
        return method_info
    
    return {}


def get_chain_detail_from_json(json_data: Dict, target_class: str, target_method: str) -> Dict:
    """从JSON数据中提取特定方法的调用链详情"""
    chains = json_data.get('impact_chains', [])
    
    for chain_data in chains:
        method_info = chain_data.get('method_info', {})
        if (method_info.get('class_name') == target_class and 
            method_info.get('method_name') == target_method):
            return chain_data
    
    return {}


# ==================== LLM分析函数 ====================
def save_to_llm_cache(analysis_type: str, direction: str, class_name: str, 
                      method_name: str, change_type: str, analysis_result: str,
                      chain_index: Optional[int] = None, method_signature: str = "",
                      input_params: str = "", model_name: str = LLM_MODEL,
                      prompt_tokens: int = 0, completion_tokens: int = 0,
                      total_tokens: int = 0, analysis_duration: float = 0.0,
                      session_id: str = "") -> bool:
    """保存LLM分析结果到缓存表"""
    db_path = get_session_db_path()
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            INSERT OR REPLACE INTO llm_analysis_cache 
            (analysis_type, direction, class_name, method_name, method_signature,
             change_type, chain_index, input_params, analysis_result, model_name,
             prompt_tokens, completion_tokens, total_tokens, analysis_duration,
             is_fresh_analysis, session_id, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, CURRENT_TIMESTAMP)
        """, (
            analysis_type, direction, class_name, method_name, method_signature,
            change_type, chain_index, input_params, analysis_result, model_name,
            prompt_tokens, completion_tokens, total_tokens, analysis_duration, session_id
        ))
        
        conn.commit()
        return True
        
    except Exception as e:
        st.error(f"保存LLM缓存失败: {e}")
        conn.rollback()
        return False
        
    finally:
        conn.close()


def get_from_llm_cache(analysis_type: str, direction: str, class_name: str,
                       method_name: str, change_type: str,
                       chain_index: Optional[int] = None) -> Optional[str]:
    """从缓存表获取LLM分析结果"""
    db_path = get_session_db_path()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            SELECT analysis_result, is_fresh_analysis, created_at, model_name,
                   analysis_duration, total_tokens
            FROM llm_analysis_cache
            WHERE analysis_type = ? 
              AND direction = ?
              AND class_name = ?
              AND method_name = ?
              AND change_type = ?
              AND (chain_index = ? OR (? IS NULL AND chain_index IS NULL))
            ORDER BY created_at DESC
            LIMIT 1
        """, (analysis_type, direction, class_name, method_name, change_type,
              chain_index, chain_index))
        
        row = cursor.fetchone()
        if row:
            return dict(row)
        return None
        
    except Exception as e:
        st.error(f"查询LLM缓存失败: {e}")
        return None
        
    finally:
        conn.close()


def call_llm_api(prompt: str, system_prompt: str = "") -> str:
    """调用LLM API进行分析"""
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LLM_API_KEY}"
    }
    
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})
    
    payload = {
        "model": LLM_MODEL,
        "messages": messages,
        "max_tokens": 2000,
        "temperature": 0.7
    }
    
    try:
        response = requests.post(
            f"{LLM_API_URL}/chat/completions",
            json=payload,
            headers=headers,
            timeout=60
        )
        
        if response.status_code == 200:
            result = response.json()
            return result['choices'][0]['message']['content']
        else:
            return f"API调用失败: HTTP {response.status_code}\n{response.text}"
    except Exception as e:
        return f"请求异常: {str(e)}"


def analyze_single_method(method_info: Dict, db_info: Dict, direction: str = 'upwards', 
                          force_fresh: bool = False) -> Dict:
    """
    分析单个方法的变更和测试建议
    
    Args:
        method_info: 方法信息字典
        db_info: 数据库补充信息
        direction: 分析方向 ('upwards' 或 'downwards')
        force_fresh: 是否强制全新分析（忽略缓存）
    
    Returns:
        Dict: {
            'result': str - 分析结果文本,
            'from_cache': bool - 是否从缓存读取,
            'cache_info': dict - 缓存信息（如果从缓存读取）
        }
    """
    change_type = method_info.get('change_type', 'UNKNOWN')
    class_name = method_info.get('class_name', '')
    method_name = method_info.get('method_name', '')
    parameters = method_info.get('parameters', '[]')
    return_type = method_info.get('return_type', '')
    method_signature = method_info.get('method_signature', '')
    
    # 尝试从缓存获取（除非强制全新分析）
    if not force_fresh:
        cached = get_from_llm_cache('method', direction, class_name, method_name, change_type)
        if cached:
            return {
                'result': cached['analysis_result'],
                'from_cache': True,
                'cache_info': {
                    'created_at': cached['created_at'],
                    'model_name': cached['model_name'],
                    'analysis_duration': cached['analysis_duration'],
                    'total_tokens': cached['total_tokens']
                }
            }
    
    # 构建分析提示
    system_prompt = """你是一位资深的Java代码审查专家和测试工程师。请分析代码变更并提供专业的测试建议。
回答要求：
1. 使用中文回答
2. 结构清晰，分点说明
3. 重点关注变更带来的影响和风险
4. 提供具体可执行的测试建议"""
    
    prompt = f"""请分析以下Java方法的变更情况，并给出测试建议：

【方法基本信息】
- 类名: {class_name}
- 方法名: {method_name}
- 参数: {parameters}
- 返回类型: {return_type}
- 变更类型: {change_type}

【数据库补充信息】
"""
    
    if db_info:
        prompt += f"""
- 文件路径: {db_info.get('filepath', 'N/A')}
- 包名: {db_info.get('package_name', 'N/A')}
- 类类型: {db_info.get('class_type', 'N/A')}
- 是否为Controller: {'是' if db_info.get('is_controller') else '否'}
- Controller基础URL: {db_info.get('controller_base_url', 'N/A')}
- 行号范围: {db_info.get('start_line', 'N/A')}-{db_info.get('end_line', 'N/A')}
- 访问修饰符: {db_info.get('access_modifier', 'N/A')}
- 是否静态方法: {'是' if db_info.get('is_static') else '否'}
- 是否抽象方法: {'是' if db_info.get('is_abstract') else '否'}
- 文档注释: {db_info.get('documentation', 'N/A')}
"""
        
        # 如果有方法体，添加方法体信息
        body = db_info.get('body')
        if body and isinstance(body, list):
            prompt += "\n【方法实现】\n```java\n" + "\n".join(body) + "\n```\n"
    
    prompt += """
【分析要求】
请从以下几个方面进行分析：

1. **变更内容分析**
   - 该方法的新增/修改/删除带来了什么功能变化
   - 可能的业务影响范围

2. **代码质量评估**
   - 方法设计的合理性
   - 潜在的性能问题
   - 异常处理是否完善

3. **测试建议**
   - 单元测试用例设计（至少3个）
   - 集成测试要点
   - 边界条件和异常场景
   - 需要Mock的对象和数据

4. **风险评估**
   - 高风险操作识别
   - 可能的副作用
   - 回归测试建议

请按照以上结构给出详细分析。"""
    
    # 调用LLM API并计时
    start_time = time.time()
    result = call_llm_api(prompt, system_prompt)
    duration = time.time() - start_time
    
    # 保存到缓存
    user_session_id = get_user_session_id()
    save_to_llm_cache(
        analysis_type='method',
        direction=direction,
        class_name=class_name,
        method_name=method_name,
        change_type=change_type,
        analysis_result=result,
        method_signature=method_signature,
        input_params=json.dumps({'parameters': parameters, 'return_type': return_type}),
        model_name=LLM_MODEL,
        analysis_duration=duration,
        session_id=user_session_id
    )
    
    return {
        'result': result,
        'from_cache': False,
        'cache_info': None
    }


def analyze_call_chain(chain_data: Dict, direction: str, force_fresh: bool = False) -> Dict:
    """
    分析整个调用链的影响和风险
    
    Args:
        chain_data: 调用链数据字典
        direction: 分析方向 ('upwards' 或 'downwards')
        force_fresh: 是否强制全新分析（忽略缓存）
    
    Returns:
        Dict: {
            'result': str - 分析结果文本,
            'from_cache': bool - 是否从缓存读取,
            'cache_info': dict - 缓存信息（如果从缓存读取）
        }
    """
    method_info = chain_data.get('method_info', {})
    entry_points = chain_data.get('entry_points', [])
    
    class_name = method_info.get('class_name', '')
    method_name = method_info.get('method_name', '')
    change_type = method_info.get('change_type', 'UNKNOWN')
    method_signature = method_info.get('method_signature', '')
    
    # 尝试从缓存获取（除非强制全新分析）
    if not force_fresh:
        cached = get_from_llm_cache('chain', direction, class_name, method_name, change_type)
        if cached:
            return {
                'result': cached['analysis_result'],
                'from_cache': True,
                'cache_info': {
                    'created_at': cached['created_at'],
                    'model_name': cached['model_name'],
                    'analysis_duration': cached['analysis_duration'],
                    'total_tokens': cached['total_tokens']
                }
            }
    
    system_prompt = """你是一位资深的系统架构师和测试专家。请分析调用链路的影响范围和测试策略。
回答要求：
1. 使用中文回答
2. 从系统整体角度分析影响面
3. 提供端到端的测试策略
4. 关注链路中的薄弱环节"""
    
    prompt = f"""请分析以下{'向上' if direction == 'upwards' else '向下'}调用链路：

【变更方法信息】
- 类名: {method_info.get('class_name', 'N/A')}
- 方法名: {method_info.get('method_name', 'N/A')}
- 变更类型: {method_info.get('change_type', 'UNKNOWN')}
- 参数: {method_info.get('parameters', 'N/A')}

【入口点信息】
"""
    
    if entry_points:
        for i, entry in enumerate(entry_points, 1):
            prompt += f"""
{i}. 入口类型: {entry.get('root_type', 'N/A')}
   - 类: {entry.get('package_class', 'N/A')}
   - 方法: {entry.get('method_signature', 'N/A')}
   - 距离变更点的深度: {entry.get('depth_from_change', 'N/A')}
"""
    else:
        prompt += "未找到明确的入口点\n"
    
    prompt += f"""
【调用链方向】
{'向上分析（影响面）: 谁调用了变更方法，寻找受影响的入口API' if direction == 'upwards' else '向下分析（功能风险）: 变更方法调用了谁，评估功能风险'}

【分析要求】
请从以下几个方面进行分析：

1. **调用链路概览**
   - 链路的起点和终点
   - 关键节点识别
   - 链路复杂度评估

2. **影响面分析**
   {'- 哪些API端点会受到影响' if direction == 'upwards' else '- 依赖了哪些下游服务/组件'}
   - 影响的用户群体或业务场景
   - 可能的级联影响

3. **风险评估**
   - 链路中的单点故障
   - 性能瓶颈识别
   - 数据一致性风险

4. **测试策略**
   - 端到端测试场景设计
   - 需要重点关注的环节
   - 监控和告警建议
   - 灰度发布策略

5. **优化建议**
   - 链路简化可能性
   - 容错机制改进
   - 性能优化方向

请按照以上结构给出详细分析。"""
    
    # 调用LLM API并计时
    start_time = time.time()
    result = call_llm_api(prompt, system_prompt)
    duration = time.time() - start_time
    
    # 保存到缓存
    user_session_id = get_user_session_id()
    save_to_llm_cache(
        analysis_type='chain',
        direction=direction,
        class_name=class_name,
        method_name=method_name,
        change_type=change_type,
        analysis_result=result,
        method_signature=method_signature,
        input_params=json.dumps({'entry_points_count': len(entry_points)}),
        model_name=LLM_MODEL,
        analysis_duration=duration,
        session_id=user_session_id
    )
    
    return {
        'result': result,
        'from_cache': False,
        'cache_info': None
    }


# ==================== UI渲染函数 ====================
def render_sidebar(baseline_param: str = None):
    """渲染侧边栏
    
    Args:
        baseline_param: 从 URL 参数传入的基线名称（可选）
    """
    st.sidebar.title("📊 JCCI 分析平台")
      
    st.sidebar.markdown("---")
    st.sidebar.subheader("📁 选择分析结果")
    
    # 列出所有可用的基线目录
    baseline_dirs = [d for d in os.listdir(RESULT_DIR) 
                     if os.path.isdir(os.path.join(RESULT_DIR, d)) and not d.startswith('.')]
    
    if not baseline_dirs:
        st.sidebar.warning("未找到分析结果目录")
        return None
    
    # 如果有baseline参数，优先使用该基线
    if baseline_param and baseline_param in baseline_dirs:
        selected_baseline = baseline_param
        st.sidebar.info(f"🎯 已从URL加载基线: {selected_baseline}")
    else:
        # 否则让用户选择
        baseline_dirs_sorted = sorted(baseline_dirs, reverse=True)
        selected_baseline = st.sidebar.selectbox(
            "基线版本",
            options=baseline_dirs_sorted,
            format_func=lambda x: x.replace('_', ' ')
        )
    
    if not selected_baseline:
        return None
    
    # 获取基线目录路径
    baseline_dir = os.path.join(RESULT_DIR, selected_baseline)
    
    # 列出该基线下的所有版本子目录
    version_subdirs = [d for d in os.listdir(baseline_dir) 
                       if os.path.isdir(os.path.join(baseline_dir, d)) and not d.startswith('.')]
    
    if not version_subdirs:
        st.sidebar.warning(f"基线 {selected_baseline} 下没有版本数据")
        return None
    
    # 让用户选择版本
    version_subdirs_sorted = sorted(version_subdirs, reverse=True)
    selected_version = st.sidebar.selectbox(
        "目标版本",
        options=version_subdirs_sorted,
        format_func=lambda x: x.replace('_', ' ')
    )
    
    if not selected_version:
        return None
    
    # 设置当前会话的数据库路径（使用基线目录）
    get_session_db_path(selected_baseline)
    
    # 构建文件路径（在版本子目录中查找）
    version_dir = os.path.join(baseline_dir, selected_version)
    upwards_json = os.path.join(version_dir, "upwards_call_chains.json")
    downwards_json = os.path.join(version_dir, "downwards_call_chains.json")
    upwards_txt = os.path.join(version_dir, "upwards.txt")
    downwards_txt = os.path.join(version_dir, "downwards.txt")
    
    # 检查文件是否存在
    if not all(os.path.exists(f) for f in [upwards_json, downwards_json, upwards_txt, downwards_txt]):
        st.sidebar.error(f"版本目录 {selected_version} 中的文件不完整")
        return None
    
    # commit_range用于显示，格式为 baseline..version
    commit_range = f"{selected_baseline}..{selected_version}"
    
    return {
        'upwards_json': upwards_json,
        'downwards_json': downwards_json,
        'upwards_txt': upwards_txt,
        'downwards_txt': downwards_txt,
        'commit_range': commit_range,
        'baseline_dir': baseline_dir,
        'version_dir': version_dir,
        'selected_baseline': selected_baseline,
        'selected_version': selected_version
    }


def render_upwards_analysis(upwards_data: Dict, upwards_text: str):
    """渲染向上分析（影响面）"""
    st.header("⬆️ 向上调用链分析（影响面）")
    
    # 显示元数据
    metadata = upwards_data.get('metadata', {})
    col1, col2, col3 = st.columns(3)
    col1.metric("总变更方法", metadata.get('total_methods', 0))
    col2.metric("成功分析", metadata.get('successful_chains', 0))
    col3.metric("失败分析", metadata.get('failed_chains', 0))
    
    st.markdown("---")
    
    # 显示调用链列表
    impact_chains = upwards_data.get('impact_chains', [])
    
    if not impact_chains:
        st.info("没有找到向上的调用链")
        return
    
    st.subheader(f"🔗 调用链列表 ({len(impact_chains)}条)")
    
    for idx, chain_data in enumerate(impact_chains, 1):
        method_info = chain_data.get('method_info', {})
        class_name = method_info.get('class_name', '')
        method_name = method_info.get('method_name', '')
        change_type = method_info.get('change_type', 'UNKNOWN')
        
        # 确定颜色
        color_map = {
            'ADDED': 'green',
            'MODIFIED': 'orange',
            'DELETED': 'red',
            'UNCHANGED': 'gray'
        }
        color = color_map.get(change_type, 'blue')
        
        with st.expander(f"{idx}. [{change_type}] {class_name}.{method_name}()", expanded=False):
            col1, col2 = st.columns([3, 1])
            
            with col1:
                st.markdown(f"**变更类型**: <span style='color:{color}'>{change_type}</span>", unsafe_allow_html=True)
                st.markdown(f"**返回类型**: {method_info.get('return_type', 'N/A')}")
                
                # 显示入口点
                entry_points = chain_data.get('entry_points', [])
                if entry_points:
                    st.markdown("**入口点**:")
                    for entry in entry_points:
                        st.markdown(f"  - `{entry.get('package_class', '')}.{entry.get('method_signature', '')}` [{entry.get('root_type', '')}]")
            
            with col2:
                # 添加“强制全新分析”复选框
                force_fresh = st.checkbox("🔄 强制全新", key=f"force_fresh_up_{idx}")
                
                if st.button("🤖 AI分析此方法", key=f"up_method_{idx}"):
                    with st.spinner("正在调用LLM分析..."):
                        db_info = get_method_info_from_db(class_name, method_name)
                        analysis_result = analyze_single_method(method_info, db_info, 'upwards', force_fresh)
                        st.session_state[f'up_method_analysis_{idx}'] = analysis_result
                
                if st.button("🔗 AI分析完整链路", key=f"up_chain_{idx}"):
                    with st.spinner("正在调用LLM分析调用链..."):
                        analysis_result = analyze_call_chain(chain_data, 'upwards', force_fresh)
                        st.session_state[f'up_chain_analysis_{idx}'] = analysis_result
            
            # 显示分析结果
            if f'up_method_analysis_{idx}' in st.session_state:
                analysis_data = st.session_state[f'up_method_analysis_{idx}']
                
                # 显示缓存信息
                if analysis_data.get('from_cache'):
                    cache_info = analysis_data.get('cache_info', {})
                    st.info(f"♻️ 从缓存读取 | 创建时间: {cache_info.get('created_at', 'N/A')}")
                else:
                    st.success("✅ 全新分析完成")
                
                st.markdown("### 📊 方法分析报告")
                st.markdown(analysis_data['result'])
            
            if f'up_chain_analysis_{idx}' in st.session_state:
                analysis_data = st.session_state[f'up_chain_analysis_{idx}']
                
                # 显示缓存信息
                if analysis_data.get('from_cache'):
                    cache_info = analysis_data.get('cache_info', {})
                    st.info(f"♻️ 从缓存读取 | 创建时间: {cache_info.get('created_at', 'N/A')} | 模型: {cache_info.get('model_name', 'N/A')}")
                else:
                    st.success("✅ 全新分析完成")
                
                st.markdown("### 🔗 调用链分析报告")
                st.markdown(analysis_data['result'])
            
            # ✅ v4.0 新增：显示 SQL 增强信息（如果是 DAO 方法）
            dao_info = method_info.get('dao_info')
            if dao_info and dao_info.get('is_dao'):
                render_sql_enhanced_info(dao_info)


def render_sql_enhanced_info(dao_info: Dict):
    """
    渲染SQL增强信息（v4.0新增）
    
    Args:
        dao_info: DAO信息字典，包含sql_type, tables, performance等
    """
    if not dao_info or not dao_info.get('is_dao'):
        return
    
    st.markdown("---")
    st.markdown("### 🗄️ SQL 增强信息 (v4.0)")
    
    # 基本信息
    col1, col2, col3 = st.columns(3)
    
    sql_type = dao_info.get('sql_type', 'UNKNOWN')
    table_name = dao_info.get('table_name', 'N/A')
    entity_name = dao_info.get('entity_name', 'N/A')
    
    # SQL类型颜色映射
    sql_color_map = {
        'SELECT': 'blue',
        'INSERT': 'green',
        'UPDATE': 'orange',
        'DELETE': 'red'
    }
    sql_color = sql_color_map.get(sql_type, 'gray')
    
    with col1:
        st.markdown(f"**SQL类型**: <span style='color:{sql_color};font-weight:bold'>{sql_type}</span>", unsafe_allow_html=True)
    
    with col2:
        st.markdown(f"**表名**: `{table_name}`")
    
    with col3:
        st.markdown(f"**实体类**: `{entity_name}`")
    
    # 显示SQL语句（如果有）
    sql_statement = dao_info.get('sql_statement')
    if sql_statement:
        with st.expander("📝 查看完整SQL语句", expanded=False):
            st.code(sql_statement, language='sql')
    
    # ✅ 性能分析结果
    performance_score = dao_info.get('performance_score')
    if performance_score is not None:
        st.markdown("#### ⚡ 性能分析")
        
        col1, col2 = st.columns([1, 3])
        
        # 性能评分徽章
        score_level = dao_info.get('performance_level', 'UNKNOWN')
        level_color_map = {
            'EXCELLENT': 'green',
            'GOOD': 'blue',
            'FAIR': 'orange',
            'POOR': 'red'
        }
        level_color = level_color_map.get(score_level, 'gray')
        
        with col1:
            st.markdown(
                f"<div style='text-align:center;padding:10px;border-radius:5px;background-color:{level_color}20;border:2px solid {level_color}'>"
                f"<div style='font-size:24px;font-weight:bold;color:{level_color}'>{performance_score}</div>"
                f"<div style='font-size:12px;color:{level_color}'>{score_level}</div>"
                f"</div>",
                unsafe_allow_html=True
            )
        
        with col2:
            # 显示性能问题列表
            issues = dao_info.get('performance_issues', [])
            if issues:
                st.markdown(f"**发现 {len(issues)} 个性能问题:**")
                for issue in issues:
                    severity = issue.get('severity', 'LOW')
                    severity_icon = {'HIGH': '🔴', 'MEDIUM': '🟡', 'LOW': '🟢'}.get(severity, '⚪')
                    
                    with st.container():
                        st.markdown(
                            f"{severity_icon} **[{severity}]** {issue.get('rule')}\n\n"
                            f"- 💬 {issue.get('message')}\n\n"
                            f"- 💡 {issue.get('suggestion')}"
                        )
                        st.markdown("---")
            else:
                st.success("✅ 未检测到性能问题")
    
    # ✅ 字段血缘追踪
    field_lineage = dao_info.get('field_lineage')
    if field_lineage:
        st.markdown("#### 🔗 字段血缘追踪")
        
        # 统计信息
        stats = field_lineage.get('statistics', {})
        total_fields = stats.get('total_fields_tracked', 0)
        
        if total_fields > 0:
            st.info(f"📊 共追踪 {total_fields} 个字段")
            
            # 数据来源（写入的字段）
            sources = field_lineage.get('sources', [])
            if sources:
                with st.expander(f"📥 数据来源 ({len(sources)}个字段)", expanded=False):
                    for source in sources:
                        table = source.get('table', '')
                        column = source.get('column', '')
                        st.markdown(f"- `{table}.{column}`")
            
            # 数据消费者（读取的字段）
            consumers = field_lineage.get('consumers', [])
            if consumers:
                with st.expander(f"📤 数据消费者 ({len(consumers)}个字段)", expanded=False):
                    for consumer in consumers:
                        table = consumer.get('table', '')
                        column = consumer.get('column', '')
                        st.markdown(f"- `{table}.{column}`")
            
            # 影响分析
            impact_analysis = field_lineage.get('impact_analysis')
            if impact_analysis:
                risk_level = impact_analysis.get('risk_level', 'UNKNOWN')
                risk_color_map = {
                    'CRITICAL': 'red',
                    'HIGH': 'orange',
                    'MEDIUM': 'yellow',
                    'LOW': 'green'
                }
                risk_color = risk_color_map.get(risk_level, 'gray')
                
                st.markdown(f"**变更影响评估**: <span style='color:{risk_color};font-weight:bold'>{risk_level}</span>", unsafe_allow_html=True)
                
                recommendations = impact_analysis.get('recommendations', [])
                if recommendations:
                    st.markdown("**建议:**")
                    for rec in recommendations:
                        st.markdown(f"- {rec}")
        else:
            st.info("ℹ️ 该SQL操作不涉及具体字段追踪")


def render_downwards_analysis(downwards_data: Dict, downwards_text: str):
    """渲染向下分析（功能风险）"""
    st.header("⬇️ 向下调用链分析（功能风险）")
    
    # 显示元数据
    metadata = downwards_data.get('metadata', {})
    col1, col2, col3 = st.columns(3)
    col1.metric("总变更方法", metadata.get('total_methods', 0))
    col2.metric("成功分析", metadata.get('successful_chains', 0))
    col3.metric("失败分析", metadata.get('failed_chains', 0))
    
    st.markdown("---")
    
    # 显示调用链列表
    # 注意：向下分析使用的是 'call_chains' 键
    dependency_chains = downwards_data.get('dependency_chains') or downwards_data.get('call_chains', [])
    
    if not dependency_chains:
        st.info("没有找到向下的调用链")
        return
    
    st.subheader(f"🔗 调用链列表 ({len(dependency_chains)}条)")
    
    for idx, chain_data in enumerate(dependency_chains, 1):
        method_info = chain_data.get('method_info', {})
        class_name = method_info.get('class_name', '')
        method_name = method_info.get('method_name', '')
        change_type = method_info.get('change_type', 'UNKNOWN')
        
        # 确定颜色
        color_map = {
            'ADDED': 'green',
            'MODIFIED': 'orange',
            'DELETED': 'red',
            'UNCHANGED': 'gray'
        }
        color = color_map.get(change_type, 'blue')
        
        with st.expander(f"{idx}. [{change_type}] {class_name}.{method_name}()", expanded=False):
            col1, col2 = st.columns([3, 1])
            
            with col1:
                st.markdown(f"**变更类型**: <span style='color:{color}'>{change_type}</span>", unsafe_allow_html=True)
                st.markdown(f"**返回类型**: {method_info.get('return_type', 'N/A')}")
                
                # 显示依赖信息
                dependencies = chain_data.get('dependencies', [])
                if dependencies:
                    st.markdown(f"**依赖数量**: {len(dependencies)}")
            
            with col2:
                # 添加“强制全新分析”复选框
                force_fresh = st.checkbox("🔄 强制全新", key=f"force_fresh_down_{idx}")
                
                if st.button("🤖 AI分析此方法", key=f"down_method_{idx}"):
                    with st.spinner("正在调用LLM分析..."):
                        db_info = get_method_info_from_db(class_name, method_name)
                        analysis_result = analyze_single_method(method_info, db_info, 'downwards', force_fresh)
                        st.session_state[f'down_method_analysis_{idx}'] = analysis_result
                
                if st.button("🔗 AI分析完整链路", key=f"down_chain_{idx}"):
                    with st.spinner("正在调用LLM分析调用链..."):
                        analysis_result = analyze_call_chain(chain_data, 'downwards', force_fresh)
                        st.session_state[f'down_chain_analysis_{idx}'] = analysis_result
            
            # 显示分析结果
            if f'down_method_analysis_{idx}' in st.session_state:
                analysis_data = st.session_state[f'down_method_analysis_{idx}']
                
                # 显示缓存信息
                if analysis_data.get('from_cache'):
                    cache_info = analysis_data.get('cache_info', {})
                    st.info(f"♻️ 从缓存读取 | 创建时间: {cache_info.get('created_at', 'N/A')} | 模型: {cache_info.get('model_name', 'N/A')}")
                else:
                    st.success("✅ 全新分析完成")
                
                st.markdown("### 📊 方法分析报告")
                st.markdown(analysis_data['result'])
            
            if f'down_chain_analysis_{idx}' in st.session_state:
                analysis_data = st.session_state[f'down_chain_analysis_{idx}']
                
                # 显示缓存信息
                if analysis_data.get('from_cache'):
                    cache_info = analysis_data.get('cache_info', {})
                    st.info(f"♻️ 从缓存读取 | 创建时间: {cache_info.get('created_at', 'N/A')} | 模型: {cache_info.get('model_name', 'N/A')}")
                else:
                    st.success("✅ 全新分析完成")
                
                st.markdown("### 🔗 调用链分析报告")
                st.markdown(analysis_data['result'])
            
            # ✅ v4.0 新增：显示 SQL 增强信息（如果是 DAO 方法）
            dao_info = method_info.get('dao_info')
            if dao_info and dao_info.get('is_dao'):
                render_sql_enhanced_info(dao_info)


def render_sql_analysis_view(downwards_data: Dict):
    """
    渲染 SQL 分析视图（v4.0 新增）
    
    展示所有 DAO 方法的 SQL 增强信息汇总
    """
    st.header("🗄️ SQL 分析视图 (v4.0)")
    
    # 提取所有 DAO 方法
    dependency_chains = downwards_data.get('dependency_chains') or downwards_data.get('call_chains', [])
    
    dao_methods = []
    for chain_data in dependency_chains:
        method_info = chain_data.get('method_info', {})
        dao_info = method_info.get('dao_info')
        
        if dao_info and dao_info.get('is_dao'):
            dao_methods.append({
                'method_info': method_info,
                'dao_info': dao_info,
                'chain_data': chain_data
            })
    
    if not dao_methods:
        st.info("ℹ️ 当前分析结果中未检测到 MyBatis Mapper/DAO 方法")
        st.markdown("""
        ### 💡 如何启用 SQL 分析？
        
        1. **确保项目包含 MyBatis Mapper XML 文件**
           - MBG生成的Mapper: `**/mall-mbg/**/*Mapper.xml`
           - 自定义DAO: `**/dao/**/*.xml`
        
        2. **系统会自动：**
           - 扫描并解析所有 Mapper XML 文件
           - 构建 Mapper 方法索引
           - 在调用链分析时自动关联 SQL 信息
           - 生成性能分析和字段血缘追踪报告
        """)
        return
    
    # 显示统计信息
    st.success(f"✅ 检测到 {len(dao_methods)} 个 DAO 方法")
    
    col1, col2, col3, col4 = st.columns(4)
    
    # 按 SQL 类型统计
    sql_type_count = {}
    performance_level_count = {}
    risk_level_count = {}
    total_tables = set()
    
    for dao_method in dao_methods:
        dao_info = dao_method['dao_info']
        sql_type = dao_info.get('sql_type', 'UNKNOWN')
        sql_type_count[sql_type] = sql_type_count.get(sql_type, 0) + 1
        
        # 性能等级统计
        perf_level = dao_info.get('performance_level', 'UNKNOWN')
        performance_level_count[perf_level] = performance_level_count.get(perf_level, 0) + 1
        
        # 风险等级统计（从 method_info 的 change_type 推断）
        change_type = dao_method['method_info'].get('change_type', 'UNKNOWN')
        risk_level_count[change_type] = risk_level_count.get(change_type, 0) + 1
        
        # 表名统计
        table_name = dao_info.get('table_name')
        if table_name:
            total_tables.add(table_name)
    
    with col1:
        st.metric("SQL 类型分布", f"{len(sql_type_count)} 种")
        for sql_type, count in sorted(sql_type_count.items()):
            st.text(f"  • {sql_type}: {count}")
    
    with col2:
        st.metric("性能等级分布", f"{len(performance_level_count)} 级")
        for level, count in sorted(performance_level_count.items()):
            st.text(f"  • {level}: {count}")
    
    with col3:
        st.metric("涉及表数量", len(total_tables))
        if len(total_tables) <= 10:
            for table in sorted(total_tables):
                st.text(f"  • {table}")
    
    with col4:
        st.metric("变更类型分布", f"{len(risk_level_count)} 种")
        for change_type, count in sorted(risk_level_count.items()):
            st.text(f"  • {change_type}: {count}")
    
    st.markdown("---")
    
    # 过滤器
    st.subheader("🔍 过滤器")
    
    filter_col1, filter_col2, filter_col3 = st.columns(3)
    
    with filter_col1:
        selected_sql_types = st.multiselect(
            "SQL 类型",
            options=sorted(sql_type_count.keys()),
            default=sorted(sql_type_count.keys())
        )
    
    with filter_col2:
        selected_perf_levels = st.multiselect(
            "性能等级",
            options=['EXCELLENT', 'GOOD', 'FAIR', 'POOR'],
            default=['EXCELLENT', 'GOOD', 'FAIR', 'POOR']
        )
    
    with filter_col3:
        min_score = st.slider("最低性能评分", 0, 100, 0)
    
    # 应用过滤
    filtered_methods = []
    for dao_method in dao_methods:
        dao_info = dao_method['dao_info']
        sql_type = dao_info.get('sql_type', 'UNKNOWN')
        perf_level = dao_info.get('performance_level', 'UNKNOWN')
        perf_score = dao_info.get('performance_score', 0)
        
        if (sql_type in selected_sql_types and 
            perf_level in selected_perf_levels and 
            perf_score >= min_score):
            filtered_methods.append(dao_method)
    
    st.info(f"显示 {len(filtered_methods)} / {len(dao_methods)} 个方法")
    
    # 显示过滤后的 DAO 方法列表
    for idx, dao_method in enumerate(filtered_methods, 1):
        method_info = dao_method['method_info']
        dao_info = dao_method['dao_info']
        
        class_name = method_info.get('class_name', '')
        method_name = method_info.get('method_name', '')
        change_type = method_info.get('change_type', 'UNKNOWN')
        
        sql_type = dao_info.get('sql_type', 'UNKNOWN')
        table_name = dao_info.get('table_name', 'N/A')
        perf_score = dao_info.get('performance_score', 0)
        perf_level = dao_info.get('performance_level', 'UNKNOWN')
        
        # 颜色映射
        sql_color_map = {
            'SELECT': 'blue',
            'INSERT': 'green',
            'UPDATE': 'orange',
            'DELETE': 'red'
        }
        sql_color = sql_color_map.get(sql_type, 'gray')
        
        change_color_map = {
            'ADDED': 'green',
            'MODIFIED': 'orange',
            'DELETED': 'red',
            'UNCHANGED': 'gray'
        }
        change_color = change_color_map.get(change_type, 'blue')
        
        perf_color_map = {
            'EXCELLENT': 'green',
            'GOOD': 'blue',
            'FAIR': 'orange',
            'POOR': 'red'
        }
        perf_color = perf_color_map.get(perf_level, 'gray')
        
        with st.expander(
            f"{idx}. [{change_type}] {class_name}.{method_name}() - "
            f"<span style='color:{sql_color}'>{sql_type}</span> on `{table_name}` - "
            f"<span style='color:{perf_color}'>{perf_score}分 ({perf_level})</span>",
            expanded=False
        ):
            # 渲染完整的 SQL 增强信息
            render_sql_enhanced_info(dao_info)


def render_text_view(upwards_text: str, downwards_text: str):
    """渲染文本视图"""
    st.header("📄 文本视图")
    
    # 添加自定义CSS，强制使用等宽字体
    st.markdown("""
    <style>
    .text-view-container {
        font-family: 'Courier New', Courier, monospace !important;
        font-size: 13px !important;
        line-height: 1.4 !important;
        white-space: pre !important;
        overflow-x: auto !important;
    }
    .text-view-container textarea {
        font-family: 'Courier New', Courier, monospace !important;
        font-size: 13px !important;
    }
    </style>
    """, unsafe_allow_html=True)
    
    tab1, tab2 = st.tabs(["向上调用链", "向下调用链"])
    
    with tab1:
        if upwards_text:
            # 使用st.code确保等宽字体显示
            st.text_area("向下调用链分析结果", upwards_text, height=600)
        else:
            st.info("没有向上调用链的文本数据")
    
    with tab2:
        if downwards_text:
            # 使用st.code确保等宽字体显示
            st.text_area("向下调用链分析结果", downwards_text, height=600)
        else:
            st.info("没有向下调用链的文本数据")


# ==================== 主应用 ====================
def main():
    # 检查是否有导航请求
    check_navigation()
    
    # 获取用户会话ID
    user_session_id = get_user_session_id()
    
    st.title("🔗 JCCI 调用链分析与LLM智能分析平台")
    
    # 从 URL 参数获取 baseline（如果存在）
    query_params = st.query_params
    baseline_param = query_params.get("baseline", None)
    
    # 创建三个 Tab 页签
    tab_submit, tab_tasks, tab_results = st.tabs(["📝 提交任务", "📋 任务列表", "📊 分析结果"])
    
    with tab_submit:
        render_task_submission_page()
    
    with tab_tasks:
        render_task_list_page()
    
    with tab_results:
        # 如果没有提供baseline参数，显示访问规则提示
        if not baseline_param:
            st.warning("⚠️ **请选择基线**")
            st.markdown("""
            ### 📋 如何查看分析结果
            
            请在左侧边栏选择一个基线，或者通过 URL 参数指定：
            
            ```
            http://localhost:8501/?baseline={基线标识符}
            ```
            
            ### 📝 示例
            
            - 使用Git Tag: `http://localhost:8501/?baseline=mall_20260508_01`
            - 使用Commit Hash: `http://localhost:8501/?baseline=mall_dd6569c3`
            """)
            return
        
        # 显示当前使用的数据库信息
        file_paths = render_sidebar(baseline_param)
        
        if not file_paths:
            st.warning("请先在侧边栏选择一个分析结果")
            return
        
        current_db_path = get_session_db_path(file_paths['commit_range'])
        st.sidebar.success("✅ 数据库隔离已启用")
        st.sidebar.info(f"📁 基线数据库: {os.path.basename(current_db_path)}")
        
        # 加载数据
        with st.spinner("正在加载数据..."):
            upwards_data = load_json_file(file_paths['upwards_json'])
            downwards_data = load_json_file(file_paths['downwards_json'])
            upwards_text = load_text_file(file_paths['upwards_txt'])
            downwards_text = load_text_file(file_paths['downwards_txt'])
        
        # 主标签页
        tab1, tab2, tab3, tab4 = st.tabs(["⬆️ 向上分析", "⬇️ 向下分析", "🗄️ SQL分析", "📄 文本视图"])
        
        with tab1:
            if upwards_data:
                render_upwards_analysis(upwards_data, upwards_text)
            else:
                st.warning("未找到向上分析的JSON数据")
        
        with tab2:
            if downwards_data:
                render_downwards_analysis(downwards_data, downwards_text)
            else:
                st.warning("未找到向下分析的JSON数据")
        
        with tab3:
            if downwards_data:
                render_sql_analysis_view(downwards_data)
            else:
                st.warning("未找到向下分析的JSON数据")
        
        with tab4:
            render_text_view(upwards_text, downwards_text)
    
    # 页脚
    st.markdown("---")
    st.markdown("""
    <div style='text-align: center; color: gray;'>
        <p>JCCI Call Chain Analysis Platform | Powered by Streamlit & LLM</p>
    </div>
    """, unsafe_allow_html=True)


if __name__ == "__main__":
    main()
