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
    
    # 使用相对于脚本文件的绝对路径
    script_dir = Path(__file__).parent
    db_path = script_dir / "src" / "jcci" / "carpenlee-cyber_mall_baseline_c824eac.db"
    
    print(f"\n数据库路径: {db_path}")
    print(f"文件是否存在: {db_path.exists()}")
    
    if not db_path.exists():
        print(f"\n错误: 数据库文件不存在: {db_path}")
        print("请先运行 JCCI 分析生成数据库")
        return
    
    try:
        # 1. 构建统一索引
        print("\n[1] 构建统一索引...")
        index = UnifiedMethodIndex(
            db_path=db_path,
            project_id=0,  # 基线
            commit_old="c824eac",
            commit_new="d9501e9"
        )
        print(f"✓ 索引构建完成")
        
        # 2. 构建调用链
        print("\n[2] 构建调用链: UmsMenuController.list()")
        builder = CallChainBuilder(index, max_depth=5)
        chain = builder.build(
            package_class="com.macro.mall.service.impl.UmsAdminServiceImpl",
            method_signature="delete(Long)"
        )
        print(f"✓ 调用链构建完成")
        
        # 3. 打印结果
        print("\n[3] 调用链结构:")
        print_chain(chain)
        print(f"✓ 调用链打印完成")
        
        # 4. 导出为 JSON
        print("\n[4] 导出为 JSON...")
        chain_dict = chain.to_dict()
        json_str = json.dumps(chain_dict, indent=2, ensure_ascii=False)
        
        output_file = "call_chain_example.json"
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(json_str)
        
        print(f"✓ 已保存到: {output_file}")
        
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



if __name__ == "__main__":
    print("JCCI 调用链路分析器 - 使用示例\n")
    
    # 示例 1: 真实数据库（）
    example_basic_usage()
    
   
    print("\n" + "=" * 80)
    print("示例完成！")
    print("=" * 80)
