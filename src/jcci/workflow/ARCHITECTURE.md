# JCCI Streamlit平台 - 技术架构文档

## 🏗️ 系统架构

```
┌─────────────────────────────────────────────────────────────┐
│                     用户浏览器                               │
│                  (http://localhost:8501)                     │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────┐
│                   Streamlit Server                           │
│              (streamlit_app.py)                              │
├─────────────────────────────────────────────────────────────┤
│  • 会话管理 (Session ID)                                     │
│  • UI渲染组件                                                │
│  • 事件处理                                                  │
└────┬────────────────────────────────────────────┬───────────┘
     │                                            │
     ▼                                            ▼
┌──────────────────┐                  ┌──────────────────────┐
│  数据加载层       │                  │  LLM分析层           │
│                  │                  │                      │
│ • JSON文件读取   │                  │ • API调用封装        │
│ • SQLite查询     │                  │ • Prompt构建         │
│ • 缓存管理       │                  │ • 结果解析           │
└────┬─────────────┘                  └──────────┬───────────┘
     │                                           │
     ▼                                           ▼
┌──────────────────┐                  ┌──────────────────────┐
│  文件系统         │                  │  外部LLM API         │
│                  │                  │                      │
│ • *.json         │                  │ • Kimi API           │
│ • *.txt          │                  │ • OpenAI兼容接口     │
└──────────────────┘                  └──────────────────────┘
     │
     ▼
┌──────────────────┐
│  SQLite数据库     │
│                  │
│ • methods表      │
│ • class表        │
└──────────────────┘
```

---

## 📁 文件结构

```
src/jcci/workflow/
├── workflow1.py              # 主工作流（步骤5启动Web服务）
├── streamlit_app.py          # Streamlit Web应用（604行）
├── config.py                 # 配置文件（不提交到Git）
├── config.py.template        # 配置模板
├── requirements_streamlit.txt # Python依赖
├── start.bat                 # Windows启动脚本
├── start.sh                  # Linux/Mac启动脚本
├── .gitignore                # Git忽略规则
├── README_STREAMLIT.md       # 详细使用文档
├── QUICKSTART.md             # 快速开始指南
├── FEATURES_DEMO.md          # 功能演示说明
└── ARCHITECTURE.md           # 本文件
```

---

## 🔑 核心模块

### 1. 配置管理模块

**文件**: `config.py`

```python
# 敏感配置（不提交到版本控制）
LLM_API_URL = "https://openai.good.hidns.vip/v1"
LLM_API_KEY = "sk-..."
LLM_MODEL = "moonshotai/kimi-k2.6"

# 路径配置
DB_PATH = r"path/to/database.db"
RESULT_DIR = r"path/to/analyze_result"

# 服务配置
STREAMLIT_PORT = 8501
STREAMLIT_HOST = "0.0.0.0"
```

**安全机制**:
- `.gitignore` 排除 `config.py`
- 提供 `config.py.template` 作为模板
- 启动时检查配置文件是否存在

---

### 2. 会话管理模块

**函数**: `get_user_session_id()`

```python
def get_user_session_id():
    """获取或创建用户会话ID"""
    if 'user_session_id' not in st.session_state:
        session_id = str(uuid.uuid4())[:8]
        st.session_state.user_session_id = session_id
    return st.session_state.user_session_id
```

**特性**:
- 基于UUID生成唯一ID
- 存储在Streamlit session_state中
- 每个浏览器标签页独立会话
- 刷新页面后保持会话

---

### 3. 数据加载模块

#### 3.1 JSON文件加载

```python
@st.cache_data(ttl=3600)
def load_json_file(filepath: str) -> Dict:
    """加载JSON文件（带缓存）"""
    if not os.path.exists(filepath):
        return {}
    with open(filepath, 'r', encoding='utf-8') as f:
        return json.load(f)
```

**优化**:
- 使用 `@st.cache_data` 装饰器
- TTL=3600秒（1小时）
- 减少重复文件I/O

#### 3.2 数据库查询

```python
@st.cache_data(ttl=3600)
def query_database(query: str, params: tuple = ()) -> List[Dict]:
    """查询数据库（带缓存）"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    try:
        cursor.execute(query, params)
        rows = cursor.fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()
```

**查询示例**:
```python
# 获取方法详细信息
def get_method_info_from_db(class_name: str, method_name: str) -> Dict:
    # 1. 查询class表获取class_id
    # 2. 查询methods表获取方法详情
    # 3. 合并返回
```

---

### 4. LLM分析模块

#### 4.1 API调用封装

```python
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
    
    response = requests.post(
        f"{LLM_API_URL}/chat/completions",
        json=payload,
        headers=headers,
        timeout=60
    )
    
    return response.json()['choices'][0]['message']['content']
```

#### 4.2 方法分析Prompt

```python
def analyze_single_method(method_info: Dict, db_info: Dict) -> str:
    """分析单个方法的变更和测试建议"""
    
    system_prompt = """你是一位资深的Java代码审查专家和测试工程师..."""
    
    prompt = f"""请分析以下Java方法的变更情况，并给出测试建议：

【方法基本信息】
- 类名: {class_name}
- 方法名: {method_name}
- 参数: {parameters}
- 返回类型: {return_type}
- 变更类型: {change_type}

【数据库补充信息】
- 文件路径: {filepath}
- 包名: {package_name}
- ...

【分析要求】
请从以下几个方面进行分析：
1. 变更内容分析
2. 代码质量评估
3. 测试建议
4. 风险评估
"""
    
    return call_llm_api(prompt, system_prompt)
```

#### 4.3 调用链分析Prompt

```python
def analyze_call_chain(chain_data: Dict, direction: str) -> str:
    """分析整个调用链的影响和风险"""
    
    prompt = f"""请分析以下{'向上' if direction == 'upwards' else '向下'}调用链路：

【变更方法信息】
...

【入口点信息】
...

【分析要求】
1. 调用链路概览
2. 影响面分析
3. 风险评估
4. 测试策略
5. 优化建议
"""
    
    return call_llm_api(prompt, system_prompt)
```

---

### 5. UI渲染模块

#### 5.1 侧边栏

```python
def render_sidebar():
    """渲染侧边栏"""
    st.sidebar.title("📊 JCCI 分析平台")
    
    # 列出所有可用的分析结果
    files = [f for f in os.listdir(RESULT_DIR) if f.endswith('.json')]
    commit_ranges = sorted(set([...]))
    
    selected_range = st.sidebar.selectbox("Commit范围", options=commit_ranges)
    
    return file_paths
```

#### 5.2 向上分析视图

```python
def render_upwards_analysis(upwards_data: Dict, upwards_text: str):
    """渲染向上分析（影响面）"""
    st.header("⬆️ 向上调用链分析（影响面）")
    
    # 显示元数据统计
    col1, col2, col3 = st.columns(3)
    col1.metric("总变更方法", metadata.get('total_methods', 0))
    col2.metric("成功分析", metadata.get('successful_chains', 0))
    col3.metric("失败分析", metadata.get('failed_chains', 0))
    
    # 显示调用链列表
    for idx, chain_data in enumerate(impact_chains, 1):
        with st.expander(f"{idx}. [{change_type}] {class_name}.{method_name}()"):
            # 显示详细信息
            # AI分析按钮
            # 分析结果展示
```

#### 5.3 分享链接生成

```python
import socket

hostname = socket.gethostname()
local_ip = socket.gethostbyname(hostname)
share_url = f"http://{local_ip}:{STREAMLIT_PORT}/?session={user_session_id}"

st.info(f"🔗 分享链接: `{share_url}`\n\n其他用户可以通过此链接访问你的分析结果")
```

---

## 🔄 数据流

### 用户点击"AI分析此方法"的流程

```
1. 用户点击按钮
   ↓
2. Streamlit触发回调
   ↓
3. 显示loading状态
   ↓
4. 调用 get_method_info_from_db()
   ├─ 查询 class 表
   └─ 查询 methods 表
   ↓
5. 构建 Prompt
   ├─ 方法基本信息
   ├─ 数据库补充信息
   └─ 分析要求
   ↓
6. 调用 call_llm_api()
   ├─ 构建请求
   ├─ 发送HTTP POST
   └─ 接收响应
   ↓
7. 存储到 session_state
   ↓
8. 渲染分析报告
   ↓
9. 用户查看结果
```

---

## 💾 缓存策略

### 三级缓存体系

1. **Streamlit缓存** (`@st.cache_data`)
   - JSON文件加载：TTL=3600s
   - 文本文件加载：TTL=3600s
   - 数据库查询：TTL=3600s
   
2. **会话状态** (`st.session_state`)
   - AI分析结果：会话级别
   - 用户会话ID：会话级别
   
3. **浏览器本地** (Streamlit自动管理)
   - 组件状态
   - 表单数据

**优势**:
- 减少重复API调用
- 提升用户体验
- 降低LLM成本

---

## 🔐 安全考虑

### 1. API Key保护

- ✅ `config.py` 加入 `.gitignore`
- ✅ 提供模板文件 `config.py.template`
- ⚠️ 不要硬编码在代码中
- ⚠️ 不要提交到版本控制

### 2. 会话隔离

- ✅ 每个用户独立会话ID
- ✅ AI分析结果按会话存储
- ✅ 互不干扰

### 3. 网络访问控制

- 本地模式：`STREAMLIT_HOST = "127.0.0.1"`
- 局域网模式：`STREAMLIT_HOST = "0.0.0.0"`
- 配合防火墙规则使用

---

## 🚀 部署方案

### 方案1: 本地开发

```bash
cd src/jcci/workflow
streamlit run streamlit_app.py
```

### 方案2: Docker部署

```dockerfile
FROM python:3.13-slim

WORKDIR /app

COPY requirements_streamlit.txt .
RUN pip install -r requirements_streamlit.txt

COPY . .

EXPOSE 8501

CMD ["streamlit", "run", "streamlit_app.py", \
     "--server.port", "8501", \
     "--server.address", "0.0.0.0"]
```

```bash
docker build -t jcci-streamlit .
docker run -p 8501:8501 jcci-streamlit
```

### 方案3: 云服务器

```bash
# 1. 上传代码到服务器
scp -r src/jcci/workflow user@server:/opt/jcci/

# 2. SSH登录服务器
ssh user@server

# 3. 安装依赖
cd /opt/jcci
pip install -r requirements_streamlit.txt

# 4. 配置config.py
cp config.py.template config.py
vim config.py

# 5. 后台运行
nohup streamlit run streamlit_app.py \
  --server.port 8501 \
  --server.address 0.0.0.0 > streamlit.log 2>&1 &

# 6. 配置防火墙
sudo ufw allow 8501/tcp
```

### 方案4: 内网穿透（ngrok）

```bash
# 启动Streamlit
streamlit run streamlit_app.py --server.port 8501

# 另一个终端启动ngrok
ngrok http 8501
```

会生成公网URL：`https://xxx.ngrok.io`

---

## 📊 性能优化

### 已实现的优化

1. **数据缓存**
   - JSON文件缓存1小时
   - 数据库查询缓存1小时
   
2. **懒加载**
   - 只在需要时加载数据
   - 按需调用LLM API

3. **异步UI**
   - Streamlit自动处理并发
   - 非阻塞式分析

### 未来优化方向

1. **数据库索引**
   ```sql
   CREATE INDEX idx_methods_name ON methods(method_name);
   CREATE INDEX idx_class_name ON class(class_name);
   ```

2. **结果预计算**
   - 提前生成常用分析报告
   - 减少实时LLM调用

3. **CDN加速**
   - 静态资源CDN
   - 减少加载时间

---

## 🧪 测试策略

### 单元测试

```python
# test_data_loading.py
def test_load_json_file():
    result = load_json_file("test.json")
    assert isinstance(result, dict)

def test_query_database():
    result = query_database("SELECT * FROM methods LIMIT 1")
    assert len(result) >= 0
```

### 集成测试

```python
# test_llm_api.py
def test_call_llm_api():
    result = call_llm_api("Say hello", "")
    assert len(result) > 0
```

### 端到端测试

```bash
# 手动测试流程
1. 启动服务
2. 选择Commit范围
3. 点击AI分析按钮
4. 验证结果展示
```

---

## 📝 维护指南

### 日常维护

1. **监控日志**
   ```bash
   tail -f streamlit.log
   ```

2. **清理缓存**
   - Streamlit自动管理
   - 重启服务可清空所有缓存

3. **更新依赖**
   ```bash
   pip install --upgrade streamlit requests
   ```

### 故障排查

1. **服务无法启动**
   - 检查端口是否被占用
   - 检查config.py是否存在
   - 查看错误日志

2. **AI分析超时**
   - 检查网络连接
   - 验证API Key有效性
   - 调整timeout参数

3. **数据库查询失败**
   - 检查DB_PATH是否正确
   - 验证数据库文件完整性
   - 查看SQL语法

---

## 🎯 扩展开发

### 添加新的分析维度

1. 在 `streamlit_app.py` 中添加新的分析函数
2. 构建对应的Prompt
3. 在UI中添加按钮
4. 渲染分析结果

### 支持更多LLM模型

修改 `config.py`:
```python
LLM_MODEL = "gpt-4"  # 或其他模型
```

### 自定义可视化组件

参考Streamlit组件库：
- `st.plotly_chart` - 交互式图表
- `st.graphviz_chart` - 流程图
- `st.aggrid` - 高级表格

---

## 📚 参考资料

- Streamlit官方文档: https://docs.streamlit.io
- Kimi API文档: https://platform.moonshot.cn
- SQLite文档: https://www.sqlite.org/docs.html
- Python requests: https://docs.python-requests.org

---

**版本**: v1.0.0  
**最后更新**: 2026-05-06  
**作者**: JCCI Team
