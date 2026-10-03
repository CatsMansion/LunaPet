# -*- coding: utf-8 -*-
"""_自测_可玩性.py —— 这套关卡到底能不能通？QTE 机制有没有测试覆盖？

⭐ 为什么单独写这个：QTE / 冰箱 / 容器噪音 / 窝边结算 全是今天加的，
   但没有一个测试从"一局能不能打完"的角度看过。
   ⭐ 单位测试全绿 ≠ 玩得通（比如微波炉巡逻段可能覆盖不到某个容器）。
"""
import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
app = QApplication.instance() or QApplication([])
from pet_engine.core import load_pack
from pet_engine import night as N
import time as T

pack = load_pack(os.path.join(HERE, "packs", "luna"))
w = N.NightWindow(pack)
T.perf_counter = lambda: [0.0]
_clock = [0.0]
_orig = T.perf_counter
T.perf_counter = lambda: _clock[0]
OK = []
BAD = []


def chk(name, cond, info=""):
    (OK if cond else BAD).append(name)
    print("  %s  %s   %s" % ("OK  " if cond else "FAIL", name, info))


def step(n=1):
    for _ in range(n):
        _clock[0] += 1.0 / 60.0
        w._tick()


def play(night, sneak, use_fridge, verbose=False):
    """模拟一局：潜行靠近 → 敲容器/撬冰箱 → 回窝放下 → 按 E 结算。"""
    w.start_night(night)
    l, mw = w.luna, w.mw
    lo, hi = w.room.ladders[0][0] - 30, w.room.ladders[0][0] + 30
    w.keys = set()
    l.x, l.y = 260.0, N.FLOOR_Y
    l.vx = l.vy = 0.0
    l.on_ground, l.on_ladder = True, False
    step(6)

    # ---- 逐个来源：够得着的就去，够不着的记下来 ----
    got = []
    unreachable = []
    tried_fridge = False
    for rnd in range(24):
        if l.carrying:                       # 手上满了 → 回窝放下
            w.keys = {Qt.Key_Left}
            for _ in range(400):
                step(1)
                if l.x < N.NEST_X1 + 20:
                    break
            w.keys = set()
            step(8)
            continue
        # 选目标：先容器（够得着且不重叠），否则冰箱
        tgt = None
        for st in w.room.stashes:
            if st["broken"]:
                continue
            if abs(st["x"] - lo) < 1 or True:
                tgt = ("stash", st)
                break
        if tgt is None and w.room.fridge_left and use_fridge and not tried_fridge:
            tgt = ("fridge", None)
        if tgt is None:
            break
        kind, st = tgt
        gx = st["x"] if kind == "stash" else N.FRIDGE["x"] - 70.0
        gy = st["y"] if kind == "stash" else N.FLOOR_Y
        # 走过去（超时判定：走不到就是"够不着"）
        w.keys = {Qt.Key_Shift} | ({Qt.Key_D} if gx > l.x else {Qt.Key_A})
        for _ in range(500):
            step(1)
            if abs(l.x - gx) < 40 or abs(l.y - gy) < 60:
                break
        w.keys = set()
        if abs(l.x - gx) > 60 and kind == "stash":
            unreachable.append(st["icon"])
            st["broken"] = True if False else st["broken"]   # 标记但不算拿到
            break
        if kind == "fridge":
            tried_fridge = True
            if not w._at_fridge():
                unreachable.append("fridge")
                break
            w._try_break()
            if w.qte is None:
                break
            # ⭐ 模拟一个"手快的人"：按对全部
            for _ in range(int(1.0 * 4)):
                w._qte_step(w.qte["seq"][w.qte["got"]])
                step(1)
            if w.luna.carrying:
                got.append(w.luna.carrying[0])
            continue
        w._try_break()
        if l.carrying:
            got.append(l.carrying[0])
    # 最后回窝结算
    w.keys = {Qt.Key_Left}
    for _ in range(500):
        step(1)
        if l.x < N.NEST_X1 + 20:
            break
    w.keys = set()
    step(8)
    if w.loot_stash:
        w._try_break()
    return got, unreachable, (w.phase == "result"), w.result


print("=" * 72)

print()
print("=" * 72)
print("\u26d4 \u201c\u4e00\u5c40\u80fd\u4e0d\u80fd\u6253\u5b8c\u201d\u5df2\u79fb\u5230 _\u81ea\u6d4b_\u53ef\u8fbe\u6027.py")
print("   \uff08\u6a21\u62df\u73a9\u5bb6\u7248\u4f1a\u56e0\u4e3a\u4e0d\u4f1a\u722c\u68af/\u8df3\u800c\u62a5\u5047\u8b66\u62a5\uff0c\u5df2\u5220\uff09")
print("=" * 72)