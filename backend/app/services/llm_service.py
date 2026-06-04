"""
LLM 智能分析服务
"""
import os
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
        self._api_lock = threading.Lock()  # 全局 LLM API 并发锁
        self._ensure_cache_table()
        self._ensure_task_tables()

    def _ensure_cache_table(self):
        """确保 LLM 缓存表存在（含自动迁移）"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # 先创建表（如果不存在），使用完整的 UNIQUE 约束（含 baseline/version）
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS llm_analysis_cache (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                analysis_type TEXT NOT NULL,
                direction TEXT NOT NULL,
                baseline TEXT DEFAULT '',
                version TEXT DEFAULT '',
                class_name TEXT,
                method_name TEXT,
                change_type TEXT,
                analysis_result TEXT NOT NULL,
                model_name TEXT,
                analysis_duration REAL DEFAULT 0.0,
                is_fresh_analysis INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP,
                UNIQUE(analysis_type, direction, baseline, version,
                       class_name, method_name, change_type)
            )
        ''')

        # 检测旧 UNIQUE 约束（不含 baseline/version），若存在则执行表重建迁移
        need_migrate = False
        try:
            existing_cols = [row[1] for row in cursor.execute("PRAGMA table_info(llm_analysis_cache)")]
            if 'baseline' not in existing_cols or 'version' not in existing_cols:
                need_migrate = True
            else:
                # 列已存在但约束可能还是旧的，通过索引名判断
                indexes = [row[1] for row in cursor.execute("PRAGMA index_list(llm_analysis_cache)")
                          if row[2] == 1]  # unique=1
                for idx_name in indexes:
                    idx_cols = [row[2] for row in
                                cursor.execute(f"PRAGMA index_info({idx_name})")]
                    if 'baseline' not in idx_cols or 'version' not in idx_cols:
                        need_migrate = True
                        break
        except Exception:
            pass  # 表不存在时走 CREATE TABLE IF NOT EXISTS 路径

        if need_migrate:
            # 创建新表（含正确 UNIQUE）
            cursor.execute('''
                CREATE TABLE llm_analysis_cache_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    analysis_type TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    baseline TEXT DEFAULT '',
                    version TEXT DEFAULT '',
                    class_name TEXT,
                    method_name TEXT,
                    change_type TEXT,
                    analysis_result TEXT NOT NULL,
                    model_name TEXT,
                    analysis_duration REAL DEFAULT 0.0,
                    is_fresh_analysis INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP,
                    UNIQUE(analysis_type, direction, baseline, version,
                           class_name, method_name, change_type)
                )
            ''')

            # 迁移数据：按新的完整 UNIQUE 键分组，保留每组最新记录
            new_cols = ['analysis_type', 'direction', 'baseline', 'version',
                        'class_name', 'method_name', 'change_type',
                        'analysis_result', 'model_name', 'analysis_duration',
                        'is_fresh_analysis']
            new_col_names = ', '.join(new_cols)
            group_keys = ['analysis_type', 'direction',
                          "COALESCE(baseline, '')", "COALESCE(version, '')",
                          'class_name', 'method_name', 'change_type']
            cursor.execute(f'''
                INSERT INTO llm_analysis_cache_new ({new_col_names})
                SELECT {new_col_names}
                FROM llm_analysis_cache
                WHERE id IN (
                    SELECT MAX(id) FROM llm_analysis_cache
                    GROUP BY {', '.join(group_keys)}
                )
            ''')

            # 替换旧表
            cursor.execute('DROP TABLE llm_analysis_cache')
            cursor.execute('ALTER TABLE llm_analysis_cache_new RENAME TO llm_analysis_cache')

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
                custom_analysis_prompt,
                baseline=baseline, version=version
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
        custom_prompt: str = '',
        baseline: str = '',
        version: str = ''
    ) -> str:
        """构建增强版链路聚合分析提示词——含完整拓扑、方法源码、子方法 LLM 分析结果"""
        if custom_prompt:
            methods_text = "\n\n---\n\n".join([
                "## {}.{}\n{}".format(r['class_name'], r['method_name'], r['result'])
                for r in sub_results
            ])
            return "{}\n\n以下是对调用链中各个方法的分析结果，请基于这些结果进行汇总分析：\n\n{}".format(
                custom_prompt, methods_text)

        mi = chain_data.get('method_info', {})
        class_name = mi.get('class_name', '')
        method_name = mi.get('method_name', '')
        direction_cn = '向上（影响面评估）' if direction == 'upwards' else '向下（功能风险评估）'

        prompt = f"""请基于以下完整的调用链信息和各方法的 LLM 分析结果进行聚合分析：

【分析任务】
- 方向: {direction_cn}
- 变更方法: {class_name}.{method_name}
- 变更类型: {mi.get('change_type', 'UNKNOWN')}
"""

        # 第一部分：调用链完整拓扑
        full_chain = None
        entry_points = []
        if baseline and version:
            full_chain = self._load_chain_from_disk(
                baseline, version, direction, class_name, method_name)

        if full_chain:
            chain_tree = full_chain.get('chain_tree')
            entry_points = full_chain.get('entry_points', [])
            if chain_tree:
                topology_lines = []
                self._format_chain_topology(
                    chain_tree, direction, topology_lines, depth=0, is_root=True)
                topology_text = '\n'.join(topology_lines)
                prompt += f"""
【调用链完整拓扑】
（缩进表示调用深度，箭头表示调用方向，行号来自源码调用点）

{topology_text}
"""

        # 第二部分：入口点分类
        if direction == 'upwards' and entry_points:
            entry_by_type = {}
            for ep in entry_points:
                rt = ep.get('root_type', 'UNKNOWN')
                entry_by_type.setdefault(rt, []).append(ep)
            entry_type_labels = {
                'HTTP_API': 'HTTP API端点', 'SCHEDULED_TASK': '定时任务',
                'EVENT_LISTENER': '事件监听器', 'MESSAGE_CONSUMER': '消息队列消费者',
                'CONTROLLER_BY_CONVENTION': 'Controller（约定）',
                'NO_STATIC_CALLER': '无静态调用者'
            }
            prompt += f"\n【入口点分类】(共 {len(entry_points)} 个)\n"
            for rt, eps in sorted(entry_by_type.items()):
                label = entry_type_labels.get(rt, rt)
                prompt += f"{label}: {len(eps)} 个\n"

        # 第三部分：方法源码
        if full_chain and full_chain.get('chain_tree'):
            chain_methods = self._collect_chain_methods(full_chain['chain_tree'])
            changed = [m for m in chain_methods if m['change_type'] != 'UNCHANGED']
            unchanged = [m for m in chain_methods if m['change_type'] == 'UNCHANGED']
            methods_to_show = changed + unchanged[:max(0, 10 - len(changed))]
            bodies = self._fetch_method_bodies(baseline, version, methods_to_show)
            if bodies:
                prompt += "\n【链路关键方法源码】\n"
                for m in methods_to_show[:8]:
                    key = f"{m['class_name']}.{m['method_name']}"
                    body = bodies.get(key, {})
                    if not body:
                        continue
                    ct_map = {'ADDED': '[新增]', 'MODIFIED': '[修改]', 'DELETED': '[删除]', 'UNCHANGED': ''}
                    ct_tag = ct_map.get(m['change_type'], '')
                    prompt += f"\n### {key} {ct_tag}\n```java\n{body.get('body', '')[:1500]}\n```\n"

        # 第四部分：子方法 LLM 分析结果
        prompt += "\n【各方法 LLM 分析结果】\n"
        for i, r in enumerate(sub_results[:12], 1):
            cache_mark = '缓存' if r.get('from_cache') else '全新'
            prompt += f"\n### {i}. {r['class_name']}.{r['method_name']} ({cache_mark})\n{r['result'][:2000]}\n"

        # 第五部分：聚合分析要求
        if direction == 'upwards':
            prompt += """
【聚合分析要求】
**重要：请在你的汇总报告最开头，首先输出【调用链路图谱】章节——直接引用上文【调用链完整拓扑】中的图谱结构（可简化为 类名.方法名 格式，保留缩进层次和箭头方向），作为用户对照的基准。然后再按以下要求进行汇总：**

请结合以上的链拓扑、方法源码和子方法分析结果，从架构视角进行汇总：

1. **综合影响面评估**
   - 按入口点类型分类评估（HTTP API、定时任务、消息队列等）
   - 区分 DIRECT 调用和 CHA 推断的置信度差异
   - 识别级联影响（A->B->C 链式影响）

2. **跨方法影响矩阵**
   - 各变更方法之间的相互影响关系
   - 新增方法 vs 修改方法的不同风险特征

3. **整体风险评级**
   - 按入口点给出风险评级（高/中/低）及依据
   - 标注需要人工确认的 CHA 推断路径
   - 上线建议（全量/灰度/回滚策略）

4. **端到端测试策略**
   - 按入口点设计核心测试场景（含输入/预期/优先级）
   - 跨服务的集成测试要点
   - 监控和告警指标建议

5. **上线检查清单**
   - 代码审查要点
   - 配置变更检查
   - 数据库变更（DDL/DML）验证
   - 回滚方案

请使用中文回答，综合所有信息给出完整、可执行的汇总分析。"""
        else:
            prompt += """
【聚合分析要求】
**重要：请在你的汇总报告最开头，首先输出【调用链路图谱】章节——直接引用上文【调用链完整拓扑】中的图谱结构（可简化为 类名.方法名 格式，保留缩进层次和箭头方向），作为用户对照的基准。然后再按以下要求进行汇总：**

请结合以上的链拓扑、方法源码和子方法分析结果进行汇总：

1. **综合功能风险评估**
   - 下游调用链的整体风险画像
   - SQL 操作的风险汇总（表、类型、性能影响）

2. **级联影响分析**
   - 变更方法对下游方法的逐层影响
   - 异常传播路径分析

3. **整体风险评级**（高/中/低）及依据

4. **端到端测试策略**
   - 从变更方法到末端方法的完整测试场景
   - SQL 验证策略

5. **上线检查清单**

请使用中文回答。"""

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
        
        # 如果提供了 baseline 和 version，从数据库获取方法源码
        source_code = None
        if baseline and version:
            # _fetch_method_bodies 按短类名查询，需从全限定名提取
            short_class = class_name.rsplit('.', 1)[-1] if '.' in class_name else class_name
            source_code = self._fetch_method_bodies(baseline, version, [{
                'class_name': short_class,
                'method_name': method_name
            }]).get(f"{short_class}.{method_name}")
        
        # 构建提示词
        prompt = custom_analysis_prompt or self._build_method_prompt(method_info, db_info, source_code)
        system_prompt = custom_system_prompt or self._get_system_prompt('method')
        
        # 调用 LLM API
        start_time = time.time()
        result = self._call_llm_api(prompt, system_prompt)
        duration = time.time() - start_time
        
        # 检测 API 错误响应（非异常但返回了错误文本）
        if result.startswith('请求异常') or result.startswith('API调用失败'):
            raise Exception(result)
        
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
        prompt = custom_analysis_prompt or self._build_chain_prompt(chain_data, direction, baseline, version)
        system_prompt = custom_system_prompt or self._get_system_prompt('chain')
        
        # 调用 LLM API
        start_time = time.time()
        result = self._call_llm_api(prompt, system_prompt)
        duration = time.time() - start_time
        
        # 检测 API 错误响应（非异常但返回了错误文本）
        if result.startswith('请求异常') or result.startswith('API调用失败'):
            raise Exception(result)
        
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
    
    def _load_chain_from_disk(
        self, baseline: str, version: str, direction: str,
        class_name: str, method_name: str
    ) -> Optional[Dict]:
        """从磁盘加载完整调用链 JSON 数据"""
        from app.config import settings as s
        result_dir = s.RESULT_DIR
    
        # 构建文件名和路径
        filename = f"{direction}_call_chains.json"
    
        # 尝试直接路径
        filepath = os.path.join(result_dir, baseline, version, filename)
        if not os.path.exists(filepath):
            # 尝试短标签路径
            from jcci.utils.tag_utils import extract_short_tag
            baseline_short = extract_short_tag(baseline)
            version_short = extract_short_tag(version)
            filepath = os.path.join(result_dir, baseline_short, version_short, filename)
            if not os.path.exists(filepath):
                return None
    
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception as e:
            print(f"[CHAIN] 加载链 JSON 失败: {e}")
            return None
    
        # 查找匹配的链
        chains_key = 'impact_chains' if direction == 'upwards' else 'call_chains'
        if chains_key not in data:
            chains_key = 'dependency_chains'
        chains = data.get(chains_key, [])
    
        for chain in chains:
            mi = chain.get('method_info', {})
            if mi.get('class_name') == class_name and mi.get('method_name') == method_name:
                return {
                    'chain_tree': chain.get('chain'),
                    'entry_points': chain.get('entry_points', []),
                    'method_info': mi,
                    'package_class': chain.get('package_class', ''),
                    'method_signature': chain.get('method_signature', ''),
                    'has_incomplete_paths': chain.get('has_incomplete_paths', False)
                }
    
        return None
    
    def _collect_chain_methods(self, node: Dict, collected: Optional[set] = None) -> List[Dict]:
        """递归收集链树中所有唯一方法（按深度排序）"""
        if collected is None:
            collected = set()
    
        if not node:
            return []
    
        results = []
        key = (node.get('class_name', ''), node.get('method_name', ''))
        if key not in collected and key[0] and key[1]:
            collected.add(key)
            results.append({
                'class_name': node.get('class_name', ''),
                'method_name': node.get('method_name', ''),
                'package_class': node.get('package_class', ''),
                'method_signature': node.get('method_signature', ''),
                'change_type': node.get('change_type', 'UNKNOWN'),
                'depth': node.get('depth', 0),
                'root_type': node.get('root_type', ''),
                'call_type': node.get('call_type', ''),
                'db_method_id': node.get('db_method_id'),
                'dao_info': node.get('dao_info')
            })
    
        for child in node.get('children', []):
            results.extend(self._collect_chain_methods(child, collected))
    
        return sorted(results, key=lambda m: m['depth'])
    
    def _format_chain_topology(
        self, node: Dict, direction: str, lines: list, depth: int = 0,
        is_root: bool = True, parent_info: Optional[Dict] = None
    ) -> None:
        """递归格式化链树拓扑为结构化文本"""
        if not node:
            return
    
        class_name = node.get('class_name', '?')
        method_sig = node.get('method_signature', node.get('method_name', '?'))
        change_type = node.get('change_type', 'UNKNOWN')
        call_type = node.get('call_type', '')
        root_type = node.get('root_type', '')
        inv_lines = node.get('invocation_lines', [])
        is_leaf = node.get('is_leaf', False)
        dao_info = node.get('dao_info')
    
        indent = '  ' * depth
    
        # 调用类型标记
        call_tag = ''
        if call_type == 'CHA_RESOLVED':
            call_tag = ' [CHA推断]'
        elif call_type == 'DIRECT':
            call_tag = ''
    
        # 变更类型标记
        ct_map = {'ADDED': '[新增]', 'MODIFIED': '[修改]', 'DELETED': '[删除]', 'UNCHANGED': ''}
        ct_tag = ct_map.get(change_type, '')
    
        # 行号
        line_info = ''
        if inv_lines:
            line_str = ','.join(str(line) for line in inv_lines[:3])
            line_info = f' (行{line_str})'
    
        # 构建节点行
        if is_root:
            lines.append(f"{indent}▼ {class_name}.{method_sig} {ct_tag} [变更方法]")
        else:
            arrow = '↑ called by' if direction == 'upwards' else '↓ calls'
            lines.append(f"{indent}{arrow} {class_name}.{method_sig} {ct_tag}{call_tag}{line_info}")
    
        # SQL 节点特殊标注
        if dao_info and isinstance(dao_info, dict) and dao_info.get('sql_type'):
            sql_type = dao_info.get('sql_type', '?').upper()
            tables = ', '.join(dao_info.get('tables', []))
            lines.append(f"{indent}  └─ [SQL: {sql_type}] 表: {tables or 'N/A'}")
    
        # 入口/叶子标记
        if is_leaf and not is_root:
            if direction == 'upwards':
                entry_types = {
                    'HTTP_API': 'HTTP API入口', 'SCHEDULED_TASK': '定时任务入口',
                    'EVENT_LISTENER': '事件监听入口', 'MESSAGE_CONSUMER': '消息消费入口',
                    'CONTROLLER_BY_CONVENTION': 'Controller入口'
                }
                label = entry_types.get(root_type, f'入口({root_type})' if root_type else '叶子节点')
                lines.append(f"{indent}  └─ [ENTRY: {label}]")
            else:
                leaf_label = 'SQL操作' if dao_info else '末端方法'
                lines.append(f"{indent}  └─ [LEAF: {leaf_label}]")
    
        # 递归子节点
        for child in node.get('children', []):
            self._format_chain_topology(child, direction, lines, depth + 1, is_root=False, parent_info=node)
    
    def _fetch_method_bodies(
        self, baseline: str, version: str, methods: List[Dict]
    ) -> Dict[str, Dict]:
        """批量从数据库获取方法的源码和元信息"""
        if not methods:
            return {}
    
        from app.config import settings as s
        result_dir = s.RESULT_DIR
        from jcci.utils.tag_utils import extract_short_tag
    
        baseline_short = extract_short_tag(baseline)
        
        # 查找数据库文件
        db_path = None
        for candidate in [
            os.path.join(result_dir, baseline_short, f"{baseline_short}_baseline.db"),
            os.path.join(result_dir, baseline, f"{baseline}_baseline.db"),
        ]:
            if os.path.exists(candidate):
                db_path = candidate
                break
    
        if not db_path:
            # 扫描带项目前缀的目录
            suffix = '_' + baseline_short
            for item in sorted(os.listdir(result_dir)):
                full = os.path.join(result_dir, item)
                if item.endswith(suffix) and os.path.isdir(full):
                    db_candidate = os.path.join(full, f"{item}_baseline.db")
                    if os.path.exists(db_candidate):
                        db_path = db_candidate
                        break
    
        if not db_path:
            return {}
    
        result = {}
        try:
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
    
            for m in methods:
                class_name = m.get('class_name', '')
                if not class_name:
                    continue
                method_name = m.get('method_name', '')
                if not method_name:
                    continue
                key = f"{class_name}.{method_name}"
    
                cursor.execute('''
                    SELECT m.body, m.annotations, m.parameters, m.return_type,
                           m.access_modifier, m.change_type, c.class_name
                    FROM methods m
                    JOIN class c ON m.class_id = c.class_id
                    WHERE c.class_name = ? AND m.method_name = ?
                    LIMIT 1
                ''', (class_name, method_name))
                row = cursor.fetchone()
    
                if row:
                    body_lines = self._parse_body(row['body'])
                    # 限制每方法源码最多 80 行，避免上下文溢出
                    if len(body_lines) > 80:
                        body_lines = body_lines[:80]
                        body_lines.append(f"// ... (截断，共 {len(self._parse_body(row['body']))} 行)")
                    result[key] = {
                        'body': '\n'.join(body_lines),
                        'annotations': row['annotations'] or '',
                        'parameters': row['parameters'] or '',
                        'return_type': row['return_type'] or '',
                        'access_modifier': row['access_modifier'] or '',
                        'change_type': row['change_type'] or 'UNCHANGED'
                    }
    
            conn.close()
        except Exception as e:
            print(f"[CHAIN] 批量获取方法源码失败: {e}")
    
        return result
    
    @staticmethod
    def _parse_body(body) -> list:
        """解析 DB body 字段为行列表"""
        if not body:
            return []
        try:
            return json.loads(body) if isinstance(body, str) else body
        except (json.JSONDecodeError, TypeError):
            return [body] if isinstance(body, str) else []
    
    def _build_method_prompt(self, method_info: Dict, db_info: Dict, source_code: Dict = None) -> str:
        """构建方法分析提示词（六部分结构化输出）"""
        change_type = method_info.get('change_type', 'UNKNOWN')
        class_name = method_info.get('class_name', '')
        method_name = method_info.get('method_name', '')
        parameters = method_info.get('parameters', [])
        return_type = method_info.get('return_type', '')
        # 从 source_code 补充字段
        if source_code:
            if source_code.get('parameters'):
                parameters = source_code['parameters']
            if source_code.get('return_type'):
                return_type = source_code['return_type']

        # 格式化参数列表
        if isinstance(parameters, str):
            try:
                parameters = json.loads(parameters)
            except (json.JSONDecodeError, TypeError):
                parameters = parameters
        if isinstance(parameters, list) and parameters:
            params_str = ', '.join(p.get('type', '?') + ' ' + p.get('name', '?') for p in parameters if isinstance(p, dict))
        elif isinstance(parameters, list):
            params_str = '(无参数)'
        else:
            params_str = str(parameters) if parameters else '(无参数)'

        # 多版本类名
        full_class_name = db_info.get('package_name', '') + '.' + class_name.split('.')[-1] if db_info.get('package_name') else class_name

        # 构建代码版本信息
        baseline_code = method_info.get('baseline_code', '')
        current_code = method_info.get('current_code', '')
        baseline_label = method_info.get('baseline_version', '基线版本')
        current_label = method_info.get('current_version', '目标版本')

        # 根据变更类型构建变更前/后代码段
        if change_type == 'ADDED':
            before_code = '(新增前没有代码)'
            after_code_block = f'【变更后代码（{current_label}）】\n```java\n{current_code or source_code.get("body", "") if source_code else ""}\n```'
        elif change_type == 'DELETED':
            before_code_block = f'【变更前代码（{baseline_label}）】\n```java\n{baseline_code or source_code.get("body", "") if source_code else ""}\n```'
            after_code = '(方法已被删除，无变更后代码)'
        elif change_type == 'UNCHANGED':
            before_code_block = f'【变更前代码（{baseline_label}）】\n```java\n{baseline_code or source_code.get("body", "") if source_code else ""}\n```'
            after_code = '(代码没有变化)'
        else:
            # MODIFIED
            before_code_block = f'【变更前代码（{baseline_label}）】\n```java\n{baseline_code or source_code.get("body", "") if source_code else ""}\n```'
            after_code_block = f'【变更后代码（{current_label}）】\n```java\n{current_code or source_code.get("body", "") if source_code else ""}\n```'

        # 构建代码输入段
        if change_type == 'ADDED':
            code_input = f'{after_code_block}\n\n【变更前代码】\n{before_code}'
        elif change_type == 'DELETED':
            code_input = f'{before_code_block}\n\n【变更后代码】\n{after_code}'
        elif change_type == 'UNCHANGED':
            code_input = f'{before_code_block}\n\n【变更后代码】\n{after_code}'
        else:
            code_input = f'{before_code_block}\n\n{after_code_block}'

        prompt = f"""# 角色与任务
你是一名资深Java开发工程师及代码审计专家。请根据我提供的"变更前代码"与"变更后代码"，生成一份专业、结构化、可直接用于技术评审或发布说明的《变更前后代码对比与分析报告》。

# 输入格式
请严格基于以下输入内容进行分析：
- 方法: {full_class_name}.{method_name}({params_str})
- 返回类型: {return_type or '(未提供)'}
- 变更类型: {change_type}
- 变更前版本号: {baseline_label}
- 变更后版本号: {current_label}

{code_input}

# 输出要求（严格按以下六部分结构输出，使用Markdown格式）

## 一、代码说明
- 分别展示变更前/后代码（使用Java代码块）。
- 关键要求：为代码添加逐逻辑块的详细注释，采用"步骤编号+核心逻辑说明"格式（如：// 1. 按发票币种分组并求和...），确保非原作者也能快速理解执行流与数据走向。

## 二、代码差异对比表
- 使用Markdown表格，列名固定为：变更点 | 变更前代码 | 变更后代码 | 说明
- 表格内容需提炼核心差异（如：币种处理、校验逻辑、计算方式、复杂度等），语言精炼。
- 表格后附一段"核心逻辑差异总结"（3-4句话，点明业务/技术层面的本质变化）。

## 三、逻辑流程图对比
- 分别绘制变更前/后的逻辑流程图。
- 格式要求：使用纯文本/ASCII字符绘制，采用箭头(↓, →, ↓ 是 ↓ 否)表示流程走向，保持简洁清晰，避免复杂图形或换行混乱。

## 四、逻辑差异详解
- 分点阐述（建议3-5点），需覆盖：
  1. 核心业务逻辑变化（如：多币种转换 vs 直接求和）
  2. 数据校验与安全性提升
  3. 代码复杂度/性能/可维护性对比
  4. 潜在依赖或前置条件变化（如：上游数据格式假设、外部服务调用变更）
- 语言需专业、精准，避免主观臆断，基于代码事实分析。若涉及未明确的外部依赖，需合理推断并标注"基于代码上下文推断"。

## 五、测试场景建议
- 提供两个Markdown表格：功能案例场景 与 流程案例场景。
- 列名固定：测试点 | 预期结果 | 备注
- 覆盖维度：正常场景、异常场景、边界场景、流程完整性、数据一致性。
- 测试点描述需具体可执行（如："正常场景：单币种核销"而非"测试正常情况"），预期结果需明确可验证。

## 六、总结
- 结构化输出：
  1. 变更影响：分"优点/收益"与"潜在风险/依赖"
  2. 实施建议：给出3条可落地的建议（如：数据验证、单元测试覆盖、回滚预案、上下游协同等）

# 约束与风格要求
- 严格遵循上述六部分结构，不增删章节，不添加额外寒暄。
- 语言风格：专业、客观、技术向，符合企业级代码评审标准。
- 所有表格、代码块、流程图必须符合Markdown规范，排版整洁。
- 直接输出报告内容，无需解释生成过程。"""

        return prompt
    
    def _build_chain_prompt(
        self, chain_data: Dict, direction: str,
        baseline: str = '', version: str = ''
    ) -> str:
        """构建增强版调用链分析提示词——含完整拓扑、方法源码、入口分类"""
        method_info = chain_data.get('method_info', {})
        class_name = method_info.get('class_name', '')
        method_name = method_info.get('method_name', '')

        direction_cn = '向上（影响面评估）' if direction == 'upwards' else '向下（功能风险评估）'

        prompt = f"""请基于以下完整的调用链信息进行{'向上' if direction == 'upwards' else '向下'}链路分析：

【分析任务】
- 方向: {direction_cn}
- 变更方法: {class_name}.{method_name}
- 变更类型: {method_info.get('change_type', 'UNKNOWN')}
"""

        # ── 第一部分：调用链完整拓扑 ──
        full_chain = None
        entry_points = []

        if baseline and version:
            full_chain = self._load_chain_from_disk(
                baseline, version, direction, class_name, method_name)

        if full_chain:
            chain_tree = full_chain.get('chain_tree')
            entry_points = full_chain.get('entry_points', [])

            if chain_tree:
                topology_lines = []
                self._format_chain_topology(
                    chain_tree, direction, topology_lines, depth=0, is_root=True)
                topology_text = '\n'.join(topology_lines)
                prompt += f"""
【调用链完整拓扑】
（缩进表示调用深度，箭头表示调用方向，行号来自源码中的调用点）

{topology_text}
"""

        # ── 第二部分：入口/出口点分类 ──
        if direction == 'upwards' and entry_points:
            entry_by_type = {}
            for ep in entry_points:
                rt = ep.get('root_type', 'UNKNOWN')
                entry_by_type.setdefault(rt, []).append(ep)

            entry_type_labels = {
                'HTTP_API': 'HTTP API端点', 'SCHEDULED_TASK': '定时任务',
                'EVENT_LISTENER': '事件监听器', 'MESSAGE_CONSUMER': '消息队列消费者',
                'CONTROLLER_BY_CONVENTION': 'Controller（约定）',
                'NO_STATIC_CALLER': '无静态调用者（可能是动态调用）'
            }

            prompt += f"\n【入口点分类汇总】(共 {len(entry_points)} 个)\n"
            for rt, eps in sorted(entry_by_type.items()):
                label = entry_type_labels.get(rt, rt)
                prompt += f"\n{label} ({len(eps)} 个):\n"
                for ep in eps[:5]:  # 每类最多显示5个
                    pc = ep.get('package_class', '?')
                    ms = ep.get('method_signature', '?')
                    prompt += f"  - {pc}.{ms}\n"
                if len(eps) > 5:
                    prompt += f"  ... 还有 {len(eps) - 5} 个\n"

        elif direction == 'downwards' and full_chain:
            chain_tree = full_chain.get('chain_tree')
            if chain_tree:
                total_nodes = len(self._collect_chain_methods(chain_tree))
                prompt += f"\n【链路规模】\n- 总节点数: {total_nodes}\n"

        # ── 第三部分：链路中各方法源码 ──
        if full_chain and full_chain.get('chain_tree'):
            chain_methods = self._collect_chain_methods(full_chain['chain_tree'])
            # 优先展示变更方法（ADDED/MODIFIED/DELETED）
            changed = [m for m in chain_methods if m['change_type'] != 'UNCHANGED']
            unchanged = [m for m in chain_methods if m['change_type'] == 'UNCHANGED']

            # 限制总数避免上下文溢出
            methods_to_show = changed + unchanged[:max(0, 15 - len(changed))]

            bodies = self._fetch_method_bodies(baseline, version, methods_to_show)

            if bodies:
                prompt += "\n【链路中各方法详情】\n"
                for m in methods_to_show:
                    key = f"{m['class_name']}.{m['method_name']}"
                    body = bodies.get(key, {})
                    if not body:
                        continue

                    sig = m.get('method_signature', m['method_name'])
                    ct_map = {'ADDED': '[新增]', 'MODIFIED': '[修改]', 'DELETED': '[删除]', 'UNCHANGED': ''}
                    ct_tag = ct_map.get(m['change_type'], '')

                    prompt += f"\n### {key}.{sig} {ct_tag} (深度={m['depth']})\n"
                    if body.get('annotations'):
                        prompt += f"注解: {body['annotations']}\n"
                    prompt += f"签名: {body.get('access_modifier', '')} {body.get('return_type', 'void')} {m['method_name']}({body.get('parameters', '')})\n"
                    prompt += f"```java\n{body.get('body', '(源码未获取)')}\n```\n"
        elif entry_points and not full_chain:
            # 回退：仅有 entry_points 信息
            prompt += "\n【入口点信息】(链拓扑文件未加载，仅显示入口点)\n"
            for i, entry in enumerate(entry_points[:10], 1):
                prompt += (f"{i}. [{entry.get('root_type', 'N/A')}] "
                          f"{entry.get('package_class', 'N/A')}."
                          f"{entry.get('method_signature', 'N/A')}\n")

        # ── 第四部分：分析要求 ──
        if direction == 'upwards':
            prompt += """
【分析要求】
**重要：请在你的分析报告最开头，首先输出【调用链路图谱】章节——直接引用上文【调用链完整拓扑】中的图谱结构（可简化为 类名.方法名 格式，保留缩进层次和箭头方向），作为用户对照的基准。然后再按以下要求逐层分析：**

1. **调用链路逐层分析**
   - 从入口点到变更方法的每一层调用中，变更如何传递影响
   - CHA推断的调用注明不确定性
   - 识别间接影响的模块和功能

2. **入口点影响面**
   - 每个入口 API / 定时任务 / 事件监听器受到的具体影响
   - 对外部调用方（前端、第三方）的兼容性影响
   - 如果入口方法本身有变更，重点分析 API 契约变化

3. **数据流与状态变化追踪**
   - 参数在各层方法间如何传递和变换
   - 数据库操作的影响（表、SQL类型、事务范围）
   - 缓存、消息队列等中间件的级联影响

4. **风险评估（按入口点分组）**
   - 高风险变更（数据破坏、资金安全、权限绕过）
   - 中风险变更（性能退化、兼容性）
   - 低风险变更（内部实现调整）
   - CHA推断的调用注明风险置信度

5. **端到端测试策略**
   - 按入口点分别设计测试场景（含输入、预期、优先级）
   - 回归测试清单（受影响的核心链路）
   - 性能测试建议（如涉及SQL变更）

请使用中文回答，结合源码细节给出具体可执行的分析。"""
        else:
            prompt += """
【分析要求】
**重要：请在你的分析报告最开头，首先输出【调用链路图谱】章节——直接引用上文【调用链完整拓扑】中的图谱结构（可简化为 类名.方法名 格式，保留缩进层次和箭头方向），作为用户对照的基准。然后再按以下要求分析：**

请基于以上完整的调用链拓扑和源码，分析变更方法向下调用链的功能风险：

1. **调用链路逐层分析**
   - 从变更方法到末端方法的每一层调用关系和功能
   - 识别关键的依赖节点和SQL操作
   - CHA推断的调用注明不确定性

2. **下游影响评估**
   - 各下游方法的变更影响（数据修改、异常传播）
   - SQL操作的风险（表变更、性能、数据一致性）
   - 外部依赖（RPC、HTTP调用、消息队列）的稳定性

3. **数据流追踪**
   - 变更方法的返回值如何被下游使用
   - 数据库读写链路和事务边界
   - 可能的副作用（缓存更新、事件发布）

4. **风险评估**
   - 高风险：N+1查询、大事务、无WHERE的UPDATE/DELETE
   - 中风险：异常未处理、缓存不一致
   - 低风险：日志、审计等辅助功能

5. **测试策略**
   - 各下游方法的单元/集成测试场景设计
   - SQL验证（执行计划、锁、回滚）
   - 性能基准测试建议

请使用中文回答，结合源码细节给出具体可执行的分析。"""

        return prompt
    
    def _get_system_prompt(self, analysis_type: str) -> str:
        """获取系统提示词"""
        if analysis_type == 'method':
            return """你是一名资深Java开发工程师及代码审计专家。请根据提供的变更前/后代码，生成专业、结构化、可直接用于技术评审或发布说明的《变更前后代码对比与分析报告》。

约束要求：
1. 使用中文，严格遵循六部分输出结构，不增删章节
2. 语言专业、客观、技术向，符合企业级代码评审标准
3. 所有表格、代码块、流程图必须符合Markdown规范
4. 直接输出报告内容，无需解释生成过程"""
        else:
            return """你是一位拥有 15 年经验的资深 Java 代码审查专家和测试架构师。你的任务是基于完整的调用链拓扑（含调用顺序、深度关系、调用行号）、每个方法的源码、以及入口点分类信息，识别变更的级联影响、评估系统风险，并给出可执行的端到端测试策略。

分析原则：
1. 使用中文，结构清晰，深度分析
2. 必须基于提供的链拓扑理解调用顺序，逐层分析而非笼统概括
3. 必须基于方法源码理解每个节点的具体功能，引用源码细节支撑判断
4. 区分 DIRECT（确定调用，高置信度）和 CHA_RESOLVED（接口多态推断，需注明不确定性）
5. 按入口点类型（HTTP API / 定时任务 / 消息队列 / 事件监听器）分别评估影响面
6. SQL 节点需关注表操作类型、WHERE 条件、事务边界、性能风险
7. 测试建议必须具体可执行（含具体输入参数、预期结果、优先级 P0/P1/P2）
8. 风险评估结合业务场景，避免泛泛而谈，引用的源码行号需标注"""
    
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
            analysis_prompt = self._build_chain_prompt(chain_data or {}, direction, '', '')
        
        return {
            'system_prompt': system_prompt,
            'analysis_prompt': analysis_prompt
        }
    
    def _call_llm_api(self, prompt: str, system_prompt: str) -> str:
        """调用 LLM API（公司内网版本）"""
        # 如果未配置 LLM API，返回模拟结果
        if not self.api_url or not self.api_key:
            return self._get_mock_result(prompt)

        try:
            import requests

            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}"
            }

            # 公司内网 API 请求格式
            payload = {
                "inputs": {"query": f"{system_prompt}\n\n{prompt}"},
                "response_mode": "blocking",
                "user": "pipeline-analysis-v3"
            }

            max_retries = 3
            base_delay = 5  # 首次重试等待 5 秒
            last_error = None

            for attempt in range(max_retries):
                try:
                    response = requests.post(
                        f"{self.api_url}/completion-messages",
                        json=payload,
                        headers=headers,
                        timeout=300
                    )
                    if response.status_code == 200:
                        result = response.json()
                        # 根据公司内网 API 响应格式提取结果
                        if 'answer' in result:
                            return result['answer']
                        elif 'text' in result:
                            return result['text']
                        else:
                            return f"API响应格式异常: {result}"
                    else:
                        # HTTP 错误不重试
                        return f"API调用失败: HTTP {response.status_code}\n{response.text}"
                except Exception as e:
                    last_error = str(e)
                    if attempt < max_retries - 1:
                        delay = base_delay * (2 ** attempt)
                        print(f"[LLM] API 调用异常，{delay}s 后重试({attempt + 1}/{max_retries}): {last_error}")
                        time.sleep(delay)
            
            return f"请求异常(已重试{max_retries}次): {last_error}"
        except Exception as e:
            return f"请求异常: {str(e)}"
    
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
