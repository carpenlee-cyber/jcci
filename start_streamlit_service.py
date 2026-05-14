#!/usr/bin/env python
"""
JCCI Streamlit 服务启动脚本

用法:
    python start_streamlit_service.py [--host HOST] [--port PORT]

示例:
    python start_streamlit_service.py --host 0.0.0.0 --port 8501
"""

import os
import sys
import argparse
import subprocess

def main():
    parser = argparse.ArgumentParser(description='启动 JCCI Streamlit 服务')
    parser.add_argument('--host', default='0.0.0.0', help='监听地址 (默认: 0.0.0.0)')
    parser.add_argument('--port', type=int, default=8501, help='监听端口 (默认: 8501)')
    
    args = parser.parse_args()
    
    # 获取当前脚本所在目录
    script_dir = os.path.dirname(os.path.abspath(__file__))
    # streamlit_app.py 在 webapp/ 目录下
    streamlit_app = os.path.join(script_dir, 'webapp', 'streamlit_app.py')
    
    if not os.path.exists(streamlit_app):
        print(f"❌ 错误: 找不到 streamlit_app.py: {streamlit_app}")
        sys.exit(1)
    
    print("=" * 80)
    print("🚀 启动 JCCI Streamlit 服务")
    print("=" * 80)
    print(f"📍 服务地址: http://{args.host}:{args.port}")
    print(f"📁 应用路径: {streamlit_app}")
    print("=" * 80)
    print()
    print("💡 提示:")
    print("按 Ctrl+C 停止服务")
    print("=" * 80)
    print()
    
    # 切换到 streamlit_app.py 所在目录，确保相对导入正常工作
    app_dir = os.path.dirname(streamlit_app)
    os.chdir(app_dir)
    print(f"📂 工作目录: {app_dir}")
    
    # 将项目根目录添加到 PYTHONPATH 环境变量，确保 Streamlit 子进程可以导入 jcci 模块
    project_root = script_dir  # jcci/ 目录就是项目根目录
    current_pythonpath = os.environ.get('PYTHONPATH', '')
    if project_root not in current_pythonpath:
        if current_pythonpath:
            os.environ['PYTHONPATH'] = f"{project_root}{os.pathsep}{current_pythonpath}"
        else:
            os.environ['PYTHONPATH'] = project_root
    print(f"📦 PYTHONPATH 已设置: {os.environ['PYTHONPATH']}")
    print()
    
    # 启动 Streamlit
    try:
        subprocess.run([
            sys.executable, '-m', 'streamlit', 'run',
            streamlit_app,
            '--server.address', args.host,
            '--server.port', str(args.port),
            '--server.headless', 'true',
            '--browser.gatherUsageStats', 'false',
            '--server.fileWatcherType', 'none'  # 禁用文件监控，避免跨驱动器路径错误
        ])
    except KeyboardInterrupt:
        print("\n\n✅ 服务已停止")
    except Exception as e:
        print(f"\n❌ 启动失败: {e}")
        sys.exit(1)

if __name__ == '__main__':
    main()
