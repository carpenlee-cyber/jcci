# Mall 项目 MyBatis 架构分析报告

**分析日期**: 2026-05-11  
**分析目的**: 为 MyBatis Mapper 链路追踪功能实施提供实际项目依据  
**目标项目**: mall (Spring Boot + MyBatis 电商系统)

---

## 一、项目概况

### 1.1 项目结构

```
mall/
├── mall-admin/          # 后台管理系统
│   ├── controller/      # Controller层 (31个)
│   ├── service/         # Service接口层 (32个)
│   │   └── impl/        # Service实现层 (31个)
│   ├── dao/             # 自定义DAO层 (22个) ⭐
│   └── mapper/          # MBG生成的Mapper接口
├── mall-mbg/            # MyBatis Generator生成代码
│   └── mapper/          # 基础Mapper接口和XML
├── mall-portal/         # 前台商城系统
├── mall-search/         # 搜索服务
└── mall-common/         # 公共模块
```

### 1.2 MyBatis 配置

**MapperScan 配置位置**:
- `mall-admin`: `@MapperScan({"com.macro.mall.mapper","com.macro.mall.dao"})`
- `mall-portal`: `@MapperScan({"com.macro.mall.mapper","com.macro.mall.portal.dao"})`
- `mall-search`: `@MapperScan({"com.macro.mall.mapper","com.macro.mall.search.dao"})`
- `mall-demo`: `@MapperScan("com.macro.mall.mapper")`

**关键发现**: 
- ✅ **两层Mapper架构**: 
  - `com.macro.mall.mapper` - MBG自动生成的基础CRUD
  - `com.macro.mall.dao` - 自定义复杂查询（手写SQL）

---

## 二、MyBatis Mapper 架构深度分析

### 2.1 两类 Mapper 的区别

#### 类型1: MBG生成的基础Mapper (mall-mbg)

**特点**:
- 由 MyBatis Generator 自动生成
- 提供标准 CRUD 操作
- XML 文件在 `mall-mbg/src/main/resources/com/macro/mall/mapper/`
- 命名规范: `{Entity}Mapper.java` + `{Entity}Mapper.xml`

**示例**: `UmsMenuMapper`
```java
// Java接口
public interface UmsMenuMapper {
    int updateByPrimaryKeySelective(UmsMenu record);
    UmsMenu selectByPrimaryKey(Long id);
    // ... 其他标准方法
}
```

```xml
<!-- XML: UmsMenuMapper.xml -->
<mapper namespace="com.macro.mall.mapper.UmsMenuMapper">
  <update id="updateByPrimaryKeySelective" parameterType="com.macro.mall.model.UmsMenu">
    update ums_menu
    <set>
      <if test="hidden != null">
        hidden = #{hidden,jdbcType=INTEGER},
      </if>
      <!-- 其他字段 -->
    </set>
    where id = #{id,jdbcType=BIGINT}
  </update>
</mapper>
```

**统计**: 
- 约 **80+** 个基础 Mapper XML 文件
- 每个包含 10-15 个标准 SQL 语句
- 总计约 **1000+** 个 SQL 语句

#### 类型2: 自定义DAO (mall-admin/dao, mall-portal/dao等)

**特点**:
- 手动编写，处理复杂查询
- 支持动态 SQL (`<if>`, `<foreach>`, `<choose>`)
- XML 文件在各模块的 `src/main/resources/dao/`
- 命名规范: `{Entity}Dao.java` + `{Entity}Dao.xml`

**示例**: `OmsOrderDao`
```java
// Java接口
public interface OmsOrderDao {
    List<OmsOrder> getList(@Param("queryParam") OmsOrderQueryParam queryParam);
    int delivery(@Param("list") List<OmsOrderDeliveryParam> deliveryParamList);
    OmsOrderDetail getDetail(@Param("id") Long id);
}
```

```xml
<!-- XML: OmsOrderDao.xml -->
<mapper namespace="com.macro.mall.dao.OmsOrderDao">
    <select id="getList" resultMap="...">
        SELECT * FROM oms_order
        WHERE delete_status = 0
        <if test="queryParam.orderSn!=null and queryParam.orderSn!=''">
            AND order_sn = #{queryParam.orderSn}
        </if>
        <if test="queryParam.status!=null">
            AND `status` = #{queryParam.status}
        </if>
        <!-- 更多动态条件 -->
    </select>
    
    <update id="delivery">
        UPDATE oms_order
        SET
        delivery_sn = CASE id
        <foreach collection="list" item="item">
            WHEN #{item.orderId} THEN #{item.deliverySn}
        </foreach>
        END,
        `status` = CASE id
        <foreach collection="list" item="item">
            WHEN #{item.orderId} THEN 2
        </foreach>
        END
        WHERE id IN
        <foreach collection="list" item="item" separator="," open="(" close=")">
            #{item.orderId}
        </foreach>
    </update>
</mapper>
```

**统计**:
- mall-admin: **22个** DAO
- mall-portal: 约 **15个** DAO
- mall-search: 约 **5个** DAO
- 总计约 **40-50个** 自定义 DAO

### 2.2 实际调用链模式分析

#### 模式1: Controller → Service → Mapper (基础CRUD)

```java
// Controller
@RestController
@RequestMapping("/menu")
public class UmsMenuController {
    @Autowired
    private UmsMenuService menuService;
    
    @PostMapping("/update/{id}")
    public CommonResult update(@PathVariable Long id, @RequestBody UmsMenu menu) {
        int count = menuService.update(id, menu);
        return count > 0 ? CommonResult.success() : CommonResult.failed();
    }
}

// Service接口
public interface UmsMenuService {
    int update(Long id, UmsMenu menu);
}

// Service实现
@Service
public class UmsMenuServiceImpl implements UmsMenuService {
    @Autowired
    private UmsMenuMapper menuMapper;  // ⚠️ 注入的是MBG生成的Mapper
    
    @Override
    public int update(Long id, UmsMenu menu) {
        menu.setId(id);
        return menuMapper.updateByPrimaryKeySelective(menu);  // 调用基础Mapper
    }
}
```

**调用链**:
```
UmsMenuController.update()
  → UmsMenuServiceImpl.update()
    → UmsMenuMapper.updateByPrimaryKeySelective() [MBG生成]
      → SQL: UPDATE ums_menu SET ... WHERE id = #{id}
```

#### 模式2: Controller → Service → Dao (复杂查询)

```java
// Controller
@RestController
@RequestMapping("/order")
public class OmsOrderController {
    @Autowired
    private OmsOrderService orderService;
    
    @GetMapping("/list")
    public CommonResult list(OmsOrderQueryParam queryParam) {
        List<OmsOrder> orders = orderService.list(queryParam, pageSize, pageNum);
        return CommonResult.success(orders);
    }
}

// Service实现
@Service
public class OmsOrderServiceImpl implements OmsOrderService {
    @Autowired
    private OmsOrderDao orderDao;  // ⚠️ 注入的是自定义DAO
    
    @Override
    public List<OmsOrder> list(OmsOrderQueryParam queryParam, Integer pageSize, Integer pageNum) {
        PageHelper.startPage(pageNum, pageSize);
        return orderDao.getList(queryParam);  // 调用自定义DAO
    }
}
```

**调用链**:
```
OmsOrderController.list()
  → OmsOrderServiceImpl.list()
    → OmsOrderDao.getList() [自定义DAO]
      → SQL: SELECT * FROM oms_order WHERE ... (动态SQL)
```

#### 模式3: Service同时使用Mapper和Dao

```java
@Service
public class OmsOrderServiceImpl implements OmsOrderService {
    @Autowired
    private OmsOrderMapper orderMapper;       // MBG生成的基础Mapper
    @Autowired
    private OmsOrderDao orderDao;             // 自定义DAO
    @Autowired
    private OmsOrderOperateHistoryDao historyDao;
    
    @Override
    public int delivery(List<OmsOrderDeliveryParam> deliveryParamList) {
        // 1. 调用自定义DAO批量发货
        int count = orderDao.delivery(deliveryParamList);
        
        // 2. 添加操作记录（使用另一个DAO）
        List<OmsOrderOperateHistory> historyList = ...;
        historyDao.insertList(historyList);
        
        return count;
    }
}
```

**调用链**:
```
OmsOrderServiceImpl.delivery()
  ├─→ OmsOrderDao.delivery()
  │     → SQL: UPDATE oms_order SET delivery_sn = CASE ... (复杂UPDATE)
  └─→ OmsOrderOperateHistoryDao.insertList()
        → SQL: INSERT INTO oms_order_operate_history VALUES ...
```

---

## 三、关键技术挑战

### 3.1 接口-实现类映射问题 ⚠️ **核心挑战**

#### 问题场景

```java
// Service接口
public interface UmsMenuService {
    int updateHidden(Long id, Integer hidden);
}

// Service实现
@Service
public class UmsMenuServiceImpl implements UmsMenuService {
    @Autowired
    private UmsMenuMapper menuMapper;
    
    @Override
    public int updateHidden(Long id, Integer hidden) {
        UmsMenu menu = new UmsMenu();
        menu.setId(id);
        menu.setHidden(hidden);
        return menuMapper.updateByPrimaryKeySelective(menu);  // 实际调用在这里
    }
}

// Controller调用
@RestController
public class UmsMenuController {
    @Autowired
    private UmsMenuService menuService;  // ⚠️ 注入的是接口
    
    @PostMapping("/updateHidden")
    public CommonResult updateHidden(@RequestParam Long id, @RequestParam Integer hidden) {
        int count = menuService.updateHidden(id, hidden);  // 静态分析看到的是接口
        return count > 0 ? CommonResult.success() : CommonResult.failed();
    }
}
```

#### 影响分析

**向上分析** (谁调用了变更方法):
- 如果 `UmsMenuServiceImpl.updateHidden` 被修改
- 需要找到所有调用 `UmsMenuService.updateHidden` (接口) 的地方
- **必须通过CHA解析**: `UmsMenuService` → `UmsMenuServiceImpl`
- 然后才能追溯到 `UmsMenuController.updateHidden`

**向下分析** (变更方法调用了谁):
- 如果从 `UmsMenuService.updateHidden` (接口) 开始分析
- 接口中没有方法体，无法直接分析
- **必须通过CHA找到实现类**: `UmsMenuServiceImpl.updateHidden`
- 然后才能分析它调用了 `UmsMenuMapper.updateByPrimaryKeySelective`
- 最终追踪到 SQL 语句

#### 解决方案需求

1. **CHA必须启用且正确工作**
2. **向下分析时自动展开接口实现**
3. **支持多实现类场景** (虽然mall项目中通常是单一实现)

### 3.2 XML文件位置分散问题

**当前分布**:
```
mall-mbg/src/main/resources/com/macro/mall/mapper/*.xml  (80+ files)
mall-admin/src/main/resources/dao/*.xml                  (22 files)
mall-portal/src/main/resources/dao/*.xml                 (15 files)
mall-search/src/main/resources/dao/*.xml                 (5 files)
```

**扫描策略需求**:
```python
search_patterns = [
    '**/*Mapper.xml',      # 匹配 MBG 生成的 Mapper
    '**/dao/**/*.xml',     # 匹配自定义 DAO
    '**/mapper/**/*.xml',  # 备用模式
]
```

### 3.3 动态SQL解析挑战

**复杂动态SQL示例** (OmsOrderDao.xml):

```xml
<update id="delivery">
    UPDATE oms_order
    SET
    delivery_sn = CASE id
    <foreach collection="list" item="item">
        WHEN #{item.orderId} THEN #{item.deliverySn}
    </foreach>
    END,
    delivery_company = CASE id
    <foreach collection="list" item="item">
        WHEN #{item.orderId} THEN #{item.deliveryCompany}
    </foreach>
    END,
    `status` = CASE id
    <foreach collection="list" item="item">
        WHEN #{item.orderId} THEN 2
    </foreach>
    END
    WHERE id IN
    <foreach collection="list" item="item" separator="," open="(" close=")">
        #{item.orderId}
    </foreach>
    AND `status` = 1
</update>
```

**解析难点**:
1. `<foreach>` 标签嵌套
2. `CASE WHEN` 动态语句
3. 表名提取需要考虑动态部分

**当前mapper_parse.py的能力**:
- ✅ 已使用 `xml.etree.ElementTree` 解析
- ✅ 支持递归提取文本内容
- ✅ 可以处理嵌套标签
- ⚠️ 需要增强表名提取逻辑（考虑动态SQL）

### 3.4 Namespace与Java包名的映射

**观察到的模式**:

| XML Namespace | Java接口位置 | 说明 |
|--------------|-------------|------|
| `com.macro.mall.mapper.UmsMenuMapper` | `mall-mbg/.../mapper/UmsMenuMapper.java` | MBG生成 |
| `com.macro.mall.dao.OmsOrderDao` | `mall-admin/.../dao/OmsOrderDao.java` | 自定义DAO |

**关联策略**:
```python
# 通过namespace直接定位Java接口
namespace = "com.macro.mall.mapper.UmsMenuMapper"
package_class = namespace  # 完全一致！

# 验证方法存在
method_exists = db.query(
    "SELECT method_id FROM methods m JOIN class c ON m.class_id = c.class_id "
    "WHERE c.package_name || '.' || c.class_name = ? AND m.method_name = ?",
    (package_class, method_id)
)
```

---

## 四、实际测试用例设计

### 4.1 推荐测试场景

基于diff文件 `diff_78e3a22..505908c.txt` 中的实际变更：

#### 测试场景1: 删除测试方法的影响面分析

**变更内容**:
```diff
- 删除了 UmsMenuController.batchUpdateHidden() 方法
- 删除了 UmsMenuServiceImpl.batchUpdateHidden() 方法
```

**预期向上分析结果**:
```
🔴 删除方法影响分析:

1. UmsMenuServiceImpl.batchUpdateHidden [DELETED]
   ⚠️ 严重性: CRITICAL
   📞 直接调用方 (1个):
      - UmsMenuController.batchUpdateHidden [DELETED]
   🎯 影响入口点:
      - 无（该方法也被删除）

2. UmsMenuController.batchUpdateHidden [DELETED]
   ⚠️ 严重性: LOW（仅删除API端点）
```

**预期向下分析结果**:
```
向下调用链 (已删除，无需分析):
  UmsMenuServiceImpl.batchUpdateHidden [DELETED]
    --> UmsMenuServiceImpl.updateHidden (UNCHANGED)
      --> UmsMenuMapper.updateByPrimaryKeySelective (UNCHANGED)
        --> SQL:UPDATE [表: ums_menu]
          SQL: UPDATE ums_menu SET hidden = #{hidden} WHERE id = #{id}
          📝 影响表: ums_menu
          🔍 操作类型: UPDATE
```

#### 测试场景2: 订单管理的完整链路追踪

**选择方法**: `OmsOrderController.delivery()`

**预期向下分析结果**:
```
向下调用链 1: OmsOrderController.delivery

OmsOrderController.delivery (UNCHANGED)
  --> OmsOrderService.delivery (接口调用)
    --> OmsOrderServiceImpl.delivery (UNCHANGED) [CHA_RESOLVED]
      --> OmsOrderDao.delivery (UNCHANGED)
        --> SQL:UPDATE [表: oms_order]
          SQL: UPDATE oms_order SET delivery_sn = CASE id ..., status = CASE id ...
          📝 影响表: oms_order
          🔍 操作类型: UPDATE (批量)
          ⚠️ 风险: 批量更新订单状态，需确认事务一致性
      
      --> OmsOrderOperateHistoryDao.insertList (UNCHANGED)
        --> SQL:INSERT [表: oms_order_operate_history]
          SQL: INSERT INTO oms_order_operate_history VALUES ...
          📝 影响表: oms_order_operate_history
          🔍 操作类型: INSERT
```

### 4.2 验证要点清单

#### 基础功能验证
- [ ] Mapper XML 文件扫描完整性（应找到 130+ 个XML）
- [ ] SQL 语句解析准确性（至少解析 1000+ 个SQL）
- [ ] 表名提取正确性（特别是动态SQL）
- [ ] Java方法与XML语句关联成功率（目标 > 95%）

#### CHA集成验证
- [ ] 接口方法能正确找到实现类
- [ ] 向下分析从接口开始时能自动展开实现
- [ ] 向上分析能追溯到接口调用方

#### 性能验证
- [ ] XML 解析时间 < 30秒（130个文件）
- [ ] 索引构建时间 < 10秒
- [ ] 单次查询响应时间 < 100ms

#### 输出质量验证
- [ ] SQL 节点显示清晰（类型、表名、风险提示）
- [ ] 调用链层级正确（Controller → Service → Mapper/Dao → SQL）
- [ ] 行号信息准确（用于代码定位）

---

## 五、实施方案调整建议

基于mall项目的实际情况，对原实施方案进行以下调整：

### 5.1 优先级调整

| 阶段 | 原优先级 | 调整后优先级 | 原因 |
|------|---------|------------|------|
| 数据库扩展 | P0 | P0 | 不变 |
| Mapper解析器增强 | P0 | P0 | 不变 |
| Mapper索引构建 | P1 | **P0** | ⬆️ 核心功能，必须首先实现 |
| DAO分析器 | P1 | **P0** | ⬆️ 与索引构建同等重要 |
| 向下调用链集成 | P2 | **P1** | ⬆️ 提前集成以验证效果 |
| Workflow集成 | P2 | P2 | 不变 |
| CHA接口展开 | 未明确 | **P0** | ⬆️ mall项目中大量使用接口注入 |

### 5.2 新增需求

#### 需求1: 支持两种Mapper路径模式

```python
# 修改 mapper_index.py 中的扫描逻辑
def _scan_mapper_xml_files(self) -> List[str]:
    """扫描项目中的 Mapper XML 文件（支持mall项目结构）"""
    xml_files = []
    
    # 模式1: MBG生成的Mapper (mall-mbg)
    mbg_pattern = os.path.join(self.source_dir, '**/mall-mbg/**/*Mapper.xml')
    xml_files.extend(glob.glob(mbg_pattern, recursive=True))
    
    # 模式2: 自定义DAO (各模块的dao目录)
    dao_pattern = os.path.join(self.source_dir, '**/dao/**/*.xml')
    xml_files.extend(glob.glob(dao_pattern, recursive=True))
    
    # 模式3: 通用匹配（兜底）
    general_pattern = os.path.join(self.source_dir, '**/*Mapper.xml')
    xml_files.extend(glob.glob(general_pattern, recursive=True))
    
    return list(set(xml_files))
```

#### 需求2: 增强动态SQL的表名提取

```python
# 修改 mapper_parse.py 中的 extract_tables_from_sql
def extract_tables_from_sql(sql_text: str) -> List[str]:
    """从 SQL 文本中提取表名（增强版，支持动态SQL）"""
    if not sql_text:
        return []
    
    # 清理动态SQL标签，保留纯SQL
    cleaned_sql = re.sub(r'<[^>]+>', ' ', sql_text)  # 移除XML标签
    
    # 匹配表名
    patterns = [
        r'(?:FROM|INTO)\s+[`"\']?(\w+)[`"\']?',
        r'(?:UPDATE)\s+[`"\']?(\w+)[`"\']?',
        r'(?:JOIN)\s+[`"\']?(\w+)[`"\']?\s+(?:ON|USING)',
    ]
    
    tables = set()
    for pattern in patterns:
        matches = re.findall(pattern, cleaned_sql, re.IGNORECASE)
        tables.update(matches)
    
    # 过滤关键字
    keywords = {'SELECT', 'WHERE', 'AND', 'OR', 'SET', 'VALUES', 'GROUP', 'ORDER', 
                'CASE', 'WHEN', 'THEN', 'END', 'IF'}
    tables = {t for t in tables if t.upper() not in keywords}
    
    return sorted(list(tables))
```

#### 需求3: CHA在向下分析中的强制应用

```python
# 修改 analyzer.py 中的向下分析部分
def build_downwards_call_chains(...):
    """构建向下调用链（强制CHA支持）"""
    
    downwards_chains = []
    
    for method_info in methods_to_analyze:
        package_class = method_info['class_name']
        method_signature = method_info['method_signature']
        
        # 检查是否为接口或抽象类
        is_interface = class_hierarchy and \
                      class_hierarchy.is_interface_or_abstract_class(package_class)
        
        if is_interface:
            logger.info(f"检测到接口方法: {package_class}.{method_signature}")
            
            # 通过CHA找到所有实现类
            impl_methods = class_hierarchy.resolve_interface_call(
                package_class, method_signature
            )
            
            if impl_methods:
                logger.info(f"  找到 {len(impl_methods)} 个实现类:")
                for impl in impl_methods:
                    logger.info(f"    - {impl['package_class']}")
                
                # 对每个实现类构建调用链
                for impl in impl_methods:
                    root_node = downwards_builder.build(
                        impl['package_class'],
                        impl['method_signature']
                    )
                    
                    # 标记为CHA解析
                    root_node.cha_resolved = True
                    root_node.original_interface = package_class
                    
                    downwards_chains.append(root_node)
            else:
                logger.warning(f"  ⚠️ 未找到实现类，按普通方法处理")
                root_node = downwards_builder.build(package_class, method_signature)
                downwards_chains.append(root_node)
        else:
            # 非接口方法，直接构建
            root_node = downwards_builder.build(package_class, method_signature)
            downwards_chains.append(root_node)
    
    return downwards_chains
```

### 5.3 数据库表结构调整

```sql
-- 新增字段：区分MBG Mapper和自定义DAO
ALTER TABLE mapper_methods ADD COLUMN mapper_type TEXT DEFAULT 'CUSTOM';
-- 值: 'MBG' (MyBatis Generator生成) 或 'CUSTOM' (自定义DAO)

-- 新增字段：记录是否为动态SQL
ALTER TABLE mapper_methods ADD COLUMN is_dynamic_sql INTEGER DEFAULT 0;
-- 1 = 包含 <if>, <foreach> 等动态标签

-- 新增索引：加速类型查询
CREATE INDEX idx_mapper_type ON mapper_methods(mapper_type);
```

---

## 六、实施路线图

### 第一阶段：基础架构（2天）

**Day 1**:
- [ ] 创建数据库迁移脚本
- [ ] 执行表结构变更
- [ ] 验证新表创建成功

**Day 2**:
- [ ] 增强 `mapper_parse.py`（动态SQL支持）
- [ ] 创建 `mapper_index.py`（双路径扫描）
- [ ] 单元测试：解析10个XML文件验证准确性

### 第二阶段：核心功能（2天）

**Day 3**:
- [ ] 创建 `dao_analyzer.py`
- [ ] 实现SQL风险评估逻辑
- [ ] 单元测试：分析5个Mapper方法

**Day 4**:
- [ ] 增强 `ClassHierarchyIndex`（确保CHA工作）
- [ ] 修改 `DownwardsCallChainBuilder`（集成DAO分析器）
- [ ] 实现接口自动展开逻辑

### 第三阶段：集成测试（1.5天）

**Day 5上午**:
- [ ] 修改 `analyzer.py`（传递CHA和DAO分析器）
- [ ] 修改 `workflow1.py` 和 `workflow2.py`

**Day 5下午**:
- [ ] 运行完整分析流程（使用mall项目）
- [ ] 验证输出格式和内容

**Day 6上午**:
- [ ] 修复发现的问题
- [ ] 性能优化

### 第四阶段：验证与文档（0.5天）

**Day 6下午**:
- [ ] 编写测试报告
- [ ] 更新技术文档
- [ ] 准备演示材料

---

## 七、风险与应对

### 风险1: XML解析失败率高

**原因**: 
- 某些XML文件格式不规范
- 命名空间声明缺失

**应对**:
- 增加容错机制，单个文件失败不影响整体
- 记录详细错误日志
- 提供手动修复指南

### 风险2: CHA解析不准确

**原因**:
- 数据库中 `implements` 字段可能为空
- 继承关系复杂

**应对**:
- 优先使用AST解析获取implements信息
-  fallback到启发式规则（类名后缀判断）
- 提供手动配置接口

### 风险3: 性能问题

**原因**:
- XML文件数量多（130+）
- SQL解析复杂

**应对**:
- 实现增量解析（只解析变更的XML）
- 缓存解析结果
- 并行解析（多线程）

---

## 八、成功标准

### 功能性标准
- ✅ 能解析mall项目中 95% 以上的 Mapper XML
- ✅ 能正确关联 90% 以上的 Java方法与SQL语句
- ✅ CHA能正确解析 95% 以上的接口-实现类关系
- ✅ 向下分析能展示完整的 SQL 级别调用链

### 性能标准
- ✅ XML解析总时间 < 30秒
- ✅ 索引构建时间 < 10秒
- ✅ 单次调用链查询 < 100ms

### 质量标准
- ✅ SQL节点信息完整（类型、表名、风险提示）
- ✅ 调用链层级清晰（最多5层：Controller → Service → Impl → Mapper → SQL）
- ✅ 无明显误报或漏报

---

**文档版本**: v1.0  
**创建日期**: 2026-05-11  
**作者**: Lingma AI Assistant  
**下一步**: 开始第一阶段实施（数据库扩展）
