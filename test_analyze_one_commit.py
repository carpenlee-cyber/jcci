import sys
import os

# 添加 src 目录到模块搜索路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from jcci import JCCI


def demo_analyze_one_commit():
    """
    演示如何使用analyze_one_commit功能
    """
    print("开始演示analyze_one_commit功能...")
    
    # 创建JCCI实例
    # 注意：这里使用本地仓库路径而非远程仓库，避免网络问题
    # 你需要确保本地存在一个git仓库用于测试
    commit_analyze = JCCI('https://github.com/carpenlee-cyber/mall.git', 'carpenlee-cyber')
    
    # 调用analyze_one_commit方法分析指定的commit
    # 这将下载指定commit的完整代码并将其存储到数据库中
    print("正在分析单个commit d9501e9...")
    try:
        commit_analyze.analyze_one_commit('d9501e9')
        print("分析完成！")
    except Exception as e:
        print(f"分析过程中发生错误: {e}")
        print("请确保:")
        print("- 本地存在对应的git仓库")
        print("- 提交ID 'd9501e9' 存在于仓库中")
        print("- 网络连接正常")


if __name__ == "__main__":
    demo_analyze_one_commit()