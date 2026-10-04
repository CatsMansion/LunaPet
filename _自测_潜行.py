# -*- coding: utf-8 -*-
"""_自测_潜行.py —— 桌宠「潜行」槽位真的实装了吗（2026-10-04）

⭐ Ronny 报「潜行没实装」。查下来是**两个独立的洞**：
   ① 素材没装机 —— 派单 38 回传早就给了 v2 + 最优窗口 [50,92]，但没有任何一条
      action/sneak_*.png，pet.json 里也没有 sneak（所以 _has_frames("sneak") 恒假，
      点了也只是播 walk，肉眼完全看不出区别）。
   ② 就算装了素材也照样不生效 —— ui.py 里直接 `play("sneak")`，而 core 有目标时
      会 `if self.state != "walk": play_walk()`，sneak 下一帧就被 walk 顶掉。
      ✅ 修法：走 pet.set_sneaking()（素材换 sneak、状态名仍 walk、速度按素材算）。

⭐ 纪律（2026-09-29 事故定）：一律驱动【真实】pet.step()，⛔ 不在脚本里复刻一份逻辑。
"""
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

app = QApplication.instance() or QApplication(sys.argv)

from pet_engine.core import load_pack
from pet_engine.ui import PetWindow

PACK = os.path.join(HERE, "packs", "luna")
DT = 1 / 60.0
CX, CY = 1920, 2000
SIL = (-256, 256, -512, 0)          # 轮廓（地形判定用，这里只是让它不报错）

OK, BAD = [], []


def chk(name, cond, info=""):
    (OK if cond else BAD).append(name)
    print("  %s  %s   %s" % ("OK  " if cond else "FAIL", name, info))


def new_pet():
    w = PetWindow(load_pack(PACK))
    pet = w.pet
    w.screen_rect = (0, 0, 3840, 2160)
    pet.screen = w.screen_rect
    pet.body.x = float(CX)
    pet.body.y = 2160.0
    pet.state = "idle"
    pet.play("idle")
    pet.state_timer = 5.0
    return w, pet


def pump(w, pet, seconds):
    for _ in range(int(60 * seconds)):
        w._feed_cursor()
        pet.step(DT, SIL)


print("=" * 72)
print("潜行自测：素材装机 / 真的在播 / 速度真的慢 / 到点换回走")
print("=" * 72)

# ---- ① 素材 ----
pack = load_pack(PACK)
a = pack.actions.get("sneak")
chk("pet.json 里有 sneak 动作", a is not None, f"{a}")
if a is None:
    print("⛔ 没有 sneak 动作，后面没法测")
    sys.exit(1)
# ⭐ 2026-10-04 Ronny 要求换 24fps 后，这里**不再硬编码帧数/fps**：
#   帧数是素材决策（当前 24fps × 43 帧 = 连续全抽窗口），改一次就会让本自测变红，
#   而它压根不代表"功能坏了"。只断言三件真正要命的事：
#   ① 有帧 ② 帧数与盘上 PNG 张数一致（少一张就是装机漏写） ③ fps 站得住（≥20 才叫流畅）
chk("帧数 / fps / 循环已登记", a.frames > 0 and a.fps >= 20.0 and a.loop == "cycle",
    f"frames={a.frames} fps={a.fps} loop={a.loop}")
_dir = os.path.join(PACK, "action")
n_png = len([f for f in os.listdir(_dir) if f.startswith("sneak_") and f.endswith(".png")])
chk("盘上 PNG 张数 = pet.json 帧数（没漏写）", n_png == a.frames, f"{n_png} 张 / 声明 {a.frames}")
chk("步幅已登记（不是 0）", bool(a.stride_px), f"stride_px={a.stride_px}")
chk("循环帧数已登记（不是 0，否则 move_per_frame 归零 → 原地踩）",
    bool(a.cycle_frames), f"cycle_frames={a.cycle_frames}")

# ⭐ 用 goto 而不是 seek：① `_feed_cursor()` 每帧会用真实光标覆盖 _cursor_x
#   （offscreen 下光标在 0,0 → 她会往左走，位移变负）；
#   ② goal="seek" 会吃到 laser_speed_mul(2.5)，测出来是"追红点速度"不是基础移速。
def run_distance(sneak: bool, seconds: float = 1.0):
    w, pet = new_pet()
    if sneak:
        pet.set_sneaking(3.2)
    pet.goal = "goto"
    pet.goal_x = CX + 900.0
    pump(w, pet, 0.5)                        # 起步缓动先跑掉（turn_ease_tau）
    x0 = pet.body.x
    act = pet.anim.act.name if pet.anim else None
    pump(w, pet, seconds)
    return pet.body.x - x0, act


sneak_dx, sneak_act = run_distance(True)
walk_dx, walk_act = run_distance(False)

chk("潜行中播的是 sneak 素材", sneak_act == "sneak", f"act={sneak_act}")
chk("对照（普通走）播的是 walk 素材", walk_act == "walk", f"act={walk_act}")
chk("潜行 1s 位移 15~40px（慢半拍）", 15.0 < sneak_dx < 40.0, f"{sneak_dx:.1f}px")
chk("普通走 1s 位移 55~85px", 55.0 < walk_dx < 85.0, f"{walk_dx:.1f}px")
chk("潜行明显慢于普通走（30%~60%）",
    0.30 < sneak_dx / max(walk_dx, 1e-6) < 0.60,
    f"比值 {sneak_dx / max(walk_dx, 1e-6):.2f}")

# ---- ④ 到点自动换回 walk ----
w4, pet4 = new_pet()
pet4.set_sneaking(3.2)
pet4.goal = "goto"
pet4.goal_x = CX + 900.0
pump(w4, pet4, 2.0)
chk("潜行中（3.2s 未到）仍是 sneak", pet4.anim.act.name == "sneak",
    f"act={pet4.anim.act.name} sneak_t={pet4.sneak_t:.2f}")
pump(w4, pet4, 1.8)                  # 累计 3.8s > 3.2s
chk("潜行到点自动换回 walk 素材", pet4.anim.act.name == "walk",
    f"act={pet4.anim.act.name}  sneak_t={pet4.sneak_t:.2f}")
chk("换回后不是卡死（状态仍 walk）", pet4.state == "walk", f"state={pet4.state}")

# ---- ⑤ 睡着时不该被潜行叫起来 ----
w3, pet3 = new_pet()
pet3.fall_asleep()
pump(w3, pet3, 0.3)
was_asleep = pet3.asleep
pet3.set_sneaking(3.2)
chk("睡着时点潜行不会把她叫起来", was_asleep and pet3.asleep,
    f"asleep={pet3.asleep} act={pet3.anim.act.name if pet3.anim else None}")

print()
print("=" * 72)
print("通过 %d / %d" % (len(OK), len(OK) + len(BAD)))
if BAD:
    print("未通过： " + "、".join(BAD))
print("=" * 72)
sys.exit(1 if BAD else 0)
