"""
JCCI 主入口程序

使用方法:
    python main.py

或者直接在代码中配置参数后运行
"""

import sys
import os

# 添加项目根目录到 Python 路径
project_root = os.path.abspath(os.path.dirname(__file__))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from backend.app.core.workflow1 import workflow1


def main():
    """
    主函数 - 调用 workflow1 进行双向调用链路分析
    
    可以根据需要修改以下参数
    """
    
    # ===== 必需参数配置 =====
    
    # Git仓库地址
    git_url = 'https://github.com/carpenlee-cyber/mall.git'
    
    # GitHub用户名
    username = 'carpenlee-cyber'
    
    # 方式1：使用tag
    tag_old = 'baseline_20260508_01'
    tag_new = 'baseline_fix1_20260508_02'
    
    # # 方式2：使用commit hash（用于开发测试）
    # tag_old = 'dd6569c3558f79af5b21aad601349e0f029b9a6d'
    # tag_new = 'dd94f3b4b317e604eee9b96252160e1a5c69785d'    
    
    
    # ===== 可选参数配置 =====
    
    # 调用链最大深度（默认5）
    max_depth = 10
    
    # 是否启动Streamlit Web服务（默认True）
    enable_streamlit = False
    
    # Streamlit服务端口（默认8501）
    streamlit_port = 8501
    
    # Streamlit服务主机（默认0.0.0.0）
    streamlit_host = "0.0.0.0"
    
    # 是否自动打开浏览器（默认True）
    auto_open_browser = True
    
    # 日志级别（默认INFO，可选DEBUG/INFO/WARNING/ERROR）
    log_level = "INFO"
    
    # ===== 执行工作流 =====
    
    print("=" * 80)
    print("JCCI - Java Code Change Impact Analysis")
    print("=" * 80)
    print(f"Git仓库: {git_url}")
    print(f"用户名: {username}")
    print(f"基线版本: {tag_old}")
    print(f"当前版本: {tag_new}")
    print("=" * 80)
    print()
    
    try:
        result = workflow1(
            git_url=git_url,
            username=username,
            tag_old=tag_old,
            tag_new=tag_new,
            max_depth=max_depth,
            enable_streamlit=enable_streamlit,
            streamlit_port=streamlit_port,
            streamlit_host=streamlit_host,
            auto_open_browser=auto_open_browser,
            log_level=log_level,
            user_ip="",
            user_name="网页",
            user_id="web",
            project_code="",
            task_stage=""
        )
        
        print("\n" + "=" * 80)
        print("分析完成！")
        print("=" * 80)
        
    except Exception as e:
        print(f"\n❌ 错误: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
