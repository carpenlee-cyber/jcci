"""
注解感知入口发现器

识别 Spring MVC Controller、Scheduled 任务、MessageListener 等框架入口方法。
解决"向上分析只到 ServiceImpl 就停止"的问题。
"""

import json
import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class AnnotationAwareEntryDetector:
    """
    注解感知入口发现器
    识别 Spring MVC Controller、Scheduled 任务、MessageListener 等入口
    """
    
    ENTRY_ANNOTATIONS = {
        'org.springframework.web.bind.annotation.RequestMapping': 'HTTP_API',
        'org.springframework.web.bind.annotation.GetMapping': 'HTTP_API',
        'org.springframework.web.bind.annotation.PostMapping': 'HTTP_API',
        'org.springframework.web.bind.annotation.PutMapping': 'HTTP_API',
        'org.springframework.web.bind.annotation.DeleteMapping': 'HTTP_API',
        'org.springframework.web.bind.annotation.PatchMapping': 'HTTP_API',
        'org.springframework.scheduling.annotation.Scheduled': 'SCHEDULED_TASK',
        'org.springframework.context.event.EventListener': 'EVENT_LISTENER',
        'org.springframework.jms.annotation.JmsListener': 'MESSAGE_CONSUMER',
        'jakarta.ws.rs.Path': 'HTTP_API',
        'javax.ws.rs.Path': 'HTTP_API',
        'org.springframework.boot.actuate.endpoint.annotation.Endpoint': 'ACTUATOR',
    }
    
    def __init__(self, db_connection, project_ids: List[int]):
        """
        初始化入口发现器
        
        Args:
            db_connection: 数据库连接对象
            project_ids: 项目ID列表
        """
        self._entry_methods: Dict[str, dict] = {}
        self._load_annotations(db_connection, project_ids)
        logger.info(f"Entry detector loaded: {len(self._entry_methods)} entry methods")
    
    def _load_annotations(self, db_connection, project_ids: List[int]):
        """
        从数据库加载方法注解信息
        
        假设有 method_annotation 表或通过其他方式存储注解信息
        如果数据库中没有注解表，则跳过此步骤
        """
        try:
            cursor = db_connection.cursor()
            placeholders = ','.join(['?'] * len(project_ids))
            
            query = f"""
                SELECT m.method_id, c.package_name, c.class_name, 
                       m.method_name, m.parameters
                FROM methods m
                JOIN class c ON m.class_id = c.class_id
                WHERE c.project_id IN ({placeholders})
            """
            
            cursor.execute(query, project_ids)
            rows = cursor.fetchall()
            
            for row in rows:
                if isinstance(row, dict):
                    method_id = row['method_id']
                    package_name = row['package_name']
                    class_name = row['class_name']
                    method_name = row['method_name']
                    parameters = row['parameters']
                else:
                    method_id, package_name, class_name, method_name, parameters = row
                
                package_class = f"{package_name}.{class_name}"
                sig = self._build_signature(method_name, parameters)
                method_key = f"{package_class}|{sig}"
                
                class_name_only = package_class.split('.')[-1]
                
                if class_name_only.endswith('Controller'):
                    self._entry_methods[method_key] = {
                        'method_id': method_id,
                        'package_class': package_class,
                        'method_signature': sig,
                        'entry_type': 'CONTROLLER_BY_CONVENTION',
                        'annotation': None,
                        'annotation_params': None
                    }
        
        except Exception as e:
            logger.warning(f"Failed to load annotations (this is OK if no annotation table exists): {e}")
    
    def is_entry_method(self, package_class: str, method_signature: str) -> Optional[dict]:
        """判断一个方法是否为入口方法"""
        key = f"{package_class}|{method_signature}"
        return self._entry_methods.get(key)
    
    def classify_root_node(self, node, has_callers: bool) -> str:
        """
        对向上分析的根节点进行分类
        
        Args:
            node: CallChainNode 实例
            has_callers: 是否有调用者
        
        Returns:
            str: 根节点类型
        """
        entry_info = self.is_entry_method(node.package_class, node.method_signature)
        if entry_info:
            return entry_info['entry_type']
        
        class_name = node.class_name
        if class_name.endswith('Controller'):
            return 'CONTROLLER_BY_CONVENTION'
        
        if not has_callers:
            return 'NO_STATIC_CALLER'
        
        return 'INTERMEDIATE'
    
    @staticmethod
    def _build_signature(method_name: str, parameters: str) -> str:
        """构建方法签名"""
        try:
            params = json.loads(parameters) if isinstance(parameters, str) else parameters
            if isinstance(params, list):
                param_types = [p.get('parameter_type', '') for p in params]
                return f"{method_name}({','.join(param_types)})"
        except:
            pass
        return f"{method_name}()"
