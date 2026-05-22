# 分析参数持久化缓存功能说明

## 功能概述

实现了分析参数的持久化缓存功能，即使用户刷新页面也能自动载入上一次提交的参数内容，避免用户重复填写所有输入。

## 实现原理

### 1. 保存参数到 localStorage

当用户点击"提交分析任务"按钮后，系统会执行以下操作：

```javascript
// 将参数保存到浏览器的 localStorage
const params = {
    git_url: "https://github.com/...",
    username: "carpenlee-cyber",
    tag_old: "baseline_20260508_01",
    tag_new: "baseline_fix1_20260508_02",
    max_depth: 5
};
localStorage.setItem('jcci_analysis_params', JSON.stringify(params));
```

**代码位置**: `streamlit_app.py` 第 261-278 行

### 2. 页面加载时恢复参数

当用户访问或刷新页面时，系统会：

1. **检查 localStorage**: JavaScript 检查是否存在缓存的参数
2. **构建带参数的 URL**: 如果找到缓存，将参数添加到 URL 查询字符串中
3. **重新加载页面**: 使用新的 URL 重新加载页面
4. **读取 URL 参数**: Streamlit 从 URL 参数中读取缓存的值
5. **设置默认值**: 将缓存的值设置为表单字段的默认值

**JavaScript 逻辑** (第 113-149 行):
```javascript
(function() {
    // 检查是否已经有 URL 参数（避免无限循环）
    const urlParams = new URLSearchParams(window.location.search);
    const hasCachedParam = urlParams.get('cached');
    
    if (!hasCachedParam) {
        // 尝试从 localStorage 加载
        const cachedParams = localStorage.getItem('jcci_analysis_params');
        if (cachedParams) {
            const params = JSON.parse(cachedParams);
            
            // 构建新的 URL，带上缓存的参数
            const newUrl = new URL(window.location);
            newUrl.searchParams.set('cached_git_url', params.git_url || '');
            newUrl.searchParams.set('cached_username', params.username || '');
            newUrl.searchParams.set('cached_tag_old', params.tag_old || '');
            newUrl.searchParams.set('cached_tag_new', params.tag_new || '');
            newUrl.searchParams.set('cached_max_depth', params.max_depth || 5);
            newUrl.searchParams.set('cached', 'true');
            
            // 重新加载页面
            window.location.replace(newUrl.toString());
        }
    }
})();
```

**Python 逻辑** (第 151-173 行):
```python
# 从 URL 参数获取缓存的值（如果有）
query_params = st.query_params
cached_git_url = query_params.get("cached_git_url", None)
cached_username = query_params.get("cached_username", None)
cached_tag_old = query_params.get("cached_tag_old", None)
cached_tag_new = query_params.get("cached_tag_new", None)
cached_max_depth = query_params.get("cached_max_depth", None)

# 初始化 session state，优先使用缓存值
if 'last_git_url' not in st.session_state:
    st.session_state.last_git_url = cached_git_url if cached_git_url else "默认值"
# ... 其他字段类似
```

## 用户体验流程

### 首次使用
1. 用户打开应用
2. 表单显示默认值
3. 用户修改参数并提交任务
4. 参数自动保存到 localStorage

### 再次访问（刷新页面后）
1. 用户刷新页面或重新打开应用
2. JavaScript 检测到 localStorage 中有缓存
3. 页面自动重新加载，URL 中包含缓存参数
4. 表单自动填充上次提交的参数
5. 用户可以直接使用或修改后提交

## 技术要点

### 1. 避免无限循环
通过检查 URL 中是否有 `cached=true` 参数，避免页面不断重新加载。

### 2. 数据类型处理
- 字符串参数直接传递
- `max_depth` 需要转换为整数，并添加异常处理

### 3. 安全性
- 只缓存非敏感信息（不缓存密码）
- 使用 `json.dumps()` 确保字符串正确转义

### 4. 浏览器兼容性
- localStorage 是现代浏览器的标准 API，兼容性良好
- 添加了 try-catch 错误处理

## 注意事项

1. **密码不会缓存**: 出于安全考虑，Git 密码不会被保存到 localStorage
2. **跨浏览器隔离**: 每个浏览器的 localStorage 是独立的
3. **清除缓存**: 用户可以通过浏览器开发者工具清除 localStorage 来重置参数
4. **隐私模式**: 在隐私/无痕模式下，localStorage 可能在关闭浏览器后被清除

## 测试方法

1. **基本测试**:
   - 填写表单并提交任务
   - 刷新页面（F5）
   - 验证表单是否自动填充了上次的参数

2. **清除缓存测试**:
   - 打开浏览器开发者工具（F12）
   - 进入 Application → Local Storage
   - 删除 `jcci_analysis_params` 键
   - 刷新页面，验证是否恢复默认值

3. **跨会话测试**:
   - 关闭浏览器标签页
   - 重新打开应用
   - 验证参数是否仍然保留

## 相关文件

- `jcci/webapp/streamlit_app.py`: 主要实现文件
  - 第 98-173 行: 参数加载逻辑
  - 第 261-278 行: 参数保存逻辑
