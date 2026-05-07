# Git Tag 分析功能使用指南

## 📋 概述

JCCI现在完全支持使用Git Tag进行代码变更分析，与Commit Hash方式并存。

## 🎯 支持的标识符类型

### 1. Commit Hash（短哈希）
```python
tag_old = 'd9501e9'
tag_new = '41e323e'
```
- 长度≤11字符，保持不变
- 数据库文件名：`carpenlee-cyber_mall_baseline_d9501e9.db`

### 2. Git Tag（附注标签）
```python
tag_old = 'TEST_BASELINE_v1.0'
tag_new = 'TEST_V1.2_MIXED_CHANGES'
```
- 长度>11字符，取最后11字符作为短标识符
- `TEST_BASELINE_v1.0` → `SELINE_v1.0`
- 数据库文件名：`carpenlee-cyber_mall_baseline_SELINE_v1.0.db`

### 3. 长Tag名称（生产环境）
```python
tag_old = 'MIX_LJ01.BUP_BUP3_UAT_UAT_00.00.01_SUMMER_20260403_01'
tag_new = 'MIX_LJ01.BUP_BUP3_UAT_UAT_00.00.01_SUMMER_20260403_02'
```
- 取最后11字符：`20260403_01` 和 `20260403_02`

## 🔧 使用方法

### 步骤1：创建Git Tag（可选）

```bash
# 给commit打附注标签
git tag -a TEST_BASELINE_v1.0 d9501e9 -m "测试基线版本 v1.0"
git tag -a TEST_V1.2_MIXED_CHANGES 41e323e -m "测试版本 v1.2"

# 查看标签
git tag -l

# 推送到远程（可选）
git push origin --tags
```

### 步骤2：配置workflow

编辑 `src/jcci/workflow/workflow1.py`：

```python
# 方式1：使用Git Tag
tag_old = 'TEST_BASELINE_v1.0'
tag_new = 'TEST_V1.2_MIXED_CHANGES'

# 方式2：使用Commit Hash
# tag_old = 'd9501e9'
# tag_new = '41e323e'
```

### 步骤3：运行分析

```bash
cd src/jcci/workflow
python workflow1.py
```

## 📊 测试结果

使用Tag `TEST_BASELINE_v1.0..TEST_V1.2_MIXED_CHANGES` 测试：

✅ **Git diff**: 成功识别4个文件变更  
✅ **变更类型**: 2个类、3个方法  
✅ **调用链分析**: 3/3成功（向上+向下）  
✅ **基线数据库**: 正确匹配路径  

## ⚙️ 技术实现

### 短标识符提取规则

```python
def _normalize_commit_or_tag(identifier: str) -> str:
    """
    标准化commit hash或tag标识符
    
    规则：
    - 长度 <= 11: 保持不变（如 commit hash）
    - 长度 > 11: 取最后11字符（如 tag名称）
    """
    if len(identifier) > 11:
        return identifier[-11:]
    else:
        return identifier
```

### 关键修复点

1. **workflow1.py**: 传递短标识符给call_chain（而非完整tag）
2. **database.py**: 移除重复截取逻辑，直接使用标准化短标识符
3. **一致性**: analyze.py和call_chain使用相同的短标识符命名规则

## 💡 最佳实践

1. **开发测试**: 使用Commit Hash（简单直观）
2. **版本管理**: 使用Git Tag（语义化版本）
3. **生产环境**: 使用长Tag名称（包含完整版本信息）

## 📝 注意事项

- 首次使用Tag分析时，系统会自动创建基线数据库
- 基线数据库文件名使用短标识符（最后11字符）
- 同一Tag的分析结果会被缓存，避免重复分析
- Tag必须在本地Git仓库中存在（可通过`git fetch --tags`获取）

---

**最后更新**: 2026-05-07  
**测试状态**: ✅ 通过
