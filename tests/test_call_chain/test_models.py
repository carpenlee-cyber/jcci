"""
CallChainNode 数据模型测试

测试重点：
1. 节点创建和属性访问
2. to_dict() 序列化
3. 默认值设置
"""

import pytest
from src.jcci.call_chain.models import CallChainNode


class TestCallChainNode:
    """CallChainNode 单元测试"""

    def test_create_basic_node(self):
        """测试创建基本节点"""
        node = CallChainNode(
            node_id="0|com.test.Service|method()",
            package_class="com.test.Service",
            method_signature="method()",
            method_name="method",
            class_name="Service",
            depth=0
        )
        
        assert node.node_id == "0|com.test.Service|method()"
        assert node.package_class == "com.test.Service"
        assert node.method_signature == "method()"
        assert node.method_name == "method"
        assert node.class_name == "Service"
        assert node.depth == 0
        assert node.invocation_lines == []
        assert node.children == []
        assert node.is_cyclic == False
        assert node.is_leaf == False
        assert node.db_method_id is None

    def test_node_with_invocation_lines(self):
        """测试带调用行号的节点"""
        node = CallChainNode(
            node_id="1|com.test.Controller|list(int)",
            package_class="com.test.Controller",
            method_signature="list(int)",
            method_name="list",
            class_name="Controller",
            depth=1,
            invocation_lines=[34, 35]
        )
        
        assert node.invocation_lines == [34, 35]

    def test_node_with_children(self):
        """测试带子节点的节点"""
        parent = CallChainNode(
            node_id="0|com.test.Controller|handleRequest()",
            package_class="com.test.Controller",
            method_signature="handleRequest()",
            method_name="handleRequest",
            class_name="Controller",
            depth=0
        )
        
        child = CallChainNode(
            node_id="1|com.test.Service|process()",
            package_class="com.test.Service",
            method_signature="process()",
            method_name="process",
            class_name="Service",
            depth=1
        )
        
        parent.children.append(child)
        
        assert len(parent.children) == 1
        assert parent.children[0].method_name == "process"

    def test_node_cyclic_flag(self):
        """测试环检测标记"""
        node = CallChainNode(
            node_id="2|com.test.A|methodA()",
            package_class="com.test.A",
            method_signature="methodA()",
            method_name="methodA",
            class_name="A",
            depth=2,
            is_cyclic=True
        )
        
        assert node.is_cyclic == True

    def test_node_leaf_flag(self):
        """测试叶子节点标记"""
        node = CallChainNode(
            node_id="3|com.test.Leaf|getValue()",
            package_class="com.test.Leaf",
            method_signature="getValue()",
            method_name="getValue",
            class_name="Leaf",
            depth=3,
            is_leaf=True
        )
        
        assert node.is_leaf == True

    def test_node_with_db_method_id(self):
        """测试数据库方法ID"""
        node = CallChainNode(
            node_id="0|com.test.Service|method()",
            package_class="com.test.Service",
            method_signature="method()",
            method_name="method",
            class_name="Service",
            depth=0,
            db_method_id=12345
        )
        
        assert node.db_method_id == 12345

    def test_to_dict_basic(self):
        """测试基本序列化"""
        node = CallChainNode(
            node_id="0|com.test.Service|method()",
            package_class="com.test.Service",
            method_signature="method()",
            method_name="method",
            class_name="Service",
            depth=0,
            invocation_lines=[34],
            is_cyclic=False,
            is_leaf=True,
            db_method_id=100
        )
        
        result = node.to_dict()
        
        assert result["node_id"] == "0|com.test.Service|method()"
        assert result["package_class"] == "com.test.Service"
        assert result["method_signature"] == "method()"
        assert result["method_name"] == "method"
        assert result["class_name"] == "Service"
        assert result["depth"] == 0
        assert result["invocation_lines"] == [34]
        assert result["is_cyclic"] == False
        assert result["is_leaf"] == True
        assert result["db_method_id"] == 100
        assert result["children"] == []

    def test_to_dict_with_children(self):
        """测试带子节点的序列化"""
        parent = CallChainNode(
            node_id="0|com.test.Controller|handle()",
            package_class="com.test.Controller",
            method_signature="handle()",
            method_name="handle",
            class_name="Controller",
            depth=0
        )
        
        child = CallChainNode(
            node_id="1|com.test.Service|process()",
            package_class="com.test.Service",
            method_signature="process()",
            method_name="process",
            class_name="Service",
            depth=1
        )
        
        parent.children.append(child)
        
        result = parent.to_dict()
        
        assert len(result["children"]) == 1
        assert result["children"][0]["method_name"] == "process"
        assert result["children"][0]["depth"] == 1

    def test_default_values(self):
        """测试默认值"""
        node = CallChainNode(
            node_id="test",
            package_class="test.Class",
            method_signature="test()",
            method_name="test",
            class_name="Class",
            depth=0
        )
        
        # 验证默认值
        assert node.invocation_lines == []
        assert node.children == []
        assert node.is_cyclic == False
        assert node.is_leaf == False
        assert node.db_method_id is None

    def test_nested_serialization(self):
        """测试嵌套序列化（多层子节点）"""
        root = CallChainNode(
            node_id="0|com.test.Root|root()",
            package_class="com.test.Root",
            method_signature="root()",
            method_name="root",
            class_name="Root",
            depth=0
        )
        
        level1 = CallChainNode(
            node_id="1|com.test.Level1|level1()",
            package_class="com.test.Level1",
            method_signature="level1()",
            method_name="level1",
            class_name="Level1",
            depth=1
        )
        
        level2 = CallChainNode(
            node_id="2|com.test.Level2|level2()",
            package_class="com.test.Level2",
            method_signature="level2()",
            method_name="level2",
            class_name="Level2",
            depth=2,
            is_leaf=True
        )
        
        level1.children.append(level2)
        root.children.append(level1)
        
        result = root.to_dict()
        
        # 验证三层结构
        assert result["depth"] == 0
        assert len(result["children"]) == 1
        assert result["children"][0]["depth"] == 1
        assert len(result["children"][0]["children"]) == 1
        assert result["children"][0]["children"][0]["depth"] == 2
        assert result["children"][0]["children"][0]["is_leaf"] == True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
