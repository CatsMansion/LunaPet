# -*- coding: utf-8 -*-
"""pet_launcher.py —— 打包专用入口（⛔ run.py / core.py / ui.py 一个字都没改）

为什么另外开一个入口，而不是直接打包 run.py？
    run.py 里默认角色包写死为 `dirname(__file__)/packs/luna`。打包成 exe 后
    `__file__` 指向 PyInstaller 的内部解包目录，**表达不了**「exe 同目录有 packs
    就优先用它」这条需求。所以这里放一层很薄的路径决策，渲染与逻辑仍然原封不动
    地走 `ui.run()`。

角色包查找顺序（先命中先用）：
    ① 命令行参数     LunaPet.exe <角色包目录>
    ② exe 同目录     <exe目录>/packs/luna     ← ⭐ 外部覆盖，以后加角色不用重打包
    ③ exe 内部       <内置资源>/packs/luna    ← ⭐ 双击即用，不需要额外放文件
"""
from __future__ import annotations

import os
import sys

PACK_NAME = "luna"          # 默认角色包名（与 packs/ 下的目录名一致）


def _force_utf8_console() -> None:
    """⭐ 打包之后才暴露的两个坑，都在这里补掉：

    ① 编码：源码方式跑 `python run.py` 时 stdout 跟着终端走，通常是 UTF-8，中文日志没问题。
       但打成 exe 后，标准输出会退回**系统 ANSI 代码页**（英文区域设置下是 cp1252）。
       而 ui.py 里 `print("[轮廓] ...")` / `print("[引擎] 已启动：露娜")` 全是中文，
       一 print 就抛 UnicodeEncodeError —— 宠物还没显示出来进程就崩了。

    ② 缓冲：输出被重定向到管道/文件时，Python 默认是**块缓冲**（8KB 一刷）。
       那几行启动日志会一直憋在缓冲区里，别人拿 `exe > log.txt` 或 `timeout exe` 去验证
       就会误判成"什么都没输出"。开成行缓冲，一行一刷。

    ⛔ 只改输出编码与缓冲，不碰任何业务逻辑（core.py / ui.py / run.py 一个字没动）。
    """
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.kernel32.SetConsoleOutputCP(65001)   # 控制台切 UTF-8
        except Exception:
            pass
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
        except Exception:
            pass        # 无控制台时 sys.stdout 是 None，忽略即可


def _exe_dir() -> str:
    """exe 所在目录；源码方式运行时退化为项目根目录。"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def _inner_dir() -> str:
    """打包进 exe 的那份只读资源根目录。

    · onedir 打包：sys._MEIPASS 指向 exe 旁边的 `_internal/`
    · 源码运行   ：没有 _MEIPASS，回落成项目根目录
    """
    return getattr(sys, "_MEIPASS", _exe_dir())


def resolve_pack_dir() -> str:
    # ① 命令行显式指定（⭐ 先把开关参数摘掉，否则它会被当成角色包路径）
    args = [a for a in sys.argv[1:] if a not in ("--tuner", "--selftest-game")]
    if args and args[0].strip():
        return os.path.abspath(args[0])
    # ② exe 同目录的 packs/（外部覆盖优先）
    outer = os.path.join(_exe_dir(), "packs", PACK_NAME)
    if os.path.isdir(outer):
        return outer
    # ③ 打包进 exe 的那份
    return os.path.join(_inner_dir(), "packs", PACK_NAME)


def _tag(pack: str) -> str:
    inner = os.path.normcase(os.path.abspath(_inner_dir()))
    return "内置" if os.path.normcase(os.path.abspath(pack)).startswith(inner) else "外部覆盖"


def _selftest_game(pack: str) -> int:
    """⭐ 2026-10-03：验证**打包后的 exe 里**能不能真的 import 到 night 并画出小游戏窗口。

    ⛔ 为什么源码跑得通不算数：
       `night` 是在 ui_toolbar 的【函数内 try/except】里延迟 import 的，
       PyInstaller 的静态分析不保证扫到这种分支 → 漏了它的症状是
       「双击 exe、拉开抽屉、点游戏机、毫无反应」，而且只在 exe 上出现。
       交付前唯一能自动抓到它的机会就是这个自检口。

    ⭐ 必须真 render 一次而不是只 import：paintEvent 里的 NameError / 局部 import
       遮蔽这类错，只有真正画一次才会抛（QLinearGradient 那三次都是这么抓到的）。

    用法：LunaPet.exe --selftest-game      → 打印结果后退出，不起桌宠
    """
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QPixmap
    from core import load_pack
    import ui_toolbar                       # 工具箱本身也要能 import
    from night import NightWindow, NIGHTS, STASHES

    app = QApplication.instance() or QApplication([])
    pack_obj = load_pack(pack)
    w = NightWindow(pack_obj)

    pm = QPixmap(w.size())
    pm.fill()
    w.render(pm)                            # ⭐ 真画一次（菜单态）
    for i in range(len(NIGHTS)):            # 三档各画一次，且开一局让物理跑起来
        w.start_night(i)
        w.render(pm)
        w._tick()
    w.phase = "result"
    w.result = {"night": "x", "loot": 1, "left": 0, "total": 1, "caught": 0,
                "time": 1.0, "score": 150, "rank": "C"}
    w.phase_t = 0.5
    w.render(pm)

    print("[selftest] ui_toolbar 导入 OK")
    print("[selftest] night 导入 OK（函数内延迟 import → hiddenimports 命中）")
    print(f"[selftest] 档数 {len(NIGHTS)}　动作帧 {len(w.imgs)}　赃物图标 {len(w.icons)}"
          f"　（档二布局 {len(STASHES)} 处）")
    print(f"[selftest] 窗口 {w.width()}x{w.height()}　缩放 s={w.s:.4f}")
    print("[selftest] paintEvent 三档 + 菜单 + 结算 全通（无异常）")
    return 0


def main() -> int:
    _force_utf8_console()   # ⭐ 必须在任何中文 print / UI 起来之前调用

    # ui.py 内部是 `from core import ...`，所以 pet_engine 必须在 sys.path 上。
    # 打包后 core/ui 已是内置模块，这一行只是为了让源码运行方式也能用同一个入口。
    sys.path.insert(0, os.path.join(_inner_dir(), "pet_engine"))

    pack = resolve_pack_dir()
    if not os.path.isdir(pack):
        print(f"⛔ 角色包不存在：{pack}")
        return 1

    if "--selftest-game" in sys.argv:
        return _selftest_game(pack)

    from ui import run       # noqa: E402  （故意延后导入：先把路径准备好）

    tuner = "--tuner" in sys.argv      # ⭐ 调试台（成品默认不开，自己调手感时用）
    print(f"[打包] 角色包来源：{_tag(pack)}  →  {pack}")
    if tuner:
        print("[调试台] 已开启 —— 滑杆实时生效，可存/取预设，可 A/B 对比")
    return run(pack, tuner=tuner)


if __name__ == "__main__":
    sys.exit(main())
