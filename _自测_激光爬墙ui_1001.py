# -*- coding: utf-8 -*-
"""定向自测：2026-10-01 激光爬墙/跳距改动（ui 侧）。

覆盖 Ronny 的两条要求：
  ① 「红点贴近墙但**不比 1.5 个人高**时**选择不爬墙**」
  ② 「横向起跳抓小红点的距离 **150px → 800px**」（含"只改 dx 无效"的澄清）

⭐ 用真实的 QCursor.setPos()（offscreen 也能设），只调 w._laser_tick(dt) —— 同 _dbg_激光笔.py v3 的做法。
"""
import os, sys
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QCursor

app = QApplication.instance() or QApplication(sys.argv)
from pet_engine.core import load_pack
from pet_engine.ui import PetWindow

PACK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "packs", "luna")
W, H = 3840.0, 2160.0
ok = 0
# ⛔ 2026-10-05 程序端补：原来只累加 ok，**失败项被静默丢弃**（详见同款 _自测_激光爬墙_1001.py）
BAD = []
def check(label, cond, detail=""):
    global ok
    print(f"  {'✅' if cond else '⛔'} {label}" + (f"   {detail}" if detail else ""))
    if cond:
        ok += 1
    else:
        BAD.append(label)

w = PetWindow(load_pack(PACK))
w.screen_rect = (0, 0, W, H)
w.pet.screen = w.screen_rect
w.pet.terrains = []
pet = w.pet
w.hold_tool("laser")
w._laser_on = True

DT = 1 / 60.0
GRABS = ("jump_excited", "jump", "tease")

def reset(x=1000.0):
    pet.body.x = x
    pet.body.y = H
    pet.body.on_ground = True
    pet.body.vx = 0.0
    pet.body.vy = 0.0
    pet.goal = None
    pet.dragging = False
    pet.asleep = False
    pet._wake_stage = 0
    pet._sleep_t = -1e9
    pet._laser_cool = 0.0
    pet.jumping = False
    pet.state = "idle"
    pet.play("idle")
    pet.state_timer = 1.2
    w._cur_action = None

sil = w._cur_sil()
char_h = abs(float(sil[2]))
print(f"当前动作轮廓 dtp={sil[2]} → 角色高 ≈ {char_h:.0f}px；1.5 倍 = {1.5*char_h:.0f}px")
print(f"她站屏幕底 y={H:.0f} → 头顶 y = {H + sil[2]:.0f}")
print(f"屏幕宽 {W:.0f}，贴边阈值 _laser_wall_edge=500 → 红点 x ≥ {W-500:.0f} 才算贴右边\n")

print("=== ① 红点贴边：高度决定爬不爬（Ronny：「不比 1.5 个人高就不爬墙」）===")
# 不贴边的低红点 → 无论多高都不该进 wall_mode
reset()
QCursor.setPos(1700, int(H - 300)); w._laser_tick(DT)
check("红点**不贴边**（x=1700）→ 不进墙模式", w._laser_wall_mode is False, f"wall_mode={w._laser_wall_mode}")

# 贴边 + 红点很低（就在她够得着的高度）→ 不爬墙
reset()
QCursor.setPos(3800, int(H - 200)); w._laser_tick(DT)
check("贴边 + 红点**很低**（y≈1960，远不到 1.5 身高）→ **不爬墙**",
      w._laser_wall_mode is False, f"wall_mode={w._laser_wall_mode}")

# 贴边 + 红点在头顶下方一点 → 仍不爬
reset()
QCursor.setPos(3800, int(H + sil[2] + 100)); w._laser_tick(DT)
check("贴边 + 红点只在**头顶下方 100px** → **不爬墙**",
      w._laser_wall_mode is False, f"wall_mode={w._laser_wall_mode}")

# 贴边 + 红点高出 1.5 身高的临界之下 → 不爬
reset()
_crit = H + sil[2] - 1.5 * char_h
QCursor.setPos(3800, int(_crit + 40)); w._laser_tick(DT)
check("贴边 + 高于头顶但**不足 1.5 身高**（临界+40）→ **不爬墙**",
      w._laser_wall_mode is False, f"wall_mode={w._laser_wall_mode}")

# 贴边 + 红点高出 1.5 身高 → 爬
reset()
QCursor.setPos(3800, int(_crit - 40)); w._laser_tick(DT)
check("贴边 + 高出头顶**超过 1.5 身高**（临界-40）→ **爬墙**",
      w._laser_wall_mode is True, f"wall_mode={w._laser_wall_mode}")

# 贴边 + 红点很高 → 爬
reset()
QCursor.setPos(3800, 200); w._laser_tick(DT)
check("贴边 + 红点**很高**（y=200）→ 爬墙", w._laser_wall_mode is True, f"wall_mode={w._laser_wall_mode}")

# 左墙同理
reset()
QCursor.setPos(120, 200); w._laser_tick(DT)
check("**左墙**贴边 + 红点很高 → 爬墙", w._laser_wall_mode is True, f"wall_mode={w._laser_wall_mode}")
reset()
QCursor.setPos(120, int(H - 200)); w._laser_tick(DT)
check("**左墙**贴边 + 红点很低 → 不爬墙", w._laser_wall_mode is False, f"wall_mode={w._laser_wall_mode}")

print("\n=== ② 横向起跳抓红点的距离 = 800px（150→800）===")
# near 半径 800：700px 外应起跳
reset(1000.0)
QCursor.setPos(1000 + 700, int(H - 300))
before = pet.state
w._laser_tick(DT)
check("红点在 **700px** 外 → **起跳抓**（旧半径 120 不会）",
      pet.state in GRABS, f"state={pet.state}")
_dx700 = pet.body.vx * (2.0 * ((pet.body.y and 0) or 0) + 1)  # 占位，下面单独测 vx

# 800px 边缘：刚好应起跳
reset(1000.0)
QCursor.setPos(1000 + 800, int(H - 300))
w._laser_tick(DT)
check("红点在 **800px** 外（临界）→ 起跳", pet.state in GRABS, f"state={pet.state}")

# 900px 外：不该起跳
reset(1000.0)
QCursor.setPos(1000 + 900, int(H - 300))
w._laser_tick(DT)
check("红点在 **900px** 外 → **不起跳**（仍走去追）",
      pet.state not in GRABS, f"state={pet.state}")

# 起跳的水平位移要真的朝红点、且量级正确
reset(1000.0)
pet.body.on_ground = True
QCursor.setPos(1000 + 760, int(H - 300))
w._laser_tick(DT)
if pet.state in GRABS:
    _t = 2.0 * (2.0 * abs(pet.body.vy) / pet.behaviour.gravity) if getattr(pet.body, "vy", 0) else 0
    _h = (pet.body.vy ** 2) / (2.0 * pet.behaviour.gravity)
    _tf = 2.0 * (2.0 * _h / pet.behaviour.gravity) ** 0.5
    _reach = abs(pet.body.vx) * _tf
    check("起跳水平位移 ≈ 760px（朝红点）", abs(_reach - 760) < 30,
          f"vx={pet.body.vx:.0f} 飞行={_tf:.2f}s → 横移 {_reach:.0f}px")
    check("垂直初速度向上（vy<0）", pet.body.vy < 0, f"vy={pet.body.vy:.0f}")
else:
    check("应处于起跳状态", False, f"state={pet.state}")

print("\n=== ③ 贴边但不高 → 仍能正常跳抓（不被墙模式吃掉）===")
reset(3100.0)
QCursor.setPos(3600, int(H - 200))       # 贴边(x≥3340) 但很低 → 不进墙模式
w._laser_tick(DT)
check("贴边+低红点 → 走普通抓取路径（能起跳，未被墙模式截走）",
      pet.state in GRABS or getattr(pet, "goal", None) == "seek",
      f"wall_mode={w._laser_wall_mode} state={pet.state} goal={pet.goal}")

print("\n" + "=" * 56)
print(f"通过 {ok} / {ok + len(BAD)}")
if BAD:
    print("⛔ %d 项未过：%s" % (len(BAD), "、".join(BAD)))
print("=" * 56)
import sys as _sys
_sys.exit(1 if BAD else 0)
