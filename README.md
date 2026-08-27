# HOI4 字体生成器（HOI4 Font Creator）

> 一款专为《钢铁雄心4》（Hearts of Iron IV）打造的**位图字体一键生成工具**。
> 选好字体 → 点一下 → 直接产出游戏可用的 `.dds` + `.fnt` 文件，无需再拆页、无需碰 BMFont。

---

## ✨ 核心优势

### 1️⃣ 一键生成，零门槛
只需要选好字体（系统字体或导入 OTF/TTF），点一下【生成字体】，即可一次性生成钢4可直接读取的
**`.dds`（图集）+ `.fnt`（字体描述）** 文件。无需手动配置、无需二次拆分。

### 2️⃣ 比 BMFont 快得多的多线程转换
底层是自写的 C 加速引擎（FreeType 光栅化 + 自研 DXT5 压缩），**支持多线程并行转换**，转换速度远超传统 BMFont，几万个字也能秒级完成。

### 3️⃣ 自动生成注册代码（.gfx），复制粘贴即用
生成完字体后，工具**自动为你生成 `.gfx` 注册代码**，一键复制粘贴即可在游戏里注册字体，省去手写 `bitmapfont` 的步骤。

### 4️⃣ 自适应视觉字号校准
不同字体在同一 px 下视觉大小不同（思源黑体字面大、鸿蒙黑体紧凑等）。工具自动测量字体字形比例并校准，让**不同字体在相同字号下视觉大小一致**。

### 5️⃣ 对齐官方视觉基准
字号、字体大小、实际字体大小三字段自动联动换算（字号 ×4/5 +1 → 字体大小，再按字体比例校准 → 实际光栅化 px），与钢4官方字体（如 `hoi_22typewriter`、`hoi_18`）的显示大小一致，不再出现"偏大/偏小"。

### 6️⃣ 直接产出钢4格式，无需拆页
生成的 `.fnt` 已按钢4格式输出（`info` / `common` / `char` 行与官方一致），自动分页，直接放进 `模组/gfx/font/` 即可用。

---

## 🎯 功能特性

- **字体来源**：读取系统已安装字体，或直接导入 `.otf/.ttf/.ttc` 字体文件
- **字符集档位**：
  - 少（约 7100 字）：GB2312 一级+二级汉字 + 英文 + 常用标点/符号
  - 中（约 15000 字）：GB2312 全部汉字 + 部分 CJK 扩展生僻字 + 英文 + 全部标点/符号
  - 完整：字体文件内全部字符（自动枚举）
  - 自定义：按 Unicode 码点区间手输
- **可变字体字重**：自动枚举变字体（Variable Font）的全部字重（如鸿蒙黑体 Thin/Bold/Black…），可按字重生成
- **超采样（Supersampling）**：可开启/关闭，渲染更平滑
- **文字预览**：生成后可直接预览 `.dds/.fnt` 的渲染效果，编辑文字即时更新、自动换行，按 1920×1080 游戏窗口基准显示
- **配置管理**：保存/加载/改名/删除多套配置，默认配置受保护，关闭自动保存、重开自动恢复

---

## 🚀 使用方法

### 绿色免安装版（推荐）
1. 双击 `package/字体生成器/字体生成器.exe` 运行。
2. 在【本机字体】里选一个字体（或点【导入字体】导入 OTF/TTF）。
3. 设置【字号】（唯一需要填的数值，字体大小/实际字体大小自动算出）。
4. 选【字符集档位】（默认"完整"）。
5. 点【生成字体】。
6. 复制下方自动生成的 `.gfx` 注册代码。

### 放进你的模组
把生成的 `xxx_0.dds`、`xxx_0.fnt` 等文件放到模组：

```
模组目录/gfx/font/<字体名前缀>/
```

在 `.gfx` 文件里注册（工具会自动生成这段代码）：

```txt
#字体名字号px
bitmapfont = {
    name = "你的字体前缀"
    color = 0xff000000
    fontfiles = {
        "gfx/font/你的字体前缀/你的字体前缀_0"
    }
}
```

然后在 gui 文件里引用：

```txt
font = "你的字体前缀"
```

---

## 🧠 技术架构

```
┌─────────────────┐      ┌──────────────────┐      ┌─────────────────────────┐
│  GUI（界面）      │──▶──│  Python 逻辑层      │──▶──│   C 引擎（光栅化+压缩）     │
│  pywebview/HTML │      │  main.py / config  │      │  font_engine.c / dds     │
│  index.html     │◀──┬──│  charset / fontlib │      │  FreeType + 自研DXT5     │
└─────────────────┘   │  └──────────────────┘      └─────────────────────────┘
                      │                                        │
                      └────────── 产出 .dds + .fnt ◀──────────┘
```

- **C 引擎（`engine/`）**：FreeType 光栅化 + 自写 DXT5（BC3）压缩，多线程并行，自动分页
- **Python 逻辑层（`python/`）**：配置管理、字符集档位、字号校准、字体发现、预览渲染、`.gfx` 生成
- **界面（`gui/`）**：基于 HTML/CSS/JS 的桌面界面，经 pywebview 承载

生成的 `.fnt` 与钢4官方读取格式一致（`info`/`common`/`char` 行、`base`/`yoffset` 语义对齐官方），字体通道为白字遮罩 + alpha，适用钢4位图字体渲染。

---

## 📁 目录结构

```
tool/
├─ build.py               # 绿色免安装打包脚本
├─ engine/                # C 引擎源码（FreeType + DXT5）
│  ├─ font_engine.c
│  ├─ dds_compress.c / .h
│  └─ Makefile
├─ gui/
│  └─ index.html          # 界面（HTML/CSS/JS）
├─ python/                # Python 逻辑层
│  ├─ main.py             # 核心后端
│  ├─ config.py           # 配置读写/默认值
│  ├─ charset.py          # 字符集档位
│  ├─ fontlib.py          # 字体发现与元数据
│  ├─ size_calib.py       # 字号自适应校准
│  ├─ engine_runner.py    # 调起 C 引擎
│  └─ preview.py          # 字体验证渲染
├─ presets/               # （运行时生成）配置存根
├─ LICENSE                # MIT License
└─ 施工计划.md
```

---

## 🛠 自行编译打包

需要：Python 3.10+、MinGW GCC、FreeType（静态库）。

```bash
# 1. 编译 C 引擎
cd engine
gcc -std=c99 -O2 -I<freetype/include> font_engine.c dds_compress.c -L<freetype/objs> -l:freetype.a -o font_engine.exe

# 2. 打包绿色文件夹
cd ..
python -X utf8 build.py
```

输出：`package/字体生成器/`（免安装绿色文件夹，含 `字体生成器.exe`、`engine/font_engine.exe`、`gui/`、`presets/`）。

---

## 📄 License

[MIT License](LICENSE) · Copyright (c) 2026 德克萨斯专员
