"""
调用点解析器

负责解析 method_invocation_map JSON，提取结构化的调用点列表。
"""

import json
import logging
from typing import List, Optional

logger = logging.getLogger(__name__)


class InvocationPointParser:
    """
    调用点解析器
    
    从 method_invocation_map JSON 中提取结构化的调用点列表。
    当前只处理方法调用（methods），不处理 fields 和 entity。
    """
    
    @staticmethod
    def parse(invocation_map_json: str) -> List[dict]:
        """
        解析 method_invocation_map
        
        Args:
            invocation_map_json: JSON 字符串，格式如：
                {
                    "com.xxx.Service": {
                        "methods": {
                            "method(int,String)": [34, 35]
                        }
                    }
                }
        
        Returns:
            List[dict]: 调用点列表，每个元素包含：
                - package_class: 完整类名
                - signature: 方法签名
                - lines: 调用发生的行号列表
        """
        if not invocation_map_json:
            return []
        
        try:
            invocation_map = json.loads(invocation_map_json)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse invocation map: {e}")
            logger.debug(f"Invalid JSON: {invocation_map_json[:100]}")
            return []
        
        if not isinstance(invocation_map, dict):
            logger.warning(f"Expected dict, got {type(invocation_map)}")
            return []
        
        points = []
        
        for package_class, sections in invocation_map.items():
            # 只处理 methods 字段
            if not isinstance(sections, dict) or 'methods' not in sections:
                continue
            
            methods_section = sections['methods']
            if not isinstance(methods_section, dict):
                continue
            
            for method_sig, lines in methods_section.items():
                # 处理行号可能是单值或数组
                if isinstance(lines, list):
                    # 过滤掉 None 值
                    lines_list = [l for l in lines if l is not None]
                else:
                    # 单值转换为数组
                    lines_list = [lines] if lines is not None else []
                
                points.append({
                    'package_class': package_class,
                    'signature': method_sig,
                    'lines': lines_list
                })
        
        return points
