# JCCI Streamlit Web应用配置文件
# 请勿将此文件提交到版本控制系统

# LLM API配置
LLM_API_URL = "https://openai.good.hidns.vip/v1"
LLM_API_KEY = "sk-B882bCwUweSeMRscoNwxZw4vxpjXmvWTLBxO5aXC7WAYhfwa"
# LLM_MODEL = "minimaxai/minimax-m2.7"
LLM_MODEL = "moonshotai/kimi-k2.6"

# 使用统一路径管理模块
from jcci.utils.path_utils import (
    RESULT_DIR,
    TASK_MANAGER_DB_PATH as DB_PATH,
)

# Streamlit服务配置
STREAMLIT_PORT = 8501
STREAMLIT_HOST = "0.0.0.0"  # 允许外部访问

# 外部访问URL（可选）
# 如果设置了此值，任务完成后的访问链接将使用此URL
# 例如: "http://192.168.1.100:8501" 或 "https://jcci.example.com"
# 如果未设置，将自动使用 STREAMLIT_HOST:STREAMLIT_PORT
STREAMLIT_EXTERNAL_URL = "http://127.0.0.1:8501"  # 例如: "http://your-server-ip:8501"
