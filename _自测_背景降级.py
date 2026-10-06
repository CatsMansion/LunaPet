# -*- coding: utf-8 -*-
"""_自测_背景降级.py —— 切片缺失时用旧图平铺铺满 3840（2026-10-05 试玩阻塞项）

⭐ 为什么这条必须存在
   PR-03 把世界扩到 3840，镜头能跟到 x=2560，但背景切片
   （`scene_bg_0/1/2.png`，BG-02e 长图切片）**还没出图**。
   而旧版降级分支是「把单张 `scene_bg.png` 顶在**世界最左**」
   ⇒ 镜头往右走就是**纯底色空白** ⇒ Ronny 试玩会以为程序坏了。

⭐ 判据纪律
   · ⭐ **两种情形都要能画**（切片在 → 走切片；切片不在 → 走平铺）。
     只测其中一种 = 另一半是假绿。
   · ⭐ 验「铺满 3840」要**看实际画到哪**，不是看函数返回值。
   · ⛔ 断言**行为**（能画 + 铺满 + 不变形），⛔ 不断言源码文本。

⚠️ 为什么⛔ 不用 `scaled()` 拉宽
   那张图里有家具（茶几/厨房台/冰箱/吊柜）。横向拉宽 3 倍⇒
   **家具变成 3 倍宽**，一眼假。平铺则每段都是原尺寸。
   ⭐ 本自测据此加了一条**形变**判据：平铺时同一张图在 x=0 与 x=1280
   的内容**完全一致**（逐像素相同）；若有人改成 `scaled()` 拉宽，这条会红。
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "pet_engine"))
sys.stdout.reconfigure(encoding="utf-8")

from PySide6.QtWidgets import QApplication
app = QApplication.instance() or QApplication([])

from PySide6.QtGui import QImage, QPainter, QColor  # noqa: E402
from PySide6.QtCore import QRectF  # noqa: E402

from pet_engine import night as N  # noqa: E402

OK, BAD = [], []


def chk(label, cond, detail=""):
    (OK if cond else BAD).append(label)
    print(f"  {'OK  ' if cond else 'FAIL'} {label}" + (f"   {detail}" if detail else ""))


class _W:
    """只带 _draw_bg_slices 所需字段的轻量窗口替身。

    ⚠️ 字段名必须和真代码一致 —— 这不是复刻逻辑，是**替掉不相关的重活**
       （load pack / 建 QPixmap / 算缩放）。被画的那一句是真代码。
    """

    def __init__(self, cam_x=0.0, slices=None, bg=None):
        self.cam_x = float(cam_x)
        self.bg_slices = slices if slices is not None else [None, None, None]
        self.bg_img = bg
        self._draw_bg_slices = N.NightWindow._draw_bg_slices.__get__(self)


def _fake_img(w=1280, h=720, seed=0):
    """造一张有可辨识内容的测试图（渐变 + 家具方块），⛔ 不是纯色。

    ⛔ 纯色图验不出"有没有铺满"，也验不出"有没有被拉宽变形"。
    """
    im = QImage(w, h, QImage.Format_ARGB32)
    im.fill(QColor(20, 22, 30))
    p = QPainter(im)
    p.fillRect(QRectF(0, 380, w, 340), QColor(90 + seed, 70, 60))# 地
    p.fillRect(QRectF(120, 300, 300, 90), QColor(150, 120, 80))     # 一块"家具"
    p.fillRect(QRectF(700, 180, 160, 200), QColor(200, 200, 190))   # 另一块
    p.end()
    return im


def _render(cam_x, slices, bg, world_w=3840, vw=1280, vh=720):
    """真跑一次 `_draw_bg_slices`，**世界坐标**渲染（⛔ 不做 translate）。

    ⚠️⚠️ 判据纪律：`paintEvent` 里是 `p.save(); p.translate(-cam_x, 0)` **之内**调用，
       所以**同一个 `p`** 只能二选一：
         · 看**视口**长什么样 ⇒ 画布 VW 宽**且** translate(-cam_x)
         · 看**整个世界**铺没铺满 ⇒ 画布 WORLD_W 宽**且不 translate**
       ⛔ 我第一版同时用了 3840 画布 + translate ⇒ cam_x=2000 时
         整个坐标系被平移了两次，黑列假红720 个。**这是判据自己的错，不是代码的错。**
    """
    pm = QImage(world_w, vh, QImage.Format_ARGB32)
    pm.fill(QColor(0, 0, 0, 255))                # 黑底：空隙会露出来
    p = QPainter(pm)
    _W(cam_x=cam_x, slices=slices, bg=bg)._draw_bg_slices(p)
    p.end()
    return pm


def _render_view(cam_x, slices, bg, vh=720):
    """真跑一次，画**视口**（与 paintEvent 同一套 translate）。"""
    pm = QImage(N.VW, vh, QImage.Format_ARGB32)
    pm.fill(QColor(0, 0, 0, 255))
    p = QPainter(pm)
    p.save()
    p.translate(-cam_x, 0.0)
    _W(cam_x=cam_x, slices=slices, bg=bg)._draw_bg_slices(p)
    p.restore()
    p.end()
    return pm


def _bg_pixels(pm):
    """返回 (x 范围, 逐列是否非黑)。只看视口内的列。"""
    cols = []
    for x in range(pm.width()):
        nonblack = False
        for y in range(0, pm.height(), 8):        # 每 8 行采一次，够用
            c = pm.pixelColor(x, y)
            if c.red() > 26 or c.green() > 26 or c.blue() > 26:
                nonblack = True
                break
        cols.append(nonblack)
    return cols


def _span(cols):
    """非黑列的 [first, last]；全黑返回 (None, None)。"""
    idx = [i for i, v in enumerate(cols) if v]
    return (idx[0], idx[-1]) if idx else (None, None)


print("=" * 74)
print("背景降级：切片缺失 ⇒ 旧图平铺铺满 3840")
print("=" * 74)
print(f"  WORLD_W={N.WORLD_W}  VW={N.VW}  CAM_X_MAX={N.CAM_X_MAX}")
print(f"  真实素材：scene_bg.png存在={os.path.isfile(os.path.join(HERE,'assets_game','scene_bg.png'))}"
      f"  切片存在={[os.path.isfile(os.path.join(HERE,'assets_game',f'scene_bg_{i}.png')) for i in range(3)]}")

_img = _fake_img()
_slices3 = [_fake_img(seed=10), _fake_img(seed=20), _fake_img(seed=30)]

# ------------------------------------------------------------------
# 1. 切片不存在 ⇒ 平铺
# ------------------------------------------------------------------
print()
print("① ⭐ 切片**不存在** ⇒ 旧图平铺铺满 3840")
cols = _bg_pixels(_render(0.0, [None, None, None], _img))
lo, hi = _span(cols)
chk("能画（不抛异常）", True, f"画布 {N.WORLD_W}×{N.VH}")
chk("⭐ 从 x=0 铺到 x=3840（没有空白）", lo == 0 and hi == N.WORLD_W - 1,
    f"非黑列范围 [{lo}, {hi}]，世界宽 {N.WORLD_W}")
_gaps = [i for i, v in enumerate(cols) if not v]
chk("⭐ 全程无空隙列（⛔ 不能有露黑底的缝）", not _gaps,
    f"空隙列 {len(_gaps)} 个" + (f"，样例 {_gaps[:8]}" if _gaps else ""))

# 各处都要有内容（镜头停在任何位置都不该空白）
print()
print("② ⭐ 镜头停在各处都要有背景（走**视口**渲染，与 paintEvent 同一套变换）")
for cam in (0.0, 640.0, 1280.0, 2000.0, float(N.CAM_X_MAX)):
    pv = _render_view(cam, [None, None, None], _img)
    c = _bg_pixels(pv)
    n = sum(1 for v in c if v)
    chk(f"  cam_x={int(cam):4d} ⇒ 视口 {N.VW} 宽全部有背景", n == N.VW,
        f"非黑 {n}/{N.VW} 列")

# ------------------------------------------------------------------
# 2. ⛔ 没有用 scaled 拉宽（形变判据）
# ------------------------------------------------------------------
print()
print("③ ⭐⭐ 平铺 ≠ 拉宽：同一张图在各处的内容必须**逐像素相同**")
_pm = _render(0.0, [None, None, None], _img)


def _col_signature(pm, x, y0=0, y1=None, step=8):
    y1 = pm.height() if y1 is None else y1
    return tuple(pm.pixelColor(x, y).rgba()
                 for y in range(y0, y1, step))


# ⭐ 比"同一个 x 偏移在三段里是否相同"：x / x+1280 / x+2560。
#   ⚠️ 必须比**同一偏移**（如 10 vs 1290 vs 2570），⛔ 不是比任意两个 x
#   （那张图不是左右对称的，比 10 vs 640 本来就该不同，那是图的内容不是形变）。
_sigs = {}
for _off in (10, 200, 640, 900):
    for _seg in (0, 1, 2):
        _sigs[(_off, _seg)] = _col_signature(_pm, _off + _seg * 1280)
_same = all(_sigs[(_off, 0)] == _sigs[(_off, 1)] == _sigs[(_off, 2)]
            for _off in (10, 200, 640, 900))
chk("⭐ 同一偏移在 3 段里像素**完全一致**（=平铺，不是拉宽）", _same,
    "x / x+1280 / x+2560 逐像素相同" if _same else
    "不一致 ⇒ ⛔ 有人改成了 scaled() 拉宽（家具会变形）")
chk("⛔ 拉宽会让家具变形 ⇒ 判据就是这条（同一段图在各处必须一样）",
    _same, "1280 宽的图重复 3 次 ⇒ 偏移相同处必然一致")
# ⭐ 阳性对照：不同偏移之间**应该**不同（否则说明整张图被抹成纯色，判据就没意义）
# ⚠️ 挑的偏移必须**真的落在不同内容上**：测试图里 x∈[0,120) 与 x∈[420,700)
#   都是"上空+ 地"两段，颜色完全相同 ⇒ 比它们必然"相同"，那是图的内容不是 bug。
#   x=200 落在"家具"上、x=640 落在空地 ⇒ 两者必然不同。
_diff = _sigs[(200, 0)] != _sigs[(640, 0)]
chk("⭐ 阳性对照：不同偏移内容**确实不同**（证明上面那条不是纯色假绿）",
    _diff, "x=200（家具上）vs x=640（空地）内容不同 ⇒ 测试图有可辨识结构")

# ------------------------------------------------------------------
# 3. 切片存在 ⇒ 走切片路径（⛔ 别删）
# ------------------------------------------------------------------
print()
print("④ ⭐ 切片**存在** ⇒ 照旧走三张切片（现有路径没被破坏）")
pm3 = _render(0.0, _slices3, _img)
c3 = _bg_pixels(pm3)
lo3, hi3 = _span(c3)
chk("能画且铺满 3840", lo3 == 0 and hi3 == N.WORLD_W - 1,
    f"非黑列范围 [{lo3}, {hi3}]")
# 三张切片用了不同 seed（10/20/30）⇒ 三个 1280 段的"地"颜色不同
def _floor_color(pm, x):
    return pm.pixelColor(x, 500).red()


_g1, _g2, _g3 = _floor_color(pm3, 640), _floor_color(pm3, 1920), _floor_color(pm3, 3200)
chk("⭐ 三段用的是**三张不同的切片**（seed 100/120/140）",
    len({_g1, _g2, _g3}) == 3, f"各段地面 R 值 {_g1} / {_g2} / {_g3}")
chk("⭐⭐ 切片在时**不会**退回平铺（⛔ 别让降级分支抢路）",
    len({_g1, _g2, _g3}) == 3,
    "若三段同色⇒ 说明走的是平铺，切片路径被降级覆盖了")

# ------------------------------------------------------------------
# 4. 边界：切片部分缺失
# ------------------------------------------------------------------
print()
print("⑤ 边界：只给 1 张切片（不齐）")
# ⚠️ 口径说明：`datas`/美术件是**三张一起到位**的，不齐属异常态。
#   现有逻辑 =「有就画、没有就留底色」⇒ 只铺 0~1280 是**预期行为**，
#   ⛔ 不是这次要修的东西（设计端只要求"切片齐"与"切片全无"两种）。
#   ⇒ 这里断言的是「**不崩+ 已有的那张画对了**」，不要求铺满。
_pmb = _render(0.0, [_slices3[0], None, None], _img)
_cmb = _bg_pixels(_pmb)
_lmb, _hmb = _span(_cmb)
chk("只有 1 张切片时能画（不抛异常）", True, f"非黑列范围 [{_lmb}, {_hmb}]")
chk("只有 1 张时铺的是它自己（地面色=seed10）", _floor_color(_pmb, 640) == 100,
    f"x=640 地面 R={_floor_color(_pmb, 640)}（期望 100）")
chk("⛔ 不齐时**不铺满 3840**（这是现有预期，⛔ 本单不改它）", _hmb == 1279,
    f"右端 {_hmb}，只覆盖第1 段 —— 不齐态等三张一起到位")

# ------------------------------------------------------------------
# 5. 兜底：无图也无切片 ⇒ 不崩
# ------------------------------------------------------------------
print()
print("⑥ 兜底：既没切片也没旧图 ⇒ 不崩（只剩底色）")
try:
    pm0 = _render(0.0, [None, None, None], None)
    c0 = _bg_pixels(pm0)
    l0, h0 = _span(c0)
    chk("⛔ 没有素材也不抛异常", True, f"非黑列范围 [{l0}, {h0}]（只有铺底色）")
except Exception as e:
    chk("⛔ 没有素材也不抛异常", False, f"{type(e).__name__}: {e}")

# ------------------------------------------------------------------
# 6. 真实素材下的行为（⛔ 用项目里真的那张图）
# ------------------------------------------------------------------
print()
print("⑦ ⭐ 用项目里**真实的** scene_bg.png 跑一遍")
_bg_path = os.path.join(HERE, "assets_game", "scene_bg.png")
if os.path.isfile(_bg_path):
    _real = QImage(_bg_path)
    pmr = _render(0.0, [None, None, None], _real)
    cr = _bg_pixels(pmr)
    lr, hr = _span(cr)
    chk("真实图能铺满 3840", lr == 0 and hr == N.WORLD_W - 1,
        f"非黑列范围 [{lr}, {hr}]，图 { _real.width()}×{_real.height()}")
    chk("真实图的宽度就是 1280（所以正好 3 段）", _real.width() == N.VW,
        f"width={_real.width()}")
else:
    chk("真实 scene_bg.png 存在", False, _bg_path)

print()
print("=" * 74)
print(f"通过 {len(OK)} / {len(OK) + len(BAD)}")
if BAD:
    print("⛔ %d 项未过：%s" % (len(BAD), "、".join(BAD)))
print("=" * 74)
sys.exit(1 if BAD else 0)
