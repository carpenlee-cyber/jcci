# JCCI 生产部署快速开始指南

## 🚀 5分钟快速启动

### 步骤1：启动 Streamlit 服务

```bash
cd c:\Users\carpe\VisualStudioProject\TestPlatform\jcci
python start_streamlit_service.py
```

**输出**:
```
================================================================================
🚀 启动 JCCI Streamlit 服务
================================================================================
📍 服务地址: http://0.0.0.0:8501
📁 应用路径: C:\...\jcci\src\jcci\workflow\streamlit_app.py
================================================================================

💡 提示:
  - 访问 http://localhost:8501/?page=submit 提交新任务
  - 访问 http://localhost:8501/?page=tasks 查看任务列表
  - 访问 http://localhost:8501/?baseline=xxx 查看分析结果

按 Ctrl+C 停止服务
================================================================================

📂 工作目录: C:\...\jcci\src\jcci\workflow

  You can now view your Streamlit app in your browser.

  Local URL: http://localhost:8501
  Network URL: http://99.11.37.201:8501
```

### 步骤2：访问任务提交页面

浏览器打开: **http://localhost:8501/?page=submit**

### 步骤3：填写分析参数

| 字段 | 示例值 | 说明 |
|------|--------|------|
| Git 仓库地址 | `https://github.com/macrozheng/mall.git` | Git 仓库 URL |
| Git 用户名 | `your_username` | 您的 Git 用户名 |
| 旧版本标签 | `v1.0.0` | 对比的起始版本 |
| 新版本标签 | `v2.0.0` | 对比的目标版本 |
| 最大分析深度 | `5` | 调用链分析深度（1-10） |

点击 **"🚀 提交分析任务"**

### 步骤4：查看任务状态

自动跳转到任务列表页面，或访问: **http://localhost:8501/?page=tasks**

看到任务状态变化:
```
⏳ pending → 🔄 running (进度: 10% → 90%) → ✅ completed
```

### 步骤5：访问分析结果

任务完成后，点击 **"🔗 打开分析结果"** 或直接访问返回的链接:

```
http://localhost:8501/?baseline=mall_v2.0.0
```

---

## 📱 常用URL

| 功能 | URL |
|------|-----|
| 提交新任务 | `http://localhost:8501/?page=submit` |
| 查看任务列表 | `http://localhost:8501/?page=tasks` |
| 查看分析结果 | `http://localhost:8501/?baseline={基线名称}` |

---

## 🔧 自定义配置

### 修改监听地址和端口

```bash
python start_streamlit_service.py --host 0.0.0.0 --port 8502
```

### 后台运行（Linux）

```bash
nohup python start_streamlit_service.py > streamlit.log 2>&1 &
```

### 停止服务

按 **Ctrl+C** 或在另一个终端执行:
```bash
pkill -f streamlit
```

---

## 💡 常见问题

### Q1: 任务一直处于 pending 状态？

**检查**:
1. 确认 workflow1 可以正常执行
2. 查看日志文件是否有错误
3. 检查数据库是否正常

### Q2: 如何查看任务执行日志？

Streamlit 控制台会输出详细日志，包括:
```
2026-05-13 11:30:00,123 任务已提交: abc123def456
2026-05-13 11:30:01,456 开始执行 workflow1: task_id=abc123def456
2026-05-13 11:35:00,789 任务完成: abc123def456, URL: http://...
```

### Q3: 任务失败怎么办？

在任务列表页面，失败的任务会显示错误信息:
```
❌ 错误: Git repository not found
```

根据错误信息调整后重新提交。

### Q4: 如何清理旧任务？

任务记录保存在数据库中，可以手动清理:

```python
from src.jcci.workflow.task_manager import get_task_manager

task_manager = get_task_manager("path/to/database.db")

# 清理 30 天前的已完成任务
import sqlite3
conn = sqlite3.connect(task_manager.db_path)
cursor = conn.cursor()
cursor.execute('''
    DELETE FROM analysis_tasks 
    WHERE status IN ('completed', 'failed')
    AND completed_at < datetime('now', '-30 days')
''')
conn.commit()
conn.close()
```

---

## 🎯 下一步

- 阅读 [PRODUCTION_DEPLOYMENT_GUIDE.md](./PRODUCTION_DEPLOYMENT_GUIDE.md) 了解完整的生产部署方案
- 配置 systemd/Docker/Supervisor 实现开机自启
- 添加监控和告警机制
- 配置反向代理（Nginx）提供 HTTPS

---

祝您使用愉快！🎉
