# JCCI Streamlit Web应用配置文件
# 请勿将此文件提交到版本控制系统
import os

# LLM API配置
LLM_API_URL = "https://openai.good.hidns.vip/v1"
LLM_API_KEY = "sk-B882bCwUweSeMRscoNwxZw4vxpjXmvWTLBxO5aXC7WAYhfwa"
LLM_MODEL = "moonshotai/kimi-k2.6"

# task_manage 数据库路径（相对于 webapp 目录）
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "task_manager.db")

# 分析结果目录（相对于项目根目录）
RESULT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "jcci", "analyze_result")

# Streamlit服务配置
STREAMLIT_PORT = 8501
STREAMLIT_HOST = "0.0.0.0"  # 允许外部访问
