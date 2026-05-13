# JCCI Workflow & Streamlit Web平台

> 🚀 基于Streamlit的代码调用链分析与LLM智能分析平台

## 📖 快速导航

### 🎯 新手入门（推荐按顺序阅读）

1. **[QUICKSTART.md](QUICKSTART.md)** - ⭐ **5分钟快速上手**
   - 配置API密钥
   - 启动Web服务
   - 基本操作指南

2. **[DEMO_WALKTHROUGH.md](DEMO_WALKTHROUGH.md)** - 📺 **完整使用演示**
   - 逐步演示操作流程
   - AI分析功能展示
   - 实际案例讲解

3. **[README_STREAMLIT.md](README_STREAMLIT.md)** - 📚 **详细使用文档**
   - 功能特性说明
   - 配置详解
   - 多用户支持
   - 部署方案

---

### 🔧 开发与维护

4. **[ARCHITECTURE.md](ARCHITECTURE.md)** - 🏗️ **技术架构文档**（610行）
   - 系统架构图
   - 核心模块说明
   - 数据流分析
   - 缓存策略
   - 部署方案

5. **[FEATURES_DEMO.md](FEATURES_DEMO.md)** - 🎨 **功能演示说明**
   - 界面截图说明
   - 交互流程
   - 视觉设计

6. **[PROJECT_SUMMARY.md](PROJECT_SUMMARY.md)** - 📊 **项目总结**
   - 交付文件清单
   - 技术栈说明
   - 最佳实践
   - 未来规划

---

### 🐛 问题与修复

7. **[BUGFIX_RECORD.md](BUGFIX_RECORD.md)** - 📋 **问题修复记录**
   - 修复历史
   - 排查方法
   - 经验总结
   - 测试清单

8. **[FIX_DOWNWARD_CHAINS.md](FIX_DOWNWARD_CHAINS.md)** - 🔧 **向下调用链修复**
   - 问题描述
   - 根本原因
   - 修复方案

---

## 🚀 快速开始

### 方式一：完整流程（推荐）

```bash
cd c:\Users\carpe\VisualStudioProject\TestPlatform\jcci
python src/jcci/workflow/workflow1.py
```

这将：
1. ✅ 执行代码变更分析
2. ✅ 构建双向调用链
3. ✅ **自动启动Web服务**
4. ✅ **自动打开浏览器**

### 方式二：仅启动Web服务

如果已有分析结果：

```bash
cd src/jcci/workflow
streamlit run streamlit_app.py
```

或使用快速启动脚本：

```bash
# Windows
start.bat

# Linux/Mac
chmod +x start.sh
./start.sh
```

---

## 📁 文件说明

### 核心代码

| 文件 | 说明 | 行数 |
|------|------|------|
| `workflow1.py` | 主工作流脚本（5个步骤） | ~170 |
| `streamlit_app.py` | Streamlit Web应用 | 604 |
| `config.py` | 配置文件（⚠️ 不提交到Git） | ~18 |

### 配置模板

| 文件 | 说明 |
|------|------|
| `config.py.template` | 配置模板（复制为config.py使用） |
| `.gitignore` | Git忽略规则（保护敏感信息） |
| `requirements_streamlit.txt` | Python依赖列表 |

### 启动脚本

| 文件 | 适用系统 |
|------|----------|
| `start.bat` | Windows |
| `start.sh` | Linux/Mac |

### 文档

| 文档 | 类型 | 说明 |
|------|------|------|
| [QUICKSTART.md](QUICKSTART.md) | 入门 | 5分钟快速上手 ⭐ |
| [DEMO_WALKTHROUGH.md](DEMO_WALKTHROUGH.md) | 教程 | 完整使用演示 |
| [README_STREAMLIT.md](README_STREAMLIT.md) | 手册 | 详细使用文档 |
| [ARCHITECTURE.md](ARCHITECTURE.md) | 技术 | 架构设计文档 |
| [FEATURES_DEMO.md](FEATURES_DEMO.md) | 演示 | 功能界面说明 |
| [PROJECT_SUMMARY.md](PROJECT_SUMMARY.md) | 总结 | 项目整体总结 |
| [BUGFIX_RECORD.md](BUGFIX_RECORD.md) | 维护 | 问题修复记录 |
| [FIX_DOWNWARD_CHAINS.md](FIX_DOWNWARD_CHAINS.md) | 修复 | 具体问题修复 |

---

## 🎯 核心功能

### 1. 可视化展示
- ⬆️ **向上调用链**：影响面分析（谁调用了变更方法？）
- ⬇️ **向下调用链**：功能风险分析（变更方法调用了谁？）
- 📄 **文本视图**：原始结构化数据

### 2. AI智能分析
- 🤖 **方法级别**：变更分析、质量评估、测试建议
- 🔗 **调用链级别**：影响面评估、端到端测试策略

### 3. 数据增强
- 🔍 自动查询SQLite数据库
- 📊 补充方法和类详细信息
- 💾 智能缓存优化性能

### 4. 协作支持
- 👥 独立会话管理
- 🔗 分享链接生成
- 🌐 局域网/外网访问

---

## ⚙️ 配置说明

### 首次使用需要配置

```bash
# 1. 复制配置模板
copy config.py.template config.py

# 2. 编辑config.py，填入你的API Key
notepad config.py
```

### config.py 示例

```python
# LLM API配置
LLM_API_URL = "https://openai.good.hidns.vip/v1"
LLM_API_KEY = "your-api-key-here"  # ⚠️ 替换为你的API Key
LLM_MODEL = "moonshotai/kimi-k2.6"

# 路径配置
DB_PATH = r"path/to/database.db"
RESULT_DIR = r"path/to/analyze_result"

# 服务配置
STREAMLIT_PORT = 8501
STREAMLIT_HOST = "0.0.0.0"
```

**⚠️ 重要**: `config.py` 已加入 `.gitignore`，不会被提交到版本控制！

---

## 💡 使用场景

### 场景1: Code Review辅助
```
开发者提交代码 → 运行workflow1.py → 查看AI分析报告 → Code Review引用
```

### 场景2: 测试计划生成
```
选择变更方法 → AI分析 → 复制测试建议 → 整理成测试计划
```

### 场景3: 影响面评估
```
查看向上调用链 → 分析入口点 → 评估影响范围 → 决定发布策略
```

### 场景4: 团队分享
```
启动服务 → 获取分享链接 → 发送给同事 → 多人协作分析
```

---

## 📊 技术栈

- **前端**: Streamlit 1.52.2
- **后端**: Python 3.13
- **数据库**: SQLite
- **AI**: Kimi API (moonshotai/kimi-k2.6)
- **HTTP**: requests 2.33.1

---

## 🎓 学习路径

### 初学者
```
QUICKSTART.md → DEMO_WALKTHROUGH.md → 实际操作
```

### 进阶用户
```
README_STREAMLIT.md → FEATURES_DEMO.md → 自定义配置
```

### 开发者
```
ARCHITECTURE.md → streamlit_app.py源码 → 扩展开发
```

### 维护者
```
BUGFIX_RECORD.md → PROJECT_SUMMARY.md → 问题排查
```

---

## ❓ 常见问题

### Q: 提示"配置文件不存在"？
**A**: 复制 `config.py.template` 为 `config.py` 并编辑。

### Q: 如何修改端口？
**A**: 编辑 `config.py` 中的 `STREAMLIT_PORT`。

### Q: AI分析超时？
**A**: 检查网络连接和API Key有效性。

### Q: 如何让外网访问？
**A**: 使用ngrok内网穿透或部署到云服务器。

更多问题请查看各文档的FAQ部分。

---

## 📈 项目状态

| 功能 | 状态 | 备注 |
|------|------|------|
| 向上调用链展示 | ✅ 正常 | 3条数据 |
| 向下调用链展示 | ✅ 正常 | 3条数据（已修复） |
| AI分析方法 | ✅ 正常 | Kimi API集成 |
| AI分析调用链 | ✅ 正常 | 完整链路分析 |
| 会话管理 | ✅ 正常 | UUID生成 |
| 分享功能 | ✅ 正常 | 局域网访问 |
| 配置文件保护 | ✅ 正常 | .gitignore排除 |

**当前版本**: v1.0.1  
**最后更新**: 2026-05-06

---

## 🤝 贡献

欢迎提交：
- Bug报告
- 功能建议
- 使用案例
- 文档改进

---

## 📄 许可证

本项目遵循原JCCI项目的许可证。

---

## 📞 支持

遇到问题？

1. 📖 查看相关文档
2. 🔍 搜索 BUGFIX_RECORD.md
3. 💬 联系项目维护者

---

**开始使用**: [QUICKSTART.md](QUICKSTART.md) ⭐
