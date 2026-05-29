"""
任务服务层 - 封装任务管理逻辑（含后台任务执行引擎）
"""
import os
import re
import sys
import uuid
import logging
import sqlite3
import threading
from typing import Dict, Optional, List
from datetime import datetime

# 添加项目根目录到路径（用于导入 workflow1）
# backend/app/services/task_service.py -> backend/ -> jcci/
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

logger = logging.getLogger(__name__)

from jcci.utils.tag_utils import extract_short_tag


class TaskStatus:
    """任务状态枚举"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class TaskService:
    """
    任务服务（含后台任务执行引擎）
    
    提供任务的 CRUD 操作和后台异步执行
    """
    
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._lock = threading.Lock()
        self._tasks: Dict[str, dict] = {}  # 内存中的任务缓存
        self._ensure_task_table()
        self._load_pending_tasks()
    
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
        
        # 添加到内存缓存
        with self._lock:
            self._tasks[task_id] = {
                'task_id': task_id,
                'status': TaskStatus.PENDING,
                'git_url': git_url,
                'username': username,
                'tag_old': tag_old,
                'tag_new': tag_new,
                'max_depth': max_depth,
                'progress': 0.0,
                'result_url': None,
                'error_message': None,
                'created_at': datetime.now().isoformat(),
                'project_code': project_code,
                'task_stage': task_stage,
                'user_ip': user_ip,
                'user_name': user_name,
                'user_id': user_id,
            }
        
        logger.info(f"任务已创建: {task_id}")
        
        # ✅ 启动任务执行（关键！）
        self._try_start_next_task()
        
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
        """更新任务状态（公开方法，供 API 调用）"""
        self._update_task_status(task_id, status, progress, result_url, error_message)
    
    def find_active_task(self, git_url: str, tag_old: str,
                          tag_new: str, max_depth: int) -> Optional[dict]:
        """
        查找相同参数的活跃任务（pending 或 running）
        
        Args:
            git_url: Git 仓库地址
            tag_old: 旧版本标签
            tag_new: 新版本标签
            max_depth: 最大分析深度
            
        Returns:
            正在排队或执行中的重复任务 dict，没有则返回 None
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute('''
            SELECT * FROM analysis_tasks 
            WHERE git_url=? AND tag_old=? AND tag_new=? AND max_depth=?
              AND status IN ('pending', 'running')
            ORDER BY created_at DESC 
            LIMIT 1
        ''', (git_url, tag_old, tag_new, max_depth))
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return dict(row)
        return None

    def find_duplicate_task(self, git_url: str, tag_old: str, 
                           tag_new: str, max_depth: int) -> Optional[dict]:
        """
        查找相同参数的已完成任务（去重）
        
        Args:
            git_url: Git 仓库地址
            tag_old: 旧版本标签
            tag_new: 新版本标签
            max_depth: 最大分析深度
            
        Returns:
            已完成的重复任务 dict，没有则返回 None
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute('''
            SELECT * FROM analysis_tasks 
            WHERE git_url=? AND tag_old=? AND tag_new=? AND max_depth=?
              AND status='completed'
            ORDER BY completed_at DESC 
            LIMIT 1
        ''', (git_url, tag_old, tag_new, max_depth))
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return dict(row)
        return None
    
    def delete_task(self, task_id: str) -> bool:
        """删除任务"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('DELETE FROM analysis_tasks WHERE task_id=?', (task_id,))
        deleted = cursor.rowcount > 0
        conn.commit()
        conn.close()
        
        with self._lock:
            self._tasks.pop(task_id, None)
        
        return deleted
    
    # ==================== 后台任务执行引擎 ====================
    
    def _load_pending_tasks(self):
        """从数据库加载所有 pending 任务到内存"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM analysis_tasks WHERE status='pending' ORDER BY created_at ASC")
        rows = cursor.fetchall()
        conn.close()
        
        with self._lock:
            for row in rows:
                task = dict(row)
                self._tasks[task['task_id']] = task
        
        if rows:
            logger.info(f"从数据库加载了 {len(rows)} 个 pending 任务")
            # 启动第一个等待任务
            self._try_start_next_task()
    
    def _try_start_next_task(self):
        """尝试启动下一个等待中的任务"""
        with self._lock:
            has_running = any(
                t['status'] == TaskStatus.RUNNING
                for t in self._tasks.values()
            )
            
            if has_running:
                logger.info("当前有任务正在运行，新任务将在队列中等待")
                return
            
            pending_tasks = [
                t for t in self._tasks.values()
                if t['status'] == TaskStatus.PENDING
            ]
            
            if not pending_tasks:
                logger.info("队列中没有等待的任务")
                return
            
            pending_tasks.sort(key=lambda x: x.get('created_at', ''))
            next_task = pending_tasks[0]
            
            logger.info(f"启动队列中的下一个任务: {next_task['task_id']}")
            
            thread = threading.Thread(
                target=self._execute_task,
                args=(
                    next_task['task_id'],
                    next_task['git_url'],
                    next_task['username'],
                    next_task['tag_old'],
                    next_task['tag_new'],
                    next_task['max_depth'],
                    next_task.get('user_ip', ''),
                    next_task.get('user_name', '网页用户'),
                    next_task.get('user_id', 'web')
                ),
                daemon=True
            )
            thread.start()
    
    def _execute_task(self, task_id: str, git_url: str, username: str,
                     tag_old: str, tag_new: str, max_depth: int,
                     user_ip: str = "", user_name: str = "网页用户", user_id: str = "web"):
        """在后台线程中执行 JCCI 分析任务"""
        try:
            self._update_task_status(task_id, TaskStatus.RUNNING, progress=10.0)
            
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            project_name = git_url.split('/')[-1].replace('.git', '')
            output_dir = os.path.join(
                os.path.dirname(self.db_path),
                "analyze_result",
                f"{project_name}_{timestamp}"
            )
            
            self._update_task_status(task_id, TaskStatus.RUNNING, progress=20.0, output_dir=output_dir)
            
            logger.info(f"开始执行 workflow1: task_id={task_id}")
            
            from backend.app.core.workflow1 import workflow1
            
            result = workflow1(
                git_url=git_url,
                username=username,
                tag_old=tag_old,
                tag_new=tag_new,
                max_depth=max_depth,
                enable_streamlit=False,
                auto_open_browser=False,
                user_ip=user_ip,
                user_name=user_name,
                user_id=user_id
            )
            
            self._update_task_status(task_id, TaskStatus.RUNNING, progress=90.0)
            
            # 构造结果 URL（同时包含 baseline 和 version）
            short_old = extract_short_tag(tag_old)
            short_new = extract_short_tag(tag_new)
            baseline_name = f"{project_name}_{short_old}"
            result_url = f"/analysis/?baseline={baseline_name}&version={short_new}"
            
            self._update_task_status(
                task_id,
                TaskStatus.COMPLETED,
                progress=100.0,
                result_url=result_url
            )
            
            logger.info(f"任务完成: {task_id}")
            
        except Exception as e:
            logger.error(f"任务执行失败: {task_id}, 错误: {e}")
            self._update_task_status(
                task_id,
                TaskStatus.FAILED,
                error_message=str(e)
            )
        finally:
            self._try_start_next_task()
    
    def _update_task_status(self, task_id: str, status: str,
                          progress: Optional[float] = None,
                          result_url: Optional[str] = None,
                          error_message: Optional[str] = None,
                          output_dir: Optional[str] = None):
        """更新任务状态（内存 + 数据库）"""
        with self._lock:
            if task_id in self._tasks:
                self._tasks[task_id]['status'] = status
                if progress is not None:
                    self._tasks[task_id]['progress'] = progress
                if result_url is not None:
                    self._tasks[task_id]['result_url'] = result_url
                if error_message is not None:
                    self._tasks[task_id]['error_message'] = error_message
                if output_dir is not None:
                    self._tasks[task_id]['output_dir'] = output_dir
        
        now = datetime.now().isoformat()
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        if status == TaskStatus.RUNNING:
            cursor.execute('''
                UPDATE analysis_tasks
                SET status=?, progress=?, started_at=?, output_dir=COALESCE(?, output_dir)
                WHERE task_id=?
            ''', (status, progress or 0.0, now, output_dir, task_id))
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
