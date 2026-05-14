"""
异步任务管理器

支持通过 Web 界面触发 workflow1 分析，并在后台异步执行
"""

import os
import sys
import json
import time
import uuid
import logging
import sqlite3
import threading
from typing import Dict, Optional, List
from datetime import datetime

# 添加项目根目录到 Python 路径
# task_manager.py 位于 jcci/webapp/
# 需要向上1级到达 jcci/（项目根目录）
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# 导入项目模块
from jcci.database import SqliteHelper
from workflow1 import workflow1  # webapp 同级模块，使用直接导入（Streamlit 不支持相对导入）

logger = logging.getLogger(__name__)


class TaskStatus:
    """任务状态枚举"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class AsyncTaskManager:
    """
    异步任务管理器
    
    功能：
    1. 接收 workflow1 分析请求
    2. 在后台线程中异步执行
    3. 跟踪任务状态和进度
    4. 存储分析结果路径
    """
    
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.tasks: Dict[str, dict] = {}
        self._lock = threading.Lock()
        self._task_complete_event = threading.Event()  # 任务完成事件
        self._task_complete_event.set()  # 初始状态为已设置（允许提交）
        
        # 确保数据库中存在任务表
        self._ensure_task_table()
    
    def _ensure_task_table(self):
        """确保任务表存在"""
        # 确保数据库目录存在
        db_dir = os.path.dirname(self.db_path)
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir, exist_ok=True)
            logger.info(f"创建数据库目录: {db_dir}")
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # 创建表
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
                output_dir TEXT
            )
        ''')
        
        conn.commit()
        
        # 验证表是否创建成功
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='analysis_tasks'")
        table_exists = cursor.fetchone()
        
        conn.close()
        
        if table_exists:
            logger.info(f"✅ 数据库初始化完成: {self.db_path}")
        else:
            logger.error(f"❌ 数据库表创建失败: {self.db_path}")
            raise RuntimeError(f"Failed to create analysis_tasks table in {self.db_path}")
    
    def submit_task(self, git_url: str, username: str, tag_old: str, 
                   tag_new: str, max_depth: int = 5) -> str:
        """
        提交分析任务
        
        Args:
            git_url: Git 仓库地址
            username: Git 用户名
            tag_old: 旧版本标签
            tag_new: 新版本标签
            max_depth: 最大分析深度
            
        Returns:
            tuple: (task_id, result_url)
                - task_id: 任务 ID
                - result_url: 如果任务已完成，返回结果 URL；否则为 None
            
        Raises:
            Exception: 如果有正在运行的不同任务
        """
        # 检查是否有相同的分析任务（相同的 git_url, tag_old, tag_new）
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            SELECT task_id, status, result_url, error_message 
            FROM analysis_tasks 
            WHERE git_url = ? AND tag_old = ? AND tag_new = ?
            ORDER BY created_at DESC
            LIMIT 1
        ''', (git_url, tag_old, tag_new))
        existing_task = cursor.fetchone()
        conn.close()
        
        if existing_task:
            existing_task_id, status, result_url, error_message = existing_task
            logger.info(f"发现已存在的任务: {existing_task_id}, 状态: {status}")
            
            # 如果任务已完成，直接返回
            if status == TaskStatus.COMPLETED:
                logger.info(f"任务已完成，直接返回结果: {existing_task_id}")
                return existing_task_id, result_url
            
            # 如果任务正在运行或等待中，返回任务 ID
            if status in [TaskStatus.PENDING, TaskStatus.RUNNING]:
                logger.info(f"任务正在执行中，返回任务 ID: {existing_task_id}")
                return existing_task_id, None
            
            # 如果任务失败，可以选择重新执行或删除后重新提交
            # 这里我们选择允许重新提交（会创建新任务）
            logger.info(f"任务已失败，将创建新任务: {existing_task_id}")
        
        # 检查任务完成事件（确保上一个任务完全结束）
        if not self._task_complete_event.is_set():
            # 获取当前运行的任务 ID
            with self._lock:
                for task in self.tasks.values():
                    if task['status'] in [TaskStatus.PENDING, TaskStatus.RUNNING]:
                        raise Exception(
                            f"已有任务正在执行中（任务ID: {task['task_id']}，状态: {task['status']}）。"
                            f"请等待当前任务完成后再提交新任务。"
                        )
            
            # 如果内存中没有找到，查数据库
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('''
                SELECT task_id, status FROM analysis_tasks 
                WHERE status IN (?, ?)
                LIMIT 1
            ''', (TaskStatus.PENDING, TaskStatus.RUNNING))
            running_task = cursor.fetchone()
            conn.close()
            
            if running_task:
                raise Exception(
                    f"已有任务正在执行中（任务ID: {running_task[0]}，状态: {running_task[1]}）。"
                    f"请等待当前任务完成后再提交新任务。"
                )
        
        task_id = str(uuid.uuid4())[:12]
        
        # 保存任务信息到数据库
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO analysis_tasks 
            (task_id, status, git_url, username, tag_old, tag_new, max_depth)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (task_id, TaskStatus.PENDING, git_url, username, tag_old, tag_new, max_depth))
        conn.commit()
        conn.close()
        
        # 在内存中也保存一份（用于快速查询）
        with self._lock:
            self.tasks[task_id] = {
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
            }
            # 清除任务完成事件，阻止新任务提交
            self._task_complete_event.clear()
        
        # 启动后台线程执行任务
        thread = threading.Thread(
            target=self._execute_task,
            args=(task_id, git_url, username, tag_old, tag_new, max_depth),
            daemon=True
        )
        thread.start()
        
        logger.info(f"任务已提交: {task_id}")
        return task_id, None  # 新任务，result_url 为 None
    
    def _execute_task(self, task_id: str, git_url: str, username: str,
                     tag_old: str, tag_new: str, max_depth: int):
        """
        在后台线程中执行任务
        
        Args:
            task_id: 任务 ID
            git_url: Git 仓库地址
            username: Git 用户名
            tag_old: 旧版本标签
            tag_new: 新版本标签
            max_depth: 最大分析深度
        """
        try:
            # 更新状态为运行中
            self._update_task_status(task_id, TaskStatus.RUNNING, progress=10.0)
            
            # 构造输出目录
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            project_name = git_url.split('/')[-1].replace('.git', '')
            output_dir = os.path.join(
                os.path.dirname(self.db_path),
                "analyze_result",
                f"{project_name}_{timestamp}"
            )
            
            # 更新进度
            self._update_task_status(task_id, TaskStatus.RUNNING, progress=20.0, output_dir=output_dir)
            
            # 执行 workflow1
            logger.info(f"开始执行 workflow1: task_id={task_id}")
            
            result = workflow1(
                git_url=git_url,
                username=username,
                tag_old=tag_old,
                tag_new=tag_new,
                max_depth=max_depth,
                enable_streamlit=False,  # 强制禁用 Streamlit
                auto_open_browser=False
            )
            
            # 更新进度
            self._update_task_status(task_id, TaskStatus.RUNNING, progress=90.0)
            
            # 构造 Web 访问链接
            # 格式: http://host:port/?baseline=project_commit
            baseline_name = f"{project_name}_{tag_old}"
            result_url = f"http://localhost:8501/?baseline={baseline_name}"
            
            # 更新状态为完成
            self._update_task_status(
                task_id, 
                TaskStatus.COMPLETED, 
                progress=100.0,
                result_url=result_url
            )
            
            logger.info(f"任务完成: {task_id}, URL: {result_url}")
            
            # 设置任务完成事件，允许新任务提交
            self._task_complete_event.set()
            
        except Exception as e:
            logger.error(f"任务失败: {task_id}, 错误: {str(e)}", exc_info=True)
            self._update_task_status(
                task_id, 
                TaskStatus.FAILED, 
                error_message=str(e)
            )
            
            # 即使失败也要设置事件，允许新任务提交
            self._task_complete_event.set()
    
    def _update_task_status(self, task_id: str, status: str, 
                           progress: Optional[float] = None,
                           result_url: Optional[str] = None,
                           error_message: Optional[str] = None,
                           output_dir: Optional[str] = None):
        """
        更新任务状态
        
        Args:
            task_id: 任务 ID
            status: 任务状态
            progress: 进度百分比 (0-100)
            result_url: 结果 URL
            error_message: 错误信息
            output_dir: 输出目录
        """
        now = datetime.now().isoformat()
        
        # 更新数据库
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
        
        # 更新内存缓存
        with self._lock:
            if task_id in self.tasks:
                self.tasks[task_id]['status'] = status
                if progress is not None:
                    self.tasks[task_id]['progress'] = progress
                if result_url is not None:
                    self.tasks[task_id]['result_url'] = result_url
                if error_message is not None:
                    self.tasks[task_id]['error_message'] = error_message
                if output_dir is not None:
                    self.tasks[task_id]['output_dir'] = output_dir
    
    def get_task_status(self, task_id: str) -> Optional[dict]:
        """
        获取任务状态
        
        Args:
            task_id: 任务 ID
            
        Returns:
            任务信息字典，如果不存在则返回 None
        """
        # 先查内存缓存
        with self._lock:
            if task_id in self.tasks:
                return self.tasks[task_id].copy()
        
        # 再查数据库
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM analysis_tasks WHERE task_id=?', (task_id,))
        row = cursor.fetchone()
        conn.close()
        
        if row:
            task_info = dict(row)
            # 同步到内存缓存
            with self._lock:
                self.tasks[task_id] = task_info
            return task_info
        
        return None
    
    def list_tasks(self, limit: int = 20) -> List[dict]:
        """
        列出最近的任务
        
        Args:
            limit: 返回数量限制
            
        Returns:
            任务列表
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute('''
            SELECT * FROM analysis_tasks 
            ORDER BY created_at DESC 
            LIMIT ?
        ''', (limit,))
        rows = cursor.fetchall()
        conn.close()
        
        tasks = [dict(row) for row in rows]
        
        # 更新内存缓存
        with self._lock:
            for task in tasks:
                self.tasks[task['task_id']] = task
        
        return tasks


# 全局任务管理器实例
_task_manager = None


def get_task_manager(db_path: str = None) -> AsyncTaskManager:
    """
    获取全局任务管理器实例
    
    Args:
        db_path: 数据库路径，如果为 None 则使用默认路径
        
    Returns:
        AsyncTaskManager 实例
    """
    global _task_manager
    
    if _task_manager is None:
        if db_path is None:
            # 使用默认数据库路径
            from config import DB_PATH
            db_path = DB_PATH
        
        _task_manager = AsyncTaskManager(db_path)
    
    return _task_manager
