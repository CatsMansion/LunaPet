# -*- coding: utf-8 -*-
"""⭐ 端到端验证「点击互动」—— 合成真实鼠标事件，不是调函数

为什么必须这么测：
   之前四次都是"改完 core / ui 就报完成"，结果 ui 那层压根没接上 →
   **点她完全没反应**。从这一版起：合成真实的鼠标按下/抬起，看她有没有真的回应。
"""
import os, sys
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "pet_engine"))

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt, QPoint
from PySide6.QtTest import QTest

from ui import PetWindow
from core import load_pack


n_ok = 0
n_all = 0          # ⭐ 2026-09-28：分母不再写死。原来写死 /10 而实际有 11 项，
                   #    结果「11 / 10 项」+ exit(1) —— 全过反而报失败。


def check(label, cond, detail=""):
    global n_all
    n_all += 1
    print(f"  {'✅' if cond else '⛔'} {label}" + (f"   {detail}" if detail else ""))
    return bool(cond)


app = QApplication.instance() or QApplication(sys.argv)
pack = load_pack(os.path.join(os.path.dirname(os.path.abspath(__file__)), "packs", "luna"))
w = PetWindow(pack)

n_ok = 0
print("=== ⭐ 点击 = 摸摸（合成真实鼠标事件）===")
m0 = w.pet.mood
QTest.mousePress(w, Qt.LeftButton, Qt.NoModifier, QPoint(256, 420))
QTest.mouseRelease(w, Qt.LeftButton, Qt.NoModifier, QPoint(256, 420))
m1 = w.pet.mood
n_ok += check("好感度上升", m1 > m0, f"{m0:.0f} → {m1:.0f}")
n_ok += check("播了 pat 动作", w.pet.state == "pat", f"state={w.pet.state}")
n_ok += check("冒了爱心", len(w.pet._hearts) > 0, f"{len(w.pet._hearts)} 个")

print()
print("=== ⭐ 拖动 ≠ 点击（拉远再松手应算拖拽，不该加分）===")
m2 = w.pet.mood
w.timer.stop()                       # 停掉主循环，避免状态机继续跑影响判定
QTest.mousePress(w, Qt.LeftButton, Qt.NoModifier, QPoint(256, 420))
# ⛔ 2026-09-28 更新：原来这里直接 `w._moved = 80.0` 戳私有变量 —— 那是【旧实现】的判定依据。
#   今天的 ui.py 改成「真的移动超阈值才 begin_drag」（修"睡着点一下被瞬移"那个 bug），
#   松手时看的是 `_drag_started`（在 mouseMoveEvent 里置位），不再回看 _moved。
#   所以必须【真的发一个 move 事件】—— 这本来也正是本文件开头写的"合成真实鼠标事件，不是调函数"。
QTest.mouseMove(w, QPoint(336, 420))     # 真的移动 80px
QTest.mouseRelease(w, Qt.LeftButton, Qt.NoModifier, QPoint(336, 420))
n_ok += check("拖完不加好感度", w.pet.mood <= m2 + 0.01, f"{m2:.0f} → {w.pet.mood:.0f}")
n_ok += check("进入下落（说明当成拖拽处理了）", w.pet.state == "fall", f"state={w.pet.state}")

print()
print("=== ⭐ 目标导向：给个目标她会走过去 ===")
w.pet.mood = 90.0
w.pet.behaviour.seek_chance = 1.0     # ⭐ 固定住，避免随机导致测试偶发失败
w.pet.set_cursor(1500.0)
w.pet._pick_goal()
n_ok += check("好感度高 → 目标是「去找光标」", w.pet.goal == "seek", f"goal={w.pet.goal}")
x0 = w.pet.body.x
for _ in range(600):
    w.pet.step(1 / 60, (-256, 256, -512, 0))
n_ok += check("走到了目标附近", abs(1500.0 - w.pet.body.x) < 20.0,
              f"x {x0:.0f} → {w.pet.body.x:.0f}（目标 1500）")

print()
print("=== ⭐ 走路中被拿起 → 必须触发 fall（不能被目标导向走路顶掉）===")
w.pet.goal = None
w.pet.body.on_ground = True
w.pet.mood = 90.0
w.pet.behaviour.seek_chance = 1.0
w.pet.set_cursor(1600.0)
w.pet._pick_goal()                       # 让她进入"要走向某处"的状态
for _ in range(30):
    w.pet.step(1 / 60, (-256, 256, -512, 0))
n_ok += check("先进入走路（目标导向）", w.pet.state == "walk", f"state={w.pet.state} goal={w.pet.goal}")
w.pet.begin_drag(w.pet.body.x, w.pet.body.y)
n_ok += check("拿起后目标被清空", w.pet.goal is None, f"goal={w.pet.goal}")
w.pet.end_drag()
n_ok += check("松手触发 fall", w.pet.state == "fall", f"state={w.pet.state}")
for _ in range(150):
    w.pet.step(1 / 60, (-256, 256, -512, 0))
n_ok += check("落地后恢复到常态", w.pet.state in ("land", "idle", "walk"), f"state={w.pet.state}")

print(f"\n{'='*54}\n  通过 {n_ok} / {n_all} 项")
sys.exit(0 if n_ok == n_all else 1)
