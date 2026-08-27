# -*- coding: utf-8 -*-
"""
charset.py —— 字符集档位（少/中/完整/自定义）

档位划分（按用户要求）：
  low    少：GB2312 一级+二级汉字 + 英文字母 + 常见标点/符号（如 ⬛ 等）
  medium 中：GB2312 一级+二级 + 部分 CJK 扩展生僻字 + 英文字母 + 全部标点、常用与少见符号
  full   完整：字体文件中包含的全部字符(由引擎枚举)
  custom 自定义：用户输入的码点区间
"""
from __future__ import annotations

# 英文字母/数字/基础英文标点（ASCII 可打印）
ASCII = list(range(0x20, 0x7F))

# ---- 常见标点与符号 ----
# 中文标点（全角）+ 常用符号
CJK_PUNCT = list(range(0x3000, 0x303F)) + list(range(0xFF01, 0xFF5F)) + list(range(0xFFE0, 0xFFE6))
# 常见英文/通用符号（引号、破折号、省略号、间隔号、¥、℃、№ 等）
COMMON_SYMBOLS = [
    0x2018, 0x2019, 0x201C, 0x201D, 0x2013, 0x2014, 0x2026, 0x2030,
    0x00A7, 0x00B7, 0x00A9, 0x00AE, 0x00B0, 0x00B1, 0x00D7, 0x00F7,
    0x20AC, 0x00A5, 0x2103, 0x2116, 0x2605, 0x2606, 0x25CF, 0x25CB,
    0x25A0, 0x25A1, 0x25B2, 0x25B3, 0x25C6, 0x25C7, 0x2764, 0x00A1,
    0x00BF, 0x2039, 0x203A, 0x2044, 0x00A2, 0x00A3, 0x00A4, 0x00A6,
    0x2190, 0x2191, 0x2192, 0x2193, 0x2194, 0x21D2, 0x21D4, 0x2208,
    0x2205, 0x2211, 0x221A, 0x221E, 0x2229, 0x222A, 0x2248, 0x2260,
    0x2264, 0x2265, 0x2312, 0x2460, 0x2474, 0x24EA, 0x3001, 0x3002,
]
# 少见/拓展符号（中档启用）：几何图形、表情方块、麻将、扑克、圆圈数字等
EXTRA_SYMBOLS = list(range(0x2700, 0x27BF)) + list(range(0x25A0, 0x2600)) + \
                list(range(0x1F300, 0x1F5FF)) + list(range(0x1F900, 0x1F9FF)) + \
                [0x2B1B, 0x2B1C, 0x2B50, 0x2B55, 0x1F600, 0x1F601, 0x1F602, 0x1F603, 0x1F604]

def _gb2312_uni():
    """按 GB2312 编码标准解码其全部汉字字符(一级+二级，共6763字)，返回码点列表。"""
    out = []
    for qu in range(16, 88):          # 16-55 = 一级(常用), 56-87 = 二级
        for wi in range(1, 95):
            try:
                s = bytes([qu + 0xA0, wi + 0xA0]).decode("gb2312")
                if len(s) == 1:
                    out.append(ord(s))
            except UnicodeDecodeError:
                continue
    return out

_GB = sorted(_gb2312_uni())            # GB2312 全部汉字(6763)

# 部分 CJK 扩展生僻字（中档）：扩展A区常见字
_EXT_A = list(range(0x3400, 0x4DBF))

def _low_chars():
    return sorted(set(ASCII) | set(CJK_PUNCT) | set(COMMON_SYMBOLS) | set(_GB))

def _medium_chars():
    return sorted(set(ASCII) | set(CJK_PUNCT) | set(COMMON_SYMBOLS) | set(EXTRA_SYMBOLS) | set(_GB) | set(_EXT_A))

PRESETS = {
    "low":    {"label": "少 (~7100)",  "chars_fn": _low_chars,
               "desc": "GB2312 一级+二级汉字(约6763) + 英文字母数字 + 常见中文标点/常用符号"},
    "medium": {"label": "中 (~15000)","chars_fn": _medium_chars,
               "desc": "GB2312 全部汉字 + 部分CJK扩展生僻字(扩展A) + 英文字母 + 全部标点/常用与少见符号"},
    "full":   {"label": "完整 (全部)","chars_fn": None,
               "desc": "字体文件内包含的全部字符(自动枚举)"},
    "custom": {"label": "自定义",      "chars_fn": None,
               "desc": "按用户输入的 Unicode 码点区间"},
}

def _base_chars():
    return sorted(set(ASCII) | set(CJK_PUNCT) | set(COMMON_SYMBOLS))

def preset_codepoints(name):
    """返回某个预设档位的码点列表；full/custom 返回 None(需另行处理)。"""
    if name not in PRESETS:
        name = "medium"
    p = PRESETS[name]
    if p["chars_fn"] is None:
        return None
    return sorted(set(p["chars_fn"]()))

def charset_label(name):
    p = PRESETS.get(name)
    return p["label"] if p else name

def charset_desc(name):
    p = PRESETS.get(name)
    return p.get("desc", "") if p else ""

def charset_info():
    """返回 {name: {label, desc, expected_count, count}}，供界面展示与提示。count/expected 为 None 表示需字体枚举。"""
    info = {}
    for name, p in PRESETS.items():
        expected = None
        if p["chars_fn"] is not None:
            expected = len(p["chars_fn"]())
        info[name] = {"label": p["label"], "desc": p.get("desc",""),
                      "expected_count": expected, "count": expected}
    return info

def missing_count(name, available_cps):
    """计算某档位规定的字符中，字体里缺失的字符数量。
    available_cps: 字体实际可用字符的码点集合。"""
    if name not in PRESETS:
        name = "medium"
    p = PRESETS[name]
    if p["chars_fn"] is None:
        return 0   # full 无固定字符，谈不上缺失
    needed = set(p["chars_fn"]())
    avail = set(available_cps)
    return len(needed - avail)

def parse_custom(chars_str):
    import re
    cps = set()
    for tok in re.split(r"[,\s]+", chars_str.strip()):
        if not tok: continue
        m = re.match(r"^(0x[0-9a-fA-F]+)-?(0x[0-9a-fA-F]+)?$", tok)
        if m:
            lo = int(m.group(1), 16)
            hi = int(m.group(2), 16) if m.group(2) else lo
            if lo <= hi:
                cps.update(range(lo, hi+1))
    return sorted(cps)
