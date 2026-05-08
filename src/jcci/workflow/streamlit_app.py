"""
JCCI 调用链分析与LLM智能分析平台

基于Streamlit构建的Web界面，用于：
1. 展示双向调用链分析结果
2. 支持点击方法/调用链进行智能分析
3. 集成LLM提供测试建议和变更分析

注意：使用前需要创建 config.py 文件（参考 config.py.template）
"""

import streamlit as st
import json
import os
import sqlite3
from typing import Dict, List, Optional
import requests
import time
import uuid

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


@st.cache_data(ttl=3600)
def load_text_file(filepath: str) -> str:
    """加载文本文件（带缓存）"""
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
        baseline_param: 从URL参数传入的基线名称（可选）
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


def render_text_view(upwards_text: str, downwards_text: str):
    """渲染文本视图"""
    st.header("📄 文本视图")
    
    tab1, tab2 = st.tabs(["向上调用链", "向下调用链"])
    
    with tab1:
        if upwards_text:
            st.text_area("向上调用链分析结果", upwards_text, height=600)
        else:
            st.info("没有向上调用链的文本数据")
    
    with tab2:
        if downwards_text:
            st.text_area("向下调用链分析结果", downwards_text, height=600)
        else:
            st.info("没有向下调用链的文本数据")


# ==================== 主应用 ====================
def main():
    # 获取用户会话ID
    user_session_id = get_user_session_id()
    
    st.title("🔗 JCCI 调用链分析与LLM智能分析平台")
    
    # 从URL参数获取baseline（如果存在）
    query_params = st.query_params
    baseline_param = query_params.get("baseline", None)
    
    # 如果没有提供baseline参数，显示访问规则提示
    if not baseline_param:
        st.warning("⚠️ **访问方式不正确**")
        st.markdown("""
        ### 📋 正确的访问方式
        
        本系统需要通过 **URL参数** 指定基线才能访问。请使用以下格式：
        
        ```
        http://0.0.0.0:8501/?baseline={基线标识符}
        ```
        
        ### 📝 示例
        
        - 使用Git Tag: `http://0.0.0.0:8501/?baseline=baseline_20260508_01`
        - 使用Commit Hash: `http://0.0.0.0:8501/?baseline=mall_dd6569c3`
        
        ### 🔍 如何获取基线标识符？
        
        1. **查看analyze_result目录**: 在 `jcci/src/jcci/analyze_result/` 目录下查看所有可用的基线文件夹
        2. **基线命名规则**: 
           - Commit Hash (40位): 截取前8位，如 `dd6569c3`
           - Git Tag (长度>11): 截取后11位，如 `20260508_01`
           - 短标识符 (长度≤11): 保持不变，如 `d9501e9`
        
        ### 💡 提示
        
        - 基线标识符对应 `analyze_result` 目录下的文件夹名称
        - 每个基线下可以有多个版本子目录用于对比分析
        - 请确保指定的基线数据库文件已生成
        """)
        
        # 列出可用的基线（如果存在）
        if os.path.exists(RESULT_DIR):
            baselines = [d for d in os.listdir(RESULT_DIR) 
                        if os.path.isdir(os.path.join(RESULT_DIR, d)) and not d.startswith('.')]
            
            if baselines:
                st.success(f"✅ 发现 {len(baselines)} 个可用基线:")
                cols = st.columns(2)
                for idx, baseline in enumerate(sorted(baselines)):
                    col_idx = idx % 2
                    with cols[col_idx]:
                        share_url = f"http://0.0.0.0:{STREAMLIT_PORT}/?baseline={baseline}"
                        st.markdown(f"- [{baseline}]({share_url})")
        
        return
    
    # 显示用户信息和分享链接
    col1, col2 = st.columns([3, 1])
    with col1:
        st.markdown("欢迎使用 JCCI 调用链分析与LLM智能分析平台")
    with col2:
        st.metric("会话ID", user_session_id)
    
    # 生成分享链接
    import socket
    try:
        hostname = socket.gethostname()
        local_ip = socket.gethostbyname(hostname)
        share_url = f"http://{local_ip}:{STREAMLIT_PORT}/?session={user_session_id}"
        st.info(f"分享链接: `{share_url}`")
    except Exception:
        pass
    
    # 侧边栏
    file_paths = render_sidebar(baseline_param)
    
    if not file_paths:
        st.warning("请先在侧边栏选择一个分析结果")
        return
    
    # 显示当前使用的数据库信息
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
    tab1, tab2, tab3 = st.tabs(["⬆️ 向上分析", "⬇️ 向下分析", "📄 文本视图"])
    
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
