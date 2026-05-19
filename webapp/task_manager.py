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
        
        # ✅ 恢复未完成的队列任务
        self._recover_pending_tasks()
    
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
    
    def _recover_pending_tasks(self):
        """
        从数据库中恢复未完成的任务到内存队列
        
        系统重启后，将数据库中status为pending或running的任务加载到内存中
        如果有running任务，将其状态改为failed（因为进程已中断）
        然后尝试启动队列中的下一个任务
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # 查询所有未完成的任务
        cursor.execute('''
            SELECT * FROM analysis_tasks 
            WHERE status IN (?, ?)
            ORDER BY created_at ASC
        ''', (TaskStatus.PENDING, TaskStatus.RUNNING))
        
        rows = cursor.fetchall()
        conn.close()
        
        if not rows:
            logger.info("没有需要恢复的队列任务")
            return
        
        recovered_count = 0
        for row in rows:
            task_dict = dict(row)
            task_id = task_dict['task_id']
            
            # 如果是running状态，说明系统崩溃或重启，将其改为failed
            if task_dict['status'] == TaskStatus.RUNNING:
                logger.warning(f"发现中断的任务 {task_id}，状态从 RUNNING 改为 FAILED")
                task_dict['status'] = TaskStatus.FAILED
                task_dict['error_message'] = '系统重启，任务中断'
                
                # 更新数据库
                conn = sqlite3.connect(self.db_path)
                cursor = conn.cursor()
                cursor.execute('''
                    UPDATE analysis_tasks 
                    SET status = ?, error_message = ?, completed_at = CURRENT_TIMESTAMP
                    WHERE task_id = ?
                ''', (TaskStatus.FAILED, '系统重启，任务中断', task_id))
                conn.commit()
                conn.close()
            
            # 加载到内存
            with self._lock:
                self.tasks[task_id] = task_dict
            
            recovered_count += 1
            logger.info(f"恢复任务: {task_id} ({task_dict['status']})")
        
        logger.info(f"共恢复 {recovered_count} 个任务到队列")
        
        # ✅ 尝试启动队列中的下一个任务
        self._try_start_next_task()
    
    def _validate_git_refs(self, git_url: str, username: str, tag_old: str, tag_new: str) -> tuple:
        """
        快速验证 Git 引用（tag/commit）是否存在
        
        使用 git ls-remote 命令远程检查，无需 clone 整个仓库
        
        Args:
            git_url: Git 仓库地址
            username: Git 用户名
            tag_old: 旧版本标签
            tag_new: 新版本标签
            
        Returns:
            tuple: (is_valid, error_message)
                - is_valid: True 如果两个引用都存在
                - error_message: 错误信息，如果验证通过则为 None
        """
        import subprocess
        import re
        
        try:
            # 构建 git ls-remote 命令
            # 对于私有仓库，可能需要认证
            cmd = ['git', 'ls-remote', git_url]
            
            # 执行命令，设置超时10秒
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=10
            )
            
            if result.returncode != 0:
                # git 命令失败
                error_msg = result.stderr.strip()
                if 'Authentication failed' in error_msg or 'could not read Username' in error_msg:
                    return False, f"Git 认证失败，请检查用户名和密码。错误: {error_msg[:100]}"
                elif 'not found' in error_msg.lower() or 'could not resolve host' in error_msg.lower():
                    return False, f"Git 仓库不存在或无法访问: {git_url}"
                else:
                    return False, f"Git 命令执行失败: {error_msg[:100]}"
            
            # 解析输出，获取所有引用
            output = result.stdout
            refs = set()
            for line in output.split('\n'):
                if line.strip():
                    parts = line.split('\t')
                    if len(parts) == 2:
                        commit_hash, ref_name = parts
                        refs.add(ref_name)
                        # 也添加短名称（refs/tags/v1.0.0 -> v1.0.0）
                        if ref_name.startswith('refs/tags/'):
                            refs.add(ref_name.replace('refs/tags/', ''))
                        elif ref_name.startswith('refs/heads/'):
                            refs.add(ref_name.replace('refs/heads/', ''))
            
            # 验证 tag_old
            if tag_old not in refs:
                # 检查是否是完整的 commit hash（40位）
                if len(tag_old) == 40 and re.match(r'^[0-9a-f]{40}$', tag_old, re.IGNORECASE):
                    # 对于 commit hash，需要检查是否在输出中
                    # git ls-remote 默认不列出所有 commit，只列出引用
                    # 所以我们假设如果是40位十六进制，就认为可能是有效的
                    logger.info(f"tag_old '{tag_old}' 是 commit hash，跳过精确验证")
                else:
                    # 尝试模糊匹配
                    matched = [r for r in refs if tag_old in r]
                    if matched:
                        logger.info(f"tag_old '{tag_old}' 模糊匹配到: {matched[0]}")
                    else:
                        available_tags = [r for r in refs if r.startswith('refs/tags/') or not r.startswith('refs/')]
                        available_sample = ', '.join(available_tags[:5])
                        return False, (
                            f"tag_old '{tag_old}' 不存在于仓库中。\n"
                            f"可用的标签/分支示例: {available_sample}"
                        )
            
            # 验证 tag_new
            if tag_new not in refs:
                # 检查是否是完整的 commit hash（40位）
                if len(tag_new) == 40 and re.match(r'^[0-9a-f]{40}$', tag_new, re.IGNORECASE):
                    logger.info(f"tag_new '{tag_new}' 是 commit hash，跳过精确验证")
                else:
                    # 尝试模糊匹配
                    matched = [r for r in refs if tag_new in r]
                    if matched:
                        logger.info(f"tag_new '{tag_new}' 模糊匹配到: {matched[0]}")
                    else:
                        available_tags = [r for r in refs if r.startswith('refs/tags/') or not r.startswith('refs/')]
                        available_sample = ', '.join(available_tags[:5])
                        return False, (
                            f"tag_new '{tag_new}' 不存在于仓库中。\n"
                            f"可用的标签/分支示例: {available_sample}"
                        )
            
            # 验证通过
            logger.info(f"✅ Git 引用验证通过: {tag_old}, {tag_new}")
            return True, None
            
        except subprocess.TimeoutExpired:
            return False, f"Git 命令超时（10秒），请检查网络连接或仓库地址: {git_url}"
        except FileNotFoundError:
            return False, "Git 未安装或不在 PATH 中"
        except Exception as e:
            logger.error(f"Git 引用验证异常: {e}", exc_info=True)
            return False, f"Git 引用验证失败: {str(e)}"
    
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
        
        # ✅ 快速验证 Git 引用是否存在（使用 git ls-remote）
        is_valid, error_msg = self._validate_git_refs(git_url, username, tag_old, tag_new)
        if not is_valid:
            raise Exception(error_msg)
        
        # ✅ 允许提交新任务，进入队列等待
        # 不再检查是否有任务在执行，所有新任务都进入pending状态
        
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
        
        # ✅ 尝试启动队列调度（如果有任务在运行，新任务会等待）
        self._try_start_next_task()
        
        logger.info(f"任务已提交: {task_id}")
        return task_id, None  # 新任务，result_url 为 None
    
    def _try_start_next_task(self):
        """
        尝试启动下一个等待中的任务
        
        检查是否有正在运行的任务，如果没有，则启动队列中最早的pending任务
        """
        with self._lock:
            # 检查是否有正在运行的任务
            has_running = any(
                task['status'] == TaskStatus.RUNNING 
                for task in self.tasks.values()
            )
            
            if has_running:
                logger.info("当前有任务正在运行，新任务将在队列中等待")
                return
            
            # 查找最早的pending任务（按创建时间）
            pending_tasks = [
                task for task in self.tasks.values()
                if task['status'] == TaskStatus.PENDING
            ]
            
            if not pending_tasks:
                logger.info("队列中没有等待的任务")
                return
            
            # 按创建时间排序，取最早的
            pending_tasks.sort(key=lambda x: x['created_at'])
            next_task = pending_tasks[0]
            
            logger.info(f"启动队列中的下一个任务: {next_task['task_id']}")
            
            # 启动任务执行线程
            thread = threading.Thread(
                target=self._execute_task,
                args=(
                    next_task['task_id'],
                    next_task['git_url'],
                    next_task['username'],
                    next_task['tag_old'],
                    next_task['tag_new'],
                    next_task['max_depth']
                ),
                daemon=True
            )
            thread.start()
    
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
            # 格式: http://host:port/?baseline=project_shorttag
            # 需要从 tag_old 提取短标识符（与 workflow1 中的逻辑一致）
            import re
            from config import STREAMLIT_PORT, STREAMLIT_HOST, STREAMLIT_EXTERNAL_URL
            
            if len(tag_old) == 40 and re.match(r'^[0-9a-f]{40}$', tag_old, re.IGNORECASE):
                short_tag = tag_old[:8]  # Commit hash: 前8位
            elif '_' in tag_old or len(tag_old) > 11:
                short_tag = tag_old[-11:]  # Git Tag: 后11位
            else:
                short_tag = tag_old  # 短标识符: 保持不变
            
            baseline_name = f"{project_name}_{short_tag}"
            
            # 优先使用外部URL配置，如果没有则根据HOST自动生成
            if STREAMLIT_EXTERNAL_URL:
                # 使用配置的外部URL
                result_url = f"{STREAMLIT_EXTERNAL_URL}/?baseline={baseline_name}"
            else:
                # 自动生成本地访问URL
                host = "localhost" if STREAMLIT_HOST == "0.0.0.0" else STREAMLIT_HOST
                result_url = f"http://{host}:{STREAMLIT_PORT}/?baseline={baseline_name}"
            
            # 更新状态为完成
            self._update_task_status(
                task_id, 
                TaskStatus.COMPLETED, 
                progress=100.0,
                result_url=result_url
            )
            
            logger.info(f"任务完成: {task_id}, URL: {result_url}")
            
            # ✅ 启动队列中的下一个任务
            self._try_start_next_task()
            
        except Exception as e:
            logger.error(f"任务失败: {task_id}, 错误: {str(e)}", exc_info=True)
            self._update_task_status(
                task_id, 
                TaskStatus.FAILED, 
                error_message=str(e)
            )
            
            # 即使失败也要启动下一个任务
            self._try_start_next_task()
    
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
    
    def get_queue_position(self, task_id: str) -> dict:
        """
        获取任务在队列中的位置
        
        Args:
            task_id: 任务 ID
            
        Returns:
            dict: {
                'position': 队列位置 (0表示正在执行，-1表示不在队列中),
                'total_pending': 等待中的任务总数,
                'estimated_wait_minutes': 预估等待时间(分钟),
                'current_running_task': 当前正在执行的任务信息
            }
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # 获取所有pending和running任务，按创建时间排序
        cursor.execute('''
            SELECT task_id, status, tag_old, tag_new, created_at
            FROM analysis_tasks 
            WHERE status IN (?, ?)
            ORDER BY created_at ASC
        ''', (TaskStatus.PENDING, TaskStatus.RUNNING))
        
        queue_tasks = [dict(row) for row in cursor.fetchall()]
        conn.close()
        
        if not queue_tasks:
            return {
                'position': 0,
                'total_pending': 0,
                'estimated_wait_minutes': 0,
                'current_running_task': None
            }
        
        # 找到当前任务的位置
        position = -1
        for idx, task in enumerate(queue_tasks):
            if task['task_id'] == task_id:
                position = idx
                break
        
        # 如果任务不在队列中（可能已完成或失败）
        if position == -1:
            return {
                'position': -1,
                'total_pending': len(queue_tasks),
                'estimated_wait_minutes': 0,
                'current_running_task': queue_tasks[0] if queue_tasks else None
            }
        
        # 计算预估等待时间（假设每个任务平均需要15分钟）
        avg_task_duration_minutes = 15
        tasks_before = position  # 前面的任务数量
        estimated_wait = tasks_before * avg_task_duration_minutes
        
        # 获取当前正在执行的任务
        current_running = None
        for task in queue_tasks:
            if task['status'] == TaskStatus.RUNNING:
                current_running = task
                break
        
        return {
            'position': position,
            'total_pending': len(queue_tasks),
            'estimated_wait_minutes': estimated_wait,
            'current_running_task': current_running
        }
    
    def cancel_task(self, task_id: str) -> bool:
        """
        取消尚未开始执行的任务
        
        Args:
            task_id: 任务 ID
            
        Returns:
            bool: 是否成功取消
        """
        # 只能取消 pending 状态的任务
        task_info = self.get_task_status(task_id)
        if not task_info:
            return False
        
        if task_info['status'] != TaskStatus.PENDING:
            logger.warning(f"无法取消任务 {task_id}，当前状态为 {task_info['status']}")
            return False
        
        # 更新数据库状态
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE analysis_tasks 
            SET status = ?, completed_at = CURRENT_TIMESTAMP,
                error_message = '用户主动取消'
            WHERE task_id = ?
        ''', (TaskStatus.FAILED, task_id))
        conn.commit()
        conn.close()
        
        # 更新内存缓存
        with self._lock:
            if task_id in self.tasks:
                self.tasks[task_id]['status'] = TaskStatus.FAILED
                self.tasks[task_id]['error_message'] = '用户主动取消'
        
        logger.info(f"任务已取消: {task_id}")
        return True
    
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
