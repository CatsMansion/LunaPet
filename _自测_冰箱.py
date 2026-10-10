# -*- coding: utf-8 -*-
"""_自测_冰箱.py —— 冰箱墙 / 冰箱顶落点 / 冰箱前站位，三项专测。

⭐ 为什么单独立一个文件：
  上一轮实机跑完整链路时抓到一个真 bug —— 从厨房台面(380)一路向右走，
  会穿过冰箱体落在 y=599, x=1218。根因：冰箱是新的落地实心体却**不在 PLATFORMS 里**，
  布墙判据扫不到它。修完还得确认三个方向都成立，不能只看"不穿模"这一项。
  ⛔ 全部走真实 Luna.update(dt, keys, room)，⛔ 不内联复刻逻辑。
"""
import os
import sys

# ⭐⭐⭐ 2026-10-10 Ronny 拍板：**冰箱也不要了**（FRIDGE_ENABLED=False）。
#   本文件**整份**都是冰箱专测（墙 / 顶落点 / 前站位）⇒ 冰箱不存在时全部无意义。
#   ⛔ 为什么不删文件：将来把冰箱加回来（把 FRIDGE_ENABLED 翻回 True），
#      这些判据就是现成的回归网，删了等于白写。
#   ⛔ 为什么不静默退出：静默退出 = 聚合脚本看到"没有失败字样"会**误判为通过**，
#      等于把 4 条判据从"红"变成"假绿"。
from pet_engine import night as _N
if not _N.FRIDGE_ENABLED:
    print("=" * 78)
    print("_自测_冰箱.py —— 已跳过：FRIDGE_ENABLED=False（2026-10-10 Ronny 拍板冰箱删除）")
    print("本文件整份是冰箱专测，冰箱不存在时无意义。")
    print("把 night.py 的 FRIDGE_ENABLED 翻回 True 可重新启用本文件的 4 条判据。")
    print("=" * 78)
    print("通过 0 / 0 （跳过，非通过）")
    sys.exit(0)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from pet_engine import night as N
from pet_engine.night import Luna, Room, Microwave

from PySide6.QtCore import Qt as _Qt

app = None
try:
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)
except Exception as e:            # pragma: no cover
    print("Qt 起不来：", e)

VW, VH = N.VW, N.VH
FLOOR_Y = N.FLOOR_Y
DT = 1.0 / 60.0
FX0 = float(N.FRIDGE["x"])
FX1 = float(N.FRIDGE["x"] + N.FRIDGE["w"])
FY_TOP = FLOOR_Y - N.FRIDGE["h"]

_LEFT = {_Qt.Key_A, _Qt.Key_Left}
_RIGHT = {_Qt.Key_D, _Qt.Key_Right}
_UP = {_Qt.Key_W, _Qt.Key_Up, _Qt.Key_Space}

fails = []


def mk_luna(x, y):
    room = type("R", (), {})()
    room.platforms = list(N.PLATFORMS)
    room.ladders = list(N.LADDERS)
    room.ladder_zones = list(N.LADDER_ZONES)
    l = Luna(x, y)
    l.vx, l.vy = 0.0, 0.0
    l.on_ground = True
    return l, room


def run(l, room, keys, frames):
    for _ in range(frames):
        l.update(DT, keys, room)
    return l


def check(name, ok, detail):
    print("  %s  %-34s %s" % ("✅" if ok else "⛔ FAIL", name, detail))
    if not ok:
        fails.append(name)


print("=" * 78)
print("冰箱 %d~%d  顶 y=%.0f  底 y=%.0f  高 %d"
      % (FX0, FX1, FY_TOP, FLOOR_Y, N.FRIDGE["h"]))
print("=" * 78)

print()
print("① 从厨房台面(380)一路向右走 —— 会不会飘进冰箱")
l, room = mk_luna(900.0, 380.0)
l.on_ground = True
hit_inside = 0
first = None
for i in range(90):
    l.update(DT, _RIGHT, room)
    if FX0 < l.x < FX1:
        hit_inside += 1
        if first is None:
            first = (i, l.x, l.y)
check("台面右走不进冰箱体", hit_inside == 0,
      "落点 x=%.1f y=%.1f  进体%d帧%s"
      % (l.x, l.y, hit_inside,
         ("  首次 @帧%d x=%.0f" % (first[0], first[1])) if first else ""))

print()
print("② 冰箱正前方能不能站住 + 触发 _at_fridge")
# _at_fridge 判据：x > FRIDGE.x-104 且 x < x+w+26 且 |y-地板|<6
probe_x = FX0 - 60.0
l, room = mk_luna(probe_x, FLOOR_Y)
l.on_ground = True
l = run(l, room, set(), 40)
cfg = N.NIGHTS[0]
room_real = Room(cfg)
room_real.luna = l
w = type("W", (), {})()
w.luna = l
at_fridge = getattr(N.NightWindow, "_at_fridge", None)
res = None
if at_fridge is not None:
    try:
        res = at_fridge(w)
    except Exception as e:
        res = "EXC:%s" % e
check("冰箱前站得住（不掉进 y<地板）",
      abs(l.y - FLOOR_Y) < 6.0, "x=%.1f y=%.1f 着地=%s" % (l.x, l.y, l.on_ground))
check("_at_fridge 在此位置为真", res is True, "x=%.1f y=%.1f → _at_fridge=%s"
      % (l.x, l.y, res))

print()
print("③ 冰箱顶能不能站住（从台面跳到顶 / 直接放顶上下落）")
# 3a 直接在冰箱顶上方 30px 松手
l, room = mk_luna((FX0 + FX1) / 2.0, FY_TOP - 30.0)
l.vx, l.vy = 0.0, 0.0
l.on_ground = False
l = run(l, room, set(), 45)
check("冰箱顶接住（y 停 %.0f）" % FY_TOP, abs(l.y - FY_TOP) < 2.0,
      "落点 x=%.1f y=%.1f 着地=%s" % (l.x, l.y, l.on_ground))

# 3b 站在冰箱顶左右走，不该掉进冰箱体里（顶是平台，边缘可以走出去自由落体）
l, room = mk_luna((FX0 + FX1) / 2.0, FY_TOP)
l.vx, l.vy = 0.0, 0.0
l.on_ground = True
l = run(l, room, _LEFT, 20)
left_edge_ok = l.x <= FX1 + 1.0
l2, room2 = mk_luna((FX0 + FX1) / 2.0, FY_TOP)
l2.vx, l2.vy = 0.0, 0.0
l2.on_ground = True
l2 = run(l2, room2, _RIGHT, 20)
check("冰箱顶可站且能从边缘走出", left_edge_ok and abs(l2.y - FY_TOP) < 2.0,
      "左走 x=%.1f y=%.1f / 右走 x=%.1f y=%.1f" % (l.x, l.y, l2.x, l2.y))

print()
print("④ 微波炉三档巡逻 600 帧（冰箱已计入实心）")
MW_H = 161.0
_solids = [(x0, x1, "台%d" % i) for i, (x0, y0, x1, y1) in enumerate(N.PLATFORMS)
           if y1 >= FLOOR_Y - 1 and i > 0]
_solids.append((FX0, FX1, "冰箱"))
for cfg in N.NIGHTS:
    rm = Room(cfg)
    rm.luna = type("S", (), {"x": 0.0, "y": FLOOR_Y})()
    mw = Microwave(cfg)
    inside = 0
    worst = None
    for i in range(600):
        mw._patrol(DT, rm.luna)
        for (x0, x1, nm) in _solids:
            if x0 < mw.x < x1:
                inside += 1
                if worst is None:
                    worst = (nm, mw.x, i)
    check("【%s】巡逻不进实心" % cfg["name"], inside == 0,
          "600 帧内 %d 帧%s"
          % (inside, ("  首次 %s x=%.0f @帧%d" % (worst[0], worst[1], worst[2]))
             if worst else ""))

print()
print("=" * 78)
if fails:
    print("⛔ %d 项未过：%s" % (len(fails), "、".join(fails)))
else:
    print("✅ 冰箱三项 + 顶平台 + 三档巡逻 全部通过")
print("=" * 78)
sys.exit(1 if fails else 0)
