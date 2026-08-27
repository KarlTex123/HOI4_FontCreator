# -*- coding: utf-8 -*-
"""
fontlib.py —— 字体发现与元数据（本地化显示名 + 搜索别名）

解决"思源黑体显示成 SourceHanSansSC-Medium"的问题：
- 扫描所有字体目录(系统+用户)，枚举 .otf/.ttf/.ttc
- 用 fontTools 读取字体的 name 表，拿到本地化显示名(如"思源黑体")、
  英文名(如 Source Han Sans SC)、家族名、字重、文件路径
- 返回结构化字体条目，搜索可匹配：中文名 / 英文名 / 注册名 / 文件名(去扩展)
"""
from __future__ import annotations
import os

FONT_EXTS = (".otf", ".ttf", ".ttc", ".otc")

_WEIGHT_NAMES = [
    ("Thin", "Thin"), ("ExtraLight", "ExtraLight"), ("UltraLight", "UltraLight"),
    ("Light", "Light"), ("Regular", "Regular"), ("Normal", "Regular"),
    ("Medium", "Medium"), ("DemiLight", "DemiLight"), ("SemiBold", "SemiBold"),
    ("Bold", "Bold"), ("ExtraBold", "ExtraBold"), ("Heavy", "Heavy"), ("Black", "Black"),
]

class FontEntry:
    """一个字体文件条目。display 用于界面显示，aliases 用于搜索匹配。"""
    __slots__ = ("path", "display", "family", "subfamily", "style", "aliases", "is_imported", "weight")
    def __init__(self, path, display, family, subfamily, style, aliases, is_imported=False, weight=None):
        self.path = path
        self.display = display          # 界面显示名（本地化优先）
        self.family = family            # 家族名
        self.subfamily = subfamily      # 字重/样式
        self.style = style              # 用于区分同名家族的不同字重
        self.aliases = aliases          # 搜索别名字符串列表
        self.is_imported = is_imported  # 用户导入的标记
        self.weight = weight            # 变字体字重坐标(wght 值)，非变字体=None(默认)

    def search_text(self):
        """用于搜索拼接的文本（小写）。"""
        parts = [self.display, self.family, self.subfamily, self.style] + list(self.aliases)
        return " ".join(str(p) for p in parts if p).lower()

def _font_dirs():
    """返回所有字体目录。"""
    dirs = []
    if os.environ.get("WINDIR"):
        dirs.append(os.path.join(os.environ["WINDIR"], "Fonts"))
    la = os.environ.get("LOCALAPPDATA", "")
    if la:
        dirs.append(os.path.join(la, "Microsoft", "Windows", "Fonts"))
    # 额外系统字体目录
    for extra in ("C:\\Windows\\Fonts", os.path.join(os.environ.get("ProgramData","C:\\ProgramData"), "Microsoft\\Windows\\Fonts")):
        if extra not in dirs:
            dirs.append(extra)
    return [d for d in dirs if os.path.isdir(d)]

def _read_name_table(path):
    """用 fontTools 读取字体的 name 表，返回 (family, subfamily, localized_display, aliases)。
    失败返回 None。"""
    try:
        from fontTools.ttLib import TTFont, TTCollection
        aliases = []
        # ttc 合集
        try:
            if path.lower().endswith((".ttc", ".otc")):
                coll = TTCollection(path)
                # 取第一个面
                font = coll.fonts[0]
            else:
                font = TTFont(path, fontNumber=0, lazy=True)
        except Exception:
            font = TTFont(path, lazy=True)
        name = font["name"]
        # 本地化显示名: 优先中文(zh-CN), 否则英文
        fam_en = None; fam_zh = None
        sub_en = None; sub_zh = None
        full_en = None; full_zh = None
        for rec in name.names:
            if rec.nameID == 1:     # family
                if rec.platformID == 3 or (rec.platformID == 1 and rec.langID in (0x804,0x409)):
                    # zh 语言ID 0x1004=zh-CN, 0x0804
                    if rec.langID in (0x804, 0x1004, 0x409) : 
                        pass
                if str(rec.langID).lower() in ("0x804","0x1004","2052","1028") and fam_zh is None:
                    fam_zh = rec.toUnicode()
                if fam_en is None:
                    fam_en = rec.toUnicode()
            elif rec.nameID == 17:  # subfamily (typographic)
                sub_en = sub_en or rec.toUnicode()
            elif rec.nameID == 2:   # subfamily (legacy style)
                sub_en = sub_en or rec.toUnicode()
            elif rec.nameID == 16:  # typographic family
                if fam_en is None:
                    fam_en = rec.toUnicode()
            elif rec.nameID == 4:   # full name
                full_en = full_en or rec.toUnicode()
        family = fam_en or full_en or os.path.splitext(os.path.basename(path))[0]
        subfamily = sub_en or ""
        # 本地化显示: 优先中文家族+字重
        if fam_zh:
            display = fam_zh
            if subfamily and subfamily.lower() not in ("regular","normal"):
                display = fam_zh + " " + subfamily
        else:
            display = (family + (" " + subfamily if subfamily and subfamily.lower() not in ("regular","normal") else "")).strip()
        # 别名: 文件基名(去扩展, 去空格下划线), 家族名, 全名
        stem = os.path.splitext(os.path.basename(path))[0]
        for a in (stem, family, full_en, fam_zh):
            if a:
                aliases.append(a)
        try:
            font.close()
        except Exception:
            pass
        return family, subfamily, display, aliases
    except Exception:
        return None

def _enum_font_variants(path):
    """若字体是可变字体(variable)，返回 [(subfamily, wght)] 字重实例列表；否则返回 []。
    wght 为 100~900 的数值(如 Bold=700)。供字重选择用。"""
    try:
        from fontTools.ttLib import TTFont
        font = TTFont(path, lazy=True)
        if "fvar" not in font:
            font.close()
            return []
        fvar = font["fvar"]
        name = font["name"]
        res = []
        for inst in fvar.instances:
            coords = inst.coordinates   # 可能是 dict {'wght': 100} 或 list
            wght = None
            if isinstance(coords, dict):
                wght_val = coords.get("wght")
                if isinstance(wght_val, (int, float)):
                    wght = int(round(wght_val))
            elif isinstance(coords, (list, tuple)):
                # 找 wght 轴索引
                for i, ax in enumerate(fvar.axes):
                    if ax.axisTag == "wght" and i < len(coords) and isinstance(coords[i], (int, float)):
                        wght = int(round(coords[i]))
                        break
            try:
                iname = name.getDebugName(inst.subfamilyNameID) or ""
            except Exception:
                iname = ""
            if not iname:
                iname = "Regular"
            res.append((iname, wght))
        try:
            font.close()
        except Exception:
            pass
        return res
    except Exception:
        return []

def scan_fonts():
    """扫描所有字体文件，返回 FontEntry 列表（已排序）。
    可变字体(variable)会按字重展开为多个条目（如 鸿蒙黑体 Regular/Bold/...）。"""
    entries = []
    seen = set()   # 去重 by (path, weight)
    for d in _font_dirs():
        try:
            files = os.listdir(d)
        except OSError:
            continue
        for fn in sorted(files):
            if not fn.lower().endswith(FONT_EXTS):
                continue
            path = os.path.join(d, fn)
            try:
                meta = _read_name_table(path)
            except Exception:
                meta = None
            if not meta:
                family, subfamily, display, aliases = fn, "", os.path.splitext(fn)[0], [os.path.splitext(fn)[0]]
            else:
                family, subfamily, display, aliases = meta
            # 变字体：按字重展开为多个条目
            variants = _enum_font_variants(path)
            if len(variants) > 1:
                base_display = display
                for vname, wght in variants:
                    d_disp = base_display
                    if vname and vname.lower() not in ("regular", "normal"):
                        d_disp = base_display + " " + vname
                    key = (path.lower(), wght if wght is not None else vname.lower())
                    if key in seen:
                        continue
                    seen.add(key)
                    aliases2 = aliases + [base_display + " " + vname, vname]
                    entries.append(FontEntry(path, d_disp, family, vname, "", aliases2, weight=wght))
                continue
            # 普通字体
            key = (path.lower(), 0)
            if key in seen:
                continue
            seen.add(key)
            entries.append(FontEntry(path, display, family, subfamily, "", aliases))
    entries.sort(key=lambda e: e.display.lower())
    return entries
