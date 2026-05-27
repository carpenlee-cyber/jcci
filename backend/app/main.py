"""
FastAPI 应用入口
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings
from app.database import db_manager


def create_app() -> FastAPI:
    """创建 FastAPI 应用实例"""
    
    app = FastAPI(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        description="JCCI Code Change Impact Analysis Platform",
    )
    
    # 配置 CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.ALLOWED_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    # 初始化数据库
    db_manager.init_db()
    
    # 注册路由
    from app.api import tasks
    app.include_router(tasks.router)
    
    # 健康检查端点
    @app.get("/health")
    def health_check():
        return {"status": "ok", "version": settings.APP_VERSION}
    
    return app


app = create_app()
