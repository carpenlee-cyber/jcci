"""
向下调用链构建器

负责构建"这个方法调用了谁"的调用链（功能风险分析）。
基本复用现有的 CallChainBuilder 逻辑。
"""

import logging
from .builder import CallChainBuilder

logger = logging.getLogger(__name__)


class DownwardsCallChainBuilder(CallChainBuilder):
    """
    向下调用链构建器
    
    继承自 CallChainBuilder，保持原有向下分析逻辑不变。
    主要用于语义区分和未来的扩展。
    """
    
    def __init__(self, unified_index, max_depth: int = 10, dao_analyzer=None):
        """
        初始化向下调用链构建器
        
        Args:
            unified_index: UnifiedMethodIndex 实例
            max_depth: 最大递归深度
            dao_analyzer: 可选的 DaoAnalyzer 实例
        """
        super().__init__(unified_index, max_depth=max_depth, dao_analyzer=dao_analyzer)
        logger.info(f"Downwards call chain builder initialized (max_depth={max_depth})")
