![Visitors](https://api.visitorbadge.io/api/visitors?path=https%3A%2F%2Fgithub.com%2Fbaikaishuipp%2Fjcci&countColor=%23263759)
![PyPI Downloads](https://static.pepy.tech/badge/jcci)

### [English Doc](https://github.com/baikaishuipp/jcci/blob/main/README.en.md)

# jcci

### 介绍
Java代码提交影响分析，是一个纯python库，分析Java项目的两次git提交差异对项目的影响，并生成树形图数据。

**v2.0 新特性**: 引入**基线增量分析策略**，显著提升重复分析场景下的性能，支持基线复用和增量解析。

PYPI: [jcci](https://pypi.org/project/jcci/) （会落后github几个版本）

### 实现效果
![效果图](./images/cii-result-tree.png)

### 软件架构
大致原理同Idea的Find Usage一致，通过代码改动定位代码影响，并不断遍历受影响的类和方法直至找到最上层的controller层

代码主要由python编写，主要涉及2个库：

* javalang java文件语法解析库
* unidiff git diff信息解析库

通过javalang语法解析获取每个Java文件的import class extends implements declarators methods 等信息

通过unidiff 解析git diff信息（diff file, added_line_num, removed_lin_num)

然后根据文件增删的代码行去判断影响了哪些类和方法，不断遍历受影响的类和方法直至找到最上层的controller层

通过传入项目git地址 分支 两次的commit id，即可分析出两次commit id之间代码改动所带来的影响，并生成树图数据方便展示影响链路。

### 安装教程
要求python >= 3.9 , sqlite3 >= 3.38

### 基线增量分析策略（v2.0）

#### 核心特性
本项目实现了**"以基线为中心的增量分析策略"**，显著提升代码变更影响分析的性能和效率。

#### 架构设计
1. **数据库管理**:
   - **命名规范**: `{username}_{project_name}_baseline_{commit_short}.db`
   - **存储位置**: `config.db_path` 目录
   - **数据隔离**: 不同基线使用独立数据库文件
   - **Commit ID 截断**: 使用前7位短哈希 (`commit_id[0:7]`)

2. **Project ID 分配规则**:

| 提交类型 | 角色 | 解析范围 | Project ID |
|---------|------|---------|-----------|
| `commit_old` | 基线 (Baseline) | 全量解析 (Full Scan) | **固定为 0** |
| `commit_new1` | 变更 1 (Delta 1) | 增量解析 (Diff Scan) | **1** (自动生成) |
| `commit_new2` | 变更 2 (Delta 2) | 增量解析 (Diff Scan) | **2** (自增) |

#### 三种执行场景
1. **场景 A：首次运行（基线初始化）**
   - **触发条件**: 基线数据库不存在
   - **执行步骤**:
     1. 创建基线数据库文件
     2. 全量解析 `commit_old` → `project_id = 0`
     3. 计算 `git diff (commit_old..commit_new)`
     4. 增量解析变更文件 → `project_id = 1`
     5. 记录分析到 project 表

2. **场景 B：重复运行（相同参数）**
   - **触发条件**: `_check_duplicate_analysis` 检测到已有记录
   - **处理方式**: 直接退出，避免重复计算

3. **场景 C：再次运行（相同基线，新提交）**
   - **触发条件**: 基线存在但 `commit_new` 不同
   - **执行步骤**:
     1. 复用基线数据（跳过全量解析）
     2. 计算新 diff，增量解析变更文件
     3. 使用 `_get_next_project_id()` 分配新 ID
     4. 记录分析结果

#### 使用方法
```python
from jcci import JCCI

# 初始化 JCCI 实例
jcci = JCCI('https://github.com/your-repo.git', 'username')

# 【推荐】基线增量分析策略
# commit_new: 新的提交ID, commit_old: 基线提交ID
jcci.analyze_two_commit_incremental('commit_new', 'commit_old')
```

#### 核心优势
- ✅ **存储高效**: 多个 `commit_new` 共享同一个 `commit_old` 的基线数据
- ✅ **结构清晰**: `project_id = 0` 快速索引基线，`project_id > 0` 索引差异分析
- ✅ **计算优化**: 利用 `git diff --name-only` 仅处理变更文件
- ✅ **数据隔离**: 不同基线使用独立数据库文件
- ✅ **自动去重**: 检测重复分析，避免冗余计算

#### 性能对比
| 分析方式 | 首次分析 | 第二次分析 | 第三次分析 |
|---------|---------|-----------|-----------|
| 传统方式 | ~60秒 | ~60秒 | ~60秒 |
| 基线增量 | ~60秒 | ~10秒 | ~10秒 |

*(注: 实际时间取决于项目规模和变更文件数量)*

---

### 传统使用说明
项目克隆下来后，新建python文件，引入jcci项目src目录下的jcci
```python
from path.to.jcci.src.jcci.analyze import JCCI

# 同一分支不同commit分析
commit_analyze = JCCI('git@xxxx.git', 'username1')
commit_analyze.analyze_two_commit('master','commit_id1','commit_id2')

# 分析一个类的方法影响, analyze_class_method方法最后参数为方法所在行数，不同方法行数用逗号分割，不填则分析完整类影响
class_analyze = JCCI('git@xxxx.git', 'username1')
class_analyze.analyze_class_method('master','commit_id1', 'package\src\main\java\ClassA.java', '20,81')

# 不同分支分析
branch_analyze = JCCI('git@xxxx.git', 'username1')
branch_analyze.analyze_two_branch('branch_new','branch_old')

# 多项目联合分析，上述三种方法都支持，以analyze_two_commit方法举例
dependents = [
    {
        'git_url': 'git@xxxx.git',
        'branch': 'master',  # default master when empty
        'commit_id': 'HEAD'  # default HEAD when empty
    }
]
commit_analyze = JCCI('git@xxxx.git', 'username1')
commit_analyze.analyze_two_commit('master','commit_id1','commit_id2', dependents=dependents)
```
#### 参数说明：
* project_git_url - 项目git地址，代码使用本机git配置clone代码，确保本机git权限或通过用户名密码/token的方式拼接url来clone代码。示例：https://userName:password@github.com/xxx.git 或 https://token@github.com/xxx.git
* username1 - 随便输入，为了避免并发分析同一项目导致结果错误，用户1分析项目A时，用户B需要等待，所以设置了该参数

运行时，会将项目克隆到目录中，然后进行分析，生成后缀格式为.cci的文件，其中包含分析结果生成的关系图数据，下载[jcci-result.html](https://github.com/baikaishuipp/jcci/blob/main/jcci-result.html) ，选择分析结果的.cci文件，即可可通过视图显示。

### 安全性
项目分析都是基于本地环境执行，无任何代码收集和日志上报，源码可查，请放心使用。

### 开源不易，如本工具对您有帮助，请点一下右上角 star ⭐

### 谁在使用
如果您在使用JCCI，请让我们知道，您的使用对我们非常重要：[登记链接](#33) （按登记顺序排列）
<table>
<tr>
<td>
    <a href="https://www.hand-china.com/">
    <img src="https://www.hand-china.com/static/img/logos.png" alt="Hand-china" width="200" height="100"/>
</td>
<td>
    <a href="https://www.sf-tech.com.cn/">
    <img src="https://p6.itc.cn/q_70/images03/20220901/83f2548ac61e484ca1f7db3d30509b7b.jpeg" alt="sf-tech" width="200" height=""/>
</td>
<td>
    <a href="https://www.dazhenyun.cn/">
    <img src="https://image0.lietou-static.com/bg_white_222x222/5ef17aa2f3eec46a32352c0107u.png" alt="dazhenyun" width="200" height=""/>
</td>
</tr>
</table>

### 沟通交流
扫码加微信，备注：JCCI微信群交流，或者扫码加入钉钉交流群

![微信交流群](./images/wechat.jpg) ![钉钉交流群](./images/jcci_dingding.jpg) 

### 鸣谢
感谢一下同学请作者喝咖啡、提供意见或反馈Bug, 排名不分先后
[zouchengli](https://github.com/zouchengli) 

### Star History

[![Star History Chart](https://api.star-history.com/svg?repos=baikaishuipp/jcci&type=Date)](https://star-history.com/#baikaishuipp/jcci&Date)
