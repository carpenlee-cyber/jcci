"""
标签短标识符统一工具函数。
所有模块必须从此处导入，禁止各自内联定义。
"""
import hashlib
import re


def extract_short_tag(tag: str) -> str:
    """
    从完整 tag 或 commit hash 提取可读短标识符（幂等）。

    格式：SHA{hash4}_{last11}

    规则：
    - 已经是短标识符格式: 直接返回（幂等，防止二次转换）
    - Commit Hash (40位十六进制): 保持旧行为，截取前8位（已唯一）
    - Git Tag: SHA256 前4位 + '_' + 后11位
      4位 hex 提供 65536 种区分，足以消除同一基线下的版本碰撞。

    示例：
    - SHAb42d_20231225_01 → SHAb42d_20231225_01 (幂等，不变)
    - dd6569c3558f79af5b21aad601349e0f029b9a6d → dd6569c3 (commit)
    - MIX_LJ01.ONB_ONB4_pipe_st_2_ST_00.03.05_SUMMER_20260506_01 → SHA3afe_20260506_01 (v1)
    - MIX_LJ01.ONB_ONB4_pipe_st_2_ST_00.03.06_SUMMER_20260506_01 → SHA6436_20260506_01 (v2)
    """
    if not tag:
        return ''

    # 幂等：已经是新短标识符格式 (SHA{4hex}_{11chars})，直接返回
    if re.match(r'^SHA[0-9a-f]{4}_[\w\.\-]{11}$', tag, re.IGNORECASE):
        return tag

    # 幂等：已经是旧短标识符格式（<=11字符 或 8位hex commit短哈希），直接返回
    if len(tag) <= 11:
        return tag
    if len(tag) == 8 and re.match(r'^[0-9a-f]{8}$', tag, re.IGNORECASE):
        return tag

    # Commit hash (40位十六进制)：保持旧行为，截取前8位
    if len(tag) == 40 and re.match(r'^[0-9a-f]{40}$', tag, re.IGNORECASE):
        return tag[:8]

    # Git Tag：SHA256 前4位 + '_' + 后11位
    hash4 = hashlib.sha256(tag.encode()).hexdigest()[:4]
    return f'SHA{hash4}_{tag[-11:]}'
