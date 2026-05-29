"""
LLM 智能分析服务
"""
import json
import time
import sqlite3
import threading
import uuid
from typing import Dict, Optional, List
from app.config import settings


class LLMAnalysisStatus:
    """全局 LLM 分析状态管理（线程安全）"""
    
    IDLE = "idle"
    ANALYZING = "analyzing"
    
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._lock = threading.Lock()
            cls._instance._status = cls.IDLE
            cls._instance._current_task = None
            cls._instance._started_at = None
        return cls._instance
    
    @property
    def status(self) -> str:
        with self._lock:
            return self._status
    
    @property
    def current_task(self) -> Optional[str]:
        with self._lock:
            return self._current_task
    
    @property
    def started_at(self) -> Optional[float]:
        with self._lock:
            return self._started_at
    
    def start(self, task_description: str = ""):
        """开始分析，返回 True 表示获取锁成功"""
        with self._lock:
            if self._status == self.ANALYZING:
                return False
            self._status = self.ANALYZING
            self._current_task = task_description
            self._started_at = time.time()
            return True
    
    def finish(self):
        """完成分析"""
        with self._lock:
            self._status = self.IDLE
            self._current_task = None
            self._started_at = None
    
    def to_dict(self) -> dict:
        with self._lock:
            elapsed = (time.time() - self._started_at) if self._started_at else 0
            return {
                "status": self._status,
                "current_task": self._current_task,
                "elapsed_seconds": round(elapsed, 1)
            }


# 全局单例
llm_status = LLMAnalysisStatus()


class LLMService:
    """LLM 分析服务"""
    
    def __init__(self):
        self.api_url = settings.LLM_API_URL
        self.api_key = settings.LLM_API_KEY
        self.model = settings.LLM_MODEL
        self.db_path = settings.DB_PATH
        self._ensure_cache_table()
        self._ensure_task_tables()

    def _ensure_cache_table(self):
        """确保 LLM 缓存表存在（含自动迁移）"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS llm_analysis_cache (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                analysis_type TEXT NOT NULL,
                direction TEXT NOT NULL,
                class_name TEXT,
                method_name TEXT,
                change_type TEXT,
                analysis_result TEXT NOT NULL,
                model_name TEXT,
                analysis_duration REAL DEFAULT 0.0,
                is_fresh_analysis INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP,
                UNIQUE(analysis_type, direction, class_name, method_name, change_type)
            )
        ''')
        
        # 迁移：为已有表添加缺失的列
        existing_columns = [row[1] for row in cursor.execute("PRAGMA table_info(llm_analysis_cache)")]
        migrations = {
            'analysis_duration': 'ALTER TABLE llm_analysis_cache ADD COLUMN analysis_duration REAL DEFAULT 0.0',
            'is_fresh_analysis': 'ALTER TABLE llm_analysis_cache ADD COLUMN is_fresh_analysis INTEGER DEFAULT 0',
            'updated_at': 'ALTER TABLE llm_analysis_cache ADD COLUMN updated_at TIMESTAMP',
            'baseline': "ALTER TABLE llm_analysis_cache ADD COLUMN baseline TEXT DEFAULT ''",
            'version': "ALTER TABLE llm_analysis_cache ADD COLUMN version TEXT DEFAULT ''",
        }
        for col_name, sql in migrations.items():
            if col_name not in existing_columns:
                try:
                    cursor.execute(sql)
                except sqlite3.OperationalError:
                    pass  # 列已存在
        
        conn.commit()
        conn.close()
    
    def _ensure_task_tables(self):
        """确保 LLM 分析任务表和结果表存在"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # 任务表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS llm_analysis_tasks (
                task_id TEXT PRIMARY KEY,
                analysis_type TEXT NOT NULL,
                direction TEXT NOT NULL,
                baseline TEXT DEFAULT '',
                version TEXT DEFAULT '',
                class_name TEXT DEFAULT '',
                method_name TEXT DEFAULT '',
                change_type TEXT DEFAULT 'UNKNOWN',
                status TEXT NOT NULL DEFAULT 'pending',
                progress REAL DEFAULT 0.0,
                total_methods INTEGER DEFAULT 1,
                completed_methods INTEGER DEFAULT 0,
                current_stage TEXT DEFAULT '',
                custom_system_prompt TEXT DEFAULT '',
                custom_analysis_prompt TEXT DEFAULT '',
                force_fresh INTEGER DEFAULT 0,
                error_message TEXT DEFAULT '',
                started_at TIMESTAMP,
                completed_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # 结果表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS llm_analysis_results (
                result_id TEXT PRIMARY KEY,
                task_id TEXT NOT NULL,
                parent_task_id TEXT,
                class_name TEXT DEFAULT '',
                method_name TEXT DEFAULT '',
                analysis_result TEXT NOT NULL,
                model_name TEXT DEFAULT '',
                analysis_duration REAL DEFAULT 0.0,
                from_cache INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (task_id) REFERENCES llm_analysis_tasks(task_id)
            )
        ''')
        
        conn.commit()
        conn.close()
    
    # ========== 异步任务管理 ==========
    
    def create_task(
        self,
        analysis_type: str,
        direction: str,
        baseline: str = '',
        version: str = '',
        class_name: str = '',
        method_name: str = '',
        change_type: str = 'UNKNOWN',
        force_fresh: bool = False,
        custom_system_prompt: str = '',
        custom_analysis_prompt: str = '',
        total_methods: int = 1
    ) -> str:
        """创建分析任务，返回 task_id"""
        task_id = str(uuid.uuid4())
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO llm_analysis_tasks 
            (task_id, analysis_type, direction, baseline, version,
             class_name, method_name, change_type, status,
             total_methods, force_fresh,
             custom_system_prompt, custom_analysis_prompt)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?)
        ''', (task_id, analysis_type, direction, baseline, version,
              class_name, method_name, change_type,
              total_methods, 1 if force_fresh else 0,
              custom_system_prompt, custom_analysis_prompt))
        conn.commit()
        conn.close()
        return task_id
    
    def update_task_status(
        self,
        task_id: str,
        status: str,
        progress: float = None,
        total_methods: int = None,
        completed_methods: int = None,
        current_stage: str = None,
        error_message: str = None
    ):
        """更新任务状态"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        updates = ["status = ?"]
        params = [status]
        
        if progress is not None:
            updates.append("progress = ?")
            params.append(progress)
        if total_methods is not None:
            updates.append("total_methods = ?")
            params.append(total_methods)
        if completed_methods is not None:
            updates.append("completed_methods = ?")
            params.append(completed_methods)
        if current_stage is not None:
            updates.append("current_stage = ?")
            params.append(current_stage)
        if error_message is not None:
            updates.append("error_message = ?")
            params.append(error_message)
        
        if status == 'running':
            updates.append("started_at = CURRENT_TIMESTAMP")
        elif status in ('completed', 'failed'):
            updates.append("completed_at = CURRENT_TIMESTAMP")
        
        params.append(task_id)
        cursor.execute(f"UPDATE llm_analysis_tasks SET {', '.join(updates)} WHERE task_id = ?", params)
        conn.commit()
        conn.close()
    
    def get_task(self, task_id: str) -> Optional[Dict]:
        """获取任务详情"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM llm_analysis_tasks WHERE task_id = ?", (task_id,))
        row = cursor.fetchone()
        conn.close()
        if row:
            task = dict(row)
            # 查询关联的子结果
            task['sub_results'] = self._get_task_results(task_id)
            return task
        return None
    
    def _get_task_results(self, task_id: str) -> List[Dict]:
        """获取任务关联的所有结果"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute('''
            SELECT r.*, t.status as task_status
            FROM llm_analysis_results r
            JOIN llm_analysis_tasks t ON r.task_id = t.task_id
            WHERE r.parent_task_id = ? OR r.task_id = ?
            ORDER BY r.created_at
        ''', (task_id, task_id))
        rows = cursor.fetchall()
        conn.close()
        return [dict(row) for row in rows]
    
    def save_result(
        self,
        task_id: str,
        class_name: str,
        method_name: str,
        analysis_result: str,
        analysis_duration: float = 0.0,
        from_cache: bool = False,
        parent_task_id: str = None
    ) -> str:
        """保存分析结果，返回 result_id"""
        result_id = str(uuid.uuid4())
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO llm_analysis_results 
            (result_id, task_id, parent_task_id, class_name, method_name,
             analysis_result, model_name, analysis_duration, from_cache)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (result_id, task_id, parent_task_id, class_name, method_name,
              analysis_result, self.model, analysis_duration, 1 if from_cache else 0))
        conn.commit()
        conn.close()
        return result_id
    
    def get_result(self, result_id: str) -> Optional[Dict]:
        """获取单个分析结果"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM llm_analysis_results WHERE result_id = ?", (result_id,))
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None
    
    # ========== 后台异步执行方法 ==========
    
    def run_method_task(
        self,
        task_id: str,
        method_info: Dict,
        db_info: Optional[Dict] = None,
        direction: str = 'upwards',
        baseline: str = '',
        version: str = '',
        force_fresh: bool = False,
        custom_system_prompt: str = '',
        custom_analysis_prompt: str = ''
    ):
        """后台执行单方法分析任务"""
        try:
            self.update_task_status(task_id, 'running', progress=0.1, current_stage='method_analysis')
            
            class_name = method_info.get('class_name', '')
            method_name = method_info.get('method_name', '')
            
            result = self.analyze_method(
                method_info=method_info,
                db_info=db_info or {},
                direction=direction,
                baseline=baseline,
                version=version,
                force_fresh=force_fresh,
                custom_system_prompt=custom_system_prompt,
                custom_analysis_prompt=custom_analysis_prompt
            )
            
            # 保存结果
            self.save_result(
                task_id=task_id,
                class_name=class_name,
                method_name=method_name,
                analysis_result=result['result'],
                analysis_duration=result.get('duration', 0.0),
                from_cache=result.get('from_cache', False)
            )
            
            self.update_task_status(task_id, 'completed', progress=1.0)
        except Exception as e:
            self.update_task_status(task_id, 'failed', error_message=str(e))
    
    def run_chain_task(
        self,
        task_id: str,
        chain_data: Dict,
        selected_methods: List[Dict],
        direction: str = 'upwards',
        baseline: str = '',
        version: str = '',
        force_fresh: bool = False,
        custom_system_prompt: str = '',
        custom_analysis_prompt: str = ''
    ):
        """后台执行链路分析任务（逐方法分析 + 聚合）"""
        try:
            total = len(selected_methods)
            self.update_task_status(task_id, 'running', progress=0.05,
                                    total_methods=total, completed_methods=0,
                                    current_stage='method_analysis')
            
            sub_results = []
            for idx, method_info in enumerate(selected_methods):
                class_name = method_info.get('class_name', '')
                method_name = method_info.get('method_name', '')
                
                try:
                    result = self.analyze_method(
                        method_info=method_info,
                        db_info=method_info.get('db_info', {}),
                        direction=direction,
                        baseline=baseline,
                        version=version,
                        force_fresh=force_fresh,
                        custom_system_prompt=custom_system_prompt,
                        custom_analysis_prompt=custom_analysis_prompt
                    )
                    
                    self.save_result(
                        task_id=task_id,
                        class_name=class_name,
                        method_name=method_name,
                        analysis_result=result['result'],
                        analysis_duration=result.get('duration', 0.0),
                        from_cache=result.get('from_cache', False),
                        parent_task_id=task_id
                    )
                    
                    sub_results.append({
                        'class_name': class_name,
                        'method_name': method_name,
                        'result': result['result'],
                        'from_cache': result.get('from_cache', False)
                    })
                except Exception as e:
                    sub_results.append({
                        'class_name': class_name,
                        'method_name': method_name,
                        'result': f"分析失败: {str(e)}",
                        'from_cache': False,
                        'error': str(e)
                    })
                
                # 更新进度
                completed = idx + 1
                progress = 0.05 + (0.55 * completed / total)
                self.update_task_status(task_id, 'running', progress=progress,
                                        completed_methods=completed)
            
            # 阶段2：聚合分析
            self.update_task_status(task_id, 'running', progress=0.65,
                                    current_stage='aggregation')
            
            success_results = [r for r in sub_results if 'error' not in r]
            if not success_results:
                raise Exception("所有子方法分析均失败，无法进行聚合分析")
            
            # 构建聚合提示词
            aggregation_prompt = self._build_chain_aggregation_prompt(
                chain_data, direction, success_results,
                custom_analysis_prompt
            )
            system_prompt = custom_system_prompt or self._get_system_prompt('chain')
            
            start_time = time.time()
            aggregation_result = self._call_llm_api(aggregation_prompt, system_prompt)
            duration = time.time() - start_time
            
            # 保存聚合结果
            mi = chain_data.get('method_info', {})
            self.save_result(
                task_id=task_id,
                class_name=mi.get('class_name', ''),
                method_name=mi.get('method_name', ''),
                analysis_result=aggregation_result,
                analysis_duration=duration,
                from_cache=False
            )
            
            # 保存到缓存
            self._save_to_cache(
                analysis_type='chain',
                direction=direction,
                baseline=baseline,
                version=version,
                class_name=mi.get('class_name', ''),
                method_name=mi.get('method_name', ''),
                change_type=mi.get('change_type', 'UNKNOWN'),
                analysis_result=aggregation_result,
                analysis_duration=duration
            )
            
            self.update_task_status(task_id, 'completed', progress=1.0)
        except Exception as e:
            self.update_task_status(task_id, 'failed', error_message=str(e))
    
    def run_batch_method_task(
        self,
        task_id: str,
        methods: List[Dict],
        direction: str = 'upwards',
        baseline: str = '',
        version: str = '',
        force_fresh: bool = False,
        custom_system_prompt: str = '',
        custom_analysis_prompt: str = ''
    ):
        """后台执行批量方法分析（逐方法调用 analyze_method，实时更新 Tree 标签）"""
        try:
            total = len(methods)
            self.update_task_status(task_id, 'running', progress=0.05,
                                    total_methods=total, completed_methods=0,
                                    current_stage='method_analysis')
            
            for idx, method_info in enumerate(methods):
                class_name = method_info.get('class_name', '')
                method_name = method_info.get('method_name', '')
                
                try:
                    result = self.analyze_method(
                        method_info=method_info,
                        db_info=method_info.get('db_info', {}),
                        direction=direction,
                        baseline=baseline,
                        version=version,
                        force_fresh=force_fresh,
                        custom_system_prompt=custom_system_prompt,
                        custom_analysis_prompt=custom_analysis_prompt
                    )
                    
                    self.save_result(
                        task_id=task_id,
                        class_name=class_name,
                        method_name=method_name,
                        analysis_result=result['result'],
                        analysis_duration=result.get('duration', 0.0),
                        from_cache=result.get('from_cache', False),
                        parent_task_id=task_id
                    )
                except Exception as e:
                    print(f"[BATCH] 批量分析子方法失败 {class_name}.{method_name}: {e}")
                
                # 更新进度
                completed = idx + 1
                progress = 0.05 + (0.9 * completed / total)
                self.update_task_status(task_id, 'running', progress=progress,
                                        completed_methods=completed)
            
            self.update_task_status(task_id, 'completed', progress=1.0)
        except Exception as e:
            self.update_task_status(task_id, 'failed', error_message=str(e))
    
    def _build_chain_aggregation_prompt(
        self,
        chain_data: Dict,
        direction: str,
        sub_results: List[Dict],
        custom_prompt: str = ''
    ) -> str:
        """构建链路聚合分析提示词"""
        if custom_prompt:
            methods_text = "\n\n---\n\n".join([
                "## {}.{}\n{}".format(r['class_name'], r['method_name'], r['result'])
                for r in sub_results
            ])
            return "{}\n\n以下是对调用链中各个方法的分析结果，请基于这些结果进行汇总分析：\n\n{}".format(
                custom_prompt, methods_text)
        
        mi = chain_data.get('method_info', {})
        prompt = f"""请对以下调用链路进行整体分析：

【链路入口】
- 类名: {mi.get('class_name', 'N/A')}
- 方法名: {mi.get('method_name', 'N/A')}
- 分析方向: {'向上（影响面）' if direction == 'upwards' else '向下（功能风险）'}

【各方法分析结果】
"""
        for i, r in enumerate(sub_results, 1):
            cache_mark = '♻️缓存' if r.get('from_cache') else '🆕全新'
            prompt += f"\n### {i}. {r['class_name']}.{r['method_name']} ({cache_mark})\n{r['result']}\n"
        
        prompt += """

【汇总要求】
请从以下角度进行汇总分析：
1. 综合影响面评估（对所有入口点和下游服务的影响）
2. 整体风险评级（高/中/低）及理由
3. 端到端测试策略建议
4. 上线检查清单

请按照以上结构给出详细汇总分析。"""
        return prompt
    
    def analyze_method(
        self,
        method_info: Dict,
        db_info: Dict,
        direction: str = 'upwards',
        baseline: str = '',
        version: str = '',
        force_fresh: bool = False,
        custom_system_prompt: str = '',
        custom_analysis_prompt: str = ''
    ) -> Dict:
        """
        分析单个方法的变更和测试建议
        
        Args:
            method_info: 方法信息字典
            db_info: 数据库补充信息
            direction: 分析方向
            baseline: 基线名称
            version: 版本名称
            force_fresh: 是否强制全新分析
            custom_system_prompt: 自定义系统提示词
            custom_analysis_prompt: 自定义分析提示词
            
        Returns:
            分析结果字典（含 duration）
        """
        change_type = method_info.get('change_type', 'UNKNOWN')
        class_name = method_info.get('class_name', '')
        method_name = method_info.get('method_name', '')
        
        # 尝试从缓存获取
        if not force_fresh:
            cached = self._get_from_cache('method', direction, baseline, version,
                                          class_name, method_name, change_type)
            if cached:
                return {
                    'result': cached['analysis_result'],
                    'from_cache': True,
                    'duration': 0.0,
                    'cache_info': {
                        'created_at': cached['created_at'],
                        'model_name': cached['model_name'],
                        'analysis_duration': cached['analysis_duration']
                    }
                }
        
        # 构建提示词
        prompt = custom_analysis_prompt or self._build_method_prompt(method_info, db_info)
        system_prompt = custom_system_prompt or self._get_system_prompt('method')
        
        # 调用 LLM API
        start_time = time.time()
        result = self._call_llm_api(prompt, system_prompt)
        duration = time.time() - start_time
        
        # 保存到缓存
        self._save_to_cache(
            analysis_type='method',
            direction=direction,
            baseline=baseline,
            version=version,
            class_name=class_name,
            method_name=method_name,
            change_type=change_type,
            analysis_result=result,
            analysis_duration=duration
        )
        
        return {
            'result': result,
            'from_cache': False,
            'duration': duration,
            'cache_info': None
        }
    
    def analyze_chain(
        self,
        chain_data: Dict,
        direction: str = 'upwards',
        baseline: str = '',
        version: str = '',
        force_fresh: bool = False,
        custom_system_prompt: str = '',
        custom_analysis_prompt: str = ''
    ) -> Dict:
        """
        分析整个调用链的影响和风险
        
        Args:
            chain_data: 调用链数据字典
            direction: 分析方向
            baseline: 基线名称
            version: 版本名称
            force_fresh: 是否强制全新分析
            custom_system_prompt: 自定义系统提示词
            custom_analysis_prompt: 自定义分析提示词
            
        Returns:
            分析结果字典
        """
        method_info = chain_data.get('method_info', {})
        entry_points = chain_data.get('entry_points', [])
        
        class_name = method_info.get('class_name', '')
        method_name = method_info.get('method_name', '')
        change_type = method_info.get('change_type', 'UNKNOWN')
        
        # 尝试从缓存获取
        if not force_fresh:
            cached = self._get_from_cache('chain', direction, baseline, version,
                                          class_name, method_name, change_type)
            if cached:
                return {
                    'result': cached['analysis_result'],
                    'from_cache': True,
                    'duration': 0.0,
                    'cache_info': {
                        'created_at': cached['created_at'],
                        'model_name': cached['model_name'],
                        'analysis_duration': cached['analysis_duration']
                    }
                }
        
        # 构建提示词
        prompt = custom_analysis_prompt or self._build_chain_prompt(chain_data, direction)
        system_prompt = custom_system_prompt or self._get_system_prompt('chain')
        
        # 调用 LLM API
        start_time = time.time()
        result = self._call_llm_api(prompt, system_prompt)
        duration = time.time() - start_time
        
        # 保存到缓存
        self._save_to_cache(
            analysis_type='chain',
            direction=direction,
            baseline=baseline,
            version=version,
            class_name=class_name,
            method_name=method_name,
            change_type=change_type,
            analysis_result=result,
            analysis_duration=duration
        )
        
        return {
            'result': result,
            'from_cache': False,
            'duration': duration,
            'cache_info': None
        }
    
    def _get_from_cache(
        self,
        analysis_type: str,
        direction: str,
        baseline: str,
        version: str,
        class_name: str,
        method_name: str,
        change_type: str
    ) -> Optional[Dict]:
        """从缓存获取分析结果（含 baseline/version 维度）"""
        try:
            conn = sqlite3.connect(settings.DB_PATH)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT analysis_result, created_at, model_name, analysis_duration
                FROM llm_analysis_cache
                WHERE analysis_type = ? 
                  AND direction = ?
                  AND baseline = ?
                  AND version = ?
                  AND class_name = ?
                  AND method_name = ?
                  AND change_type = ?
                ORDER BY created_at DESC
                LIMIT 1
            """, (analysis_type, direction, baseline, version,
                  class_name, method_name, change_type))
            
            row = cursor.fetchone()
            conn.close()
            
            if row:
                return dict(row)
            return None
        except Exception as e:
            print(f"查询缓存失败: {e}")
            return None
    
    def _save_to_cache(
        self,
        analysis_type: str,
        direction: str,
        baseline: str,
        version: str,
        class_name: str,
        method_name: str,
        change_type: str,
        analysis_result: str,
        analysis_duration: float = 0.0
    ):
        """保存分析结果到缓存（含 baseline/version 维度）"""
        try:
            conn = sqlite3.connect(settings.DB_PATH)
            cursor = conn.cursor()
            
            cursor.execute("""
                INSERT OR REPLACE INTO llm_analysis_cache 
                (analysis_type, direction, baseline, version,
                 class_name, method_name, 
                 change_type, analysis_result, model_name, analysis_duration,
                 is_fresh_analysis, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, CURRENT_TIMESTAMP)
            """, (
                analysis_type, direction, baseline, version,
                class_name, method_name,
                change_type, analysis_result, self.model, analysis_duration
            ))
            
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"保存缓存失败: {e}")
    
    def _build_method_prompt(self, method_info: Dict, db_info: Dict) -> str:
        """构建方法分析提示词"""
        change_type = method_info.get('change_type', 'UNKNOWN')
        class_name = method_info.get('class_name', '')
        method_name = method_info.get('method_name', '')
        parameters = method_info.get('parameters', '[]')
        return_type = method_info.get('return_type', '')
        
        # 变更类型中文映射
        change_type_cn = {
            'ADDED': '新增',
            'MODIFIED': '修改',
            'DELETED': '删除',
            'UNCHANGED': '未变更'
        }.get(change_type, change_type)
        
        # 数据库补充信息
        db_parts = []
        if db_info:
            if db_info.get('filepath'):
                db_parts.append(f"- 文件路径: {db_info['filepath']}")
            if db_info.get('package_name'):
                db_parts.append(f"- 包名: {db_info['package_name']}")
            if db_info.get('class_type'):
                db_parts.append(f"- 类类型: {db_info['class_type']}")
            if db_info.get('is_controller') is not None:
                db_parts.append(f"- 是否为Controller: {'是' if db_info['is_controller'] else '否'}")
        db_section = '\n'.join(db_parts) if db_parts else '（无补充信息）'
        
        prompt = f"""请基于以下信息，分析Java方法的变更情况并提供专业的测试建议：

【方法基本信息】
- 类名: {class_name}
- 方法名: {method_name}
- 参数: {parameters}
- 返回类型: {return_type}
- 变更类型: {change_type}（{change_type_cn}）

【数据库补充信息】
{db_section}

【分析要求】
请严格按照以下五部分结构进行分析：

### 一、变更内容分析
- 识别功能变化、逻辑调整、新增/删除的代码块
- 说明业务影响范围（如涉及哪些模块、表、缓存、消息队列等）
- 如为Controller方法，分析API端点变更对外部调用方的影响

### 二、代码质量评估
| 评估维度 | 分析要点 |
|---------|---------|
| 方法设计 | 命名规范、RESTful合规性、职责单一性 |
| 参数校验 | 是否缺失 @NotNull、@Valid、范围校验等 |
| 异常处理 | 是否捕获业务异常、是否吞异常、是否返回友好提示 |
| 性能考量 | 循环调用、N+1查询、大事务、同步阻塞 |
| 幂等性 | 重复调用是否安全 |
| 线程安全 | 是否存在竞态条件、共享变量修改 |

### 三、测试建议
#### 1. 集成测试要点
| 测试场景 | 输入条件 | 预期结果 | 优先级 |
|---------|---------|---------|--------|
| （请填写） | （请填写） | （请填写） | P0/P1/P2 |

#### 2. 边界条件与异常场景
- 空值/边界值：null参数、空集合、超长字符串等
- 异常路径：数据库异常、网络超时、依赖服务不可用
- 并发场景：多线程同时调用、重复提交

#### 3. 接口规范测试
- Swagger注解与实际行为是否一致
- HTTP方法语义是否正确（GET/POST/PUT/DELETE）
- 返回结构是否向前兼容

### 四、风险评估
#### 🔴 高风险操作
- 识别物理删除、资金操作、批量更新无限制、跨服务调用等

#### ⚠️ 可能的副作用
- 关联数据完整性影响
- 缓存一致性问题
- 消息通知或事件触发链
- 前端兼容性（返回字段变更）

#### 📋 回归测试建议
- 明确需要回归的核心链路和相关功能点
- 上下游模块的影响范围

### 五、改进建议（可选）
- 如发现代码设计或实现可改进之处，提供优化方案
- 可给出优化后的代码片段示例

请使用中文回答，确保分析具体、可执行。"""
        
        return prompt
    
    def _build_chain_prompt(self, chain_data: Dict, direction: str) -> str:
        """构建调用链分析提示词"""
        method_info = chain_data.get('method_info', {})
        entry_points = chain_data.get('entry_points', [])
        
        class_name = method_info.get('class_name', '')
        method_name = method_info.get('method_name', '')
        change_type = method_info.get('change_type', 'UNKNOWN')
        
        prompt = f"""请分析以下{'向上' if direction == 'upwards' else '向下'}调用链路：

【变更方法信息】
- 类名: {method_info.get('class_name', 'N/A')}
- 方法名: {method_info.get('method_name', 'N/A')}
- 变更类型: {method_info.get('change_type', 'UNKNOWN')}

【入口点信息】
"""
        
        if entry_points:
            for i, entry in enumerate(entry_points, 1):
                prompt += f"""
{i}. 入口类型: {entry.get('root_type', 'N/A')}
   - 类: {entry.get('package_class', 'N/A')}
   - 方法: {entry.get('method_signature', 'N/A')}
"""
        else:
            prompt += "未找到明确的入口点\n"
        
        prompt += f"""
【调用链方向】
{'向上分析（影响面）: 谁调用了变更方法，寻找受影响的入口API' if direction == 'upwards' else '向下分析（功能风险）: 变更方法调用了谁，评估功能风险'}

【分析要求】
请从以下几个方面进行分析：

1. **调用链路概览**
   - 链路的起点和终点
   - 关键节点识别
   - 链路复杂度评估

2. **影响面分析**
   {'- 哪些API端点会受到影响' if direction == 'upwards' else '- 依赖了哪些下游服务/组件'}
   - 影响的用户群体或业务场景

3. **风险评估**
   - 链路中的单点故障
   - 性能瓶颈识别
   - 数据一致性风险

4. **测试策略**
   - 端到端测试场景设计
   - 需要重点关注的环节
   - 监控和告警建议

请按照以上结构给出详细分析。"""
        
        return prompt
    
    def _get_system_prompt(self, analysis_type: str) -> str:
        """获取系统提示词"""
        if analysis_type == 'method':
            return """你是一位资深的Java代码审查专家和测试工程师。你的任务是基于代码变更信息，识别潜在风险并提供精准、可执行的测试策略。

回答要求：
1. 使用中文，结构清晰，分点说明
2. 重点关注变更带来的影响和风险
3. 测试建议必须具体可执行（含场景、预期结果、优先级）
4. 风险评估需结合业务场景，避免泛泛而谈
5. 如信息不足，明确指出需要补充的内容"""
        else:
            return """你是一位资深的系统架构师和测试专家。请分析调用链路的影响范围和测试策略。
回答要求：
1. 使用中文回答
2. 从系统整体角度分析影响面
3. 提供端到端的测试策略
4. 关注链路中的薄弱环节"""
    
    def get_default_prompts(self, analysis_type: str, method_info: Optional[Dict] = None, chain_data: Optional[Dict] = None, direction: str = 'upwards') -> Dict:
        """
        获取默认的系统提示词和分析提示词模板
        
        Args:
            analysis_type: 'method' | 'chain'
            method_info: 方法信息（用于生成分析方法提示词）
            chain_data: 调用链数据（用于生成链分析提示词）
            direction: 分析方向
            
        Returns:
            { system_prompt, analysis_prompt }
        """
        system_prompt = self._get_system_prompt(analysis_type)
        
        if analysis_type == 'method':
            analysis_prompt = self._build_method_prompt(method_info or {}, {})
        else:
            analysis_prompt = self._build_chain_prompt(chain_data or {}, direction)
        
        return {
            'system_prompt': system_prompt,
            'analysis_prompt': analysis_prompt
        }
    
    def _call_llm_api(self, prompt: str, system_prompt: str) -> str:
        """调用 LLM API"""
        # 如果未配置 LLM API，返回模拟结果
        if not self.api_url or not self.api_key:
            return self._get_mock_result(prompt)
        
        try:
            import requests
            
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}"
            }
            
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt}
            ]
            
            payload = {
                "model": self.model,
                "messages": messages,
                "max_tokens": 2000,
                "temperature": 0.7
            }
            
            response = requests.post(
                f"{self.api_url}/chat/completions",
                json=payload,
                headers=headers,
                timeout=300
            )
            
            if response.status_code == 200:
                result = response.json()
                return result['choices'][0]['message']['content']
            else:
                return f"API调用失败: HTTP {response.status_code}\n{response.text}"
        except Exception as e:
            return f"请求异常: {str(e)}\n\n建议使用模拟数据进行测试。"
    
    def _get_mock_result(self, prompt: str) -> str:
        """生成模拟分析结果（用于测试）"""
        return """## 分析报告（模拟数据）

### 一、变更内容分析
- 这是一个模拟的分析结果
- 实际使用时需要配置 LLM API

### 二、代码质量评估
| 评估维度 | 分析要点 |
|---------|---------|
| 方法设计 | 当前为测试模式 |
| 参数校验 | 请在 config.py 中配置 LLM_API_URL 和 LLM_API_KEY |
| 异常处理 | 配置后即可获得真实分析 |
| 性能考量 | N/A（模拟数据） |
| 幂等性 | N/A（模拟数据） |
| 线程安全 | N/A（模拟数据） |

### 三、测试建议
| 测试场景 | 输入条件 | 预期结果 | 优先级 |
|---------|---------|---------|--------|
| 模拟测试 | N/A | N/A | P2 |

### 四、风险评估
- 🔴 高风险操作: N/A（模拟数据）
- ⚠️ 可能的副作用: N/A（模拟数据）
- 📋 回归测试建议: N/A（模拟数据）

### 五、改进建议
- 当前为模拟数据，不影响核心功能测试

---
💡 **提示**: 要启用真实的 LLM 分析，请在 backend/app/config.py 中配置：
```python
LLM_API_URL = "https://api.openai.com/v1"
LLM_API_KEY = "your-api-key"
LLM_MODEL = "gpt-3.5-turbo"
```
"""


# 全局实例
llm_service = LLMService()
