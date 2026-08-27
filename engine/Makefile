# font_engine Makefile (MinGW)
# 用法: mingw32-make -f Makefile

CC := C:/AAA-Study/mingw64/bin/gcc.exe
FT_ROOT := C:/虚拟桌面/Game/钢铁雄心/工具/字体/tool/_downloads/freetype
FT_INC := $(FT_ROOT)/include
FT_LIB := $(FT_ROOT)/objs

CFLAGS := -std=c99 -O2 -Wall -I"$(FT_INC)"
LDFLAGS := -L"$(FT_LIB)" -lfreetype

font_engine.exe: font_engine.c
	$(CC) $(CFLAGS) font_engine.c $(LDFLAGS) -o font_engine.exe

clean:
	rm -f font_engine.exe
