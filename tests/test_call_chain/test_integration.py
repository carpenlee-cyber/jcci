"""
集成测试：验证组件协作

测试完整流程：索引 → 解析 → 构建
"""

import pytest
import json
from unittest.mock import Mock
from src.jcci.call_chain.index import UnifiedMethodIndex
from src.jcci.call_chain.builder import CallChainBuilder


class MockDatabase:
    """模拟数据库"""
    
    def __init__(self, baseline_data=None, incremental_data=None):
        self.baseline_data = baseline_data or []
        self.incremental_data = incremental_data or []
        self.call_count = 0
    
    def cursor(self):
        mock_cursor = Mock()
        
        # 第一次调用返回基线数据，第二次返回增量数据
        if self.call_count == 0:
            mock_cursor.fetchall.return_value = self._to_tuples(self.baseline_data)
        else:
            mock_cursor.fetchall.return_value = self._to_tuples(self.incremental_data)
        
        self.call_count += 1
        return mock_cursor
    
    def _to_tuples(self, data):
        return [
            (m['method_id'], m['package_name'], m['class_name'], m['method_name'],
             m['parameters'], m['method_invocation_map'], m['change_type'])
            for m in data
        ]


class TestIntegration:
    """集成测试"""
    
    def test_complete_call_chain_flow(self):
        """测试完整调用链流程"""
        # 准备基线数据
        baseline_data = [
            {
                'method_id': 1,
                'package_name': 'com.test',
                'class_name': 'Controller',
                'method_name': 'handle',
                'parameters': json.dumps([]),
                'method_invocation_map': json.dumps({
                    'com.test.Service': {
                        'methods': {
                            'process()': [34]
                        }
                    }
                }),
                'change_type': 'UNCHANGED'
            },
            {
                'method_id': 2,
                'package_name': 'com.test',
                'class_name': 'Service',
                'method_name': 'process',
                'parameters': json.dumps([]),
                'method_invocation_map': json.dumps({
                    'com.test.Mapper': {
                        'methods': {
                            'select()': [50]
                        }
                    }
                }),
                'change_type': 'UNCHANGED'
            },
            {
                'method_id': 3,
                'package_name': 'com.test',
                'class_name': 'Mapper',
                'method_name': 'select',
                'parameters': json.dumps([]),
                'method_invocation_map': json.dumps({}),
                'change_type': 'UNCHANGED'
            }
        ]
        
        # 创建 mock 数据库
        mock_db = MockDatabase(baseline_data=baseline_data)
        
        # 构建统一索引
        index = UnifiedMethodIndex(
            db_path=":memory:",
            project_id=0,
            commit_old="commit_old",
            commit_new="commit_new",
            db_connection=mock_db
        )
        
        # 构建调用链
        builder = CallChainBuilder(index, max_depth=10)
        chain = builder.build('com.test.Controller', 'handle()')
        
        # 验证调用链结构
        assert chain.package_class == 'com.test.Controller'
        assert chain.method_signature == 'handle()'
        assert len(chain.children) == 1
        
        service_node = chain.children[0]
        assert service_node.package_class == 'com.test.Service'
        assert service_node.method_signature == 'process()'
        assert len(service_node.children) == 1
        
        mapper_node = service_node.children[0]
        assert mapper_node.package_class == 'com.test.Mapper'
        assert mapper_node.is_leaf == True

    def test_baseline_incremental_merge_in_call_chain(self):
        """测试基线和增量合并在调用链中的体现"""
        # 基线中有方法 A 和 B
        baseline_data = [
            {
                'method_id': 1,
                'package_name': 'com.test',
                'class_name': 'Controller',
                'method_name': 'handle',
                'parameters': json.dumps([]),
                'method_invocation_map': json.dumps({
                    'com.test.OldService': {
                        'methods': {
                            'oldProcess()': [34]
                        }
                    }
                }),
                'change_type': 'UNCHANGED'
            },
            {
                'method_id': 2,
                'package_name': 'com.test',
                'class_name': 'OldService',
                'method_name': 'oldProcess',
                'parameters': json.dumps([]),
                'method_invocation_map': json.dumps({}),
                'change_type': 'DELETED'  # 这个方法被删除了
            }
        ]
        
        # 增量中 Controller 改为调用 NewService
        incremental_data = [
            {
                'method_id': 10,
                'package_name': 'com.test',
                'class_name': 'Controller',
                'method_name': 'handle',
                'parameters': json.dumps([]),
                'method_invocation_map': json.dumps({
                    'com.test.NewService': {
                        'methods': {
                            'newProcess()': [34]
                        }
                    }
                }),
                'change_type': 'MODIFIED'
            },
            {
                'method_id': 11,
                'package_name': 'com.test',
                'class_name': 'NewService',
                'method_name': 'newProcess',
                'parameters': json.dumps([]),
                'method_invocation_map': json.dumps({}),
                'change_type': 'ADDED'
            }
        ]
        
        mock_db = MockDatabase(baseline_data=baseline_data, incremental_data=incremental_data)
        
        index = UnifiedMethodIndex(
            db_path=":memory:",
            project_id=1,
            commit_old="commit_old",
            commit_new="commit_new",
            db_connection=mock_db
        )
        
        builder = CallChainBuilder(index, max_depth=10)
        chain = builder.build('com.test.Controller', 'handle()')
        
        # 验证使用的是增量版本（调用 NewService）
        assert len(chain.children) == 1
        assert chain.children[0].package_class == 'com.test.NewService'
        assert chain.children[0].method_signature == 'newProcess()'


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
