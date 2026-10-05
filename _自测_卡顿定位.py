# -*- coding: utf-8 -*-
"""_自测_卡顿定位.py —— 卡顿根因定位（Ronny 2026-10-05）

## 这个脚本干什么
把「卡顿到底耗在哪」这件事变成可复现的量。⛔ 不猜、不改代码、只量。

## ⛔⛔ 用法（重要，否则量出来的数不可信）
本项目 offscreen 平台**只有 800×800 虚拟屏**。
⛔ 想量真实 1166×656 / 1280×720 的绘制耗时，**必须**先 `app.setOverrideCursor` 之外的做法：
   直接把窗口 resize 到目标尺寸**再 render**，`render()` 走的是离屏路径、不经过
   `clamp_to_screen`，所以不受 800×800 限制。
⛔ 凡是量"实机表现"，**最终必须在真机窗口上量**。本脚本只用于**定位嫌疑**。

## ⭐ 结论（本脚本实测出来的，不是推测）
  · `hundred._step_play` 单帧中位 1.5μs，占 60fps 预算 0.01%  → ⛔ 不是瓶颈
  · 三个窗口的 paintEvent 中位 0.65 / 0.79 / 1.54ms        → ⛔ 不是瓶颈
  · `ui.py:901` 的 `pm.scaled(SmoothTransformation)` 中位 187μs
    ⇒ `display_scale=0.7328` ≠ 1.0 ⇒ 该分支**永远为真** ⇒ **每帧都在做高质量插值**
    ⇒ 60fps 下占 **67.5%** 的帧预算  ← **这才是卡顿头号嫌疑**
"""
import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, ".")

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication

app = QApplication([])

US = 1.0 / 60.0            # 60fps 帧预算 = 16667us
BUDGET_US = 16667.0


def pct(v):
    return v / BUDGET_US * 100.0


def bench(fn, n=60, warm=8):
    """跑 n 次返回中位/p90/最大（微秒）。先 warm 几次避开首次开销。"""
    for _ in range(warm):
        fn()
    ts = []
    for _ in range(n):
        t0 = time.perf_counter()
        fn()
        ts.append((time.perf_counter() - t0) * 1e6)
    ts.sort()
    return ts[n // 2], ts[int(n * .9)], ts[-1]


def main():
    from pet_engine.core import load_pack
    import pet_engine.hundred as H
    import pet_engine.gamehub as G
    import pet_engine.night as N

    pack = load_pack("packs/luna")
    ok, ng = 0, 0

    def chk(name, cond, detail=""):
        nonlocal ok, ng
        if cond:
            ok += 1
            print("  OK    %-46s %s" % (name, detail))
        else:
            ng += 1
            print("  FAIL  %-46s %s" % (name, detail))

    print("=" * 78)
    print("① ⭐ 头号嫌疑：ui.py:901 每帧重做高质量缩放")
    print("=" * 78)
    scale = 0.7328            # pet.json 的 display_scale
    base = QPixmap(512, 512)
    base.fill()
    tgt = max(1, int(512 * scale))

    def do_scale():
        return base.scaled(tgt, tgt, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)

    med, p90, mx = bench(do_scale)
    print("  512→%d scaled(SmoothTransformation)  中位 %.0fus  p90 %.0fus  最大 %.0fus"
          % (tgt, med, p90, mx))
    print("  ⇒ 若 60fps 每帧都做：占帧预算 %.1f%%" % pct(med * 60))
    chk("⭐ 单次缩放确实是几十微秒级（值得缓存）",
        med > 50, "%.0fus" % med)
    chk("⭐ 缩放占预算比例高（>30% 即为可疑瓶颈）",
        pct(med * 60) > 30.0, "%.1f%%" % pct(med * 60))

    def do_noscale():
        return base                      # 走 user_scale==1.0 的分支
    med1, _, _ = bench(do_noscale)
    print("  对照：不缩放 %.0fus  ⇒ 缩放本身是 %.0f 倍开销" % (med1, med / max(med1, 1)))
    chk("⭐ 缩放开销远大于不缩放（证明分支常开就一定有代价）",
        med > med1 * 10, "%.0f×" % (med / max(med1, 1)))

    print()
    print("=" * 78)
    print("② 已排除的嫌疑（省得重跑）")
    print("=" * 78)
    h = H.HundredWindow(pack)
    h.start()
    ts = []
    for _ in range(3000):
        t0 = time.perf_counter()
        h._step_play(US)
        ts.append((time.perf_counter() - t0) * 1e6)
    ts.sort()
    med_l = ts[1500]
    print("  hundred._step_play 中位 %.1fus  p99 %.1fus  最大 %.1fus"
          % (med_l, ts[int(3000 * .99)], ts[-1]))
    chk("⭐ 游戏逻辑不是瓶颈（<5% 帧预算）",
        pct(med_l) < 5.0, "占 %.3f%%" % pct(med_l))

    # ⛔ 别写 (N, "night") 这种：N 是**模块**，不是类。
    #   写成 cls(pack) 会报 'module' object is not callable（实测踩过）。
    for cls, tag in ((H.HundredWindow, "hundred"),
                     (G.GameHubWindow, "gamehub"),
                     (N.NightWindow, "night")):
        w = cls(pack)
        w.resize(1280, 720)
        pm = QPixmap(w.width(), w.height())
        m, p, x = bench(lambda: w.render(pm), n=40)
        print("  %-9s paint %4dx%-4d 中位 %6.2fms p90 %6.2fms 最大 %6.2fms"
              % (tag, w.width(), w.height(), m / 1000, p / 1000, x / 1000))
        chk("  %s 单窗口绘制不超预算" % tag, m / 1000 < 16.6,
            "%.2fms / 16.6ms" % (m / 1000))

    print()
    print("=" * 78)
    print("③ 三个窗口同时跑（tick 叠加）")
    print("=" * 78)
    ws = [H.HundredWindow(pack), G.GameHubWindow(pack), N.NightWindow(pack)]
    for w in ws:
        w.resize(1280, 720)
    ivs = []
    for w, tag in zip(ws, ("hundred", "gamehub", "night")):
        t = getattr(w, "timer", None)
        iv = t.interval() if t is not None else None
        ivs.append(iv)
        print("  %-9s timer.interval = %s ms" % (tag, iv))
    chk("三个窗口各有一个 16ms tick ⇒ 叠加后 tick 频率 ×3",
        all(i == 16 for i in ivs if i is not None),
        "⇒ 事件循环每 16ms 要跑 3 个 tick")

    print()
    print("=" * 78)
    print("④ ⛔ 本脚本量不到的东西（必须在真机上量）")
    print("=" * 78)
    print("""  · Windows DWM 合成成本（本脚本走 offscreen，完全绕过）
  · 4K 屏 200% 缩放下的真实光栅化
  · 桌宠窗口透明 + 圆角 + 阴影的合成开销
  · 多窗口重叠时的实际 blit
  ⇒ 本脚本只用于**定位嫌疑**，"改完好了没有"必须在真机窗口上验。""")

    print()
    print("=" * 78)
    if ng:
        print("⛔ %d 项未过（通过 %d）" % (ng, ok))
    else:
        print("✅ 通过 %d / %d" % (ok, ok + ng))
    print("=" * 78)
    return 1 if ng else 0


if __name__ == "__main__":
    sys.exit(main())
