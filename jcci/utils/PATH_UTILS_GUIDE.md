# JCCI 路径管理模块使用指南

## 📋 概述

`jcci/utils/path_utils.py` 提供了统一的路径计算函数，避免硬编码路径导致的错误。

---

## 🎯 核心常量

```python
from jcci.utils.path_utils import (
    PROJECT_ROOT,      # 项目根目录: c:\...\jcci\jcci
    RESULT_DIR,        # 分析结果目录: c:\...\jcci\jcci\analyze_result
    WEBAPP_DIR,        # Web应用目录: c:\...\jcci\jcci\webapp
    TASK_MANAGER_DB_PATH,  # 任务数据库: c:\...\jcci\jcci\webapp\task_manager.db
)
```

---

## 🔧 路径计算函数

### 1. 基线目录路径

```python
from jcci.utils.path_utils import get_baseline_dir

baseline_dir = get_baseline_dir("mall", "20260508_01")
# 返回: c:\...\jcci\analyze_result\mall_20260508_01
```

### 2. 版本子目录路径

```python
from jcci.utils.path_utils import get_version_subdir

version_dir = get_version_subdir("mall", "20260508_01", "20260508_02")
# 返回: c:\...\jcci\analyze_result\mall_20260508_01\20260508_02
```

### 3. 基线数据库路径

```python
from jcci.utils.path_utils import get_baseline_db_path

db_path = get_baseline_db_path("mall", "20260508_01")
# 返回: c:\...\jcci\analyze_result\mall_20260508_01\mall_20260508_01_baseline.db
```

### 4. 分析缓存文件路径

```python
from jcci.utils.path_utils import get_analysis_cache_path

cache_path = get_analysis_cache_path("mall", "20260508_01", "20260508_02")
# 返回: c:\...\jcci\analyze_result\mall_20260508_01\20260508_02\analysis_result.json
```

### 5. 调用链文件路径

```python
from jcci.utils.path_utils import (
    get_upwards_txt_path,
    get_downwards_txt_path,
    get_upwards_json_path,
    get_downwards_json_path,
)

upwards_txt = get_upwards_txt_path("mall", "20260508_01", "20260508_02")
downwards_txt = get_downwards_txt_path("mall", "20260508_01", "20260508_02")
upwards_json = get_upwards_json_path("mall", "20260508_01", "20260508_02")
downwards_json = get_downwards_json_path("mall", "20260508_01", "20260508_02")
```

---

## 🛠️ 工具函数

### 确保目录存在

```python
from jcci.utils.path_utils import ensure_dir_exists, get_version_subdir

version_dir = get_version_subdir("mall", "20260508_01", "20260508_02")
ensure_dir_exists(version_dir)  # 自动创建目录（如果不存在）
```

### 列出基线目录

```python
from jcci.utils.path_utils import list_baseline_dirs

baselines = list_baseline_dirs()
# 返回: ['mall_20260508_01', 'mall_20260508_02', ...]
```

### 列出版本子目录

```python
from jcci.utils.path_utils import list_version_subdirs

versions = list_version_subdirs("mall", "20260508_01")
# 返回: ['20260508_02', '20260508_03', ...]
```

---

## 🔄 迁移示例

### ❌ 旧代码（硬编码路径）

```python
# jcci/analyze.py
output_dir = os.path.join(os.path.dirname(__file__), 'analyze_result', 
                         f"{self.project_name}_{self.commit_short_old}")

# jcci/call_chain/analyzer.py
base_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'analyze_result')
output_dir = os.path.join(base_dir, f"{project_name}_{commit_old_short}")
```

### ✅ 新代码（使用 path_utils）

```python
from jcci.utils.path_utils import get_baseline_dir, get_version_subdir

# jcci/analyze.py
output_dir = get_baseline_dir(self.project_name, self.commit_short_old)

# jcci/call_chain/analyzer.py
output_dir = get_baseline_dir(project_name, commit_old_short)
version_dir = get_version_subdir(project_name, commit_old_short, commit_new_short)
```

---

## 📝 完整使用示例

```python
from jcci.utils.path_utils import (
    RESULT_DIR,
    get_baseline_dir,
    get_version_subdir,
    get_baseline_db_path,
    get_analysis_cache_path,
    get_upwards_txt_path,
    get_downwards_txt_path,
    ensure_dir_exists,
)

# 定义参数
project_name = "mall"
commit_old = "20260508_01"
commit_new = "20260508_02"

# 1. 获取基线目录
baseline_dir = get_baseline_dir(project_name, commit_old)
print(f"基线目录: {baseline_dir}")

# 2. 获取版本子目录
version_dir = get_version_subdir(project_name, commit_old, commit_new)
ensure_dir_exists(version_dir)  # 确保目录存在
print(f"版本子目录: {version_dir}")

# 3. 获取基线数据库路径
db_path = get_baseline_db_path(project_name, commit_old)
print(f"基线数据库: {db_path}")

# 4. 获取分析结果文件路径
cache_path = get_analysis_cache_path(project_name, commit_old, commit_new)
upwards_path = get_upwards_txt_path(project_name, commit_old, commit_new)
downwards_path = get_downwards_txt_path(project_name, commit_old, commit_new)

print(f"分析缓存: {cache_path}")
print(f"向上调用链: {upwards_path}")
print(f"向下调用链: {downwards_path}")

# 5. 列出所有基线
from jcci.utils.path_utils import list_baseline_dirs
baselines = list_baseline_dirs()
print(f"可用基线: {baselines}")
```

---

## ⚠️ 注意事项

1. **不要硬编码路径**：始终使用 `path_utils` 中的函数
2. **导入顺序**：在文件顶部导入，避免循环依赖
3. **路径分隔符**：使用 `os.path.join()` 而非字符串拼接
4. **目录创建**：使用 `ensure_dir_exists()` 确保目录存在

---

## 🚀 测试模块

```bash
cd c:\Users\carpe\VisualStudioProject\TestPlatform\jcci
python jcci/utils/path_utils.py
```

输出示例：
```
================================================================================
JCCI 路径管理模块测试
================================================================================

📁 项目根目录: C:\Users\carpe\VisualStudioProject\TestPlatform\jcci\jcci
📊 分析结果目录: C:\Users\carpe\VisualStudioProject\TestPlatform\jcci\jcci\analyze_result
...
```

---

## 📖 相关文件

- **实现文件**: `jcci/utils/path_utils.py`
- **导出模块**: `jcci/utils/__init__.py`
- **配置文件**: `webapp/config.py`（仍保留，用于 Streamlit 应用）
