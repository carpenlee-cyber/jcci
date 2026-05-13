# 性能监控 - 快速参考

## 🚀 一行代码启用监控

```python
from src.jcci.workflow.workflow1 import workflow1

# 执行工作流，自动打印性能报告
result = workflow1(
    git_url='https://github.com/...',
    username='your-username',
    tag_old='v1.0',
    tag_new='v2.0'
)
```

---

## 📊 查看性能瓶颈

执行完成后自动显示：

```
🔥 Top 5 性能瓶颈:
  1. Step 2: Incremental Analysis (JCCI): 18.234s  ← 最慢
  2. Step 3.2: Execute Bidirectional Analysis: 15.678s
  3. Step 3.1.1: Build Class Hierarchy Index (CHA): 5.432s
  ...
```

---

## 🛠️ 手动监控代码

### 方式1: 装饰器

```python
from src.jcci.utils.performance_monitor import performance_monitor

@performance_monitor
def my_function():
    # 你的代码
    pass
```

### 方式2: 上下文管理器

```python
from src.jcci.utils.performance_monitor import timer

with timer("Operation Name"):
    # 你的代码
    pass
```

---

## 📈 获取性能数据

```python
from src.jcci.utils.performance_monitor import (
    get_performance_summary,
    get_top_bottlenecks,
    print_performance_report
)

# 获取摘要
summary = get_performance_summary()
print(f"总耗时: {summary['total_time']}s")

# 获取瓶颈
bottlenecks = get_top_bottlenecks(5)

# 打印报告
print_performance_report()
```

---

## 💡 优化建议速查

| 瓶颈阶段 | 优化方案 | 预期提升 |
|---------|---------|---------|
| Step 2 (Git分析) | 数据库连接池 + WAL | 67% ↓ |
| Step 3.2 (双向分析) | 并行执行 | 42% ↓ |
| Step 3.1.1/3.1.2 (索引) | 持久化 + 懒加载 | 92% ↓ |
| Step 4 (文件输出) | 压缩存储 | 50% ↓ |

详细方案见：`PERFORMANCE_OPTIMIZATION_ANALYSIS.md`

---

## 📁 相关文件

- `src/jcci/utils/performance_monitor.py` - 核心模块
- `test_performance_monitor.py` - 测试脚本
- `PERFORMANCE_MONITOR_GUIDE.md` - 完整使用指南
- `PERFORMANCE_OPTIMIZATION_ANALYSIS.md` - 优化分析报告

---

## ✅ 测试验证

```bash
cd jcci
python test_performance_monitor.py
```

预期输出：性能报告 + 无错误
