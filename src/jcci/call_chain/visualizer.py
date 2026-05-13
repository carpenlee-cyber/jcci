"""
调用链可视化显示工具

将调用链分析结果转换为易读的文本格式进行展示。
支持向上和向下两个方向的调用链展示。
"""

import logging
from typing import List, Dict, Any
from .models import CallChainNode

logger = logging.getLogger(__name__)


class CallChainVisualizer:
    """
    调用链可视化显示工具
    
    将复杂的调用链树结构转换为简洁的文本格式，便于用户快速理解。
    """
    
    @staticmethod
    def format_upwards_chains(upwards_result: Dict[str, Any]) -> str:
        """
        格式化向上调用链（影响面分析）
        
        Args:
            upwards_result: 向上分析的结果字典
        
        Returns:
            str: 格式化后的文本
        """
        lines = []
        
        # 添加metadata信息
        metadata = upwards_result.get('metadata', {})
        lines.append("=" * 80)
        lines.append("向上调用链分析 - 元数据信息")
        lines.append("=" * 80)
        lines.append(f"项目: {metadata.get('project_name', 'N/A')}")
        lines.append(f"用户名: {metadata.get('username', 'N/A')}")
        lines.append(f"Git URL: {metadata.get('git_url', 'N/A')}")
        # 兼容两种字段名: commit_old/commit_new 或 baseline_commit/target_commit
        commit_old = metadata.get('commit_old') or metadata.get('baseline_commit', 'N/A')
        commit_new = metadata.get('commit_new') or metadata.get('target_commit', 'N/A')
        lines.append(f"Commit范围: {commit_old}..{commit_new}")
        lines.append(f"分析版本: {metadata.get('analysis_version', 'N/A')}")
        lines.append(f"最大深度: {metadata.get('max_depth', 'N/A')}")
        lines.append(f"总变更方法数: {metadata.get('total_methods', 0)}")
        lines.append(f"成功分析: {metadata.get('successful_chains', 0)}")
        lines.append(f"失败分析: {metadata.get('failed_chains', 0)}")
        
        # 功能启用状态
        features = metadata.get('features_enabled', {})
        if features:
            lines.append("")
            lines.append("功能启用状态:")
            lines.append(f"  - 类层次分析 (CHA): {'是' if features.get('class_hierarchy_analysis') else '否'}")
            lines.append(f"  - 入口检测: {'是' if features.get('entry_detection') else '否'}")
        
        lines.append("")
        lines.append("=" * 80)
        lines.append("")
        
        lines.append("\n向上调用链分析（影响面：谁调用了变更方法？）")
        lines.append("")
        
        impact_chains = upwards_result.get('impact_chains', [])
        
        # 收集所有入口点
        all_entry_points = []
        for chain_data in impact_chains:
            entry_points = chain_data.get('entry_points', [])
            for entry in entry_points:
                # entry结构: package_class, method_signature, root_type
                package_class = entry.get('package_class', '')
                method_signature = entry.get('method_signature', '')
                
                # 从package_class中提取类名
                class_name = package_class.split('.')[-1] if package_class else ''
                
                # 从method_signature中提取方法名（去掉参数部分）
                method_name = method_signature.split('(')[0] if method_signature else ''
                
                entry_key = f"{class_name}.{method_name}"
                if entry_key not in [e['key'] for e in all_entry_points]:
                    all_entry_points.append({
                        'key': entry_key,
                        'class_name': class_name,
                        'method_name': method_name,
                        'package_class': package_class,
                        'method_signature': method_signature,
                        'root_type': entry.get('root_type', 'UNKNOWN'),
                        'depth_from_change': entry.get('depth_from_change', 0),
                        'api_paths': entry.get('api_paths', [])  # 添加API路径
                    })
        
        # 展示所有入口点汇总
        if all_entry_points:
            lines.append("=" * 80)
            lines.append(f"🎯 发现的入口点 ({len(all_entry_points)}个):")
            lines.append("=" * 80)
            for idx, entry in enumerate(all_entry_points, 1):
                entry_tag = "(入口)" if entry['root_type'] in ['HTTP_API', 'SCHEDULED_TASK', 'EVENT_LISTENER',
                                                                  'MESSAGE_CONSUMER', 'CONTROLLER_BY_CONVENTION'] else ""
                
                # 构建显示文本
                display_text = f"  {idx}. {entry['key']}{entry_tag} [{entry['root_type']}]"
                
                # 如果有API路径，添加到显示中
                api_paths = entry.get('api_paths', [])
                if api_paths:
                    # 格式化API路径，例如: [POST]/coupon/delete/{id}
                    api_path_str = ', '.join(api_paths)
                    display_text += f" - {api_path_str}"
                
                lines.append(display_text)
                
                # 展示该入口点关联的调用链
                related_chains = []
                for chain_idx, chain_data in enumerate(impact_chains, 1):
                    method_info = chain_data.get('method_info', {})
                    change_type = method_info.get('change_type', 'UNKNOWN')
                    change_type_display = change_type if change_type else 'UNKNOWN'
                    
                    # 检查调用链中是否包含此入口点
                    chain_tree = chain_data.get('chain', {})
                    if CallChainVisualizer._contains_entry_point(chain_tree, entry['class_name'], entry['method_name']):
                        related_chains.append({
                            'chain_idx': chain_idx,
                            'method_info': method_info
                        })
                
                if related_chains:
                    lines.append(f"     关联的调用链:")
                    for rc in related_chains:
                        method_info = rc['method_info']
                        class_name = method_info.get('class_name', '')
                        method_name = method_info.get('method_name', '')
                        change_type = method_info.get('change_type', 'UNKNOWN')
                        change_type_display = change_type if change_type else 'UNKNOWN'
                        lines.append(f"       - 调用链 {rc['chain_idx']}: {change_type_display}方法 {class_name}.{method_name}")
            lines.append("")
            lines.append("=" * 80)
            lines.append("")
        
        # 展示详细的调用链
        for idx, chain_data in enumerate(impact_chains, 1):
            method_info = chain_data.get('method_info', {})
            class_name = method_info.get('class_name', '')
            method_name = method_info.get('method_name', '')
            change_type = method_info.get('change_type', 'UNKNOWN')
            
            # 使用原始英文变更类型（用于标题）
            change_type_display = change_type if change_type else 'UNKNOWN'
            
            lines.append(f"调用链 {idx}：{change_type_display}方法 {class_name}.{method_name}")
            
            # 获取调用链树
            chain_tree = chain_data.get('chain', {})
            entry_points = chain_data.get('entry_points', [])
            
            # 递归展示调用链
            CallChainVisualizer._format_chain_node(
                chain_tree, 
                lines, 
                depth=0, 
                is_root=True,
                direction='upwards'
            )
            
            lines.append("")
        
        return "\n".join(lines)
    
    @staticmethod
    def format_downwards_chains(downwards_result: Dict[str, Any]) -> str:
        """
        格式化向下调用链（功能风险分析）
        
        Args:
            downwards_result: 向下分析的结果字典
        
        Returns:
            str: 格式化后的文本
        """
        lines = []
        
        # 添加metadata信息
        metadata = downwards_result.get('metadata', {})
        lines.append("=" * 80)
        lines.append("向下调用链分析 - 元数据信息")
        lines.append("=" * 80)
        lines.append(f"项目: {metadata.get('project_name', 'N/A')}")
        lines.append(f"用户名: {metadata.get('username', 'N/A')}")
        lines.append(f"Git URL: {metadata.get('git_url', 'N/A')}")
        # 兼容两种字段名: commit_old/commit_new 或 baseline_commit/target_commit
        commit_old = metadata.get('commit_old') or metadata.get('baseline_commit', 'N/A')
        commit_new = metadata.get('commit_new') or metadata.get('target_commit', 'N/A')
        lines.append(f"Commit范围: {commit_old}..{commit_new}")
        lines.append(f"分析版本: {metadata.get('analysis_version', 'N/A')}")
        lines.append(f"最大深度: {metadata.get('max_depth', 'N/A')}")
        lines.append(f"总变更方法数: {metadata.get('total_methods', 0)}")
        lines.append(f"成功分析: {metadata.get('successful_chains', 0)}")
        lines.append(f"失败分析: {metadata.get('failed_chains', 0)}")
        
        lines.append("")
        lines.append("=" * 80)
        lines.append("")
        
        lines.append("\n向下调用链分析（功能风险：变更方法调用了谁？）")
        lines.append("")
        
        call_chains = downwards_result.get('call_chains', [])
        
        for idx, chain_data in enumerate(call_chains, 1):
            method_info = chain_data.get('method_info', {})
            class_name = method_info.get('class_name', '')
            method_name = method_info.get('method_name', '')
            change_type = method_info.get('change_type', 'UNKNOWN')
            
            # 使用原始英文变更类型（用于标题）
            change_type_display = change_type if change_type else 'UNKNOWN'
            
            lines.append(f"调用链 {idx}：{change_type_display}方法 {class_name}.{method_name}")
            
            # 获取调用链树
            chain_tree = chain_data.get('chain', {})
            
            # 递归展示调用链
            CallChainVisualizer._format_chain_node(
                chain_tree, 
                lines, 
                depth=0, 
                is_root=True,
                direction='downwards'
            )
            
            lines.append("")
        
        return "\n".join(lines)
    
    @staticmethod
    def _contains_entry_point(node: Dict[str, Any], class_name: str, method_name: str) -> bool:
        """
        递归检查调用链节点中是否包含指定的入口点
        
        Args:
            node: 调用链节点字典
            class_name: 类名
            method_name: 方法名
        
        Returns:
            bool: 是否包含该入口点
        """
        if not node:
            return False
        
        # 检查当前节点
        if node.get('class_name') == class_name and node.get('method_name') == method_name:
            return True
        
        # 递归检查子节点
        children = node.get('children', [])
        for child in children:
            if CallChainVisualizer._contains_entry_point(child, class_name, method_name):
                return True
        
        return False
    
    @staticmethod
    def _format_chain_node(node: Dict[str, Any], lines: List[str], 
                          depth: int, is_root: bool, direction: str):
        """
        递归格式化调用链节点
        
        Args:
            node: 调用链节点字典
            lines: 输出行列表
            depth: 当前深度
            is_root: 是否为根节点
            direction: 方向 ('upwards' 或 'downwards')
        """
        if not node:
            return
        
        class_name = node.get('class_name', '')
        method_name = node.get('method_name', '')
        method_signature = node.get('method_signature', '')
        change_type = node.get('change_type', 'UNKNOWN')
        root_type = node.get('root_type', 'UNKNOWN')
        invocation_lines = node.get('invocation_lines', [])
        children = node.get('children', [])
        dao_info = node.get('dao_info')  # v3.3: SQL节点信息
        
        # 构建节点标签
        # 使用原始英文变更类型
        change_type_tag = change_type if change_type else 'UNKNOWN'
        
        # 判断是否为入口点
        is_entry = root_type in ['HTTP_API', 'SCHEDULED_TASK', 'EVENT_LISTENER',
                                  'MESSAGE_CONSUMER', 'CONTROLLER_BY_CONVENTION']
        entry_tag = "(入口)" if is_entry else ""
        
        # 构建缩进前缀
        indent = "\t" * depth
        
        # v3.3: 检查是否为SQL节点（Mapper方法且有dao_info）
        is_sql_node = dao_info and isinstance(dao_info, dict) and 'sql_type' in dao_info
        
        if is_sql_node:
            # v3.3: 格式化SQL节点（增强版）
            CallChainVisualizer._format_sql_node(node, dao_info, lines, depth)
        elif is_root:
            # 根节点特殊格式
            lines.append(f"{indent}{class_name}.{method_name} ({change_type_tag}){entry_tag}")
        else:
            # 非根节点：显示调用关系
            if invocation_lines:
                lines_str = ",".join([str(line) for line in invocation_lines[:3]])  # 最多显示3个行号
                if len(invocation_lines) > 3:
                    lines_str += f"...(+{len(invocation_lines)-3})"
                arrow = f"{indent}--行号{lines_str}-->"
                lines.append(f"{arrow}")
            
            lines.append(f"{indent}{class_name}.{method_name} ({change_type_tag}){entry_tag}")
        
        # 递归处理子节点
        for child in children:
            CallChainVisualizer._format_chain_node(
                child, 
                lines, 
                depth + 1, 
                is_root=False,
                direction=direction
            )
    
    @staticmethod
    def _format_sql_node(node: Dict[str, Any], dao_info: Dict, lines: List[str], depth: int):
        """
        v3.3: 格式化SQL节点（增强版）
        
        Args:
            node: 调用链节点字典
            dao_info: DAO分析结果（包含SQL信息）
            lines: 输出行列表
            depth: 当前深度
        """
        indent = "\t" * depth
        
        # 提取SQL信息
        sql_type = dao_info.get('sql_type', 'UNKNOWN').upper()
        tables = dao_info.get('tables', [])
        risk_level = dao_info.get('risk_level', 'LOW')
        perf_issues = dao_info.get('performance_issues', [])
        dynamic_conditions = dao_info.get('dynamic_conditions', [])
        has_where = dao_info.get('has_where', False)
        has_limit = dao_info.get('has_limit', False)
        estimated_rows = dao_info.get('estimated_rows', 'UNKNOWN')
        sql_content = dao_info.get('sql_content', '')  # ✅ 获取完整SQL语句
        
        # SQL类型图标
        sql_icons = {
            'SELECT': '🟦',
            'INSERT': '🟩',
            'UPDATE': '🟧',
            'DELETE': '🟥'
        }
        icon = sql_icons.get(sql_type, '⬜')
        
        # 风险等级徽章
        risk_badges = {
            'LOW': '✅ LOW',
            'MEDIUM': 'ℹ️ MEDIUM',
            'HIGH': '⚠️ HIGH',
            'CRITICAL': '🔴 CRITICAL'
        }
        risk_badge = risk_badges.get(risk_level, f'ℹ️ {risk_level}')
        
        # 表名显示
        tables_str = ', '.join(tables) if tables else 'N/A'
        
        # WHERE和LIMIT状态
        where_status = '✅' if has_where else '❌ 缺失'
        limit_status = '✅' if has_limit else '❌ 无'
        
        # 第一行：SQL节点标题（显示完整SQL语句）
        if sql_content:
            # 清理SQL语句中的多余空白
            clean_sql = ' '.join(sql_content.split())
            lines.append(f"{indent}{icon} SQL: {clean_sql}")
        else:
            lines.append(f"{indent}{icon} SQL:{sql_type} [表: {tables_str}]")
        
        # 第二行开始：详细信息框
        # 使用固定宽度，确保所有行的字符数完全一致
        box_width = 50
        lines.append(f"{indent}    ┌{'─' * box_width}┐")
        
        # 计算字符串的显示宽度（考虑emoji占用2个字符宽度）
        def display_width(s: str) -> int:
            """计算字符串的显示宽度，emoji按2个字符计算"""
            width = 0
            for char in s:
                # emoji和其他特殊字符通常占用2个字符宽度
                if ord(char) > 0x1F000:  # emoji范围
                    width += 2
                else:
                    width += 1
            return width
        
        # 格式化框内行的辅助函数
        # 关键：确保每行的总长度（不包括indent和边框）严格等于box_width
        def format_box_line(emoji: str, label: str, value: str) -> str:
            """格式化框内行，确保右侧竖线对齐"""
            # 构建内容部分：emoji + 空格 + 标签 + 冒号 + 空格 + 值
            content = f"{emoji} {label}: {value}"
            # 计算内容的显示宽度
            content_width = display_width(content)
            # 计算需要的填充空格数
            padding_needed = box_width - content_width
            if padding_needed < 0:
                # 如果内容太长，截断
                content = content[:box_width]
                padding_needed = 0
            return f"{indent}    │ {content}{' ' * padding_needed}│"
        
        lines.append(format_box_line('📊', '操作类型', sql_type))
        lines.append(format_box_line('📋', '影响表', tables_str))
        lines.append(format_box_line('⚠️ ', '风险等级', risk_badge))
        lines.append(format_box_line('🔍', 'WHERE条件', where_status))
        lines.append(format_box_line('📄', 'LIMIT限制', limit_status))
        lines.append(format_box_line('📝', '预估行数', estimated_rows))
        
        lines.append(f"{indent}    └{'─' * box_width}┘")
        
        # 性能预警
        if perf_issues:
            lines.append(f"{indent}    ⚡ 性能预警:")
            for issue in perf_issues:
                issue_risk = issue.get('risk_level', 'LOW')
                issue_msg = issue.get('message', '')
                issue_suggestion = issue.get('suggestion', '')
                lines.append(f"{indent}      • [{issue_risk}] {issue_msg}")
                lines.append(f"{indent}        💡 建议: {issue_suggestion}")
        
        # 动态SQL条件
        if dynamic_conditions:
            lines.append(f"{indent}    🔄 动态SQL条件:")
            for cond in dynamic_conditions:
                lines.append(f"{indent}      • IF: {cond}")
    @staticmethod
    def print_bidirectional_summary(bidirectional_result: Dict[str, Any]):
        """
        打印双向分析摘要
        
        Args:
            bidirectional_result: 双向分析的完整结果
        """
        upwards = bidirectional_result.get('upwards', {})
        downwards = bidirectional_result.get('downwards', {})
        
        logger.info("\n" + "=" * 80)
        logger.info("📈 双向调用链分析摘要")
        logger.info("=" * 80)
        
        # 向上分析摘要
        upwards_meta = upwards.get('metadata', {})
        logger.info(f"\n【向上分析 - 影响面】")
        logger.info(f"  ✓ 成功: {upwards_meta.get('successful_chains', 0)}")
        logger.info(f"  ✗ 失败: {upwards_meta.get('failed_chains', 0)}")
        
        coverage_stats = upwards_meta.get('coverage_stats', {})
        logger.info(f"  🎯 覆盖率: {coverage_stats.get('coverage_rate_percent', 0)}%")
        logger.info(f"  🔍 入口点: {coverage_stats.get('entry_points_found', 0)}")
        logger.info(f"  🔗 CHA解析: {coverage_stats.get('cha_resolved_calls', 0)}")
        
        # 向下分析摘要
        downwards_meta = downwards.get('metadata', {})
        logger.info(f"\n【向下分析 - 功能风险】")
        logger.info(f"  ✓ 成功: {downwards_meta.get('successful_chains', 0)}")
        logger.info(f"  ✗ 失败: {downwards_meta.get('failed_chains', 0)}")
        
        # 建议
        recommendations = upwards.get('recommendations', [])
        if recommendations:
            logger.info(f"\n💡 建议:")
            for rec in recommendations:
                logger.info(f"  • {rec}")
        
        logger.info("=" * 80)
