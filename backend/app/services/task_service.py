"""
任务服务层 - 封装任务管理逻辑
"""
import os
import sys
import uuid
import logging
import sqlite3
import threading
from typing import Dict, Optional, List
from datetime import datetime

# 添加项目根目录到路径（用于导入 workflow1）
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

logger = logging.getLogger(__name__)


class TaskStatus:
    """任务状态枚举"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class TaskService:
    """
    任务服务
    
    提供任务的 CRUD 操作
    """
    
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._ensure_task_table()
    
    def _ensure_task_table(self):
        """确保任务表存在"""
        db_dir = os.path.dirname(self.db_path)
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir, exist_ok=True)
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
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
        conn.close()
    
    def create_task(self, git_url: str, username: str, tag_old: str, 
                   tag_new: str, max_depth: int = 5, password: str = None,
                   project_code: str = "", task_stage: str = "",
                   user_ip: str = "", user_name: str = "网页用户", user_id: str = "web") -> str:
        """
        创建任务
        
        Returns:
            task_id: 任务 ID
        """
        task_id = str(uuid.uuid4())[:12]
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO analysis_tasks 
            (task_id, status, git_url, username, tag_old, tag_new, max_depth, has_password,
             project_code, task_stage, user_ip, user_name, user_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (task_id, TaskStatus.PENDING, git_url, username, tag_old, tag_new, max_depth, 1 if password else 0,
              project_code, task_stage, user_ip, user_name, user_id))
        conn.commit()
        conn.close()
        
        logger.info(f"任务已创建: {task_id}")
        return task_id
    
    def get_task(self, task_id: str) -> Optional[dict]:
        """获取任务详情"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM analysis_tasks WHERE task_id=?', (task_id,))
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return dict(row)
        return None
    
    def list_tasks(self, limit: int = 20, offset: int = 0) -> List[dict]:
        """获取任务列表"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute('''
            SELECT * FROM analysis_tasks 
            ORDER BY created_at DESC 
            LIMIT ? OFFSET ?
        ''', (limit, offset))
        rows = cursor.fetchall()
        conn.close()
        
        return [dict(row) for row in rows]
    
    def count_tasks(self) -> int:
        """获取任务总数"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('SELECT COUNT(*) as count FROM analysis_tasks')
        result = cursor.fetchone()
        conn.close()
        
        return result[0] if result else 0
    
    def update_task_status(self, task_id: str, status: str, 
                          progress: Optional[float] = None,
                          result_url: Optional[str] = None,
                          error_message: Optional[str] = None):
        """更新任务状态"""
        now = datetime.now().isoformat()
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        if status == TaskStatus.RUNNING and progress is not None:
            cursor.execute('''
                UPDATE analysis_tasks 
                SET status=?, progress=?, started_at=?
                WHERE task_id=?
            ''', (status, progress, now, task_id))
        elif status == TaskStatus.COMPLETED:
            cursor.execute('''
                UPDATE analysis_tasks 
                SET status=?, progress=100.0, result_url=?, completed_at=?
                WHERE task_id=?
            ''', (status, result_url, now, task_id))
        elif status == TaskStatus.FAILED:
            cursor.execute('''
                UPDATE analysis_tasks 
                SET status=?, error_message=?, completed_at=?
                WHERE task_id=?
            ''', (status, error_message, now, task_id))
        
        conn.commit()
        conn.close()
    
    def delete_task(self, task_id: str) -> bool:
        """删除任务"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('DELETE FROM analysis_tasks WHERE task_id=?', (task_id,))
        deleted = cursor.rowcount > 0
        conn.commit()
        conn.close()
        
        return deleted
