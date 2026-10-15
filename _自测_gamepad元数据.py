# -*- coding: utf-8 -*-
"""_自测_gamepad元数据.py —— GP03：gamepad 条目改档

派单：`[程序端]派单GP03-gamepad元数据改档.md`（2026-10-14，设计端 team-lead）

--------------------------------------------------------------------------
⭐ 执行结果与**对派单口径的两处更正**（都附实测，不是"我觉得"）
--------------------------------------------------------------------------
① **`loop: cycle → pingpong` 已落地**（与 PNG 尺寸无关，安全）。

② ⛔ **`canvas`/`anchor` 改 512 那套 → 已回退**（维持 640 / 320,640）。
   实测（`_gp03_probe3.py`）：
     sils["gamepad"]  anchor(320,640) ⇒ dbt=**-5**
                      anchor(256,512) ⇒ dbt=**+123**
   `Body.clamp_to_screen` 的 `bottom_limit = 地面 - dbt` ⇒ dbt 转正后她的 y 被顶到
   `799-123=676`，而 `ground_at()`=799 ⇒ 支撑检查判「悬空」⇒ 播 `fall`。
   真机驱动实测（f300）：`y=763.9 on_ground=0 state=fall`，最后滑成 idle，**坐不下来**。
   ⇒ **anchor 必须与盘上 PNG 的实际尺寸匹配**；盘上仍是 GP01b 的 640×640
     ⇒ 现在改 512 是「中间态」，派单 §0/§6 说的「顺序无关」**不成立**。
   ⇒ 正确时序：**GP02 把 512 帧装盘的同一次改动里**再换 canvas+anchor。
      （派单 §0 本来就把「等新素材装盘后再改」列为可选，本单选它。）

③ ⛔ **判据 6 原口径（`seq[0]` vs `seq[15]`）是恒绿判据**：
   `cycle` 的序列是 `range(16)` ⇒ `seq[0]=0`、`seq[15]=15` ⇒ **本来就不等**（派单写
   「cycle 会让 [0]==[15]」是错的），所以那条对两种 loop 都成立、抓不到任何东西。
   ✅ 改成量**循环接缝**：`abs(seq[-1] - seq[0])` —— pingpong=**1**（1→0，无缝），
      cycle=**15**（15→0，硬跳）。这才是「首尾不重复」的正确口径。

⭐ 判据 7 同时充当 **GP02 的闸门**：GP02 装完 512 帧后，判据 7 会红（canvas 640 ≠ PNG 512），
   逼着换 canvas/anchor —— 这正是想要的耦合，不是误报。
"""
import os
import subprocess
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from PySide6.QtGui import QImage                      # noqa: E402
from PySide6.QtWidgets import QApplication            # noqa: E402

app = QApplication.instance() or QApplication([])

from pet_engine.core import load_pack                 # noqa: E402
from pet_engine import ui as U                        # noqa: E402
from pet_engine import ui_toolbar as UT               # noqa: E402

PACK_DIR = os.path.join(HERE, "packs", "luna")
PY = sys.executable
_T = [1000.0]
_orig_perf = time.perf_counter
time.perf_counter = lambda: _T[0]

OK, BAD = [], []


def chk(name, cond, info=""):
    (OK if cond else BAD).append(name)
    print(f"{'  OK ' if cond else ' FAIL'}  {name}   {info}")


def fresh_pack():
    """每次重新读盘 —— ⛔ 别复用被临时改过 loop/anchor 的同一个 pack。"""
    return load_pack(PACK_DIR)


pk = fresh_pack()
GP = pk.actions["gamepad"]
PNG0 = QImage(pk.frame_path("gamepad", 0))
PNG_W, PNG_H = PNG0.width(), PNG0.height()

print("=" * 72)
print("① 已落地的元数据（loop）")
print("=" * 72)
chk("GP03-1 `loop == \"pingpong\"`（本单已落地）",
    GP.loop == "pingpong", f"实测 {GP.loop!r}")
chk("GP03-2 `frames == 16` 且 `fps == 12.0`（派单要求不变）",
    GP.frames == 16 and GP.fps == 12.0, f"frames={GP.frames} fps={GP.fps}")
chk("GP03-3 护栏：`entry_center` / `exit_center` **未被改动**（派单 §3 明令本单不动）",
    list(GP.entry_center) == [302.0, 391.0] and list(GP.exit_center) == [302.0, 391.0],
    f"entry={list(GP.entry_center)} exit={list(GP.exit_center)}")

print()
print("=" * 72)
print("② 播放序列（判循环的正确口径）")
print("=" * 72)
_seq = GP.sequence()
_EXPECT = list(range(16)) + list(range(14, 0, -1))          # 设计端独立复算的 30 项
chk("GP03-4 序列长度 = 16 + 14 = 30（设计端已独立复算）",
    len(_seq) == 30, f"实测 len={len(_seq)}")
chk("GP03-5 序列与设计端独立复算的 30 项**逐项相等**",
    _seq == _EXPECT,
    f"前 17={_seq[:17]} 回程段={_seq[16:]}")
# ⭐⭐ 核心：量「循环接缝」，不是量 seq[0] vs seq[15]
_seam_pp = abs(_seq[-1] - _seq[0])
chk("GP03-6 ⭐⭐⭐ **核心**：pingpong 的循环接缝 `abs(seq[-1]-seq[0]) == 1`"
    "（末帧 1 → 首帧 0，无缝）；⛔ 判据原文的 `seq[0] vs seq[15]` 对两种 loop 都成立，是恒绿口径",
    _seam_pp == 1 and _seq[-1] == 1 and _seq[0] == 0,
    f"seq[-1]={_seq[-1]} seq[0]={_seq[0]} 接缝跳变={_seam_pp}（cycle 会是 {GP.frames - 1}）")

print()
print("=" * 72)
print("③ 阳性对照 A：把 loop 换成 cycle ⇒ 接缝必须变成大跳")
print("=" * 72)
pk_a = fresh_pack()
ga = pk_a.actions["gamepad"]
_pp = pk_a.actions["gamepad"]
_per = {}
for _lp in ("pingpong", "cycle"):
    ga.loop = _lp
    _s = ga.sequence()
    _per[_lp] = (len(_s), abs(_s[-1] - _s[0]), _s[0], _s[15])
chk("GP03-7 ⭐⭐ 阳性对照A：`cycle` 的接缝 = 15（15→0 硬跳）而 `pingpong` = 1"
    " ⇒ 证明判据 6 量的是 loop 这个量，不是恒绿",
    _per["cycle"][1] == 15 and _per["pingpong"][1] == 1,
    f"cycle: len={_per['cycle'][0]} 接缝={_per['cycle'][1]}；"
    f"pingpong: len={_per['pingpong'][0]} 接缝={_per['pingpong'][1]}")

print()
print("=" * 72)
print("④ 真不变量：canvas / anchor 必须匹配**盘上 PNG 的实际尺寸**")
print("=" * 72)
chk("GP03-8 ⭐⭐⭐ canvas == 盘上 PNG 尺寸，且 anchor == (PNG宽/2, PNG高)"
    "（当前 PNG 仍是 GP01b 的 640×640 ⇒ 元数据须保持 640 / 320,640）",
    tuple(GP.canvas) == (PNG_W, PNG_H) and tuple(GP.anchor) == (PNG_W // 2, PNG_H),
    f"盘上 PNG={PNG_W}x{PNG_H}；canvas={list(GP.canvas)} anchor={list(GP.anchor)}"
    f"（若 GP02 已装 512 帧而这里报红 ⇒ 该换 canvas/anchor 了，见文件头 §② ）")

print()
print("=" * 72)
print("⑤ 阳性对照 B：anchor 换成 512 那套（配 640 PNG）⇒ 轮廓 dbt 转正 ⇒ 真机 fall")
print("=" * 72)


def _probe_anchor(anchor):
    """把 gamepad 的 anchor 临时改成给定值，返回 (sils_gamepad, 驱动 300 帧后是否出现过 fall)。"""
    p = fresh_pack()
    p.actions["gamepad"].anchor = tuple(anchor)
    w = U.PetWindow(p)
    w._last_ms = None
    w.pet.mood = 0.0
    w.pet._sleep_need = 1e9
    sil = w.sils.get("gamepad")
    w.pet.go_and_play("gamepad")
    fell = False
    _T[0] += 0.0
    for _ in range(300):
        _T[0] += 1.0 / 60.0
        w._tick()
        if w.pet.state == "fall":
            fell = True
    return sil, fell


_sil_ok, _fell_ok = _probe_anchor((PNG_W // 2, PNG_H))          # 正确：320,640
_sil_bad, _fell_bad = _probe_anchor((256, 512))                 # 错配：512 画布的锚点
chk("GP03-9 ⭐⭐⭐ 阳性对照B：anchor 错配 `(256,512)`（配 640 PNG）⇒ "
    "轮廓 dbt 由负转正（悬空判定）且驱动中**真的出现 fall**；正确 anchor 下 dbt<0 且不 fall"
    " ⇒ 证明 anchor 必须与 PNG 尺寸匹配（这就是本单回退 canvas/anchor 的依据）",
    _sil_ok is not None and _sil_bad is not None
    and _sil_ok[3] < 0 and _sil_bad[3] > 0
    and (not _fell_ok) and _fell_bad,
    f"正确 anchor(320,640)：sil={_sil_ok} dbt={_sil_ok[3]} fall={_fell_ok}；"
    f"错配 anchor(256,512)：sil={_sil_bad} dbt={_sil_bad[3]} fall={_fell_bad}")

print()
print("=" * 72)
print("⑥ 回归：接线 + 相关套件")
print("=" * 72)
w6 = U.PetWindow(fresh_pack())
w6._last_ms = None
w6.pet.mood = 0.0
bar6 = UT.ToolBar(w6)
bar6._open_entry("gamepad")
_on = w6.pet._game_act
bar6._on_hub_closed()
_off = w6.pet._game_act
chk("GP03-10 回归：`ToolBar._open_entry('gamepad')` 仍叫起游戏姿态、`_on_hub_closed()` 仍能停掉",
    _on == "gamepad" and _off is None,
    f"开窗后 _game_act={_on!r}；关窗后 _game_act={_off!r}")

_env = dict(os.environ)
_env["QT_QPA_PLATFORM"] = "offscreen"
_env["PYTHONIOENCODING"] = "utf-8"
_res = {}
for _suite in ("_自测_夜间.py", "_自测_桌宠游戏姿态.py"):
    try:
        _cp = subprocess.run([PY, _suite], cwd=HERE, env=_env,
                             capture_output=True, timeout=300)
        _out = (_cp.stdout or b"").decode("utf-8", "replace")
        _tail = [ln for ln in _out.splitlines() if "通过" in ln][-1:] or ["(无汇总行)"]
        _res[_suite] = (_cp.returncode, _tail[0].strip())
    except subprocess.TimeoutExpired:
        _res[_suite] = ("TIMEOUT", "")
chk("GP03-11 回归：`_自测_夜间.py` 与 `_自测_桌宠游戏姿态.py` 子进程实跑均 exit=0",
    all(rc == 0 for rc, _ in _res.values()),
    "；".join(f"{k} rc={rc} {t}" for k, (rc, t) in _res.items()))

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
