# -*- coding: utf-8 -*-
"""⭐ 2026-09-28 新增：专门验证【UI 层】点击唤醒链路
   覆盖自测_睡眠没覆盖的路径：mousePress →（不移动）→ mouseRelease
   ⛔ 旧 bug：mousePress 就 begin_drag → asleep 被清 → on_click 唤醒分支失效
"""
import os, sys, time
sys.stdout.reconfigure(encoding="utf-8")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "pet_engine"))
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt, QPoint, QEvent
from PySide6.QtGui import QMouseEvent
from PySide6.QtCore import QPointF
import ui as U
from core import load_pack

app = QApplication.instance() or QApplication([])
pack = load_pack(os.path.join(HERE, "packs", "luna"))
w = U.PetWindow(pack)

P = F = 0
def ck(cond, msg):
    global P, F
    if cond: P += 1; print(f"  ✅ {msg}")
    else:    F += 1; print(f"  ⛔ {msg}")

def press_local(pt=None):
    pt = pt or QPoint(w.width()//2, w.height()//2)
    ev = QMouseEvent(QEvent.Type.MouseButtonPress, QPointF(pt),
                     QPointF(w.mapToGlobal(pt)), Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
    w.mousePressEvent(ev)
def release_local(pt=None):
    pt = pt or QPoint(w.width()//2, w.height()//2)
    ev = QMouseEvent(QEvent.Type.MouseButtonRelease, QPointF(pt),
                     QPointF(w.mapToGlobal(pt)), Qt.LeftButton, Qt.NoButton, Qt.NoModifier)
    w.mouseReleaseEvent(ev)
def move_local(pt):
    ev = QMouseEvent(QEvent.Type.MouseMove, QPointF(pt),
                     QPointF(w.mapToGlobal(pt)), Qt.NoButton, Qt.LeftButton, Qt.NoModifier)
    w.mouseMoveEvent(ev)

print("=== ① 睡着时【只按下不移动】→ 松手应走 sleep_out（不是瞬移 default）===")
w.pet.fall_asleep()
for _ in range(400):
    w.pet.step(0.05, w._cur_sil())          # 推进到 sleep_loop
ck(w.pet.asleep, f"先确认睡着了 state={w.pet.state}")
press_local()
ck(not w.pet.dragging, "按下后【没有】立即进入拖拽（旧 bug 就是这里进去了）")
ck(w.pet.state in ("sleep_in","sleep_loop"), f"按下后仍在睡眠状态 state={w.pet.state}")
release_local()
ck(w.pet.state == "sleep_out", f"松手后应播 sleep_out，实际 state={w.pet.state}")
ck(not w.pet.asleep, "asleep 已清")

print("\n=== ② 睡着时【真拖拽】→ 应进 drag，松手 fall ===")
w.pet.play("idle"); w.pet.fall_asleep()
for _ in range(400): w.pet.step(0.05, w._cur_sil())
ck(w.pet.asleep, f"又睡着了 state={w.pet.state}")
press_local()
move_local(QPoint(w.width()//2 + 40, w.height()//2))
ck(w.pet.dragging, "移动超阈值后进入拖拽")
ck(w.pet.state == "drag", f"state={w.pet.state}")
release_local()
ck(not w.pet.dragging, "松手后不再拖拽")
ck(w.pet.state == "fall", f"松手进入 fall，实际 {w.pet.state}")

print("\n=== ③ 没睡着时点击 → 摸摸（pat），不是叫醒 ===")
w.pet.play("idle"); w.pet.asleep = False
press_local(); release_local()
ck(w.pet.state == "pat", f"应播 pat，实际 {w.pet.state}")

print("\n=== ④ 光标靠近能吵醒（全局轮询）===")
# ⛔ 首跑教训：③ 里 press/release 用 mapToGlobal 喂了光标（就在她身上）→ 她"一入睡就被吵醒"
#    ——那其实证明唤醒逻辑是对的。这里先清光标模拟"鼠标不在旁边"，再分段验证。
w.pet.play("idle"); w.pet._cursor_x = None; w.pet.fall_asleep()
for _ in range(400): w.pet.step(0.05, w._cur_sil())
ck(w.pet.asleep, f"睡着了 state={w.pet.state}")
w._feed_cursor()            # 直接测轮询函数（离屏下 QCursor.pos() 取不到真实位置）
ck(w.pet._cursor_x is not None, f"光标已喂进去 _cursor_x={w.pet._cursor_x}")
# 分段 A：光标在 500px 外（超 wake_radius=120）→ 不该醒
w.pet.set_cursor(w.pet.body.x + 500)
w.pet._wake_from_cursor()
ck(w.pet.asleep and w.pet.state in ("sleep_in", "sleep_loop"), "光标在 500px 外 → 不醒（继续睡）")
# 分段 B：光标挪到 50px 内 → 应醒
w.pet.set_cursor(w.pet.body.x + 50)
w.pet._wake_from_cursor()
ck(w.pet.state == "sleep_out", f"光标靠近应吵醒 → sleep_out，实际 {w.pet.state}")

print(f"\n=== 结果：{P} 通过 / {F} 失败 ===")
sys.exit(1 if F else 0)
