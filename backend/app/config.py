"""
FastAPI 应用配置
"""
import os
from pathlib import Path
from pydantic_settings import BaseSettings


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
    
    # 分析结果目录
    RESULT_DIR: str = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "analyze_result")
    
    # CORS 配置
    ALLOWED_ORIGINS: list = ["*"]
    
    # LLM API 配置（可选）
    LLM_API_URL: str = ""
    LLM_API_KEY: str = ""
    LLM_MODEL: str = "gpt-3.5-turbo"
    
    class Config:
        env_file = ".env"
        case_sensitive = True


# 创建全局配置实例
settings = Settings()

# 确保必要的目录存在
os.makedirs(os.path.dirname(settings.DB_PATH), exist_ok=True)
os.makedirs(settings.RESULT_DIR, exist_ok=True)
