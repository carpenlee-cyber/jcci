"""
JCCI 调用链路分析器

提供基于基线+增量合并数据的调用链路构建能力。
v3.1 新增：支持双向分析（向上影响面 + 向下功能风险）
"""

from .models import CallChainNode
from .index import UnifiedMethodIndex
from .parser import InvocationPointParser
from .builder import CallChainBuilder
from .upwards_builder import ReverseCallerIndex, UpwardsCallChainBuilder
from .downwards_builder import DownwardsCallChainBuilder
from .analyzer import (
    build_upwards_call_chains,
    build_downwards_call_chains,
    build_call_chains_for_changes
)

__all__ = [
    'CallChainNode',
    'UnifiedMethodIndex',
    'InvocationPointParser',
    'CallChainBuilder',
    'ReverseCallerIndex',
    'UpwardsCallChainBuilder',
    'DownwardsCallChainBuilder',
    'build_upwards_call_chains',
    'build_downwards_call_chains',
    'build_call_chains_for_changes',
]
