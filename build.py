# -*- coding: utf-8 -*-
"""
build.py —— 绿色免安装打包脚本

用 PyInstaller 把 main.py 打成一个 exe，然后把 font_engine.exe、gui 资源、
FreeType(已静态链接进引擎, 无需外部dll) 一起组装进一个绿色文件夹。

用法:
    python build.py
输出:
    package/字体生成器/
        ├─ 字体生成器.exe
        ├─ engine/font_engine.exe
        ├─ gui/index.html
        ├─ presets/          (空, 运行时创建)
        └─ README.txt
"""
from __future__ import annotations
import os, sys, shutil, subprocess

_HERE = os.path.dirname(os.path.abspath(__file__))
_TOOL = _HERE
_GUI = os.path.join(_TOOL, "gui")
_ENGINE = os.path.join(_TOOL, "engine")
_PY = os.path.join(_TOOL, "python")
_MAIN = os.path.join(_PY, "main.py")

_OUT = os.path.join(_TOOL, "package")
_BUNDLE = os.path.join(_OUT, "字体生成器")

def clean(path):
    if os.path.isdir(path):
        shutil.rmtree(path, ignore_errors=True)
    elif os.path.isfile(path):
        os.remove(path)

def main():
    # 1. 清理旧产物
    clean(os.path.join(_TOOL, "build"))
    clean(os.path.join(_TOOL, "dist"))
    clean(_BUNDLE)

    # 2. PyInstaller 打包 python 为 onedir(绿色文件夹里放 exe+依赖库)
    print("==> PyInstaller 打包 main.py ...")
    cmd = [sys.executable, "-m", "PyInstaller",
           "--name", "字体生成器",
           "--onedir",
           "--windowed",              # 不弹控制台
           "--noconfirm",
           "--clean",
           "--distpath", os.path.join(_TOOL, "dist"),
           "--workpath", os.path.join(_TOOL, "build"),
           "--specpath", _TOOL,
           # 收集 gui 与 python 模块
           "--add-data", f"{_GUI};gui",
           "--add-data", f"{_PY};python",
           # 隐藏控制台
           "--onefile", "0",  # 占位忽略
           _MAIN]
    # 去掉占位
    cmd = [c for c in cmd if c != "--onefile" and c != "0"]
    print("   ", " ".join(cmd))
    subprocess.run(cmd, check=True)

    # PyInstaller onedir 生成 dist/字体生成器/
    exe_bundle = os.path.join(_TOOL, "dist", "字体生成器")
    print("==> 组装绿色文件夹 ...")
    clean(_BUNDLE)
    os.makedirs(_BUNDLE, exist_ok=True)
    shutil.copytree(exe_bundle, _BUNDLE, dirs_exist_ok=True)

    # 3. 放进引擎 exe
    eng_dir = os.path.join(_BUNDLE, "engine")
    os.makedirs(eng_dir, exist_ok=True)
    shutil.copy2(os.path.join(_ENGINE, "font_engine.exe"), eng_dir)

    # 4. 确保 gui 资源在打包里
    gui_dir = os.path.join(_BUNDLE, "gui")
    os.makedirs(gui_dir, exist_ok=True)
    shutil.copy2(os.path.join(_GUI, "index.html"), gui_dir)

    # 5. 空 presets 目录(运行时创建)
    os.makedirs(os.path.join(_BUNDLE, "presets"), exist_ok=True)

    # 6. README
    with open(os.path.join(_BUNDLE, "README.txt"), "w", encoding="utf-8") as f:
        f.write(
            "钢铁雄心4 字体生成器\n"
            "=================\n\n"
            "双击【字体生成器.exe】运行。\n\n"
            "说明:\n"
            "  - 选择系统字体或导入 OTF/TTF\n"
            "  - 选择视觉字号, 工具会自动校准到实际引擎字号\n"
            "  - 选择字符集档位(少/中/高/完整/自定义)\n"
            "  - 点击【生成字体】, 输出 xxx_0.dds + xxx_0.fnt 等\n"
            "  - .fnt 已按钢铁雄心4格式直接生成, 无需二次拆分\n\n"
            "生成好的字放到 模组/gfx/font/ 下, 并在 .gfx 里注册即可。\n"
        )
    print("==> 完成! 绿色文件夹:")
    print("   ", _BUNDLE)
    print("   (含 字体生成器.exe / engine/font_engine.exe / gui/ / presets/)")

if __name__ == "__main__":
    main()
