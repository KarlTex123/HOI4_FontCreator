#ifndef DDS_COMPRESS_H
#define DDS_COMPRESS_H
#include <stdint.h>

/* 单线程 DXT5 写出（兼容旧接口） */
int write_dxt5_dds(const char *path, const uint8_t *rgba, int w, int h);
/* 多线程 DXT5 写出；threads<=0 表示自动使用 CPU 核心数 */
int write_dxt5_dds_threaded(const char *path, const uint8_t *rgba, int w, int h, int threads);

#endif
