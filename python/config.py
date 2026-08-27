# -*- coding: utf-8 -*-
"""
config.py —— 配置读取/写入/默认值/管理（与 BMFont .bmfc 兼容）

默认值取自 font_config.bmfc:
    outWidth=2048 outHeight=4096 outBitDepth=32 textureCompression=3(DXT5)
    padding=0 spacing=1 useClearType=0 useSmoothing=1 aa=4(超采样) useHinting=1
    renderFromOutline=1
但引擎输出的 .fnt 通道我们修正为白字遮罩: alphaChnl=8 redChnl=1 greenChnl=2 blueChnl=4
"""
from __future__ import annotations
import json, os, re

# 与 HOI4 标准的引擎默认值
DEFAULTS = {
    # 图集
    "out_width": 2048,
    "out_height": 4096,
    "bit_depth": 32,              # 32 (RGBA)
    "compression": "DXT5",        # DXT5 / DXT1
    # 字体渲染
    "font_size": 18,
    "display_size": 22,           # 字号(界面引用/文件名标注, = font_size*1.33+1)
    "aa": 2,                      # 超采样等级 (2/4)
    "use_smoothing": True,
    "use_hinting": True,
    "use_clear_type": False,
    "render_from_outline": True,
    "use_supersampling": True,     # 超采样开关
    # 布局
    "padding": 1,                 # 建议 1, 防细笔画断
    "spacing_x": 1,
    "spacing_y": 1,
    # 通道 (白字遮罩标准)
    "alpha_chnl": 8,
    "red_chnl": 1,
    "green_chnl": 2,
    "blue_chnl": 4,
    # 性能
    "threads": 0,                 # 0=自动(CPU核心数)
    # 输出
    "out_dir": "",
    "font_name": "",
    "font_file": "",
    "custom_name": "",             # 自定义字体名前缀(用于 xxx_0.fnt/.dds), 空=用字体文件名
    "make_subfolder": True,        # 自动生成字体文件夹: 输出到 <out_dir>/<字体名>/ (默认勾选)
    "char_set_preset": "full",    # 字符集档位 (默认"完整(全部)")
    "custom_chars": "",           # 自定义字符(按档位"custom"时)
}

def _strbool(v):
    return str(v).strip() in ("1", "true", "True", "yes")

# 从 .bmfc 解析字段 -> 我们的配置
BMFC_MAP = {
    "outWidth": ("out_width", int),
    "outHeight": ("out_height", int),
    "outBitDepth": ("bit_depth", int),
    "fontSize": ("font_size", int),
    "aa": ("aa", int),
    "useSmoothing": ("use_smoothing", _strbool),
    "useHinting": ("use_hinting", _strbool),
    "useClearType": ("use_clear_type", _strbool),
    "renderFromOutline": ("render_from_outline", _strbool),
    "paddingLeft": ("padding", int),
    "spacingHoriz": ("spacing_x", int),
    "spacingVert": ("spacing_y", int),
    "fontFile": ("font_file", str),
    "fontName": ("font_name", str),
}

def _strbool(v):
    return str(v).strip() in ("1", "true", "True", "yes")

def load_bmfc_defaults(path):
    """从 .bmfc 读取并并入默认配置。返回 dict。"""
    cfg = dict(DEFAULTS)
    if not os.path.isfile(path):
        return cfg
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k = k.strip(); v = v.strip()
                if k in BMFC_MAP:
                    key, conv = BMFC_MAP[k]
                    try:
                        cfg[key] = conv(v)
                    except Exception:
                        pass
    except Exception:
        pass
    return cfg

def save_config(path, cfg):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)

def load_config(path):
    if not os.path.isfile(path):
        return dict(DEFAULTS)
    with open(path, "r", encoding="utf-8") as f:
        cfg = dict(DEFAULTS)
        data = json.load(f)
        cfg.update(data)
        return cfg

def reset_default():
    return dict(DEFAULTS)

# 参与"配置相同"判定的有意义字段（排除与运行环境相关的路径/临时字段）
MEANINGFUL_KEYS = [
    "font_size", "display_size", "aa", "use_smoothing", "use_hinting", "use_clear_type",
    "render_from_outline", "use_supersampling",
    "padding", "spacing_x", "spacing_y",
    "threads", "custom_name", "make_subfolder",
    "char_set_preset", "custom_chars", "compression",
]

def sig(cfg):
    """提取配置的签名(有意义字段的规范化元组)，用于比较两个配置是否一致。"""
    c = cfg if isinstance(cfg, dict) else dict(DEFAULTS)
    return tuple((k, repr(c.get(k))) for k in MEANINGFUL_KEYS if k in c)

def configs_equal(a, b):
    return sig(a) == sig(b)

def validate(cfg):
    """校验并规范化配置，返回 (cfg, 错误列表)。"""
    errs = []
    c = dict(cfg)
    c["out_width"] = int(c.get("out_width", 2048))
    c["out_height"] = int(c.get("out_height", 4096))
    # 字号(display_size)为主值；字体大小(font_size) = 字号 × 4/5 + 1（若未单独存则派生）
    c["display_size"] = int(c.get("display_size", 22) or 22)
    c["font_size"] = int(c.get("font_size", 0) or (c["display_size"] * 4 // 5 + 1))
    c["aa"] = int(c.get("aa", 2))
    if c["out_width"] % 4 or c["out_height"] % 4:
        errs.append("图集宽高必须是4的倍数")
    if c["font_size"] <= 0:
        errs.append("字号必须为正")
    if c["compression"] not in ("DXT5", "DXT1"):
        errs.append("压缩格式只能是 DXT5 或 DXT1")
    c["padding"] = int(c.get("padding", 1))
    c["spacing_x"] = int(c.get("spacing_x", 1))
    c["spacing_y"] = int(c.get("spacing_y", 1))
    c["threads"] = int(c.get("threads", 0))
    # 字符串字段直接透传；布尔字段规范化
    c["custom_name"] = str(c.get("custom_name", "") or "")
    c["char_set_preset"] = c.get("char_set_preset", "medium")
    c["custom_chars"] = str(c.get("custom_chars", "") or "")
    c["out_dir"] = str(c.get("out_dir", "") or "")
    c["font_file"] = str(c.get("font_file", "") or "")
    c["font_name"] = str(c.get("font_name", "") or "")
    c["make_subfolder"] = bool(c.get("make_subfolder", False))
    c["use_supersampling"] = bool(c.get("use_supersampling", True))
    return c, errs
