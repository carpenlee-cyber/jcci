# JCCI 系统设计文档

> **Java Code Change Impact Analyzer**  
> Java 代码变更影响分析系统 — 基于 Git Diff 的双向静态调用链分析平台

**文档版本**: v1.0  
**更新日期**: 2026-05-30  
**用途**: 供后续需求开发和 Bug 修复时快速理解系统整体架构  

---

## 目录

1. [项目概述](#1-项目概述)
2. [系统架构总览](#2-系统架构总览)
3. [核心引擎 (jcci/)](#3-核心引擎-jcci)
4. [调用链分析子系统 (call_chain/)](#4-调用链分析子系统-call_chain)
5. [后端 API 与服务层 (backend/)](#5-后端-api-与服务层-backend)
6. [前端应用 (frontend/)](#6-前端应用-frontend)
7. [数据库设计](#7-数据库设计)
8. [关键数据流与业务流程](#8-关键数据流与业务流程)
9. [部署架构](#9-部署架构)
10. [关键设计决策与已知问题](#10-关键设计决策与已知问题)

---

## 1. 项目概述

### 1.1 核心目标

JCCI 解决的核心问题是：**当 Java 项目发生代码变更时，如何快速准确地评估变更的影响范围？**

系统通过对比两个 Git 版本（`tag_old` → `tag_new`）之间的差异，构建**双向调用链**：
- **向上分析**（影响面）：谁调用了变更的方法？→ 找到受影响的 HTTP API 入口
- **向下分析**（功能风险）：变更方法调用了谁？→ 评估深层依赖风险，追踪到 SQL/表级别

### 1.2 技术栈

| 层 | 技术 |
|----|------|
| **核心引擎** | Python 3 + javalang (Java AST 解析) + unidiff (Git diff 解析) |
| **后端服务** | FastAPI + SQLite + 多线程 |
| **LLM 集成** | OpenAI 兼容 API（Gemini 3.1 Flash Lite） |
| **前端** | Vue 3 + TypeScript + Element Plus + Pinia |
| **构建/部署** | Vite + Docker Compose + Nginx |

### 1.3 项目目录结构

```
jcci/
├── jcci/                      # ★ 核心引擎（纯 Python 包）
│   ├── analyze.py             #    JCCI 主类：全过程编排器
│   ├── java_parse.py          #    Java 源码解析器（基于 javalang）
│   ├── mapper_parse.py        #    MyBatis Mapper XML 解析器
│   ├── diff_parse.py          #    Git diff 解析器
│   ├── graph.py               #    调用图数据结构 + ECharts 布局
│   ├── change_type_analyzer.py#    变更类型标记器
│   ├── database.py            #    SQLite CRUD 封装
│   ├── constant.py / config.py#    常量 & 配置
│   ├── call_chain/            # ★ 调用链分析子系统
│   │   ├── analyzer.py        #    双向分析编排器
│   │   ├── index.py           #    统一方法索引（基线+增量合并）
│   │   ├── builder.py         #    DFS 链构建器
│   │   ├── upwards_builder.py #    向上分析
│   │   ├── downwards_builder.py#   向下分析
│   │   ├── class_hierarchy.py #    类层次分析 (CHA)
│   │   ├── entry_detector.py  #    入口检测器
│   │   ├── mapper_index.py    #    Mapper 索引
│   │   ├── dao_analyzer.py    #    DAO 分析器
│   │   ├── sql_performance_analyzer.py  # SQL 性能规则引擎
│   │   ├── field_lineage_tracker.py     # 字段血缘追踪
│   │   ├── visualizer.py      #    文本可视化输出
│   │   └── models.py          #    数据模型
│   └── utils/                 #    工具模块
│       ├── tag_utils.py       #    短标识符提取
│       ├── path_utils.py      #    统一路径管理
│       └── performance_monitor.py # 性能监控
│
├── backend/                   # ★ 后端 Web 服务
│   └── app/
│       ├── main.py            #    FastAPI 应用入口
│       ├── config.py          #    配置管理
│       ├── models.py          #    Pydantic 数据模型
│       ├── api/
│       │   ├── tasks.py       #    任务管理 API
│       │   ├── analysis.py    #    分析数据 API (24 个端点)
│       │   └── stats.py       #    统计 API
│       ├── services/
│       │   ├── task_service.py#    任务服务（后台执行引擎）
│       │   ├── llm_service.py #    LLM 分析服务
│       │   └── sql_analyzer.py#    SQL 分析服务
│       └── core/
│           └── workflow1.py   #    核心工作流
│
├── frontend/                  # ★ 前端 Vue 应用
│   ├── src/
│   │   ├── api/               #    HTTP API 封装 (axios)
│   │   ├── stores/            #    Pinia 状态管理
│   │   ├── views/             #    6 个页面
│   │   ├── components/        #    7 个组件
│   │   └── router/            #    Vue Router 配置
│   ├── vite.config.ts         #    Vite 构建配置
│   └── nginx.conf             #    Nginx 配置
│
├── docker-compose.yml         #    Docker 编排
├── main.py                    #    命令行入口
└── markdown/                  #    文档
```

---

## 2. 系统架构总览

### 2.1 架构图

```
┌──────────────────────────────────────────────────────────────────────┐
│                          用户浏览器 (Vue 3 + Element Plus)            │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐  │
│  │ 任务提交  │ │ 任务列表  │ │ 分析结果  │ │ AI 配置  │ │ AI 结果  │  │
│  └────┬─────┘ └──────────┘ └────┬─────┘ └──────┬───┘ └────┬─────┘  │
└───────┼──────────────────────────┼──────────────┼──────────┼────────┘
        │                          │              │          │
   POST /api/tasks/submit    GET /api/analysis/*  LLM API   轮询 task
        │                          │              │          │
        ▼                          ▼              ▼          ▼
┌───────────────────────────────────────────────────────────────────┐
│                      Nginx (端口 80)                               │
│         / → 静态文件       /api/ → proxy_pass backend:8000         │
└──────────────────────────────┬────────────────────────────────────┘
                               │
                               ▼
┌───────────────────────────────────────────────────────────────────┐
│                     FastAPI Backend (端口 8000)                     │
│  ┌─────────────────┐  ┌──────────────────┐  ┌─────────────────┐   │
│  │  tasks.py       │  │  analysis.py     │  │  stats.py       │   │
│  │  (任务 CRUD)    │  │  (24 端点)       │  │  (埋点统计)     │   │
│  └────────┬────────┘  └───────┬──────────┘  └─────────────────┘   │
│           │                   │                                    │
│           ▼                   ▼                                    │
│  ┌─────────────────┐  ┌──────────────────────────────────────┐    │
│  │  task_service   │  │  analysis.py  (磁盘文件加载)          │    │
│  │  (后台引擎)      │  │  + path_utils (路径映射)             │    │
│  │  - 串行调度      │  │  + tag_utils  (短标识符解析)         │    │
│  │  - 去重检查      │  └──────────────────────────────────────┘    │
│  │  - Git 验证      │                                              │
│  └────────┬────────┘                                              │
│           │                                                        │
│           ▼                                                        │
│  ┌───────────────────────────────────────────────────────────┐    │
│  │                   workflow1.py                            │    │
│  │  Step1: 参数配置 → Step2: JCCI 增量分析                   │    │
│  │  Step3: 双向调用链 → Step4: 可视化输出 → Step5: 性能报告   │    │
│  └───────────────────────────────┬───────────────────────────┘    │
│                                  │                                 │
└──────────────────────────────────┼─────────────────────────────────┘
                                   │
                                   ▼
┌───────────────────────────────────────────────────────────────────┐
│                      JCCI 核心引擎                                 │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐             │
│  │ Git操作  │→│ diff解析 │→│ Java解析 │→│ 影响传播 │             │
│  │ clone/   │ │ unidiff  │ │ javalang │ │ BFS遍历  │             │
│  │ reset    │ │          │ │ AST提取  │ │ 调用图   │             │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘             │
│                                                                   │
│  输出:                                                             │
│  ┌──────────────────────────┐ ┌──────────────────────────────┐   │
│  │ analyze_result/          │ │ call_chain/                  │   │
│  │  ├── *.db (基线代码库)    │ │  ├── upwards_call_chains.json│   │
│  │  ├── analysis_result.json│ │  ├── downwards_call_chains.. │   │
│  │  ├── upwards.txt         │ │  ├── upwards.txt             │   │
│  │  └── downwards.txt       │ │  └── downwards.txt           │   │
│  └──────────────────────────┘ └──────────────────────────────┘   │
└───────────────────────────────────────────────────────────────────┘
```

### 2.2 核心设计理念

| 理念 | 实现 |
|------|------|
| **基线+增量策略** | 仅解析变更文件，未变更数据复用基线库，大幅加速重复分析 |
| **预计算索引** | `method_invocation_map` JSON 字段预存储调用关系，O(1) 反向查询 |
| **双向分析** | 向上（影响面）+ 向下（功能风险），覆盖完整评估维度 |
| **静态分析为主** | CHA（类层次分析）处理多态，DAO 穿透到 SQL 表级别 |
| **LLM 增强** | AI 解释变更影响、生成测试建议，结果缓存避免重复调用 |

---

## 3. 核心引擎 (jcci/)

### 3.1 模块关系图

```
analyze.py (JCCI 主类)
  ├── _get_project_files()          → 遍历项目文件树
  ├── _get_diff_parse_map()         → git diff + unidiff 解析
  │     └── diff_parse.py            → get_diff_info()
  ├── _parse_project()              → 切换版本 + 解析源码
  │     └── java_parse.py            → JavaParse.parse_java_file_list()
  │           ├── javalang.parse()    → AST 解析
  │           ├── _parse_method()     → 提取 method_invocation_map
  │           └── database.py         → 写入 SQLite
  ├── _start_analysis_diff_and_impact()
  │     ├── _diff_analyze()          → 遍历 diff → 标记变更节点
  │     └── _impacted_analyze()      → BFS 影响传播
  │           └── graph.py            → Graph.create_node_category()
  ├── change_type_analyzer.py        → 标记 ADDED/MODIFIED/DELETED
  └── _draw_and_write_result()       → 布局 + JSON 输出
```

### 3.2 核心数据结构：method_invocation_map

这是 JCCI 最核心的字段，在解析 Java 方法体时生成，存储在该方法对应 SQLite 行的 `method_invocation_map` 列中。

```json
{
  "com.example.UserService": {
    "entity": {"body": true, "return_type": true},
    "methods": {
      "getUser(Long)": [42],
      "save(User)": [58, 63]
    },
    "fields": {
      "userName": [12]
    }
  }
}
```

**用途**：影响分析时通过 SQL 的 `json_extract(method_invocation_map, ...)` 反向查询"谁调用了变更方法"，避免实时 AST 遍历。

### 3.3 完整数据流

```
1. git clone {repo} → projects/{project_name}/
2. git reset --hard {commit_old}
3. os.walk → 收集所有 .java 文件
4. ThreadPoolExecutor(4线程) 并行解析 → SQLite 入库
   └── 每个文件: javalang AST → extract class/field/method/import/annotation
   └── 核心: method_invocation_map 的生成
5. git diff {old}..{new} → unidiff.PatchSet 解析
   └── 返回 {filepath: {line_num_added, line_content_added, ...}}
6. git reset --hard {commit_new}
7. 增量解析: 仅解析 diff 涉及的 .java 文件
8. ChangeTypeAnalyzer: 标记 class/method/field 的 change_type
9. BFS 影响传播:
   └── 从 diff 中找到的变更方法/字段出发
   └── json_extract 反向查询调用关系
   └── 递归发现所有受影响的方法 → 标记为 impacted
10. Graph.draw_graph() → ECharts 布局 → JSON 输出
```

### 3.4 基线+增量分析策略

| 场景 | 条件 | 策略 |
|------|------|------|
| **A: 首次运行** | 基线 DB 不存在 | 全量解析 commit_old → project_id=0（基线），diff 后增量解析 commit_new → project_id=1 |
| **B: 重复分析** | DB 存在 + 相同版本对 | 直接返回 JSON 缓存（幂等） |
| **C: 同基线新版本** | DB 存在 + 不同 commit_new | 复用基线 project_id=0，仅增量解析新版本，效率极高 |

---

## 4. 调用链分析子系统 (call_chain/)

### 4.1 双向分析架构

```
build_call_chains_for_changes()  ← 顶层入口
     │
     ├── build_upwards_call_chains()     ★ 向上：影响面
     │     ├── UnifiedMethodIndex        (基线+增量合并)
     │     ├── ClassHierarchyIndex       (CHA 接口解析)
     │     ├── ReverseCallerIndex        (反向调用索引)
     │     ├── AnnotationAwareEntryDetector (入口检测)
     │     └── UpwardsCallChainBuilder   (反向 DFS)
     │         输出: upwards_call_chains.json
     │
     └── build_downwards_call_chains()   ★ 向下：功能风险
           ├── UnifiedMethodIndex
           ├── DownwardsCallChainBuilder (DFS 展开 + CHA)
           │     ├── DaoAnalyzer         (SQL 穿透)
           │     │     ├── MapperMethodIndex
           │     │     ├── SqlPerformanceAnalyzer
           │     │     └── FieldLineageTracker
           │     └── ClassHierarchyIndex
           └── CallChainVisualizer       (文本格式化)
               输出: downwards_call_chains.json
```

### 4.2 UnifiedMethodIndex — 基线+增量合并

核心问题：增量数据库只有变更方法，未变更方法在索引中缺失会导致调用链断裂。

```
Step 1: 加载基线 (project_id=0) → baseline_index
Step 2: 加载增量 (project_id=N) → incremental_index
Step 3: 合并:
   ├── ① 复制活跃基线方法 (排除 change_type='DELETED')
   └── ② 用增量覆盖匹配 key (获取最新 invocation_map)
```

### 4.3 DFS 环检测机制

```python
# 路径级 visited（非全局）
path_visited.add(caller_key)     # 进入递归前
_dfs_expand(child, ...)           # 递归展开
path_visited.discard(caller_key) # 递归返回后移除

# 环判定: if child_key ∈ path_visited → 创建 is_cyclic=True 节点
```

**设计决策**：路径级检测只阻止 A→B→C→A 的循环，允许不同路径访问同一节点，可准确反映多路径调用关系。

### 4.4 入口检测 — 三级优先级

| 优先级 | 规则 | 类型 |
|--------|------|------|
| 1 | `is_api = 1` 且有 `api_paths` | `HTTP_API` / `SCHEDULED_TASK` 等 |
| 2 | 类名以 `Controller` 结尾 | `CONTROLLER_BY_CONVENTION` |
| 3 | 无静态调用者 | `NO_STATIC_CALLER`（可能未被检测到的入口） |

支持的入口注解：`@RequestMapping`, `@GetMapping`, `@PostMapping`, `@Scheduled`, `@EventListener`, `@JmsListener` 等。

### 4.5 CHA — 类层次分析

解决 Java 多态问题。对于接口调用 `MenuService.list()`：
- 构建 `_interface_impls` → `"MenuService" → ["MenuServiceImpl", ...]`
- 构建 `_method_override_map` → 接口方法签名 → 所有实现类方法
- `resolve_interface_call()` 返回所有实现类的对应方法

### 4.6 DAO 层 SQL 穿透

```
MapperMethodIndex.build_index()
  → 扫描 MyBatis XML → 解析 <select>/<insert>/<update>/<delete>
  → _link_java_methods() 关联 Mapper 接口方法
  → 存入 mapper_methods 表

DaoAnalyzer.analyze(method)
  → SQL 类型/表名/字段提取
  → 风险评估: DELETE 无 WHERE → CRITICAL
  → SQL 性能分析: 规则引擎扣分制
  → 字段血缘追踪: SELECT/INSERT/UPDATE 字段提取
```

### 4.7 数据模型: CallChainNode

```python
@dataclass
class CallChainNode:
    node_id: str               # "0|com.example.Controller|handleRequest()"
    package_class: str         # 完整类名
    method_signature: str      # "delete(Long)"
    method_name: str           # "delete"
    class_name: str            # "UserController"
    depth: int = 0             # 节点深度
    invocation_lines: List[int]# 调用行号
    children: List['CallChainNode']  # 递归子节点
    is_cyclic: bool            # 是否环
    is_leaf: bool              # 是否叶子
    root_type: str             # HTTP_API / SCHEDULED_TASK / ...
    call_type: str             # DIRECT / CHA_RESOLVED
    api_paths: List[str]       # ["[POST]/api/user/{id}"]
    change_type: str           # UNCHANGED / ADDED / MODIFIED / DELETED
    dao_info: Optional[DaoInfo]# DAO 透视信息
    documentation: Optional[str] # 方法注释
```

---

## 5. 后端 API 与服务层 (backend/)

### 5.1 FastAPI 路由表

#### 任务管理 (`/api/tasks`)

| 方法 | 路径 | 功能 |
|------|------|------|
| POST | `/api/tasks/submit` | 提交 JCCI 分析任务（Git 验证 + 去重 + 排队） |
| GET | `/api/tasks/` | 获取任务列表（分页） |
| GET | `/api/tasks/{task_id}` | 获取任务状态 |
| DELETE | `/api/tasks/{task_id}` | 取消 PENDING 任务 |

#### 分析数据 (`/api/analysis`)

| 方法 | 路径 | 功能 |
|------|------|------|
| GET | `/api/analysis/baselines` | 列出所有基线及版本 |
| GET | `/api/analysis/{baseline}/{version}/info` | 版本数据文件存在性检查 |
| GET | `/api/analysis/{baseline}/{version}/upwards` | 读取向上调用链 JSON |
| GET | `/api/analysis/{baseline}/{version}/downwards` | 读取向下调用链 JSON |
| GET | `/api/analysis/{baseline}/{version}/text/upwards` | 读取向上调用链文本 |
| GET | `/api/analysis/{baseline}/{version}/text/downwards` | 读取向下调用链文本 |
| GET | `/api/analysis/{baseline}/{version}/chain-methods` | 变更方法摘要列表 |
| GET | `/api/analysis/{baseline}/{version}/sql-summary` | SQL 汇总信息 |
| GET | `/api/analysis/method-code` | 方法源代码对比 |
| GET | `/api/analysis/default-prompts` | 获取默认 LLM 提示词 |

#### LLM 分析 (同步 + 异步)

| 方法 | 路径 | 功能 |
|------|------|------|
| POST | `/api/analysis/analyze/method` | 同步分析单个方法 |
| POST | `/api/analysis/analyze/chain` | 同步分析调用链 |
| POST | `/api/analysis/tasks` | 创建异步 AI 任务 |
| POST | `/api/analysis/batch-methods` | 批量方法异步分析 |
| GET | `/api/analysis/tasks/{task_id}` | 查询异步任务状态 |
| GET | `/api/analysis/results/{result_id}` | 获取分析结果 |
| POST | `/api/analysis/nodes-status` | 批量查询节点 AI 分析状态 |
| GET | `/api/analysis/llm-status` | LLM 全局状态 |

### 5.2 任务生命周期

```
PENDING  ← 用户 POST /api/tasks/submit（经 Git 验证 + 去重检查）
   │
   │ _try_start_next_task() — 单线程串行调度
   ▼
RUNNING  (progress: 10% → 20% → 90% → 100%)
   │
   ├── Git 验证失败 → FAILED (error_message)
   ├── workflow1 异常 → FAILED
   └── workflow1 成功 → COMPLETED (result_url)
```

**并发控制**：同一时间最多 1 个 JCCI 分析任务运行，其余排队。

### 5.3 Git 引用验证

`validate_git_refs()` 使用 `git ls-remote --exit-code` 查询远程仓库：
1. 直接查询用户输入的 ref → 匹配则通过
2. 未匹配则加 `refs/tags/` 前缀再查 → 匹配则通过
3. 均不匹配 → 返回明确错误信息

在 **提交入口** (`tasks.py`) 和 **执行入口** (`task_service.py._execute_task`) 两处验证，形成双重防线。

### 5.4 LLM 分析服务

```
LLMService
  ├── 缓存层: llm_analysis_cache (UNIQUE 约束含 baseline+version)
  ├── 任务层: llm_analysis_tasks + llm_analysis_results
  ├── 分析核心: analyze_method() / analyze_chain()
  ├── 异步执行: FastAPI BackgroundTasks + 2秒轮询
  │     ├── 方法分析: 逐方法 → 保存子结果
  │     └── 链分析: 逐方法分析(0~60%) → 聚合分析(65~100%) 两阶段
  └── API: OpenAI 兼容接口, 3次重试+指数退避, 全局互斥锁
```

### 5.5 Workflow1 执行流程

```
Step1: 参数配置
  → 提取短标识符 extract_short_tag(tag_old/new)

Step2: JCCI 增量分析
  → JCCI.analyze_two_commit_incremental(commit_new, commit_old)
  → 返回: change_summary.methods + source_dir

Step3: 双向调用链分析
  → 3.1 构建 CHA 类层次索引
  → 3.2 构建 Mapper 索引 + DAO 分析器
  → 3.3 build_call_chains_for_changes() → 双向 JSON

Step4: 可视化输出
  → 格式化文本 → 写入 filesystem

Step5: 性能报告
  → 打印各步骤耗时统计
```

---

## 6. 前端应用 (frontend/)

### 6.1 技术栈

| 技术 | 用途 |
|------|------|
| Vue 3 Composition API | UI 框架 |
| TypeScript | 类型安全 |
| Vite 8 | 构建工具 |
| Element Plus | UI 组件库 |
| Pinia | 状态管理 |
| Vue Router 5 | 路由 |
| Axios | HTTP 客户端 |
| Marked | Markdown→HTML |

### 6.2 路由设计

```
/ (重定向) → /tasks
├── /tasks                                任务列表（首页）
├── /submit                               提交新任务
├── /analysis/:taskId                     分析结果（Tab: 树视图/文本视图/SQL视图）
│   ├── /analysis/:taskId/ai-config       AI 分析配置
│   ├── /analysis/:taskId/ai-progress/:aiTaskId  AI 进度
│   └── /analysis/:taskId/ai-result/:resultId    AI 结果
```

### 6.3 核心组件

| 组件 | 功能 |
|------|------|
| `BaselineSelector` | 基线/版本级联选择（会话持久化到 localStorage） |
| `MethodSummaryTable` | 变更方法摘要表格（支持点击→详情/链查看） |
| `CallChainTree` | 调用链 el-tree 渲染（多标签：变更类型/API/DAO/SQL/环/缓存状态） |
| `TextViewer` | 调用链文本视图 |
| `SqlAnalysisView` | SQL 分析视图（表名/操作类型/调用次数） |
| `LLMAnalyzer` | 同步式 AI 分析（轮询全局 LLM 状态） |

### 6.4 状态管理 (Pinia)

| Store | 职责 |
|-------|------|
| `session` | 用户会话（基线/版本/Tab 选择），localStorage + URL 双向同步 |
| `aiAnalysis` | AI 分析全流程（配置/方法选择/任务轮询/节点状态/结果） |
| `task` | 任务列表缓存 |

### 6.5 关键业务流程

#### 提交流程
```
TaskSubmit.vue → POST /api/tasks/submit
  → Git 验证(400 提示) → 去重检查 → 创建 PENDING
  → 自动跳转 /tasks → 5秒轮询状态 → 完成点击"查看结果"
```

#### AI 分析流程
```
分析结果页 → [AI 分析] → /ai-config
  → 选择范围(方法/链) → 选择方向(上/下) → 查看代码对比
  → store.submitTask() → POST /api/analysis/tasks
  → /ai-progress/:aiTaskId → 2秒轮询进度
  → 完成 → /ai-result/:resultId → Markdown 渲染报告
```

### 6.6 部署架构 (Docker + Nginx)

```
浏览器 → Nginx:80
  ├── /        → dist/ 静态文件
  └── /api/    → proxy_pass backend:8000
                    └── FastAPI (Uvicorn)
```

Nginx `try_files $uri $uri/ /index.html` 支持 Vue Router history 模式。

---

## 7. 数据库设计

### 7.1 数据库文件分布

| 文件 | 用途 |
|------|------|
| `backend/task_manager.db` | 任务管理 + LLM 缓存 |
| `databases/{username}_jcci.db` | 用户级 JCCI 元数据 |
| `analyze_result/{project}_{commit_old}/{project}_{commit_old}_baseline.db` | 基线代码库 |

### 7.2 基线代码库核心表

```
project ──< class ──< methods
                ├──< field
                └──< import

mapper_methods (v4.0)
```

| 表 | 核心字段 |
|----|---------|
| **project** | project_id(0=基线,>0=增量), project_name, git_url, branch, commit_or_branch_new/old |
| **class** | class_id, package_name, class_name, extends_class, implements, annotations, is_controller, change_type |
| **methods** | method_id, return_type, method_name, parameters(JSON), body(JSON), **method_invocation_map(JSON)** ← 核心, is_api, api_path(JSON), change_type |
| **field** | field_id, field_type, field_name, is_static, start_line/end_line, change_type |
| **import** | class_id, import_path |
| **mapper_methods** | namespace, method_id, full_method, sql_type, sql_content, tables(JSON), linked_method_id |

### 7.3 任务管理库表

| 表 | 核心字段 |
|----|---------|
| **analysis_tasks** | task_id, status, git_url, tag_old, tag_new, max_depth, progress, result_url, error_message, project_code |
| **llm_analysis_cache** | UNIQUE(type, direction, baseline, version, class_name, method_name, change_type), analysis_result |
| **llm_analysis_tasks** | task_id, status, progress, total_methods, completed_methods, current_stage |
| **llm_analysis_results** | result_id, task_id, parent_task_id, analysis_result |

### 7.4 project_id 体系

| project_id | 含义 | 内容 |
|------------|------|------|
| 0 | 基线 | 旧版本**全量**代码（所有 class/method/field） |
| 1, 2, 3... | 增量 | 各版本**差异**代码（仅变更文件） |

增量版本中的 UNCHANGED 方法直接从基线继承，无需重复分析。这使得同一基线下的多次分析效率极高。

---

## 8. 关键数据流与业务流程

### 8.1 短标识符映射规则

JCCI 输入 tag 格式多样，通过 `extract_short_tag()` 统一为短标识符：

| 输入类型 | 规则 | 示例 |
|----------|------|------|
| 内嵌短标识符 `SHA{4hex}_{11chars}` | 提取 | `mall_SHAb42d_20231225_01` → `SHAb42d_20231225_01` |
| Commit hash (40位hex) | 截取前8位 | `dd6569c3558f...` → `dd6569c3` |
| 任意 Git tag | SHA256 前4位 + `_` + 后11位 | `MIX_LJ01...20260506_01` → `SHA3afe_20260506_01` |

**短标识符用于**：数据库记录、文件命名、目录结构  
**原始值用于**：Git 操作（checkout, reset, diff）

### 8.2 磁盘存储布局

```
analyze_result/
└── {project_name}_{commit_old_short}/       ← 基线目录
    ├── {project_name}_{commit_old_short}_baseline.db  ← 基线代码库
    └── {commit_new_short}/                  ← 版本子目录
        ├── analysis_result.json             ← JCCI 缓存
        ├── upwards_call_chains.json         ← 向上调用链
        ├── downwards_call_chains.json       ← 向下调用链
        ├── upwards.txt                      ← 向上链文本
        └── downwards.txt                    ← 向下链文本
```

### 8.3 路径解析三级回退

`_resolve_data_path(baseline, version)` 支持 URL 参数与磁盘路径的灵活映射：

```
1. 直接路径: analyze_result/{baseline}/{version}
2. 短标签路径: analyze_result/{short_baseline}/{short_version}
3. 前缀扫描: analyze_result/*{_short_baseline}/{short_version}
```

---

## 9. 部署架构

### 9.1 Docker Compose

```yaml
services:
  backend:     # FastAPI + Uvicorn, 端口 8000
    build: ./backend/Dockerfile
    volumes: ./backend/data:/app/data

  frontend:    # Nginx + Vue 静态文件, 端口 80
    build: ./frontend/Dockerfile (多阶段: Node构建 → Nginx serving)
    depends_on: backend
```

### 9.2 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `JCCI_PROJECTS_DIR` | `{PROJECT_ROOT}/projects` | Git 项目克隆目录 |
| `JCCI_DB_DIR` | `{PROJECT_ROOT}/databases` | 用户数据库目录 |
| `LLM_API_URL` | — | LLM API 地址 |
| `LLM_API_KEY` | — | LLM API Key |
| `LLM_MODEL` | — | LLM 模型名 |

---

## 10. 关键设计决策与已知问题

### 10.1 关键设计决策

| 决策 | 原因 | 影响 |
|------|------|------|
| **SQLite 而非 PostgreSQL** | 部署简单、零配置、单文件数据库 | 并行写入受限、无连接池 |
| **基线+增量策略** | 避免每次全量解析 | 重复分析效率提升 10x+ |
| **单线程串行调度** | 防止 Git clone/reset 冲突 | 高并发场景需排队 |
| **LLM 结果全维缓存** | baseline+version 维度隔离 | 不同基线同名方法结果不覆盖 |
| **method_invocation_map 预计算** | 避免实时 AST 遍历 | 影响分析 O(1) 查询 |
| **路径级环检测（非全局）** | 保留多路径信息 | 更准确反映实际调用关系 |
| **CHA 类层次分析** | 静态分析多态调用 | 无法处理运行时动态确定（反射/Lambda/代理） |

### 10.2 已知局限

| ID | 严重度 | 描述 |
|----|--------|------|
| DYNAMIC_DISPATCH | **HIGH** | 无法覆盖反射、Lambda、方法引用、动态代理、Spring AOP |
| INTERFACE_RESOLUTION | MEDIUM | CHA 基于静态类层次，无法处理运行时类型（工厂模式、条件分支） |
| FRAMEWORK_CALLS | MEDIUM | 框架调度代码不在分析范围（DispatcherServlet、定时调度器） |
| NATIVE_CODE | LOW | JNI 调用无法追踪 |

### 10.3 已知工程问题

| 问题 | 严重度 | 位置 |
|------|--------|------|
| SQL 注入风险（字符串拼接SQL） | **严重** | `database.py` insert_data/add_project/add_class |
| os.system() 命令注入 | **中等** | `analyze.py` git 命令拼接 |
| select_data 缓存无过期 | **中等** | `database.py` sql_result_map |
| project_id 硬编码 0 | **中等** | `analyze.py` _collect_method_changes |
| diff_parse 跳过注释行 | **低** | `diff_parse.py` |

---

## 附录 A: 重要文件索引

| 文件 | 行数 | 说明 |
|------|------|------|
| `jcci/jcci/analyze.py` | 1233 | JCCI 主类：全过程编排器 |
| `jcci/jcci/java_parse.py` | 1018 | Java AST 解析器 |
| `jcci/jcci/call_chain/analyzer.py` | 744 | 双向调用链编排 |
| `jcci/jcci/call_chain/index.py` | 313 | 统一方法索引 |
| `jcci/backend/app/api/analysis.py` | 1283 | 分析数据 API |
| `jcci/backend/app/services/llm_service.py` | 1651 | LLM 分析服务 |
| `jcci/backend/app/services/task_service.py` | 499 | 任务后台引擎 |
| `jcci/backend/app/core/workflow1.py` | 276 | 核心工作流 |
| `jcci/frontend/src/components/CallChainTree.vue` | ~500 | 调用链树组件 |
| `jcci/frontend/src/stores/aiAnalysis.ts` | ~300 | AI 分析状态管理 |

## 附录 B: API 端点速查

| 分组 | 端点 | 功能 |
|------|------|------|
| 任务 | `POST /api/tasks/submit` | 提交任务（含 Git 验证） |
| 任务 | `GET /api/tasks/{task_id}` | 任务状态轮询 |
| 分析 | `GET /api/analysis/baselines` | 基线列表 |
| 分析 | `GET /api/analysis/{b}/{v}/upwards` | 向上调用链 JSON |
| 分析 | `GET /api/analysis/{b}/{v}/chain-methods` | 变更方法列表 |
| LLM | `POST /api/analysis/tasks` | 创建异步 AI 任务 |
| LLM | `GET /api/analysis/tasks/{task_id}` | AI 任务状态轮询 |
| LLM | `POST /api/analysis/nodes-status` | 批量节点分析状态 |

---

*文档结束*
