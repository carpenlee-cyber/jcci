"""
变更类型分析器：根据 diff 信息自动标记 class、method、field 的 change_type
"""
import sqlite3
import json
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')

class ChangeTypeAnalyzer:
    """变更类型分析器"""
    
    def __init__(self, db_path):
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        self.cursor = self.conn.cursor()
    
    def analyze_and_mark_changes(self, diff_parse_map, commit_new, commit_old, project_id):
        """
        分析 diff 并标记变更类型
        
        Args:
            diff_parse_map: diff 解析结果，格式为 {filepath: {'line_num_added': [], 'line_num_removed': [], ...}}
            commit_new: 新提交 ID
            commit_old: 旧提交 ID
            project_id: 项目 ID
        """
        logging.info(f"开始分析变更类型 (project_id={project_id})")
        
        try:
            # 1. 识别新增和删除的文件
            added_files = []
            deleted_files = []
            modified_files = []
            
            for filepath, diff_info in diff_parse_map.items():
                if not filepath.endswith('.java'):
                    continue
                
                line_added = diff_info.get('line_num_added', [])
                line_removed = diff_info.get('line_num_removed', [])
                
                # 判断文件是新增、删除还是修改
                if not line_removed and line_added:
                    # 只有新增行，没有删除行 → 可能是新增文件
                    # 需要进一步检查是否是全新文件
                    added_files.append(filepath)
                elif not line_added and line_removed:
                    # 只有删除行，没有新增行 → 可能是删除文件
                    deleted_files.append(filepath)
                else:
                    # 既有新增又有删除 → 修改文件
                    modified_files.append(filepath)
            
            logging.info(f"  新增文件: {len(added_files)} 个")
            if added_files:
                for f in added_files:
                    logging.info(f"    - {f}")
            
            logging.info(f"  删除文件: {len(deleted_files)} 个")
            if deleted_files:
                for f in deleted_files:
                    logging.info(f"    - {f}")
            
            logging.info(f"  修改文件: {len(modified_files)} 个")
            if modified_files:
                for f in modified_files:
                    logging.info(f"    - {f}")
            
            # 2. 标记 Class 的变更类型
            self._mark_class_changes(added_files, deleted_files, modified_files, project_id, commit_new, commit_old)
            
            # 3. 标记 Method 的变更类型
            self._mark_method_changes(diff_parse_map, project_id, commit_new, commit_old)
            
            # 4. 标记 Field 的变更类型（可选）
            self._mark_field_changes(diff_parse_map, project_id, commit_new, commit_old)
            
            self.conn.commit()
            logging.info("✅ 变更类型分析完成！")
            
            # 5. 统计结果
            self._print_statistics(project_id)
            
        except Exception as e:
            logging.error(f"❌ 分析失败: {e}")
            self.conn.rollback()
            raise
    
    def _mark_class_changes(self, added_files, deleted_files, modified_files, project_id, commit_new, commit_old):
        """标记 Class 的变更类型"""
        
        # 标记新增的 Class
        for filepath in added_files:
            self.cursor.execute('''
                UPDATE class 
                SET change_type = 'ADDED'
                WHERE project_id = ?
                AND filepath LIKE ?
                AND commit_or_branch = ?
            ''', (project_id, f'%{filepath}', commit_new))
            
            count = self.cursor.rowcount
            if count > 0:
                logging.info(f"  ✓ 标记 {count} 个类为 ADDED: {filepath}")
        
        # 标记删除的 Class（在旧版本中）
        for filepath in deleted_files:
            self.cursor.execute('''
                UPDATE class 
                SET change_type = 'DELETED'
                WHERE project_id = 0
                AND filepath LIKE ?
                AND commit_or_branch = ?
            ''', (f'%{filepath}', commit_old))
            
            count = self.cursor.rowcount
            if count > 0:
                logging.info(f"  ✓ 标记 {count} 个类为 DELETED: {filepath}")
        
        # 标记修改的 Class
        for filepath in modified_files:
            self.cursor.execute('''
                UPDATE class 
                SET change_type = 'MODIFIED'
                WHERE project_id = ?
                AND filepath LIKE ?
                AND commit_or_branch = ?
                AND change_type = 'UNCHANGED'
            ''', (project_id, f'%{filepath}', commit_new))
            
            count = self.cursor.rowcount
            if count > 0:
                logging.info(f"  ✓ 标记 {count} 个类为 MODIFIED: {filepath}")
    
    def _mark_method_changes(self, diff_parse_map, project_id, commit_new, commit_old):
        """
        标记 Method 的变更类型
        
        核心原则：
        - project_id = 0 (基线): 只能标记为 UNCHANGED 或 DELETED
        - project_id > 0 (增量): 只能标记为 UNCHANGED、ADDED 或 MODIFIED
        
        实现逻辑（基于精确的行号映射 + 方法签名对比）：
        1. get_diff_info 已提供精确的 line_num_added 和 line_num_removed
        2. 查找与这些精确行号有交集的方法
        3. 通过方法签名跨版本对比判定 ADDED vs MODIFIED
        4. 未触及的方法保持 UNCHANGED（从基线继承，无需分析）
        """
        
        for filepath, diff_info in diff_parse_map.items():
            if not filepath.endswith('.java'):
                continue
            
            line_added = diff_info.get('line_num_added', [])
            line_removed = diff_info.get('line_num_removed', [])
            
            if not line_added and not line_removed:
                continue
            
            # ========== 处理基线 (project_id = 0) ==========
            if project_id == 0:
                # 基线只能标记 DELETED
                # 逻辑：如果方法的所有行都在 line_removed 中，则标记为 DELETED
                if not line_removed:
                    continue
                
                removed_lines_set = set(line_removed)
                
                # 找出所有与删除行有交集的方法（使用精确的行号范围）
                min_removed = min(line_removed)
                max_removed = max(line_removed)
                
                self.cursor.execute('''
                    SELECT m.method_id, m.method_name, c.class_name,
                           m.start_line, m.end_line
                    FROM methods m
                    JOIN class c ON m.class_id = c.class_id
                    WHERE m.project_id = 0
                    AND c.commit_or_branch = ?
                    AND c.filepath LIKE ?
                    AND m.change_type = 'UNCHANGED'
                    AND m.start_line <= ?
                    AND m.end_line >= ?
                ''', (commit_old, f'%{filepath}', max_removed, min_removed))
                
                affected_methods = self.cursor.fetchall()
                
                for method_id, method_name, class_name, start_line, end_line in affected_methods:
                    # 检查该方法的所有行是否都在 line_removed 中
                    method_lines = set(range(start_line, end_line + 1))
                    
                    # 只有当方法的所有行都被删除时，才标记为 DELETED
                    if method_lines.issubset(removed_lines_set):
                        self.cursor.execute('''
                            UPDATE methods 
                            SET change_type = 'DELETED'
                            WHERE method_id = ?
                        ''', (method_id,))
                        logging.info(f"    - [基线] 标记方法为 DELETED: {class_name}.{method_name}() lines {start_line}-{end_line}")
                    # 否则，保持 UNCHANGED（基线中的方法没有被完全删除）
            
            # ========== 处理增量 (project_id > 0) ==========
            else:
                # 核心思路：
                # 1. 找出新版本中与变更行（新增或删除）有交集的方法
                # 2. 对这些方法，检查它们在旧版本（基线）中是否存在
                # 3. 如果不存在 -> ADDED；如果存在 -> MODIFIED
                # 4. 未触及的方法保持 UNCHANGED（从基线继承，无需重复分析）
                
                all_changed_lines = set(line_added) | set(line_removed)
                
                if not all_changed_lines:
                    continue
                
                # 找出所有与变更行有交集的方法
                min_line = min(all_changed_lines)
                max_line = max(all_changed_lines)
                
                self.cursor.execute('''
                    SELECT DISTINCT m.method_id, m.method_name, m.parameters, c.class_name,
                           m.start_line, m.end_line
                    FROM methods m
                    JOIN class c ON m.class_id = c.class_id
                    WHERE m.project_id = ?
                    AND c.commit_or_branch = ?
                    AND c.filepath LIKE ?
                    AND m.change_type = 'UNCHANGED'
                    AND m.start_line <= ?
                    AND m.end_line >= ?
                ''', (project_id, commit_new, f'%{filepath}', max_line, min_line))
                
                candidate_methods = self.cursor.fetchall()
                
                for method_id, method_name, parameters, class_name, start_line, end_line in candidate_methods:
                    method_lines = set(range(start_line, end_line + 1))
                    
                    # 检查方法是否与变更行有实际交集（精确匹配）
                    if not (method_lines & all_changed_lines):
                        continue
                    
                    # 构建方法签名用于跨版本匹配
                    try:
                        params = json.loads(parameters) if parameters else []
                        param_types = ','.join([p['parameter_type'] for p in params])
                        method_signature = f"{class_name}.{method_name}({param_types})"
                    except:
                        method_signature = f"{class_name}.{method_name}()"
                    
                    # 在基线 (project_id=0) 中查找相同文件、相同方法名的方法
                    self.cursor.execute('''
                        SELECT m2.method_id
                        FROM methods m2
                        JOIN class c2 ON m2.class_id = c2.class_id
                        WHERE m2.project_id = 0
                        AND c2.commit_or_branch = ?
                        AND c2.filepath LIKE ?
                        AND m2.method_name = ?
                        LIMIT 1
                    ''', (commit_old, f'%{filepath}', method_name))
                    
                    old_method = self.cursor.fetchone()
                    
                    if old_method is None:
                        # 旧版本中找不到相同名称的方法 -> ADDED
                        self.cursor.execute('''
                            UPDATE methods 
                            SET change_type = 'ADDED'
                            WHERE method_id = ?
                        ''', (method_id,))
                        logging.info(f"    - [增量] 标记方法为 ADDED: {method_signature} lines {start_line}-{end_line}")
                    else:
                        # 旧版本中存在该方法 -> MODIFIED
                        self.cursor.execute('''
                            UPDATE methods 
                            SET change_type = 'MODIFIED'
                            WHERE method_id = ?
                        ''', (method_id,))
                        logging.info(f"    - [增量] 标记方法为 MODIFIED: {method_signature} lines {start_line}-{end_line}")
                
                # 关键优化：将增量中未被diff触及的方法标记为 UNCHANGED
                # 这些方法不需要分析，直接从基线继承即可
                self.cursor.execute('''
                    UPDATE methods 
                    SET change_type = 'UNCHANGED'
                    WHERE project_id = ?
                    AND class_id IN (
                        SELECT c.class_id 
                        FROM class c 
                        WHERE c.project_id = ? 
                        AND c.commit_or_branch = ?
                        AND c.filepath LIKE ?
                    )
                    AND change_type = 'UNCHANGED'
                ''', (project_id, project_id, commit_new, f'%{filepath}'))
    
    def _mark_field_changes(self, diff_parse_map, project_id, commit_new, commit_old):
        """标记 Field 的变更类型（简化版）"""
        # TODO: 实现字段的变更类型标记
        pass
    
    def _print_statistics(self, project_id):
        """打印统计信息"""
        
        print("\n" + "=" * 80)
        print("变更类型统计")
        print("=" * 80)
        
        # Class 统计
        self.cursor.execute('''
            SELECT change_type, COUNT(*) 
            FROM class 
            WHERE project_id = ?
            GROUP BY change_type
            ORDER BY change_type
        ''', (project_id,))
        
        print("\nClass 表变更类型分布:")
        class_stats = self.cursor.fetchall()
        if not class_stats:
            print("  (无变更记录)")
        else:
            for change_type, count in class_stats:
                print(f"  {change_type}: {count} 个")
        
        # Method 统计
        self.cursor.execute('''
            SELECT change_type, COUNT(*) 
            FROM methods 
            WHERE project_id = ?
            GROUP BY change_type
            ORDER BY change_type
        ''', (project_id,))
        
        print("\nMethods 表变更类型分布:")
        method_stats = self.cursor.fetchall()
        unchanged_count = 0
        if not method_stats:
            print("  (无变更记录)")
        else:
            for change_type, count in method_stats:
                print(f"  {change_type}: {count} 个")
                if change_type == 'UNCHANGED':
                    unchanged_count = count
        
        # 性能优化提示
        if unchanged_count > 0 and project_id > 0:
            print(f"\n  ⚡ 性能优化: {unchanged_count} 个 UNCHANGED 方法将直接从基线继承，无需重复分析")
        
        # 详细列出变更的类
        changed_classes = self.get_changed_classes(project_id)
        if changed_classes:
            print(f"\n变更的类详情 ({len(changed_classes)} 个):")
            for cls in changed_classes[:20]:  # 最多显示20个
                print(f"  [{cls['change_type']}] {cls['package_name']}.{cls['class_name']}")
            if len(changed_classes) > 20:
                print(f"  ... 还有 {len(changed_classes) - 20} 个类")
        
        # 详细列出变更的方法
        changed_methods = self.get_changed_methods(project_id)
        if changed_methods:
            print(f"\n变更的方法详情 ({len(changed_methods)} 个):")
            for method in changed_methods[:30]:  # 最多显示30个
                params = json.loads(method['parameters']) if method['parameters'] else []
                param_str = ', '.join([p.get('parameter_type', '') for p in params])
                print(f"  [{method['change_type']}] {method['class_name']}.{method['method_name']}({param_str}) -> {method['return_type']}")
            if len(changed_methods) > 30:
                print(f"  ... 还有 {len(changed_methods) - 30} 个方法")
        
        print("=" * 80)
    
    def get_changed_classes(self, project_id, change_type=None):
        """
        查询变更的类
        
        Args:
            project_id: 项目 ID
            change_type: 变更类型过滤 (ADDED/MODIFIED/DELETED)，None 表示全部
        
        Returns:
            list: 变更的类列表
        """
        if change_type:
            self.cursor.execute('''
                SELECT class_name, package_name, class_type, filepath, change_type
                FROM class
                WHERE project_id = ?
                AND change_type = ?
                ORDER BY class_name
            ''', (project_id, change_type))
        else:
            self.cursor.execute('''
                SELECT class_name, package_name, class_type, filepath, change_type
                FROM class
                WHERE project_id = ?
                AND change_type != 'UNCHANGED'
                ORDER BY change_type, class_name
            ''', (project_id,))
        
        return [
            {
                'class_name': row[0],
                'package_name': row[1],
                'class_type': row[2],
                'filepath': row[3],
                'change_type': row[4]
            }
            for row in self.cursor.fetchall()
        ]
    
    def get_changed_methods(self, project_id, change_type=None):
        """
        查询变更的方法
        
        Args:
            project_id: 项目 ID
            change_type: 变更类型过滤 (ADDED/MODIFIED/DELETED)，None 表示全部
        
        Returns:
            list: 变更的方法列表
        """
        if change_type:
            self.cursor.execute('''
                SELECT c.class_name, m.method_name, m.parameters, m.return_type, m.change_type
                FROM methods m
                JOIN class c ON m.class_id = c.class_id
                WHERE m.project_id = ?
                AND m.change_type = ?
                ORDER BY c.class_name, m.method_name
            ''', (project_id, change_type))
        else:
            self.cursor.execute('''
                SELECT c.class_name, m.method_name, m.parameters, m.return_type, m.change_type
                FROM methods m
                JOIN class c ON m.class_id = c.class_id
                WHERE m.project_id = ?
                AND m.change_type != 'UNCHANGED'
                ORDER BY m.change_type, c.class_name, m.method_name
            ''', (project_id,))
        
        return [
            {
                'class_name': row[0],
                'method_name': row[1],
                'parameters': row[2],
                'return_type': row[3],
                'change_type': row[4]
            }
            for row in self.cursor.fetchall()
        ]
    
    def close(self):
        """关闭数据库连接"""
        self.conn.close()
