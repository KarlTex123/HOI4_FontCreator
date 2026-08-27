# -*- coding: utf-8 -*-
"""
size_calib.py —— 字号自动校准（视觉大小同步）

不同字体在同一 px 下视觉大小不同（如思源黑体字面大留白多、鸿蒙黑体紧凑）。
本模块用 FreeType 测「永」字的实际 ink 高度比例，把目标视觉高度规范成实际字号，
使不同字体在同一视觉 px 下看起来大小一致。
"""
from __future__ import annotations
import ctypes, os, ctypes.util

# 直接用 fontTools 测量字体的 unitsPerEm 和特定字形的 bbox
# 思源黑体 unitsPerEm=1000, '永' ink 高/em ≈ 0.918

def measure_glyph_ratio(font_path, char="永"):
    """返回 (units_per_em, ink_height_ratio)。char 的 ink 高度 / em。"""
    from fontTools.ttLib import TTFont
    from fontTools.pens.boundsPen import BoundsPen
    try:
        f = TTFont(font_path)
        head = f["head"]
        upm = head.unitsPerEm
        cmap = f.getBestCmap()
        gname = cmap.get(ord(char))
        if gname is None:
            return upm, 1.0
        gs = f.getGlyphSet()
        bp = BoundsPen(gs)
        gs[gname].draw(bp)
        if bp.bounds is None:
            return upm, 1.0
        xmin, ymin, xmax, ymax = bp.bounds
        h = ymax - ymin
        return upm, (h / upm) if upm else 1.0
    except Exception:
        return 1000, 1.0

def calibrate_size(font_path, target_px, reference_ratio=None):
    """返回【实际字体大小(ppem)】，使不同字体在同一 target_px 下视觉大小一致。

    目标：字形实际渲染高度 = target_px * VISUAL_RATIO（匹配 HOI4 官方字体视觉基准）。
    官方数据显示：官方"字体大小18"时字形视觉高≈15px，即基准视觉比例 ≈ 0.83。
    算法：ppem = target_visual_height / ink_ratio。
      · target_visual_height = round(target_px * VISUAL_RATIO)  统一视觉高
      · ink_ratio = 字体字形"永"的 ink 高 / em（FreeType 测得）
    这样思源(0.918)、鸿蒙(0.927)等字体在"字体大小18"下都渲染出≈15px 的字形，
    视觉大小一致，且匹配官方。
    """
    VISUAL_RATIO = 0.83   # 官方字体的字形视觉高 / 显示字号 平均基准
    upm, ratio = measure_glyph_ratio(font_path)
    if ratio <= 0:
        ratio = 1.0
    target_visual_h = round(target_px * VISUAL_RATIO)
    engine_px = max(1, round(target_visual_h / ratio))
    return engine_px, ratio

if __name__ == "__main__":
    import sys
    p = r"C:\Users\aaa15\Desktop\SimplifiedChinese\SourceHanSansSC-Regular.otf"
    upm, ratio = measure_glyph_ratio(p)
    print(f"思源黑体: upm={upm}, '永' ink高/em={ratio:.3f}")
    for tgt in (16, 18, 20):
        px, r = calibrate_size(p, tgt)
        print(f"  目标视觉 {tgt}px -> 引擎字号 {px}px")
