# JCCI 调用链分析平台 - 部署指南

## 📋 目录结构

```
jcci/
├── backend/          # FastAPI 后端
│   ├── app/
│   │   ├── api/
│   │   ├── models/
│   │   └── services/
│   ├── Dockerfile
│   └── requirements.txt
├── frontend/         # Vue 3 前端
│   ├── src/
│   ├── Dockerfile
│   └── nginx.conf
└── docker-compose.yml
```

## 🚀 快速开始

### 方式一：Docker Compose 部署（推荐）

1. **构建并启动服务**
```bash
cd jcci
docker-compose up -d --build
```

2. **访问应用**
- 前端: http://localhost
- 后端 API: http://localhost:8000
- API 文档: http://localhost:8000/docs

3. **停止服务**
```bash
docker-compose down
```

### 方式二：本地开发模式

#### 后端启动

```bash
cd jcci/backend
pip install -r requirements.txt
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

#### 前端启动

```bash
cd jcci/frontend
npm install
npm run dev
```

访问 http://localhost:5173

## ⚙️ 配置说明

### 环境变量

后端支持以下环境变量：

| 变量名 | 说明 | 默认值 |
|--------|------|--------|
| DB_PATH | 数据库路径 | ./data/jcci.db |
| APP_NAME | 应用名称 | JCCI Platform |
| APP_VERSION | 应用版本 | 1.0.0 |

### Docker 配置

修改 `docker-compose.yml` 中的配置：

```yaml
services:
  backend:
    environment:
      - DB_PATH=/app/data/jcci.db
    ports:
      - "8000:8000"  # 可修改端口
  
  frontend:
    ports:
      - "80:80"  # 可修改端口
```

## 📊 功能特性

### 核心功能
- ✅ 任务提交与管理
- ✅ 实时进度监控（自动刷新）
- ✅ 调用链可视化（向上/向下）
- ✅ 文本分析报告
- ✅ SQL 影响分析
- ✅ LLM 智能分析（模拟数据）
- ✅ 埋点数据统计

### 技术栈
- **前端**: Vue 3 + TypeScript + Element Plus + Vite
- **后端**: FastAPI + SQLite + Pydantic
- **部署**: Docker + Docker Compose + Nginx

## 🔧 常见问题

### 1. 端口冲突

如果 80 或 8000 端口被占用，修改 `docker-compose.yml`：

```yaml
ports:
  - "8080:80"  # 前端改为 8080
  - "8001:8000"  # 后端改为 8001
```

### 2. 数据库持久化

数据存储在 `backend/data/jcci.db`，确保该目录有写入权限。

### 3. CORS 问题

前端通过 Nginx 代理访问后端 API，已配置好跨域处理。

## 📝 API 端点

### 任务管理
- `POST /api/tasks/submit` - 提交任务
- `GET /api/tasks/{task_id}` - 获取任务状态
- `GET /api/tasks/` - 获取任务列表
- `DELETE /api/tasks/{task_id}` - 取消任务

### 高级功能
- `POST /api/tasks/{task_id}/analyze-llm` - LLM 分析
- `GET /api/tasks/stats/tracking` - 埋点统计

## 🎯 使用流程

1. **提交任务**
   - 访问 http://localhost/submit
   - 填写 Git 仓库信息
   - 点击"提交分析任务"

2. **查看进度**
   - 访问 http://localhost/tasks
   - 任务列表每 5 秒自动刷新
   - 查看任务状态和进度

3. **查看结果**
   - 任务完成后点击"查看结果"
   - 切换不同视图查看分析结果

## 🔐 安全建议

1. 生产环境启用 HTTPS
2. 添加身份验证中间件
3. 限制 API 访问频率
4. 定期备份数据库

## 📞 技术支持

如有问题，请检查：
1. Docker 日志: `docker-compose logs -f`
2. 后端日志: `docker logs jcci-backend`
3. 前端日志: `docker logs jcci-frontend`
