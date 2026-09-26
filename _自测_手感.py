# -*- coding: utf-8 -*-
"""量化「轻重」：模拟同一次拖拽，看三档预设的倾角行为

⭐ 手感是主观的，但"峰值角度 / 滞后时间 / 回正时间"是客观可测的。
   ⭐ 关键指标是【滞后】—— 重物的标志是"跟不上、要慢慢追"。
"""
import os, sys, math
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "pet_engine"))
sys.stdout.reconfigure(encoding="utf-8")
from core import load_pack, Pet

HERE = os.path.dirname(os.path.abspath(__file__))
SCH = (0, 0, 1920, 1080)
DT = 1/60

def run(preset: dict, label: str):
    p = load_pack(os.path.join(HERE, "packs", "luna"))
    for k, v in preset.items():
        setattr(p.behaviour, k, v)
    pet = Pet(p, SCH)
    pet.body.x, pet.body.y = 900, 600
    pet.begin_drag(900, 600)

    tilt_trace = []
    # 拖 0.6 秒：先加速到 1200px/s 再匀速（模拟真实甩动）
    x = 900.0
    for i in range(36):
        v = 1200.0 * min(1.0, i / 8)
        x += v * DT
        pet.move_drag(x, 600)          # move_drag → _update_drag_tilt
        pet._last_dt = DT
        pet.body.tilt += 0             # 已在上一步更新
        tilt_trace.append(pet.body.tilt)
    peak = max(tilt_trace, key=abs)
    t_peak = (tilt_trace.index(peak) + 1) * DT
    # 松手后回正
    pet.end_drag()
    t_settle = None
    # ⭐ 修 bug：松手后倾角还会因滞后继续长 → 基准要取"松手后见到的最大值"
    post_peak = abs(pet.body.tilt)
    for i in range(240):
        pet.step(DT, (-256, 256, -512, 0))
        post_peak = max(post_peak, abs(pet.body.tilt))
        if abs(pet.body.tilt) < post_peak * 0.1:
            t_settle = i * DT
            break
    print(f"  {label:<4} 峰值 {peak:>5.1f}°   到达峰值 {t_peak*1000:>4.0f}ms"
          f"   回正到 10% {('%.0fms' % (t_settle*1000)) if t_settle else '>4000ms'}")
    return abs(peak), t_peak, t_settle

print("=== ⭐ 三档手感（同一次拖拽：0→1200px/s 加速，匀速 0.6s，松手）===")
import json
cfg = json.load(open(os.path.join(HERE, "packs", "luna", "pet.json"), encoding="utf-8"))
for name, preset in cfg["behaviour"]["_预设"].items():
    run(preset, name)
print()
print("⭐ 判读：")
print("   · **到达峰值越晚 = 越重**（跟不上，要慢慢追）")
print("   · 峰值角度只是观感，**滞后才是重量感的来源**")
