# -*- coding: utf-8 -*-
"""定向自测：2026-10-01 激光爬墙改动（core 侧）。

覆盖 Ronny 的两条要求：
  ② 爬墙不必到顶 —— 可以爬到「头与红点等高」就跳
  ③ 红点不高时（≤1.5 个人高）不爬墙 —— 这条在 ui 侧，本文件只测 core 收到的结果

core 侧唯一改动：`_terrain_climb()` 里 `_climb_top` 的取值。
"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "pet_engine"))
sys.stdout.reconfigure(encoding="utf-8")
import random
random.seed(0)
from core import load_pack, Pet

PACK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "packs", "luna")
SCR = (0, 0, 1920, 1080)
ok = 0
def check(label, cond, detail=""):
    global ok
    print(f"  {'✅' if cond else '⛔'} {label}" + (f"   {detail}" if detail else ""))
    if cond:
        ok += 1

p = load_pack(PACK)

def make(excited, dot_y, body_y=1000.0, top=700.0):
    """造一个"站在平台侧面、该爬"的场景，调一次 _terrain_climb，返回 _climb_top"""
    pet = Pet(p, SCR)
    pet.terrains = [{"label": "t", "x0": 1000.0, "y0": top, "x1": 1300.0, "y1": 1000.0}]
    pet.body.x = 1100.0
    pet.body.y = body_y
    pet.body.on_ground = True
    pet.state = "idle"
    pet.dragging = False
    pet._sil = (-100, 100, -400, 0)      # dtp=-400 → 身高 400
    pet.set_excited(excited)
    if dot_y is None:
        pet._laser_pos_y = None
    else:
        pet._laser_pos_y = dot_y
    got = pet._terrain_climb(0.016)
    return got, getattr(pet, "_climb_top", None), pet

print("=== 场景：站在平台顶(700)下方 body.y=1000，身高 400（dtp=-400）===")
print("    身高 = |dtp| = 400 → 头顶在 body.y-400；『头顶与红点等高』时 body.y = dot_y + 400\n")

print("① 兴奋态 + 红点在高处（dot_y=400）→ 头顶等高点是 800 > 平台顶 700")
got, stop, _ = make(True, 400.0)
check("开始爬", got is True)
check("⭐ 爬升终点 = 800（不是平台顶 700）→ 爬到与红点等高就停",
      stop == 800.0, f"_climb_top={stop}")

print("\n② 兴奋态 + 红点更高（dot_y=200）→ 等高点 600 已在平台顶之上 → 仍爬到顶")
got, stop, _ = make(True, 200.0)
check("开始爬", got is True)
check("爬升终点 = 700（平台顶，不能爬过头）", stop == 700.0, f"_climb_top={stop}")

print("\n③ 兴奋态 + 红点在她头顶之下（dot_y=800 → 等高点 1200 > 她现在 1000）→ 不据此提前停")
got, stop, _ = make(True, 800.0)
check("开始爬", got is True)
check("爬升终点 = 700（平台顶）", stop == 700.0, f"_climb_top={stop}")

print("\n④ ⛔ 非兴奋态（普通漫游爬平台）+ 红点在高处 → 不受红点影响，仍爬到顶")
got, stop, _ = make(False, 400.0)
check("开始爬", got is True)
check("爬升终点 = 700（平台顶）—— 旧行为不变", stop == 700.0, f"_climb_top={stop}")

print("\n⑤ 没有 _laser_pos_y（没有激光驱动）→ 仍爬到顶")
got, stop, _ = make(True, None)
check("开始爬", got is True)
check("爬升终点 = 700（平台顶）", stop == 700.0, f"_climb_top={stop}")

print("\n⑥ 爬升速度随之调整（60 下限保护）")
_, _, pet = make(True, 400.0)
check("climb_speed 合理（>0，与距离/1.33 同量级）", pet.climb_speed > 60.0,
      f"climb_speed={pet.climb_speed:.1f}（距离 200px ÷ 1.33 ≈ 150）")

print("\n⑦ excited 但 climb 素材没装机 → 不爬（旧保护不变）")
class _NoClimb:
    def __contains__(self, k): return k != "climb"
pet = Pet(p, SCR)
pet.terrains = [{"label": "t", "x0": 1000.0, "y0": 700.0, "x1": 1300.0, "y1": 1000.0}]
pet.body.x = 1100.0; pet.body.y = 1000.0; pet.body.on_ground = True
pet.state = "idle"; pet.dragging = False; pet._sil = (-100, 100, -400, 0)
pet.set_excited(True); pet._laser_pos_y = 400.0
_orig_has = pet._has
pet._has = lambda a: (a != "climb") and _orig_has(a)
check("没有 climb 素材 → 不进入爬（返回 False）", pet._terrain_climb(0.016) is False)

print("\n" + "=" * 54)
print(f"  通过 {ok} 组检查")
print("=" * 54)
