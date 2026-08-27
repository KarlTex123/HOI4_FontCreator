# -*- coding: utf-8 -*-
"""
main.py —— 字体生成器入口（pywebview GUI + API 桥接）

启动 pywebview 窗口加载 gui/index.html，并暴露 Python API 供 JS 调用。
"""
from __future__ import annotations
import os, sys, json, threading, subprocess, tempfile, shutil, re

_HERE = os.path.dirname(os.path.abspath(__file__))
_TOOL = os.path.dirname(_HERE)   # tool/
# 打包模式(PyInstaller): 资源在 sys._MEIPASS; 否则用工具根目录
_APP_ROOT = sys._MEIPASS if (getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS")) else _TOOL
if not os.path.isdir(_APP_ROOT):
    _APP_ROOT = _TOOL
sys.path.insert(0, _HERE)
sys.path.insert(0, _TOOL)

import config, charset, size_calib, fontlib
import engine_runner as er
import preview as preview_mod

GUI = os.path.join(_APP_ROOT, "gui", "index.html")
if not os.path.isfile(GUI):
    GUI = os.path.join(_TOOL, "gui", "index.html")
# 运行目录: 打包后 exe 同目录; 否则工具根目录
_RUNTIME = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else _TOOL
CONFIG_DIR = os.path.join(_RUNTIME, "presets")
CONFIG_LIST_FILE = os.path.join(CONFIG_DIR, "configs.json")
# BMFont 默认配置文件(作为初始默认值来源; 存在才读)
BMFC = os.path.join(os.path.dirname(_TOOL), "font_config.bmfc")   # 上级目录
if not os.path.isfile(BMFC):
    BMFC = None

_current = None   # 当前配置 dict

DEFAULT_NAME = "默认配置"
_CURRENT_STATE_FILE = "_current_state.json"

def _ensure_dirs():
    os.makedirs(CONFIG_DIR, exist_ok=True)

def _cfg_path(name):
    return os.path.join(CONFIG_DIR, name + ".json")

def _load_cfg_list():
    """读取配置列表 [{name, protected}]。返回 list。"""
    _ensure_dirs()
    if not os.path.isfile(CONFIG_LIST_FILE):
        lst = [{"name": DEFAULT_NAME, "protected": True}]
        _write_cfg_list(lst)
        return lst
    try:
        with open(CONFIG_LIST_FILE, "r", encoding="utf-8") as f:
            lst = json.load(f)
    except Exception:
        lst = []
    if not isinstance(lst, list):
        lst = []
    # 确保默认配置始终存在且受保护
    if not any(x.get("name") == DEFAULT_NAME for x in lst):
        lst.insert(0, {"name": DEFAULT_NAME, "protected": True})
    for x in lst:
        if x.get("name") == DEFAULT_NAME:
            x["protected"] = True
    # 确保默认配置的值文件存在（其值 = 程序初始默认，来自 BMFC 或 reset_default）
    if not os.path.isfile(_cfg_path(DEFAULT_NAME)):
        _write_cfg_file(DEFAULT_NAME, config.validate(dict(_current))[0] if _current else config.reset_default())
    return lst

def _write_cfg_list(lst):
    _ensure_dirs()
    with open(CONFIG_LIST_FILE, "w", encoding="utf-8") as f:
        json.dump(lst, f, ensure_ascii=False, indent=2)

def _read_cfg_file(name):
    """读取具名配置文件为 dict；不存在返回 None。"""
    p = _cfg_path(name)
    if not os.path.isfile(p):
        return None
    return config.load_config(p)

def _write_cfg_file(name, cfg):
    config.save_config(_cfg_path(name), cfg)

class Api:
    def __init__(self):
        global _current
        # 启动时恢复上次关闭的当前配置；否则用默认
        _current = config.load_bmfc_defaults(BMFC) if BMFC else config.reset_default()
        self.auto_restore_current()
        self._last_out = None   # 最近一次生成的输出信息(供预览)

    # ---- 配置 ----
    def get_config(self):
        return _current

    def update_field(self, key, value):
        """由 JS 在用户修改某个字段时调用，保持 Python 配置同步。"""
        global _current
        if key in ("font_size", "display_size", "aa", "padding", "spacing_x", "spacing_y", "threads"):
            try:
                value = int(value)
            except (TypeError, ValueError):
                value = _current.get(key, 0)
        elif key in ("make_subfolder", "use_supersampling"):
            value = bool(value) if not isinstance(value, str) else (value in ("1","true","True","on","yes"))
        _current[key] = value
        return _current

    def reset_config(self):
        """回到默认配置值（不写入配置列表，仅作用于当前配置）。"""
        global _current
        _current = config.reset_default()
        return _current

    def config_list(self):
        """返回配置列表 [{name, protected, active}]。
        active 表示"当前配置与该保存配置一致"。"""
        lst = _load_cfg_list()
        for x in lst:
            try:
                c = _read_cfg_file(x["name"])
                x["active"] = bool(c) and config.configs_equal(c, _current)
            except Exception:
                x["active"] = False
        return lst

    def save_config_as(self, name):
        """以指定名称保存当前配置(新建/覆盖非默认)。"""
        global _current
        name = (name or "").strip()
        if not name:
            return {"ok": False, "msg": "配置名不能为空"}
        if name == DEFAULT_NAME:
            return {"ok": False, "msg": f"不能覆盖「{DEFAULT_NAME}」"}
        cfg, errs = config.validate(dict(_current))
        if errs:
            return {"ok": False, "msg": "; ".join(errs)}
        lst = _load_cfg_list()
        if any(x["name"] == name and x.get("protected") for x in lst):
            return {"ok": False, "msg": f"配置「{name}」为受保护配置，不可覆盖"}
        _write_cfg_file(name, cfg)
        if not any(x["name"] == name for x in lst):
            lst.append({"name": name})
        _write_cfg_list(lst)
        return {"ok": True, "name": name, "list": self.config_list()}

    def save_config(self, name=None):
        """保存当前配置。name 省略时：若与某已有配置一致则报错，否则自动命名保存。"""
        if name:
            return self.save_config_as(name)
        lst = _load_cfg_list()
        cfg, errs = config.validate(dict(_current))
        if errs:
            return {"ok": False, "msg": "; ".join(errs)}
        # 查重：若当前配置与某保存配置一致 -> 报错
        for x in lst:
            c = _read_cfg_file(x["name"])
            if c and config.configs_equal(c, cfg):
                return {"ok": False, "msg": f"配置「{x['name']}」已存在", "name": x["name"]}
        newname = "配置%d" % (len([x for x in lst if not x.get('protected')]) + 1)
        return self.save_config_as(newname)

    def load_config(self, name):
        """应用某保存配置到当前。"""
        global _current
        c = _read_cfg_file(name)
        if c is None:
            return _current
        _current = config.load_config(_cfg_path(name))
        return _current

    def rename_config(self, old, new):
        """重命名一个配置(默认配置不可改)。"""
        global _current
        new = (new or "").strip()
        if old == DEFAULT_NAME:
            return {"ok": False, "msg": f"「{DEFAULT_NAME}」不可重命名"}
        if not new:
            return {"ok": False, "msg": "新名称不能为空"}
        if new == old:
            return {"ok": True, "name": new, "list": self.config_list()}
        lst = _load_cfg_list()
        if any(x["name"] == new for x in lst):
            return {"ok": False, "msg": f"配置「{new}」已存在"}
        if not any(x["name"] == old for x in lst):
            return {"ok": False, "msg": f"配置「{old}」不存在"}
        old_cfg = _read_cfg_file(old)
        if old_cfg is not None:
            _write_cfg_file(new, old_cfg)
            p = _cfg_path(old)
            if os.path.isfile(p):
                os.remove(p)
        for x in lst:
            if x["name"] == old:
                x["name"] = new
        _write_cfg_list(lst)
        return {"ok": True, "name": new, "list": self.config_list()}

    def delete_config(self, name):
        """删除一个配置(默认配置不可删)。"""
        if name == DEFAULT_NAME:
            return {"ok": False, "msg": f"「{DEFAULT_NAME}」不可删除"}
        lst = _load_cfg_list()
        lst = [x for x in lst if x["name"] != name]
        _write_cfg_list(lst)
        p = _cfg_path(name)
        if os.path.isfile(p):
            os.remove(p)
        return {"ok": True, "name": name, "list": self.config_list()}

    def import_config(self):
        """通过文件对话框导入配置(.json/.bmfc)，作为新的具名配置。"""
        import webview
        try:
            win = webview.windows[0]
            f = win.create_file_dialog(webview.OPEN_DIALOG,
                                       file_types=("配置文件 (*.json;*.bmfc)", "所有文件 (*.*)"))
            if not f:
                return {"ok": False, "msg": "未选择"}
            path = f[0] if isinstance(f, (list, tuple)) else f
            c = config.load_bmfc_defaults(path) if path.lower().endswith(".bmfc") else config.load_config(path)
            global _current
            _current = c
            base = os.path.splitext(os.path.basename(path))[0]
            lst = _load_cfg_list()
            newname = base
            i = 2
            while any(x["name"] == newname for x in lst):
                newname = f"{base} ({i})"; i += 1
            _write_cfg_file(newname, config.validate(dict(c))[0])
            lst.append({"name": newname})
            _write_cfg_list(lst)
            return {"ok": True, "msg": "已导入 " + os.path.basename(path), "cfg": _current, "name": newname}
        except Exception as e:
            return {"ok": False, "msg": str(e)}

    def export_config(self, names=None):
        """导出指定的一个或多个配置到文件。names 为 ['配置1','配置2']。
        仅一个配置时直接进入文件保存对话框；多个则要求用户选择目录。"""
        import webview
        try:
            win = webview.windows[0]
            if not names:
                return {"ok": False, "msg": "未选择要导出的配置"}
            # 单配置 -> 文件另存
            if len(names) == 1:
                f = win.create_file_dialog(webview.SAVE_DIALOG, file_types=("配置文件 (*.json)",))
                if not f:
                    return {"ok": False, "msg": "未选择保存位置"}
                p = f[0] if isinstance(f, (list, tuple)) else f
                c = _read_cfg_file(names[0])
                if c is None:
                    return {"ok": False, "msg": f"配置「{names[0]}」不存在"}
                if not p.lower().endswith(".json"):
                    p += ".json"
                config.save_config(p, c)
                return {"ok": True, "msg": "已导出 " + os.path.basename(p)}
            # 多配置 -> 选择目录，逐个导出
            d = win.create_file_dialog(webview.FOLDER_DIALOG)
            if not d:
                return {"ok": False, "msg": "未选择导出目录"}
            out = d[0] if isinstance(d, (list, tuple)) else d
            exported = []
            for nm in names:
                c = _read_cfg_file(nm)
                if c is not None:
                    p = os.path.join(out, nm + ".json")
                    config.save_config(p, c)
                    exported.append(nm + ".json")
            return {"ok": True, "msg": "已导出 " + str(len(exported)) + " 个配置", "exported": exported}
        except Exception as e:
            return {"ok": False, "msg": str(e)}

    def auto_save_current(self):
        """程序关闭时自动保存当前配置(不在配置列表新增项)。"""
        _ensure_dirs()
        config.save_config(os.path.join(CONFIG_DIR, _CURRENT_STATE_FILE), dict(_current))

    def auto_restore_current(self):
        """启动时恢复上次关闭时的当前配置。"""
        global _current
        p = os.path.join(CONFIG_DIR, _CURRENT_STATE_FILE)
        if os.path.isfile(p):
            _current = config.load_config(p)
        return _current

    def browse_out_dir(self):
        """打开目录选择框，返回选中的目录路径。"""
        import webview
        try:
            win = webview.windows[0]
            f = win.create_file_dialog(webview.FOLDER_DIALOG)
            if f:
                path = f[0] if isinstance(f, (list, tuple)) else f
                return {"ok": True, "path": path}
        except Exception as e:
            return {"ok": False, "msg": str(e)}
        return {"ok": False, "msg": "未选择"}

    # ---- 字体 ----
    def list_system_fonts(self):
        """返回结构化字体列表（含本地化显示名 + 搜索别名 + 文件路径 + 是否导入）。

        每个条目: {display, path, family, subfamily, is_imported, search_text}
        显示名跟随系统语言(中文系统显示中文名)，搜索可匹配中/英/注册/文件名。
        """
        entries = fontlib.scan_fonts()
        result = []
        seen = set()
        for e in entries:
            key = e.display.lower() + "|" + e.path.lower()
            if key in seen:
                continue
            seen.add(key)
            result.append({
                "display": e.display,
                "path": e.path,
                "family": e.family,
                "subfamily": e.subfamily,
                "weight": e.weight,
                "is_imported": e.is_imported,
                "search_text": e.search_text(),
            })
        # 追加用户导入的字体（若未在内置扫描里）
        for imp in getattr(self, "_imported", []):
            if not any(r["path"].lower() == imp["path"].lower() for r in result):
                result.append(imp)
        result.sort(key=lambda r: r["display"].lower())
        return result

    def _init_imported(self):
        if not hasattr(self, "_imported"):
            self._imported = []

    def pick_system_font(self, name):
        """按显示名（或路径）选中字体，写入 _current。"""
        self._init_imported()
        # 先在所有字体(含导入)里找匹配显示名
        entries = self.list_system_fonts()
        target = None
        for e in entries:
            if e["display"] == name:
                target = e; break
        if target is None:
            # 尝试按路径后缀匹配
            for e in entries:
                if os.path.basename(e["path"]).lower() == os.path.basename(name).lower():
                    target = e; break
        if target:
            _current["font_file"] = target["path"]
            _current["font_name"] = target["display"]
            w = target.get("weight")
            if w is not None:
                _current["font_weight"] = int(w)
            else:
                _current.pop("font_weight", None)
        return _current

    def import_font(self):
        """多选导入字体文件（占位，真实实现见 pick_font_dialog）。"""
        return self._import_fonts_impl()

    def _import_fonts_impl(self, paths=None):
        """导入字体文件到 _imported 列表，并返回导入结果。

        返回: {ok, added:[显示名], paths:[路径], dup:[重复的路径], used:[系统已存在仍导入的], cfg}
        """
        self._init_imported()
        if paths is None:
            # 用 pywebview 文件对话框多选
            import webview
            try:
                win = webview.windows[0]
                f = win.create_file_dialog(webview.OPEN_DIALOG,
                                           file_types=("字体文件 (*.otf;*.ttf;*.ttc)", "所有文件 (*.*)"),
                                           allow_multiple=True)
                if not f:
                    return {"ok": False, "msg": "未选择"}
                if isinstance(f, (list, tuple)):
                    paths = list(f)
                else:
                    paths = [f]
            except Exception as e:
                return {"ok": False, "msg": str(e)}
        if not paths:
            return {"ok": False, "msg": "无文件"}

        existing_paths = {i["path"].lower() for i in self._imported}
        seen_paths = set(existing_paths)   # 已导入 + 本次已加入
        added = []
        dup = []
        for p in paths:
            p = str(p)
            if not os.path.isfile(p):
                dup.append(os.path.basename(p))
                continue
            if p.lower() in seen_paths:
                dup.append(os.path.basename(p))
                continue
            seen_paths.add(p.lower())
            try:
                meta = fontlib._read_name_table(p)
            except Exception:
                meta = None
            if meta:
                family, subfamily, display, aliases = meta
            else:
                family, subfamily, display, aliases = os.path.splitext(os.path.basename(p))[0], "", os.path.splitext(os.path.basename(p))[0], [os.path.splitext(os.path.basename(p))[0]]
            from fontlib import FontEntry
            entry = FontEntry(p, display, family, subfamily, "", aliases, is_imported=True)
            added.append(entry)
            # 立即设为当前字体
            _current["font_file"] = p
            _current["font_name"] = display
        # 序列化存储
        serialized = []
        for e in added:
            serialized.append({
                "display": e.display, "path": e.path, "family": e.family,
                "subfamily": e.subfamily, "is_imported": True,
                "search_text": e.search_text(),
            })
        self._imported.extend(serialized)
        return {"ok": True,
                "added": [e.display for e in added],
                "paths": [e.path for e in added],
                "dup": dup,
                "cfg": _current}

    def remove_imported_font(self, path):
        """从已导入列表移除指定字体（按路径）。返回剩余导入列表。"""
        self._init_imported()
        self._imported = [i for i in self._imported if i["path"].lower() != path.lower()]
        return self._imported

    def pick_font_dialog(self):
        """导入字体文件对话框（多选，兼容旧 JS 调用）。返回导入结果。"""
        return self._import_fonts_impl()

    # ---- 字符集 ----
    def count_charset(self, preset, font_file=None):
        """返回字符数（含缺失）。full 用字体枚举，custom 解析自定义。
        完整档若给了 font_file 则返回字体实际字符数。前端据此显示。"""
        if preset == "full":
            if font_file and os.path.isfile(font_file):
                try:
                    return len(er.enumerate_font_chars(font_file))
                except Exception:
                    return 0
            return 0
        if preset == "custom":
            return 0
        cps = charset.preset_codepoints(preset)
        if not cps:
            return 0
        if font_file and os.path.isfile(font_file):
            try:
                avail = er.enumerate_font_chars(font_file)
                return len(cps) - charset.missing_count(preset, avail)
            except Exception:
                return 0
        return len(cps)

    def charset_info(self):
        """返回各档位信息 {name: {label, desc, expected_count, count}}。"""
        info = charset.charset_info()
        for name, d in info.items():
            if d["expected_count"] is None:
                d["count"] = None
            else:
                d["count"] = d["expected_count"]
        return info

    # ---- 字号校准 ----
    def calibrate_size(self, target_px):
        if not _current.get("font_file"):
            return target_px
        px, _ = size_calib.calibrate_size(_current["font_file"], target_px)
        return px

    # ---- 生成 ----
    def generate(self):
        """调用引擎生成字体，返回结果信息。"""
        # 收集配置
        cfg = config.validate(dict(_current))[0]
        font_file = cfg.get("font_file")
        if not font_file or not os.path.isfile(font_file):
            return {"ok": False, "msg": "未选择有效的字体文件"}
        # px = 实际字体大小(ppem)：把「字体大小」按字体 ink 比例校准，使不同字体视觉一致
        fs = cfg.get("font_size", 18)
        try:
            px, _ = size_calib.calibrate_size(font_file, fs)
        except Exception:
            px = fs
        preset = cfg.get("char_set_preset", "medium")
        cps = charset.preset_codepoints(preset)
        if preset == "full":
            # 完整档：枚举字体文件实际包含的全部字符
            if not os.path.isfile(font_file):
                return {"ok": False, "msg": "字体文件不存在"}
            cps = sorted(er.enumerate_font_chars(font_file))
        elif preset == "custom":
            cps = charset.parse_custom(cfg.get("custom_chars", ""))
        if not cps:
            return {"ok": False, "msg": "无字符"}

        out_dir = cfg.get("out_dir") or os.path.dirname(font_file)
        # 自定义字体名优先，否则用字体文件名
        prefix = (cfg.get("custom_name") or "").strip() or os.path.splitext(os.path.basename(font_file))[0]
        # 清洗文件名非法字符
        prefix = re.sub(r'[\\/:*?"<>|\s]+', '_', prefix)
        # 若开启"自动生成字体文件夹"，则输出到 <out_dir>/<prefix>/ 下
        if cfg.get("make_subfolder"):
            out_dir = os.path.join(out_dir, prefix)
        os.makedirs(out_dir, exist_ok=True)
        charsfile = os.path.join(tempfile.gettempdir(), "fg_chars.txt")
        er.build_charsfile(cps, charsfile)

        # 超采样开关：关闭时强制 aa=1（不做超采样）
        use_ss = bool(cfg.get("use_supersampling", True))
        aa_val = cfg.get("aa", 2) if use_ss else 1

        try:
            info, err = er.run_engine(
                font_file, px, prefix, prefix, charsfile,
                pad=cfg.get("padding", 1),
                spacingx=cfg.get("spacing_x", 1),
                spacingy=cfg.get("spacing_y", 1),
                aa=aa_val,
                threads=cfg.get("threads", 0),
                outdir=out_dir,
                weight=cfg.get("font_weight"))
        except Exception as e:
            return {"ok": False, "msg": str(e)}

        # 生成每页 .fnt
        pages = []
        # BMFont 风格：lineHeight≈字号(px)，base=FreeType ascender(保证基线正确/汉字下沉)
        line_height = px
        base = info.get("base") or px
        for pg in info["pages"]:
            stem = f"{prefix}_{pg}"
            fnt = er.generate_fnt_for_page(pg, info["glyphs"][pg], stem,
                                           line_height=line_height, base=base,
                                           atlas_w=info["atlas_w"], atlas_h=info["atlas_h"],
                                           face_fallback=prefix, pad=cfg.get("padding",1),
                                           font_size=px)
            path = os.path.join(out_dir, stem + ".fnt")
            with open(path, "w", encoding="utf-8", newline="") as f:
                f.write(fnt)
            pages.append(path)

        # 构建 .gfx 注册文本（字号 = 显示字号 display_size，非光栅化 px）
        font_local = cfg.get("font_name") or prefix
        if cfg.get("make_subfolder"):
            files = [f"\"gfx/font/{prefix}/{prefix}_{pg}\"" for pg in info["pages"]]
        else:
            files = [f"\"gfx/font/{prefix}_{pg}\"" for pg in info["pages"]]
        gfx = self._build_gfx_text(font_local, prefix, cfg.get("display_size", fs), files)

        # 计算缺失字符数(字体不包含的档位规定字符)
        missing = 0
        if preset not in ("full", "custom") and os.path.isfile(font_file):
            try:
                avail = er.enumerate_font_chars(font_file)
                missing = charset.missing_count(preset, avail)
            except Exception:
                missing = 0

        # 记录最近一次输出，供预览使用
        self._last_out = {"out_dir": out_dir, "prefix": prefix, "font_size": px}
        return {"ok": True, "pages": pages, "out_dir": out_dir, "chars": len(cps),
                "gfx": gfx, "font_name": prefix, "font_local": font_local,
                "missing": missing}

    def preview_font(self, text, color=None, background=None):
        """生成字体后，用真实产出的 .fnt/.dds 渲染一段文字的预览 PNG(1920x1080 逻辑画布)。

        text: 要预览的文本；自动换行。
        color: 文字颜色 (r,g,b,a)，默认黑(对应 .gfx color=0xff000000)。
        返回 {ok, png(base64), width, height, font_size}。
        png 为透明背景(仅字形着色)，白底由 GUI 外层舞台提供，缩放只变字。
        """
        if not getattr(self, "_last_out", None):
            return {"ok": False, "msg": "请先生成字体"}
        out_dir = self._last_out["out_dir"]
        prefix = self._last_out["prefix"]
        fp = preview_mod.load_font(out_dir, prefix)
        if fp is None:
            return {"ok": False, "msg": "找不到已生成的字体文件"}
        if color is None:
            color = (0, 0, 0, 255)   # .gfx 默认 color 0xff000000 = 黑
        png = preview_mod.render_png(fp, text or "", color=color, transparent=True)
        import base64 as _b64
        b64 = _b64.b64encode(png).decode("ascii")
        return {"ok": True, "png": b64, "width": preview_mod.CANVAS_W,
                "height": preview_mod.CANVAS_H,
                "font_size": self._last_out.get("font_size", 18)}

    def _build_gfx_text(self, font_local, prefix, size, files):
        """生成 .gfx 注册代码块。"""
        lines = []
        lines.append(f"#{font_local}{size}px")
        lines.append("bitmapfont = {")
        lines.append(f"\t\tname = \"{prefix}\"")
        lines.append("\t\tcolor = 0xff000000")
        lines.append("\t\tfontfiles = {")
        for f in files:
            lines.append(f"\t\t\t{f}")
        lines.append("\t\t}")
        lines.append("\t}")
        return "\n".join(lines)

def main():
    import webview
    api = Api()
    window = webview.create_window(
        "钢铁雄心4 字体生成器",
        GUI,
        js_api=api,
        width=1000, height=780,
        min_size=(860, 640))
    # 关闭窗口时自动保存当前配置(不新增列表项)
    window.events.closed += lambda: api.auto_save_current()
    webview.start()

if __name__ == "__main__":
    main()
