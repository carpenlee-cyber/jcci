"""
JCCI 统一日志配置模块

提供彩色、格式化的日志输出，支持不同级别的清晰区分。

使用示例：
    from jcci.logger import get_logger
    
    logger = get_logger(__name__)
    logger.info("这是一条信息")
    logger.warning("这是一条警告")
    logger.error("这是一条错误")
"""

import logging
import sys
import os
from typing import Optional

try:
    import colorlog
    HAS_COLORLOG = True
except ImportError:
    HAS_COLORLOG = False

# 在 Windows 上启用 ANSI 颜色支持
if sys.platform == 'win32':
    try:
        # 使用 colorama 初始化 Windows 终端
        from colorama import init as colorama_init
        colorama_init()
    except ImportError:
        # 如果 colorama 不可用，尝试手动启用虚拟终端处理
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            # ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
            # DISABLE_NEWLINE_AUTO_RETURN = 0x0008
            mode = kernel32.GetConsoleMode(kernel32.GetStdHandle(-11))  # STD_OUTPUT_HANDLE
            kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), mode | 0x0004 | 0x0008)
        except Exception:
            pass  # 如果失败，继续使用默认设置


def setup_logger(
    name: str = "jcci",
    level: int = logging.INFO,
    log_file: Optional[str] = None,
    use_color: bool = True
) -> logging.Logger:
    """
    配置并返回一个logger实例
    
    Args:
        name: logger名称，通常使用 __name__
        level: 日志级别 (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_file: 可选的日志文件路径
        use_color: 是否启用彩色输出（仅终端有效）
        
    Returns:
        配置好的logger实例
    """
    logger = logging.getLogger(name)
    
    # 如果已经配置过，直接返回
    if logger.handlers:
        logger.setLevel(level)
        return logger
    
    logger.setLevel(level)
    
    # 定义日志格式
    if HAS_COLORLOG and use_color:
        # 彩色格式 - 适合终端显示
        formatter = colorlog.ColoredFormatter(
            fmt="%(log_color)s%(asctime)s [%(levelname)-8s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
            log_colors={
                'DEBUG': 'cyan',
                'INFO': 'green',
                'WARNING': 'yellow',
                'ERROR': 'red',
                'CRITICAL': 'bold_red',
            },
            secondary_log_colors={
                'asctime': {'DEBUG': 'white', 'INFO': 'white', 'WARNING': 'yellow', 'ERROR': 'red', 'CRITICAL': 'red'},
                'levelname': {'DEBUG': 'cyan', 'INFO': 'green', 'WARNING': 'yellow', 'ERROR': 'red', 'CRITICAL': 'bold_red'},
            },
            force_color=True  # 强制启用颜色（特别是在 Windows 上）
        )
    else:
        # 普通格式 - 适合文件写入或不支持颜色的终端
        formatter = logging.Formatter(
            fmt="%(asctime)s [%(levelname)-8s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )
    
    # 控制台处理器
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    console_handler.setLevel(level)
    logger.addHandler(console_handler)
    
    # 文件处理器（如果指定了日志文件）
    if log_file:
        file_formatter = logging.Formatter(
            fmt="%(asctime)s [%(levelname)-8s] %(name)s:%(lineno)d - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setFormatter(file_formatter)
        file_handler.setLevel(logging.DEBUG)  # 文件记录更详细的日志
        logger.addHandler(file_handler)
    
    # 防止日志传播到根logger
    logger.propagate = False
    
    return logger


def get_logger(name: str = None) -> logging.Logger:
    """
    获取logger实例（便捷函数）
    
    Args:
        name: logger名称，默认为调用者的模块名
        
    Returns:
        logger实例
    """
    if name is None:
        # 自动获取调用者的模块名
        import inspect
        frame = inspect.currentframe().f_back
        name = frame.f_globals.get('__name__', 'jcci')
    
    return setup_logger(name)


# 创建默认的JCCI logger
default_logger = setup_logger("jcci")


if __name__ == "__main__":
    # 测试日志输出
    logger = get_logger("test")
    
    print("=" * 80)
    print("JCCI 彩色日志测试")
    print("=" * 80)
    print()
    
    logger.debug("这是一条DEBUG级别的日志（青色）")
    logger.info("这是一条INFO级别的日志（绿色）")
    logger.warning("这是一条WARNING级别的日志（黄色）")
    logger.error("这是一条ERROR级别的日志（红色）")
    logger.critical("这是一条CRITICAL级别的日志（粗体红色）")
    
    print()
    print("=" * 80)
    print("日志配置完成！")
    print("=" * 80)
