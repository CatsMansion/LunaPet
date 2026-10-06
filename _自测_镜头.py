# -*- coding: utf-8 -*-
"""_自测_镜头.py —— PR-03 第一批：横向镜头跟随的验收判据

⭐ 对应派单 `[程序端]派单PR03-左右镜头跟随-第一批.md` §5.1 镜头 5 项。

⚠️ 口径声明（重要）：
   本自测只覆盖**第一批**（镜头 + 越界 + 死区 + 无抖 + 两端夹紧）。
   ⛔ 玩法不变式（派单 §5.2 六项：微波炉通道 / 容器可达 / 冰箱 / 吊柜……）
      **故意不测** —— 那些依赖第二批的 `PLATFORMS`/`FRIDGE`/`LADDERS` 重排。
      在布局重排前测它们 = 测"旧布局还成立"，与本单无关。
      ⇒ 那六项由 `_自测_可达性.py` / `_自测_冰箱.py` / `_自测_夜间.py` 继续守着。

⭐ 判据纪律（本项目血泪，逐条沿用）：
   · 用 `perf_counter` 换**可控假时钟**：offscreen 下真实 dt≈0.0001s，
     直接 `_step_cam(dt)` 跑"400 帧"其实只过几十微秒 ⇒ 误判"镜头不动"。
   · 判「不动」要断言**逐帧**Δcam_x==0，而不是"最终差不多"。
   · 判「无抖」用**不等式**（每帧 |Δcam| ≤ 露娜位移 + 0.5px），不写死数字。
   · ⭐ **阳性对照**：故意把 CAM_X_DEAD 设成 0 跑一遍，判据必须报红 ——
     证明"死区生效"这条真的在测死区，而不是恰好没动。
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "pet_engine"))
sys.stdout.reconfigure(encoding="utf-8")

from PySide6.QtWidgets import QApplication
app = QApplication.instance() or QApplication([])

import night as N

OK, BAD = [], []
DT = 1.0 / 60.0


def chk(label, cond, detail=""):
    (OK if cond else BAD).append(label)
    print(f"  {'✅' if cond else '⛔'} {label}" + (f"   {detail}" if detail else ""))


def mkwin():
    """造一个**只带镜头所需字段**的轻量窗口替身。

    ⛔ 为什么不用真 NightWindow：它会去 load pack、算角色缩放、建QPixmap，
       与本单要验的东西无关，且慢。⭐ 但字段名必须和真代码一致
       （昨天栽过：用 SimpleNamespace 造 room 报 TypeError，
         真实接口是字典式 cfg["patrol"]）。
    """
    class _W:
        pass
    w = _W()
    w.cam_x = 0.0
    w.luna = None
    w._step_cam = N.NightWindow._step_cam.__get__(w)
    return w


class _FakeLuna:
    def __init__(self, x):
        self.x = float(x)


def setcam(w, x, cam=None):
    """把镜头放到某个位置再把露娜放在某处，返回二者。"""
    w.cam_x = float(N.CAM_X_MAX if cam is None else cam)
    w.luna = _FakeLuna(x)
    return w.luna.x, w.cam_x


print("=" * 72)
print("PR-03 第一批 · 镜头跟随验收（派单 §5.1）")
print("=" * 72)
print(f"  常量核对: WORLD_W={N.WORLD_W}  VW={N.VW}  "
      f"cam_x∈[0,{N.CAM_X_MAX}]  LAG={N.CAM_X_LAG}  DEAD={N.CAM_X_DEAD}")
chk("世界宽=3840 / 视口=1280 ⇒ cam_x 上界 2560",
    N.WORLD_W == 3840 and N.VW == 1280 and N.CAM_X_MAX == 2560,
    f"CAM_X_MAX={N.CAM_X_MAX}")

# ------------------------------------------------------------------
# 1. 镜头永远不越界（跑 5000 帧逐帧断言）
# ------------------------------------------------------------------
print()
print("① 镜头永远不越界（5000 帧，露娜在世界两端来回跑）")
w = mkwin()
_lo, _hi = 0.0, float(N.WORLD_W)
_bad_cnt = 0
_worst = None
_x = 200.0
_d = 1
for _f in range(5000):
    _x += _d * 9.0                # 每帧 9px，来回跑覆盖全地图
    if _x <= 20.0 or _x >= _lo + N.WORLD_W - 20.0:
        _d = -_d
        _x = max(20.0, min(_lo + N.WORLD_W - 20.0, _x))
    w.luna = _FakeLuna(_x)
    w._step_cam(DT)
    if w.cam_x < 0.0 or w.cam_x > N.CAM_X_MAX:
        _bad_cnt += 1
        if _worst is None:
            _worst = (w.cam_x, _f, _x)
chk("5000 帧内cam_x 始终 ∈ [0, 2560]", _bad_cnt == 0,
    f"越界 {_bad_cnt} 帧" + (f"  首个越界 cam_x={_worst[0]:.4f} @frame{_worst[1]}"
                              if _worst else ""))

# ------------------------------------------------------------------
# 2. 露娜走不出世界（_clamp_x 夹世界宽，不再夹视口）
# ------------------------------------------------------------------
print()
print("② 露娜走不出世界（_clamp_x 必须夹 world_w 而不是 VW）")
w2 = mkwin()


class _FakeRoom:
    world_w = float(N.WORLD_W)


room = _FakeRoom()
clamp = N.Luna._clamp_x
lua = _FakeLuna(0.0)
lua.x = -9999.0
clamp(lua, room)
chk("露娜被左边界夹住", 16.0 <= lua.x < 40.0, f"x={lua.x:.1f}（BODY_W*0.5+8=24 附近）")
lua.x = 99999.0
clamp(lua, room)
chk("露娜被右边界夹住（世界右缘，不是 1280 视口右缘）",
    N.WORLD_W - 40.0 < lua.x <= N.WORLD_W, f"x={lua.x:.1f}")
# ⭐ 阳性对照：旧版夹 VW ⇒ 右边界会是 ~1240。确认我们**不是**那个行为。
chk("⛔ 右边界不是旧版的 1280 视口边界（证明真改成世界宽了）",
    lua.x > N.VW, f"x={lua.x:.1f} > VW={N.VW}")

# ------------------------------------------------------------------
# 3. 死区生效：露娜在 cam_x+640±24 内移动 ⇒ cam_x 一帧都不变
# ------------------------------------------------------------------
print()
print("③ ⭐ 死区生效（±24px 内cam_x 逐帧零变化）")
w3 = mkwin()
# 把镜头放在中段，露娜落在镜头中心附近（进入死区）
setcam(w3, N.CAM_X_CENTER + 1200.0 + 10.0, cam=1200.0)
_base = w3.cam_x
_moved = 0
for _f in range(180):                 # 在死区内来回小幅移动
    w3.luna.x = 1200.0 + 640.0 + 10.0 + (6.0 if _f % 2 else -6.0)
    w3._step_cam(DT)
    if w3.cam_x != _base:
        _moved += 1
chk("死区内 180 帧 cam_x 零变化", _moved == 0, f"变动 {_moved} 帧（基线 {_base:.2f}）")

# ⭐⭐ 阳性对照（必做）：把死区临时设成 0，同一场景必须报红。
#   不做这步 ⇒ "死区生效"可能只是"恰好没动"，判据等于没测。
_saved = N.CAM_X_DEAD
try:
    N.CAM_X_DEAD = 0.0
    w3b = mkwin()
    setcam(w3b, 1200.0 + 640.0 + 10.0, cam=1200.0)
    _base2 = w3b.cam_x
    _moved2 = 0
    for _f in range(180):
        w3b.luna.x = 1200.0 + 640.0 + 10.0 + (6.0 if _f % 2 else -6.0)
        w3b._step_cam(DT)
        if w3b.cam_x != _base2:
            _moved2 += 1
finally:
    N.CAM_X_DEAD = _saved
chk("✅ 阳性对照：死区设 0 后同一场景会动（证明③真在测死区）",
    _moved2 > 0, f"死区=0 时变动 {_moved2} 帧（应 >0）")

# ------------------------------------------------------------------
# 4. 无跳变：逐帧 |Δcam_x| ≤ 露娜位移 + 0.5px
# ------------------------------------------------------------------
print()
print("④ ⭐ 镜头跟随无跳变（逐帧 |Δcam| ≤ 露娜位移 + 0.5px）")
w4 = mkwin()
w4.cam_x = 0.0
_x = 300.0
_viol = 0
_maxratio = 0.0
_worst4 = None
for _f in range(1200):
    _px = _x
    _x += 7.0                    # 露娜匀速 7px/帧
    w4.luna = _FakeLuna(_x)
    w4._step_cam(DT)
    _d_cam = abs(w4.cam_x - getattr(w4, "_prev_cam", w4.cam_x))
    _d_luna = abs(_x - _px)
    # 死区帧镜头不动 ⇒ Δ=0，天然满足不等式。这里统计**最大超出量**。
    _excess = _d_cam - (_d_luna + 0.5)
    if _excess > 1e-9:
        _viol += 1
        if _excess > _maxratio:
            _maxratio = _excess
            _worst4 = (_d_cam, _d_luna, _f)
    w4._prev_cam = w4.cam_x
chk("1200 帧无跳变（相机位移没超过露娜位移）", _viol == 0,
    f"超限 {_viol} 帧" + (f"  最严重 Δcam={_worst4[0]:.2f} vs Δ露娜={_worst4[1]:.2f}"
                           if _worst4 else ""))

# 加速跑（露娜变快⇒ 镜头必须能跟上，不能被LAG 拖成"追不上"）
# ⭐⭐ 2026-10-05 程序端修判据（第一版报 9500px 滞后，是**判据自己的错**）：
#   第一版让露娜从 x=100 每帧 +14px 跑 900 帧 ⇒ 她跑到 x≈12700，
#   **远超世界右缘 3824**。此时 want 恒被 clamp 到 2560，而露娜还在往前跑
#   ⇒ 误差 = (x-640) - 2560 单调累积到 9500。
#   ⛔ 那不是"镜头跟不上"，那是"露娜已走出世界，镜头本来就该停在边界"。
#   ✅ 正确口径：**稳态滞后只在中段测**（want 不撞上下界），
#      边界行为由第① 项（不越界）和第⑤ 项（两端夹紧）守。
#⭐ 理论值：匀速 v 时滞后 ≈ v/LAG = 14*60/6 = 140px，再扣死区 24 ⇒≈116px。
#   门槛取 160px（容35%），不写死理论值 —— 理论值本身是推导，不是实测。
w5 = mkwin()
w5.cam_x = 0.0
_x = 300.0
_maxlag = 0.0
_N = 190                        # 190 帧 × 14px = 2660px ⇒ x到 2960，仍在中段
for _f in range(_N):
    _x += 14.0
    w5.luna = _FakeLuna(_x)
    w5._step_cam(DT)
    if _f > 40:                  # 跳过平滑启动段
        _maxlag = max(_maxlag, abs((_x - N.CAM_X_CENTER) - w5.cam_x))
chk("高速跑动时镜头跟得上（中段稳态滞后 < 160px）", _maxlag < 160.0,
    f"稳态最大滞后 {_maxlag:.1f}px（理论 v/LAG=140 扣死区 24≈116）")
chk("⛔ 上面那条测的是中段，边界不参与（否则会假红）",
    _x < N.WORLD_W - N.BODY_W, f"结束时 x={_x:.0f}，世界右缘 {N.WORLD_W - N.BODY_W:.0f}")

# ------------------------------------------------------------------
# 5. 左右跑到头
# ------------------------------------------------------------------
print()
print("⑤ 左右跑到头")
w6 = mkwin()
setcam(w6, 16.0)
for _f in range(600):
    w6._step_cam(DT)
chk("露娜 x=16 ⇒ cam_x=0（左端夹紧）", abs(w6.cam_x - 0.0) < 1e-6,
    f"cam_x={w6.cam_x:.4f}")

w7 = mkwin()
setcam(w7, N.WORLD_W - 16.0)
for _f in range(600):
    w7._step_cam(DT)
chk("露娜 x=3824 ⇒ cam_x=2560（右端夹紧）", abs(w7.cam_x - N.CAM_X_MAX) < 1e-6,
    f"cam_x={w7.cam_x:.4f}")

# ------------------------------------------------------------------
# 6. ⭐ 回归：背景切片在缺图时不崩（BG-02b 未回传的现状）
# ------------------------------------------------------------------
print()
print("⑥ ⭐ 渐进降级：切片缺失时不崩（BG-02b 未回传的现状）")
# ⭐ 2026-10-05 程序端修判据：第一版查的是 __doc__ 里的注释文字 ⇒ 红。
#   ⛔ **注释不是判据** —— 那验的是"我写了这句话"，不是"代码有这个行为"。
#   ✅ 改成真调用：真拿一个"切片全None 的窗口"去画，看会不会抛异常。
chk("_draw_bg_slices 方法存在", hasattr(N.NightWindow, "_draw_bg_slices"))

from PySide6.QtGui import QImage, QPainter, QColor
from PySide6.QtCore import QRectF          # noqa: F401  (与被测模块同源，供将来复用)


def _paint_with(w, tag):
    """真跑一次 _draw_bg_slices，返回 (ok, detail)。"""
    try:
        pm = QImage(1280, 720, QImage.Format_ARGB32)
        pm.fill(QColor(0, 0, 0, 255))
        p = QPainter(pm)
        N.NightWindow._draw_bg_slices(w, p)
        p.end()
        return True, tag
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


_w8 = mkwin()
_w8.bg_slices = [None, None, None]        # ⛔ 模拟 BG-02b 未回传
_w8.bg_img = None
_w8.cam_x = 0.0
_ok, _d = _paint_with(_w8, "空画布实跑通过")
chk("⛔ 三张切片都缺时能画（不抛异常、不白屏）", _ok, _d)

#切片齐时也要能画（模拟 BG-02b 到位后的状态）⇒ 提前验掉"到位那天才炸"
_w9 = mkwin()
_w9.bg_img = None
_w9.cam_x = 0.0
_w9.bg_slices = [QImage(1280, 720, QImage.Format_ARGB32) for _ in range(3)]
_ok2, _d2 = _paint_with(_w9, "")
chk("三张切片齐全时能画（BG-02b 到位后的状态）", _ok2, _d2)

# ⭐ 切片齐 + 镜头推到最右（画第3 张切片，边界最容易出事）
_w10 = mkwin()
_w10.bg_img = None
_w10.bg_slices = [QImage(1280, 720, QImage.Format_ARGB32) for _ in range(3)]
_w10.cam_x = float(N.CAM_X_MAX)
_ok3, _d3 = _paint_with(_w10, "")
chk("cam_x=2560（最右）时三切片仍能画", _ok3, _d3)

# ------------------------------------------------------------------
# 7. ⭐⭐ 像素级验「只平移不缩放 + 没有二次偏移」
# ------------------------------------------------------------------
#⭐ 这条是**唯一**能抓「背景二次偏移」的判据。
#   我第一版写_draw_bg_slices 时，在里面写了 sx = wx - cam_x，
#   而本方法又在外层 p.translate(-cam_x) 之内调用 ⇒ **减了两次**。
#   逻辑测试全部会绿（因为只验 cam_x 数值，不验画面），
#   只有"在世界坐标里放标记块，看它落到屏幕哪"才抓得到。
#   ⛔ 判据纪律：⛔ 判"画面平移对不对"必须落在**像素**上，不能只验状态量。
print()
print("⑦ ⭐⭐ 像素级：只平移不缩放、且没有二次偏移")


def _shot_with_marker(cam_x):
    """画一帧：每张切片在世界 x=100..180 处放一个红色标记块。"""
    w = mkwin()
    w.cam_x = float(cam_x)
    w.bg_img = None
    w.bg_slices = []
    for _i in range(3):
        im = QImage(1280, 720, QImage.Format_ARGB32)
        im.fill(QColor(30 + _i * 40, 60, 120, 255))
        pp = QPainter(im)
        pp.fillRect(QRectF(100, 300, 80, 80), QColor(255, 0, 0, 255))
        pp.end()
        w.bg_slices.append(im)
    pm = QImage(1280, 720, QImage.Format_ARGB32)
    pm.fill(QColor(0, 0, 0, 255))
    p2 = QPainter(pm)
    p2.save()
    p2.translate(-w.cam_x, 0.0)          # 与 paintEvent 同一套变换
    N.NightWindow._draw_bg_slices(w, p2)
    p2.restore()
    p2.end()
    return pm


def _find_red(pm):
    for _y in range(0, 720, 2):
        for _x in range(0, 1280, 2):
            c = pm.pixelColor(_x, _y)
            if c.red() > 200 and c.green() < 80 and c.blue() < 80:
                return _x
    return None


_a = _find_red(_shot_with_marker(0))
_b = _find_red(_shot_with_marker(50))
chk("标记块在 cam_x=0 时落到屏幕 x=100", _a == 100, f"实测 x={_a}")
chk("标记块在 cam_x=50 时落到屏幕 x=50", _b == 50, f"实测 x={_b}")
chk("⭐ 位移量 = cam_x 差值（证明只平移不缩放、无二次偏移）",
    (_a is not None and _b is not None and (_a - _b) == 50),
    f"实测位移 {_a - _b if (_a and _b) else 'NA'}px，期望 50px")

print()
print("=" * 72)
print(f"通过 {len(OK)} / {len(OK) + len(BAD)}")
if BAD:
    print("⛔ %d 项未过：%s" % (len(BAD), "、".join(BAD)))
print("=" * 72)
sys.exit(1 if BAD else 0)