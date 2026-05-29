# 📊 分析结果页面 OOM 问题分析与优化方案

## 问题描述

用户在 📊 分析结果 页面查看两个 tag 之间的变更方法时，若变更方法数量非常多（数百至数千），前端加载极慢，浏览器内存消耗巨大，最终出现 Out of Memory 导致页面崩溃。

---

## 根因分析

通过对前后端代码的深入分析，定位到 **4 层叠加瓶颈**，每层都导致数据量与 DOM 节点呈 O(n) 量级膨胀。

### 🔴 根因 1：后端全量返回，无分页机制

**位置**：[`backend/app/api/analysis.py` L195-L248](../backend/app/api/analysis.py#L195-L248)

`/api/analysis/{baseline}/{version}/upwards` 和 `/downwards` 端点直接读取完整的 JSON 文件全量返回。

```python
# analysis.py L195-L220
@router.get("/{baseline}/{version}/upwards")
async def get_upwards_chains(baseline: str, version: str):
    filepath = os.path.join(_resolve_data_path(baseline, version), "upwards_call_chains.json")
    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)
    return data  # 全量返回，无任何分页或过滤
```

**影响**：当两个 tag 之间变更方法极多时，JSON 文件可达数十 MB。HTTP 传输 + JSON.parse 阶段即消耗大量内存。

---

### 🔴 根因 2：前端一次性并行加载全部 4 份数据

**位置**：[`frontend/src/views/AnalysisResult.vue` L128-L133](../frontend/src/views/AnalysisResult.vue#L128-L133)

```typescript
// AnalysisResult.vue L128-L133
const [upwardsRes, downwardsRes, upwardsTextRes, downwardsTextRes] = await Promise.all([
    getUpwardsChains(baseline, version).catch(() => null),
    getDownwardsChains(baseline, version).catch(() => null),
    getUpwardsText(baseline, version).catch(() => null),
    getDownwardsText(baseline, version).catch(() => null)
])
```

**影响**：即使用户只看"向上调用链"标签页，向下调用链 JSON、上下行文本 3 份大数据也被全部加载进内存。4 倍数据冗余。

---

### 🔴 根因 3：`default-expand-all` 导致 DOM 节点全量渲染

**位置**：[`frontend/src/components/CallChainTree.vue` L50-L57](../frontend/src/components/CallChainTree.vue#L50-L57)

```html
<el-tree
    :data="data"
    :props="treeProps"
    node-key="id"
    default-expand-all           <!-- 全部展开 -->
    :expand-on-click-node="false"
    v-loading="loading"
>
```

每个树节点模板（L58-L188）渲染多个子组件：

| 组件 | 数量/节点 | 用途 |
|------|-----------|------|
| `<el-icon>` | 1~2 | 连线、文档图标 |
| `<el-tooltip>` | 2~3 | 文档说明 tooltip |
| `<el-tag>` | 1~6 | 变更类型、DAO/SQL类型、入口标记、API路径、环检测、AI分析状态 |
| `<el-button>` | 2 | AI分析、查看结果按钮 |

**内存估算**：假设 500 个变更方法，每条链深 5 层：
- 2500 个树节点 × 平均 8 个子组件 ≈ **20,000 个 Vue 组件实例**
- 每个 `el-tooltip` 附带独立的 Popper DOM，进一步加剧内存压力

---

### 🟡 根因 4：30 秒定时全量轮询节点 AI 分析状态

**位置**：[`frontend/src/components/CallChainTree.vue` L288-L292](../frontend/src/components/CallChainTree.vue#L288-L292)

```typescript
// 定期刷新节点状态（30秒间隔）
statusRefreshTimer = window.setInterval(() => {
    if (document.visibilityState === 'visible') {
        loadNodesStatus()  // 递归收集所有节点 → POST /nodes-status
    }
}, 30000)
```

**影响**：每 30 秒递归遍历树中所有节点收集 key，再发送批量查询请求。在大树上此操作本身就很昂贵，且与根因 3 叠加后持续消耗 CPU 和内存。

---

## 优化方案

### 🥇 方案 A：折叠默认 + Tab 懒加载（最快见效，改动最小）

#### A1. 去掉 `default-expand-all`，改为仅展开第一层

**文件**：`frontend/src/components/CallChainTree.vue`

**改动**：

```
// 替换 L54 的 default-expand-all
// 移除: default-expand-all
// 新增: :default-expanded-keys="firstLevelKeys"

// Props 新增:
//   expandDepth?: number  (默认 1，仅展开第一层)

// 在组件内计算 firstLevelKeys:
const firstLevelKeys = computed(() => 
    props.data.filter(n => n.children?.length > 0).map(n => n.id)
)
```

**效果**：初始 DOM 量从 2500+ 降至约 50，用户在需要时手动展开子节点。

#### A2. 按 Tab 懒加载数据

**文件**：`frontend/src/views/AnalysisResult.vue`

**改动**：

```
// L118-L170 loadAnalysisData 函数重构:
// - 移除 Promise.all 并行加载
// - 改为只加载当前 activeTab 对应的数据
// - watch activeTab 切换时按需加载

// 伪代码:
const loadAnalysisData = async (baseline, version) => {
    // 仅加载当前 tab 的数据
    if (activeTab.value === 'upstream') {
        const [upwardsRes, upwardsTextRes] = await Promise.all([...])
    } else if (activeTab.value === 'downstream') {
        const [downwardsRes, downwardsTextRes] = await Promise.all([...])
    }
}

watch(activeTab, (tab) => {
    if (!loadedTabs.has(tab)) {
        loadTabData(tab)
    }
})
```

**效果**：内存占用降至原来的 1/4，后续 tab 切换时按需加载。

---

### 🥈 方案 B：后端分页 / 分批返回（中等改动，根本性解决）

#### B1. API 增加分页参数

**文件**：`backend/app/api/analysis.py`

**改动**：

```
// L195-L220 的 /upwards 端点改造:
@router.get("/{baseline}/{version}/upwards")
async def get_upwards_chains(
    baseline: str, 
    version: str,
    offset: int = 0,      // 新增：起始位置
    limit: int = 50       // 新增：每页数量
):
    data = json.load(open(filepath))
    impact_chains = data.get('impact_chains', [])
    total = len(impact_chains)
    
    return {
        "total": total,
        "offset": offset,
        "limit": limit,
        "impact_chains": impact_chains[offset:offset + limit]
    }
```

同理改造 `/downwards` 端点。

#### B2. 前端增加分页控件

**文件**：`frontend/src/views/AnalysisResult.vue`、`frontend/src/components/CallChainTree.vue`

**改动**：

```
// AnalysisResult.vue:
// - 新增 page/limit 响应式变量
// - loadAnalysisData 传分页参数

// CallChainTree.vue:
// - Props 新增 total/offset/limit
// - 底部新增 el-pagination 组件
// - 翻页时 emit 'page-change' 事件
```

**效果**：每次只传输 50 条链，HTTP 响应体控制在几 KB 到几十 KB，彻底解决大数据量传输问题。

---

### 🥉 方案 C：摘要 + 详情双视图（长期优化，最佳体验）

#### C1. 新增变更方法摘要 API

**文件**：`backend/app/api/analysis.py`

**改动**：

```
// 新增端点:
@router.get("/{baseline}/{version}/chain-methods")
async def get_chain_methods(baseline: str, version: str, direction: str = 'upwards'):
    data = json.load(open(filepath))
    chains = data.get('impact_chains', [])
    
    // 仅返回方法摘要信息（极轻量）
    return [
        {
            "class_name": chain['method_info']['class_name'],
            "method_name": chain['method_info']['method_name'],
            "change_type": chain['method_info']['change_type'],
            "entry_count": len(chain.get('entry_points', [])),
            "chain_depth": chain.get('max_depth', 0)
        }
        for chain in chains
    ]
```

#### C2. 新增摘要表格组件 + 详情按需加载

**文件**：新增 `frontend/src/components/MethodSummaryTable.vue`，修改 `AnalysisResult.vue`

**改动**：

```
// 新增 MethodSummaryTable.vue:
// - el-table 紧凑展示变更方法列表（类名、方法名、变更类型、入口数、链深度）
// - 点击某行 → emit 'select-method' → 父组件加载该方法完整调用链并展开

// AnalysisResult.vue:
// - 页面顶部显示 MethodSummaryTable
// - 下方显示 CallChainTree（显示选中方法的详细链）
// - 初次加载时仅请求 /chain-methods 摘要数据
```

**效果**：初次加载仅传输极轻量摘要数据，用户点击感兴趣的方法时才请求完整调用链详情。内存从 O(n×depth) 优化为 O(1)。

---

## 推荐实施路径

```
 方案 A（短期急救）         方案 B（中期加固）         方案 C（长期完美）
 ─────────────────    →    ─────────────────    →    ─────────────────
 去掉 default-expand-all     后端分页 + 前端分页控件      摘要表格 + 详情按需加载
 Tab 懒加载
 改动 2 个文件               改动 3 个文件                新增 1 文件 + 改动 2 文件
 约 30 行代码                约 60 行代码                 约 150 行代码
 预计 30 分钟                预计 2 小时                  预计 4 小时
```

| 方案 | 改动量 | 效果 | 内存降幅 | 适用场景 |
|------|--------|------|----------|----------|
| A | 小 | 立即缓解 | ~75% | 紧急修复，快速上线 |
| B | 中 | 根本解决 | ~95% | 1000+ 方法的大规模 diff |
| C | 大 | 最佳体验 | ~99% | 长期产品化方向 |

---

## 附录：涉及文件清单

| 文件 | 当前问题 | 方案 A | 方案 B | 方案 C |
|------|----------|--------|--------|--------|
| `backend/app/api/analysis.py` | 全量返回 JSON | - | 加分页参数 | 加 `/chain-methods` 摘要端点 |
| `frontend/src/views/AnalysisResult.vue` | Promise.all 并行加载 | Tab 懒加载 | 分页传参 | 摘要+详情双视图 |
| `frontend/src/components/CallChainTree.vue` | default-expand-all | 仅展开一层 | 分页控件 | 改受控展开 |
| `frontend/src/components/MethodSummaryTable.vue` | - | - | - | **新增** 摘要表格 |

---

> **文档创建时间**：2026-05-29
> **分析作者**：Qoder AI Assistant
