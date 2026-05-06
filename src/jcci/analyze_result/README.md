# JCCI 分析结果缓存目录

## 说明

此目录用于存储 `analyze_two_commit_incremental` 方法的 JSON 缓存文件，以实现**完全幂等性**。

## 缓存文件命名规则

```
{username}_{project_name}_{commit_old}..{commit_new}.json
```

### 示例

- `carpenlee-cyber_mall_83abb8e..f2ace83.json`
- `carpenlee-cyber_mall_c824eac..d9501e9.json`

## 工作原理

### 首次分析
1. 执行完整的代码差异分析和调用链构建
2. 将完整结果（包括 nodes、links、categories、impacted_api_list、method_changes、change_summary）保存到 JSON 文件
3. 返回分析结果，标记 `is_duplicate: false`

### 重复分析
1. 检测到相同的分析请求（相同的 commit_old 和 commit_new）
2. 从 JSON 缓存文件加载完整结果
3. 返回缓存的结果，标记 `is_duplicate: true`
4. **所有字段与首次分析完全一致**

## 优势

✅ **完全幂等**：所有字段在重复分析时保持一致  
✅ **性能优化**：避免重复执行耗时的调用链构建  
✅ **数据完整性**：保留完整的调用链可视化数据  

## 管理建议

### 保留缓存
- 如果需要频繁进行相同的分析，建议保留缓存文件
- 缓存文件可以显著加快重复分析的速度

### 删除缓存
- 如果磁盘空间有限，可以安全删除缓存文件
- 删除后，下次分析将重新执行完整分析
- 或者回退到数据库模式（仅返回 method_changes 和 change_summary）

### 版本控制
- 默认情况下，此目录中的 `.json` 文件已被 `.gitignore` 忽略
- 如需共享缓存文件，可以手动添加到版本控制

## 技术细节

- **缓存位置**：`src/jcci/analyze_result/`
- **文件格式**：UTF-8 编码的 JSON
- **自动创建**：目录会在首次使用时自动创建
- **错误处理**：如果缓存加载失败，会自动回退到数据库模式

## 相关文件

- 实现代码：`src/jcci/analyze.py`
  - `_get_cache_file_path()`: 获取缓存文件路径
  - `_save_analysis_cache()`: 保存分析结果到缓存
  - `_load_analysis_cache()`: 从缓存加载分析结果
- 测试脚本：`test_json_cache_idempotency.py`
- 文档：`IDEMPOTENCY_IMPROVEMENT.md`
