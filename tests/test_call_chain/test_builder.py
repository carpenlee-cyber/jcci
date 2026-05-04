"""
CallChainBuilder 单元测试

测试重点：
1. 简单调用链构建
2. 环检测
3. 深度限制
4. 调用点排序
5. 方法不存在容错
"""

import pytest
import json
from unittest.mock import Mock
from src.jcci.call_chain.models import CallChainNode
from src.jcci.call_chain.index import UnifiedMethodIndex
from src.jcci.call_chain.parser import InvocationPointParser
from src.jcci.call_chain.builder import CallChainBuilder


class MockUnifiedIndex:
    """模拟统一索引，用于测试"""
    
    def __init__(self):
        self.methods = {}
    
    def add_method(self, package_class, method_signature, method_id, 
                   invocation_map=None, change_type='UNCHANGED'):
        """添加一个方法到索引"""
        method_name = method_signature.split('(')[0]
        key = (package_class, method_name)
        
        if key not in self.methods:
            self.methods[key] = []
        
        # 解析参数类型
        params_str = method_signature[method_signature.find('(')+1:method_signature.rfind(')')]
        if params_str:
            param_types = [p.strip() for p in params_str.split(',')]
            parameters = json.dumps([{'parameter_type': pt} for pt in param_types])
        else:
            parameters = json.dumps([])
        
        self.methods[key].append({
            'method_id': method_id,
            'package_name': '.'.join(package_class.split('.')[:-1]),
            'class_name': package_class.split('.')[-1],
            'method_name': method_name,
            'parameters': parameters,
            'method_invocation_map': json.dumps(invocation_map) if invocation_map else '{}',
            'change_type': change_type
        })
    
    def query_method(self, package_class, method_signature):
        """查询方法"""
        method_name = method_signature.split('(')[0]
        key = (package_class, method_name)
        
        candidates = self.methods.get(key, [])
        if not candidates:
            return None
        
        # 简化：返回第一个候选（实际实现会做精确匹配）
        return candidates[0]


class TestCallChainBuilder:
    """CallChainBuilder 单元测试"""
    
    def setup_method(self):
        """每个测试前的设置"""
        self.max_depth = 10
    
    # ========== Task 4.1: 基础构建测试 ==========
    
    def test_build_simple_call_chain(self):
        """测试简单调用链构建：Controller → Service → Mapper"""
        # 构建 mock 索引
        mock_index = MockUnifiedIndex()
        
        # Controller 调用 Service
        mock_index.add_method(
            'com.test.Controller', 'handleRequest()', 1,
            invocation_map={
                'com.test.Service': {
                    'methods': {
                        'process()': [34]
                    }
                }
            }
        )
        
        # Service 调用 Mapper
        mock_index.add_method(
            'com.test.Service', 'process()', 2,
            invocation_map={
                'com.test.Mapper': {
                    'methods': {
                        'select()': [50]
                    }
                }
            }
        )
        
        # Mapper 是叶子节点
        mock_index.add_method(
            'com.test.Mapper', 'select()', 3,
            invocation_map={}
        )
        
        # 构建调用链
        builder = CallChainBuilder(mock_index, max_depth=self.max_depth)
        chain = builder.build('com.test.Controller', 'handleRequest()')
        
        # 验证根节点
        assert chain.package_class == 'com.test.Controller'
        assert chain.method_signature == 'handleRequest()'
        assert chain.depth == 0
        assert chain.is_leaf == False
        
        # 验证第一层子节点
        assert len(chain.children) == 1
        service_node = chain.children[0]
        assert service_node.package_class == 'com.test.Service'
        assert service_node.method_signature == 'process()'
        assert service_node.depth == 1
        assert service_node.invocation_lines == [34]
        
        # 验证第二层子节点
        assert len(service_node.children) == 1
        mapper_node = service_node.children[0]
        assert mapper_node.package_class == 'com.test.Mapper'
        assert mapper_node.method_signature == 'select()'
        assert mapper_node.depth == 2
        assert mapper_node.is_leaf == True

    def test_build_no_children_leaf_node(self):
        """测试没有调用的方法（叶子节点）"""
        mock_index = MockUnifiedIndex()
        
        mock_index.add_method(
            'com.test.SimpleService', 'getValue()', 1,
            invocation_map={}  # 没有调用任何其他方法
        )
        
        builder = CallChainBuilder(mock_index, max_depth=self.max_depth)
        chain = builder.build('com.test.SimpleService', 'getValue()')
        
        assert chain.package_class == 'com.test.SimpleService'
        assert chain.method_signature == 'getValue()'
        assert chain.is_leaf == True
        assert len(chain.children) == 0

    # ========== Task 4.2: 环检测测试 ==========
    
    def test_detect_self_recursive_call(self):
        """测试自递归调用检测"""
        mock_index = MockUnifiedIndex()
        
        # 方法调用自己
        mock_index.add_method(
            'com.test.RecursiveService', 'recurse()', 1,
            invocation_map={
                'com.test.RecursiveService': {
                    'methods': {
                        'recurse()': [20]
                    }
                }
            }
        )
        
        builder = CallChainBuilder(mock_index, max_depth=self.max_depth)
        chain = builder.build('com.test.RecursiveService', 'recurse()')
        
        # 验证检测到环
        assert len(chain.children) == 1
        child = chain.children[0]
        assert child.is_cyclic == True
        assert child.is_leaf == True

    def test_detect_circular_dependency(self):
        """测试循环依赖检测：A → B → C → A"""
        mock_index = MockUnifiedIndex()
        
        # A 调用 B
        mock_index.add_method(
            'com.test.A', 'methodA()', 1,
            invocation_map={
                'com.test.B': {
                    'methods': {
                        'methodB()': [10]
                    }
                }
            }
        )
        
        # B 调用 C
        mock_index.add_method(
            'com.test.B', 'methodB()', 2,
            invocation_map={
                'com.test.C': {
                    'methods': {
                        'methodC()': [20]
                    }
                }
            }
        )
        
        # C 调用 A（形成环）
        mock_index.add_method(
            'com.test.C', 'methodC()', 3,
            invocation_map={
                'com.test.A': {
                    'methods': {
                        'methodA()': [30]
                    }
                }
            }
        )
        
        builder = CallChainBuilder(mock_index, max_depth=self.max_depth)
        chain = builder.build('com.test.A', 'methodA()')
        
        # 验证结构：A → B → C → A(cyclic)
        assert chain.package_class == 'com.test.A'
        assert len(chain.children) == 1
        
        b_node = chain.children[0]
        assert b_node.package_class == 'com.test.B'
        assert len(b_node.children) == 1
        
        c_node = b_node.children[0]
        assert c_node.package_class == 'com.test.C'
        assert len(c_node.children) == 1
        
        a_cyclic_node = c_node.children[0]
        assert a_cyclic_node.package_class == 'com.test.A'
        assert a_cyclic_node.is_cyclic == True
        assert a_cyclic_node.is_leaf == True

    # ========== Task 4.3: 深度限制测试 ==========
    
    def test_depth_limit_enforcement(self):
        """测试深度限制生效"""
        mock_index = MockUnifiedIndex()
        
        # 创建深层调用链：A → B → C → D → E
        mock_index.add_method(
            'com.test.A', 'a()', 1,
            invocation_map={'com.test.B': {'methods': {'b()': [1]}}}
        )
        mock_index.add_method(
            'com.test.B', 'b()', 2,
            invocation_map={'com.test.C': {'methods': {'c()': [1]}}}
        )
        mock_index.add_method(
            'com.test.C', 'c()', 3,
            invocation_map={'com.test.D': {'methods': {'d()': [1]}}}
        )
        mock_index.add_method(
            'com.test.D', 'd()', 4,
            invocation_map={'com.test.E': {'methods': {'e()': [1]}}}
        )
        mock_index.add_method(
            'com.test.E', 'e()', 5,
            invocation_map={}
        )
        
        # 设置最大深度为 2
        builder = CallChainBuilder(mock_index, max_depth=2)
        chain = builder.build('com.test.A', 'a()')
        
        # 验证深度限制
        assert chain.depth == 0
        assert len(chain.children) == 1
        
        b_node = chain.children[0]
        assert b_node.depth == 1
        assert len(b_node.children) == 1
        
        c_node = b_node.children[0]
        assert c_node.depth == 2
        # 达到深度限制，应该是叶子节点
        assert c_node.is_leaf == True
        assert len(c_node.children) == 0

    # ========== Task 4.4: 调用点排序测试 ==========
    
    def test_invocation_points_sorted_by_line_number(self):
        """测试调用点按行号升序排列"""
        mock_index = MockUnifiedIndex()
        
        # 方法在同一行调用多个方法（乱序）
        mock_index.add_method(
            'com.test.Controller', 'handle()', 1,
            invocation_map={
                'com.test.ServiceC': {
                    'methods': {
                        'methodC()': [30]
                    }
                },
                'com.test.ServiceA': {
                    'methods': {
                        'methodA()': [10]
                    }
                },
                'com.test.ServiceB': {
                    'methods': {
                        'methodB()': [20]
                    }
                }
            }
        )
        
        # 添加被调用的方法
        mock_index.add_method('com.test.ServiceA', 'methodA()', 2, invocation_map={})
        mock_index.add_method('com.test.ServiceB', 'methodB()', 3, invocation_map={})
        mock_index.add_method('com.test.ServiceC', 'methodC()', 4, invocation_map={})
        
        builder = CallChainBuilder(mock_index, max_depth=self.max_depth)
        chain = builder.build('com.test.Controller', 'handle()')
        
        # 验证子节点按行号排序：10, 20, 30
        assert len(chain.children) == 3
        assert chain.children[0].invocation_lines == [10]
        assert chain.children[0].package_class == 'com.test.ServiceA'
        
        assert chain.children[1].invocation_lines == [20]
        assert chain.children[1].package_class == 'com.test.ServiceB'
        
        assert chain.children[2].invocation_lines == [30]
        assert chain.children[2].package_class == 'com.test.ServiceC'

    # ========== Task 4.5: 异常处理测试 ==========
    
    def test_method_not_found_handling(self):
        """测试方法不存在时的容错处理"""
        mock_index = MockUnifiedIndex()
        # 不添加任何方法
        
        builder = CallChainBuilder(mock_index, max_depth=self.max_depth)
        chain = builder.build('com.test.NonExistent', 'method()')
        
        # 应该返回一个叶子节点
        assert chain.package_class == 'com.test.NonExistent'
        assert chain.method_signature == 'method()'
        assert chain.is_leaf == True
        assert len(chain.children) == 0

    def test_invalid_invocation_map_handling(self):
        """测试无效 invocation_map 的容错处理"""
        mock_index = MockUnifiedIndex()
        
        # 添加一个有无效 JSON 的方法
        method_data = {
            'method_id': 1,
            'package_name': 'com.test',
            'class_name': 'Service',
            'method_name': 'process',
            'parameters': json.dumps([]),
            'method_invocation_map': '{invalid json}',  # 无效 JSON
            'change_type': 'UNCHANGED'
        }
        
        key = ('com.test.Service', 'process')
        mock_index.methods[key] = [method_data]
        
        builder = CallChainBuilder(mock_index, max_depth=self.max_depth)
        chain = builder.build('com.test.Service', 'process()')
        
        # 应该能正常处理，标记为叶子节点
        assert chain.is_leaf == True

    def test_multiple_calls_same_line(self):
        """测试同一行多次调用同一方法"""
        mock_index = MockUnifiedIndex()
        
        mock_index.add_method(
            'com.test.Controller', 'handle()', 1,
            invocation_map={
                'com.test.Service': {
                    'methods': {
                        'validate()': [15, 15, 15]  # 同一行调用三次
                    }
                }
            }
        )
        
        mock_index.add_method('com.test.Service', 'validate()', 2, invocation_map={})
        
        builder = CallChainBuilder(mock_index, max_depth=self.max_depth)
        chain = builder.build('com.test.Controller', 'handle()')
        
        # 应该只有一个子节点（去重由调用点解析器处理）
        assert len(chain.children) == 1
        assert chain.children[0].invocation_lines == [15, 15, 15]

    def test_complex_call_tree(self):
        """测试复杂调用树：一个方法调用多个服务"""
        mock_index = MockUnifiedIndex()
        
        # Controller 调用多个 Service
        mock_index.add_method(
            'com.test.Controller', 'complexHandle()', 1,
            invocation_map={
                'com.test.AuthService': {
                    'methods': {
                        'authenticate()': [10]
                    }
                },
                'com.test.ValidationService': {
                    'methods': {
                        'validate()': [15]
                    }
                },
                'com.test.BusinessService': {
                    'methods': {
                        'execute()': [20]
                    }
                }
            }
        )
        
        # 添加所有被调用的方法
        mock_index.add_method('com.test.AuthService', 'authenticate()', 2, invocation_map={})
        mock_index.add_method('com.test.ValidationService', 'validate()', 3, invocation_map={})
        mock_index.add_method('com.test.BusinessService', 'execute()', 4, invocation_map={})
        
        builder = CallChainBuilder(mock_index, max_depth=self.max_depth)
        chain = builder.build('com.test.Controller', 'complexHandle()')
        
        # 验证有三个子节点
        assert len(chain.children) == 3
        
        # 验证所有子节点都是叶子节点
        for child in chain.children:
            assert child.is_leaf == True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
