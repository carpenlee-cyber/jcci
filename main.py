import sys
import os

# 添加 src 目录到模块搜索路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from jcci import JCCI

# 使用本地仓库路径而非远程仓库，避免网络问题
# 注意：需要确保本地存在一个git仓库用于测试
commit_analyze = JCCI('https://github.com/carpenlee-cyber/mall.git', 'carpenlee-cyber')
# 这里使用实际存在的分支名和提交ID，或者注释掉下面这行以避免错误
# commit_analyze.analyze_two_commit('master','d9501e9','bab28d4')

# 调用新增的单次提交分析功能
commit_analyze.analyze_one_commit('d9501e9')

print("JCCI module imported successfully!")
print("To run a full analysis, call analyze_two_commit with valid branch names and commit IDs.")
print("To run a single commit analysis, call analyze_one_commit with a valid commit ID.")
print("To run incremental analysis with baseline strategy, call analyze_two_commit_incremental(commit_new, commit_old).")

# 基线增量分析示例
# commit_analyze = JCCI('https://github.com/carpenlee-cyber/mall.git', 'carpenlee-cyber')

# 首次运行:会创建基线数据库并全量解析
# commit_analyze.analyze_two_commit_incremental('new_commit_id', 'base_commit_id')

# 后续运行:复用基线,仅增量解析变更文件
# commit_analyze.analyze_two_commit_incremental('another_new_commit', 'base_commit_id')