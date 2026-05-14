# JCCI Streamlit Web应用配置文件
# 请勿将此文件提交到版本控制系统

# LLM API配置
LLM_API_URL = "https://openai.good.hidns.vip/v1"
LLM_API_KEY = "sk-B882bCwUweSeMRscoNwxZw4vxpjXmvWTLBxO5aXC7WAYhfwa"
LLM_MODEL = "moonshotai/kimi-k2.6"

# 使用统一路径管理模块
from jcci.utils.path_utils import (
    RESULT_DIR,
    TASK_MANAGER_DB_PATH as DB_PATH,
)

# Streamlit服务配置
STREAMLIT_PORT = 8501
STREAMLIT_HOST = "0.0.0.0"  # 允许外部访问
