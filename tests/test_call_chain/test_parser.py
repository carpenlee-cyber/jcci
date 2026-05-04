"""
InvocationPointParser 单元测试

测试重点：
1. 基本 JSON 解析
2. 空值和无效 JSON 容错
3. 行号格式处理（单值 vs 数组）
"""

import pytest
import json
from src.jcci.call_chain.parser import InvocationPointParser


class TestInvocationPointParser:
    """InvocationPointParser 单元测试"""

    def test_parse_standard_invocation_map(self):
        """测试标准调用映射解析"""
        invocation_map = {
            "com.test.ServiceA": {
                "methods": {
                    "process(int)": [34],
                    "validate(String)": [35, 36]
                }
            },
            "com.test.ServiceB": {
                "methods": {
                    "save()": [40]
                }
            }
        }
        
        result = InvocationPointParser.parse(json.dumps(invocation_map))
        
        assert len(result) == 3
        
        # 验证第一个调用点
        assert result[0]['package_class'] == 'com.test.ServiceA'
        assert result[0]['signature'] == 'process(int)'
        assert result[0]['lines'] == [34]
        
        # 验证第二个调用点
        assert result[1]['package_class'] == 'com.test.ServiceA'
        assert result[1]['signature'] == 'validate(String)'
        assert result[1]['lines'] == [35, 36]
        
        # 验证第三个调用点
        assert result[2]['package_class'] == 'com.test.ServiceB'
        assert result[2]['signature'] == 'save()'
        assert result[2]['lines'] == [40]

    def test_parse_empty_invocation_map(self):
        """测试空调用映射"""
        result = InvocationPointParser.parse('{}')
        assert result == []

    def test_parse_none_input(self):
        """测试 None 输入"""
        result = InvocationPointParser.parse(None)
        assert result == []

    def test_parse_empty_string(self):
        """测试空字符串"""
        result = InvocationPointParser.parse('')
        assert result == []

    def test_parse_invalid_json(self):
        """测试无效 JSON 容错"""
        result = InvocationPointParser.parse('{invalid json}')
        assert result == []

    def test_parse_no_methods_section(self):
        """测试没有 methods 字段的情况"""
        invocation_map = {
            "com.test.Service": {
                "fields": {
                    "logger": [10]
                }
            }
        }
        
        result = InvocationPointParser.parse(json.dumps(invocation_map))
        assert result == []

    def test_parse_single_line_number(self):
        """测试单值行号（不是数组）"""
        invocation_map = {
            "com.test.Service": {
                "methods": {
                    "process()": 34  # 单值，不是数组
                }
            }
        }
        
        result = InvocationPointParser.parse(json.dumps(invocation_map))
        
        assert len(result) == 1
        assert result[0]['lines'] == [34]

    def test_parse_mixed_line_formats(self):
        """测试混合行号格式（单值和数组混合）"""
        invocation_map = {
            "com.test.Service": {
                "methods": {
                    "method1()": 10,  # 单值
                    "method2()": [20, 21],  # 数组
                    "method3()": 30  # 单值
                }
            }
        }
        
        result = InvocationPointParser.parse(json.dumps(invocation_map))
        
        assert len(result) == 3
        assert result[0]['lines'] == [10]
        assert result[1]['lines'] == [20, 21]
        assert result[2]['lines'] == [30]

    def test_parse_with_null_lines(self):
        """测试包含 null 的行号"""
        invocation_map = {
            "com.test.Service": {
                "methods": {
                    "process()": [34, None, 35]
                }
            }
        }
        
        result = InvocationPointParser.parse(json.dumps(invocation_map))
        
        # null 应该被过滤掉
        assert len(result) == 1
        assert result[0]['lines'] == [34, 35]

    def test_parse_complex_real_world_example(self):
        """测试复杂的真实场景"""
        invocation_map = {
            "com.macro.mall.service.UmsMenuService": {
                "methods": {
                    "list(int,int)": [34],
                    "update(Long,UmsMenu)": [45, 46]
                }
            },
            "com.macro.mall.mapper.UmsMenuMapper": {
                "methods": {
                    "selectByExample(UmsMenuExample)": [50]
                }
            }
        }
        
        result = InvocationPointParser.parse(json.dumps(invocation_map))
        
        assert len(result) == 3
        
        # 验证顺序和內容
        service_list = [p for p in result if 'UmsMenuService' in p['package_class']]
        mapper_list = [p for p in result if 'UmsMenuMapper' in p['package_class']]
        
        assert len(service_list) == 2
        assert len(mapper_list) == 1

    def test_parse_multiple_classes_same_method(self):
        """测试多个类有相同方法名"""
        invocation_map = {
            "com.test.ServiceA": {
                "methods": {
                    "process()": [10]
                }
            },
            "com.test.ServiceB": {
                "methods": {
                    "process()": [20]
                }
            }
        }
        
        result = InvocationPointParser.parse(json.dumps(invocation_map))
        
        assert len(result) == 2
        assert result[0]['package_class'] == 'com.test.ServiceA'
        assert result[1]['package_class'] == 'com.test.ServiceB'

    def test_parse_preserves_order(self):
        """测试保持原始顺序"""
        invocation_map = {
            "com.test.ZService": {
                "methods": {
                    "zMethod()": [1]
                }
            },
            "com.test.AService": {
                "methods": {
                    "aMethod()": [2]
                }
            }
        }
        
        result = InvocationPointParser.parse(json.dumps(invocation_map))
        
        # Python 3.7+ 字典保持插入顺序
        assert result[0]['package_class'] == 'com.test.ZService'
        assert result[1]['package_class'] == 'com.test.AService'


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
