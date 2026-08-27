# -*- coding: utf-8 -*-
"""
preview.py —— 字体生成后预览模块

读取生成的多页 .fnt + .dds（HOI4 位图字体），在 1920x1080 逻辑画布上
按 HOI4 规则渲染一段文字，输出 PNG。供前端以"屏幕等比缩放"方式显示，
字号与 1080p 游戏窗口完全一致。

- .dds 为 DXT5(BC3)，含"白色字形 + alpha 遮罩"
- .fnt 为按页拆分：每页一个 .fnt + 同名 .dds；char 行的 x/y/width/height/
  xoffset/yoffset/xadvance 定位字形
"""
from __future__ import annotations
import os, struct, re, io
from PIL import Image

CANVAS_W = 1920
CANVAS_H = 1080
LINE_MARGIN = 2   # 行间距(px)

class CharDef:
    __slots__ = ("page","code","x","y","w","h","xoff","yoff","adv")
    def __init__(self, page, code, x, y, w, h, xoff, yoff, adv):
        self.page=page; self.code=code; self.x=x; self.y=y
        self.w=w; self.h=h; self.xoff=xoff; self.yoff=yoff; self.adv=adv

# ---- DXT5(BC3) 解码 ----
def _dxt5_decode_block(b):
    """解码 DXT5(BC3) 4x4 块，返回 (alphas[16], rgb[16])。
    alphas: 每像素 alpha(从8字节alpha表)；rgb: 每像素 (r,g,b) 灰度(BC1颜色)。"""
    # alpha 段(前8字节)
    a0, a1 = b[0], b[1]
    alut = [a0, a1]
    if a0 > a1:
        for i in range(6): alut.append((a0*(6-i)+a1*(i+1))//7)
    else:
        for i in range(4): alut.append((a0*(4-i)+a1*(i+1))//5)
        alut += [0, 255]
    a_bits = int.from_bytes(b[2:8], "little")
    alphas = [alut[(a_bits >> (i*3)) & 7] for i in range(16)]
    # BC1 颜色段(后8字节): c0(2B), c1(2B), 4字节索引(每像素2bit)
    c0 = struct.unpack_from("<H", b, 8)[0]
    c1 = struct.unpack_from("<H", b, 10)[0]
    def unp565(v):
        return (((v>>11)&0x1F)*255//31, ((v>>5)&0x3F)*255//63, (v&0x1F)*255//31)
    rgb0 = unp565(c0); rgb1 = unp565(c1)
    pal = [rgb0, rgb1]
    if c0 > c1:
        pal.append(tuple((2*rgb0[i]+rgb1[i])//3 for i in range(3)))
        pal.append(tuple((rgb0[i]+2*rgb1[i])//3 for i in range(3)))
    else:
        pal.append(tuple((rgb0[i]+rgb1[i])//2 for i in range(3)))
        pal.append((0,0,0))
    c_bits = struct.unpack_from("<I", b, 12)[0]
    rgb = [pal[(c_bits >> (i*2)) & 3] for i in range(16)]
    return alphas, rgb

def load_dds_mask(path, use_alpha=True):
    """读取 DXT5 .dds，返回 (w, h, mask: bytearray)。
    use_alpha=True 时从 alpha 通道取遮罩(本生成器：白字+alpha)；
    use_alpha=False 时从 RGB(蓝通道)取字形亮部遮罩(BMFont：redChnl=4 等)。"""
    data = open(path, "rb").read()
    W = struct.unpack_from("<I", data, 16)[0]
    H = struct.unpack_from("<I", data, 12)[0]
    off = 128
    kw, kh = W//4, H//4
    mask = bytearray(W*H)
    for by in range(kh):
        for bx in range(kw):
            bi = by*kw + bx
            blk = data[off + bi*16 : off + bi*16 + 16]
            alphas, rgb = _dxt5_decode_block(blk)
            for yy in range(4):
                for xx in range(4):
                    gx = bx*4+xx; gy = by*4+yy
                    # 从输入像素的 (R,G,B) 中拿"字形所在通道"。本生成器字形为白色，
                    # BMFont 常把字形放进蓝色通道，用其亮度作为遮罩。
                    pix = rgb[yy*4+xx]
                    if use_alpha:
                        v = alphas[yy*4+xx]
                    else:
                        v = pix[2]  # 蓝通道亮度(字形遮罩)
                    if gx < W and gy < H:
                        mask[gy*W + gx] = v
    return W, H, mask

# ---- .fnt 解析 ----
def parse_fnt(path):
    """解析单页 .fnt，返回 (scaleW, scaleH, lineHeight, base, [CharDef])。"""
    scaleW = scaleH = line_height = base = 0
    chars = []
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if line.startswith("common "):
                m = re.search(r'scaleW=(\d+)', line); scaleW = int(m.group(1)) if m else 0
                m = re.search(r'scaleH=(\d+)', line); scaleH = int(m.group(1)) if m else 0
                m = re.search(r'lineHeight=(\d+)', line); line_height = int(m.group(1)) if m else 0
                m = re.search(r'base=(\d+)', line); base = int(m.group(1)) if m else 0
            elif line.startswith("char id="):
                m = re.search(r'id=(\d+)', line); code = int(m.group(1)) if m else 0
                m = re.search(r'x=(\d+)', line); x = int(m.group(1)) if m else 0
                m = re.search(r'y=(\d+)', line); y = int(m.group(1)) if m else 0
                m = re.search(r'width=(\d+)', line); w = int(m.group(1)) if m else 0
                m = re.search(r'height=(\d+)', line); h = int(m.group(1)) if m else 0
                m = re.search(r'xoffset=(-?\d+)', line); xoff = int(m.group(1)) if m else 0
                m = re.search(r'yoffset=(-?\d+)', line); yoff = int(m.group(1)) if m else 0
                m = re.search(r'xadvance=(-?\d+)', line); adv = int(m.group(1)) if m else 0
                chars.append(CharDef(0, code, x, y, w, h, xoff, yoff, adv))
    return scaleW, scaleH, line_height, base, chars

class FontPages:
    """一个字体的全部页。按 char code 索引。"""
    def __init__(self):
        self.chars = {}      # code -> CharDef
        self.alphas = {}     # page -> alpha bytearray
        self.sizes = {}      # page -> (w,h)
        self.line_h = 26
        self.base = 18

def load_font(out_dir, prefix, use_alpha=True):
    """从输出目录加载字体(多页)。按 <prefix>_N.fnt + <prefix>_N.dds 探测页数。

    use_alpha=True 时字形遮罩取自 alpha 通道——本生成器与 BMFont 字形都实际存于
    DXT5 的 alpha 通道(白字+alpha遮罩，.fnt 仅声明值不同)，统一从 alpha 读取最可靠。
    也支持 BMFont 单文件：<prefix>.fnt + <prefix>_0.dds。
    """
    fp = FontPages()
    page = 0
    while True:
        fnt = os.path.join(out_dir, f"{prefix}_{page}.fnt")
        dds = os.path.join(out_dir, f"{prefix}_{page}.dds")
        if not os.path.isfile(fnt) or not os.path.isfile(dds):
            # 尝试单文件形式: <prefix>.fnt + <prefix>.dds (同名, 如官方 cg_16b_2of4)
            if page == 0:
                alt_fnt = os.path.join(out_dir, prefix + ".fnt")
                alt_dds = os.path.join(out_dir, prefix + ".dds")
                if os.path.isfile(alt_fnt) and os.path.isfile(alt_dds):
                    fnt, dds = alt_fnt, alt_dds
                else:
                    # 再尝试 BMFont 形式: <prefix>.fnt + <prefix>_0.dds
                    alt_fnt = os.path.join(out_dir, prefix + ".fnt")
                    alt_dds = os.path.join(out_dir, prefix + "_0.dds")
                    if not os.path.isfile(alt_fnt) or not os.path.isfile(alt_dds):
                        break
                    fnt, dds = alt_fnt, alt_dds
            else:
                break
        sw, sh, lh, base, chars = parse_fnt(fnt)
        if page == 0:
            fp.line_h = lh; fp.base = base
        W, H, mask = load_dds_mask(dds, use_alpha=use_alpha)
        fp.sizes[page] = (W, H)
        fp.alphas[page] = mask
        for c in chars:
            c.page = page
            fp.chars[c.code] = c
        page += 1
        # 若只用单文件形式且已加载，则结束
        if not os.path.isfile(os.path.join(out_dir, f"{prefix}_{page}.fnt")):
            if page >= 1 and not os.path.isfile(os.path.join(out_dir, f"{prefix}_{page}.dds")):
                break
    return fp if fp.chars else None

def _get_alpha(fp, page, x, y):
    W, H = fp.sizes[page]
    if 0 <= x < W and 0 <= y < H:
        return fp.alphas[page][y*W + x]
    return 0

def render_png(fp, text, width=CANVAS_W, height=CANVAS_H, color=(0,0,0,255), bg=(240,240,240,255), background=None, transparent=False):
    """在 width x height 画布上渲染 text，自动换行。返回 PNG bytes。

    字形为"白色 + alpha 遮罩"：边缘 alpha 半透明 → 用 alpha 与背景混合，抗锯齿平滑。
    transparent=True 时：背景全透明，仅字形处着色(alpha=255, 边缘按字形alpha)。
    透明背景用于 GUI 预览——白底固定在外层舞台容器，缩放只变字、白窗不动。
    """
    if background is not None:
        bg = background
    if transparent:
        bg = (0, 0, 0, 0)
    img = Image.new("RGBA", (width, height), bg)
    px = img.load()
    br, bgc, bb, _ = bg
    cr, cg, cb, _ = color
    base = fp.base
    # 逐字排版
    x = y = 0
    for ch in text:
        code = ord(ch)
        c = fp.chars.get(code)
        if c is None:
            x += 20; continue
        if x + c.w > width:     # 换行
            x = 0
            y += fp.line_h + LINE_MARGIN
        if y + fp.line_h > height:
            break
        # 引擎/官方约定：glyphTop = 行顶 + yoffset(yoffset 是字形顶部到行顶的距离, 汉字≈0对齐)
        # (与官方 cg_16b 一致——用 base-yoff 是错误的，会导致歪斜)
        for gy in range(c.h):
            for gx in range(c.w):
                a = _get_alpha(fp, c.page, c.x + gx, c.y + gy)
                if a == 0:
                    continue
                dx = x + c.xoff + gx
                dy = y + c.yoff + gy
                if 0 <= dx < width and 0 <= dy < height:
                    if transparent:
                        # 字形颜色 + 字形alpha(保留半透明边缘)，白底由外层提供
                        px[dx, dy] = (cr, cg, cb, a)
                    else:
                        t = a / 255.0
                        r = round(br*(1-t) + cr*t)
                        g = round(bgc*(1-t) + cg*t)
                        b = round(bb*(1-t) + cb*t)
                        px[dx, dy] = (r, g, b, 255)
        x += c.adv
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
