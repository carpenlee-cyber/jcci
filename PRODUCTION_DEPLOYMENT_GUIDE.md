# 生产部署架构升级实施报告

## 🎯 需求概述

用户计划将 JCCI 系统发布到生产环境，需要解决以下问题：

### 问题1：Streamlit 服务常驻后台
- Streamlit Web 服务必须作为常驻后台服务运行
- 无论是否有 workflow1 分析任务在执行，服务都应保持可用
- workflow1 即使设置 `enable_streamlit=False`，也需要返回可访问的 Web 链接

### 问题2：通过 Web 界面触发分析
- Streamlit 需要提供触发 workflow1 的入口
- 用户可通过网页输入参数（git_url、username、tag_old、tag_new、max_depth）
- 强制 `enable_streamlit=False`（不可更改）
- 分析完成后展示返回的 Web 链接
- 用户通过链接访问分析结果

---

## 🏗️ 架构设计

### 整体架构

```
┌─────────────────────────────────────────────────────────────┐
│                   生产环境架构                               │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌──────────────────────────────────────────────────────┐  │
│  │         Streamlit Web Service (常驻)                  │  │
│  │  - 任务提交页面 (?page=submit)                        │  │
│  │  - 任务列表页面 (?page=tasks)                         │  │
│  │  - 结果查看页面 (?baseline=xxx)                       │  │
│  └──────────────────────────────────────────────────────┘  │
│                          │                                  │
│                          ▼                                  │
│  ┌──────────────────────────────────────────────────────┐  │
│  │         AsyncTaskManager (任务管理器)                 │  │
│  │  - 接收任务请求                                       │  │
│  │  - 后台线程执行 workflow1                             │  │
│  │  - 跟踪任务状态和进度                                 │  │
│  │  - 存储结果路径                                       │  │
│  └──────────────────────────────────────────────────────┘  │
│                          │                                  │
│                          ▼                                  │
│  ┌──────────────────────────────────────────────────────┐  │
│  │         Workflow1 (分析引擎)                          │  │
│  │  - Git 代码拉取                                       │  │
│  │  - 增量分析                                           │  │
│  │  - 双向调用链构建                                     │  │
│  │  - 结果保存到文件系统                                 │  │
│  └──────────────────────────────────────────────────────┘  │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### 关键组件

#### 1. 任务管理器 (task_manager.py)

**职责**:
- 管理异步任务的提交和执行
- 跟踪任务状态（pending/running/completed/failed）
- 存储任务元数据和结果 URL
- 提供任务查询接口

**核心类**:
```python
class AsyncTaskManager:
    def submit_task(git_url, username, tag_old, tag_new, max_depth) -> task_id
    def get_task_status(task_id) -> dict
    def list_tasks(limit=20) -> List[dict]
```

**数据库表**:
```sql
CREATE TABLE analysis_tasks (
    task_id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    git_url TEXT NOT NULL,
    username TEXT,
    tag_old TEXT,
    tag_new TEXT,
    max_depth INTEGER DEFAULT 5,
    progress REAL DEFAULT 0.0,
    result_url TEXT,
    error_message TEXT,
    created_at TIMESTAMP,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    output_dir TEXT
)
```

#### 2. Streamlit 前端 (streamlit_app.py)

**新增页面**:

##### 任务提交页面 (`?page=submit`)
- 表单输入：git_url, username, tag_old, tag_new, max_depth
- 提交后返回 task_id
- 引导用户查看任务状态

##### 任务列表页面 (`?page=tasks`)
- 显示所有任务及其状态
- 实时进度条
- 完成的任务显示访问链接
- 失败的任务显示错误信息

##### 结果查看页面 (`?baseline=xxx`)
- 原有功能保持不变
- 显示双向调用链分析结果
- LLM 智能分析

#### 3. 启动脚本 (start_streamlit_service.py)

**功能**:
- 简化 Streamlit 服务启动
- 支持自定义 host 和 port
- 提供友好的启动提示

**用法**:
```bash
python start_streamlit_service.py --host 0.0.0.0 --port 8501
```

---

## 📝 实施细节

### 1. 创建任务管理器模块

**文件**: `src/jcci/workflow/task_manager.py`

**核心功能**:

#### 提交任务
```python
def submit_task(self, git_url, username, tag_old, tag_new, max_depth=5):
    # 1. 生成唯一 task_id
    task_id = str(uuid.uuid4())[:12]
    
    # 2. 保存任务信息到数据库
    conn = sqlite3.connect(self.db_path)
    cursor.execute('''
        INSERT INTO analysis_tasks 
        (task_id, status, git_url, username, tag_old, tag_new, max_depth)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (task_id, 'pending', ...))
    
    # 3. 启动后台线程执行
    thread = threading.Thread(
        target=self._execute_task,
        args=(task_id, git_url, username, tag_old, tag_new, max_depth),
        daemon=True
    )
    thread.start()
    
    return task_id
```

#### 执行任务
```python
def _execute_task(self, task_id, git_url, username, tag_old, tag_new, max_depth):
    try:
        # 更新状态为 running
        self._update_task_status(task_id, 'running', progress=10.0)
        
        # 构造输出目录
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        project_name = git_url.split('/')[-1].replace('.git', '')
        output_dir = os.path.join(..., f"{project_name}_{timestamp}")
        
        # 执行 workflow1（强制 enable_streamlit=False）
        result = workflow1(
            git_url=git_url,
            username=username,
            commit_or_branch_old=tag_old,
            commit_or_branch_new=tag_new,
            max_depth=max_depth,
            enable_streamlit=False,  # 强制禁用
            auto_open_browser=False,
            output_dir=output_dir
        )
        
        # 构造 Web 访问链接
        baseline_name = f"{project_name}_{tag_new}"
        result_url = f"http://localhost:8501/?baseline={baseline_name}"
        
        # 更新状态为 completed
        self._update_task_status(task_id, 'completed', result_url=result_url)
        
    except Exception as e:
        # 更新状态为 failed
        self._update_task_status(task_id, 'failed', error_message=str(e))
```

### 2. 修改 Streamlit 应用

**文件**: `src/jcci/workflow/streamlit_app.py`

#### 添加路由逻辑
```python
def main():
    query_params = st.query_params
    page = query_params.get("page", "view")
    
    if page == "submit":
        render_task_submission_page()
        return
    elif page == "tasks":
        render_task_list_page()
        return
    
    # 原有的结果查看逻辑
    baseline_param = query_params.get("baseline", None)
    ...
```

#### 任务提交页面
```python
def render_task_submission_page():
    st.header("🚀 提交新的分析任务")
    
    with st.form("submit_task_form"):
        git_url = st.text_input("Git 仓库地址")
        username = st.text_input("Git 用户名")
        tag_old = st.text_input("旧版本标签")
        tag_new = st.text_input("新版本标签")
        max_depth = st.slider("最大分析深度", 1, 10, 5)
        
        submitted = st.form_submit_button("🚀 提交分析任务")
    
    if submitted:
        task_manager = get_task_manager(DB_PATH)
        task_id = task_manager.submit_task(...)
        st.success(f"✅ 任务已提交！任务 ID: {task_id}")
```

#### 任务列表页面
```python
def render_task_list_page():
    st.header("📋 分析任务列表")
    
    task_manager = get_task_manager(DB_PATH)
    tasks = task_manager.list_tasks(limit=50)
    
    for task in tasks:
        with st.expander(f"任务 {task['task_id']}"):
            st.markdown(f"**状态**: {task['status']}")
            st.progress(task['progress'] / 100.0)
            
            if task['status'] == 'completed':
                st.success(f"✅ 分析完成！")
                st.markdown(f"**访问链接**: [{task['result_url']}]({task['result_url']})")
```

#### 侧边栏导航
```python
def render_sidebar(baseline_param=None):
    st.sidebar.title("📊 JCCI 分析平台")
    
    # 添加导航按钮
    col1, col2 = st.sidebar.columns(2)
    with col1:
        if st.button("➕ 提交任务"):
            st.switch_page("?page=submit")
    with col2:
        if st.button("📋 任务列表"):
            st.switch_page("?page=tasks")
    
    # 原有的基线选择逻辑
    ...
```

### 3. 创建启动脚本

**文件**: `start_streamlit_service.py`

```python
#!/usr/bin/env python
"""JCCI Streamlit 服务启动脚本"""

import subprocess
import sys

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--host', default='0.0.0.0')
    parser.add_argument('--port', type=int, default=8501)
    
    args = parser.parse_args()
    
    subprocess.run([
        sys.executable, '-m', 'streamlit', 'run',
        'streamlit_app.py',
        '--server.address', args.host,
        '--server.port', str(args.port),
        '--server.headless', 'true'
    ])

if __name__ == '__main__':
    main()
```

---

## 🧪 使用流程

### 场景1：常驻服务 + Web 提交任务

#### 步骤1：启动 Streamlit 服务
```bash
cd c:\Users\carpe\VisualStudioProject\TestPlatform\jcci
python start_streamlit_service.py --host 0.0.0.0 --port 8501
```

**输出**:
```
================================================================================
🚀 启动 JCCI Streamlit 服务
================================================================================
📍 服务地址: http://0.0.0.0:8501
📁 应用路径: .../streamlit_app.py
================================================================================

💡 提示:
  - 访问 http://localhost:8501/?page=submit 提交新任务
  - 访问 http://localhost:8501/?page=tasks 查看任务列表
  - 访问 http://localhost:8501/?baseline=xxx 查看分析结果

按 Ctrl+C 停止服务
```

#### 步骤2：访问任务提交页面
浏览器打开: `http://localhost:8501/?page=submit`

填写表单:
- Git 仓库地址: `https://github.com/macrozheng/mall.git`
- Git 用户名: `your_username`
- 旧版本标签: `v1.0.0`
- 新版本标签: `v2.0.0`
- 最大分析深度: `5`

点击 "🚀 提交分析任务"

#### 步骤3：查看任务状态
自动跳转到任务列表页面，或手动访问: `http://localhost:8501/?page=tasks`

看到任务状态:
- ⏳ pending → 🔄 running → ✅ completed

#### 步骤4：访问分析结果
任务完成后，点击 "🔗 打开分析结果" 或直接访问返回的链接:
```
http://localhost:8501/?baseline=mall_v2.0.0
```

---

### 场景2：通过 API 调用 workflow1

如果需要在其他系统中集成，可以这样调用：

```python
from src.jcci.workflow.task_manager import get_task_manager

# 获取任务管理器
task_manager = get_task_manager("path/to/database.db")

# 提交任务
task_id = task_manager.submit_task(
    git_url="https://github.com/macrozheng/mall.git",
    username="your_username",
    tag_old="v1.0.0",
    tag_new="v2.0.0",
    max_depth=5
)

print(f"任务已提交: {task_id}")

# 查询任务状态
import time
while True:
    status = task_manager.get_task_status(task_id)
    print(f"状态: {status['status']}, 进度: {status['progress']}%")
    
    if status['status'] == 'completed':
        print(f"完成！访问链接: {status['result_url']}")
        break
    elif status['status'] == 'failed':
        print(f"失败: {status['error_message']}")
        break
    
    time.sleep(5)
```

---

## 📊 文件变更清单

### 新增文件

| 文件 | 行数 | 说明 |
|------|------|------|
| `src/jcci/workflow/task_manager.py` | 351 | 异步任务管理器 |
| `start_streamlit_service.py` | 66 | Streamlit 服务启动脚本 |
| `PRODUCTION_DEPLOYMENT_GUIDE.md` | - | 本文档 |

### 修改文件

| 文件 | 变更 | 说明 |
|------|------|------|
| `src/jcci/workflow/streamlit_app.py` | +200 | 添加任务管理页面和导航 |

---

## 🔧 配置说明

### 1. 数据库配置

任务管理器使用与主系统相同的数据库（`config.py` 中的 `DB_PATH`）。

新增表: `analysis_tasks`

### 2. Streamlit 配置

在 `config.py` 中配置:
```python
STREAMLIT_HOST = "0.0.0.0"  # 监听地址
STREAMLIT_PORT = 8501       # 监听端口
```

### 3. 输出目录

分析结果默认保存到:
```
{RESULT_DIR}/analyze_result/{project_name}_{timestamp}/
```

其中:
- `RESULT_DIR`: 在 `config.py` 中配置
- `project_name`: 从 git_url 提取
- `timestamp`: 任务提交时间

---

## 🚀 部署指南

### 开发环境

```bash
# 1. 进入项目目录
cd c:\Users\carpe\VisualStudioProject\TestPlatform\jcci

# 2. 启动 Streamlit 服务
python start_streamlit_service.py

# 3. 浏览器访问
# - 提交任务: http://localhost:8501/?page=submit
# - 查看任务: http://localhost:8501/?page=tasks
```

### 生产环境（Linux）

#### 方案1：systemd 服务

创建 `/etc/systemd/system/jcci-streamlit.service`:
```ini
[Unit]
Description=JCCI Streamlit Service
After=network.target

[Service]
Type=simple
User=jcci
WorkingDirectory=/opt/jcci
ExecStart=/usr/bin/python3 start_streamlit_service.py --host 0.0.0.0 --port 8501
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

启动服务:
```bash
sudo systemctl daemon-reload
sudo systemctl enable jcci-streamlit
sudo systemctl start jcci-streamlit
```

#### 方案2：Docker

创建 `Dockerfile`:
```dockerfile
FROM python:3.9-slim

WORKDIR /app
COPY . /app

RUN pip install -r requirements.txt

EXPOSE 8501

CMD ["python", "start_streamlit_service.py", "--host", "0.0.0.0", "--port", "8501"]
```

构建和运行:
```bash
docker build -t jcci-streamlit .
docker run -d -p 8501:8501 --name jcci jcci-streamlit
```

#### 方案3：Supervisor

创建 `/etc/supervisor/conf.d/jcci.conf`:
```ini
[program:jcci-streamlit]
command=/usr/bin/python3 /opt/jcci/start_streamlit_service.py --host 0.0.0.0 --port 8501
directory=/opt/jcci
user=jcci
autostart=true
autorestart=true
stderr_logfile=/var/log/jcci/err.log
stdout_logfile=/var/log/jcci/out.log
```

启动:
```bash
sudo supervisorctl reread
sudo supervisorctl update
sudo supervisorctl start jcci-streamlit
```

---

## 💡 最佳实践

### 1. 任务超时处理

对于长时间运行的任务，建议添加超时机制：

```python
def _execute_task(self, task_id, ...):
    import signal
    
    def timeout_handler(signum, frame):
        raise TimeoutError("任务执行超时")
    
    # 设置 30 分钟超时
    signal.signal(signal.SIGALRM, timeout_handler)
    signal.alarm(1800)
    
    try:
        # 执行 workflow1
        ...
    finally:
        signal.alarm(0)  # 取消超时
```

### 2. 并发控制

限制同时运行的任务数量：

```python
class AsyncTaskManager:
    def __init__(self, db_path, max_concurrent=3):
        self.max_concurrent = max_concurrent
        self.running_count = 0
        self._lock = threading.Lock()
    
    def submit_task(self, ...):
        with self._lock:
            if self.running_count >= self.max_concurrent:
                raise Exception("达到最大并发任务数限制")
            self.running_count += 1
        
        # 提交任务...
```

### 3. 任务清理

定期清理已完成的任务记录：

```python
def cleanup_old_tasks(self, days=30):
    """清理 30 天前的已完成任务"""
    conn = sqlite3.connect(self.db_path)
    cursor = conn.cursor()
    cursor.execute('''
        DELETE FROM analysis_tasks 
        WHERE status IN ('completed', 'failed')
        AND completed_at < datetime('now', '-30 days')
    ''')
    conn.commit()
    conn.close()
```

### 4. 监控和告警

添加任务失败告警：

```python
def _execute_task(self, task_id, ...):
    try:
        # 执行任务
        ...
    except Exception as e:
        # 发送告警
        send_alert(f"任务 {task_id} 失败: {str(e)}")
        raise
```

---

## 📈 性能优化建议

### 1. 数据库索引

为 `analysis_tasks` 表添加索引：

```sql
CREATE INDEX idx_tasks_status ON analysis_tasks(status);
CREATE INDEX idx_tasks_created ON analysis_tasks(created_at DESC);
```

### 2. 缓存优化

缓存任务列表查询结果：

```python
from functools import lru_cache

@lru_cache(maxsize=1)
def get_cached_tasks(timestamp_key):
    """缓存任务列表，5分钟过期"""
    return self.list_tasks()
```

### 3. 异步 I/O

对于大量任务，考虑使用 asyncio：

```python
import asyncio

async def execute_task_async(task_id, ...):
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, workflow1, ...)
```

---

## ✅ 验证清单

部署前请确认:

- [ ] Streamlit 服务可以正常启动
- [ ] 任务提交页面可以访问
- [ ] 任务可以成功提交并执行
- [ ] 任务状态可以实时更新
- [ ] 完成的任务可以访问结果
- [ ] 失败的任务显示错误信息
- [ ] 侧边栏导航正常工作
- [ ] 数据库表正确创建
- [ ] 日志记录完整

---

## 🎯 总结

本次升级实现了以下目标:

✅ **Streamlit 服务常驻**: 作为独立服务持续运行  
✅ **Web 界面提交任务**: 用户可通过网页触发分析  
✅ **异步执行**: 后台线程执行 workflow1，不阻塞 Web 界面  
✅ **任务状态跟踪**: 实时显示任务进度和状态  
✅ **结果链接返回**: 完成后提供可直接访问的 URL  
✅ **生产就绪**: 提供多种部署方案和最佳实践  

现在 JCCI 系统已经准备好部署到生产环境！🚀
