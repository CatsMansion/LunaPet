# -*- coding: utf-8 -*-
"""自测：睡眠 → 叫醒 → 伸懒腰 状态机（纯逻辑，无 UI）

跑法：python _自测_睡眠.py
"""
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pet_engine.core import load_pack, Pet

HERE = os.path.dirname(os.path.abspath(__file__))
PACK = os.path.join(HERE, "packs", "luna")
SCREEN = (0, 0, 3840, 2160)
DT = 1 / 60

ok_n = bad_n = 0


def chk(name, cond, extra=""):
    global ok_n, bad_n
    if cond:
        ok_n += 1
        print(f"  ✅ {name}")
    else:
        bad_n += 1
        print(f"  ⛔ {name}  {extra}")


def frames_exist(pack):
    missing = []
    for name, a in pack.actions.items():
        for i in range(a.frames):
            p = pack.frame_path(name, i)
            if not os.path.exists(p):
                missing.append(f"{name}_{i}")
    return missing


print("=== ① 角色包完整性 ===")
pack = load_pack(PACK)
print(f"  动作：{' / '.join(pack.actions.keys())}")
chk("sleep_loop 已注册", "sleep_loop" in pack.actions)
chk("land_settle 已注册", "land_settle" in pack.actions)
miss = frames_exist(pack)
chk(f"所有帧文件存在（{sum(a.frames for a in pack.actions.values())} 张）", not miss,
    f"缺 {len(miss)} 张：{miss[:6]}")

print()
print("=== ② 入睡链路 idle → sleep_in → sleep_loop ===")
pack.behaviour.sleep_after = (0.30, 0.30)      # 加速测试
pet = Pet(pack, SCREEN)
seq = []
for i in range(int(6 / DT)):
    pet._last_dt = DT
    pet.step(DT, (0, 0, 0, 0))
    if not seq or seq[-1] != pet.state:
        seq.append(pet.state)
print(f"  状态序列：{' → '.join(seq)}")
chk("走完了 sleep_in → sleep_loop", "sleep_in" in seq and "sleep_loop" in seq)
chk("最后停在 sleep_loop", pet.state == "sleep_loop")
chk("asleep 标志为真", pet.asleep is True)

print()
print("=== ③ 叫醒链路 sleep_loop → sleep_out → 舒展 → idle ===")
# ⛔ 之后不再需要"快速入睡"，改成几乎不会睡着，否则 8 秒窗口里它又要睡回去
pack.behaviour.sleep_after = (600.0, 600.0)
pet._sleep_need = 600.0
pet.on_click()
seq2 = []
t = 0.0
while t < 8.0:
    pet._last_dt = DT
    pet.step(DT, (0, 0, 0, 0))
    if not seq2 or seq2[-1] != pet.state:
        seq2.append(pet.state)
    t += DT
print(f"  状态序列：{' → '.join(seq2)}")
# ⭐ 2026-09-29 修正断言：`stretch_chance` 是概率（默认 0.6），
#   sleep_out 播完【可以】直接进 idle —— 那是设计允许的，不是失败。
#   真正要守的契约是：① 必须先播 sleep_out；② 之后必须回到常态循环，且不出别的动作。
chk("起床链合法（sleep_out → [舒展] → idle/walk）",
    seq2[:1] == ["sleep_out"]
    and all(s in ("sleep_out", "stretch", "land_settle", "idle", "walk") for s in seq2)
    and pet.state in ("idle", "walk"), f"实际 {seq2}")
chk("回到了常态循环（idle/walk）", pet.state in ("idle", "walk"), f"实际 {pet.state}")
chk("asleep 已清", pet.asleep is False)
chk("原因已记录", pet.last_wake_reason == "click")

print()
print("=== ④ 光标靠近也会吵醒 ===")
pet2 = Pet(pack, SCREEN)
pet2.fall_asleep()
for _ in range(400):
    pet2.step(DT, (0, 0, 0, 0))
chk("先确认睡着了", pet2.state == "sleep_loop", pet2.state)
pet2.set_cursor(pet2.body.x + 50)          # 50 < wake_radius(120)
pet2.step(DT, (0, 0, 0, 0))
chk("光标进入半径 → 进入 sleep_out", pet2.state == "sleep_out", pet2.state)
chk("原因=cursor", pet2.last_wake_reason == "cursor")

print()
print("=== ⑤ 睡着时被拎起来 ===")
pet3 = Pet(pack, SCREEN)
pet3.fall_asleep()
for _ in range(400):
    pet3.step(DT, (0, 0, 0, 0))
pet3.begin_drag(100, 100)
# ⭐ 2026-09-29 修正断言：素材升级后"拎起来"拆成了两段 ——
#   drag_in（拿起过渡，一次性）→ drag（悬挂循环）。
#   begin_drag 之后立刻看到的是 drag_in，不是 drag。
chk("进入拖拽（drag_in 或 drag）", pet3.state in ("drag_in", "drag"), pet3.state)
chk("asleep 已清", pet3.asleep is False)
pet3.end_drag()
pet3.step(DT, (0, 0, 0, 0))
# ⭐ 同理：松手是 drag_out（松手过渡）→ fall，不是直接 fall。
chk("松手进入下落（drag_out 或 fall）", pet3.state in ("drag_out", "fall"), pet3.state)

print()
print("=== ⑥ 睡着时不该自己溜达 / 不该被 idle 计时切走 ===")
pet4 = Pet(pack, SCREEN)
pet4.fall_asleep()
for _ in range(60 * 12):
    pet4.step(DT, (0, 0, 0, 0))
chk("12 秒后仍在 sleep_loop（没被切走）", pet4.state == "sleep_loop", pet4.state)
chk("没有目标", pet4.goal is None, str(pet4.goal))

print()
print(f"=== 结果：{ok_n} 通过 / {bad_n} 失败 ===")
sys.exit(1 if bad_n else 0)
