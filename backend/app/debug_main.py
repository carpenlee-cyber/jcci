#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
调试启动脚本 - debug_main.py
专门用于调试模式的FastAPI应用启动
"""

import os
import sys
import uvicorn
from pathlib import Path

# 设置环境变量启用调试模式
os.environ['DEBUG'] = 'True'

# 添加项目路径到sys.path
project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

def start_debug_server():
    """启动调试服务器"""

    # 调试配置 - 使用导入字符串方式启用热重载
    debug_config = {
        'host': '0.0.0.0',
        'port': 8000,
        'reload': True,  # 启用代码热重载
        'reload_dirs': [str(project_root / 'app')],  # 监控app目录的变化
        'log_level': 'debug',  # 详细日志
        'access_log': True,    # 启用访问日志
    }

    print("=" * 60)
    print("🚀 PipelineAnalysisV3 调试模式启动")
    print("=" * 60)
    print(f"📡 服务地址: http://{debug_config['host']}:{debug_config['port']}")
    print(f"🔧 调试模式: 已启用")
    print(f"🔄 热重载: 已启用")
    print(f"📝 日志级别: {debug_config['log_level']}")
    print("=" * 60)
    print("💡 调试提示:")
    print("• 在PyCharm中设置断点后访问API端点触发调试")
    print("• 修改代码后会自动重载")
    print("• 查看控制台输出获取详细日志")
    print("=" * 60)

    # 使用导入字符串方式启动服务器（支持热重载）
    uvicorn.run("main:app", **debug_config)

if __name__ == "__main__":
    try:
        start_debug_server()
    except KeyboardInterrupt:
        print("\n👋 调试服务器已停止")
    except Exception as e:
        print(f"❌ 启动调试服务器时发生错误: {e}")
        print("💡 检查依赖是否安装: pip install -r requirements.txt")
        sys.exit(1)