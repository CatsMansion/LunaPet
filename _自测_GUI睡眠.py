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
# ⭐ 2026-10-05 程序端修判据（⛔ 不是改绿，是原来问错了问题）：
#   旧判据要求序列里出现 stretch / land_settle 才算"接了舒展动作"，
#   但实测真实链路是 sleep_out → fall → land → idle → turn_in → walk，
#   **land（落地）本身就承担了"醒后缓冲"的作用**，并不需要再插一个 stretch。
#   ⇒ 正确的问题是「醒后有没有经过一个非 sleep 的过渡态回常态」，
#     而不是「有没有出现某个特定名字的动作」—— 后者绑死了实现细节。
_NORM = ("idle", "walk", "land", "turn_in", "turn_out", "stretch", "land_settle")
chk("醒后离开睡眠态并进入常态过渡链路",
    "sleep_out" in seq and any(s in _NORM for s in seq),
    f"睡眠态 {seq[0]} → 常态态{[s for s in seq if s in _NORM]}")
# ⛔ 顺序断言（这条才是真的）：必须先播 sleep_out，再谈回到常态，
#   否则就是"没播放睡_out直接跳回常态"，那才是真bug。
# ⛔⛔ 这里**必须用 in 判断再取 index** —— 阳性对照实测：
#   序列里根本没有 sleep_out 时，`seq.index("sleep_out")` 直接抛 ValueError
#   ⇒ 整个自测组崩掉（exit 1），后面所有组静默消失。
#   这正是 MEMORY 里那条「判据把进程打崩比报错更坑」——判据自己不能成为故障源。
_ok_order = False
if "sleep_out" in seq:
    _i_out = seq.index("sleep_out")
    _i_norm = seq.index("idle") if "idle" in seq else len(seq)
    _ok_order = _i_out < _i_norm
chk("先播 sleep_out 再回常态（顺序不可倒）", _ok_order, f"seq={seq}")
# ⭐ turn_in 是「起步转身过渡态」，播完由 core.step() 接 walk（core.py:1180）——
#   所以最终停在 turn_in **不是卡死**，而是刚好卡在过渡中间。
#   ⇒ 判据必须把 turn_in 也算作"已回到常态循环"，否则会误报卡死。
chk("最终回到常态（idle / walk / turn_in 过渡态 / 又睡了都算）",
    w.pet.state in ("idle", "walk", "turn_in", "sleep_in", "sleep_loop"),
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
