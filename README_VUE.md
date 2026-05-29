# 🔗 JCCI 调用链分析平台 (Vue 3 + FastAPI)

> 基于 Vue 3 和 FastAPI 的代码变更影响分析平台，提供调用链可视化、SQL 分析和 LLM 智能分析功能。

## ✨ 特性

- 🎯 **任务管理** - 提交、跟踪和管理代码分析任务
- 📊 **实时进度** - 自动刷新任务状态，无需手动操作
- 🔍 **调用链可视化** - 向上/向下调用链树形图展示
- 📝 **文本报告** - 详细的变更分析报告
- 💾 **SQL 分析** - 数据库操作影响分析
- 🤖 **LLM 集成** - AI 驱动的智能代码分析（预留接口）
- 📈 **埋点统计** - 使用情况数据统计和分析

## 🚀 快速开始

### Docker Compose 部署

```bash
cd jcci
docker-compose up -d --build
```

访问 http://localhost 即可使用。

### 本地开发

**后端:**
```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload
```

**前端:**
```bash
cd frontend
npm install
npm run dev
```

## 📁 项目结构

```
jcci/
├── backend/                 # FastAPI 后端
│   ├── app/
│   │   ├── api/            # API 路由
│   │   ├── models/         # Pydantic 模型
│   │   └── services/       # 业务逻辑
│   ├── Dockerfile
│   └── requirements.txt
├── frontend/               # Vue 3 前端
│   ├── src/
│   │   ├── api/           # API 调用封装
│   │   ├── components/    # 可复用组件
│   │   ├── views/         # 页面组件
│   │   ├── router/        # 路由配置
│   │   └── stores/        # Pinia 状态管理
│   ├── Dockerfile
│   └── nginx.conf
├── docker-compose.yml
└── DEPLOYMENT.md
```

## 🛠️ 技术栈

### 前端
- Vue 3 + TypeScript
- Element Plus UI
- Vue Router
- Pinia 状态管理
- Axios HTTP 客户端
- Vite 构建工具

### 后端
- FastAPI
- SQLite 数据库
- Pydantic 数据验证
- Uvicorn ASGI 服务器

### 部署
- Docker + Docker Compose
- Nginx 反向代理

## 📖 详细文档

- [部署指南](DEPLOYMENT.md)
- [API 文档](http://localhost:8000/docs) (运行后访问)

## 🎯 使用示例

1. **提交分析任务**
   - 填写 Git 仓库地址
   - 指定版本标签
   - 设置分析深度

2. **查看分析结果**
   - 调用链树形图
   - 文本报告
   - SQL 影响分析

3. **数据统计**
   - 按项目统计
   - 按用户统计
   - 总体使用情况

## 🔧 配置

环境变量配置见 [DEPLOYMENT.md](DEPLOYMENT.md)

## 📝 License

MIT License

## 👥 贡献

欢迎提交 Issue 和 Pull Request！
