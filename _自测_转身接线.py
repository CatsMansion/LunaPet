# -*- coding: utf-8 -*-
"""⭐ 2026-09-28 转身接线自测：turn_in(起步转身) / turn_out(收工转回正面)
   素材事实：walk/turn_in尾/turn_out首 原生都朝右；turn_in #0-#8 为静止预备段(start=9 跳过)
"""
import os, sys, random
sys.stdout.reconfigure(encoding="utf-8")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "pet_engine"))
from PySide6.QtWidgets import QApplication
import ui as U
from core import load_pack

app = QApplication.instance() or QApplication([])
pack = load_pack(os.path.join(HERE, "packs", "luna"))
w = U.PetWindow(pack)
p = w.pet
P = F = 0
def ck(cond, msg):
    global P, F
    if cond: P += 1; print(f"  ✅ {msg}")
    else:    F += 1; print(f"  ⛔ {msg}")

# ① turn_in 的播放序列从 #9 开始（跳过静止预备段）
seq = pack.actions["turn_in"].sequence()
ck(seq[0] == 9, f"turn_in sequence 首帧 = {seq[0]}（应为 9，跳过预备段）")
ck(len(seq) == 9, f"turn_in 播放长度 = {len(seq)}（应为 9）")
ck(pack.actions["turn_out"].sequence()[0] == 0, "turn_out 全段播（首帧 0）")
ck(pack.actions["idle"].sequence()[0] == 0, "未配 start 的动作不受影响（idle 首帧 0）")

# ② idle 计时结束选走路 → 应先进 turn_in（不是直接 walk）
p.behaviour.walk_weight = 1.0     # 强制选走路
p.behaviour.turn_chance = 0.0     # 不随机翻向
p.play("idle"); p.state_timer = 0.0
p.step(0.05, w._cur_sil())        # 触发 _idle_pick
ck(p.state == "turn_in", f"起步应先进 turn_in，实际 {p.state}")
ck(p.goal is not None, "已有走路目标")
ck(p.facing_right == (p.goal_x > p.body.x), f"转身朝向与目标一致 facing_right={p.facing_right}")

# ③ turn_in 播放期间不被 goal-driven 顶掉
p.goal = "goto"; p.goal_x = p.body.x + 300
for _ in range(4): p.step(0.05, w._cur_sil())
ck(p.state == "turn_in", f"turn_in 播放中不被顶掉（旧 bug：每帧被 play('walk') 覆盖），state={p.state}")

# ④ turn_in 播完 → walk，且 state_timer 已重设
for _ in range(40):
    p.step(0.05, w._cur_sil())
    if p.state == "walk": break
ck(p.state == "walk", f"turn_in 播完接 walk，实际 {p.state}")
ck(p.state_timer > 3.0, f"walk 的 state_timer 已重设（={p.state_timer:.1f}s，不占转身时长）")

# ⑤ 走到目标 → turn_out（转回正面）→ idle（⭐ goal-driven 停下那条路）
for _ in range(600):
    p.step(0.05, w._cur_sil())
    if p.state == "turn_out": break
ck(p.state == "turn_out", f"走到目标应先进 turn_out，实际 {p.state}")
ck(p.goal is None, "目标已清")
for _ in range(40):
    p.step(0.05, w._cur_sil())
    if p.state == "idle": break
ck(p.state == "idle", f"turn_out 播完回 idle，实际 {p.state}")

# ⑥ 目标没走到、走路计时先到 → 继续走（不中途转身）
p.behaviour.walk_weight = 0.0     # 计时到点会"选 idle"，此时目标未清
p.goal = "goto"; p.goal_x = p.body.x + 500
p.state_timer = 0.0
p.step(0.05, w._cur_sil())
ck(p.state == "walk", f"目标未到不该中途转身/停下，实际 {p.state}（goal 仍激活）")

# ⑦ 目标已清、走路计时到点 → turn_out
p.behaviour.walk_weight = 0.0
p.goal = None
p.state_timer = 0.0
p.step(0.05, w._cur_sil())
ck(p.state == "turn_out", f"无目标时走路到点应转回正面，实际 {p.state}")

# ⑧ 朝左走：facing_right=False，turn_in/walk 镜像一致性（逻辑层）
p.behaviour.walk_weight = 1.0
gx = p.body.x - 300
_pick_backup = p._pick_goal          # ⭐ 存好原方法
p._pick_goal = lambda: (setattr(p, "goal", "goto"), setattr(p, "goal_x", gx))
p._idle_pick()
ck(p.facing_right == False, f"目标在左 → facing_right=False，实际 {p.facing_right}")
ck(p.state == "turn_in", f"左走起步同样经 turn_in，实际 {p.state}")
ck(abs(p.goal_x - gx) < 1, "目标未被 _idle_pick 内部重挑")
# ⛔⛔ 必须还原！不还原的话后面所有 _pick_goal 都返回这个固定 x =
#    把 ⑩ 的目标钉死在一个够不到的位置，⑩ 会以"贴着墙原地走 120 秒"收场。
p._pick_goal = _pick_backup

# ⑨ turn 期间不累计睡眠计时
p.behaviour.walk_weight = 1.0
p.goal = None
p.play("idle"); p._sleep_t = 10.0
p.state_timer = 0.0
p.step(0.05, w._cur_sil())        # _idle_pick → turn_in（此后 turn 状态清零 _sleep_t）
for _ in range(5): p.step(0.05, w._cur_sil())
ck(p._sleep_t == 0.0, f"turn 状态不累计睡眠计时（应清零，实际 {p._sleep_t}）")

# ⑩ 无人值守长跑：全链路无卡死（120s）
#   ⛔ 首跑教训：sleep_after 是 40~90s，120s 里她会按设计睡着 → turn_out 没出现不是 bug。
#   本条只验走路链路，先关睡眠；睡眠链路由专项自测覆盖。
p.behaviour.walk_weight = 0.6; p.behaviour.turn_chance = 0.35
p.behaviour.sleep_after = (99999.0, 99999.0); p._sleep_need = 99999.0
random.seed(7)
seen = set()
for _ in range(2400):
    p.step(0.05, w._cur_sil())
    seen.add(p.state)
need = {"turn_in", "turn_out", "walk", "idle"}
ck(need <= seen, f"120s 内走完 idle→turn_in→walk→turn_out→idle 全链路，实际出现 {sorted(seen)}")

# ⑪ ⭐⭐ 够不到的目标不许"贴墙原地走"（2026-09-28 新修）
#   构造一个【必然够不到】的目标：把她放到左墙边，再让目标远远落在墙外。
#   ⛔ 没有这条修的时候：walk 的轮廓左占 174px，目标一旦落在 [sl+80, sl+174)
#      就永远满足不了 arrive_eps → 因为"有目标就不许停"，她会一直贴着墙走到睡着。
p.behaviour.walk_weight = 1.0
p.behaviour.sleep_after = (99999.0, 99999.0); p._sleep_need = 99999.0
p.play("idle"); p.goal = None; p.state_timer = 0.0
p.body.x = float(p.screen[0])          # 贴死左墙
p._pick_goal = lambda: (setattr(p, "goal", "goto"), setattr(p, "goal_x", -5000.0))
p._idle_pick()                          # → turn_in（目标在左）
ck(p.state == "turn_in", f"起步进 turn_in，实际 {p.state}")
for _ in range(400):                    # 20 秒，足够走到墙边并被挡
    p.step(0.05, w._cur_sil())
    if p.goal is None:
        break
ck(p.goal is None, f"够不到的目标应被作废，实际 goal={p.goal} goal_x={getattr(p,'goal_x',None)}")
ck(p.state in ("turn_out", "idle"), f"作废后应转回正面/待机，实际 {p.state}")
p._pick_goal = _pick_backup

print(f"\n=== 结果：{P} 通过 / {F} 失败 ===")
sys.exit(1 if F else 0)
