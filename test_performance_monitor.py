"""
性能监控工具测试脚本
"""

import sys
import os
import time

# 添加项目根目录到 Python 路径
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from src.jcci.utils.performance_monitor import (
    timer,
    performance_monitor,
    print_performance_report,
    get_performance_summary
)


# 测试1: 使用装饰器
@performance_monitor
def slow_function_1():
    """模拟慢函数1"""
    time.sleep(0.5)
    return "result1"


@performance_monitor(operation_name="Custom Operation Name")
def slow_function_2():
    """模拟慢函数2"""
    time.sleep(0.3)
    return "result2"


# 测试2: 使用上下文管理器
def slow_function_3():
    """模拟慢函数3"""
    with timer("Manual Timer Operation"):
        time.sleep(0.2)
    return "result3"


def nested_operations():
    """测试嵌套操作"""
    with timer("Outer Operation"):
        time.sleep(0.1)
        with timer("Inner Operation"):
            time.sleep(0.05)
    return "nested_result"


if __name__ == "__main__":
    print("=" * 80)
    print("🧪 性能监控工具测试")
    print("=" * 80)
    print()
    
    # 执行测试
    print("执行测试函数...")
    result1 = slow_function_1()
    result2 = slow_function_2()
    result3 = slow_function_3()
    result4 = nested_operations()
    
    print(f"\n函数执行结果:")
    print(f"  - slow_function_1: {result1}")
    print(f"  - slow_function_2: {result2}")
    print(f"  - slow_function_3: {result3}")
    print(f"  - nested_operations: {result4}")
    
    print("\n")
    
    # 打印性能报告
    print_performance_report()
    
    # 打印摘要
    summary = get_performance_summary()
    print(f"\n性能摘要:")
    print(f"  - 总操作数: {summary['total_operations']}")
    print(f"  - 成功操作: {summary['successful_operations']}")
    print(f"  - 失败操作: {summary['failed_operations']}")
    print(f"  - 总耗时: {summary['total_time']:.3f}s")
    print(f"  - 平均耗时: {summary['average_time']:.3f}s")
    
    print("\n✅ 测试完成！")
