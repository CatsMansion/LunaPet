# -*- coding: utf-8 -*-
"""_自测_抠像键控v2.py —— GP04-v2：真·绿幕键控窗口收窄（薄荷保护）

派单：`[程序端]派单GP04v2-真键控窗口收窄.md`（设计端 team-lead 2026-10-15 08:40）
性质：0 积分 / 只改 1 行常数 + 2 行注释 / 不出图

改动（唯一实质改动 + 注释更正）：
  `客户资料/露娜/试点产出/桌宠v1/_work/_绿幕抠像.py`
    · :32 注释  RGB(0,201,0)→RGB(0,187,0)（实测更正；两者 H 都是 60）
    · :33 常数  `H_LO, H_HI = 35, 85` → `35, 68`   ← 真凶这一处（角色帧的键控在这，不是 _装机_场景分件.py）

⭐ 判据一律**直接驱动真·模块** `_绿幕抠像.bg_mask`（⛔ 不自己复刻一份键控 ——
   那样测的是测试自己，不是被测代码）。
⭐ 旧窗对照用**改模块全局**（`K.H_HI = 85`）来做 —— 同一份代码、只换常数，是最干净的控制变量。

⚠️⚠️ V2-1 / V2-2 / V2-4 是**数学关系判据**（自己设 68/85 对比），
   ⛔ **不守护模块改动** —— 谁把 `_绿幕抠像.py:33` 改回 85，它们照样全绿。
   守护 GP04v2 那处改动由 **V2-5** 负责（它**读模块实际 `H_HI`**，且是全文件**第一条** `chk`，
   之前**没有任何** `K.H_HI = ...` 赋值）。

⚠️ `gamepad_0` 的薄荷现在 = 50，改完**仍是 50**（已装盘成品帧不可回溯）。
   派单 §3 明写它是「预期为红，不是缺陷」，靠 GP02v2 新素材装盘时自然恢复。
   ⇒ 本文件**不为它设判据**，只在 §⑤ 打印实测值供核对。
"""
import hashlib
import importlib
import os
import sys

import numpy as np
import cv2
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
KEYER_DIR = os.path.join(ROOT, "客户资料", "露娜", "试点产出", "桌宠v1", "_work")
KEYER = os.path.join(KEYER_DIR, "_绿幕抠像.py")
GP02 = os.path.join(ROOT, "_work", "_gp02")
ACTION_DIR = os.path.join(HERE, "packs", "luna", "action")

BASELINE_MINT = {"walk_0": 1060, "idle_0": 739}      # GP04 实测基线（派单 §3-V2-3 同值）
OK, BAD = [], []


def chk(name, cond, info=""):
    (OK if cond else BAD).append(name)
    print(f"{'  OK ' if cond else ' FAIL'}  {name}   {info}")


def hsv_of(R):
    hsv = cv2.cvtColor(R, cv2.COLOR_RGB2HSV)
    return (hsv[:, :, 0].astype(np.int16), hsv[:, :, 1].astype(np.int16),
            hsv[:, :, 2].astype(np.int16))


def mint_mask(H, S, V):
    """派单 V2-3 的薄荷口径：0-359 的 H∈[150,178] ⇔ cv2 [75,89]；S∈[51,191]；V≥120"""
    return (H >= 75) & (H <= 89) & (S >= 51) & (S <= 191) & (V >= 120)


def md5f(p):
    return hashlib.md5(open(p, "rb").read()).hexdigest()


# ---- 加载被测模块 ----
sys.path.insert(0, KEYER_DIR)
import _绿幕抠像 as K           # noqa: E402
importlib.reload(K)
print("=" * 78)
print("被测模块：", K.__file__)
print(f"  当前判据：H_LO={K.H_LO} H_HI={K.H_HI}  S_MIN={K.S_MIN} V_MIN={K.V_MIN} SOFT_R={K.SOFT_R}")
print(f"  文件 md5={md5f(KEYER)}  行数={len(open(KEYER, encoding='utf-8').read().splitlines())}")
print("=" * 78)

# ============================================================================
# ⓪ V2-5：**唯一**守护 GP04v2 那处改动的判据。
#   ⛔ 它必须是全文件**第一条** chk，且**之前不许出现任何 `K.H_HI = ...` 赋值** ——
#      一旦自己先把值设好再断言，又变成恒绿判据（GP04v3 派单 §1 抓的就是这个洞）。
# ============================================================================
print()
print("=" * 78)
print("⓪ V2-5 守护：读模块**实际**值（之前无任何 `K.H_HI = ...` 赋值）")
print("=" * 78)
chk("V2-5 ⭐⭐ 守护：模块 `H_HI` 当前值必须 == 68（⛔ 读模块实际值，不许自己设）",
    K.H_HI == 68,
    f"实测 K.H_HI = {K.H_HI}")

SRCS = [os.path.join(GP02, f) for f in
        ("srcframe_00_0.png", "srcframe_01_53.png", "srcframe_02_106.png")]
_missing = [p for p in SRCS if not os.path.isfile(p)]
if _missing:
    chk("V2-0 前置：源帧齐全（`_work/_gp02/srcframe_*.png`）", False,
        f"缺 {[os.path.basename(p) for p in _missing]}")
    SRCS = [p for p in SRCS if os.path.isfile(p)]

# ============================================================================
print()
print("=" * 78)
print("① V2-1 / V2-2：真源帧上的薄荷保留率（新窗 68 vs 旧窗 85，直接跑真模块）")
print("=" * 78)
_rows, _ok_new, _ok_old = [], True, True
for sp in SRCS:
    R = np.array(Image.open(sp).convert("RGB"))
    H, S, V = hsv_of(R)
    mint = mint_mask(H, S, V)
    tot = max(1, int(mint.sum()))
    K.H_HI = 68                                   # 现状（改后）
    keep68 = 100.0 * int((mint & (~K.bg_mask(R))).sum()) / tot
    K.H_HI = 85                                   # 阳性对照（旧窗）
    keep85 = 100.0 * int((mint & (~K.bg_mask(R))).sum()) / tot
    K.H_HI = 68                                   # 复位
    src_mint = int(mint.sum())
    _rows.append(f"{os.path.basename(sp)}: 薄荷{src_mint} 新窗68→{keep68:.1f}% 旧窗85→{keep85:.1f}%")
    if keep68 < 99.0:
        _ok_new = False
    if keep85 > 20.0:
        _ok_old = False

chk("V2-1 ⭐ 新键控（`H_HI=68`）在真源帧上的薄荷保留率 ≥ 99%（3 张全测，跑真模块）"
    "　（测的是数学关系，不守护模块改动）",
    _ok_new and len(SRCS) == 3, "；".join(_rows))
chk("V2-2 ⭐⭐ 阳性对照：同一批源帧用**旧窗 85** 跑 ⇒ 保留 ≤ 20%（⛔ 不报红就说明改窗没生效）"
    "　（测的是数学关系，不守护模块改动）",
    _ok_old, "；".join(_rows))

# ============================================================================
print()
print("=" * 78)
print("② V2-3：防误伤 —— walk_0 / idle_0 的薄荷计数不许变化")
print("=" * 78)
_now = {}
for nm in ("walk_0", "idle_0"):
    p = os.path.join(ACTION_DIR, nm + ".png")
    arr = np.array(Image.open(p))
    H, S, V = hsv_of(arr[:, :, :3])
    _now[nm] = int((mint_mask(H, S, V) & (arr[:, :, 3] > 128)).sum())
    print(f"  {nm}: 薄荷={_now[nm]}（基线 {BASELINE_MINT[nm]}）  文件 md5={md5f(p)}")
chk("V2-3 ⭐ 防误伤：`walk_0` / `idle_0` 薄荷计数与 GP04 基线**完全一致**（没误伤已装帧）",
    all(_now[n] == BASELINE_MINT[n] for n in BASELINE_MINT),
    "；".join(f"{n}: {_now[n]} vs 基线 {BASELINE_MINT[n]}" for n in BASELINE_MINT))

# ============================================================================
print()
print("=" * 78)
print("③ V2-4：绿幕仍被键掉（纯 RGB(0,187,0) 板，跑真模块）")
print("=" * 78)
_g = np.zeros((64, 64, 3), np.uint8)
_g[:, :] = (0, 187, 0)
K.H_HI = 68
_bg = K.bg_mask(_g)
_pct = 100.0 * _bg.mean()
chk("V2-4 ⭐ 收窄窗口后**绿幕仍被判背景**（纯绿板 64×64 ⇒ ≥ 95%）"
    "（⛔ 只收上限不动下限，绿幕底 H=60 离 68 还有 8°，必须仍然键得掉）"
    "　（测的是数学关系，不守护模块改动）",
    _pct >= 95.0, f"判背景 {_pct:.1f}%")

# ============================================================================
print()
print("=" * 78)
print("④ gamepad_0：实测值（⚠️ 派单 §3 明写「预期为红，不是缺陷」，故**不设判据**）")
print("=" * 78)
_gp = os.path.join(ACTION_DIR, "gamepad_0.png")
arr = np.array(Image.open(_gp))
H, S, V = hsv_of(arr[:, :, :3])
_gpm = int((mint_mask(H, S, V) & (arr[:, :, 3] > 128)).sum())
print(f"  gamepad_0 薄荷 = {_gpm}（改前也是 50）  md5={md5f(_gp)}")
print("  ⇒ 已装盘的成品帧不可回溯：它的薄荷在**上次装机时**就被旧窗键掉了。")
print("     本单只修键控本身；gamepad_0 靠 **GP02v2 新素材装盘**时用已修好的键控自然恢复。")
print(f"     确认：仍为 {_gpm}，属预期。")

print()
print("=" * 78)
print(f"通过 {len(OK)} / {len(OK) + len(BAD)}")
if BAD:
    print(f"❌ 未通过 {len(BAD)} 条：")
    for _n in BAD:
        print("   ·", _n)
print("=" * 78)
sys.exit(1 if BAD else 0)
