/*
 * font_engine.c —— 钢铁雄心4 字体生成器 光栅化引擎（多页版，M2+M3+M4 核心）
 *
 * 功能：用 FreeType 加载 TTF/OTF，把指定字符集光栅化成灰度位图，
 *       自动分配到多张 2048x4096 图集（每页一个 .dds，DXT5/白字遮罩），
 *       并把每个字形数据写到 stdout，供上层生成每页拆分后的 .fnt。
 *
 * 输出协议（stdout，供 Python 生成 .fnt）：
 *   ATLAS_W <w> ATLAS_H <h> PAGES <n>
 *   HEADER_INFO <face>          —— info face 原名(可用 --face 覆盖)
 *   COMMON_ATTRS <...>          —— common 行除 pages/scaleW/scaleH 外的字段
 *   PAGE <page> <dds_name>      —— 每页的 dds 文件名(基于 outprefix)
 *   CHAR <page> <unicode> <x> <y> <w> <h> <xoffset> <yoffset> <xadvance>
 *   ATLAS_END
 *
 * CLI:
 *   font_engine <fontfile> <px> [--outprefix <prefix>] [--face <name>]
 *              [--pad <n>] [--spacingx <n>] [--spacingy <n>] [--aa <n>]
 *              -- <unicode...>
 *
 * 依赖: libfreetype
 */
#include <ft2build.h>
#include FT_FREETYPE_H
#include FT_BITMAP_H
#include FT_MULTIPLE_MASTERS_H
#include FT_MODULE_ERRORS_H

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <math.h>

#include "dds_compress.h"

#include "dds_compress.h"

#define ATLAS_W 2048
#define ATLAS_H 4096
#define MAX_PAGES 8

typedef struct {
    uint8_t *pixels;      /* ATLAS_W*ATLAS_H*4 RGBA */
    int cur_x, cur_y, row_h, line_h;
} Page;

static Page pages[MAX_PAGES];
static int n_pages = 0;
static int pad = 1, spx = 1, spy = 1;

static Page* cur_page(void){ return &pages[n_pages-1]; }

static void page_new(int line_h) {
    if (n_pages >= MAX_PAGES) return;
    Page *p = &pages[n_pages++];
    p->pixels = (uint8_t*)calloc((size_t)ATLAS_W * ATLAS_H * 4, 1);
    p->cur_x = 0; p->cur_y = 0; p->row_h = 0; p->line_h = line_h;
}

static void pages_free(void){ for(int i=0;i<n_pages;i++) free(pages[i].pixels); n_pages=0; }

/* 放置字形到当前页；返回所在页码，-1 表示放不下。 */
static int page_place(FT_Bitmap *bm, int *out_x, int *out_y) {
    if (n_pages == 0) return -1;
    Page *p = cur_page();
    int gw = bm->width, gh = bm->rows;
    int req_w = gw + 2*pad, req_h = gh + 2*pad;
    if (req_w > ATLAS_W || req_h > ATLAS_H) return -2; /* 字形太大 */
    if (p->cur_x + req_w > ATLAS_W) {
        p->cur_x = 0;
        p->cur_y += (p->row_h > 0 ? p->row_h : req_h) + spy - 1;
        p->row_h = 0;
    }
    if (p->cur_y + req_h > ATLAS_H) return -1; /* 当前页满, 需开新页 */
    int px = p->cur_x + pad, py = p->cur_y + pad;
    if (bm->pixel_mode == FT_PIXEL_MODE_GRAY) {
        for (int y = 0; y < gh; y++)
            for (int x = 0; x < gw; x++) {
                uint8_t v = bm->buffer[y * bm->pitch + x];
                size_t idx = ((size_t)(py+y)*ATLAS_W + (px+x))*4;
                p->pixels[idx+0]=255; p->pixels[idx+1]=255; p->pixels[idx+2]=255;
                p->pixels[idx+3]=v;
            }
    } else if (bm->pixel_mode == FT_PIXEL_MODE_MONO) {
        for (int y = 0; y < gh; y++)
            for (int x = 0; x < gw; x++) {
                int on = (bm->buffer[y*bm->pitch + (x/8)] >> (7-(x%8))) & 1;
                size_t idx = ((size_t)(py+y)*ATLAS_W + (px+x))*4;
                p->pixels[idx+0]=255; p->pixels[idx+1]=255; p->pixels[idx+2]=255;
                p->pixels[idx+3]= on?255:0;
            }
    }
    if (p->row_h < req_h) p->row_h = req_h;
    p->cur_x += req_w + spx - 1;
    *out_x = px; *out_y = py;
    return n_pages-1;
}

/* 通用放置: 接受任意灰度 buffer(w x h)。根据是否有 padding 处理。 */
static int page_place_gray(const uint8_t *gray, int gw, int gh, int *out_x, int *out_y) {
    if (n_pages == 0) return -1;
    Page *p = cur_page();
    int req_w = gw + 2*pad, req_h = gh + 2*pad;
    if (req_w > ATLAS_W || req_h > ATLAS_H) return -2;
    if (p->cur_x + req_w > ATLAS_W) {
        p->cur_x = 0;
        p->cur_y += (p->row_h > 0 ? p->row_h : req_h) + spy - 1;
        p->row_h = 0;
    }
    if (p->cur_y + req_h > ATLAS_H) return -1;
    int px = p->cur_x + pad, py = p->cur_y + pad;
    for (int y=0; y<gh; y++)
        for (int x=0; x<gw; x++) {
            uint8_t v = gray[y*gw + x];
            size_t idx = ((size_t)(py+y)*ATLAS_W + (px+x))*4;
            p->pixels[idx+0]=255; p->pixels[idx+1]=255; p->pixels[idx+2]=255;
            p->pixels[idx+3]=v;
        }
    if (p->row_h < req_h) p->row_h = req_h;
    p->cur_x += req_w + spx - 1;
    *out_x = px; *out_y = py;
    return n_pages-1;
}

static int g_threads = 0;   /* 0 = 自动 */
static void write_pages_dds(const char *prefix) {
    for (int i=0;i<n_pages;i++) {
        char path[512];
        snprintf(path, sizeof(path), "%s_%d.dds", prefix, i);
        if (write_dxt5_dds_threaded(path, pages[i].pixels, ATLAS_W, ATLAS_H, g_threads) != 0)
            fprintf(stderr, "write_dds failed: %s\n", path);
        else
            fprintf(stderr, "wrote %s\n", path);
    }
}

/* 真超采样: 把一张高位图的灰度 bitmap 双线性缩放到目标尺寸。
   src(FT_Bitmap, gray) -> 输出到 dst(w x h, gray)。src 尺寸除以 scale 得目标。 */
static int downscale_gray(const FT_Bitmap *src, uint8_t **out, int *dw, int *dh, int scale) {
    if (!src || src->pixel_mode != FT_PIXEL_MODE_GRAY || scale < 1) {
        *out = NULL; *dw = src?src->width:0; *dh = src?src->rows:0;
        return 0;
    }
    int sw = src->width, sh = src->rows;
    int tw = (sw + scale - 1) / scale, th = (sh + scale - 1) / scale;
    if (tw < 1) tw = 1; if (th < 1) th = 1;
    uint8_t *o = (uint8_t*)malloc((size_t)tw * th);
    if (!o) { *out=NULL; *dw=tw; *dh=th; return 0; }
    for (int y=0; y<th; y++) {
        for (int x=0; x<tw; x++) {
            /* 目标像素 (x,y) 对应源区域 [x*scale..x*scale+scale, y*scale..y*scale+scale] 的平均 */
            int sx0 = x*scale, sy0 = y*scale;
            int sx1 = sx0 + scale, sy1 = sy0 + scale;
            if (sx1 > sw) sx1 = sw; if (sy1 > sh) sy1 = sh;
            unsigned sum=0, cnt=0;
            for (int sy=sy0; sy<sy1; sy++)
                for (int sxx=sx0; sxx<sx1; sxx++)
                    { sum += src->buffer[sy*src->pitch + sxx]; cnt++; }
            o[y*tw + x] = (uint8_t)(cnt? sum/cnt : 0);
        }
    }
    *out = o; *dw = tw; *dh = th;
    return 1;
}

/* 动态字符数组 */
typedef struct {
    unsigned long *data;
    size_t len, cap;
} CharVec;
static void cv_push(CharVec *v, unsigned long c) {
    if (v->len == v->cap) { v->cap = v->cap? v->cap*2 : 1024; v->data = (unsigned long*)realloc(v->data, v->cap*sizeof(unsigned long)); }
    v->data[v->len++] = c;
}
static void cv_free(CharVec *v){ free(v->data); v->data=NULL; v->len=v->cap=0; }

/* 从字符串 "0x4E00-0x9FFF" 或 "0x91D1" 解析，写入向量 */
static void parse_range(const char *tok, CharVec *v) {
    char buf[64]; strncpy(buf, tok, sizeof(buf)-1); buf[sizeof(buf)-1]=0;
    char *dash = strchr(buf, '-');
    if (dash) {
        *dash = 0;
        unsigned long lo = strtoul(buf, NULL, 0);
        unsigned long hi = strtoul(dash+1, NULL, 0);
        for (unsigned long c=lo; c<=hi; c++) cv_push(v, c);
    } else {
        cv_push(v, strtoul(buf, NULL, 0));
    }
}

/* 从字符集文件读取（每行一个 unicode/区间，# 注释，逗号或空白分隔） */
static void load_charsfile(const char *path, CharVec *v) {
    FILE *f = fopen(path, "r");
    if (!f) { fprintf(stderr, "charsfile open failed: %s\n", path); return; }
    char line[4096];
    while (fgets(line, sizeof(line), f)) {
        char *p = line;
        /* 去注释 */
        char *hash = strchr(p, '#'); if (hash) *hash = 0;
        /* 按逗号/空白分词 */
        char *tok = strtok(p, ", \t\r\n");
        while (tok) { parse_range(tok, v); tok = strtok(NULL, ", \t\r\n"); }
    }
    fclose(f);
    fprintf(stderr, "charsfile %s -> %zu chars\n", path, v->len);
}

int main(int argc, char **argv) {
    if (argc < 3) {
        fprintf(stderr, "usage: font_engine <fontfile> <px> [opts] -- <unicode...>\n");
        return 1;
    }
    const char *fontfile = argv[1];
    int px = atoi(argv[2]);
    int font_weight = -1;   /* 变字体字重(wght)，-1=默认 */
    const char *outprefix = "atlas";
    const char *face_name = NULL;
    int aa = 2;
    CharVec chars = {0};

    /* 解析可选参数 */
    int i = 3;
    for (; i < argc; i++) {
        if (!strcmp(argv[i], "--outprefix") && i+1 < argc) { outprefix = argv[++i]; }
        else if (!strcmp(argv[i], "--face") && i+1 < argc) { face_name = argv[++i]; }
        else if (!strcmp(argv[i], "--pad") && i+1 < argc) { pad = atoi(argv[++i]); }
        else if (!strcmp(argv[i], "--spacingx") && i+1 < argc) { spx = atoi(argv[++i]); }
        else if (!strcmp(argv[i], "--spacingy") && i+1 < argc) { spy = atoi(argv[++i]); }
        else if (!strcmp(argv[i], "--aa") && i+1 < argc) { aa = atoi(argv[++i]); }
        else if (!strcmp(argv[i], "--threads") && i+1 < argc) { g_threads = atoi(argv[++i]); }
        else if (!strcmp(argv[i], "--charsfile") && i+1 < argc) { load_charsfile(argv[++i], &chars); }
        else if (!strcmp(argv[i], "--weight") && i+1 < argc) { font_weight = atoi(argv[++i]); }
        else if (!strcmp(argv[i], "--char") && i+1 < argc) { parse_range(argv[++i], &chars); }
        else if (!strcmp(argv[i], "--")) { i++; break; }
        else break; /* 剩余的应为字符 */
    }
    /* -- 后的直接当成 unicode */
    for (; i < argc; i++) parse_range(argv[i], &chars);

    if (chars.len == 0) { fprintf(stderr, "no chars provided\n"); cv_free(&chars); return 1; }
    fprintf(stderr, "total chars to render: %zu\n", chars.len);

    FT_Library lib;
    if (FT_Init_FreeType(&lib) != 0) { fprintf(stderr, "FT_Init failed\n"); return 1; }
    FT_Face face;
    if (FT_New_Face(lib, fontfile, 0, &face) != 0) {
        fprintf(stderr, "FT_New_Face failed: %s\n", fontfile);
        return 1;
    }
    /* 若指定了变字体字重(wght>0)，设置可变轴坐标 */
    if (font_weight > 0) {
        FT_MM_Var *mm = NULL;
        if (FT_Get_MM_Var(face, &mm) == 0 && mm) {
            for (FT_UInt ai = 0; ai < mm->num_axis; ai++) {
                if (mm->axis[ai].tag == FT_MAKE_TAG('w','g','h','t')) {
                    FT_Fixed coords[4] = {0};
                    FT_Fixed wval = (FT_Fixed)(font_weight) * 65536;
                    for (FT_UInt k = 0; k < mm->num_axis; k++) coords[k] = mm->axis[k].def;
                    coords[ai] = wval;
                    FT_Set_Var_Design_Coordinates(face, mm->num_axis, coords);
                    break;
                }
            }
            FT_Done_MM_Var(lib, mm);
        }
    }
    /* 超采样: 先按 aa*px 渲染再缩小。这里用 FT_Set_Pixel_Sizes 直接按目标尺寸,
       超采样通过更高分辨率渲染 + 引擎侧缩放(简化为按 aa 倍渲染, 缩小交给FreeType 需 load scale)。
       为控制复杂度, 本版用 FT_LOAD_TARGET_NORMAL; 后续可加真超采样。 */
    FT_Set_Pixel_Sizes(face, 0, px);

    int line_h = face->size->metrics.height / 64;
    int base = face->size->metrics.ascender / 64;   /* 基线距行顶(BMFont 的 base) */
    page_new(line_h);

    /* 输出头 */
    printf("ATLAS_W %d ATLAS_H %d\n", ATLAS_W, ATLAS_H);
    printf("LINE_H %d\n", line_h);
    printf("BASE %d\n", base);
    const char *fn = face_name ? face_name : outprefix;
    printf("FACE %s\n", fn);

    int written = 0;
    for (size_t ci = 0; ci < chars.len; ci++) {
        unsigned long uc = chars.data[ci];
        FT_UInt gid = FT_Get_Char_Index(face, uc);
        if (gid == 0) { printf("CHAR 0x%lx MISSING\n", uc); continue; }

        /* 真超采样: aa>1 时按 aa 倍高渲染再缩到目标；否则普通渲染 */
        int used_aa = (aa > 1) ? aa : 1;
        if (FT_Set_Pixel_Sizes(face, 0, px * used_aa) != 0) { printf("CHAR 0x%lx SETSIZEERR\n", uc); continue; }
        if (FT_Load_Glyph(face, gid, FT_LOAD_RENDER | FT_LOAD_TARGET_NORMAL) != 0) {
            printf("CHAR 0x%lx LOADERR\n", uc); continue;
        }
        FT_GlyphSlot slot = face->glyph;

        int ox, oy;
        if (used_aa > 1 && slot->bitmap.pixel_mode == FT_PIXEL_MODE_GRAY) {
            /* 超采样: 把高位图缩小到目标 */
            uint8_t *small = NULL; int sw, sh;
            if (downscale_gray(&slot->bitmap, &small, &sw, &sh, used_aa)) {
                int pg = page_place_gray(small, sw, sh, &ox, &oy);
                if (pg == -1) { page_new(line_h); pg = page_place_gray(small, sw, sh, &ox, &oy); }
                if (pg == -1) { free(small); printf("CHAR 0x%lx OVERSIZE\n", uc); continue; }
                int adv = (int)((int64_t)slot->advance.x / used_aa / 64);
                int bsx = (int)((int64_t)slot->bitmap_left / used_aa);
                /* yoffset = base - bitmap_top：字形顶部到行顶的距离(引擎公式 top=yoffset)。
                   与官方 cg_16b 约定一致(汉字 yoff≈0, 顶部对齐)。 */
                int bsy = base - (int)((int64_t)slot->bitmap_top / used_aa);
                printf("CHAR %d 0x%lx %d %d %d %d %d %d %d\n",
                       pg, uc, ox, oy, sw, sh, bsx, bsy, adv);
                free(small);
                written++;
                continue;
            }
            free(small);
        }

        /* 普通渲染(aa=1 或非灰度) 走原路径 */
        int pg = page_place(&slot->bitmap, &ox, &oy);
        if (pg == -1) { page_new(line_h); pg = page_place(&slot->bitmap, &ox, &oy); }
        if (pg == -1) { printf("CHAR 0x%lx OVERSIZE\n", uc); continue; }
        int adv = slot->advance.x / 64;
        int bsx = slot->bitmap_left;
        /* yoffset = base - bitmap_top：字形顶部到行顶的距离(引擎公式 top=yoffset)。
           与官方 cg_16b 约定一致(汉字 yoff≈0, 顶部对齐)。 */
        int bsy = base - slot->bitmap_top;
        printf("CHAR %d 0x%lx %d %d %d %d %d %d %d\n",
               pg, uc, ox, oy, slot->bitmap.width, slot->bitmap.rows, bsx, bsy, adv);
        written++;
    }

    /* 若因放不下开了新页, 前面一些字符已经放好, 无需重排(顺序可接受) */
    printf("PAGES %d\n", n_pages);
    for (int p=0;p<n_pages;p++){
        char ddsname[512];
        snprintf(ddsname, sizeof(ddsname), "%s_%d.dds", outprefix, p);
        printf("PAGE %d %s\n", p, ddsname);
    }
    printf("ATLAS_END\n");

    write_pages_dds(outprefix);
    fprintf(stderr, "chars=%d pages=%d\n", written, n_pages);

    FT_Done_Face(face);
    FT_Done_FreeType(lib);
    pages_free();
    cv_free(&chars);
    return 0;
}
