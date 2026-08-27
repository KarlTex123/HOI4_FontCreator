/*
 * font_engine.c —— 钢铁雄心4 字体生成器 光栅化引擎（M2）
 *
 * 功能：用 FreeType 加载 TTF/OTF，把指定字符集光栅化成灰度位图，
 *       排布进 2048x4096 图集。本文件先实现单线程正确版，M2 后续加并行。
 *
 * 输出协议（供上层 .fnt 生成使用）：把每个字形的 x/y/width/height/xoffset/
 *       yoffset/xadvance 写到一个易解析的文本结果（stdout），供 Python 层
 *       读取后生成 .fnt。同时输出一张原始 RGBA 图集（BMP 或 raw），供 M3 压缩成 DDS。
 *
 * 依赖：libfreetype
 * 编译：gcc font_engine.c -I<ft include> -L<ft objs> -lfreetype -o font_engine.exe
 */
#include <ft2build.h>
#include FT_FREETYPE_H
#include FT_BITMAP_H

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>

/* dds_compress.c 提供的 DXT5 写出函数 */
int write_dxt5_dds(const char *path, const uint8_t *rgba, int w, int h);

#define ATLAS_W 2048
#define ATLAS_H 4096
#define DEFAULT_PX 18
#define DEFAULT_PADDING 1
#define DEFAULT_SPACING_X 1
#define DEFAULT_SPACING_Y 1

/* 图集：一行行的网格排布。用简单的“行扫描”策略：每行固定高度 = 最大字形高 + padding，
 * 放不下则换行。*/
typedef struct {
    uint8_t *pixels;      /* ATLAS_W*ATLAS_H*4 RGBA，预填透明(0) */
    int cur_x, cur_y;     /* 当前可放位置 */
    int row_h;            /* 当前行高 */
    int line_h;           /* 行高(由字体 lineHeight 决定) */
} Atlas;

static Atlas atlas;

static void atlas_init(void) {
    atlas.pixels = (uint8_t*)calloc((size_t)ATLAS_W * ATLAS_H * 4, 1);
    atlas.cur_x = 0; atlas.cur_y = 0; atlas.row_h = 0;
    atlas.line_h = 0;
}

static void atlas_free(void) { free(atlas.pixels); }

/* 把 FT_Bitmap 的灰度字形画到图集，返回它在图集中的坐标 */
static int atlas_place_glyph(FT_Bitmap *bm, int pad, int *out_x, int *out_y) {
    int gw = bm->width, gh = bm->rows;
    int req_w = gw + 2*pad, req_h = gh + 2*pad;

    /* 需要换行 */
    if (atlas.cur_x + req_w > ATLAS_W) {
        atlas.cur_x = 0;
        atlas.cur_y += atlas.row_h + atlas.line_h? atlas.line_h - atlas.row_h : req_h;
        atlas.row_h = 0;
    }
    /* 超出高度则报错（应预先评估页数） */
    if (atlas.cur_y + req_h > ATLAS_H) { *out_x = -1; *out_y = -1; return 0; }

    int px = atlas.cur_x + pad, py = atlas.cur_y + pad;
    if (bm->pixel_mode == FT_PIXEL_MODE_GRAY) {
        for (int y = 0; y < gh; y++) {
            for (int x = 0; x < gw; x++) {
                unsigned char v = bm->buffer[y * bm->pitch + x];
                size_t idx = ((size_t)(py + y) * ATLAS_W + (px + x)) * 4;
                /* 白色字形 + alpha 遮罩：RGB=255, A=v */
                atlas.pixels[idx + 0] = 255;
                atlas.pixels[idx + 1] = 255;
                atlas.pixels[idx + 2] = 255;
                atlas.pixels[idx + 3] = v;
            }
        }
    } else if (bm->pixel_mode == FT_PIXEL_MODE_MONO) {
        for (int y = 0; y < gh; y++) {
            for (int x = 0; x < gw; x++) {
                int on = (bm->buffer[y * bm->pitch + (x/8)] >> (7 - (x%8))) & 1;
                size_t idx = ((size_t)(py + y) * ATLAS_W + (px + x)) * 4;
                atlas.pixels[idx + 0] = 255;
                atlas.pixels[idx + 1] = 255;
                atlas.pixels[idx + 2] = 255;
                atlas.pixels[idx + 3] = on ? 255 : 0;
            }
        }
    }

    int cell_advance = req_w + DEFAULT_SPACING_X;
    if (atlas.row_h < req_h) atlas.row_h = req_h;
    atlas.cur_x += cell_advance;

    *out_x = px; *out_y = py;
    return 1;
}

static void write_bmp(const char *path) {
    /* 简易 24-bit BMP 便于查验，仅用于开发诊断；把 alpha 作为灰度显示，便于看到字形形状 */
    int w = ATLAS_W, h = ATLAS_H;
    int rowBytes = (w*3 + 3) & ~3;
    int dataSize = rowBytes * h;
    int fileSize = 54 + dataSize;
    FILE *f = fopen(path, "wb");
    if (!f) return;
    unsigned char hdr[54] = {0};
    hdr[0]='B'; hdr[1]='M';
    hdr[2]=fileSize&0xff; hdr[3]=(fileSize>>8)&0xff; hdr[4]=(fileSize>>16)&0xff; hdr[5]=(fileSize>>24)&0xff;
    hdr[10]=54; hdr[14]=40; hdr[18]=w&0xff; hdr[19]=(w>>8)&0xff; hdr[20]=(w>>16)&0xff; hdr[21]=(w>>24)&0xff;
    hdr[22]=h&0xff; hdr[23]=(h>>8)&0xff; hdr[24]=(h>>16)&0xff; hdr[25]=(h>>24)&0xff;
    hdr[26]=1; hdr[28]=24;
    fwrite(hdr, 54, 1, f);
    for (int y = h-1; y >= 0; y--) {
        for (int x = 0; x < w; x++) {
            size_t idx = ((size_t)y*ATLAS_W + x)*4;
            unsigned char a = atlas.pixels[idx+3];   /* 用 alpha 做灰度 */
            fputc(a, f); fputc(a, f); fputc(a, f);
        }
        for (int pad = 0; pad < (rowBytes - w*3); pad++) fputc(0, f);
    }
    fclose(f);
}

int main(int argc, char **argv) {
    /* 参数：fontfile size [chars...]  —— 简化的 CLI，后续扩展 */
    if (argc < 3) {
        fprintf(stderr, "usage: font_engine <fontfile> <px> <unicode...>\n");
        return 1;
    }
    const char *fontfile = argv[1];
    int px = atoi(argv[2]);

    FT_Library lib;
    if (FT_Init_FreeType(&lib) != 0) { fprintf(stderr, "FT_Init failed\n"); return 1; }
    FT_Face face;
    if (FT_New_Face(lib, fontfile, 0, &face) != 0) {
        fprintf(stderr, "FT_New_Face failed: %s\n", fontfile);
        return 1;
    }
    FT_Set_Pixel_Sizes(face, 0, px);

    atlas_init();
    /* 行高由 face->size->metrics 决定 */
    atlas.line_h = face->size->metrics.height / 64;

    int n_chars = argc - 3;
    printf("ATLAS %d %d\n", ATLAS_W, ATLAS_H);
    printf("LINE_H %d\n", atlas.line_h);
    for (int i = 0; i < n_chars; i++) {
        unsigned long uc = strtoul(argv[3+i], NULL, 0);
        FT_UInt gid = FT_Get_Char_Index(face, uc);
        if (gid == 0) {
            printf("CHAR 0x%lx MISSING\n", uc);
            continue;
        }
        if (FT_Load_Glyph(face, gid, FT_LOAD_RENDER | FT_LOAD_TARGET_NORMAL) != 0) {
            printf("CHAR 0x%lx LOADERR\n", uc);
            continue;
        }
        FT_GlyphSlot slot = face->glyph;
        int ox, oy;
        if (!atlas_place_glyph(&slot->bitmap, DEFAULT_PADDING, &ox, &oy)) {
            printf("CHAR 0x%lx OVERSIZE\n", uc);
            continue;
        }
        int adv = slot->advance.x / 64;
        int bsx = slot->bitmap_left;
        int bsy = slot->bitmap_top;
        printf("CHAR 0x%lx %d %d %d %d %d %d %d\n",
               uc, ox, oy, slot->bitmap.width, slot->bitmap.rows, bsx, bsy, adv);
    }

    write_bmp("atlas_diag.bmp");
    /* M3: 输出 DXT5 DDS，作为正式产物 */
    if (write_dxt5_dds("atlas.dds", atlas.pixels, ATLAS_W, ATLAS_H) != 0) {
        fprintf(stderr, "write_dxt5_dds failed\n");
    } else {
        fprintf(stderr, "DDS written: atlas.dds\n");
    }
    printf("ATLAS_END\n");

    FT_Done_Face(face);
    FT_Done_FreeType(lib);
    atlas_free();
    return 0;
}
