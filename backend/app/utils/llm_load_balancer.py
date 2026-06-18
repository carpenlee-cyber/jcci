#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LLM API流量均衡器
负责管理多个API KEY的负载均衡、健康检查和故障恢复
"""

import time
import random
import threading
from dataclasses import dataclass, field
from typing import List, Dict, Optional
from datetime import datetime, timedelta


@dataclass
class APIKeyStatus:
    """API KEY状态管理"""
    key: str
    model: str
    weight: float = 1.0  # 当前权重（0.0-1.0）
    enabled: bool = True
    total_calls: int = 0  # 总调用次数
    success_calls: int = 0  # 成功调用次数
    failure_calls: int = 0  # 失败调用次数
    last_call_time: Optional[float] = None  # 最后调用时间
    consecutive_failures: int = 0  # 连续失败次数
    last_failure_time: Optional[float] = None  # 最后失败时间
    call_count_1min: int = 0  # 1分钟内调用次数
    response_time_avg: float = 0.0  # 平均响应时间

    @property
    def success_rate(self) -> float:
        """计算成功率"""
        if self.total_calls == 0:
            return 0.0
        return self.success_calls / self.total_calls


@dataclass
class CallWindow:
    """1分钟调用统计窗口"""
    window_start: float  # 窗口开始时间
    call_counts: Dict[str, int] = field(default_factory=dict)  # KEY -> 调用次数
    success_counts: Dict[str, int] = field(default_factory=dict)  # KEY -> 成功次数
    failure_counts: Dict[str, int] = field(default_factory=dict)  # KEY -> 失败次数


class CallStatistics:
    """调用统计器 - 1分钟滑动窗口统计（线程安全）"""

    def __init__(self, window_size: int = 60):
        """初始化统计器

        Args:
            window_size: 窗口大小（秒），默认60秒
        """
        self.window_size = window_size
        self.windows: List[CallWindow] = []
        self._lock = threading.Lock()  # 线程安全锁

    def record_call(self, key: str, success: bool):
        """记录一次调用（线程安全）

        Args:
            key: API KEY
            success: 是否成功
        """
        with self._lock:
            current_time = time.time()

            # 清理过期窗口
            self._clean_expired_windows(current_time)

            # 获取当前窗口
            current_window = self._get_current_window(current_time)

            # 更新统计
            current_window.call_counts[key] = current_window.call_counts.get(key, 0) + 1
            if success:
                current_window.success_counts[key] = current_window.success_counts.get(key, 0) + 1
            else:
                current_window.failure_counts[key] = current_window.failure_counts.get(key, 0) + 1

    def get_call_count_1min(self, key: str) -> int:
        """获取1分钟内调用次数（线程安全）

        Args:
            key: API KEY

        Returns:
            1分钟内调用次数
        """
        with self._lock:
            current_time = time.time()
            self._clean_expired_windows(current_time)

            total_calls = 0
            for window in self.windows:
                total_calls += window.call_counts.get(key, 0)

            return total_calls

    def get_success_count_1min(self, key: str) -> int:
        """获取1分钟内成功次数（线程安全）

        Args:
            key: API KEY

        Returns:
            1分钟内成功次数
        """
        with self._lock:
            current_time = time.time()
            self._clean_expired_windows(current_time)

            total_success = 0
            for window in self.windows:
                total_success += window.success_counts.get(key, 0)

            return total_success

    def _clean_expired_windows(self, current_time: float):
        """清理过期窗口（需在锁内调用）"""
        cutoff_time = current_time - self.window_size
        self.windows = [w for w in self.windows if w.window_start >= cutoff_time]

    def _get_current_window(self, current_time: float) -> CallWindow:
        """获取当前时间窗口（需在锁内调用）"""
        window_start = current_time - (current_time % self.window_size)

        for window in self.windows:
            if window.window_start == window_start:
                return window

        # 创建新窗口
        new_window = CallWindow(window_start=window_start)
        self.windows.append(new_window)
        return new_window


class HealthChecker:
    """健康检查器 - 负责KEY的健康状态管理（线程安全）"""

    def __init__(self):
        self._lock = threading.Lock()

    def update_key_health(self, key_status: APIKeyStatus, success: bool, response_time: float):
        """更新KEY健康状态（线程安全）

        Args:
            key_status: KEY状态对象
            success: 是否成功
            response_time: 响应时间（秒）
        """
        with self._lock:
            # 更新调用统计
            key_status.total_calls += 1
            key_status.last_call_time = time.time()

            if success:
                key_status.success_calls += 1
                key_status.consecutive_failures = 0

                # 成功时缓慢恢复权重（最多恢复到1.0）
                key_status.weight = min(1.0, key_status.weight + 0.05)

                # 如果之前被禁用，重新启用
                if not key_status.enabled:
                    key_status.enabled = True
                    key_status.weight = 0.5  # 重新启用时设置为中等权重

            else:
                key_status.failure_calls += 1
                key_status.consecutive_failures += 1
                key_status.last_failure_time = time.time()

                # 失败时降低权重（基于连续失败次数）
                penalty = 0.2 * min(key_status.consecutive_failures, 5)  # 最多降低到0
                key_status.weight = max(0.0, key_status.weight - penalty)

                # 连续失败过多时暂时禁用
                if key_status.consecutive_failures >= 10:
                    key_status.enabled = False
                    print(f"[LLM LoadBalancer] API KEY {key_status.key[:8]}... 因连续失败{key_status.consecutive_failures}次被暂时禁用")

            # 更新响应时间统计
            self._update_response_time(key_status, response_time)

    def _update_response_time(self, key_status: APIKeyStatus, response_time: float):
        """更新响应时间统计（需在锁内调用）

        Args:
            key_status: KEY状态对象
            response_time: 响应时间（秒）
        """
        if key_status.total_calls == 1:
            key_status.response_time_avg = response_time
        else:
            # 指数移动平均（EMA）
            alpha = 0.1  # 平滑因子
            key_status.response_time_avg = (alpha * response_time +
                                          (1 - alpha) * key_status.response_time_avg)


class LoadBalancer:
    """负载均衡器 - 基于最少调用次数的智能选择（线程安全）"""

    def __init__(self, call_stats: CallStatistics):
        """初始化负载均衡器

        Args:
            call_stats: 调用统计器
        """
        self.call_stats = call_stats
        self._lock = threading.Lock()

    def select_best_key(self, api_keys: List[APIKeyStatus]) -> Optional[APIKeyStatus]:
        """选择最优API KEY（线程安全）

        Args:
            api_keys: API KEY状态列表

        Returns:
            最优的API KEY状态对象，如果没有可用KEY则返回None
        """
        with self._lock:
            # 1. 过滤可用的KEY（启用且权重>0）
            available_keys = [k for k in api_keys if k.enabled and k.weight > 0]

            if not available_keys:
                print("[LLM LoadBalancer] 警告：没有可用的API KEY")
                return None

            # 2. 更新1分钟调用次数统计
            for key_status in available_keys:
                key_status.call_count_1min = self.call_stats.get_call_count_1min(key_status.key)

            # 3. 计算1分钟内调用次数最少的KEY
            min_calls = min(k.call_count_1min for k in available_keys)
            candidates = [k for k in available_keys if k.call_count_1min == min_calls]

            # 4. 如果有多个候选，选择权重最高的
            if len(candidates) > 1:
                max_weight = max(k.weight for k in candidates)
                candidates = [k for k in candidates if k.weight == max_weight]

            # 5. 如果还有多个候选，随机选择一个（避免热点）
            if len(candidates) > 1:
                selected = random.choice(candidates)
                print(f"[LLM LoadBalancer] 从{len(candidates)}个候选KEY中随机选择模型: {selected.model}")
            else:
                selected = candidates[0]

            print(f"[LLM LoadBalancer] 选择模型: {selected.model}, 1min调用次数: {selected.call_count_1min}, 权重: {selected.weight:.2f}")
            return selected


class LLMKeyManager:
    """LLM KEY管理器 - 统一管理多个API KEY（线程安全）"""

    def __init__(self, api_keys_config: List[Dict[str, str]]):
        """初始化KEY管理器

        Args:
            api_keys_config: API KEY配置列表
        """
        self.api_keys: List[APIKeyStatus] = []
        self._lock = threading.Lock()
        self._init_api_keys(api_keys_config)

        # 初始化相关组件
        self.call_stats = CallStatistics()
        self.health_checker = HealthChecker()
        self.load_balancer = LoadBalancer(self.call_stats)

    def _init_api_keys(self, api_keys_config: List[Dict[str, str]]):
        """初始化API KEY状态

        Args:
            api_keys_config: API KEY配置列表
        """
        for config in api_keys_config:
            key_status = APIKeyStatus(
                key=config.get('key', ''),
                model=config.get('model', 'unknown'),
                weight=float(config.get('weight', 1.0)),
                enabled=bool(config.get('enabled', True))
            )
            self.api_keys.append(key_status)

        print(f"[LLM KeyManager] 初始化了{len(self.api_keys)}个API KEY")

    def get_keys(self) -> List[APIKeyStatus]:
        """获取所有KEY状态（线程安全）

        Returns:
            API KEY状态列表
        """
        with self._lock:
            return self.api_keys.copy()

    def get_available_keys(self) -> List[APIKeyStatus]:
        """获取可用KEY状态（线程安全）

        Returns:
            可用的API KEY状态列表
        """
        with self._lock:
            return [k for k in self.api_keys if k.enabled and k.weight > 0]

    def record_call_result(self, key: str, success: bool, response_time: float = 0.0):
        """记录调用结果（线程安全）

        Args:
            key: API KEY
            success: 是否成功
            response_time: 响应时间（秒）
        """
        # 更新调用统计
        self.call_stats.record_call(key, success)

        # 找到对应的KEY状态
        with self._lock:
            key_status = next((k for k in self.api_keys if k.key == key), None)
        if key_status:
            self.health_checker.update_key_health(key_status, success, response_time)

    def get_key_status(self, key: str) -> Optional[APIKeyStatus]:
        """获取指定KEY的状态（线程安全）

        Args:
            key: API KEY

        Returns:
            KEY状态对象，如果不存在返回None
        """
        with self._lock:
            return next((k for k in self.api_keys if k.key == key), None)

    def enable_key(self, key: str):
        """启用指定KEY（线程安全）

        Args:
            key: API KEY
        """
        with self._lock:
            key_status = next((k for k in self.api_keys if k.key == key), None)
            if key_status:
                key_status.enabled = True
                key_status.consecutive_failures = 0
                key_status.weight = 0.5  # 重新启用时设置为中等权重
                print(f"[LLM KeyManager] 已启用API KEY: {key[:8]}...")

    def disable_key(self, key: str):
        """禁用指定KEY（线程安全）

        Args:
            key: API KEY
        """
        with self._lock:
            key_status = next((k for k in self.api_keys if k.key == key), None)
            if key_status:
                key_status.enabled = False
                print(f"[LLM KeyManager] 已禁用API KEY: {key[:8]}...")

    def get_status_report(self) -> Dict:
        """获取状态报告（线程安全）

        Returns:
            包含所有KEY状态的字典
        """
        with self._lock:
            report = {
                'total_keys': len(self.api_keys),
                'available_keys': len([k for k in self.api_keys if k.enabled and k.weight > 0]),
                'keys': []
            }

            for key_status in self.api_keys:
                report['keys'].append({
                    'key': key_status.key[:8] + '...',  # 只显示前8位
                    'model': key_status.model,
                    'enabled': key_status.enabled,
                    'weight': round(key_status.weight, 2),
                    'total_calls': key_status.total_calls,
                    'success_rate': round(key_status.success_rate, 3),
                    'consecutive_failures': key_status.consecutive_failures,
                    'call_count_1min': key_status.call_count_1min,
                    'response_time_avg': round(key_status.response_time_avg, 2)
                })

            return report