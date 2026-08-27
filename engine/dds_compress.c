/*
 * dds_compress.c —— DXT5 (BC3) 压缩器（M3，支持多线程并行）
 *
 * 输入: RGBA8 图集 (w x h)
 * 输出: DDS 文件 (DXT5, 带 alpha, 白色字形遮罩)
 *
 * 并行: 每 4x4 块独立，按「块行」分给多个线程，各线程写 buffer 的不同区间
 *       （块位置 = 行主序索引 * 16 字节），无共享写竞争。压缩完一次性写文件。
 */
#include <stdint.h>
#include <string.h>
#include <stdio.h>
#include <stdlib.h>
#ifdef _WIN32
#include <windows.h>
#endif

#define BC_BLOCK 4  /* 4x4 块 */

/* RGB565 打包 */
static uint16_t pack565(uint8_t r, uint8_t g, uint8_t b) {
    return (uint16_t)(((r>>3)<<11) | ((g>>2)<<5) | (b>>3));
}

/* 把一个 4x4 的 RGBA 块压缩成 16 字节 DXT5 块 */
static void dxt5_block(const uint8_t *src, uint8_t out[16]) {
    int i;
    uint8_t alph[16];
    for (i=0;i<16;i++) alph[i] = src[i*4+3];

    uint8_t a0=255, a1=0;
    for (i=0;i<16;i++){ if(alph[i]<a0)a0=alph[i]; if(alph[i]>a1)a1=alph[i]; }
    out[0]=a0; out[1]=a1;

    uint8_t alut[8];
    alut[0]=a0; alut[1]=a1;
    if (a0>a1) {
        for (i=0;i<6;i++) alut[2+i] = (uint8_t)((a0*(6-i) + a1*(i+1))/7);
    } else {
        for (i=0;i<4;i++) alut[2+i] = (uint8_t)((a0*(4-i) + a1*(i+1))/5);
        alut[6]=0; alut[7]=255;
    }
    uint64_t abits=0;
    for (i=0;i<16;i++){
        int best=0, bd=9999;
        for (int k=0;k<8;k++){ int d=alph[i]-alut[k]; if(d<0)d=-d; if(d<bd){bd=d;best=k;} }
        abits |= ((uint64_t)best) << (i*3);
    }
    for (i=0;i<6;i++) out[2+i] = (uint8_t)((abits >> (i*8)) & 0xFF);

    /* 颜色：白字遮罩 */
    uint16_t c0=pack565(255,255,255), c1=pack565(255,255,255);
    out[8]=(uint8_t)(c0&0xFF); out[9]=(uint8_t)(c0>>8);
    out[10]=(uint8_t)(c1&0xFF); out[11]=(uint8_t)(c1>>8);
    for (i=0;i<4;i++) out[12+i]=0;
}

/* 并行压缩工作线程的共享上下文 */
typedef struct {
    const uint8_t *rgba;
    uint8_t *outbuf;   /* bw*bh*16 */
    int w, h;
    int bw, bh;
    int by_start, by_end;  /* 负责的块行区间 [by_start, by_end) */
} ComCtx;

static void compress_rows(ComCtx *ctx) {
    const uint8_t *rgba = ctx->rgba;
    uint8_t *outbuf = ctx->outbuf;
    int w = ctx->w, bw = ctx->bw;
    for (int by = ctx->by_start; by < ctx->by_end; by++) {
        for (int bx = 0; bx < bw; bx++) {
            uint8_t px[64];
            int p = 0;
            for (int yy=0; yy<4; yy++)
                for (int xx=0; xx<4; xx++) {
                    int gx=bx*4+xx, gy=by*4+yy;
                    const uint8_t *s = rgba + ((size_t)gy*w + gx)*4;
                    px[p++]=s[0]; px[p++]=s[1]; px[p++]=s[2]; px[p++]=s[3];
                }
            uint8_t block[16];
            dxt5_block(px, block);
            /* 块位置: (by*bw + bx)*16 */
            memcpy(outbuf + ((size_t)(by*bw + bx))*16, block, 16);
        }
    }
}

#ifdef _WIN32
static DWORD WINAPI compress_thread(LPVOID arg) {
    compress_rows((ComCtx*)arg);
    return 0;
}
#endif

/* 把整张 RGBA 图集写为 DXT5 DDS。threads=0 表示用 CPU 核心数。 */
int write_dxt5_dds_threaded(const char *path, const uint8_t *rgba, int w, int h, int threads) {
    int bw = w/4, bh = h/4;
    size_t datasize = (size_t)bw * bh * 16;
    uint8_t *outbuf = (uint8_t*)malloc(datasize);
    if (!outbuf) return -1;

#ifdef _WIN32
    if (threads <= 0) {
        SYSTEM_INFO si; GetSystemInfo(&si); threads = (int)si.dwNumberOfProcessors;
    }
    if (threads > bh) threads = bh;
    if (threads < 1) threads = 1;

    ComCtx *ctxs = (ComCtx*)malloc(sizeof(ComCtx)*threads);
    HANDLE *handles = (HANDLE*)malloc(sizeof(HANDLE)*threads);
    int chunk = (bh + threads - 1) / threads;
    for (int t=0; t<threads; t++) {
        ctxs[t].rgba=rgba; ctxs[t].outbuf=outbuf; ctxs[t].w=w; ctxs[t].h=h;
        ctxs[t].bw=bw; ctxs[t].bh=bh;
        ctxs[t].by_start = t*chunk;
        ctxs[t].by_end = (t+1)*chunk;
        if (ctxs[t].by_end > bh) ctxs[t].by_end = bh;
        handles[t] = CreateThread(NULL, 0, compress_thread, &ctxs[t], 0, NULL);
    }
    WaitForMultipleObjects(threads, handles, TRUE, INFINITE);
    for (int t=0;t<threads;t++) CloseHandle(handles[t]);
    free(ctxs); free(handles);
#else
    /* 非 Windows 回退为串行 */
    ComCtx ctx = {rgba, outbuf, w, h, bw, bh, 0, bh};
    compress_rows(&ctx);
#endif

    FILE *f = fopen(path, "wb");
    if (!f) { free(outbuf); return -1; }
    uint8_t hdr[128]; memset(hdr,0,128);
    memcpy(hdr, "DDS ", 4);
    uint32_t dwSize=124; memcpy(hdr+4,&dwSize,4);
    uint32_t dwFlags=0x00021007; memcpy(hdr+8,&dwFlags,4);
    uint32_t dh=(uint32_t)h; memcpy(hdr+12,&dh,4);
    uint32_t dw=(uint32_t)w; memcpy(hdr+16,&dw,4);
    uint32_t pitch=(uint32_t)(bw*16); memcpy(hdr+20,&pitch,4);
    uint32_t pfSize=32; memcpy(hdr+76,&pfSize,4);
    uint32_t pfFlags=0x4; memcpy(hdr+80,&pfFlags,4);
    memcpy(hdr+84, "DXT5", 4);
    uint32_t caps1=0x1000; memcpy(hdr+108,&caps1,4);
    fwrite(hdr,128,1,f);
    fwrite(outbuf,1,datasize,f);
    fclose(f);
    free(outbuf);
    return 0;
}

/* 兼容旧接口：单线程 */
int write_dxt5_dds(const char *path, const uint8_t *rgba, int w, int h) {
    return write_dxt5_dds_threaded(path, rgba, w, h, 1);
}

