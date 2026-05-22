"""
测试参数缓存功能的简单脚本

这个脚本用于演示和测试 localStorage 缓存功能的工作原理
"""

import json

def test_cache_save():
    """模拟保存参数到缓存"""
    params = {
        "git_url": "https://github.com/carpenlee-cyber/mall.git",
        "username": "carpenlee-cyber",
        "tag_old": "baseline_20260508_01",
        "tag_new": "baseline_fix1_20260508_02",
        "max_depth": 5
    }
    
    # 模拟 JavaScript 的 localStorage.setItem
    cache_data = json.dumps(params)
    print("✅ 参数已保存到缓存:")
    print(cache_data)
    return cache_data

def test_cache_load(cache_data):
    """模拟从缓存加载参数"""
    # 模拟 JavaScript 的 localStorage.getItem 和 JSON.parse
    params = json.loads(cache_data)
    print("\n✅ 从缓存加载的参数:")
    for key, value in params.items():
        print(f"  {key}: {value}")
    return params

def test_url_params_generation(params):
    """模拟生成带参数的 URL"""
    base_url = "http://localhost:8501"
    
    # 构建查询参数
    query_params = []
    if params.get('git_url'):
        query_params.append(f"cached_git_url={params['git_url']}")
    if params.get('username'):
        query_params.append(f"cached_username={params['username']}")
    if params.get('tag_old'):
        query_params.append(f"cached_tag_old={params['tag_old']}")
    if params.get('tag_new'):
        query_params.append(f"cached_tag_new={params['tag_new']}")
    if params.get('max_depth'):
        query_params.append(f"cached_max_depth={params['max_depth']}")
    query_params.append("cached=true")
    
    full_url = f"{base_url}?{'&'.join(query_params)}"
    print(f"\n✅ 生成的 URL:")
    print(full_url)
    return full_url

if __name__ == "__main__":
    print("=" * 60)
    print("测试参数缓存功能")
    print("=" * 60)
    
    # 1. 保存参数
    print("\n[步骤 1] 用户提交任务，保存参数到 localStorage")
    cache_data = test_cache_save()
    
    # 2. 加载参数
    print("\n[步骤 2] 页面刷新，从 localStorage 加载参数")
    params = test_cache_load(cache_data)
    
    # 3. 生成 URL
    print("\n[步骤 3] JavaScript 将参数添加到 URL 并重新加载页面")
    url = test_url_params_generation(params)
    
    print("\n" + "=" * 60)
    print("测试完成!")
    print("=" * 60)
    print("\n实际流程:")
    print("1. 用户填写表单并提交 → 参数保存到 localStorage")
    print("2. 用户刷新页面 → JavaScript 检测 localStorage")
    print("3. 发现有缓存 → 构建带参数的 URL 并重新加载")
    print("4. Streamlit 读取 URL 参数 → 设置表单默认值")
    print("5. 表单自动填充上次的参数 ✅")
