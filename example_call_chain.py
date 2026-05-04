"""
调用链路分析器使用示例

演示如何使用 CallChainAnalyzer 构建方法调用链。
"""

import json
import sys
from pathlib import Path

# 添加 src 到路径
sys.path.insert(0, str(Path(__file__).parent / "src"))

from jcci.call_chain import UnifiedMethodIndex, CallChainBuilder


def example_basic_usage():
    """基本用法示例"""
    print("=" * 80)
    print("示例 1: 基本用法")
    print("=" * 80)
    
    # 注意：这里需要使用真实的数据库路径
    db_path = "src/jcci/carpenlee-cyber_mall_baseline_83abb8e.db"
    
    if not Path(db_path).exists():
        print(f"数据库文件不存在: {db_path}")
        print("请先运行 JCCI 分析生成数据库")
        return
    
    try:
        # 1. 构建统一索引
        print("\n[1] 构建统一索引...")
        index = UnifiedMethodIndex(
            db_path=db_path,
            project_id=0,  # 基线
            commit_old="83abb8e",
            commit_new="83abb8e"
        )
        print(f"    ✓ 索引构建完成")
        
        # 2. 构建调用链
        print("\n[2] 构建调用链: UmsMenuController.list()")
        builder = CallChainBuilder(index, max_depth=5)
        chain = builder.build(
            package_class="com.macro.mall.controller.UmsMenuController",
            method_signature="list(int,int)"
        )
        
        # 3. 打印结果
        print("\n[3] 调用链结构:")
        print_chain(chain)
        
        # 4. 导出为 JSON
        print("\n[4] 导出为 JSON...")
        chain_dict = chain.to_dict()
        json_str = json.dumps(chain_dict, indent=2, ensure_ascii=False)
        
        output_file = "call_chain_example.json"
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(json_str)
        
        print(f"    ✓ 已保存到: {output_file}")
        
    except Exception as e:
        print(f"错误: {e}")
        import traceback
        traceback.print_exc()


def print_chain(node, indent=0):
    """递归打印调用链"""
    prefix = "  " * indent
    
    # 构建显示文本
    parts = [f"{prefix}{node.class_name}.{node.method_signature}"]
    
    if node.invocation_lines:
        parts.append(f" [lines: {node.invocation_lines}]")
    
    if node.is_cyclic:
        parts.append(" [CYCLIC]")
    
    if node.is_leaf:
        parts.append(" [LEAF]")
    
    print("".join(parts))
    
    # 递归打印子节点
    for child in node.children:
        print_chain(child, indent + 1)


def example_with_mock_data():
    """使用 Mock 数据的示例（无需数据库）"""
    print("\n" + "=" * 80)
    print("示例 2: 使用 Mock 数据（演示用途）")
    print("=" * 80)
    
    from tests.test_call_chain.test_builder import MockUnifiedIndex
    
    # 创建 mock 索引
    mock_index = MockUnifiedIndex()
    
    # 添加方法
    mock_index.add_method(
        'com.example.Controller', 'handleRequest()', 1,
        invocation_map={
            'com.example.Service': {
                'methods': {
                    'process()': [34]
                }
            }
        }
    )
    
    mock_index.add_method(
        'com.example.Service', 'process()', 2,
        invocation_map={
            'com.example.Mapper': {
                'methods': {
                    'select()': [50]
                }
            }
        }
    )
    
    mock_index.add_method(
        'com.example.Mapper', 'select()', 3,
        invocation_map={}
    )
    
    # 构建调用链
    builder = CallChainBuilder(mock_index, max_depth=10)
    chain = builder.build('com.example.Controller', 'handleRequest()')
    
    # 打印结果
    print("\n调用链结构:")
    print_chain(chain)
    
    # 统计信息
    def count_nodes(node):
        count = 1
        for child in node.children:
            count += count_nodes(child)
        return count
    
    total_nodes = count_nodes(chain)
    print(f"\n总计: {total_nodes} 个节点")


if __name__ == "__main__":
    print("JCCI 调用链路分析器 - 使用示例\n")
    
    # 示例 1: 真实数据库（如果存在）
    example_basic_usage()
    
    # 示例 2: Mock 数据
    example_with_mock_data()
    
    print("\n" + "=" * 80)
    print("示例完成！")
    print("=" * 80)
