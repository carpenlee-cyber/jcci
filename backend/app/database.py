"""
数据库连接管理
"""
import sqlite3
from typing import Optional
from contextlib import contextmanager
from app.config import settings


class DatabaseManager:
    """数据库管理器"""
    
    def __init__(self, db_path: str = None):
        self.db_path = db_path or settings.DB_PATH
    
    @contextmanager
    def get_connection(self):
        """获取数据库连接（上下文管理器）"""
        conn = None
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row  # 使结果可以通过列名访问
            yield conn
        finally:
            if conn:
                conn.close()
    
    def init_db(self):
        """初始化数据库表结构"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # 创建任务表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS analysis_tasks (
                    task_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    git_url TEXT NOT NULL,
                    username TEXT,
                    tag_old TEXT,
                    tag_new TEXT,
                    max_depth INTEGER DEFAULT 5,
                    progress REAL DEFAULT 0.0,
                    result_url TEXT,
                    error_message TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    started_at TIMESTAMP,
                    completed_at TIMESTAMP,
                    output_dir TEXT,
                    has_password BOOLEAN DEFAULT 0,
                    project_code TEXT,
                    task_stage TEXT,
                    user_ip TEXT,
                    user_name TEXT,
                    user_id TEXT
                )
            ''')
            
            conn.commit()


# 全局数据库管理器实例
db_manager = DatabaseManager()
