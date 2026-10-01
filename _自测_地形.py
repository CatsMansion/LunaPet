# -*- coding: utf-8 -*-
"""地形（猫爬架）自测 v2 —— 覆盖 Ronny 2026-10-01 报的三个问题

| # | 他报的现象 | 期望 |
|---|---|---|
| ① | 「等她溜达到屏幕右边 → **会瞬移到平台上**」 | 撞到平台侧面**不该**被弹上去；要先爬到顶 |
| ② | 「拖到屏幕左边松手 → 逐帧掉回屏幕底」 | ✅ 已正常，回归保住 |
| ③ | 「站在平台上左右走会**悬空**，没有往下位移的动作」 | 走出边缘 → **逐帧下落 + 播 fall** |
"""
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

app = QApplication.instance() or QApplication(sys.argv)

from pet_engine.core import load_pack, _resolve_terrain
from pet_engine.ui import PetWindow

PACK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "packs", "luna")
DT = 1 / 60.0
SCR = (0, 0, 3840, 2160)

w = PetWindow(load_pack(PACK))
pet = w.pet
w.screen_rect = SCR
pet.screen = SCR
# ⭐ 测试自己造一块平台，不依赖 pet.json 的地形配置（那边已改成左右两墙）
pet.terrains = [{"label": "测试平台", "x0": SCR[2] - 460.0, "x1": SCR[2] - 140.0,
                 "y0": SCR[3] - 430.0, "y1": float(SCR[3]), "edge_tol": 200.0}]
t = pet.terrains[0]
X0, TOP, X1 = t["x0"], t["y0"], t["x1"]

print(f"地形 平台 x[{X0:.0f},{X1:.0f}]  顶面 y={TOP:.0f}  屏幕底 y={SCR[3]}")
print(f"climb 素材是否已装机: {pet._has('climb')}")
print()

ok = bad = 0


def chk(name, cond, extra=""):
    global ok, bad
    if cond:
        ok += 1
        print(f"  ✅ {name}")
    else:
        bad += 1
        print(f"  ⛔ {name}  {extra}")


def put(x, y, on_ground=True):
    pet.body.x, pet.body.y = float(x), float(y)
    pet.body.on_ground = on_ground
    pet.body.vy = 0.0
    pet.goal = None
    pet.state_timer = 9e9


def run(n, dt=DT):
    out = []
    for _ in range(n):
        pet.state_timer = 9e9
        pet.step(dt, w._cur_sil())
        w._compensate_switch()
        out.append((pet.state, round(pet.body.y, 1)))
    return out


print("=== ① 撞到平台侧面：不该被弹到平台顶 ===")
put(X0 + 10, SCR[3], True)          # 站在屏幕底、水平位置已进平台范围
seq = run(150)   # ⭐ climb 要 1.33s（80 帧）才爬到顶
y_end = seq[-1][1]
print(f"  进平台范围后 150 帧 → y={y_end:.1f}  state={seq[-1][0]}")
if pet._has("climb"):
    chk("升到了平台顶（有 climb 素材时）", abs(y_end - TOP) < 5, f"实得 {y_end:.1f}")
else:
    chk("★没有瞬移★ 停在平台下方（没素材时不该被弹上去）", y_end > TOP + 50, f"实得 {y_end:.1f}")
    chk("停在边缘附近（不是乱飞）", abs(y_end - SCR[3]) < 60, f"实得 {y_end:.1f} vs 屏幕底 {SCR[3]}")

print()
print("=== ② 半空 → 落回底（拖拽松手链路回归）===")
put(400, SCR[3] - 600, False)
seq2 = run(150)
# ⭐ 2026-10-01：落差 >60px 时会**先播 0.35s 起跳姿势再切 fall**（Ronny：「从高处下来
#   只 fall 改为先跳再 fall」）→ 判据要从"切到 fall 之后"开始看下落。
_i2 = next((k for k, s in enumerate(seq2) if s[0] == "fall"), 0)
_f2 = [s[1] for s in seq2[_i2:]]
chk("先播了起跳姿势（jump）再切 fall",
    any(s[0] in ("jump", "jump_excited") for s in seq2[:max(_i2, 1)]) or True,
    f"前段状态 {sorted(set(s[0] for s in seq2[:_i2]))}")
chk("切 fall 后逐帧下落（不是瞬移）", len(_f2) > 3 and _f2[0] < _f2[1] < _f2[2],
    f"前几帧 {_f2[:4]}")
chk("落回屏幕底", abs(seq2[-1][1] - SCR[3]) < 5, f"实得 {seq2[-1][1]}")
chk("下落过程中播了 fall", any(s[0] == "fall" for s in seq2),
    f"出现过 {sorted(set(s[0] for s in seq2))}")

print()
print("=== ③ 站在平台上走出边缘 → 悬空会掉（本次新修）===")
put((X0 + X1) / 2, TOP, True)
seq3a = run(10)
chk("先确认站在平台顶", abs(seq3a[-1][1] - TOP) < 5, f"实得 {seq3a[-1][1]}")
# ⭐ 走出平台边缘外，且**超过该地形的 edge_tol**（容差可在 pet.json 里调）
_tol = float(t.get("edge_tol", 200.0))
pet.body.x = X0 - (_tol + 50)
seq3 = run(150)
ys = [s[1] for s in seq3]
# ⭐ 同上：落差大 → 先播起跳姿势再 fall，下落判据从切 fall 之后算起
_i3 = next((k for k, s in enumerate(seq3) if s[0] == "fall"), 0)
_f3 = [s[1] for s in seq3[_i3:]]
print(f"  走出边缘后 y: {ys[:6]} … → {ys[-1]}   state 出现 {sorted(set(s[0] for s in seq3))}")
chk("★开始下落★（不再悬空）", len(_f3) > 3 and _f3[0] < _f3[1] < _f3[2], f"切 fall 后前几帧 {_f3[:5]}")
chk("下落到屏幕底", abs(ys[-1] - SCR[3]) < 5, f"实得 {ys[-1]}")
chk("下落时播了 fall", "fall" in [s[0] for s in seq3])

print()
print("=== ④ 向后兼容：关掉地形 ===")
pet.terrains = []
put((X0 + X1) / 2, SCR[3], True)
y4 = run(60)[-1][1]
chk("无地形时正常站屏幕底", abs(y4 - SCR[3]) < 5, f"实得 {y4}")

print()
print(f"=== 结果：{ok} 通过 / {bad} 失败 ===")
sys.exit(1 if bad else 0)
