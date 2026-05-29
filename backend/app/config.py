"""
FastAPI 应用配置
"""
import os
import sys
from pathlib import Path
from pydantic_settings import BaseSettings

# 确保 jcci 包可导入
_project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from jcci.utils.path_utils import RESULT_DIR as JCCI_RESULT_DIR


class Settings(BaseSettings):
    """应用配置"""
    
    # 应用基本信息
    APP_NAME: str = "JCCI Analysis Platform"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = True
    
    # 服务器配置
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    
    # 数据库配置
    DB_PATH: str = os.path.join(os.path.dirname(os.path.dirname(__file__)), "task_manager.db")
    
    # 分析结果目录（与 JCCI 引擎保持一致）
    RESULT_DIR: str = JCCI_RESULT_DIR
    
    # CORS 配置
    ALLOWED_ORIGINS: list = ["*"]
    
    # LLM API 配置（可选）
    LLM_API_URL: str = "https://openai.good.hidns.vip/v1"
    LLM_API_KEY: str = "sk-B882bCwUweSeMRscoNwxZw4vxpjXmvWTLBxO5aXC7WAYhfwa"
    # LLM_MODEL: str = "minimaxai/minimax-m2.7"
    LLM_MODEL: str = "moonshotai/kimi-k2.6"
    
    class Config:
        env_file = ".env"
        case_sensitive = True


# 创建全局配置实例
settings = Settings()

# 确保必要的目录存在
os.makedirs(os.path.dirname(settings.DB_PATH), exist_ok=True)
os.makedirs(settings.RESULT_DIR, exist_ok=True)
