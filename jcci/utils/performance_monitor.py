"""
性能监控工具

提供装饰器和上下文管理器，用于监控函数执行时间和定位性能瓶颈。
"""

import time
import logging
from contextlib import contextmanager
from functools import wraps
from typing import Optional, Dict, List
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class PerformanceMetric:
    """性能指标数据类"""
    operation: str
    elapsed_time: float
    status: str = "success"  # success/failed
    error_message: Optional[str] = None
    
    def to_dict(self) -> dict:
        return {
            'operation': self.operation,
            'elapsed_time': round(self.elapsed_time, 3),
            'status': self.status,
            'error_message': self.error_message
        }


class PerformanceMonitor:
    """
    性能监控器
    
    职责：
    1. 记录所有性能指标
    2. 生成性能报告
    3. 识别性能瓶颈
    """
    
    def __init__(self):
        self.metrics: List[PerformanceMetric] = []
        self._start_times: Dict[str, float] = {}
    
    def start_timer(self, operation: str):
        """启动计时器"""
        self._start_times[operation] = time.time()
    
    def stop_timer(self, operation: str, status: str = "success", 
                   error_message: Optional[str] = None) -> Optional[PerformanceMetric]:
        """停止计时器并记录指标"""
        if operation not in self._start_times:
            logger.warning(f"Timer for '{operation}' was not started")
            return None
        
        start_time = self._start_times.pop(operation)
        elapsed = time.time() - start_time
        
        metric = PerformanceMetric(
            operation=operation,
            elapsed_time=elapsed,
            status=status,
            error_message=error_message
        )
        self.metrics.append(metric)
        
        # 实时日志
        if status == "success":
            logger.info(f"[PERF] {operation} completed in {elapsed:.3f}s")
        else:
            logger.error(f"[PERF] {operation} failed after {elapsed:.3f}s: {error_message}")
        
        return metric
    
    def get_top_bottlenecks(self, top_n: int = 5) -> List[PerformanceMetric]:
        """获取耗时最长的前 N 个操作"""
        successful_metrics = [m for m in self.metrics if m.status == "success"]
        sorted_metrics = sorted(successful_metrics, key=lambda x: x.elapsed_time, reverse=True)
        return sorted_metrics[:top_n]
    
    def get_summary(self) -> dict:
        """获取性能摘要"""
        if not self.metrics:
            return {
                'total_operations': 0,
                'total_time': 0,
                'average_time': 0,
                'failed_operations': 0
            }
        
        successful = [m for m in self.metrics if m.status == "success"]
        failed = [m for m in self.metrics if m.status == "failed"]
        total_time = sum(m.elapsed_time for m in successful)
        
        return {
            'total_operations': len(self.metrics),
            'successful_operations': len(successful),
            'failed_operations': len(failed),
            'total_time': round(total_time, 3),
            'average_time': round(total_time / max(len(successful), 1), 3),
            'slowest_operation': self.get_top_bottlenecks(1)[0].to_dict() if successful else None
        }
    
    def generate_report(self) -> str:
        """生成可读的性能报告"""
        summary = self.get_summary()
        bottlenecks = self.get_top_bottlenecks(5)
        
        report_lines = [
            "=" * 80,
            "📊 性能分析报告",
            "=" * 80,
            "",
            f"总操作数: {summary['total_operations']}",
            f"成功操作: {summary['successful_operations']}",
            f"失败操作: {summary['failed_operations']}",
            f"总耗时: {summary['total_time']:.3f}s",
            f"平均耗时: {summary['average_time']:.3f}s",
            "",
            "-" * 80,
            "🔥 Top 5 性能瓶颈:",
            "-" * 80,
        ]
        
        for i, metric in enumerate(bottlenecks, 1):
            report_lines.append(
                f"  {i}. {metric.operation}: {metric.elapsed_time:.3f}s"
            )
        
        if not bottlenecks:
            report_lines.append("  (无数据)")
        
        report_lines.append("")
        report_lines.append("=" * 80)
        
        return "\n".join(report_lines)
    
    def reset(self):
        """重置所有指标"""
        self.metrics.clear()
        self._start_times.clear()


# 全局性能监控器实例
_global_monitor = PerformanceMonitor()


def performance_monitor(func=None, operation_name: Optional[str] = None):
    """
    性能监控装饰器
    
    用法：
        @performance_monitor
        def my_function():
            pass
        
        @performance_monitor(operation_name="Custom Operation Name")
        def my_function():
            pass
    """
    def decorator(fn):
        op_name = operation_name or fn.__qualname__
        
        @wraps(fn)
        def wrapper(*args, **kwargs):
            _global_monitor.start_timer(op_name)
            try:
                result = fn(*args, **kwargs)
                _global_monitor.stop_timer(op_name, status="success")
                return result
            except Exception as e:
                _global_monitor.stop_timer(op_name, status="failed", error_message=str(e))
                raise
        return wrapper
    
    if func is not None:
        return decorator(func)
    return decorator


@contextmanager
def timer(operation_name: str):
    """
    性能监控上下文管理器
    
    用法：
        with timer("Loading baseline methods"):
            load_methods()
    """
    _global_monitor.start_timer(operation_name)
    try:
        yield
        _global_monitor.stop_timer(operation_name, status="success")
    except Exception as e:
        _global_monitor.stop_timer(operation_name, status="failed", error_message=str(e))
        raise


def get_performance_monitor() -> PerformanceMonitor:
    """获取全局性能监控器实例"""
    return _global_monitor


def print_performance_report():
    """打印性能报告"""
    report = _global_monitor.generate_report()
    logger.info("\n" + report)


def get_performance_summary() -> dict:
    """获取性能摘要"""
    return _global_monitor.get_summary()


def get_top_bottlenecks(top_n: int = 5) -> List[PerformanceMetric]:
    """获取性能瓶颈"""
    return _global_monitor.get_top_bottlenecks(top_n)
