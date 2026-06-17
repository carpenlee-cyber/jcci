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
    DEBUG: bool = False
    
    # 服务器配置
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    
    # 数据库配置
    DB_PATH: str = os.path.join(os.path.dirname(os.path.dirname(__file__)), "task_manager.db")
    
    # 分析结果目录（与 JCCI 引擎保持一致）
    RESULT_DIR: str = JCCI_RESULT_DIR
    
    # CORS 配置（生产环境应通过环境变量限制为前端域名）
    ALLOWED_ORIGINS: str = "*"
    
    @property
    def allowed_origins_list(self) -> list:
        """将逗号分隔的字符串转为列表"""
        return [o.strip() for o in self.ALLOWED_ORIGINS.split(",") if o.strip()]
    
    # # LLM API 配置
    # LLM_API_URL: str = "https://openai.good.hidns.vip/v1"
    # LLM_API_KEY: str = "sk-B882bCwUweSeMRscoNwxZw4vxpjXmvWTLBxO5aXC7WAYhfwa"
    # # LLM_MODEL: str = "minimaxai/minimax-m2.7"
    # LLM_MODEL: str = "moonshotai/kimi-k2.6"
    
    # LLM API 配置
    LLM_API_URL: str = "http://testhub-ai-runtime-gateway.paasuat.cmbchina.cn/v1"
    LLM_API_KEY: str = "app-gf4FuFGcnrgim1KX2t2ae6DV"
    LLM_MODEL: str = "公司内部模型"

    # PipelineAnalysisV2 API 配置
    PIPELINE_V2_API_BASE_URL: str = "http://localhost:8001"

    class Config:
        env_file = ".env"
        case_sensitive = True


# 创建全局配置实例
settings = Settings()

# 确保必要的目录存在
os.makedirs(os.path.dirname(settings.DB_PATH), exist_ok=True)
os.makedirs(settings.RESULT_DIR, exist_ok=True)