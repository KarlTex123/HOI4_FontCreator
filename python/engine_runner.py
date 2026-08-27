# -*- coding: utf-8 -*-
"""
engine_runner.py —— Python 逻辑层：调用 font_engine.exe 并生成钢4单页 .fnt

职责：
1. 构造字符集文件(由 charsfile 生成)
2. 调用 font_engine.exe 光栅化 + 生成每页 .dds
3. 解析引擎输出的 CHAR/PAGE 数据
4. 按 split_fnt_pages.py 的格式生成每页拆分后的单页 .fnt

单页 .fnt 格式(HOI4 要求, 与 split_fnt_pages.py 一致):
    info face="<输出文件名>" ...
    common ... pages=1 ...
    chars count=<该页字符数>
    page id=0 file="<输出文件名>.dds"
    char id=.. x=.. y=.. width=.. height=.. xoffset=.. yoffset=.. xadvance=.. page=0 chnl=15
"""
from __future__ import annotations
import subprocess, os, sys, re, tempfile, dataclasses

_HERE = os.path.dirname(os.path.abspath(__file__))
# 打包模式: PyInstaller 把资源放在 sys._MEIPASS; 否则用工具根目录
if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
    _ROOT = sys._MEIPASS
else:
    _ROOT = os.path.dirname(_HERE)   # tool/
# 引擎目录: 打包后在根下 engine/，开发时在 tool/engine/
def _find_engine():
    for cand in (os.path.join(_ROOT, "engine", "font_engine.exe"),
                 os.path.join(_ROOT, "font_engine.exe"),
                 os.path.join(_HERE, "..", "engine", "font_engine.exe")):
        if os.path.isfile(cand):
            return cand
    return os.path.join(_ROOT, "engine", "font_engine.exe")

ENGINE = _find_engine()

@dataclasses.dataclass
class Glyph:
    page: int
    code: int
    x: int; y: int; w: int; h: int
    xoff: int; yoff: int; adv: int

def build_charsfile(codepoints, path):
    """把 unicode 码点列表写成引擎可读的区间文件。"""
    # 简单做法: 每行一个码点(区间合并留给 char 生成层, 这里按相邻合并)
    cps = sorted(set(codepoints))
    ranges = []
    start = prev = cps[0]
    for c in cps[1:]:
        if c == prev + 1:
            prev = c
        else:
            ranges.append((start, prev)); start = prev = c
    ranges.append((start, prev))
    with open(path, "w", encoding="utf-8") as f:
        for lo, hi in ranges:
            if lo == hi:
                f.write("0x%X\n" % lo)
            else:
                f.write("0x%X-0x%X\n" % (lo, hi))

def run_engine(font_file, px, outprefix, face_name, charsfile,
               pad=1, spacingx=1, spacingy=1, aa=2, threads=0, outdir=None, weight=None):
    """调用引擎，返回 (glyphs 列表, 引擎stderr)。weight 为变字体字重(wght)，None=默认。"""
    if not os.path.isfile(ENGINE):
        raise FileNotFoundError(f"引擎不存在: {ENGINE}")
    cmd = [ENGINE, font_file, str(px),
           "--outprefix", outprefix,
           "--face", face_name,
           "--pad", str(pad),
           "--spacingx", str(spacingx),
           "--spacingy", str(spacingy),
           "--aa", str(aa),
           "--threads", str(threads),
           "--charsfile", charsfile]
    if weight is not None:
        cmd += ["--weight", str(int(weight))]
    if outdir:
        cwd = outdir
    else:
        cwd = os.path.dirname(os.path.abspath(font_file))
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd)
    if proc.returncode != 0:
        raise RuntimeError(f"引擎出错 rc={proc.returncode}: {proc.stderr[-2000:]}")
    return parse_output(proc.stdout), proc.stderr

def parse_output(stdout):
    """解析引擎 stdout 的 CHAR/PAGE 行。返回 dict(含 glyphs/face/pages/atlas/line_h/base)。"""
    glyphs = {}
    face = None; pages = []; atlas_w = atlas_h = 0; line_h = 0; base = 0
    for line in stdout.splitlines():
        line = line.strip()
        if not line: continue
        parts = line.split()
        if parts[0] == "FACE":
            face = parts[1]
        elif parts[0] == "ATLAS_W":
            atlas_w = int(parts[1]); atlas_h = int(parts[3]) if len(parts)>3 else 0
        elif parts[0] == "LINE_H":
            line_h = int(parts[1])
        elif parts[0] == "BASE":
            base = int(parts[1])
        elif parts[0] == "PAGES":
            pass
        elif parts[0] == "PAGE":
            p = int(parts[1])
        elif parts[0] == "CHAR" and len(parts) >= 10:
            pg = int(parts[1])
            code = int(parts[2], 16)
            x, y, w, h = int(parts[3]), int(parts[4]), int(parts[5]), int(parts[6])
            xoff, yoff, adv = int(parts[7]), int(parts[8]), int(parts[9])
            glyphs.setdefault(pg, []).append(Glyph(pg, code, x, y, w, h, xoff, yoff, adv))
    return {"glyphs": glyphs, "face": face, "pages": sorted(glyphs.keys()),
            "atlas_w": atlas_w, "atlas_h": atlas_h, "line_h": line_h, "base": base}

def generate_fnt_for_page(page_no, glyphs, out_stem, line_height, base, atlas_w, atlas_h,
                          face_fallback, pad=1, spacing=1, font_size=18):
    """按 split_fnt_pages.py 格式生成单页 .fnt 文本。

    注意：与 HOI4 游戏本体一致——common 行【不写】alphaChnl/redChnl/greenChnl/blueChnl
    通道字段，避免引擎按错误通道读取字形导致歪扭/乱码。char 行的 page/chnl 保留(游戏本体亦然)。
    """
    gs = sorted(glyphs, key=lambda g: g.code)
    lines = []
    # info 行(face = 输出文件名 = out_stem)，size 用真实字号
    lines.append('info face="%s" size=%d bold=0 italic=0 charset="" unicode=1 '
                 'stretchH=100 smooth=1 aa=1 padding=0,0,0,0 spacing=1,1 outline=0'
                 % (out_stem, font_size))
    # common 行: 与游戏本体一致，不写通道字段
    lines.append('common lineHeight=%d base=%d scaleW=%d scaleH=%d pages=1 packed=0'
                 % (line_height, base, atlas_w, atlas_h))
    lines.append('chars count=%d' % len(gs))
    lines.append('page id=0 file="%s.dds"' % out_stem)
    for g in gs:
        lines.append('char id=%d   x=%d   y=%d   width=%d     height=%d     '
                     'xoffset=%d     yoffset=%d     xadvance=%d     page=0  chnl=15'
                     % (g.code, g.x, g.y, g.w, g.h, g.xoff, g.yoff, g.adv))
    return "\r\n".join(lines) + "\r\n"

def main():
    # 测试: 用思源黑体生成少量字验证 .fnt
    font = r"C:\Users\aaa15\Desktop\SimplifiedChinese\SourceHanSansSC-Regular.otf"
    outprefix = "test_gen"
    outdir = tempfile.mkdtemp(prefix="fnttest_")
    charsfile = os.path.join(outdir, "chars.txt")
    build_charsfile([0x91D1, 0x878D, 0x6D77, 0x5578, 0x8513, 0x5EF6], charsfile)
    info, _err = run_engine(font, 18, outprefix, "test_gen", charsfile,
                            pad=1, spacingx=1, spacingy=1, aa=2, outdir=outdir)
    print("face=", info["face"], "pages=", info["pages"])
    for pg in info["pages"]:
        stem = "%s_%d" % (outprefix, pg)
        fnt = generate_fnt_for_page(pg, info["glyphs"][pg], stem,
                                    line_height=26, base=18,
                                    atlas_w=info["atlas_w"], atlas_h=info["atlas_h"],
                                    face_fallback=info["face"], pad=1, spacing=1)
        path = os.path.join(outdir, stem + ".fnt")
        open(path, "w", encoding="utf-8", newline="").write(fnt)
        print("写了", path)
    print("outdir=", outdir)
    # 校验生成的几个 fnt 是否与期望结构一致
    for pg in info["pages"]:
        p = os.path.join(outdir, "%s_%d.fnt" % (outprefix, pg))
        if os.path.isfile(p):
            head = open(p, encoding="utf-8").read().splitlines()
            print("  ---", os.path.basename(p))
            for ln in head[:5]:
                print("   ", ln[:110])

def enumerate_font_chars(font_path):
    """枚举字体文件中包含的全部 Unicode 码点(用于计算缺失字符)。返回 set。"""
    cps = set()
    try:
        from fontTools.ttLib import TTFont, TTCollection
        try:
            if font_path.lower().endswith((".ttc", ".otc")):
                coll = TTCollection(font_path)
                fonts = coll.fonts
            else:
                fonts = [TTFont(font_path, lazy=True)]
        except Exception:
            fonts = [TTFont(font_path, lazy=True)]
        for font in fonts:
            try:
                cmap = font.getBestCmap()
                if cmap:
                    cps.update(cmap.keys())
            except Exception:
                continue
            try:
                font.close()
            except Exception:
                pass
    except Exception:
        pass
    return cps

if __name__ == "__main__":
    main()
