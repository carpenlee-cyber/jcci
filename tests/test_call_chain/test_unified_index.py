"""
UnifiedMethodIndex 单元测试

测试重点：
1. 基线和增量数据合并
2. 删除方法过滤
3. 重载方法精确匹配
4. 方法查询
"""

import pytest
import json
from unittest.mock import Mock, patch
from src.jcci.call_chain.index import UnifiedMethodIndex


class MockDatabase:
    """模拟数据库连接"""
    
    def __init__(self):
        self.data = []
    
    def execute(self, sql, params=None):
        return self
    
    def fetchall(self):
        return self.data
    
    def set_data(self, data):
        self.data = data


class TestUnifiedMethodIndex:
    """UnifiedMethodIndex 单元测试"""
    
    def setup_method(self):
        """每个测试前的设置"""
        self.db_path = ":memory:"
        self.project_id = 1
        self.commit_old = "commit_old_abc"
        self.commit_new = "commit_new_xyz"
    
    def _create_mock_db(self, methods_data):
        """创建模拟数据库"""
        mock_db = Mock()
        mock_cursor = Mock()
        # 将字典列表转换为元组列表
        tuple_data = [
            (
                m['method_id'],
                m['package_name'],
                m['class_name'],
                m['method_name'],
                m['parameters'],
                m['method_invocation_map'],
                m['change_type']
            )
            for m in methods_data
        ]
        mock_cursor.fetchall.return_value = tuple_data
        mock_db.cursor.return_value = mock_cursor
        return mock_db
    
    # ========== Task 2.1: 索引加载测试 ==========
    
    def test_load_baseline_methods(self):
        """测试加载基线方法"""
        baseline_data = [
            {
                'method_id': 1,
                'package_name': 'com.test',
                'class_name': 'ServiceA',
                'method_name': 'method1',
                'parameters': json.dumps([{'parameter_type': 'int'}]),
                'method_invocation_map': json.dumps({}),
                'change_type': 'UNCHANGED'
            },
            {
                'method_id': 2,
                'package_name': 'com.test',
                'class_name': 'ServiceA',
                'method_name': 'method2',
                'parameters': json.dumps([]),
                'method_invocation_map': json.dumps({}),
                'change_type': 'UNCHANGED'
            }
        ]
        
        mock_db = self._create_mock_db(baseline_data)
        
        index = UnifiedMethodIndex(
            db_path=self.db_path,
            project_id=0,
            commit_old=self.commit_old,
            commit_new=self.commit_new,
            db_connection=mock_db
        )
        
        # 验证基线索引已构建
        assert len(index.baseline_index) > 0
        key = ('com.test.ServiceA', 'method1')
        assert key in index.baseline_index

    def test_load_incremental_methods(self):
        """测试加载增量方法"""
        incremental_data = [
            {
                'method_id': 101,
                'package_name': 'com.test',
                'class_name': 'ServiceB',
                'method_name': 'newMethod',
                'parameters': json.dumps([{'parameter_type': 'String'}]),
                'method_invocation_map': json.dumps({}),
                'change_type': 'ADDED'
            }
        ]
        
        mock_db = self._create_mock_db(incremental_data)
        
        index = UnifiedMethodIndex(
            db_path=self.db_path,
            project_id=1,
            commit_old=self.commit_old,
            commit_new=self.commit_new,
            db_connection=mock_db
        )
        
        # 验证增量子引已构建
        assert len(index.incremental_index) > 0
        key = ('com.test.ServiceB', 'newMethod')
        assert key in index.incremental_index

    # ========== Task 2.2: 索引合并测试 ==========
    
    def test_basic_merge_incremental_overwrites_baseline(self):
        """测试基本合并：增量覆盖基线"""
        baseline_data = [
            {
                'method_id': 1,
                'package_name': 'com.test',
                'class_name': 'Service',
                'method_name': 'update',
                'parameters': json.dumps([{'parameter_type': 'int'}]),
                'method_invocation_map': json.dumps({}),
                'change_type': 'UNCHANGED'
            }
        ]
        
        incremental_data = [
            {
                'method_id': 2,
                'package_name': 'com.test',
                'class_name': 'Service',
                'method_name': 'update',
                'parameters': json.dumps([{'parameter_type': 'int'}, {'parameter_type': 'String'}]),
                'method_invocation_map': json.dumps({}),
                'change_type': 'MODIFIED'
            }
        ]
        
        # 创建 mock，第一次返回基线数据，第二次返回增量数据
        mock_db = Mock()
        cursor = Mock()
        
        # 转换为元组列表
        baseline_tuples = [
            (m['method_id'], m['package_name'], m['class_name'], m['method_name'],
             m['parameters'], m['method_invocation_map'], m['change_type'])
            for m in baseline_data
        ]
        incremental_tuples = [
            (m['method_id'], m['package_name'], m['class_name'], m['method_name'],
             m['parameters'], m['method_invocation_map'], m['change_type'])
            for m in incremental_data
        ]
        
        cursor.fetchall.side_effect = [baseline_tuples, incremental_tuples]
        mock_db.cursor.return_value = cursor
        
        index = UnifiedMethodIndex(
            db_path=self.db_path,
            project_id=1,
            commit_old=self.commit_old,
            commit_new=self.commit_new,
            db_connection=mock_db
        )
        
        # 验证统一索引中是增量版本（参数更多）
        key = ('com.test.Service', 'update')
        assert key in index._unified_index
        methods = index._unified_index[key]
        assert len(methods) == 1
        # 应该是增量版本（method_id=2）
        assert methods[0]['method_id'] == 2

    def test_deleted_methods_filtered_from_baseline(self):
        """测试删除方法过滤：基线中 DELETED 的方法不应出现在统一索引"""
        baseline_data = [
            {
                'method_id': 1,
                'package_name': 'com.test',
                'class_name': 'Service',
                'method_name': 'oldMethod',
                'parameters': json.dumps([]),
                'method_invocation_map': json.dumps({}),
                'change_type': 'DELETED'  # 已删除
            },
            {
                'method_id': 2,
                'package_name': 'com.test',
                'class_name': 'Service',
                'method_name': 'activeMethod',
                'parameters': json.dumps([]),
                'method_invocation_map': json.dumps({}),
                'change_type': 'UNCHANGED'
            }
        ]
        
        mock_db = self._create_mock_db(baseline_data)
        
        index = UnifiedMethodIndex(
            db_path=self.db_path,
            project_id=0,
            commit_old=self.commit_old,
            commit_new=self.commit_new,
            db_connection=mock_db
        )
        
        # 验证 DELETED 方法不在统一索引中
        deleted_key = ('com.test.Service', 'oldMethod')
        assert deleted_key not in index._unified_index
        
        # 验证 UNCHANGED 方法在统一索引中
        active_key = ('com.test.Service', 'activeMethod')
        assert active_key in index._unified_index

    def test_added_methods_included_in_unified_index(self):
        """测试新增方法包含在统一索引中"""
        incremental_data = [
            {
                'method_id': 100,
                'package_name': 'com.test',
                'class_name': 'NewService',
                'method_name': 'addedMethod',
                'parameters': json.dumps([]),
                'method_invocation_map': json.dumps({}),
                'change_type': 'ADDED'
            }
        ]
        
        mock_db = self._create_mock_db(incremental_data)
        
        index = UnifiedMethodIndex(
            db_path=self.db_path,
            project_id=1,
            commit_old=self.commit_old,
            commit_new=self.commit_new,
            db_connection=mock_db
        )
        
        # 验证 ADDED 方法在统一索引中
        key = ('com.test.NewService', 'addedMethod')
        assert key in index._unified_index

    # ========== Task 2.3: 方法查询测试 ==========
    
    def test_query_method_exact_match(self):
        """测试精确匹配查询"""
        methods_data = [
            {
                'method_id': 1,
                'package_name': 'com.test',
                'class_name': 'Service',
                'method_name': 'process',
                'parameters': json.dumps([
                    {'parameter_type': 'int'},
                    {'parameter_type': 'String'}
                ]),
                'method_invocation_map': json.dumps({}),
                'change_type': 'UNCHANGED'
            }
        ]
        
        mock_db = self._create_mock_db(methods_data)
        
        index = UnifiedMethodIndex(
            db_path=self.db_path,
            project_id=0,
            commit_old=self.commit_old,
            commit_new=self.commit_new,
            db_connection=mock_db
        )
        
        # 精确匹配
        result = index.query_method('com.test.Service', 'process(int,String)')
        
        assert result is not None
        assert result['method_id'] == 1
        assert result['method_name'] == 'process'

    def test_query_method_overload_resolution(self):
        """测试重载方法解析：根据参数类型区分"""
        methods_data = [
            {
                'method_id': 1,
                'package_name': 'com.test',
                'class_name': 'Service',
                'method_name': 'calculate',
                'parameters': json.dumps([{'parameter_type': 'int'}]),
                'method_invocation_map': json.dumps({}),
                'change_type': 'UNCHANGED'
            },
            {
                'method_id': 2,
                'package_name': 'com.test',
                'class_name': 'Service',
                'method_name': 'calculate',
                'parameters': json.dumps([{'parameter_type': 'double'}]),
                'method_invocation_map': json.dumps({}),
                'change_type': 'UNCHANGED'
            },
            {
                'method_id': 3,
                'package_name': 'com.test',
                'class_name': 'Service',
                'method_name': 'calculate',
                'parameters': json.dumps([{'parameter_type': 'int'}, {'parameter_type': 'int'}]),
                'method_invocation_map': json.dumps({}),
                'change_type': 'UNCHANGED'
            }
        ]
        
        mock_db = self._create_mock_db(methods_data)
        
        index = UnifiedMethodIndex(
            db_path=self.db_path,
            project_id=0,
            commit_old=self.commit_old,
            commit_new=self.commit_new,
            db_connection=mock_db
        )
        
        # 查询 calculate(int) - 应该返回 method_id=1
        result1 = index.query_method('com.test.Service', 'calculate(int)')
        assert result1 is not None
        assert result1['method_id'] == 1
        
        # 查询 calculate(double) - 应该返回 method_id=2
        result2 = index.query_method('com.test.Service', 'calculate(double)')
        assert result2 is not None
        assert result2['method_id'] == 2
        
        # 查询 calculate(int,int) - 应该返回 method_id=3
        result3 = index.query_method('com.test.Service', 'calculate(int,int)')
        assert result3 is not None
        assert result3['method_id'] == 3

    def test_query_method_not_found(self):
        """测试方法不存在的情况"""
        mock_db = self._create_mock_db([])
        
        index = UnifiedMethodIndex(
            db_path=self.db_path,
            project_id=0,
            commit_old=self.commit_old,
            commit_new=self.commit_new,
            db_connection=mock_db
        )
        
        result = index.query_method('com.test.NonExistent', 'method()')
        assert result is None

    def test_query_method_no_exact_match_fallback(self):
        """测试无精确匹配时返回第一个候选（带告警）"""
        methods_data = [
            {
                'method_id': 1,
                'package_name': 'com.test',
                'class_name': 'Service',
                'method_name': 'process',
                'parameters': json.dumps([{'parameter_type': 'int'}]),
                'method_invocation_map': json.dumps({}),
                'change_type': 'UNCHANGED'
            }
        ]
        
        mock_db = self._create_mock_db(methods_data)
        
        index = UnifiedMethodIndex(
            db_path=self.db_path,
            project_id=0,
            commit_old=self.commit_old,
            commit_new=self.commit_new,
            db_connection=mock_db
        )
        
        # 查询 process(String)，但只有 process(int)
        # 应该返回第一个候选并记录告警
        result = index.query_method('com.test.Service', 'process(String)')
        
        # 由于没有精确匹配，应该返回第一个候选
        assert result is not None
        assert result['method_id'] == 1

    def test_extract_param_types_simple(self):
        """测试参数类型提取：简单情况"""
        mock_db = self._create_mock_db([])
        
        index = UnifiedMethodIndex(
            db_path=self.db_path,
            project_id=0,
            commit_old=self.commit_old,
            commit_new=self.commit_new,
            db_connection=mock_db
        )
        
        # process(int,String) -> ['int', 'String']
        types = index._extract_param_types('process(int,String)')
        assert types == ['int', 'String']
        
        # getValue() -> []
        types = index._extract_param_types('getValue()')
        assert types == []

    def test_extract_param_types_with_generics(self):
        """测试参数类型提取：泛型情况"""
        mock_db = self._create_mock_db([])
        
        index = UnifiedMethodIndex(
            db_path=self.db_path,
            project_id=0,
            commit_old=self.commit_old,
            commit_new=self.commit_new,
            db_connection=mock_db
        )
        
        # process(List<String>,Map<String,Integer>) -> ['List<String>', 'Map<String,Integer>']
        types = index._extract_param_types('process(List<String>,Map<String,Integer>)')
        assert types == ['List<String>', 'Map<String,Integer>']

    def test_unified_index_complete_flow(self):
        """测试完整流程：加载 -> 合并 -> 查询"""
        baseline_data = [
            {
                'method_id': 1,
                'package_name': 'com.test',
                'class_name': 'Service',
                'method_name': 'existing',
                'parameters': json.dumps([]),
                'method_invocation_map': json.dumps({}),
                'change_type': 'UNCHANGED'
            },
            {
                'method_id': 2,
                'package_name': 'com.test',
                'class_name': 'Service',
                'method_name': 'deleted',
                'parameters': json.dumps([]),
                'method_invocation_map': json.dumps({}),
                'change_type': 'DELETED'
            }
        ]
        
        incremental_data = [
            {
                'method_id': 3,
                'package_name': 'com.test',
                'class_name': 'Service',
                'method_name': 'added',
                'parameters': json.dumps([]),
                'method_invocation_map': json.dumps({}),
                'change_type': 'ADDED'
            }
        ]
        
        # 创建 mock，第一次返回基线数据，第二次返回增量数据
        mock_db = Mock()
        cursor = Mock()
        
        # 转换为元组列表
        baseline_tuples = [
            (m['method_id'], m['package_name'], m['class_name'], m['method_name'],
             m['parameters'], m['method_invocation_map'], m['change_type'])
            for m in baseline_data
        ]
        incremental_tuples = [
            (m['method_id'], m['package_name'], m['class_name'], m['method_name'],
             m['parameters'], m['method_invocation_map'], m['change_type'])
            for m in incremental_data
        ]
        
        cursor.fetchall.side_effect = [baseline_tuples, incremental_tuples]
        mock_db.cursor.return_value = cursor
        
        index = UnifiedMethodIndex(
            db_path=self.db_path,
            project_id=1,
            commit_old=self.commit_old,
            commit_new=self.commit_new,
            db_connection=mock_db
        )
        
        # 验证 existing 方法存在（来自基线）
        result1 = index.query_method('com.test.Service', 'existing()')
        assert result1 is not None
        assert result1['method_id'] == 1
        
        # 验证 deleted 方法不存在
        result2 = index.query_method('com.test.Service', 'deleted()')
        assert result2 is None
        
        # 验证 added 方法存在（来自增量）
        result3 = index.query_method('com.test.Service', 'added()')
        assert result3 is not None
        assert result3['method_id'] == 3


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
