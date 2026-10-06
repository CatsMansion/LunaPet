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
_rows = []
for name, preset in cfg["behaviour"]["_预设"].items():
    _rows.append((name,) + run(preset, name))

print()
print("⭐ 判读：")
print("   · **到达峰值越晚 = 越重**（跟不上，要慢慢追）")
print("   · 峰值角度只是观感，**滞后才是重量感的来源**")

# ===============================================================
# ⭐ 2026-10-05 程序端补：机器可读结果行（原先只输出散文，判据没法进 CI 契约）
#
# ⛔ 边界声明（重要，别越界）：
#   我是程序端，**不自己定手感阈值**（玩法数值/验收线属设计端）。
#   所以这里只断言**与调参无关的结构性不变量**，手感本身好不好由Ronny 拍板。
#   ⛔ 别把这些断言读成"手感验收线"——它们只保证"测量本身没坏"。
# ===============================================================
_OK = 0
_BAD = []


def chk(label, cond, detail=""):
    global _OK
    print(f"  {'✅' if cond else '⛔'} {label}" + (f"   {detail}" if detail else ""))
    if cond:
        _OK += 1
    else:
        _BAD.append(label)


print()
print("=== 判据· 结构性不变量（⛔ 不是手感验收线）===")

# ① 三档都测到了，且数量与配置一致
chk(f"三档全部测到（配置 {len(cfg['behaviour']['_预设'])} 档）",
    len(_rows) == len(cfg["behaviour"]["_预设"]),
    f"实测 {len(_rows)} 档")

for name, peak, t_peak, t_settle in _rows:
    # ② 数值有效性：NaN / inf 会让后面的比较全部静默失效（判据在制造假绿）
    chk(f"[{name}] 峰值是有限数", math.isfinite(peak), f"peak={peak:.2f}")
    chk(f"[{name}] 到达峰值时间在0~0.6s 内（拖拽只持续 0.6s）",
        math.isfinite(t_peak) and 0.0 < t_peak <= 0.6 + 1e-9, f"t_peak={t_peak*1000:.0f}ms")
    # ③ 松手后必须回正——这是物理底线，"永远歪着"就是 bug 不是风格
    chk(f"[{name}] 松手后能回正（4s 内到峰值的 10%）",
        t_settle is not None, "回正 %.0fms" % (t_settle * 1000) if t_settle else ">4000ms 没收正")

# ④ ⭐ 三档必须有区分度。若两个预设测出完全一样的轨迹，
#    说明其中一个预设**根本没生效**（键名写错 / 没被读取）—— 这是真 bug。
peaks = [r[1] for r in _rows]
sig = [(round(r[1], 4), round(r[2], 5)) for r in _rows]
chk("三档倾角轨迹互不相同（否则有预设未生效）",
    len(set(sig)) == len(sig), f"轨迹签名 {sig}")

# ⑤ 观测到的排序（只报数据，⛔ 不判"对不对"——阈值归设计端）
order = sorted(_rows, key=lambda r: r[2])
print()
print("  📊 按「到达峰值」排序（越晚= 越重）：%s"
      % " → ".join("%s(%.0fms)" % (r[0], r[2] * 1000) for r in order))
print("     ⏳ **手感排序是否符合设计意图，需设计端/ Ronny 拍板**"
      "（程序端不自己定阈值）")

print()
print("=" * 54)
print(f"通过 {_OK} / {_OK + len(_BAD)}")
if _BAD:
    print("⛔ %d 项未过：%s" % (len(_BAD), "、".join(_BAD)))
print("=" * 54)
sys.exit(1 if _BAD else 0)
