# 性能监控工具使用指南

## 📖 概述

JCCI 系统现已集成性能监控工具，可以实时监控各阶段的执行时间，帮助快速定位性能瓶颈。

## 🚀 快速开始

### 1. 在 workflow1 中的使用

性能监控已自动集成到 `workflow1.py` 中，无需额外配置。执行工作流时会自动记录并打印性能报告。

```python
from src.jcci.workflow.workflow1 import workflow1

result = workflow1(
    git_url='https://github.com/...',
    username='your-username',
    tag_old='v1.0',
    tag_new='v2.0'
)
# 执行完成后会自动打印性能报告
```

### 2. 性能报告示例

```
================================================================================
📊 工作流执行完成 - 性能分析报告
================================================================================
总耗时: 45.234s

================================================================================
📊 性能分析报告
================================================================================

总操作数: 8
成功操作: 8
失败操作: 0
总耗时: 44.892s
平均耗时: 5.612s

--------------------------------------------------------------------------------
🔥 Top 5 性能瓶颈:
--------------------------------------------------------------------------------
  1. Step 2: Incremental Analysis (JCCI): 18.234s
  2. Step 3.2: Execute Bidirectional Analysis: 15.678s
  3. Step 3.1.1: Build Class Hierarchy Index (CHA): 5.432s
  4. Step 3.1.2: Build Mapper Index and DAO Analyzer: 3.210s
  5. Step 4: Visualization and File Output: 1.890s

================================================================================

✅ 分析流程已成功完成！
   总操作数: 8
   总耗时: 44.892s
   平均耗时: 5.612s
================================================================================
```

## 🛠️ 手动使用性能监控

### 方式1: 装饰器

```python
from src.jcci.utils.performance_monitor import performance_monitor

# 基本用法
@performance_monitor
def my_function():
    # 你的代码
    pass

# 自定义操作名称
@performance_monitor(operation_name="My Custom Operation")
def another_function():
    # 你的代码
    pass
```

### 方式2: 上下文管理器

```python
from src.jcci.utils.performance_monitor import timer

def my_function():
    with timer("Database Query"):
        # 执行数据库查询
        result = db.query(...)
    
    with timer("File Processing"):
        # 处理文件
        process_file(...)
```

### 方式3: 获取性能数据

```python
from src.jcci.utils.performance_monitor import (
    get_performance_summary,
    get_top_bottlenecks,
    print_performance_report
)

# 获取性能摘要
summary = get_performance_summary()
print(f"总耗时: {summary['total_time']}s")
print(f"平均耗时: {summary['average_time']}s")

# 获取Top 5瓶颈
bottlenecks = get_top_bottlenecks(5)
for bn in bottlenecks:
    print(f"{bn.operation}: {bn.elapsed_time}s")

# 打印完整报告
print_performance_report()
```

## 📊 监控的指标

workflow1 中自动监控以下阶段：

| 阶段 | 说明 |
|------|------|
| Step 1: Parameter Configuration | 参数配置和初始化 |
| Step 2: Incremental Analysis (JCCI) | Git Diff 解析和项目分析 |
| Step 3: Bidirectional Call Chain Analysis | 双向调用链分析（总） |
| ├─ Step 3.1: Initialize MyBatis Mapper Index and DAO Analyzer | 初始化索引和分析器（总） |
| │  ├─ Step 3.1.1: Build Class Hierarchy Index (CHA) | 构建类层次索引 |
| │  └─ Step 3.1.2: Build Mapper Index and DAO Analyzer | 构建 Mapper 索引 |
| ├─ Step 3.2: Execute Bidirectional Analysis | 执行双向分析 |
| Step 4: Visualization and File Output | 可视化和文件输出 |
| Step 5: Start Streamlit Web Service | 启动 Web 服务（可选） |

## 🔍 如何识别性能瓶颈

### 1. 查看 Top 5 瓶颈

性能报告会自动列出耗时最长的 5 个操作，重点关注：
- **Step 2** (Incremental Analysis): 如果超过 20s，考虑优化 Git 操作或启用缓存
- **Step 3.2** (Bidirectional Analysis): 如果超过 15s，考虑并行化或减少 max_depth
- **Step 3.1.1/3.1.2** (Index Building): 如果超过 5s，考虑持久化索引

### 2. 对比多次执行

通过对比不同 commit 范围的性能报告，可以发现：
- 哪些阶段随代码量增长而变慢
- 缓存是否生效（重复执行应显著更快）
- 哪些优化措施最有效

### 3. 定位具体问题

如果某个阶段异常慢，可以：
1. 查看该阶段的子操作（如 Step 3.1 包含 3.1.1 和 3.1.2）
2. 检查对应的日志输出
3. 根据 PERFORMANCE_OPTIMIZATION_ANALYSIS.md 中的建议进行优化

## 💡 最佳实践

### 1. 首次 vs 重复执行

- **首次执行**: 需要构建基线数据库，耗时较长（60-120s）
- **重复执行**: 利用 JSON 缓存，耗时显著降低（10-30s）

### 2. 调整 max_depth

如果 Step 3.2 耗时过长，可以尝试减小 `max_depth` 参数：

```python
workflow1(
    ...,
    max_depth=3  # 默认是 5，减小可提升性能
)
```

### 3. 禁用 Streamlit

如果不需要 Web 界面，可以禁用 Step 5：

```python
workflow1(
    ...,
    enable_streamlit=False  # 跳过 Web 服务启动
)
```

### 4. 定期清理缓存

缓存文件位于 `src/jcci/analyze_result/`，定期清理旧版本可节省磁盘空间。

## 🐛 故障排查

### 问题1: 性能报告未显示

**原因**: 可能在中途出错退出

**解决**: 检查日志中是否有错误信息，确保工作流完整执行

### 问题2: 某些阶段耗时异常

**原因**: 可能是网络问题、磁盘 I/O 瓶颈或数据库锁

**解决**: 
1. 检查网络连接（Git 操作）
2. 检查磁盘空间
3. 确认没有其他进程占用数据库

### 问题3: 内存占用过高

**原因**: 大型项目可能加载大量数据到内存

**解决**: 
1. 减小 `max_depth`
2. 考虑启用懒加载（参考 PERFORMANCE_OPTIMIZATION_ANALYSIS.md）
3. 增加系统可用内存

## 📚 相关文档

- [PERFORMANCE_OPTIMIZATION_ANALYSIS.md](./PERFORMANCE_OPTIMIZATION_ANALYSIS.md) - 详细的性能优化分析报告
- [test_performance_monitor.py](./test_performance_monitor.py) - 性能监控工具测试脚本

## 🎯 下一步

根据性能报告识别的瓶颈，可以参考 PERFORMANCE_OPTIMIZATION_ANALYSIS.md 中的优化建议，逐步实施：

1. **Phase 1**: 数据库连接池 + WAL 模式（快速见效）
2. **Phase 2**: 懒加载索引 + 并行分析（核心优化）
3. **Phase 3**: 多级缓存 + 索引持久化（高级优化）

每次优化后重新运行工作流，对比性能报告验证效果。
