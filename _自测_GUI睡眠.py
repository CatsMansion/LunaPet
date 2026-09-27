# -*- coding: utf-8 -*-
"""GUI 冒烟自测：离屏起真窗口 + 调试台，用 QTest 点新按钮（⛔ 不能只靠"能启动"）

跑法：python _自测_GUI睡眠.py
"""
import os
import sys

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "pet_engine"))
sys.path.insert(0, HERE)

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer, Qt
from PySide6.QtTest import QTest

from core import load_pack
from ui import PetWindow
from console import open_tuner

ok = bad = 0


def chk(n, c, extra=""):
    global ok, bad
    if c:
        ok += 1
        print(f"  ✅ {n}")
    else:
        bad += 1
        print(f"  ⛔ {n}  {extra}")


app = QApplication(sys.argv)
pack = load_pack(os.path.join(HERE, "packs", "luna"))
w = PetWindow(pack)
w.show()
tw = open_tuner(w)
tw.show()
print("=== 窗口与调试台已建（离屏）===")
chk("调试台有「让她睡」按钮", hasattr(tw, "do_sleep"))
chk("调试台有「叫醒」按钮", hasattr(tw, "do_wake"))
chk("调试台有睡眠状态标签", hasattr(tw, "sleep_lbl"))

# 让窗口先跑几帧
for _ in range(10):
    app.processEvents()

print()
print("=== 点「😴 让她睡」 ===")
tw.do_sleep()
for _ in range(6):
    app.processEvents()
chk("点了之后进入入睡/睡着", w.pet.asleep or w.pet.state in ("sleep_in", "sleep_loop"),
    w.pet.state)

# 推进时间让它走完 sleep_in
import time
t0 = time.time()
while time.time() - t0 < 4.0:
    app.processEvents()
    QTest.qWait(16)
print(f"  4 秒后状态：{w.pet.state}   asleep={w.pet.asleep}")
chk("走到 sleep_loop", w.pet.state == "sleep_loop", w.pet.state)
chk("睡眠标签有更新", "睡" in tw.sleep_lbl.text(), tw.sleep_lbl.text())

print()
print("=== 点「⏰ 叫醒」 ===")
tw.do_wake()
app.processEvents()
chk("进入 sleep_out", w.pet.state == "sleep_out", w.pet.state)
seq = [w.pet.state]
t0 = time.time()
while time.time() - t0 < 6.0:
    app.processEvents()
    QTest.qWait(16)
    if seq[-1] != w.pet.state:
        seq.append(w.pet.state)
print(f"  状态序列：{' → '.join(seq)}")
chk("起床后接了舒展动作", any(s in ("stretch", "land_settle") for s in seq), str(seq))
chk("最终回到 idle（或又睡了）", w.pet.state in ("idle", "walk", "sleep_in", "sleep_loop"),
    w.pet.state)

print()
print("=== 再点一次「叫醒」（她没在睡，应提示而不是崩） ===")
try:
    tw.do_wake()
    chk("没在睡时点叫醒不崩", True)
except Exception as e:
    chk("没在睡时点叫醒不崩", False, repr(e))

print()
print(f"=== 结果：{ok} 通过 / {bad} 失败 ===")
sys.exit(1 if bad else 0)
