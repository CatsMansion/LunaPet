# -*- coding: utf-8 -*-
"""_自测_桌宠游戏姿态.py —— 「开游戏窗 → 露娜自己走到屏幕右下角播 gamepad」的源码层验证

来源：Ronny 2026-10-14 09:11 口述
     「新增一个待办，游戏窗口打开时，桌宠露娜要走到屏幕右下角，然后播放动作打游戏。」
     Ronny 09:23 三答：同进程 / 主屏 / 复用现有自主走动。
     Ronny 09:27 授权开锁：「开锁开干，大不了回档」。

改动：
  · core.py        `Pet.go_and_play()` / `Pet.end_game_act()` / `Pet._game_go_x()`
                   + `_arrive()` / `_idle_pick()` 的游戏姿态分支 + `begin_drag()` 清 `_game_arrived`
  · ui_toolbar.py  `_open_entry()` 开窗后叫她去坐下；`_on_hub_closed()` 关窗时叫停

⭐ 纪律（2026-09-29 / 10-14 两次事故定的）：
  ① 驱动真 `PetWindow._tick()`，⛔ 不在脚本里复刻走动/物理逻辑
  ② 「画出来的是 gamepad 帧」按 **QImage 对象身份** 认定（spy `QPixmap.fromImage`），
     ⛔ **不看 `pet.state` 字符串** —— 「state 写对了但画的是别的帧」正是要防的坑
  ③ 每条判据都配**阳性对照**（⛔ 没有对照不算数）
  ④ 用可控假时钟（`_tick` 拿真时钟的话 dt≈1e-4，她一步都走不动）
"""
import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from PySide6.QtCore import Qt                      # noqa: E402
from PySide6.QtGui import QPixmap                  # noqa: E402
from PySide6.QtWidgets import QApplication         # noqa: E402

app = QApplication.instance() or QApplication([])

from pet_engine.core import load_pack              # noqa: E402
from pet_engine import ui as U                     # noqa: E402
from pet_engine import ui_toolbar as UT            # noqa: E402

pack = load_pack(os.path.join(HERE, "packs", "luna"))

# ---- 可控时钟（⛔ 必须：真时钟下 _tick 的 dt≈1e-4，她一帧走 0.00x px）----
_T = [1000.0]
_orig_perf = time.perf_counter
time.perf_counter = lambda: _T[0]

OK, BAD = [], []


def chk(name, cond, info=""):
    (OK if cond else BAD).append(name)
    print(f"{'  OK ' if cond else ' FAIL'}  {name}   {info}")


def new_window():
    """新开一个真 PetWindow，并把时钟/心情夹具摆成可复现状态。

    ⛔ `mood = 0` 是刻意的：`_pick_goal()` 在 `mood >= seek_cursor_mood(65)` 时
       会去追光标 ⇒ 对照组会受本机光标位置影响，判据就不可复现了。
    """
    w = U.PetWindow(pack)
    w._last_ms = None               # ⭐ 让首帧 dt 走 0.016 分支（见 ui._tick）
    w.pet.mood = 0.0
    w.pet._sleep_need = 1e9         # 别让她在测试中途睡着
    return w


def _frame_owner(w, im):
    """按 QImage **对象身份**反查这一帧属于哪个动作。"""
    for name, lst in (w.frames or {}).items():
        for i, x in enumerate(lst or []):
            if x is im:
                return name, i
    return None, None


def capture(w):
    """真 render 一次，返回 paintEvent 这帧实际用的 (动作名, 帧索引)。

    ⭐ 认 `QPixmap.fromImage` 的**入参 QImage** —— 那正是 `w.frames[name][idx]` 里的对象
      （`paintEvent` 是 `pm = QPixmap.fromImage(im)`，再 drawPixmap）。
    """
    seen = []
    _orig = QPixmap.fromImage

    def _spy(im, *a, **k):
        seen.append(im)
        return _orig(im, *a, **k)

    QPixmap.fromImage = staticmethod(_spy)
    try:
        pm = QPixmap(w.size())
        pm.fill(Qt.transparent)
        w.render(pm)
    finally:
        QPixmap.fromImage = _orig
    if not seen:
        return None, None
    return _frame_owner(w, seen[0])


def drive(w, n, on_frame=None):
    """驱 n 帧真 `_tick`；每帧可选回调 on_frame(i)。"""
    for i in range(n):
        _T[0] += 1.0 / 60.0
        w._tick()
        if on_frame is not None:
            on_frame(i)


def walk_until(w, pred, max_frames=3000, sample_every=40):
    """驱帧直到 pred(w) 成立（或超帧数）。返回 (用了多少帧, 沿途命中的帧身份集合, 走过的 x 轨迹极值)。"""
    seen_names = set()
    xs = [w.pet.body.x]
    n = 0
    for n in range(1, max_frames + 1):
        _T[0] += 1.0 / 60.0
        w._tick()
        xs.append(w.pet.body.x)
        if n % sample_every == 0 or pred(w):
            nm, _ = capture(w)
            if nm:
                seen_names.add(nm)
        if pred(w):
            break
    return n, seen_names, (min(xs), max(xs))


print("=" * 72)
print("① 判据 A：go_and_play('gamepad') ⇒ 她真的走到屏幕右下角、且**画出的是 gamepad 帧**")
print("=" * 72)

w = new_window()
sr = float(w.screen_rect[2])
sl = float(w.screen_rect[0])
_x0 = w.pet.body.x
w.pet.go_and_play("gamepad")
_n_walk, _walk_names, _xspan = walk_until(w, lambda ww: ww.pet.state == "gamepad")
_x_end = w.pet.body.x
# 到位后再多驱 30 帧，**每帧**都取一次帧身份 ⇒ 证明"坐下之后一直在画 gamepad"
_post_names = []
_post_idx = []
for _ in range(30):
    _T[0] += 1.0 / 60.0
    w._tick()
    _nm, _ix = capture(w)
    _post_names.append(_nm)
    _post_idx.append(_ix)
_act_name = w.pet.anim.act.name if w.pet.anim else None
_all_post_gamepad = bool(_post_names) and all(x == "gamepad" for x in _post_names)
_anim_running = len(set(i for i in _post_idx if i is not None)) >= 2

chk("㉙-1 ⭐⭐⭐ 判据A：`go_and_play('gamepad')` ⇒ 她**自己走到屏幕右缘**（不是瞬移）"
    "，到位后循环播 gamepad，且**画出的帧身份属于 gamepad**（⛔ 不是只看 state 字符串）",
    _x_end > _x0 + 100.0                      # 真往右走了
    and _x_end > (sl + sr) / 2.0              # 走到了屏幕右半边
    and _x_end >= sr - 260.0                  # 贴着右限位（轮廓 + margin 会留一点）
    and w.pet.state == "gamepad"
    and _act_name == "gamepad"
    and _all_post_gamepad
    and _anim_running,
    f"x {_x0:.0f} → {_x_end:.0f}（屏 {sl:.0f}~{sr:.0f}）走了 {_n_walk} 帧；"
    f"state={w.pet.state} anim={_act_name}；"
    f"到位后 30 帧画出动作={sorted(set(_post_names))} 用到 {len(set(_post_idx))} 个不同帧索引")

print()
print("=" * 72)
print("② 判据 A 阳性对照：**不调** go_and_play ⇒ 全程不会出现 gamepad 帧")
print("=" * 72)

w2 = new_window()
_n2, _names2, _span2 = walk_until(w2, lambda ww: False, max_frames=600, sample_every=40)
chk("㉙-2 ⭐⭐ 判据A 阳性对照：同一套夹具但**不调** `go_and_play`"
    " ⇒ 600 帧里一次 gamepad 帧都不许画、state 也绝不等于 gamepad"
    "（证明判据A 抓的是「她被叫去打游戏」这件事，不是恒绿）",
    "gamepad" not in _names2 and w2.pet.state != "gamepad",
    f"沿途画出的动作={sorted(_names2)}（共 {_n2} 帧）state={w2.pet.state}")

print()
print("=" * 72)
print("③ 判据 B：end_game_act() ⇒ 结束游戏姿态、回到正常漫游（不残留）")
print("=" * 72)

_end_before = w.pet.state
w.pet.end_game_act()
_st_after = w.pet.state
_act_after = w.pet.anim.act.name if w.pet.anim else None
# 再驱 240 帧（4s）：⛔ 不许她自动回到 gamepad（游戏窗已关）
_resid = []
for _ in range(240):
    _T[0] += 1.0 / 60.0
    w._tick()
    if w.pet.state == "gamepad" or (w.pet.anim and w.pet.anim.act.name == "gamepad"):
        _resid.append(_T[0])
chk("㉙-3 ⭐⭐⭐ 判据B：`end_game_act()` ⇒ `_game_act` 清空、`state` 离开 gamepad（回 idle）"
    "；关窗后再跑 240 帧**不许**自动回到 gamepad（游戏窗已关，不能残留）",
    w.pet._game_act is None
    and _end_before == "gamepad"
    and _st_after != "gamepad" and _act_after != "gamepad"
    and len(_resid) == 0,
    f"关窗前 state={_end_before} → 关窗后 state={_st_after} anim={_act_after}；"
    f"240 帧里回到 gamepad 的次数={len(_resid)}")

print()
print("=" * 72)
print("④ 判据 B 阳性对照：给一个**没有帧**的动作 ⇒ 她压根不该去（不进游戏姿态）")
print("=" * 72)

w3 = new_window()
w3.pet.go_and_play("__这个动作不存在__")
_x3_0 = w3.pet.body.x
drive(w3, 120)
chk("㉙-4 ⭐⭐ 判据B 阳性对照：`go_and_play('一个不存在的动作')` ⇒ `_game_act` 必须保持 None、"
    "state 绝不为该动作（证明判据不是「调了就绿」）",
    w3.pet._game_act is None and w3.pet.state != "__这个动作不存在__",
    f"_game_act={w3.pet._game_act} state={w3.pet.state} "
    f"x {_x3_0:.0f} → {w3.pet.body.x:.0f}")

print()
print("=" * 72)
print("⑤ 判据 C：ui_toolbar 接线端到端（开主界面→去坐下 / 关主界面→站起来）")
print("=" * 72)

w4 = new_window()
_bar = UT.ToolBar(w4)
_bar._open_entry("gamepad")
_on_open = w4.pet._game_act
_bar._on_hub_closed()
_on_close = w4.pet._game_act
chk("㉙-5 ⭐⭐⭐ 判据C：真 `ToolBar._open_entry('gamepad')` **端到端**把游戏姿态叫起来"
    "（`_game_act == 'gamepad'`），`_on_hub_closed()` 又把它停掉（`_game_act is None`）"
    " ⇒ 开/关窗两条接线都真的接上了",
    _on_open == "gamepad" and _on_close is None,
    f"开窗后 _game_act={_on_open!r}；关窗后 _game_act={_on_close!r}")

print()
print("=" * 72)
print("⑥ 判据 C 阳性对照：别的入口键（非 gamepad）⇒ 不许触发游戏姿态")
print("=" * 72)

w5 = new_window()
_bar5 = UT.ToolBar(w5)
_bar5._open_entry("laser")            # ⛔ `_open_entry` 只认 "gamepad"，别的键直接 return
chk("㉙-6 ⭐⭐ 判据C 阳性对照：`_open_entry('laser')`（非 gamepad 键）⇒ `_game_act` 必须还是 None"
    "（证明判据C 测的是 gamepad 这条接线本身，不是「调了 _open_entry 就绿」）",
    w5.pet._game_act is None,
    f"_game_act={w5.pet._game_act!r}")

print()
print("=" * 72)
print(f"通过 {len(OK)} / {len(OK) + len(BAD)}")
if BAD:
    print(f"❌ 未通过 {len(BAD)} 条：")
    for _n in BAD:
        print("   ·", _n)
print("=" * 72)

time.perf_counter = _orig_perf
sys.exit(1 if BAD else 0)
