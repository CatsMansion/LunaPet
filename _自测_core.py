# -*- coding: utf-8 -*-
"""无头自测：只测 core.py 的逻辑（状态机 / 物理 / 边界 / 步幅）

⭐ 为什么单独测：GUI 跑起来看不到内部状态，而今天踩的坑全在 core 层。
   ⭐ 这里逐条验证「今天学到的规矩」是否真的被引擎内建了。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "pet_engine"))
sys.stdout.reconfigure(encoding="utf-8")

import random
random.seed(0)   # ⭐ 固定种子：自测是"契约"，随机驱动的契约没有意义
                 #   （不加这行时，⑧ 的断言有约 1/4 概率误报，因为 walk_weight=0.6 是随机的）

from core import load_pack, Pet, Anim   # noqa: E402

PACK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "packs", "luna")
SCH = (0, 0, 1920, 1080)          # 假桌面
ok = 0


def check(label, cond, detail=""):
    global ok
    print(f"  {'✅' if cond else '⛔'} {label}" + (f"   {detail}" if detail else ""))
    if cond:
        ok += 1


print("=== ① 角色包加载 ===")
p = load_pack(PACK)
CORE = ["idle", "walk", "fall", "land", "drag", "pat"]   # ⭐ 核心 6 个（其余可选，如 sleep_in/out/land_settle）
check("核心 6 个动作都在", all(k in p.actions for k in CORE),
      f"共 {len(p.actions)} 个：{sorted(p.actions)}")
check("walk 有 cycle_frames", p.actions["walk"].cycle_frames == 28)
check("walk 有 stride_px", p.actions["walk"].stride_px == 154.0)

print("\n=== ② ⭐ 步幅推导（DyberPet 里只能手调 frame_move）===")
mv = p.actions["walk"].move_per_frame
check("每帧位移由 stride÷cycle 自动算出", abs(mv - 5.5) < 1e-6, f"{mv:.2f} px/帧")
spd = mv * p.actions["walk"].fps
check("走速 ≈ 68.75 px/s", abs(spd - 68.75) < 0.1, f"{spd:.2f} px/s")

print("\n=== ③ 循环序列（pingpong 不去重首尾）===")
check("idle(pingpong 22帧) 序列长 = 42", len(Anim(p.actions["idle"]).seq) == 42,
      f"{len(Anim(p.actions['idle']).seq)}")
check("walk(cycle 28帧) 序列长 = 28", len(Anim(p.actions["walk"]).seq) == 28)

print("\n=== ④ ⭐ 走路位移：一圈应正好走 stride_px ===")
pet = Pet(p, SCH)
pet.play("walk")
pet.facing_right = True
# ⭐ 起步有斜坡（turn_ease_tau），先热身到稳态再量 —— 契约是"稳态下一圈走多远"
for _ in range(150):
    pet.update(0.01)
x0 = pet.body.x
T = p.actions["walk"].cycle_frames / p.actions["walk"].fps     # 一圈秒数
steps = int(T / 0.01)
for _ in range(steps):
    pet.update(0.01)
moved = pet.body.x - x0
check(f"稳态下一圈走了 ≈ {moved:.1f}px（目标 154px）", abs(moved - 154) < 6,
      f"误差 {abs(moved-154)/154*100:.1f}%  → 这就是「不太空步」的保证")

print("\n=== ⑤ ⭐ 屏幕限位（按实际轮廓，不是窗口中心）===")
pet2 = Pet(p, SCH)
pet2.body.x = 10 ** 6                       # 推到远远出屏
pet2.body.clamp_to_screen(SCH, (-256, 256, -512, 0))
check("右边界被限住", pet2.body.x <= SCH[2], f"x={pet2.body.x}")
pet2.body.x = -10 ** 6
pet2.body.clamp_to_screen(SCH, (-256, 256, -512, 0))
check("左边界被限住", pet2.body.x >= SCH[0], f"x={pet2.body.x}")
pet2.body.y = 10 ** 6
pet2.body.clamp_to_screen(SCH, (-256, 256, -512, 0))
check("脚底贴到屏幕底", pet2.body.y == SCH[3], f"y={pet2.body.y}")

print("\n=== ⑥ 重力 / 下落 / 落地 ===")
pet3 = Pet(p, SCH)
pet3.body.on_ground = False
pet3.body.y = 200.0
pet3.play("fall")
for _ in range(200):
    pet3.step(1/60, (-256, 256, -512, 0))
check("下落会受重力加速并最终落地", pet3.body.on_ground and pet3.body.y == SCH[3],
      f"on_ground={pet3.body.on_ground} y={pet3.body.y}")

print("\n=== ⑦ ⭐ 拖拽倾斜（DyberPet 里主角色做不到）===")
pet4 = Pet(p, SCH)
pet4.begin_drag(500, 500)
for i in range(10):
    pet4.move_drag(500 + i * 20, 500)        # 往右拖
tilt_r = pet4.body.tilt
check("往右拖 → 产生倾角", abs(tilt_r) > 1, f"tilt={tilt_r:.1f}°")
check("倾角不超上限", abs(tilt_r) <= p.behaviour.drag_tilt_max + 1e-6,
      f"上限 {p.behaviour.drag_tilt_max}°")

print("\n=== ⑧ 状态机：拖拽 → 松手 → 下落 → 落地 ===")
pet4.end_drag()
check("松手后进入 fall", pet4.state == "fall")
for _ in range(400):
    pet4.step(1/60, (-256, 256, -512, 0))
check("最终恢复到常态（idle / walk / land 都算恢复）",
      pet4.state in ("idle", "walk", "land"), f"state={pet4.state}")
check("已落地（on_ground）", pet4.body.on_ground, f"on_ground={pet4.body.on_ground}")

print(f"\n{'='*54}\n  通过 {ok} / 8 组检查")
