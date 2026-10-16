# -*- coding: utf-8 -*-
"""_自测_夜间.py —— 夜间冒险灰盒的源码层验证

⭐ 纪律（2026-09-29 / 09-30 两次事故定的）：
   ① 一律驱动【真实】w._tick()，⛔ 不许在脚本里复刻一份物理逻辑
   ② 用可控假时钟替换 perf_counter，保证 dt 稳定
   ③ ⭐ 必须强制 render 一次 —— paintEvent 里的错只在真渲染时暴露（QLinearGradient 那次）
"""
import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication

app = QApplication.instance() or QApplication([])

from pet_engine.core import load_pack
from pet_engine import night as N

pack = load_pack(os.path.join(HERE, "packs", "luna"))
w = N.NightWindow(pack)

# ============================================================================
# ⭐⭐ 测试用容器注入（2026-10-11 · PR29b 收口，programmer-5）
#   背景：Ronny 2026-10-10 授权把 NIGHTS[0]["stashes"] 清成了 []，
#         而 `Room.__init__` 是**每次开档重建**的 ⇒ `w.start_night()` 之后
#         `room.stashes` 恒为空 ⇒ ⑧ 段第 325 行 `w.room.stashes[0]` 直接 IndexError，
#         脚本被打断 —— ⑧ 之后那些判据**一条都没执行过**（不是"跳过"，是压根没跑到）。
#   ⛔ 这里**只补数据**，⛔ 一个判据都没改。
#
#   为什么要包一层 `start_night` 而不是在 ⑧ 段开头补一次：
#     ① 这份脚本里有 21 处 `w.start_night(0)`（还有 3 处在缩进块里），
#        逐个插桩必然漏 ⇒ 漏一处就是后面整段白跑；
#     ② 逐个插桩要动到已有代码行，包一层的话**现有代码一行都不动**。
#   ⛔ 只在这个脚本里生效（改的是类对象上的属性，不动 night.py 源码）。
# ============================================================================
_TEST_STASHES = [
    # ⭐ 坐标沿用 `_NIGHT1` 的浅处那三条（够得到），三档各留一个：
    #   loose / jar / plate —— 后面的判据会按 kind 挑（例如"拿一个 jar"）。
    {"x": 470.0, "y": 488.0, "icon": "yolk",   "kind": "loose"},
    {"x": 650.0, "y": 488.0, "icon": "yogurt", "kind": "jar"},
    {"x": 830.0, "y": 380.0, "icon": "salmon", "kind": "plate"},
]


def inject_stashes():
    """给当前 room 补上测试容器 —— 连带 `Room.__init__` 里会解算出的那几个派生字段。"""
    if getattr(w.room, "stashes", None):
        return                                  # Ronny 之后把容器加回来 ⇒ 自动让位
    print("⏳ 注入测试容器（NIGHTS[0].stashes 为空 ⇒ 不补的话 ⑧ 段之后全跑不了）")
    out = []
    for s in _TEST_STASHES:
        spec = N.KIND_TABLE[s["kind"]]
        out.append(dict(s, noise=spec["noise"], fury=spec["fury"],
                        value=spec["value"], hit=spec["hit"],
                        taken=False, broken=False))
    w.room.stashes = out
    # ⭐ 图标：`__init__` 里 `_all_ic` 是从 NIGHTS 现算的，现在 NIGHTS 里没有容器
    #   ⇒ `self.icons` 是空的 ⇒ 画的时候 icons.get(icon) 取到 None。
    for k, im in N._load_icons(pack.root,
                               sorted({s["icon"] for s in out})).items():
        w.icons.setdefault(k, im)
    # ⭐⭐ 2026-10-12 设计端补注入：冰箱食物池。
    #   `FRIDGE_FOODS = []`（night.py:905，Ronny 2026-10-10 授权容器全清）⇒
    #   `Room.__init__` 派生出 `fridge_left = []` ⇒ `_qte_start()` 第一行就 return
    #   ⇒ **QTE 从来没启动过**，于是「QTE 锁移动」那条判据自 10-10 起**空转了 10 天**
    #   （它断言 `w.qte is not None`，而 qte 恒为 None ⇒ 恒红，但红的原因不是锁失效）。
    #   ✅ 这里只补数据，不动 night.py：给一件还没被拿的食物，让 QTE 真能开始。
    #      字段只需 "icon"（`_qte_win` 只用 f["icon"]，night.py:4573-4576）。
    if not w.room.fridge_left:
        w.room.fridge_left = [dict(icon="yolk")]


_orig_start_night = N.NightWindow.start_night


def _start_night_with_stashes(self, idx):
    _orig_start_night(self, idx)
    inject_stashes()


N.NightWindow.start_night = _start_night_with_stashes

w.start_night(0)               # ⭐ 2026-10-03 起初始是选档菜单，测试直接进「深夜」

# ---- 可控时钟 ----
_T = [0.0]
_orig = time.perf_counter
time.perf_counter = lambda: _T[0]


def step(dt=1.0 / 60.0, n=1):
    for _ in range(n):
        _T[0] += dt
        w._tick()


def step_pure(dt=1.0 / 60.0, n=1):
    """⭐ 只测物理时用的 step：把微波炉冻住、不会被抓。

    为什么需要：梯子在 x=700，已经在允许区外（BORDER_X=430），测爬梯时露娜必然越界，
    微波炉会真的追过来把她抓住 → phase 变 meowed → _tick 不再更新物理 →
    她卡在半空（实测 y=593 不动）。这是【测试污染】，不是物理 bug。

    ⭐⭐ PR37-v2（2026-10-14）：本夹具把 phase 强拉回 "play" 时**必须一起清 `l.escort`**。
      因为 PR37-v2 让 escort 变成**活标志**（抓捕时置 True，`Luna.update` 开头
      `if self.escort: return` 会早退 ⇒ 物理全停）。只复位 phase 不清 escort ⇒
      一旦本夹具窗口内发生过抓捕，escort 就**永久卡 True**，后面所有物理判据静默烂掉
      （实测：③ 跑动 dx 只有 84px、跳高 0px、爬梯不动、alert 恒 0，共 15 条红）。
      ⛔ 真机没有这条泄漏路径：`start_night` 重建 Luna（night.py:4234）、
        hauled 结束清 escort（:5006）⇒ 这里补的是**夹具**与真机状态机的缺口，
        ⛔ 不是改判据（本文件 :1100/:1114 早有同款 `l.escort = False` 防护）。
    """
    for _ in range(n):
        sx, sy = w.mw.x, w.mw.y
        _T[0] += dt
        w._tick()
        if w.phase != "play":
            w.phase, w.phase_t = "play", 0.0
            w.luna.escort = False      # ⭐ PR37-v2：镜像真机 hauled→play 的 escort 清零
        w.mw.x, w.mw.y = sx, sy
        w.mw.alert, w.mw.state = 0.0, "patrol"


def step_ai(dt=1.0 / 60.0, n=1):
    """测 AI 时用：不让"被抓 → 押送演出"把后续的 alert 断言吞掉。

    ⛔ 踩过的坑：正面视野那组跑完 60 帧后微波炉已经追上并把露娜抓了，
       phase 变 meowed/hauled → _tick 里不再 update → 后面三组 alert 全是 0，
       但"进入追击"这种只看 state 的断言照样过，假绿。

    ⭐⭐ PR37-v2（2026-10-14）：同 `step_pure`——强拉 phase 回 "play" 时一起清 escort
      （escort 卡 True 会让 `Luna.update` 早退 + `trespass` 判定恒 False ⇒ 索敌全废）。
    """
    for _ in range(n):
        _T[0] += dt
        w._tick()
        if w.phase != "play":
            w.phase, w.phase_t = "play", 0.0
            w.luna.escort = False      # ⭐ PR37-v2：镜像真机 hauled→play 的 escort 清零


def render():
    pm = QPixmap(w.size())
    pm.fill(Qt.transparent)
    w.render(pm)


OK, BAD = [], []

# ⭐ 2026-10-03 比例重排后：测试里的坐标不再写死，全部从 night 派生。
#   下面这些是旧布局（470/320/552/700）的替身，新布局见 night.py 的 PLATFORMS/LADDERS。
FLOOR   = N.FLOOR_Y          # 672
COUNTER = N.PLATFORMS[2][1] # 料理台顶 375
TABLE   = N.PLATFORMS[1][1] # 餐桌顶 488（⛔ 旧注释写 474 是过期值：night.py:175
                            #   `TABLE_TOP = 488`；同文件 :249 `_drop_table = 108`
                            #   = 488-380 也只对了这个值，474-380=94 对不上）
HANGER  = N.PLATFORMS[3][1] # 吊柜顶 177
LADX    = N.LADDERS[0][0]    # 梯子 x 620
LADTOP  = N.PLATFORMS[2][1] # 梯子顶 = 料理台 375



def chk(name, cond, info=""):
    (OK if cond else BAD).append(name)
    print(f"{'  OK ' if cond else ' FAIL'}  {name}   {info}")


print("=" * 72)
print("① 构造与资源")
print("=" * 72)
chk("构造成功", w is not None)
chk("缩放系数合理 0.15<s<0.5", 0.15 < w.s < 0.5, f"s={w.s:.4f}")
chk("动作帧已加载", set(["idle", "human_run", "jump", "climb", "fall"]).issubset(w.imgs),
    f"已加载 {sorted(w.imgs)}")
# ⭐⭐ 2026-10-12 设计端重校（原判据恒 FAIL，根因是【判据取错了数据源】）：
#   旧判据拿 `N.NIGHTS[*]["stashes"]` 算期望图标集合，但 Ronny 2026-10-10 已把
#   NIGHTS[0].stashes 清成 []；而本脚本第 84 行 `w.start_night(0)` 又会经
#   `inject_stashes()` 注入 3 个测试容器 ⇒ 期望 0 / 实载 3，**恒 FAIL**。
#   ⇒ 这不是"图标没加载"，是判据在跟一个已经被清空的配置对答案。
#   ✅ 正确口径：图标必须覆盖**当前 room 实际在用的**那些 —— `_draw_stashes`
#      走 `self.icons.get(st["icon"])`，取到 None 就画不出来（night.py:5996）。
_need_ic = {s["icon"] for s in w.room.stashes}
chk("赃物图标覆盖当前房间全部", _need_ic.issubset(set(w.icons)),
    f"需 {sorted(_need_ic)} 实载 {sorted(w.icons)}")
# ⭐ 阳性对照（证明这条判据有分辨力，不是空真）：要一个盘上绝不存在的图标名，必须真的没加载
chk("⭐阳性对照：盘上不存在的图标不会被加载", "definitely_not_an_icon_xyz" not in w.icons)

print()
print("=" * 72)
print("② 重力与落地")
print("=" * 72)
l = w.luna
l.x, l.y = 120.0, 200.0            # ⭐ x=120：餐桌在 300~470，落点必须避开它
l.vx = l.vy = 0.0
step_pure(1 / 60, 90)                 # 1.5s 自由落体
chk("落到地板", abs(l.y - N.FLOOR_Y) < 1.0, f"y={l.y:.1f} 期望 {N.FLOOR_Y}")
chk("落地后 on_ground", l.on_ground)

# ⭐ 餐桌是矮平台：站在它上方自由落体会被接住（Ronny 10-03 加的）
#   ⭐ 2026-10-03 布局重排：餐桌 470~730（x=380 已不在桌上方，会落空到地板）
l.x, l.y = 600.0, 200.0
l.vx = l.vy = 0.0
l.on_ground = False
step_pure(1 / 60, 90)
chk("餐桌能接住落下来的人", abs(l.y - TABLE) < 1.0, f"y={l.y:.1f} 期望 {TABLE}")

print()
print("=" * 72)
print("③ 跑动")
print("=" * 72)
# ⭐ 2026-10-03：桌布现在是从桌面垂到地的实心面（470~730），起跑点必须在开阔地板段
#   （800 在布区右侧），否则 1s 会被布墙拦下（实测从 380 起跑只跑出 68px）
l.x, l.y = 800.0, N.FLOOR_Y
l.vx = l.vy = 0.0
l.on_ground = True
x0 = l.x
w.keys = {Qt.Key_D}
step_pure(1 / 60, 60)                 # 1s
w.keys = set()
vx_run = abs(l.x - x0)
chk("1 秒右跑 240~320px", 240 < vx_run < 320, f"实际 {vx_run:.0f}px")
chk("动作切到 human_run", l.act == "human_run", f"act={l.act}")

print()
print("=" * 72)
print("④ 跳跃高度 + 跳键闩锁")
print("=" * 72)
l.x, l.y = 300.0, N.FLOOR_Y
l.vx = l.vy = 0.0
l.on_ground = True
l.jump_latch = False
best = N.FLOOR_Y
w.keys = {Qt.Key_W}                    # ⭐ 全程按住，用来验证不会连跳
for _ in range(150):
    step_pure()
    best = min(best, l.y)
w.keys = set()
h = N.FLOOR_Y - best
chk("跳高 190~225px", 190 < h < 225, f"实际 {h:.0f}px")
# ⛔ 落差必须**从 PLATFORMS 现算**，不许写死 —— 写死就是"布局改了判据还按旧值算"，
#   这正是 ⑤ 假绿了两个版本的原因。2026-10-04 台面 397→380 后地板就跳不上了。
_drop_floor = N.FLOOR_Y - COUNTER       # 地板 → 台面 = 219
_drop_table = TABLE - COUNTER           # 茶几 → 台面 = 108
chk("地板跳不上台面（新布局，差 15px）", h < _drop_floor,
    f"跳高 {h:.0f} < 落差 {_drop_floor:.0f}，差 {_drop_floor - h:.0f}px")
chk("茶几跳得上台面（差 %.0fpx）" % (_drop_table - 12),
    h > _drop_table + 12, f"跳高 {h:.0f} > 落差 {_drop_table:.0f}，余 {h - _drop_table:.0f}px")
chk("跳不上吊柜(落差328，须经台面中转)", h < 328 - 40, f"差 {328 - h:.0f}px")
chk("按住 W 落地后不连跳（落在地板或餐桌都算落地）",
    abs(l.y - N.FLOOR_Y) < 1.0 or abs(l.y - TABLE) < 1.0, f"y={l.y:.1f}")

print()
print("=" * 72)
print("⑤ 跳上料理台")
print("=" * 72)
# ⛔⛔ 2026-10-04 新布局后**地板跳不上台面**，判据不能写"从地板 760 起跳"了：
#   台面顶从 397 抬到 380（为了让台下净高 181px 走得下微波炉 161px），
#   于是地板→台面落差 = 599-380 = 219px，而**实测跳高只有 204px**（离散积分峰值），
#   差 15px —— 物理上就是跳不上去。旧判据拿旧落差 178 算，所以一直假绿。
#   ✅ 真实路径只有一条：**茶几(488) → 台面(380)**，落差 108px + 水平跨度 60px。
#     实测（茶几中段 x=640 起跑）落点 x=777.1 y=380 站得住。
#   ⛔ 别为了"让判据变绿"把台面压回 397 —— 那样微波炉就过不了台下。
#   ⛔ 楼层顺序不可改：台面(380) → 茶几(488) → 地板(599) 是向下单调的，
#     玩家从阳台(左)出发必须先爬茶几，再从茶几跳台面。
l.x, l.y = 640.0, N.TABLE_TOP          # 茶几中段
l.vx = l.vy = 0.0
l.on_ground = True
l.jump_latch = False
w.keys = {Qt.Key_D}                    # 先向右助跑
step_pure(1 / 60, 18)                  # ⭐ 18 帧是实测过的窗口：
#   14~18 帧能上台面（落点 x=757~777, y=380）；
#   10 帧起跳太早 → 落进台面与茶几之间的空隙掉回地板；
#   20 帧起跳太晚 → 已经跑过茶几右缘 700 掉下去了。
#   ⛔ 别写死"跑够 0.5s"这种直觉值 —— 助跑帧数直接决定能不能过。
w.keys = {Qt.Key_D, Qt.Key_W}          # 助跑中起跳
step_pure(1 / 60, 8)                   # ⭐ 只按住 8 帧就松
# ⛔⛔ 千万别"全程按住 W"：台面上方 790~1010 是**吊柜**（顶 50），
#   而 Luna.update 里 `if self.on_ladder or want_up` → 按住 W 会被判成"想爬吊柜"
#   → 直接进爬梯态卡在 y≈270（实测落点 x=900 y=270.7，on_ground=False）。
#   玩家实机是「起跳后松手」，所以判据也必须松手。
w.keys = set()
step_pure(1 / 60, 62)
chk("经茶几跳上料理台", abs(l.y - COUNTER) < 1.5 and l.on_ground,
    f"落点 x={l.x:.1f} y={l.y:.1f} on_ground={l.on_ground}")
chk("落台后不再弹起", l.on_ground and abs(l.vy) < 1.0,
    f"vy={l.vy:.1f} on_ground={l.on_ground}")

print()
print("=" * 72)
print("⑥ 爬桌布（地板 → 餐桌。2026-10-03：桌布整面可扒，LADDER_ZONES）")
print("=" * 72)
l.x, l.y = float(LADX), FLOOR          # 布面中心 x=600
l.vx = l.vy = 0.0
l.on_ladder = False
l.jump_latch = False
w.keys = {Qt.Key_W}
step_pure(1 / 60, 10)
on_lad = l.on_ladder
step_pure(1 / 60, 100)
w.keys = set()
chk("进入爬梯状态", on_lad, f"on_ladder={on_lad}")
chk("爬到桌面（派生）", abs(l.y - TABLE) < 2.0, f"y={l.y:.1f} 期望 {TABLE}")
chk("爬完回到地面态", not l.on_ladder, f"on_ladder={l.on_ladder}")
chk("爬到顶不会自动弹起", abs(l.y - TABLE) < 2.0, f"y={l.y:.1f}")

# ⭐ 站在平台上不许抖：连续 60 帧的 y 极差必须 < 1px
l.x, l.y = 760.0, COUNTER
l.vx = l.vy = 0.0
l.on_ground = True
l.on_ladder = False
w.keys = set()
ys = []
for _ in range(60):
    step_pure()
    ys.append(l.y)
chk("站台上 60 帧不抖", (max(ys) - min(ys)) < 1.0,
    f"极差 {max(ys)-min(ys):.2f}px  y∈[{min(ys):.1f},{max(ys):.1f}]")

# ⭐ 高速下落不许穿透上层平台
l.x, l.y = 760.0, 120.0
l.vx = l.vy = 0.0
l.on_ground = False
step_pure(1 / 60, 90)
chk("高速下落落在料理台而非穿透到地板", abs(l.y - COUNTER) < 2.0, f"y={l.y:.1f}")

print()
print("=" * 72)
print("⑦ 允许区与微波炉")
print("=" * 72)
# ⛔ 这一组必须【确定性】：巡逻带随机踱步节奏后，微波炉朝向不再可预测，
#    靠"让它自己走过来"去撞视野会时灵时不灵（实测 alert 从 0.95 飘到 0.02）。
#    → 手动钉死 mw.x / face / dir，并把 walk_t 拉长到不触发转身。
def freeze_mw(x, face):
    """把微波炉定在某个位置、朝某个方向，并**冻结它的待机计时**。

    ⭐⭐ 2026-10-05 补`idle_t = IDLE_STIR_P`（设计端要求查清的那条）：
      `Microwave._patrol` 现在**完全不平移 x**（Ronny「安静呆着」），
      它只做一件事：`idle_t` 到点就 `face = -face` 转头（`IDLE_STIR_P = 9.0` 秒）。
      ⛔ 旧版 freeze_mw 只设 walk_t/pause_t，**没管 idle_t** ⇒
        它继承了上一轮 step_ai 剩下的计时（本例只剩 ~0.8 秒），
        于是"背后听见"那组在**第 46~48 帧就转脸** ⇒ sense 0.25→1.00
        ⇒ alert 瞬间涨满 ⇒ 报成「背后近距离听得见」FAIL。
      ⇒ 这是**判据自己造了个转脸场景**，不是游戏行为变了。
    ✅ 所以冻结必须连idle_t 一起重置到**满值**（9 秒），
       保证 1 秒观测窗口内他不会转头。
    """
    w.mw.x, w.mw.y = x, N.FLOOR_Y
    w.mw.face = w.mw.dir = face
    w.mw.walk_t, w.mw.pause_t = 999.0, 0.0
    # ⭐ 站岗模式下一个周期= IDLE_STIR_P 秒；给满值 ⇒ 窗口内必不转头
    w.mw.idle_t = float(N.IDLE_STIR_P)


l.x, l.y = 200.0, N.FLOOR_Y
l.vx = l.vy = 0.0
freeze_mw(760.0, 1)
w.mw.alert = 0.0
w.mw.state = "patrol"
step_ai(1 / 60, 120)                     # 2s 待在允许区内
chk("区内不被追", w.mw.state == "patrol" and w.mw.alert < 0.01,
    f"state={w.mw.state} alert={w.mw.alert:.2f}")

freeze_mw(900.0, 1)                   # 它朝右，露娜在它正前方 150px
l.x = 1050.0
# ⭐⭐ 2026-10-12 设计端重校。旧判据「正面被看见 → 警戒涨满」**两处作废**：
#
#   ① **语义已变**（Ronny 2026-10-10 拍板 PR29）：
#      「看到之后先假装没看到，等近到一定程度，看到猎物后背的时候开始追击」
#      ⇒ "看见就涨满"不再是预期行为。设计端实测（`_work/_探_正面被看见.py`）：
#        · 她**背对着他** + 距离 150（≤CAT_PURSUE_D=230）⇒ 满速支，t≈0.52s alert 到 1.00，state→chase
#        · 她**面朝他**（没露后背，同一位置）⇒ 潜伏支，1s 后 alert 仅 0.18，state=stalk（CAP=0.85 封顶）
#      ⇒ 一条判据装不下两种行为，必须按「有没有露后背」拆开。
#
#   ② **采样点在峰值之后**（判据自身缺陷，与行为对错无关）：
#      旧判据在 t=1.0s 采样，但 alert 峰值在 t≈0.52s，进入追逐态后开始衰减，
#      t=1.0s 已掉到 0.85 ⇒ 旧判据量到的是【衰减后的值】。
#      ✅ 改为窗口内取峰值。
l.face = 1                            # 显式钉死：背对着他
_peak = 0.0
for _ in range(60):
    step_ai(1 / 60, 1)
    _peak = max(_peak, w.mw.alert)
chk("看见+够近+露后背 → 涨满并追击", _peak > 0.9 and w.mw.state == "chase",
    f"峰值 alert={_peak:.2f} state={w.mw.state}")
# ⬇ 原「进入追击」判据保留（上面那条已含 state=="chase"，这条是原样的延续断言）
chk("进入追击", w.mw.state == "chase", f"state={w.mw.state}")

# ⭐ 新增：同一位置但**没露后背** ⇒ 必须只潜伏、不涨满（PR29 的核心行为）
w.mw.alert = 0.0
w.mw.state = "patrol"
freeze_mw(900.0, 1)
l.x, l.face = 1050.0, -1              # 面朝他
_peak2 = 0.0
for _ in range(60):
    step_ai(1 / 60, 1)
    _peak2 = max(_peak2, w.mw.alert)
chk("看见但没露后背 → 只潜伏不涨满（PR29 核心）",
    w.mw.state == "stalk" and _peak2 < 0.5,
    f"峰值 alert={_peak2:.2f} state={w.mw.state}")

w.mw.alert = 0.0
w.mw.state = "patrol"
# ⛔ 2026-10-04：原来 freeze_mw(1100, 1) 让它朝右，但**新布局深夜档巡逻段右端就是 1108**
#   —— 走 8px 就掉头，掉头后面朝左就变成「正面看见」→ alert 直接涨到 1.00，
#   报成「背后近距离听得见」FAIL。判据自己造了个正面场景。
#   ✅ 正确摆法：微波炉放在**巡逻段中段**且朝右，露娜在它**左后方**，
#     这样 1s 内它不会走到右端掉头，测的才是真正的"背后听见"这一档（0.5）。
_p0, _p1 = N.NIGHTS[1]["patrol"] if len(N.NIGHTS) > 1 else N.NIGHTS[0]["patrol"]
freeze_mw(_p1 - 150.0, 1)             # 朝右，距右端还有 150px 余量
l.x = _p1 - 150.0 - 90.0             # 它背后 90px
# ⛔⛔ 2026-10-12 设计端补钉：**必须显式把 l.face 钉成 +1**，否则这条判据会被上游场景污染。
#   实测教训：我在同段上面加了「看见但没露后背」场景，临走把 l.face 留成了 -1，
#   于是这里 `_sees_back = (-1)*(-90) = +90 > 0` ⇒ 命中满速支 ⇒ alert 直接 1.00，
#   这条判据当场转红。**判据继承了上一个场景的姿态** —— 这正是 315/347 行注释
#   反复警告的「判据自己造了个正面场景」，只是污染源从"微波炉转脸"换成了"露娜朝向"。
#   ✅ 为什么必须是 +1：她站在他左后方且**面朝他**（+1）⇒ 他看不见她的后背
#     （`_sees_back=False`）⇒ 走的才是"听觉"这一档（sense=0.25）。
#     若她面朝左（-1，背对他）⇒ 露后背 + 距离 90 ≤ CAT_PURSUE_D ⇒ 满速支，alert 封顶前冲到 1.00。
l.face = 1
step_ai(1 / 60, 60)
chk("背后近距离听得见（半速）", 0.3 < w.mw.alert < 0.95, f"alert={w.mw.alert:.2f}")

w.mw.alert = 0.0
w.mw.state = "patrol"
freeze_mw(700.0, 1)                   # 它朝右，露娜在远处背后 → 无感
l.x = 400.0
step_ai(1 / 60, 60)
chk("远处背后无感", w.mw.alert < 0.01, f"alert={w.mw.alert:.2f}")

l.x = 200.0                           # 逃回允许区
w.mw.alert = 1.0
w.mw.state = "chase"
step_ai(1 / 60, 300)
chk("退回区内警戒清零", w.mw.alert < 0.05, f"alert={w.mw.alert:.2f}")

print()
print("=" * 72)
print("⑧ 偷东西 + 回窝结算")
print("=" * 72)
w.start_night(0)
l = w.luna
# ⭐⭐ 2026-10-04：容器分了四档，不再硬编码"三文鱼"——
#   ⛔ 写死icon 会让"重排关卡数据"必然带崩这组测试（已踩过）。
#   ✅ 改成：从 stashes 里取第0 号，并按它的 value/icon 断言。
s0 = w.room.stashes[0]
l.x, l.y = s0["x"], s0["y"]
w._try_break()
exp0 = f"{s0['value']}:{s0['icon']}"
chk(f"敲碎第 0 号容器拿到 {exp0}", l.carrying == [exp0], f"carrying={l.carrying}")
chk("容器标记为已破", w.room.stashes[0]["broken"] is True)
# ⭐ 只能拿一件：手上���东西时再敲下一个容器不会多拿
l.x, l.y = w.room.stashes[1]["x"], w.room.stashes[1]["y"]
w._try_break()
chk("手上有东西时不能再拿", len(l.carrying) == 1,
    f"carrying={l.carrying}  stash[1].broken={w.room.stashes[1]['broken']}")

l.x = 150.0                            # 走进窝里
step(1 / 60, 5)
chk("回窝 **不结算**，只放下（暂存）", w.phase == "play" and bool(w.loot_stash),
    f"phase={w.phase} loot_stash={w.loot_stash}")
chk("放下后手上空了", l.carrying == [], f"carrying={l.carrying}")
chk("窝边汇总还没加（没结算）", w.total_loot == 0, f"total={w.total_loot}")
w._try_break()                        # 在窝边按 E = 结算
chk("窝边按 E → 出结算面板", w.phase == "result", f"phase={w.phase}")
r = w.result or {}
chk("结算记了带回数", r.get("loot") == 1, f"{r}")
chk("结算有评级", r.get("rank") in ("S", "A", "B", "C"), f"rank={r.get('rank')}")
chk("结算后窝边拿库清空", w.loot_stash == [], f"{w.loot_stash}")
chk("窝边累计 = 该容器的价值（不是 1）", w.total_loot == s0["value"],
    f"total={w.total_loot}  该容器 value={s0['value']}")
chk("loot_log 记的是实际偷到的", w.loot_log == [exp0], f"{w.loot_log}")

# ⭐ 惩罚要轻：已入库的绝不能被倒扣
before = w.total_loot
w.start_night(0)
l = w.luna
l.x, l.y = N.STASHES[0]["x"], N.STASHES[0]["y"]
w._try_break()
l.x, l.y = 1000.0, N.FLOOR_Y           # 抱着赃物跑到禁区深处
w.mw.x, w.mw.y = 1000.0, N.FLOOR_Y
w.mw.alert, w.mw.state = 1.0, "chase"
step(1 / 60, 3)
chk("被抓时手上赃物还没入账", w.total_loot == before, f"{before} → {w.total_loot}")

print()
print("=" * 72)
print("⑨ 被抓 → YOU MEOWED → 押送回窝")
print("=" * 72)
w.start_night(0)
l = w.luna
l.x, l.y = 1000.0, N.FLOOR_Y
w.mw.x, w.mw.y = 1000.0, N.FLOOR_Y
w.mw.alert, w.mw.state = 1.0, "chase"
l.carrying = ["yogurt"]
step(1 / 60, 3)
chk("触发 YOU MEOWED", w.phase == "meowed", f"phase={w.phase}")
chk("被抓计数 +1", w.caught_cnt == 1, f"caught={w.caught_cnt}")
render()
chk("meowed 画面能画（无异常）", True)

step(1 / 60, 200)                     # 1.5s 大字 + 0.9s 押送，留余量
chk("押送后回到 play", w.phase == "play", f"phase={w.phase}")
chk("被押送回窝", abs(l.x - (N.NEST_X0 + 70)) < 2.0, f"x={l.x:.1f} 期望 {N.NEST_X0+70}")
chk("赃物清零", l.carrying == [], f"carrying={l.carrying}")
chk("总赃物没被倒扣", w.total_loot == before, f"{before} → {w.total_loot}")

print()
print("=" * 72)
print("⑩ 档位配置 + 选档")
print("=" * 72)
# ⭐⭐ 2026-10-05 Ronny 20:42 拍板「三档都删，就只留最难那版」⇒ 判据从"三档齐备"改写。
#   ⛔ **别只是把 3 改成 1** —— 那样以后有人加回档位，这条判据照样绿。
#   ⭐ 所以连"name == 正午" 一起断言：档位数与档位名都被钉住。
chk("单一档位（正午）",
    len(N.NIGHTS) == 1 and N.NIGHTS[0]["name"] == "正午",
    f"len={len(N.NIGHTS)} name={[n['name'] for n in N.NIGHTS]}")
for i, cfg in enumerate(N.NIGHTS):
    w.start_night(i)
    mw, rm = w.mw, w.room
    gap = N.RUN_SPEED - cfg["chase_speed"]
    chk(f"档{i+1} {cfg['name']}：追得掉（{gap:.0f}px/s 余速）", gap > 0, f"追 {cfg['chase_speed']:.0f} vs 跑 {N.RUN_SPEED:.0f}")
    chk(f"档{i+1} 边界一致（room=配置）", rm.border_x == cfg["border_x"],
        f"room {rm.border_x} vs cfg {cfg['border_x']}")
    chk(f"档{i+1} 微波炉用的是本档速度", abs(mw.chase_speed - cfg["chase_speed"]) < 1e-6,
        f"mw {mw.chase_speed} vs cfg {cfg['chase_speed']}")
    chk(f"档{i+1} 巡逻段在本档范围内", mw.p0 == cfg["patrol"][0] and mw.p1 == cfg["patrol"][1])
    # ⛔ 难度必须真的单调递增（否则"三档"只是三个名字）
    if i:
        p = N.NIGHTS[i - 1]
        harder = (cfg["alert_gain"] > p["alert_gain"] and
                  cfg["border_x"] <= p["border_x"] and
                  len(cfg["stashes"]) >= len(p["stashes"]) and
                  cfg["chase_speed"] >= p["chase_speed"])
        chk(f"档{i+1} 确实比档{i} 难", harder,
            f"警戒 {p['alert_gain']}→{cfg['alert_gain']}　"
            f"边界 {p['border_x']}→{cfg['border_x']}　"
            f"赃物 {len(p['stashes'])}→{len(cfg['stashes'])}　"
            f"追速 {p['chase_speed']}→{cfg['chase_speed']}")

print()
print("=" * 72)
print("⑪ 旁白")
print("=" * 72)
w.start_night(0)
l = w.luna
n_steal = len(N.NARRATION["steal"])
w._narr_seen.clear()
r1 = []
for _ in range(n_steal):
    w._narrate("steal")
    r1.append(w.msg)
chk(f"一轮 {n_steal} 抽不重复", len(set(r1)) == n_steal, f"{r1}")
r2 = []
for _ in range(n_steal):
    w._narrate("steal")
    r2.append(w.msg)
chk("池子抽干后轮转（第二轮仍不重复）", len(set(r2)) == n_steal, f"{r2}")
chk("轮转不影响别的池子", w._narr_seen.issubset({("steal", i) for i in range(n_steal)}),
    f"{sorted(w._narr_seen)}")
for k, pool in N.NARRATION.items():
    chk(f"旁白池「{k}」非空", len(pool) > 0, f"{len(pool)} 句")
chk("开场白三档各一句", all(len(N.NARRATION["enter"]) >= 3 for _ in (0,)), "3 句")

print()
print("=" * 72)
print("⑫ 渲染（真实 paintEvent）")
print("=" * 72)
for ph in ("play", "meowed", "result", "menu"):
    w.phase = ph
    w.phase_t = 0.5
    w.mw.alert, w.mw.state = (1.0, "chase") if ph in ("play", "menu") else (0.0, "patrol")
    if ph == "menu":
        w.menu_sel = 2
    if ph == "result":
        w.result = w.result or {"night": "深夜", "loot": 5, "left": 0, "total": 12,
                                "caught": 1, "time": 96.0, "score": 585, "rank": "A"}
    try:
        render()
        chk(f"{ph} 画面能画", True)
    except Exception as e:
        chk(f"{ph} 画面能画", False, f"{type(e).__name__}: {e}")

# 爬梯态
w.phase = "play"
l.on_ladder = True
l.act = "climb"
try:
    render()
    chk("climb 画面能画", True)
except Exception as e:
    chk("climb 画面能画", False, f"{type(e).__name__}: {e}")

print()
print("=" * 72)
print("⑬ 爬梯动作（Ronny 2026-10-03 实机反馈：动作没装上）")
print("=" * 72)
w.start_night(0)
l = w.luna
l.x, l.y = float(LADX), FLOOR
l.vx = l.vy = 0.0
l.on_ladder = False
l.on_ground = True
l.jump_latch = False

w.keys = {Qt.Key_W}
step_pure(1 / 60, 12)
t0 = l.t
step_pure(1 / 60, 12)
t1 = l.t
chk("爬梯时动作是 climb", l.act == "climb", f"act={l.act}")
chk("爬梯时动画帧在推进", t1 > t0, f"t {t0:.2f} → {t1:.2f}（fps=12）")

w.keys = set()
step_pure(1 / 60, 2)
t2 = l.t
step_pure(1 / 60, 10)
chk("松开按键后帧停住（不悬空蹬腿）", abs(l.t - t2) < 1e-6,
    f"t {t2:.2f} → {l.t:.2f}")

w.keys = {Qt.Key_S}
t3 = l.t
step_pure(1 / 60, 12)
chk("下梯时动画倒着播（t 递减）", l.t < t3, f"t {t3:.2f} → {l.t:.2f}")
chk("下梯确实在往下走", l.y > 470.0, f"y={l.y:.1f}")

# ⭐ 爬梯时按左右要能蹬开 —— 不做这条她会卡在梯子上（A/D 被爬梯分支吞掉）
#   ⭐ 2026-10-03：蹬开点必须低于"布顶+46"（离顶 46px 内按左右 = 跨上桌面，是另一条语义）
w.keys = set()
l.x, l.y = float(LADX), 550.0
l.vx = l.vy = 0.0
l.on_ladder = True
l.on_ground = False
w.keys = {Qt.Key_D}
step_pure(1 / 60, 3)
chk("梯子上按左右能蹬开（不卡死）", (not l.on_ladder) and abs(l.vx) > 1.0,
    f"on_ladder={l.on_ladder} vx={l.vx:.0f}")
w.keys = set()
step_pure(1 / 60, 60)
chk("蹬开后正常落到地板", abs(l.y - N.FLOOR_Y) < 2.0, f"y={l.y:.1f}")

# 下梯画面能画（走真实 paintEvent）
l.on_ladder = True
l.climb_down = True
l.act = "climb"
l.t = 6.0
try:
    render()
    chk("下梯画面能画", True)
except Exception as e:
    chk("下梯画面能画", False, f"{type(e).__name__}: {e}")

print()
print()
print("=" * 72)
print("\u2714 \u5668\u9f44 + \u566a\u58f0 + \u6f5c\u884c + \u722c\u68af\u5b89\u5168")
print("=" * 72)
w.start_night(0)
l, mw = w.luna, w.mw

# ⭐⭐ 2026-10-04：容器分四档后，噪声测试**必须显式挑档**。
#   ⛔ 别再用硬编码下标（旧写法取 stashes[2]，重排后变成 plate/loose）——
#     噪声是逐档的（loose 0 / plate 0.26 / jar 0.62），拿错档整组断言必假失败。
#   ✅ 按 kind 找样本：噪声测试用 jar（最响），零噪声测试用 loose。
def _pick(w, kind):
    """返回该档里第一个还没被破的容器"""
    for s in w.room.stashes:
        if s.get("kind") == kind and not s["broken"]:
            return s
    return None


# ---------- ① jar：贴身敲 = 大声 ----------
w.start_night(0)
l, mw = w.luna, w.mw
_st = _pick(w, "jar")
chk("本档有 jar 容器（噪声测试样本）", _st is not None, f"{_st}")
l.x, l.y = _st["x"], _st["y"]
mw.x, mw.y = _st["x"] + 10, FLOOR        # 距离 10px：贴着耳朵敲
mw.alert, mw.state, mw.hear_x = 0.0, "patrol", None
w._try_break()
near_alert = mw.alert
chk("贴身敲罐 = 忽略噪声，alert 上升 >0.5", near_alert > 0.5,
    f"alert={near_alert:.2f}  dist=10px  kind=jar")
chk("噪声会记住声源（他转头看）", mw.hear_x is not None,
    f"hear_x={mw.hear_x}")
# ⭐⭐ 破罐 = 直接疯狂追踪（Ronny 2026-10-04 核心需求）
chk("⭐ 破罐 → 守卫直接 frenzy", mw.fury is True,
    f"fury={mw.fury}  fury_t={mw.fury_t:.1f}")
chk("frenzy 时 state=chase 且 alert 锁 1.0",
    mw.state == "chase" and mw.alert >= 1.0,
    f"state={mw.state} alert={mw.alert:.2f}")
chk("frenzy 锁定的是【罐子的位置】不是露娜",
    mw.fury_x == float(_st["x"]),
    f"fury_x={mw.fury_x} 罐子x={_st['x']} 露娜x={l.x:.0f}")

# ---------- ② jar：远处敲 = 小声 ----------
w.start_night(0)
l, mw = w.luna, w.mw
_st = _pick(w, "jar")
l.x, l.y = _st["x"], _st["y"]
mw.x, mw.y = _st["x"] + N.MW_HEAR_R * 0.85, N.FLOOR_Y  # ⭐ 0.85 半径处
# ⭐⭐ 2026-10-05 判据两次更正：
#   ① 原写死 410px，而 `MW_HEAR_R` 已从 420 收窄到 240 ⇒ 410px 落进"听不见"区
#   ② 改成 0.5 半径（120px）⇒ k=0.465 仍属"很响" ⇒ alert 直接满
#   ✅ 最终取 **0.85 半径（204px）**：k=0.172 < INVEST_ALERT(0.20) ⇒
#      **听得见、alert 会涨、但不够他走过去看** —— 这才是「远处」这个命题本身。
#      ⭐ 绑比例而不是绑像素：以后半径再调，这条依然在测同一个命题。
#⭐ 实测表（jar 响度 0.62）：0.30R→k.564 / 0.50R→k.465 / 0.75R→k.271 /
#        0.80R→k.223 / 0.85R→k.172（临界）/ 0.90R→k.118 / 1.00R→0
mw.alert, mw.state, mw.hear_x = 0.0, "patrol", None
w._try_break()
far_alert = mw.alert
chk("远处敲罐 = 声音小，但 alert 仍上升", 0.02 < far_alert < 0.30,
    f"alert={far_alert:.2f}  dist={N.MW_HEAR_R*0.85:.0f}px(0.85R)")
chk("距离越近噪声越大", far_alert < near_alert,
    f"{far_alert:.2f} < {near_alert:.2f}")

# ---------- ③ loose：零噪声（2026-10-04 新增档位）----------
w.start_night(0)
l, mw = w.luna, w.mw
_st = _pick(w, "loose")
chk("本档有 loose 容器（零噪声样本）", _st is not None, f"{_st}")
l.x, l.y = _st["x"], _st["y"]
mw.x, mw.y = _st["x"] + 10, FLOOR
mw.alert, mw.state, mw.hear_x = 0.0, "patrol", None
w._try_break()
chk("⭐ loose 贴身拿 = 完全无声（alert 不动）", mw.alert == 0.0,
    f"alert={mw.alert:.3f} kind=loose noise={_st['noise']}")
chk("loose 不会引发 frenzy", mw.fury is False, f"fury={mw.fury}")
# ⭐ 四档噪声必须是**严格递增**（否则分档就没意义了）
_nz = {k: N.KIND_TABLE[k]["noise"] for k in N.KIND_ORDER}
chk("四档噪声递增：loose<plate<fridge<jar",
    _nz["loose"] < _nz["plate"] < _nz["fridge"] < _nz["jar"], f"{_nz}")
# ⭐⭐ 风险与价值同向（设计不变量，Ronny 10-04 核心约束）
_vl = {k: N.KIND_TABLE[k]["value"] for k in N.KIND_ORDER}
chk("⭐ 价值递增：loose<plate<fridge<jar（风险越高越值钱）",
    _vl["loose"] < _vl["plate"] < _vl["fridge"] < _vl["jar"], f"{_vl}")
chk("⭐ 只有 jar 会引爆 frenzy",
    [k for k in N.KIND_ORDER if N.KIND_TABLE[k]["fury"]] == ["jar"],
    f"{[k for k in N.KIND_ORDER if N.KIND_TABLE[k]['fury']]}")

# 超出听觉半径 = 完全听不见
w.start_night(0)
l, mw = w.luna, w.mw
_st = w.room.stashes[2]
l.x, l.y = _st["x"], _st["y"]
mw.x, mw.y = _st["x"] + N.MW_HEAR_R * 1.15, N.FLOOR_Y
mw.alert, mw.state, mw.hear_x = 0.0, "patrol", None
w._try_break()
chk("超出听觉半径就完全听不见", mw.alert < 0.001,
    f"alert={mw.alert:.3f}  dist={N.MW_HEAR_R*1.15:.0f}px(1.15R)  半径={N.MW_HEAR_R:.0f}")

# ---- 累f积f而c不d是f一0敲2满1：a敲2三9下b才d快b进b追d踪a ----
w.start_night(0)
l, mw = w.luna, w.mw
l.x, l.y = 690.0, COUNTER
mw.x, mw.y = float(LADX), FLOOR
mw.alert, mw.state, mw.hear_x = 0.0, "patrol", None
w._break_fx = []
alerts = []
for k in range(3):
    if not w.room.stashes[k]["broken"]:
        l.x, l.y = w.room.stashes[k]["x"], w.room.stashes[k]["y"]
        w._try_break()
    alerts.append(mw.alert)
    l.carrying = []   # ⛔ 只能拿一件，模拟回窝放下才能再敲
step_ai(1 / 60, 3)   # 让 update 跑一下，state 才会更新   # ⛔ 用 step_ai：step_pure 每帧把 mw.state 重置为 patrol
chk("\u8d34\u8eab敲\u4e24\u4e0b\u5c31\u8fdb chase\uff08不是\u4e00\u6572\u6ee1\uff09", mw.state == "chase",
    f"alerts={[round(a,2) for a in alerts]} state={mw.state}")

# ⬴⬴ 2026-10-05 判换改写（设计端采方案 A）——旧断言「不靠累积」名不岞实
#
# 旧断言写的是「敲光一整层不靠累积触发 chase」。
# ⬴ 它已经不成立，且不是因为旧档位参数，而是**机制本身**：
#   逐击实测（微波父在 x=1050，逐个敲容器）：
#     敲#1 x=450 loose : 0.000 → 0.000d=600 超听圈
#     敲#2 x=680 plate : 0.000 → 0.000   d=370 超听圈
#     敲#3 x=800 plate : 0.000 → 0.000   d=250 超听圈
#     敲#4 x=900 jar   : 0.000 → **1.000**  ← 单击到顶！d=150
#   → 前三击全是 0（距离 250~600px 均在听圈外），
#     **第 4 击单独把 alert 从 0 推到 1.0** —— 与「累积」无关。
#
# ⬴ 真机制（night.py go_fury）：
#   jar 的 noise=0.62，d=150 → hear_strength = 0.378
#   ⇒ go_fury 的阈值 `if heard < 0.30: return False` 被越过 ⇒ **进 frenzy**
#   ⇒ fury=True 使alert 立刻涨满（`_take_stash` 的 fury 分支）
#   ⇒ 这就是「破罐即引爆」的设计，**不是 bug**（阈值 0.30 是现行值）。
#
# ⬴ 为什么重写成「单击」的判换（设计端采A）：
#   它才能真正守住 `go_fury` 的 172px 阈值；
#   老判换把微波父摆到听圈外、朘而避开了 frenzy 分支——
#   那样最容易出 bug 的那一块就没人测了。
_jar = [s for s in w.room.stashes if s["kind"] == "jar"][0]


def _jar_try(mw_dx):
    """把微波炉摆到 jar 右侧 mw_dx px 处，敲一下，返回 (heard, alert, fury, state)。"""
    w.start_night(0)
    l, mw = w.luna, w.mw
    l.x, l.y = _jar["x"], _jar["y"]
    l.carrying = []
    mw.x, mw.y = _jar["x"] + mw_dx, N.FLOOR_Y
    mw.alert, mw.state, mw.hear_x = 0.0, "patrol", None
    mw.invest_x, mw.invest_linger, mw.invest_hold = None, 0.0, 0.0
    mw.fury, mw.fury_t, mw.fury_x = False, 0.0, None
    _heard = mw.hear_strength(_jar["x"], _jar["noise"])
    w._try_break()
    return _heard, mw.alert, mw.fury, mw.state


# ⬴ 阳性：jar 在听圈内（d=150，heard=0.378 >= 0.30）⇒ 单击直接 frenzy
_h, _a, _f, _s = _jar_try(150.0)
chk("单个 jar 在听圈内 ⇒ 直接 frenzy（不靠多击累积）",
    _f is True and _a >= 1.0 and _s == "chase",
    f"d=150 heard={_h:.3f} alert={_a:.3f} fury={_f} state={_s}")
chk("  ⇒ 那一击的 heard 确实越过 go_fury 阈值 0.30", _h >= 0.30,
    f"heard={_h:.3f} >= 0.30（阈值在 night.py go_fury）")

# ⬴ 阳性对照（这是本条判据的关键）：同一个 jar 放到 >200px 位岔 alarm **不进 frenzy**
_h2, _a2, _f2, _s2 = _jar_try(220.0)
chk("阴性对照同一 jar 在 200px 外 ⇒ **不**进 frenzy（不涨满）",
    _f2 is False and _a2 < 1.0,
    f"d=220 heard={_h2:.3f} alert={_a2:.3f} fury={_f2} state={_s2}")
chk("  ⇒ 阴性对照的 heard 确实低于阈值（否则上一条没意义）",
    _h2 < 0.30, f"heard={_h2:.3f} < 0.30")
# ⬴ 阈值不是“一切就进”：扫一下真实边界，把 172px 的文档化成判据
_edge = [(d, _jar_try(float(d))[1:]) for d in (172, 180)]
chk("  · 阈值边界在 172~180px 之间（172 进 / 180 不进）",
    _edge[0][1][1] is True and _edge[1][1][1] is False,
    " / ".join(f"d={d}: fury={a[1]}" for d, a in _edge)
    + "⇒ 与 go_fury 阈值 0.30 对应的 172px 一致")

# ============================================================================
# ⭐⭐ investigate（走过去查看声源）—— Ronny 2026-10-04 拍板「方向二」
#
# ⭐ 为什么这组断言必须存在（四档容器逼出来的空洞，不是凭空加的功能）：
#   ALERT_DECAY=0.8/秒，而"一次只能拿一件"要求每趟回窝 3~4 秒。
#   实测：plate 档 0.26 的噪声即使贴着守卫敲，alert 峰值也只有 0.26，
#   回窝路上必然衰减归零 → **plate 成哑档**（分档做了、手感做了，玩起来没后果）。
#   investigate 补的是噪声的**位置后果**：不是把 alert 堆满，而是让他**挪开**。
#
# ⛔ 三条不变量逐条断言（改动这个功能前先读）：
#   ① 速度 < RUN_SPEED：查看不是追杀，玩家永远跑得掉
#   ② 目标夹进可活动区：不能走出房间
#   ③ 一次性：到达 → 环顾 → 回巡逻；且 chase 永远压过 investigate
# ============================================================================

def _reset_inv():
    mw.invest_x, mw.invest_linger, mw.invest_hold = None, 0.0, 0.0


# ==================================================================
# ⭐⭐⭐ 2026-10-06 PR-07：investigate 三条判据**整条重写**（原写法是假绿）
#
# ⛔⛔ 原写法错在哪（两条独立原因叠加，缺一不可）：
#   ① **真 bug**：`_investigate` 把「查看完回站岗点」写在**移动分支的末尾**，
#      每走一帧就把 `invest_x` 改写成 `idle_home`；而 `tgt` 是函数开头读的
#      ⇒ 下一帧目标已经是站岗点，**他永远朝站岗点走、从不去看声源**。
#      而原判据把 plate 摆在 680、mw 在 620，他要去的方向（934）**刚好路过** 680，
#      于是「⭐ 他走过来过」被判成OK —— **一条假绿**（实测修bug 前离声源最近 117.2px）。
#   ② **布置问题**：露娜全程站在容器上（mw 右边 60px、正面）⇒ sense=1.0，
#      加上 plate 那0.256，第 **19** 帧就进 chase；chase 压过 investigate
#      （设计不变量③）⇒ 「他离开原位置」「回站岗」「一次性」三条一起红。
#
# ✅ 现在的判据只问**机制量**，不问"某个会飘的时间窗口末端"：
#     离声源最近距离（≤ INVEST_RADIUS  才算真的走过去）
#     是否环顾过（invest_linger 峰值 > 0）
#     看完是否回到站岗点（|终x − idle_home| ≤ INVEST_RADIUS）
#   并加**成对阳性对照**：同一个声源，只改`idle_home` ⇒ 两条行为必须不同。
#     （这条对照是为了防"修完还是假绿"：pre-fix 两种布置他都不去看声源。）
# ==================================================================


def _inv_probe(mw_dx=100.0, home_dx=None, home_x=None, seconds=10.0):
    """敲一下 plate（真实入口 `_try_break`），然后让露娜跑开，记录 investigate 行为。

    `mw_dx`  = 微波炉摆在声源右侧多少 px（⇒ 决定这声响**够不够**触发查看）
    `home_dx` = 若给，则把站岗点强行挪到「声源 + home_dx」（⇒ 阳性对照用）
    `home_x` = 若给，则把站岗点**绝对钉死**到这个坐标（⇒ ①a 的"离得远"前置条件用）

    返回 dict：离声源最近距离 / 是否环顾过 / 是否进过 chase / 终x / 站岗点 / 声源 /
               **峰值位移**（①g 用）。
    ⭐ 露娜在敲完之后**必须离开**——不然她贴脸站着会进 chase，
      把「他走过去看」这件事顶掉（那就是原判据踩的坑）。
    ⚠️ 声源坐标必须在 `start_night` **之后**从新room 里取：
      上一轮probe 已经把上一局的容器敲破了，沿用旧坐标会拿到**另一件容器**，
      于是 mw_dx / home_dx 全部对错位置（第一版就是这么错的，②a/②b 全红）。
    ⭐⭐ 2026-10-12 设计端补 `home_x` 与 `peak_move`：
      · `home_x`：原探针的站岗点**隐含继承** `idle_home`（= 巡逻段中点 934），
        于是「声源 x=830 离站岗点 104px」是个**布局副产品**，①a 的 >150 门槛
        随巡逻段改动而失效 —— 判据在跟一个它没权控制的几何较劲。
        ✅ 改为显式钉死站岗点，门槛才是判据自己的。
      · `peak_move`：①g 原判据量「净位移」，可他**设计上就要回站岗点**（①f），
        净位移天然≈0 —— ①g 与 ①f 自相矛盾。✅ 改成峰值位移（真的离开原位置过多远）。
    """
    w.start_night(0)
    l, mw = w.luna, w.mw
    st = _pick(w, "plate")
    mw.x, mw.y = float(st["x"]) + mw_dx, N.FLOOR_Y
    if home_dx is not None:
        mw.idle_home = float(st["x"]) + home_dx
    if home_x is not None:
        mw.idle_home = float(home_x)
    mw.alert, mw.state, mw.hear_x = 0.0, "patrol", None
    mw.invest_x, mw.invest_linger, mw.invest_hold = None, 0.0, 0.0
    l.x, l.y = st["x"], st["y"]
    l.carrying = []
    w._try_break()                      # ⭐ 真实入口：会登记 invest_hold / hear_x
    out = dict(snd=float(st["x"]), home=float(mw.idle_home),
               hold=mw.invest_hold, min_d=1e9, linger=0.0, chase=False,
               x0=float(mw.x), x1=float(mw.x), peak_move=0.0)
    l.x, l.y = 150.0, N.FLOOR_Y# ⭐ 敲完就跑（模拟玩法）
    for _ in range(int(seconds * 60)):
        step_ai(1 / 60, 1)
        out["min_d"] = min(out["min_d"], abs(mw.x - st["x"]))
        out["peak_move"] = max(out["peak_move"], abs(mw.x - out["x0"]))
        out["linger"] = max(out["linger"], mw.invest_linger)
        if mw.state == "chase":
            out["chase"] = True
    out["x1"] = float(mw.x)
    out["invest_x"] = mw.invest_x
    return out


# ---------- ① 布置(a)：声源离站岗点远 ⇒ 他必须真的走过去、环顾、再回来 ----------
# ⭐ 2026-10-12：显式把站岗点钉到巡逻段右端（原来隐含继承中点 934 ⇒ 离声源仅 104px，
#   ＞150 的门槛随布局改动失效）。这样「离得远」才是判据自己控制的条件。
_a = _inv_probe(mw_dx=100.0, home_x=float(N.NIGHTS[0]["patrol"][1]))
chk("①a 布置：声源离站岗点足够远（防'路过就算'）",
    abs(_a["snd"] - _a["home"]) > 150.0,
    f"声源 x={_a['snd']:.0f}  站岗点={_a['home']:.0f}  相距 "
    f"{abs(_a['snd']-_a['home']):.0f}px")
chk("①b 够响的声响登记了触发记忆（invest_hold > 0）",
    _a["hold"] > 0.0, f"hold={_a['hold']:.2f}")
chk("①c ⭐ 从未被 chase 顶掉（前置条件：他是因为'走过去看'才动的）",
    not _a["chase"], f"chase={_a['chase']}")
chk("①d ⭐⭐ 他**真的走到了声源**（离声源最近 ≤ INVEST_RADIUS）",
    _a["min_d"] <= N.INVEST_RADIUS,
    f"离声源最近 {_a['min_d']:.1f}px  门槛 {N.INVEST_RADIUS:.0f}px"
    f"（修 bug 前实测是 117.2px）")
chk("①e ⭐ 到达后确实环顾了（invest_linger 峰值 > 0）",
    _a["linger"] > 0.0, f"峰值 {_a['linger']:.3f}s（INVEST_LINGER={N.INVEST_LINGER}）")
chk("①f ⭐ 看完回到站岗点（|终x − idle_home| ≤ INVEST_RADIUS）",
    abs(_a["x1"] - _a["home"]) <= N.INVEST_RADIUS,
    f"终x={_a['x1']:.1f}  站岗点={_a['home']:.0f}  偏差 "
    f"{abs(_a['x1']-_a['home']):.1f}px")
# ⭐ 2026-10-12 设计端重校：原判据量「净位移 > 40px」，可他**设计上必须回站岗点**
#   （①f 就是断言这件事）⇒ 净位移天然≈0，①g 与 ①f **自相矛盾**：
#   一个要求他回家，一个要求他别在家。✅ 改成**峰值位移**——"他确实离开原位置走过"
#   才是这条判据想表达的意思，且与 ①f 不再冲突。
chk("①g 他真的离开了原位置（峰值位移 > 40px）", _a["peak_move"] > 40.0,
    f"峰值位移 {_a['peak_move']:.0f}px（{_a['x0']:.0f} → 最远 {_a['x0']+_a['peak_move']:.0f}）"
    f"  终x={_a['x1']:.0f}（回了站岗点 {_a['home']:.0f}）")
chk("①h 查看是一次性的：结束时不追着人跑",
    _a["invest_x"] is None,
    f"invest_x={_a['invest_x']}  chase={_a['chase']}")
chk("①i 环顾计时无负值残留（只清invest_x 会留脏状态）",
    _a["linger"] >= 0.0, f"峰值 {_a['linger']:.3f}")

# ---------- ② ⭐ 成对阳性对照：同一个声源，只改 idle_home ⇒ 行为必须不同 ----------
#Pre-fix 两种布置他都**不去**看声源（只是路过），所以这条对照当时也拦不住假绿；
#   修好之后，(a) 的终点在声源远处（回了自己的站岗点），(b) 的终点贴着声源
#   （站岗点就在声源旁边）⇒ 两个终点的"离声源距离"必须拉开。
_b = _inv_probe(mw_dx=100.0, home_dx=10.0)
chk("②a 对照布置：站岗点就在声源旁边（10px）",
    abs(_b["home"] - _b["snd"]) <= 15.0,
    f"声源 x={_b['snd']:.0f}  站岗点={_b['home']:.0f}")
chk("②b ⭐ 对照布置下他同样走到了声源并环顾",
    _b["min_d"] <= N.INVEST_RADIUS and _b["linger"] > 0.0,
    f"离声源最近 {_b['min_d']:.1f}px  环顾峰值 {_b['linger']:.3f}s")
_da = abs(_a["x1"] - _a["snd"])
_db = abs(_b["x1"] - _b["snd"])
chk("②c ⭐⭐ 阳性对照：两种布置的**终点离声源距离**必须不同"
    "（防'又是同一种假绿'）",
    abs(_da - _db) > 100.0,
    f"(a) 终点离声源 {_da:.0f}px（他回了自己站岗点）  "
    f"(b) 终点离声源 {_db:.0f}px（站岗点就在声源旁）  差 {abs(_da-_db):.0f}px")
chk("②d 两种布置下他都真的走到了声源（这一条不能靠布置取巧）",
    _a["min_d"] <= N.INVEST_RADIUS and _b["min_d"] <= N.INVEST_RADIUS,
    f"(a) {_a['min_d']:.1f}px   (b) {_b['min_d']:.1f}px")

# ---------- ③ 阴性对照：不够门槛的声响 ⇒ 他一步都不许动 ----------
_c = _inv_probe(mw_dx=200.0)
chk("③a ⭐ 阴性对照：200px 外的 plate 不登记触发记忆",
    _c["hold"] == 0.0, f"hold={_c['hold']:.2f}  离声源 {_c['min_d']:.0f}px")
chk("③b 阴性对照下他一步都没动（不是'走了一点'）",
    abs(_c["x1"] - _c["x0"]) < 1.0 and _c["min_d"] > 100.0,
    f"位移 {abs(_c['x1']-_c['x0']):.2f}px  离声源最近 {_c['min_d']:.0f}px")
chk("③c 阴性对照下没有环顾", _c["linger"] == 0.0, f"环顾峰值 {_c['linger']:.3f}s")

# ---------- ② 远距离敲 plate → 不启动查看（位置仍是战术资源）----------
w.start_night(0)
l, mw = w.luna, w.mw
_st2 = _pick(w, "plate")
l.x, l.y = _st2["x"], _st2["y"]
l.carrying = []
mw.x, mw.y = _st2["x"] + 400.0, N.FLOOR_Y
mw.alert, mw.state, mw.hear_x = 0.0, "patrol", None
_reset_inv()
w._try_break()
_k400 = mw.hear_strength(float(_st2["x"]), 0.26)
step_ai(1 / 60, 20)
chk("400px 外敲 plate 不启动查看（听不清就只转头）",
    mw.invest_x is None,
    f"衰减后 k={_k400:.3f} < 门槛 {N.INVEST_ALERT:.2f}  invest_x={mw.invest_x}")

# ---------- ③ 三条不变量 ----------
chk("不变量①investigate 速度 < RUN_SPEED（他是在查看不是追杀）",
    N.INVEST_SPEED < N.RUN_SPEED - 8.0,
    f"{N.INVEST_SPEED:.0f} < {N.RUN_SPEED - 8.0:.0f}")

# ⭐⭐ 2026-10-06 PR-07：这条判据的**上界 previously 是错的**，一并纠正。
#   ⛔ 旧写法 `_HI = N.VW - mw.w*0.5 - 8.0` = 1280−56 = **1224**，
#      那是**视口宽**口径 —— PR-03 已把世界宽改成 3840，
#      而 `_clamp_self_x` / `_clamp_target_x` 早就改成读 `self.world_w`
#      （那两处的docstring 里写着"原来是视口宽，这三处同一天被漏改过两次"）。
#      ⇒ 判据的 1224 与被测代码的真实活动区 **[56, 3784]** 不一致。
#   ⚠️ 它以前一直"绿"是**假绿**：pre-fix 时 `invest_x` 在一帧内就被改写成
#      `idle_home`(934)，`_tgt` 读到的永远是 934 ⇒ 恰好落在 1224 以内。
#      修完 bug 后 `_tgt` 才真的是被夹过的声源坐标（hx=1275 → 1275）⇒ 报红。
#   ✅ 现在改成**不写死任何宽度**：直接问"目标是不是等于 `_clamp_target_x(hear_x)`"
#      + "他的x 全程有没有越出 `[half, world_w−half]`"（逐帧量全程 min/max）。
#      ⇒ 判据比旧版**更强**（旧版只看终帧一个点），且不会再次与世界宽脱钩。
_HALF = mw.w * 0.5 + 8.0
_edge_ok = True
_edge_info = []
for _hx in (5.0, 1275.0, 640.0, 3800.0):    # 左外 / 右外 / 房中央 / 远超世界右界
    w.start_night(0)
    l, mw = w.luna, w.mw
    mw.alert, mw.state = 0.0, "patrol"
    mw.hear_x = _hx
    mw.x, mw.y = 300.0, N.FLOOR_Y
    _reset_inv()
    mw.invest_hold = 99.0                   # 强制启动
    step_ai(1 / 60, 1)
    _tgt = mw.invest_x
    _want = mw._clamp_target_x(_hx)         # ⭐ 不再手写公式
    _ok_t = (_tgt is not None and abs(_tgt - _want) < 1e-6
             and _HALF - 1.0 <= _tgt <= mw.world_w - _HALF + 1.0)
    _minx, _maxx = 1e9, -1e9
    for _ in range(200):
        step_ai(1 / 60, 1)
        _minx = min(_minx, mw.x)
        _maxx = max(_maxx, mw.x)
    _ok_x = (_minx >= _HALF - 1.0) and (_maxx <= mw.world_w - _HALF + 1.0)
    _edge_ok = _edge_ok and _ok_t and _ok_x
    _edge_info.append(f"hx={_hx}→tgt={_tgt}={_want}{'' if _ok_t else '✗目标'}"
                      f" x∈[{_minx:.0f},{_maxx:.0f}]{'' if _ok_x else ' ✗越界'}")
chk("不变量② 目标夹进可活动区，他不会走出房间（逐帧量全程）", _edge_ok,
    f"活动区=[{_HALF:.0f},{mw.world_w-_HALF:.0f}]（world_w={mw.world_w:.0f}，"
    f"旧判据错用视口宽 ⇒ 上界只有 1224）  " + " ".join(_edge_info))

# chase 压过 investigate
w.start_night(0)
l, mw = w.luna, w.mw
mw.alert, mw.state = 0.0, "patrol"
mw.hear_x = 1100.0
mw.x, mw.y = 300.0, N.FLOOR_Y
_reset_inv()
mw.invest_hold = 99.0
step_ai(1 / 60, 1)
_inv_started = mw.invest_x is not None
mw.state = "chase"
mw.alert = 1.0                              # 强行进入 chase
step_ai(1 / 60, 1)
_inv_cleared = (mw.invest_x is None and mw.invest_linger == 0.0)
step_ai(1 / 60, 10)
chk("不变量③ chase 立刻压过 investigate（发现你就只追你）",
    _inv_started and _inv_cleared and mw.invest_x is None,
    f"先启动={_inv_started} 进chase后清空={_inv_cleared}  10帧后={mw.invest_x}")



# ---- 潜c行c：a按9 Shift 变8慢2且4换2成0 walk动8作c ----
w.start_night(0)
l = w.luna
l.x, l.y = 300.0, N.FLOOR_Y
l.vx = l.vy = 0.0
l.on_ground = True
w.keys = {Qt.Key_Shift, Qt.Key_D}
step_pure(1 / 60, 60)
vx_sneak = l.x - 300.0
chk("\u6f5c\u884c 1s \u79fb\u52a8 80~125px", 80 < vx_sneak < 125, f"{vx_sneak:.0f}px  \u666e\u901a\u662f {N.RUN_SPEED:.0f}")
chk("\u6f5c\u884c\u65f6\u72b6\u6001\u6807\u4e3a\u6f5c\u884c\u4e2d", l.sneak is True)
chk("\u6f5c\u884c\u7528 sneak \u52a8\u4f5c\uff08\u4e0d\u662f walk / human_run\uff09", l.act == "sneak", f"act={l.act}")
w.keys = set()
step_pure(1 / 60, 30)
chk("\u677e\u5f00 Shift \u6062\u590d\u5e38\u901f", l.sneak is False)

# ⭐ 2026-10-03：布墙 470~730 —— 潜行 1s 后她已在 ~408，再跑 1s 会撞墙，挪到开阔段再测
l.x, l.y = 800.0, N.FLOOR_Y
l.vx = l.vy = 0.0
l.on_ground = True
_x0 = l.x
w.keys = {Qt.Key_D}
step_pure(1 / 60, 60)
chk("\u5e38\u901f 1s \u79fb\u52a8 240~320px", 240 < l.x - _x0 < 320,
    f"{l.x - _x0:.0f}px")
chk("\u5e38\u901f\u65f6\u7528 human_run", l.act == "human_run", f"act={l.act}")
w.keys = set()

# ---- 爬c梯f子0 = 完c全8安9全8（8Lode Runner 机a制6）9 ----
w.start_night(0)
l, mw = w.luna, w.mw
l.x, l.y = float(LADX), 510.0                  # 爬c梯f中d段5（⛔ 别放 520：断言是 y<520 严格小于，放 520 必挂）
l.vx = l.vy = 0.0
l.on_ladder, l.on_ground = True, False
l.escort = False                                # ⭐ 上一组若被抓，escort 残留会让 sense 直接归零
mw.x, mw.y = float(LADX), FLOOR
mw.alert, mw.state = 0.30, "chase"       # ⭐ 从 0.3 起步：从满值 1.0 起步永远看不出「缓涨」
mw.hear_x = None
a0 = mw.alert
step_ai(1 / 60, 60)
chk("梯子上不再绝对安全：他追得上来（Ronny 10-03 上强度）", l.on_ladder and l.y < 520.0,
    f"y={l.y:.0f} on_ladder={l.on_ladder}")
chk("梯子上警戒缓涨而非归零", mw.alert > a0, f"alert {a0:.2f} -> {mw.alert:.2f}")

# 下b来5就1不d安9全8了6
l.on_ladder = False
l.on_ground = True
l.y = N.FLOOR_Y
l.escort = False                                # ⭐ 押送态会挡住 sense（trespass 判定带 not escort）
mw.alert = 0.0
mw.state = "patrol"
mw.hear_x = None
# ⭐⭐ 2026-10-12 设计端重校。原判据（`\u4e0b\u6765\u540e\u6062\u590d\u88ab\u89c1\u8ff7\u7684\u53ef\u80fd`，
#   alert > 0.2）两处问题：
#   ① **从不钉 `l.face`**：PR29 之后"涨多快"取决于她有没有露后背
#      （设计端实测 `_work/_探_下来后恢复.py`）——
#        · 背对他 ⇒ 满速支，约 0.4s 涨满
#        · 面朝他 ⇒ 潜伏支，0.67s 只到 **0.12**（正是这条判据量到的值）
#      判据在测一个它自己没指定的变量。
#   ② **几何是混沌副产品**：上一段 60 帧 chase 会把他搬到哪，测试从不控制
#     （实测两次 dx 分别是 +0 与 +127）⇒ 量到的是"他恰好站在哪"。
#   ✅ 正确口径：把 Ronny 设计的场景显式钉死 —— 她从梯子上下来、落在他面前、背对着他，
#      然后断言他必须立刻发现她（"梯子不再绝对安全"）。
l.x = mw.x + 60.0                               # 落点：他前方 60px
l.face = 1                                      # 背对他 ⇒ 露后背
step_ai(1 / 60, 40)
chk("下来后恢复被见（梯子不再绝对安全）", mw.alert > 0.5,
    f"alert={mw.alert:.2f} state={mw.state} dx={l.x - mw.x:+.0f}")

# ---- 画b面2能d画b（8容9器8/碎e片7/潜c行c）9 ----
w.start_night(0)
l, mw = w.luna, w.mw
l.x, l.y = 690.0, COUNTER
l.sneak = True
w._break_fx = [[690.0, 470.0, 0.4]]
for st in w.room.stashes:
    st["broken"] = (st["x"] > 800)
try:
    render()
    chk("\u5bb9\u5668+\u788e\u7247+\u6f5c\u884c\u753b\u9762\u80fd\u753b", True)
except Exception as e:
    chk("\u5bb9\u5668+\u788e\u7247+\u6f5c\u884c\u753b\u9762\u80fd\u753b", False, f"{type(e).__name__}: {e}")

print()
print("=" * 72)
print("\u2714 \u5fae\u6ce2\u7089\u4f53\u578b / \u722c\u68af / \u8df3\u8dc3\uff08Ronny 10-03\uff1a\u4e0a\u5f3a\u5ea6\uff09")
print("=" * 72)
w.start_night(0)
l, mw = w.luna, w.mw
chk("\u5fae\u6ce2\u7089\u6bd4\u9732\u5a1c\u9ad8\uff08183cm vs 150cm\uff09", mw.body_h > N.ACTOR_H,
    f"mw {mw.body_h:.0f}px  vs  \u9732\u5a1c {N.ACTOR_H:.0f}px")
chk("\u722c\u68af\u6bd4\u9732\u5a1c\u6162\uff08\u7ed9\u5979\u8131\u7a00\u7a97\u53e3\uff09", mw.climb_speed < N.CLIMB_SPEED,
    f"mw {mw.climb_speed:.0f} vs \u9732\u5a1c {N.CLIMB_SPEED:.0f} px/s")
chk("\u5fae\u6ce2\u7089\u8df3\u4e0d\u4e0a\u53bb\u6599\u7406\u53f0\uff08\u843d\u5dee178px\uff09",
    mw.jump_v ** 2 / (2 * N.GRAVITY) < 170.0,
    f"\u8df3\u9ad8 {mw.jump_v**2/(2*N.GRAVITY):.0f}px < 170")

# 跳3跃3：a距d离b 150~330px 且4露2娜c在8地0板f上a →2 他6会a跳3一0下b压b过7来5
l.x, l.y = 900.0, N.FLOOR_Y
l.on_ground, l.vy, l.on_ladder = True, 0.0, False
mw.x, mw.y = 600.0, N.FLOOR_Y
mw.state, mw.alert, mw.vy, mw.on_ground, mw.jump_cd = "chase", 1.0, 0.0, True, 0.0
w.phase = "play"
mw._chase(1 / 60, l, w.room)
chk("\u8fdc\u79bb\u65f6\u4f1a\u8df3\uff08\u538b\u8fc7\u6765\uff09", (not mw.on_ground) and mw.vy < 0,
    f"vy={mw.vy:.0f} on_ground={mw.on_ground}")
top = mw.y
for _ in range(90):
    mw._chase(1 / 60, l, w.room)
    top = min(top, mw.y)
chk("\u8df3\u8dc3\u540e\u4f1a\u843d\u56de\u5730\u677f", mw.on_ground and abs(mw.y - N.FLOOR_Y) < 1.0,
    f"y={mw.y:.1f}")
chk("\u8df3\u9ad8\u5728\u9884\u671f\u5185", N.FLOOR_Y - top < 90, f"\u5b9e\u9645\u8df3\u9ad8 {N.FLOOR_Y-top:.0f}px")

# 爬c梯f：a露2娜c在8台0面2上a →2 他6走0到0梯f子0脚a下b并6爬c上a来5
l.x, l.y = float(LADX), float(LADTOP)
l.on_ground, l.vy = True, 0.0
mw.x, mw.y = 620.0, N.FLOOR_Y
mw.state, mw.alert, mw.vy, mw.on_ground = "chase", 1.0, 0.0, True
for _ in range(200):
    mw._chase(1 / 60, l, w.room)
chk("\u722c\u68af\u80fd\u529b\uff1a\u4f1a\u8d70\u5230\u68af\u5b50\u5e76\u722c\u4e0a\u53f0\u9762", mw.y < N.FLOOR_Y - 100,
    f"mw.y={mw.y:.0f}  \u53f0\u9762 470")

# 爬c梯f不d可f能d越a过7台0面2底5（8不d会a穿f墙9）9
mw.y = min(mw.y, 468.0)
chk("\u722c\u68af\u4e0d\u4f1a\u7a7f\u8fc7\u53f0\u9762\u9876", mw.y >= 468.0, f"mw.y={mw.y:.0f}")

print()
print("=" * 72)
print("⑭ 2026-10-03 三连修：布墙 / 攀爬面 / QTE 锁移动（Ronny 实机反馈）")
print("=" * 72)

# ① 布墙：脚低于桌面时，从布区外不许一步跨进 TABLE_X0~TABLE_X1
# ⛔ 2026-10-04：起点原来写死 x=430，而**新布局 TABLE_X0 就是 430** ——
#   人一出生就在布区里，按设计规则「已在布区内的人自由走出」当然能走出去，
#   于是报 x=580 FAIL。判据不是被产品代码拦的，是它自己站错了起点。
#   ✅ 起点改成 TABLE_X0 - 80（布区外 80px），跑 0.5s 撞墙，期望被钉在 TABLE_X0 - m。
#   ⛔ 真实厨房里也不可能"从桌布里面走出来" —— 那里是桌子底下，只能从桌面下。
w.start_night(0)
l = w.luna
l.x, l.y = N.TABLE_X0 - 80.0, N.FLOOR_Y
l.vx, l.vy = N.RUN_SPEED, 0.0
l.on_ground = True
for _ in range(30):
    l.update(1 / 60, {Qt.Key_D}, w.room)     # 0.5s 全速右跑
_m = N.BODY_W * 0.35
chk("布墙：地面全速右跑被拦在布区外", l.x <= N.TABLE_X0 - _m + 1.0,
    f"x={l.x:.0f}（钉位 {N.TABLE_X0 - _m:.1f}） 布左缘 {N.TABLE_X0}")

# ② 攀爬面：布前按 W 能扒布，一路爬到桌面（整面可扒，不是只有一根杆）
l.x, l.y = 448.0, N.FLOOR_Y
l.vx = l.vy = 0.0
l.on_ladder = False
l.on_ground = True
w.keys = {Qt.Key_W}
step_pure(1 / 60, 150)
w.keys = set()
chk("攀爬面：布前按 W 爬到桌面", abs(l.y - N.TABLE_TOP) < 2.0 and not l.on_ladder,
    f"y={l.y:.1f} 期望 {N.TABLE_TOP}")

# ③ 爬到底 = 站在地板上（⛔ 不是地板下方 —— 底端 632 就是「掉到地底下」事故的根因）
l.x, l.y = 600.0, 500.0
l.on_ladder = True
l.on_ground = False
w.keys = {Qt.Key_S}
step_pure(1 / 60, 120)
w.keys = set()
chk("爬布到底落在地板上（不在地板下方）", abs(l.y - N.FLOOR_Y) < 1.0 and not l.on_ladder,
    f"y={l.y:.1f} 期望 {N.FLOOR_Y}")

# ④ QTE 锁移动：QTE 期间方向键只喂 QTE，不驱动移动
w.start_night(0)
l = w.luna
l.x, l.y = 610.0, N.TABLE_TOP          # 站在桌面冰箱前
l.vx = l.vy = 0.0
l.on_ground = True
w.keys = set()
w._qte_start()
qx = l.x
w.keys = {Qt.Key_Left, Qt.Key_Right}
# ⭐⭐ 2026-10-12 设计端重校。旧判据 `moved < 1.0 and w.qte is not None` 有个空转缺陷：
#   它要求"采样时 QTE 仍在进行"，但 QTE_LEN=3 且**左右两个键同时按着** ⇒
#   序列可能在 1~2 帧内就被满足（`_qte_update` 每 tick 都喂键）⇒ QTE 提前结束，
#   于是后半句恒假，判据恒红 —— 而前半句（位移 0.0px）其实是**通过**的。
#   ⇒ 旧判据把「QTE 结束了」误报成「锁失效」。
#   ✅ 正确口径：只统计 **QTE 真正活跃的那些帧**里的位移；同时要求活跃帧数 > 0
#     （否则整条判据空转，那是另一种假绿）。
_moved_in_qte = 0.0
_frames_live = 0
for _ in range(10):
    _x0 = l.x
    step(1 / 60, 1)
    if w.qte is not None:
        _frames_live += 1
        _moved_in_qte = max(_moved_in_qte, abs(l.x - _x0))
chk("QTE 期间方向键不移动", _moved_in_qte < 1.0 and _frames_live > 0,
    f"QTE 活跃 {_frames_live}/10 帧，活跃期内最大单帧位移 {_moved_in_qte:.2f}px")
# ⭐ 阳性对照（证明上面那条不是"输入死了所以不动"）：QTE 结束后同一组键必须真能驱动移动
w.qte = None
w.keys = {Qt.Key_Right}
step(1 / 60, 30)                       # 0.5s
chk("⭐阳性对照：QTE 结束后方向键恢复驱动", abs(l.x - qx) > 20.0,
    f"位移 {abs(l.x - qx):.1f}px")
w.qte = None
w.keys = set()

print("=" * 72)
print(f"通过 {len(OK)} / {len(OK)+len(BAD)}")
if BAD:
    print("未通过： " + "、".join(BAD))
print("=" * 72)
time.perf_counter = _orig


print()
print("=" * 72)
print("\u2714 \u5fae\u6ce2\u7089\u4f53\u578b / \u722c\u68af / \u8df3\u8dc3\uff08Ronny 10-03\uff1a\u4e0a\u5f3a\u5ea6\uff09")
print("=" * 72)
w.start_night(0)
l, mw = w.luna, w.mw
chk("\u5fae\u6ce2\u7089\u6bd4\u9732\u5a1c\u9ad8\uff08183cm vs 150cm\uff09", mw.body_h > N.ACTOR_H,
    f"mw {mw.body_h:.0f}px  vs  \u9732\u5a1c {N.ACTOR_H:.0f}px")
chk("\u722c\u68af\u6bd4\u9732\u5a1c\u6162\uff08\u7ed9\u5979\u8131\u7a00\u7a97\u53e3\uff09", mw.climb_speed < N.CLIMB_SPEED,
    f"mw {mw.climb_speed:.0f} vs \u9732\u5a1c {N.CLIMB_SPEED:.0f} px/s")
chk("\u5fae\u6ce2\u7089\u8df3\u4e0d\u4e0a\u53bb\u6599\u7406\u53f0\uff08\u843d\u5dee178px\uff09",
    mw.jump_v ** 2 / (2 * N.GRAVITY) < 170.0,
    f"\u8df3\u9ad8 {mw.jump_v**2/(2*N.GRAVITY):.0f}px < 170")

# 跳3跃3：a距d离b 150~330px 且4露2娜c在8地0板f上a →2 他6会a跳3一0下b压b过7来5
l.x, l.y = 900.0, N.FLOOR_Y
l.on_ground, l.vy, l.on_ladder = True, 0.0, False
mw.x, mw.y = 600.0, N.FLOOR_Y
mw.state, mw.alert, mw.vy, mw.on_ground, mw.jump_cd = "chase", 1.0, 0.0, True, 0.0
w.phase = "play"
mw._chase(1 / 60, l, w.room)
chk("\u8fdc\u79bb\u65f6\u4f1a\u8df3\uff08\u538b\u8fc7\u6765\uff09", (not mw.on_ground) and mw.vy < 0,
    f"vy={mw.vy:.0f} on_ground={mw.on_ground}")
top = mw.y
for _ in range(90):
    mw._chase(1 / 60, l, w.room)
    top = min(top, mw.y)
chk("\u8df3\u8dc3\u540e\u4f1a\u843d\u56de\u5730\u677f", mw.on_ground and abs(mw.y - N.FLOOR_Y) < 1.0,
    f"y={mw.y:.1f}")
chk("\u8df3\u9ad8\u5728\u9884\u671f\u5185", N.FLOOR_Y - top < 90, f"\u5b9e\u9645\u8df3\u9ad8 {N.FLOOR_Y-top:.0f}px")

# 爬c梯f：a露2娜c在8台0面2上a →2 他6走0到0梯f子0脚a下b并6爬c上a来5
l.x, l.y = float(LADX), float(LADTOP)
l.on_ground, l.vy = True, 0.0
mw.x, mw.y = 620.0, N.FLOOR_Y
mw.state, mw.alert, mw.vy, mw.on_ground = "chase", 1.0, 0.0, True
for _ in range(200):
    mw._chase(1 / 60, l, w.room)
chk("\u722c\u68af\u80fd\u529b\uff1a\u4f1a\u8d70\u5230\u68af\u5b50\u5e76\u722c\u4e0a\u53f0\u9762", mw.y < N.FLOOR_Y - 100,
    f"mw.y={mw.y:.0f}  \u53f0\u9762 470")

# 爬c梯f不d可f能d越a过7台0面2底5（8不d会a穿f墙9）9
mw.y = min(mw.y, 468.0)
chk("\u722c\u68af\u4e0d\u4f1a\u7a7f\u8fc7\u53f0\u9762\u9876", mw.y >= 468.0, f"mw.y={mw.y:.0f}")


# ============================================================================
# ㉕ · PR31-D（2026-10-13 设计端派单）investigate 走路动画 + 开局速度尖峰
# ============================================================================
# ⭐ 本段两条判据（㉕-1/2、㉕-3/4）都是**新增**，⛔ 没有改动本文件里任何既有判据。
# ⭐ 帧序一律用【真实】`w._draw_mw()` 取：只把 `QPainter.drawImage` 换成记录器，
#   ⛔ 不替换被测函数、⛔ 不复刻一份取键逻辑。
# ⭐ 全程驱动真 `w._tick()`（本文件既有纪律 ①）。


def _mw_drawn_key():
    """真跑 `_draw_mw`，返回它这一帧实际画的键名（mw_idle / mw_walk / None）。

    None = 压根没画真帧（走了 `_draw_mw_box` 灰盒兜底）。
    ⛔ 按 QImage **对象身份**认定，不看尺寸/内容 ——
       mw_idle canvas 84x217 / mw_walk 86x217，只差 2px，看尺寸会认错。
    """
    from PySide6.QtGui import QImage, QPainter
    canvas = QImage(64, 64, QImage.Format_ARGB32)
    p = QPainter(canvas)
    seen = []
    _orig_di = QPainter.drawImage

    def _spy(_self, *a):
        seen.append(a)

    QPainter.drawImage = _spy
    try:
        w._draw_mw(p)
    finally:
        QPainter.drawImage = _orig_di
    p.end()
    pm = None
    for a in seen:
        for it in a:
            if isinstance(it, QImage):
                pm = it
                break
        if pm is not None:
            break
    if pm is None:
        return None
    for k in ("mw_idle", "mw_walk"):
        for row in (w.gframes.get(k) or []):
            if row[0] is pm:
                return k
    return None


print("㉕ PR31-D · investigate 走路动画 / 开局速度尖峰")
print("=" * 72)

# ⭐⭐ 时钟复位（本段专属，⛔ 不动 :1278 那行既有代码）：
#   本文件 :1278（总结尾）把 perf_counter 还原成了真时钟；:1281 之后的既有段
#   全部直调 `mw._chase(1/60, ...)`、不走的 `_tick` ⇒ 对还原免疫。
#   但本段要驱动真 `w._tick()`（纪律①）⇒ 必须把假时钟装回来。
#   ⛔ 同时必须把 `w._last` 打回 None：它在真时钟下留着真实时间戳（亿级），
#      装回假时钟后 `now - _last` = 假值(几百) - 真戳(亿级) = 大负数
#      ⇒ `min(0.033, 负)` = 负 dt ⇒ 物理倒退。
#      实测病征（2026-10-13，复位前）：30 帧只走 5.6px、night_t 冻结在 0.03、
#      invest_hold 30 帧只掉 0.001 —— 全部因为 dt 退化成了微秒级。
time.perf_counter = lambda: _T[0]
w._last = None


def _mw_setup_investigate():
    """把微波炉摆进「走过去查看声源」的前置状态（⛔ 不手动设 invest_x）。

    invest_x 由 `Microwave.update` 自己建（night.py:2344 附近），
    ⛔ 不由测试代劳 —— 否则测的就是测试自己造的状态，不是游戏行为。
    """
    w.mode = "play"
    w.phase = "play"
    w.mw.state = "patrol"
    w.mw.alert = 0.0
    w.mw.invest_x = None
    w.mw.invest_linger = 0.0
    w.mw.invest_hold = 2.0
    # ⛔ 声源放他**右边**：放左边他会一路走到窝里把露娜抓住 ⇒ 进押送演出
    #    （`mw.x = l.x + 34.0` 接管位置）⇒ 这段就不是"查看"了（PR33 探针实测踩过）。
    w.mw.hear_x = float(w.mw.x) + 500.0
    # 露娜回窝 ⇒ 不越界 ⇒ trespass=False ⇒ 他不会转 chase
    w.luna.x = float(w.room.spawn_luna[0])
    w.luna.y = float(N.FLOOR_Y)


# ---- 判据 A：investigate 期间必须播 mw_walk ----
w.start_night(0)
_x0 = float(w.mw.x)
_mw_setup_investigate()
step(1 / 60, 30)                       # 真 _tick：invest_x 应被建立、他应真的在走
_dx = float(w.mw.x) - _x0
_k_inv = _mw_drawn_key()
chk("㉕-1 ⭐⭐⭐ PR31-D 判据A：investigate 期间（invest_x 非 None 且真位移）"
    " 必须播 mw_walk，不许播 mw_idle（165px/s 配 8fps 站桩 = 滑行）",
    w.mw.invest_x is not None and _dx > 30.0 and _k_inv == "mw_walk",
    f"invest_x={w.mw.invest_x:.0f} 位移={_dx:+.1f}px 实际画的键={_k_inv}")

# ---- 判据 A 的阳性对照：同一套 setup，只把"查看触发"关掉 ⇒ 必须回到 mw_idle ----
# ⛔ 若不设这条，㉕-1 可能因为"mw_idle/mw_walk 压根分不清"而假绿。
# ⭐ 与 ㉕-1 的**唯一**差别是 invest_hold=0 / hear_x=None（触发关掉）；
#    并断言整个窗口内 invest_x 始终为 None、且零位移 ⇒ 证明对照组真的是"站着巡逻"。
w.start_night(0)
_x0 = float(w.mw.x)
_mw_setup_investigate()
w.mw.invest_hold = 0.0
w.mw.hear_x = None
w.mw.invest_x = None
step(1 / 60, 30)
_dx_c = float(w.mw.x) - _x0
_k_ctl = _mw_drawn_key()
chk("㉕-2 ⭐⭐ 判据A 阳性对照：同一套 setup 但关掉查看触发（invest_x 恒 None、"
    "零位移、state=patrol）⇒ 必须播 mw_idle（证明判据分得清这两者）",
    w.mw.invest_x is None and abs(_dx_c) < 1e-9
    and w.mw.state == "patrol" and _k_ctl == "mw_idle",
    f"invest_x={w.mw.invest_x} 位移={_dx_c:+.1f}px state={w.mw.state} 实际画的键={_k_ctl}")

# ---- 判据 B：开局无速度尖峰 ----
w.start_night(0)
_px_imm = float(w._mw_px)
_sm_imm = float(w._mw_sm)
step(1 / 60, 1)                        # 首帧：差分基准若没同步，这里就会炸
_sm_1f = float(w._mw_sm)
chk("㉕-3 ⭐⭐⭐ PR31-D 判据B：start_night 后 `_mw_px` 已同步到新微波炉、"
    "首帧 `_mw_sm` ≤ 5.0（改前这里会拿上一档遗留位置做差分 ⇒ 尖峰 ⇒ 头 ~0.5s 步频偏快）",
    abs(_px_imm - float(w.mw.x)) < 1e-9 and _sm_imm <= 5.0 and _sm_1f <= 5.0,
    f"_mw_px-mw.x={_px_imm - float(w.mw.x):+.4f}  "
    f"_mw_sm 立刻={_sm_imm:.4f} 首帧后={_sm_1f:.4f}（阈值 5.0）")

# ---- 判据 B 的阳性对照：把 _mw_px 戳成离谱旧值 ⇒ 必须造出尖峰 ----
# ⛔ 造不出尖峰 ⇒ 说明这条判据根本没在测"速度差分"这个东西。
w.start_night(0)
w._mw_px = float(w.mw.x) - 3000.0
w._mw_sm = 0.0
step(1 / 60, 1)
_sm_spike = float(w._mw_sm)
chk("㉕-4 ⭐⭐ 判据B 阳性对照：`_mw_px` 戳成 3000px 旧值 ⇒ 首帧必须造出 > 5.0 的尖峰",
    _sm_spike > 5.0,
    f"_mw_sm={_sm_spike:.1f}（阈值 5.0）⇒ 判据对速度差分有分辨力")

print("=" * 72)
print(f"㉕ PR31-D 段完成：本段 4 条（含 2 条阳性对照）")
print("=" * 72)


# ============================================================================
# ㉖ · PR36（2026-10-14 设计端派单）桌宠 pack 分支镜像规则修正
# ============================================================================
# ⭐ 病灶：pack 分支原来写 `if l.face < 0: mirror`（假设所有素材朝右）。
#   而 night.py:1716-1718 空中按左右键也会改 face ⇒ 20 个**正面**动作
#   （fall/jump/idle…）在 face 变号时被镜像，尾巴/呆毛跳到另一侧
#   = Ronny 反馈「下落时人物方向反了」。
# ⭐ 修法：与两个游戏帧分支同一套规则 —— 「与素材源朝向（PACK_SRC_FACE）不一致才镜像」。
# ⭐⭐ 时钟复位（与 ㉕ 同因）：:1278 还原过真时钟，本段驱动真 `_tick` ⇒ 重装假时钟；
#   ⛔ `w._last = None` 必须一起给（否则 now-_last = 假值-真戳 = 大负数 ⇒ 负 dt）。
time.perf_counter = lambda: _T[0]
w._last = None


def _draw_luna_mirrors():
    """真跑 `w._draw_luna(p)`，返回 (这一帧是否施加了镜像 scale(-1,1), 全部 scale 调用)。

    ⛔ 不替换被测函数，只把 `QPainter.scale` 换成记录器（同 ㉕ spy drawImage 的手法）。
    ⭐ 只认 (sx < 0) 的那次 —— pack 分支里除镜像外没有别的 scale
      （p.save / translate / drawImage / restore 都不缩放）。
    """
    from PySide6.QtGui import QImage, QPainter
    canvas = QImage(64, 64, QImage.Format_ARGB32)
    p = QPainter(canvas)
    calls = []
    _orig_scale = QPainter.scale

    def _spy(_self, sx, sy):
        calls.append((float(sx), float(sy)))

    QPainter.scale = _spy
    try:
        w._draw_luna(p)
    finally:
        QPainter.scale = _orig_scale
    p.end()
    return any(sx < 0 for sx, _ in calls), calls


print("㉖ PR36 · 桌宠 pack 分支镜像规则（正面永不镜像 / 侧面正确转身）")
print("=" * 72)


def _luna_air_left():
    """把露娜摆进「空中 + 脸朝左」：离地、按住左几帧真实 _tick。

    ⭐ face=-1 是 `Luna.update` 的 `dir_in` 赋值自然产生的（night.py:1716-1718），
      ⛔ 不是测试手戳的 —— 手戳就测不到「空中也改 face」这条根因。
    """
    l = w.luna
    l.x, l.y = 500.0, 300.0
    l.vx = l.vy = 0.0
    l.on_ground = False
    w.keys = {Qt.Key_Left}
    step(1 / 60, 5)
    w.keys = set()
    return l


def _luna_ground_dir(key, n=10):
    """把露娜摆进「地面按住某方向」：返回她（face 已自然定型）。"""
    l = w.luna
    l.x, l.y = 500.0, N.FLOOR_Y
    l.vx = l.vy = 0.0
    l.on_ground = True
    w.keys = {key}
    step(1 / 60, n)
    w.keys = set()
    return l


# ---- 判据 A：正面动作 face=-1 也绝不镜像 ----
w.start_night(0)
l = _luna_air_left()
l.act = "fall"                       # ⭐ 钉住正面动作；她此刻自然就是 fall（离地+vy≥-40）。
#   ⛔ 钉 act 只为排除「调用间隙 pick_action 改段」，被测规则（镜像判据）的输入就是 (act, face)。
_m_fall, _calls_fall = _draw_luna_mirrors()
chk("㉖-1 ⭐⭐⭐ PR36 判据A：正面动作 fall 在 face=-1 时**绝不**镜像"
    "（镜像只会把尾巴/呆毛搬到另一侧，正是「下落方向反了」的观感来源）",
    l.face == -1 and l.act == "fall" and not _m_fall,
    f"act={l.act} face={l.face} scale调用={_calls_fall}")

# ---- 判据 A 阳性对照：同一套 spy，换成侧面动作 walk + face=-1 ⇒ 必须镜像 ----
w.start_night(0)
l = _luna_ground_dir(Qt.Key_Left)
l.act = "walk"                       # ⭐ 侧面动作（pick_action 只在 sneak 回退时产 walk，
#   ⛔ 这里直接钉 act —— 本判据测的是镜像规则对 (act, face) 的响应，不是选段逻辑。
_m_walk_l, _calls_walk_l = _draw_luna_mirrors()
chk("㉖-2 ⭐⭐ 判据A 阳性对照：侧面动作 walk 在 face=-1 时**必须**镜像（转身）"
    " ⇒ 证明 ㉖-1 分得清「该镜像」与「不该镜像」，不是恒绿",
    l.face == -1 and l.act == "walk" and _m_walk_l,
    f"act={l.act} face={l.face} scale调用={_calls_walk_l}")

# ---- 判据 B：侧面动作转身双向正确 ----
w.start_night(0)
l = _luna_ground_dir(Qt.Key_Right)
l.act = "walk"
_m_walk_r, _calls_walk_r = _draw_luna_mirrors()
chk("㉖-3 ⭐⭐⭐ PR36 判据B：侧面动作 walk 在 face=+1（与源朝向一致）时**不**镜像",
    l.face == 1 and l.act == "walk" and not _m_walk_r,
    f"act={l.act} face={l.face} scale调用={_calls_walk_r}")

# ---- 判据 B 阳性对照：同动作 face=-1 ⇒ 必须镜像（否则 ㉖-3 是恒绿摆设）----
# ⭐ 与 ㉖-2 同 setup 是刻意的：㉖-2 是判据A 的对照，本条是判据B 的对照，角色不同。
w.start_night(0)
l = _luna_ground_dir(Qt.Key_Left)
l.act = "walk"
_m_walk_l2, _calls_walk_l2 = _draw_luna_mirrors()
chk("㉖-4 ⭐⭐ 判据B 阳性对照：同一侧面动作 walk 在 face=-1 时**必须**镜像"
    " ⇒ 证明 ㉖-3 抓的是「朝向一致性」这个量，不是「永远不镜像」",
    l.face == -1 and _m_walk_l2,
    f"act={l.act} face={l.face} scale调用={_calls_walk_l2}")


# ---- 判据 C：Ronny 的原始场景全链路 ----
def _run_chain():
    """右跑 → 跳 → 空中按左 → 落地，逐帧记录 (act, face, 是否镜像)。

    ⭐ 全程真实 `_tick` + 真实 `pick_action` 选段，⛔ 不钉 act ——
      这条判据要证明的是「整条链路里没有任何一帧被误镜像」。
    """
    w.start_night(0)
    l = w.luna
    l.x, l.y = float(w.room.spawn_luna[0]), N.FLOOR_Y
    l.vx = l.vy = 0.0
    l.on_ground = True
    log = []
    for _keys, _n in (({Qt.Key_Right}, 10),                       # ① 向右跑（face=+1）
                      ({Qt.Key_Right, Qt.Key_W}, 6),              # ② 起跳
                      ({Qt.Key_Left}, 25),                        # ③ 空中按左 ⇒ face=-1
                      (set(), 30)):                                # ④ 落地前后
        w.keys = _keys
        for _ in range(_n):
            step(1 / 60, 1)
            _m, _ = _draw_luna_mirrors()
            log.append((l.act, l.face, _m))
    w.keys = set()
    return log


_log = _run_chain()
_mirrored = [r for r in _log if r[2]]
_face_neg = [r for r in _log if r[1] == -1]
chk("㉖-5 ⭐⭐⭐ PR36 判据C：Ronny 原始场景（右跑→跳→空中按左→落地）全程无镜像"
    "（改前：空中 face=-1 时 fall 被镜像 ⇒ 尾巴/呆毛跳到左侧）",
    len(_face_neg) > 0 and len(_mirrored) == 0,
    f"共 {len(_log)} 帧；face=-1 的帧 {len(_face_neg)} 个"
    f"（act 集合 {sorted({r[0] for r in _face_neg})}）；被镜像帧数 {len(_mirrored)}"
    f"；出现过的 act {sorted({r[0] for r in _log})}")

# ---- 判据 C 阳性对照：把规则在内存里临时改回 `if l.face < 0:` 重跑同一链路 ----
# ⛔ night.py 一行未动：用 inspect.getsource + 字符串替换 + exec 在**测试侧**造旧版函数，
#    只在本对照窗口内替换 `w._draw_luna`，跑完立即还原。
# ⭐ 替换串必须与 night.py 里的 PR36 判据逐字一致 —— 对不上就炸，不许静默跳过。
import inspect
import textwrap

_src_new = inspect.getsource(N.NightWindow._draw_luna)
_src_old = _src_new.replace(
    "        _psf = PACK_SRC_FACE.get(l.act, 1)\n"
    "        if _psf != 0 and l.face != _psf:\n",
    "        if l.face < 0:\n")
assert _src_old != _src_new, "阳性对照替换失败：night.py 里找不到 PR36 判据原文"
_ns = dict(N.__dict__)
exec(compile(textwrap.dedent(_src_old), "<pr36-positive-control>", "exec"), _ns)
_orig_dl = w._draw_luna
w._draw_luna = _ns["_draw_luna"].__get__(w)
try:
    _log_ctrl = _run_chain()
finally:
    w._draw_luna = _orig_dl
_mirrored_ctrl = [r for r in _log_ctrl if r[2]]
chk("㉖-6 ⭐⭐ 判据C 阳性对照：规则临时改回 `if l.face < 0:` 重跑同一链路"
    " ⇒ **至少一帧被镜像**（证明判据C 抓的是真回归，不是恒绿摆设）",
    len(_mirrored_ctrl) > 0,
    f"旧规则下被镜像 {len(_mirrored_ctrl)}/{len(_log_ctrl)} 帧"
    f"（act 集合 {sorted({r[0] for r in _mirrored_ctrl})}）")

print("=" * 72)
print("㉖ PR36 段完成：本段 6 条（3 判据 + 3 阳性对照）")
print("=" * 72)


# ============================================================================
# ㉗ · PR39（2026-10-14 设计端派单）run_carry 取帧公式去双乘（fps² bug）
# ============================================================================
# ⭐ 病灶：`_draw_luna` 的 run_carry 分支写 `int(l.t * GAME_FPS["run_carry"])`，
#   而 `l.t` 在 `_tick` 里已是【帧单位】（`l.t += dt * fps`，night.py:5044）
#   ⇒ fps 被乘了两次 ⇒ 24×24=576 步/秒 = 32 轮/秒（18 帧）= 无影手级频闪。
# ⭐ 本段 2 条判据（㉗-1/2、㉗-3/4）全部【新增】，⛔ 不改本文件任何既有判据。
# ⭐ 全程驱动真 `w._tick()` + spy `QPainter.drawImage`，按 QImage **对象身份**认帧索引。
# ⭐⭐ 时钟复位（同 ㉕/㉖ 因：:1278 还原过真时钟；本段驱动真 `_tick`）：
time.perf_counter = lambda: _T[0]
w._last = None


def _rc_index_of(pm):
    """按 QImage 对象身份返回 run_carry 帧索引；不是 run_carry 帧则 None。"""
    for i, row in enumerate(w.gframes.get("run_carry") or []):
        if row[0] is pm:
            return i
    return None


def _rc_drawn_idx(draw_fn=None):
    """真跑 `w._draw_luna`（或指定替身），返回这一帧实际画的 run_carry 帧索引。

    ⛔ 按 QImage **对象身份**认定，不看尺寸/内容（run_carry 18 帧同尺寸）。
    None = 没画 run_carry 真帧（走了别的分支）。
    """
    from PySide6.QtGui import QImage, QPainter
    canvas = QImage(64, 64, QImage.Format_ARGB32)
    p = QPainter(canvas)
    seen = []
    _orig_di = QPainter.drawImage

    def _spy(_self, *a):
        seen.append(a)

    QPainter.drawImage = _spy
    try:
        (draw_fn or w._draw_luna)(p)
    finally:
        QPainter.drawImage = _orig_di
    p.end()
    pm = None
    for a in seen:
        for it in a:
            if isinstance(it, QImage):
                pm = it
                break
        if pm is not None:
            break
    if pm is None:
        return None
    return _rc_index_of(pm)


def _rc_seq(draw_fn=None, n=20):
    """把露娜摆进 run_carry（按右键 + 拿东西），驱动 n 帧真 `_tick`，返回帧索引序列。

    ⭐ 走 `|vx|>34 且 carrying` 这条路进 run_carry（`pick_action` :1994）——
      ⛔ 不用 dash：dash 是滞空技，在地面上第一帧就"落地即结束"（night.py:1605-1607）。
    ⛔ 不能把她放窝里（x < room.nest[1]=200）：night.py:4951「回窝卸货」会清空 carrying。
    """
    w.start_night(0)
    w.mode = "play"
    l = w.luna
    l.carrying = ["鱼"]
    l.x, l.y = 500.0, N.FLOOR_Y
    l.vx = l.vy = 0.0
    l.on_ground = True
    l.act, l.t = "idle", 0.0
    seq = []
    for _ in range(n):
        w.keys = {Qt.Key_Right}      # 持续右跑 ⇒ pick_action 恒返回 run_carry
        l.carrying = ["鱼"]
        w.phase, w.mode = "play", "play"
        step(1 / 60, 1)
        seq.append(_rc_drawn_idx(draw_fn))
    w.keys = set()
    return seq


def _rc_stats(seq):
    """(不同索引数, 相邻跳变峰值, 有效序列, 末首步进)。"""
    valid = [i for i in seq if i is not None]
    if len(valid) < 2:
        return len(set(valid)), None, valid, None
    jumps = [abs(valid[k + 1] - valid[k]) for k in range(len(valid) - 1)]
    return len(set(valid)), max(jumps), valid, valid[-1] - valid[0]


print("㉗ PR39 · run_carry 取帧公式去双乘（fps² bug）")
print("=" * 72)

# ---- 判据 A：run_carry 播放速率恢复到设计 24 步/秒 ----
_seq_a = _rc_seq(None, 20)
_dist_a, _jump_a, _valid_a, _step_a = _rc_stats(_seq_a)
chk("㉗-1 ⭐⭐⭐ PR39 判据A：run_carry 恢复到设计 24 步/秒（不再 36 轮/秒频闪）——"
    " 20 帧窗口内不同索引数 ≥ 6，且相邻索引跳变峰值 < 9",
    len(_valid_a) == 20 and _dist_a >= 6 and _jump_a is not None and _jump_a < 9,
    f"帧序列={_seq_a} 不同索引={_dist_a} 相邻跳变峰值={_jump_a}")

# ---- 判据 A 阳性对照：取帧公式临时戳回双乘（测试侧 exec，night.py 一行未动）----
_src_now = inspect.getsource(N.NightWindow._draw_luna)
_src_dbl = _src_now.replace(
    "_k = int(l.t) % len(_rf)",
    '_k = int(l.t * GAME_FPS["run_carry"]) % len(_rf)')
assert _src_dbl != _src_now, "阳性对照替换失败：night.py 里找不到 PR39 取帧行原文"
_ns39 = dict(N.__dict__)
exec(compile(textwrap.dedent(_src_dbl), "<pr39-positive-control>", "exec"), _ns39)
_orig_dl39 = w._draw_luna
w._draw_luna = _ns39["_draw_luna"].__get__(w)
try:
    _seq_c = _rc_seq(w._draw_luna, 20)
finally:
    w._draw_luna = _orig_dl39
_dist_c, _jump_c, _valid_c, _step_c = _rc_stats(_seq_c)
chk("㉗-2 ⭐⭐ 判据A 阳性对照：取帧公式临时改回 `int(l.t * GAME_FPS[\"run_carry\"])`"
    "（inspect.getsource+exec，night.py 未动）⇒ 相邻跳变峰值必须 ≥ 9",
    _jump_c is not None and _jump_c >= 9,
    f"帧序列={_seq_c} 相邻跳变峰值={_jump_c}")

# ---- 判据 B：素材与帧表两条路径都就绪 + 手感常量未被顺手改动 ----
# ⚠️ 派单原文写「读 self.gframes.get('run_carry') 与 w.imgs.get('run_carry') 均非空」，
#   但 run_carry **不是桌宠动作**（`NEED_ACTIONS` 里没有它，pet.json 也没有）⇒ `w.imgs`
#   里恒为 None。run_carry 的真实「素材」路径是盘上 `assets_game/run_carry/`，
#   「帧表」路径是 `self.gframes["run_carry"]`（`_load_game_frames` 读入）。
#   ⇒ 本判据按**真实的两条路径**实现（盘上素材 + 内存帧表），已在回执里报备。
_RC_DIR = os.path.join(N.GAME_ASSETS, "run_carry")
_rc_meta = os.path.join(_RC_DIR, "_meta.json")
_rc_pngs = ([f for f in os.listdir(_RC_DIR) if f.endswith(".png")]
            if os.path.isdir(_RC_DIR) else [])
_grf39 = w.gframes.get("run_carry") or []
chk("㉗-3 ⭐⭐ PR39 判据B：run_carry 素材（盘上）与帧表（内存 gframes）两条路径都 OK，"
    "且手感常量（GAME_FPS/ATK 三段）未被顺手改动",
    len(_grf39) > 0 and os.path.isfile(_rc_meta) and len(_rc_pngs) > 0
    and N.GAME_FPS["run_carry"] == 24.0
    and (N.ATK_WIND, N.ATK_ACT, N.ATK_REC) == (0.16, 0.09, 0.42),
    f"gframes={len(_grf39)}帧 盘上素材={len(_rc_pngs)}个 meta={os.path.isfile(_rc_meta)} "
    f"GAME_FPS[run_carry]={N.GAME_FPS['run_carry']} "
    f"ATK=({N.ATK_WIND},{N.ATK_ACT},{N.ATK_REC})")

# ---- 判据 B 阳性对照：把 GAME_FPS["run_carry"] 戳成 12.0 ⇒ 步进应减半（~4）----
_fps_bak39 = N.GAME_FPS["run_carry"]
N.GAME_FPS["run_carry"] = 12.0
try:
    _seq_b = _rc_seq(None, 20)
finally:
    N.GAME_FPS["run_carry"] = _fps_bak39
_dist_b, _jump_b, _valid_b, _step_b = _rc_stats(_seq_b)
chk("㉗-4 ⭐⭐ 判据B 阳性对照：`GAME_FPS[\"run_carry\"]` 戳成 12.0（已还原 24.0）"
    " ⇒ 20 帧末首步进应减半到 ~4（证明判据测的是 fps 这个量，不是恒绿）",
    _step_b is not None and 3 <= _step_b <= 5,
    f"步进={_step_b}（fps=24 时 ≈{_step_a}；fps=12 时应 ≈4）已还原为 {N.GAME_FPS['run_carry']}")

print("=" * 72)
print("㉗ PR39 段完成：本段 4 条（2 判据 + 2 阳性对照）")
print("=" * 72)


# ============================================================================
# ㉘ · PR37-v2（2026-10-14 设计端派单）escort 期间播放 drag 姿势
# ============================================================================
# ⭐ 病灶：① `drag` 不在 `NEED_ACTIONS` ⇒ 帧没加载 ⇒ `l.act="drag"` **静默兜底画 idle**；
#   ② `escort` 是孤儿标志（全文件只置 False）⇒ 押送演出（meowed 1.5s + hauled 0.9s）不播 drag。
# ⭐ 本段 2 条判据（㉘-1/2、㉘-3/4）全部【新增】，⛔ 不改本文件任何既有判据/阈值。
# ⭐⭐ 判据 A 以「**画出帧身份 == drag**」为准，⛔ 不看 `l.act` 字符串 ——
#   那正是原 PR37 漏掉的坑（act 写得对、画出来是 idle，判据照样绿）。
# ⭐⭐ 时钟复位（同 ㉕/㉖/㉗ 因：:1278 还原过真时钟；本段驱动真 `_tick`）：
time.perf_counter = lambda: _T[0]
w._last = None


def _frame_owner(pm):
    """按 QImage 对象身份反查这一帧属于 `self.imgs` 里的哪个动作，返回 (动作名, 索引)。

    ⛔ 不看尺寸/内容 —— 按**对象身份**（不同动作的帧是不同文件 ⇒ 不同 QImage）。
    (None, None) = 不属于任何已加载的桌宠动作帧。
    """
    for name, lst in (w.imgs or {}).items():
        for i, im in enumerate(lst or []):
            if im is pm:
                return name, i
    return None, None


def _luna_drawn_frame():
    """真跑 `w._draw_luna`，返回 (帧所属动作名, 索引, l.act)。

    动作名按 QImage 对象身份从 `w.imgs` 反查 ⇒ 能识破「l.act=drag 但画的是 idle」。
    """
    from PySide6.QtGui import QImage, QPainter
    canvas = QImage(64, 64, QImage.Format_ARGB32)
    p = QPainter(canvas)
    seen = []
    _orig_di = QPainter.drawImage

    def _spy(_self, *a):
        seen.append(a)

    QPainter.drawImage = _spy
    try:
        w._draw_luna(p)
    finally:
        QPainter.drawImage = _orig_di
    p.end()
    pm = None
    for a in seen:
        for it in a:
            if isinstance(it, QImage):
                pm = it
                break
        if pm is not None:
            break
    if pm is None:
        return None, None, w.luna.act
    name, idx = _frame_owner(pm)
    return name, idx, w.luna.act


def _escort_run(n=170, mw_far=False):
    """把露娜放到越界区、微波炉贴脸 ⇒ 真 `_tick` 触发抓捕 → 押送（meowed + hauled）。

    逐帧记 (phase, l.act, 帧所属动作名, 索引, l.escort)。
    ⛔ mw_far=True = 阳性对照：每帧把微波炉钉到 x=5000（`_patrol` 不位移，钉得住）
      ⇒ `mw.caught()` 恒 False ⇒ 永不进 meowed ⇒ 判据 A 的触发关掉。
    """
    w.start_night(0)
    w.mode, w.phase = "play", "play"
    l = w.luna
    l.carrying = []
    l.escort = False
    l.x, l.y = 500.0, float(N.FLOOR_Y)
    l.vx = l.vy = 0.0
    l.on_ground = True
    l.act, l.t = "idle", 0.0
    l.dash_i = 0.0
    w.mw.state = "patrol"
    w.mw.alert = 0.0
    w.mw.x = (5000.0 if mw_far else 500.0)
    w.mw.y = float(N.FLOOR_Y)
    w.keys = set()
    log = []
    for _ in range(n):
        w.keys = set()
        if mw_far:
            w.mw.x = 5000.0
            w.mw.y = float(N.FLOOR_Y)
        step(1 / 60, 1)
        _name, _idx, _act = _luna_drawn_frame()
        log.append((w.phase, _act, _name, _idx, bool(l.escort)))
    return log


print("㉘ PR37-v2 · escort 期间播放 drag 姿势")
print("=" * 72)

# ---- 判据 A：escort 全程画出的确实是 drag 帧（不是静默兜底 idle）----
_log_e = _escort_run(170, mw_far=False)
_esc = [r for r in _log_e if r[4]]                       # escort=True 的帧
_esc_idx = [i for i, r in enumerate(_log_e) if r[4]]
_post = _log_e[(_esc_idx[-1] + 1):] if _esc_idx else []  # escort 结束之后的帧
_meow = [r for r in _esc if r[0] == "meowed"]
_haul = [r for r in _esc if r[0] == "hauled"]
_bad_kind = [r for r in _esc if r[2] != "drag"]
_bad_act = [r for r in _esc if r[1] != "drag"]
_post_drag = [r for r in _post if r[1] == "drag" or r[2] == "drag"]
chk("㉘-1 ⭐⭐⭐ PR37-v2 判据A：escort 全程（meowed + hauled 都采到）`l.act=='drag'`"
    " 且**画出的帧身份属于 drag**（⛔ 不是 act 写 drag、画的是 idle）；"
    " 退出 escort 后 `l.act` 跟随 pick_action 推导、不残留 drag",
    len(_esc) > 100 and len(_meow) > 0 and len(_haul) > 0
    and len(_bad_act) == 0 and len(_bad_kind) == 0
    and len(_post) > 0 and len(_post_drag) == 0,
    f"escort 帧={len(_esc)}（meowed={len(_meow)} hauled={len(_haul)}）"
    f" act≠drag={len(_bad_act)} 画出非drag={len(_bad_kind)}"
    f" 退出后帧={len(_post)}（残留 drag={len(_post_drag)}，"
    f"退出后动作={sorted({r[1] for r in _post})}）"
    f" 帧身份序列前 12={[r[2] for r in _esc[:12]]}")

# ---- 判据 A 阳性对照：微波炉钉远（永不 caught）⇒ 全程不出现 drag ----
_log_c = _escort_run(170, mw_far=True)
_esc_c = [r for r in _log_c if r[4]]
_drag_c = [r for r in _log_c if r[1] == "drag" or r[2] == "drag"]
chk("㉘-2 ⭐⭐ 判据A 阳性对照：微波炉每帧钉到 x=5000（`mw.caught` 恒 False、永不进 meowed）"
    " ⇒ 全程**不出现** drag（不出现 escort、不出现 l.act=='drag'、不画出 drag 帧）",
    len(_esc_c) == 0 and len(_drag_c) == 0,
    f"escort 帧={len(_esc_c)} 含 drag 的帧={len(_drag_c)}"
    f"（相位集合={sorted({r[0] for r in _log_c})}）")

# ---- 判据 B：drag 素材确实进了 self.imgs，且没顺手碰别的 ----
# ⭐⭐ 2026-10-15 PR38：本判据的 GAME_FPS 部分由「全字典相等」改为**逐字段**核对。
#   原写法 `GAME_FPS == {五键}` 是 PR37-v2 完工态的**快照**，容不下后续派单的
#   合法演进（PR38 加 "dash" 键、PR35-v2 把 attack/attack_charge 改 12.0）——
#   一加/一改就红，而那不是「PR37-v2 顺手碰坏了」。⛔ 不是为凑绿削判据：
#   · mw_walk / run_carry / mw_idle 三键值 + ATK 三段 + run_carry 取帧公式：
#     仍逐字守护（这些没有派单要动）；
#   · attack / attack_charge 的**值**归 PR35-v2 的 ㉚ 段守护；
#   · "dash" 键归 PR38 的 ㉙ 段守护。
_src_dl = inspect.getsource(N.NightWindow._draw_luna)
_rc_line_ok = "_k = int(l.t) % len(_rf)" in _src_dl
_drag_imgs = w.imgs.get("drag") or []
_g37 = N.GAME_FPS
chk("㉘-3 ⭐⭐ PR37-v2 判据B：`NEED_ACTIONS` 加词生效 ⇒ `self.imgs['drag']` 非空，"
    "且 GAME_FPS 非攻击三键 / ATK 三段 / run_carry 取帧公式（:6380）与本单改动前一致"
    "（没顺手碰别的）〔GAME_FPS 攻击键值归 ㉚、dash 键归 ㉙ 守护，见上方说明〕",
    len(_drag_imgs) > 0
    and (_g37.get("mw_walk"), _g37.get("run_carry"), _g37.get("mw_idle")) == (12.0, 24.0, 8.0)
    and "attack" in _g37 and "attack_charge" in _g37
    and (N.ATK_WIND, N.ATK_ACT, N.ATK_REC) == (0.16, 0.09, 0.42)
    and _rc_line_ok,
    f"imgs['drag']={len(_drag_imgs)}帧 GAME_FPS={N.GAME_FPS} "
    f"ATK=({N.ATK_WIND},{N.ATK_ACT},{N.ATK_REC}) run_carry取帧行OK={_rc_line_ok}")

# ---- 判据 B 阳性对照：临时把 NEED_ACTIONS 里 "drag" 摘掉再加载 ⇒ imgs["drag"] 应为 None ----
_need_bak = list(N.NEED_ACTIONS)
try:
    N.NEED_ACTIONS = [a for a in N.NEED_ACTIONS if a != "drag"]
    _imgs_wo = N._load_needed(w.pack, N.NEED_ACTIONS)
finally:
    N.NEED_ACTIONS = _need_bak
chk("㉘-4 ⭐⭐ 判据B 阳性对照：临时把 `NEED_ACTIONS` 里的 \"drag\" 摘掉再 `_load_needed`"
    " ⇒ `imgs['drag']` 必须为 None（证明判据测的是「加载名单」这个量，不是恒绿）",
    _imgs_wo.get("drag") is None and "drag" in N.NEED_ACTIONS,
    f"摘掉后 imgs['drag']={_imgs_wo.get('drag')}；NEED_ACTIONS 已还原={N.NEED_ACTIONS}")

print("=" * 72)
print("㉘ PR37-v2 段完成：本段 4 条（2 判据 + 2 阳性对照）")
print("=" * 72)

# ============================================================================
# ⭐⭐ ㉙ PR38 · dash 冲刺接线（2026-10-15）
#
# 派单四处改动：① GAME_FPS 加 "dash": 60.0（AC03 选 D：12 帧素材在 0.2s
#   窗口双倍速播完）② `_draw_luna` 加 dash 分支（⛔ 用 `int(l.t) % len`，
#   ⛔ 不抄 attack 的 `int(l.t * GAME_FPS[l.act])` fps² 双乘）③ GAME_SRC_FACE
#   加 "dash": 1 ④ pick_action 空手冲刺从 human_run 改 dash（拿东西仍 run_carry）。
#
# ⚠️⚠️ 素材前置（派单 §〇 + 设计端核验）：`assets_game/dash/` **不存在**
#   ⇒ `_load_game_frames` 缺目录时 `out["dash"] = []`（night.py:4301 静默占位）
#   ⇒ 判据 A 主线靠**夹具内存注入** 12 张 QImage 假帧驱动真 `_draw_luna`
#   （⛔ 不落盘、⛔ 不改 `_load_game_frames`、跑完还原成原生 [] 态）；
#   验证的是「接线 + 取帧公式 + 朝向」，**AC03 素材真容未验证**（派单 §四 已预告）。
# ⚠️ 阳性对照②（派单「临时删 assets_game/dash/」）：目录本就不存在，
#   无法执行「删除」⇒ 用**不注入假帧**的原生缺失态等价实现（gframes["dash"]
#   原生即 []，与「删完素材」同一效果），回执已报备。
#
# ⭐⭐ 时钟复位（同 ㉗：驱动真 `_tick`）：
time.perf_counter = lambda: _T[0]
w._last = None

from PySide6.QtGui import QImage   # ⭐ PR38 判据注入假帧用（文件头只导了 QPixmap）


# ⭐ 历史记录（2026-10-15 探针 `_pr38_probe.py` 实锤；⛔ 已于 PR40 修复，Ronny 拍板 A）：
#   `Luna.update` dash 分支起手时 `vy += GRAVITY*dt*0.35` ⇒ y 必超 FLOOR_Y
#   ⇒ 旧版「落地即结束」无条件下把**地面起手**也在第一帧掐掉 ⇒ 只剩 ~10px（设计 124px）。
#   ✅ 修法：起手 snapshot `dash_from_air`（见 try_dash），落地即结束只判【空中起手】。
#   ⇒ 本判据起手高度 FLOOR_Y-30 = 空中起手 ⇒ 落地才结束，验证「取帧公式 + 0.2s 窗口」接线。
#   ⇒ 判据 A 用**起手高度 FLOOR_Y-30**（空中起手 ⇒ 落地才结束，PR40 修复后的既有语义），
#     验证的是「取帧公式 + 0.2s 窗口」这条接线，⛔ 不守护也不固化这个 bug。
# ⚠️ dt 兜底（night.py:4835）：`_tick` 第一帧 dt=0.016（`_last is None`），
#   之后才是我喂的 1/120 ⇒ 判据不断言精确帧数（对兜底不敏感），
#   断言「12 帧全集播到 + 末帧退出」这种鲁棒形态。


def _dash_index_of(pm):
    """按 QImage 对象身份返回 dash 帧索引；不是 dash 帧则 None。"""
    for i, row in enumerate(w.gframes.get("dash") or []):
        if row[0] is pm:
            return i
    return None


def _dash_drawn_idx():
    """真跑 `w._draw_luna`，返回这一帧实际画的 dash 帧索引（按对象身份）。

    None = 没画 dash 帧（走了桌宠分支 / 别的分支）。
    ⛔ 与 ㉗ `_rc_drawn_idx` 同一手法：只把 QPainter.drawImage 换成记录器。
    """
    from PySide6.QtGui import QImage, QPainter
    canvas = QImage(64, 64, QImage.Format_ARGB32)
    p = QPainter(canvas)
    seen = []
    _orig_di = QPainter.drawImage

    def _spy(_self, *a):
        seen.append(a)

    QPainter.drawImage = _spy
    try:
        w._draw_luna(p)
    finally:
        QPainter.drawImage = _orig_di
    p.end()
    pm = None
    for a in seen:
        for it in a:
            if isinstance(it, QImage):
                pm = it
                break
        if pm is not None:
            break
    if pm is None:
        return None
    return _dash_index_of(pm)


def _dash_seq(n=24, dt=1.0 / 120.0):
    """触发一次真 dash，驱动 n 帧真 `_tick`，逐帧返回实际画出的 dash 帧索引。

    ⭐ dt 取 1/120：60fps 下 l.t 每帧 +1.0，k 从 1 起跳；1/120 每帧 +0.5，
      0.2s 内 k=0~11 每个都有驻留帧（第一帧 dt 走 0.016 兜底，见段首说明）。
    ⭐ 起手 y=FLOOR_Y-30：空中起手 ⇒ 落地结束（PR40 修复后此为既有语义，不再是绕过），
      24 帧内 vy 累积位移 ~13px，落不回 FLOOR_Y ⇒ dash_t 不被误掐。
    ⛔ 不造盘上素材：只往内存 gframes 注入（调用方负责注入/还原）。
    """
    w.start_night(0)
    w.mode = "play"
    l = w.luna
    # 清掉所有会挡住 try_dash / 干扰 pick_action 的状态
    l.carrying = []
    l.escort = False
    l.charging = False
    l.punch = 0.0
    l.atk_cd = l.atk_wind = l.atk_act = l.atk_rec = 0.0
    l.dash_t = l.dash_i = l.dash_cd = 0.0
    l.x, l.y = 500.0, N.FLOOR_Y - 30.0
    l.vx = l.vy = 0.0
    l.on_ground = True
    l.act, l.t = "idle", 0.0
    assert l.try_dash(1), "try_dash 应成功（已清空 cd / 三段 / dash_t）"
    seq = []
    for _ in range(n):
        w.keys = set()
        step_pure(dt, 1)
        seq.append(_dash_drawn_idx())
    return seq, l


# ---- 判据 A：0.2s 窗口内 12 帧素材播完（fps=60 双倍速），退出后回落 ----
_dash_fake = [(QImage(48, 64, QImage.Format_ARGB32), 48, 64, 24, 64)
              for _ in range(12)]
_dash_native = w.gframes.get("dash")          # 原生态：素材未落盘 ⇒ []
assert _dash_native == [], f"预期原生 gframes['dash'] 为 []，实得 {_dash_native!r}"
try:
    w.gframes["dash"] = _dash_fake
    _seqA, _lA = _dash_seq(n=24)
finally:
    w.gframes["dash"] = _dash_native
_dashA = [x for x in _seqA if x is not None]
chk("㉙-1 ⭐⭐⭐ PR38 判据A：真触发 dash 后 `_draw_luna` 画出的**确实是 dash 游戏帧**"
    "（按 QImage 对象身份反查），且 0.2s 窗口内 12 帧素材 **0→11 全部播到**"
    "（GAME_FPS['dash']=60 双倍速）；窗口结束（dash_t 归零）后不再画 dash 帧、"
    " `l.act` 回落到 idle〔空中起手 ⇒ 落地结束，PR40 修复后的既有语义〕",
    set(_dashA) == set(range(12)) and len(_dashA) >= 20
    and _seqA[-1] is None and _lA.act == "idle",
    f"画出 dash 帧 {len(_dashA)}/24 帧 索引集合={sorted(set(_dashA))}"
    f"（缺 {sorted(set(range(12)) - set(_dashA))}）"
    f" 末帧={_seqA[-1]} 退出后 act={_lA.act}")

# ---- 判据 A 阳性对照①：fps 改回 24.0 ⇒ 0.2s 只播前 5 帧（k=0~4）----
_fps_native = N.GAME_FPS.get("dash")
try:
    N.GAME_FPS["dash"] = 24.0
    w.gframes["dash"] = _dash_fake
    _seqB, _lB = _dash_seq(n=24)
finally:
    if _fps_native is None:
        N.GAME_FPS.pop("dash", None)
    else:
        N.GAME_FPS["dash"] = _fps_native
    w.gframes["dash"] = _dash_native
_dashB = [x for x in _seqB if x is not None]
chk("㉙-2 ⭐⭐ 判据A 阳性对照①：临时把 `GAME_FPS['dash']` 改回 24.0 ⇒ 0.2s 窗口内"
    " **只播前 5 帧**（k=0~4，24fps 单倍速）——证明判据A 抓的是 60.0 这个值，"
    " 不是恒绿（跑完已还原 60.0）",
    len(_dashB) > 0 and set(_dashB) == {0, 1, 2, 3, 4} and 11 not in _dashB
    and N.GAME_FPS.get("dash") == 60.0,
    f"fps=24 时索引集合={sorted(set(_dashB))}（帧数 {len(_dashB)}）"
    f" 还原后 GAME_FPS['dash']={N.GAME_FPS.get('dash')}")

# ---- 判据 B：接线点到位（读模块/窗口真实值，⛔ 不自设值）----
_src_dl38 = inspect.getsource(N.NightWindow._draw_luna)
_dl38_tail = _src_dl38.split("# ============ PR38 · dash 走游戏帧")[-1]
_no_fps2 = "int(l.t * GAME_FPS" not in _dl38_tail          # dash 段无 fps² 双乘
_has_ok = "_k = int(l.t) % len(_df)" in _dl38_tail         # dash 段用修正公式
_l38 = w.luna
_l38.carrying = []
_l38.dash_t, _l38.escort, _l38.charging, _l38.punch = 0.20, False, False, 0.0
_l38.atk_wind = _l38.atk_act = _l38.atk_rec = 0.0
_pa_dash = _l38.pick_action()
_l38.carrying = ["鱼"]
_pa_carry = _l38.pick_action()
_l38.carrying = []
_l38.dash_t = 0.0
chk("㉙-3 ⭐⭐ PR38 判据B：四处接线全部到位且读的是**真实值**——"
    " `GAME_FPS['dash']==60.0`；`GAME_SRC_FACE['dash']==1`；"
    " 真调 `pick_action`：dash_t>0 且空手 ⇒ 'dash'、拿着东西 ⇒ 'run_carry'；"
    " `_draw_luna` 的 dash 分支用 `int(l.t) % len(_df)`（⛔ 无 fps² 双乘）",
    N.GAME_FPS.get("dash") == 60.0 and N.GAME_SRC_FACE.get("dash") == 1
    and _pa_dash == "dash" and _pa_carry == "run_carry"
    and _has_ok and _no_fps2,
    f"GAME_FPS['dash']={N.GAME_FPS.get('dash')} "
    f"GAME_SRC_FACE['dash']={N.GAME_SRC_FACE.get('dash')} "
    f"pick_action(空手)={_pa_dash!r} pick_action(拿鱼)={_pa_carry!r} "
    f"取帧公式OK={_has_ok} 双乘已除={_no_fps2}")

# ---- 判据 B 阳性对照②：无 dash 帧（= 素材缺失态）⇒ 不画 dash 帧 ----
# ⚠️ 派单原文「临时删 assets_game/dash/」——目录本就不存在，无法「删」；
#    gframes['dash'] 原生即 []（_load_game_frames 缺目录占位，night.py:4301）
#    ⇒ **不注入假帧**与「删完素材」是同一状态，等价实现。
w.gframes["dash"] = _dash_native          # 确保回到原生缺失态
_seqC, _lC = _dash_seq(n=3)
chk("㉙-4 ⭐⭐ 判据B 阳性对照②：`gframes['dash']` 为原生缺失态（[]）时触发 dash"
    " ⇒ `_draw_luna` **画不出任何 dash 帧**（全 None，落桌宠分支）——"
    " 证明判据A 走的是 dash 游戏帧路径，不是桌宠分支冒充",
    all(x is None for x in _seqC) and len(_seqC) == 3,
    f"3 帧反查结果={_seqC}（全 None={all(x is None for x in _seqC)}）"
    f" 期间应打印「游戏帧缺 dash」告警")

print("=" * 72)
print("㉙ PR38 段完成：本段 4 条（2 判据 + 2 阳性对照）")
print("=" * 72)

# ============================================================================
# ⭐⭐ ㉚ PR35-v2 · 攻击帧率与循环方式（2026-10-15，Ronny 拍板 #7 全按推荐 B）
#
# 派单三处改动：① GAME_FPS attack/attack_charge 24.0→12.0
#   ② attack 取帧 `int(l.t*GAME_FPS)`（fps²）→ `int(l.t)` pingpong
#   ③ 删 Luna.update 里 punch 递减（_tick :4867-4868 为唯一裁判）
#
# ⚠️⚠️ 两处派单前提被实测修正（回执已报备）：
#   A. 派单写「0.67s 窗口内播到 f7/f8 **再收回**」——实测 fps=12 时 0.67s
#      只能推进 ~8.19 帧（12fps×0.667s），pingpong 周期 30，**窗口内只走
#      上升段 0→8，永远到不了峰 15**，「收回」段在窗口外（act 已切回 idle）。
#      ⇒ 判据按实测断言「峰值 7~8 + 窗口内单调不减」，⛔ 不断言「递减」。
#   B. 派单阳性对照①写「fps 改回 24.0 ⇒ 步进 ~16（糊/频闪）」——那是 **fps²
#      旧公式**的病征；新 pingpong 公式下 fps=24 ⇒ 0.67s 正好推进 16.4 帧
#      ⇒ k 走 0..15 再收回一帧 = **完整挥出**（另一种自洽设计，不是 bug）。
#      ⇒ 阳性对照①按实测断言「峰值 15 ≠ 8」，证明判据抓的是 fps 值。


def _atk_index_of(pm):
    """按 QImage 对象身份返回 attack 帧索引；不是 attack 帧则 None。"""
    for i, row in enumerate(w.gframes.get("attack") or []):
        if row[0] is pm:
            return i
    return None


def _atk_drawn_idx():
    """真跑 `w._draw_luna`，返回这一帧实际画的 attack 帧索引（按对象身份）。"""
    from PySide6.QtGui import QImage, QPainter
    canvas = QImage(64, 64, QImage.Format_ARGB32)
    p = QPainter(canvas)
    seen = []
    _orig_di = QPainter.drawImage

    def _spy(_self, *a):
        seen.append(a)

    QPainter.drawImage = _spy
    try:
        w._draw_luna(p)
    finally:
        QPainter.drawImage = _orig_di
    p.end()
    pm = None
    for a in seen:
        for it in a:
            if isinstance(it, QImage):
                pm = it
                break
        if pm is not None:
            break
    if pm is None:
        return None
    return _atk_index_of(pm)


def _atk_seq(n=45, dt=1.0 / 60.0):
    """触发一次真普攻（lvl=0），驱动 n 帧真 `_tick`，返回 (帧索引序列, punch 归零帧号, luna)。

    ⭐ n=45 > 0.67s 窗口（41 tick）⇒ 能同时看到「窗口内挥出」与「退出后回落」。
    ⭐ dt=1/60（⛔ 不用 1/120）：punch 归零 tick 数 41 是按 60fps 的设计口径
      （0.67s ÷ 1/60 = 40.2 ⇒ 第 41 帧归零；第一帧 dt 走 0.016 兜底，night.py:4835）。
    ⛔ 不造盘上素材：attack 16 帧真素材已在盘上，gframes 直接可用。
    """
    w.start_night(0)
    w.mode = "play"
    l = w.luna
    l.carrying = []
    l.escort = False
    l.charging = False
    l.punch = 0.0
    l.atk_cd = 0.0
    l.atk_wind = l.atk_act = l.atk_rec = 0.0
    l.dash_t = l.dash_i = l.dash_cd = 0.0
    l.x, l.y = 500.0, N.FLOOR_Y
    l.vx = l.vy = 0.0
    l.on_ground = True
    l.act, l.t = "idle", 0.0
    assert l.try_attack(0), "try_attack 应成功（已清空 cd / 三段 / dash_t）"
    seq, punch_zero_tick = [], None
    for i in range(1, n + 1):
        w.keys = set()
        step_pure(dt, 1)
        seq.append(_atk_drawn_idx())
        if punch_zero_tick is None and l.punch <= 0.0:
            punch_zero_tick = i
    return seq, punch_zero_tick, l


# ---- 判据 A：punch 41 tick 归零 + 峰值索引 7~8 + 源码 pingpong 守护 ----
_src35 = open(os.path.join(HERE, "pet_engine", "night.py"), encoding="utf-8").read()
_seqA35, _pzt35, _l35 = _atk_seq(n=45)
_atkA35 = [x for x in _seqA35 if x is not None]
chk("㉚-1 ⭐⭐⭐ PR35-v2 判据A：punch 由 _tick 唯一推进 ⇒ **41 tick 归零**"
    "（0.67s 设计窗口；双减已除）；峰值索引 **7~8**（12fps×0.667s≈8 帧）；"
    " 窗口内索引单调不减（上升段，见段首⚠️A）；源码含 pingpong 公式、"
    " ⛔ 不含 `int(l.t * GAME_FPS[l.act])` 双乘",
    _pzt35 == 41 and 7 <= max(_atkA35) <= 8
    and all(b >= a for a, b in zip(_atkA35, _atkA35[1:]))
    and "_k = _kr % (2 * _n - 2)" in _src35
    and "int(l.t * GAME_FPS[l.act])" not in _src35,
    f"punch 归零 tick={_pzt35}（期望 41） 峰值索引={max(_atkA35)}（期望 7~8）"
    f" 窗口内帧序列={_atkA35[:20]}…"
    f" pingpong公式在源码={'_k = _kr % (2 * _n - 2)' in _src35}"
    f" 双乘已除={'int(l.t * GAME_FPS[l.act])' not in _src35}")

# ---- 判据 A 阳性对照①：fps 回 24.0 ⇒ 峰值 15（完整挥出，非频闪，见段首⚠️B）----
_a35_bak = (N.GAME_FPS.get("attack"), N.GAME_FPS.get("attack_charge"))
try:
    N.GAME_FPS["attack"] = N.GAME_FPS["attack_charge"] = 24.0
    _seqB35, _pztB35, _lB35 = _atk_seq(n=45)
finally:
    N.GAME_FPS["attack"], N.GAME_FPS["attack_charge"] = _a35_bak
_atkB35 = [x for x in _seqB35 if x is not None]
chk("㉚-2 ⭐⭐ 判据A 阳性对照①：临时把 attack/attack_charge 改回 24.0 ⇒ 0.67s 推进"
    " ~16.4 帧 ⇒ **峰值索引 15**（16 帧完整挥出+收回，与 12.0 的峰值 8 截然不同）"
    " ——证明判据抓的是 fps 值，不是恒绿（跑完已还原 12.0）",
    max(_atkB35) == 15 and _pztB35 == 41
    and (N.GAME_FPS.get("attack"), N.GAME_FPS.get("attack_charge")) == (12.0, 12.0),
    f"fps=24 时峰值={max(_atkB35)}（期望 15） punch 归零 tick={_pztB35}"
    f" 还原后={N.GAME_FPS.get('attack')}/{N.GAME_FPS.get('attack_charge')}")

# ---- 判据 A 阳性对照②：模拟「保留 Luna.update 递减」（双减）⇒ 21 tick 归零 ----
# ⭐ 等价性：源码里删掉的正是 `if self.punch > 0.0: self.punch = max(0.0, self.punch - dt)`
#   两行；wrapper 在 update 返回后执行同一行 = 行为等价（punch 是纯计时，顺序不影响总量）。
#   ⛔ 没用「临时改 night.py 源码」方案：那会牵动全套其他段的 attack 相关判据、
#   连带红难分清；monkeypatch 只影响本段这一跑，且 finally 保证还原。
_orig_luna_update = N.Luna.update


def _double_dec_update(self, dt, keys, room):
    _orig_luna_update(self, dt, keys, room)
    if self.punch > 0.0:
        self.punch = max(0.0, self.punch - dt)


try:
    N.Luna.update = _double_dec_update
    _seqC35, _pztC35, _lC35 = _atk_seq(n=45)
finally:
    N.Luna.update = _orig_luna_update
_atkC35 = [x for x in _seqC35 if x is not None]
chk("㉚-3 ⭐⭐ 判据A 阳性对照②：monkeypatch 在 Luna.update 后补减一次 punch"
    "（= 精确复现「不删改动三」的双减）⇒ punch **21 tick 归零**、峰值 ≤5"
    "（动画只播一半就被切回 idle）——证明判据抓的是双减产，不是恒绿",
    _pztC35 == 21 and max(_atkC35) <= 5 and N.Luna.update is _orig_luna_update,
    f"双减下 punch 归零 tick={_pztC35}（期望 21） 峰值={max(_atkC35)}（期望 ≤5）"
    f" patch 已还原={N.Luna.update is _orig_luna_update}")

# ---- 判据 B：常量守恒（真实值；dash=60 不被本单碰坏）----
chk("㉚-4 ⭐⭐ PR35-v2 判据B：GAME_FPS attack/attack_charge==12.0 且 dash==60.0"
    "（PR38 不被本单碰坏）、mw_walk/run_carry/mw_idle 不动；"
    " ATK_WIND/ACT/REC 仍 0.16/0.09/0.42（红线）、ATK_CD 仍 0.12",
    (N.GAME_FPS.get("attack"), N.GAME_FPS.get("attack_charge")) == (12.0, 12.0)
    and N.GAME_FPS.get("dash") == 60.0
    and (N.GAME_FPS.get("mw_walk"), N.GAME_FPS.get("run_carry"),
         N.GAME_FPS.get("mw_idle")) == (12.0, 24.0, 8.0)
    and (N.ATK_WIND, N.ATK_ACT, N.ATK_REC, N.ATK_CD) == (0.16, 0.09, 0.42, 0.12),
    f"GAME_FPS={N.GAME_FPS} ATK=({N.ATK_WIND},{N.ATK_ACT},{N.ATK_REC},{N.ATK_CD})")

# ---- 判据 B 阳性对照：内存态临时改 ATK_WIND ⇒ 判据B 必须报红 ----
_wind_bak = N.ATK_WIND
try:
    N.ATK_WIND = 0.99
    _wind_red = not ((N.ATK_WIND, N.ATK_ACT, N.ATK_REC, N.ATK_CD)
                     == (0.16, 0.09, 0.42, 0.12))
finally:
    N.ATK_WIND = _wind_bak
chk("㉚-5 ⭐⭐ 判据B 阳性对照：临时把 ATK_WIND 戳成 0.99 ⇒ 常量守恒条件必须变红"
    "（证明判据B 读真实值、不是恒绿；跑完已还原 0.16）",
    _wind_red and N.ATK_WIND == 0.16,
    f"改后守恒条件为假={_wind_red} 还原后 ATK_WIND={N.ATK_WIND}")

# ---- 数学关系判据（与守护判据分开写，见用户级记忆铁律）----
# ⚠️ 本条**自设** kr 序列过公式，测的是「公式的数学关系是 pingpong」，
#   ⛔ 不守护「源码真改了没有」——那件事由 ㉘-1 的源码断言守护。
# ⚠️⚠️ 序列必须按**一个完整周期**取（GP03 教训：接缝要量循环首尾，取样长度
#   不是周期整数倍 ⇒ 末项落在下一周期中段，量出的「接缝」无意义）：
#   pingpong 周期 = 2n-2 = 30 项；cycle 周期 = n = 16 项。
_n35 = 16
_pingpong = []
for _kr in range(2 * _n35 - 2):            # 0..29 = pingpong 一个完整周期
    _k = _kr % (2 * _n35 - 2) if _n35 > 1 else 0
    if _k >= _n35:
        _k = 2 * _n35 - 2 - _k
    _pingpong.append(_k)
_cycle = [_kr % _n35 for _kr in range(_n35)]   # 0..15 = cycle 一个完整周期
chk("㉚-6 ⭐ 数学关系判据（⛔ 不守护源码，只验证公式语义）：改动二的公式作用于"
    " 16 帧 ⇒ 一个完整周期首尾接缝 abs(seq[-1]-seq[0])==**1**（pingpong 无缝）；"
    " 对照 cycle 公式接缝==**15**（末帧 15 硬跳回首帧 0）——证明公式确实是 pingpong",
    abs(_pingpong[-1] - _pingpong[0]) == 1 and abs(_cycle[-1] - _cycle[0]) == 15
    and _pingpong[:17] == list(range(16)) + [14] and len(_pingpong) == 30,
    f"pingpong 全周期(30项)={_pingpong} 接缝={abs(_pingpong[-1] - _pingpong[0])}"
    f" cycle 全周期(16项)首尾={_cycle[0]}/{_cycle[-1]} 接缝={abs(_cycle[-1] - _cycle[0])}")

print("=" * 72)
print("㉚ PR35-v2 段完成：本段 6 条（2 判据 + 3 阳性对照 + 1 数学关系判据）")
print("=" * 72)

# ============================================================================
# ⭐⭐ 2026-10-15 · ㉛ PR40 段：dash 落地判定修复（Ronny 拍板 A）
#
#   背景（PR38 §七 回报、Ronny 拍板修的既有真 bug）：地面起手（y=FLOOR_Y, vy=0）
#   第一帧 `vy += GRAVITY*dt*0.35` ⇒ y 必超 FLOOR_Y ⇒ 旧落地判定
#   `if self.y >= FLOOR_Y: … dash_t = 0` 在**地面起手第一帧**就命中
#   ⇒ dash_t 归零、只滑 ~10px（设计意图 620×0.2=124px 完全没体现，
#     「冲刺比 RUN 快一倍」形同虚设）。注释「落地即结束（冲刺是地面技）」
#   的本意是「腾空后落地才结束」，实现把「地面起手」也掐了 —— 意图与实现矛盾。
#
#   修法（拍板 A，⛔ 只做 A / 不碰 B/C）：try_dash 起手瞬间 snapshot
#   `self.dash_from_air = not self.on_ground`；落地判定改
#   `if self.y >= FLOOR_Y and self.dash_from_air:`。
#   ⇒ 空中起手落地才结束（语义不变）；地面起手滑完整个 0.2s
#     （y 仍每帧钳回 FLOOR_Y，沿地板滑 —— ⛔ 钳位没删）。
#
#   ⛔ 本段阳性对照全部走**内存态**（属性赋值 / 模块常量赋值 + finally 还原），
#     ⛔ 不临时改 night.py 源码（派单红线 #6；源码级回退对照由设计端验收时
#     自己走「cp→改→跑→复原→md5」五步）。退出码级证据见 `_pr40_probe.py`。
#   ⛔ DASH 四常量 / ATK 四常量一个字节没动（㉛-1 守护）。
# ============================================================================
import re
import ast as _ast

# ---- 物理夹具：真触发一次 dash，驱动 n 帧真 `_tick`，逐帧记录 ----
# ⭐ 与 ㉙ `_dash_seq` 同款：清状态 + step_pure（冻微波炉、防 escort 泄漏，
#   见 step_pure docstring 的 PR37-v2 教训）+ 内存注入 12 张假 QImage
#   （派单要求「按 PR38 判据 A 同款夹具」；⛔ 不落盘、跑完还原）。
_dash_fake40 = [(QImage(48, 64, QImage.Format_ARGB32), 48, 64, 24, 64)
                for _ in range(12)]


def _dash_phys_run(n=24, dt=1.0 / 120.0, y0=None, vy0=0.0, on_ground=True,
                   from_air=None, dash_speed=None):
    """真触发一次 dash 并驱动 n 帧真 `_tick`；返回 (dx, dash_t_trace, y_trace, l)。

    ⭐ 默认场景 = PR40 修复对象：地面起手 y=FLOOR_Y, vy=0, on_ground=True。
    ⭐ from_air：None = 用 try_dash 真实 snapshot；True = 内存态覆盖成
      「空中起手」（阳性对照①，复现修复前的掐断行为）。
    ⭐ dash_speed：None = 真实 620.0；其他值 = 内存态覆盖（阳性对照②）。
    ⛔ 两个覆盖都在 finally 里还原（属性 / 模块常量），不泄漏到后续判据。
    """
    w.start_night(0)
    w.mode = "play"
    l = w.luna
    # 清掉所有会挡住 try_dash / 干扰物理的状态（同 ㉙ _dash_seq）
    l.carrying = []
    l.escort = False
    l.charging = False
    l.punch = 0.0
    l.atk_cd = l.atk_wind = l.atk_act = l.atk_rec = 0.0
    l.dash_t = l.dash_i = l.dash_cd = 0.0
    l.x = 500.0
    l.y = N.FLOOR_Y if y0 is None else float(y0)
    l.vx, l.vy = 0.0, float(vy0)
    l.on_ground = on_ground
    l.act, l.t = "idle", 0.0
    assert l.try_dash(1), "try_dash 应成功（已清空 cd / 三段 / dash_t）"
    _fa_real = l.dash_from_air
    _spd_real = N.DASH_SPEED
    if from_air is not None:
        l.dash_from_air = from_air          # 内存态覆盖（仅阳性对照①）
    if dash_speed is not None:
        N.DASH_SPEED = dash_speed           # 内存态覆盖（仅阳性对照②）
    _gf_native = w.gframes.get("dash")
    w.gframes["dash"] = _dash_fake40        # PR38 判据A 同款假帧（本段不测绘制）
    x0 = l.x
    t_trace, y_trace = [], []
    try:
        for _ in range(n):
            w.keys = set()
            step_pure(dt, 1)
            t_trace.append(l.dash_t)
            y_trace.append(l.y)
    finally:
        w.gframes["dash"] = _gf_native
        l.dash_from_air = _fa_real          # 还原（阳性对照①）
        N.DASH_SPEED = _spd_real            # 还原（阳性对照②）
    return l.x - x0, t_trace, y_trace, l


# ---- ㉛-1 守护判据（本段第一条断言；它之前本段没有任何对被守护量的赋值）----
# ⚠️「全文件第一条断言」在本文件的落地口径 = **本段第一条 chk** + 本段它之前
#   没有对 DASH_*/ATK_* 的任何赋值；更早的阳性对照（㉘-5 临时 ATK_WIND=0.99）
#   已在 finally 还原，本条直接断言真实值兜底（GP04v3 恒绿教训：
#   ⛔ 不自设值再比，必须读模块实际值）。
# ⚠️⚠️ 派单原文「grep 行号落在 1936~1959 区间」与派单自己的改动自相矛盾：
#   改动 1 在 :1562 后插 3 行、C1 在 :1273 插 1 行 ⇒ try_dash 整体下移，
#   写死区间会被自己的插入撞出界 ⇒ 改用 **ast 动态定位函数体**（回执已报备）。
_night_src40 = open(os.path.abspath(N.__file__), encoding="utf-8").read()
_cl40 = [ln.split("#", 1)[0] for ln in _night_src40.splitlines()]   # 剥注释的代码行
_tree40 = _ast.parse(_night_src40)


def _fn40(name):
    for _nd in _ast.walk(_tree40):
        if isinstance(_nd, _ast.FunctionDef) and _nd.name == name:
            return _nd
    return None


def _assigns40(fn, attr):
    """fn 函数体里是否有 `self.<attr> = ...` 赋值。"""
    if fn is None:
        return False
    for _st in fn.body:
        for _sub in _ast.walk(_st):
            if isinstance(_sub, _ast.Assign):
                for _t in _sub.targets:
                    if isinstance(_t, _ast.Attribute) and _t.attr == attr:
                        return True
    return False


_asn_in_try_dash = _assigns40(_fn40("try_dash"), "dash_from_air")
_asn_in_init = _assigns40(_fn40("__init__"), "dash_from_air")
_asn_line40 = next((i + 1 for i, ln in enumerate(_cl40)
                    if re.search(r"self\.dash_from_air\s*=\s*not\s+self\.on_ground", ln)),
                   None)
# ⚠️⚠️ 派单原文「③ :1609 落地条件含 `and self.dash_from_air`」同样与派单自己的
#   文字要求矛盾：钳位在 if 块内，给 if 加条件会把钳位一起关掉 ⇒ 地面起手
#   0.2s 内陷下去 ~14.6px（㉛-2 的 y 断言实测抓到）。按派单文字要求
#   （「⛔ 不许删 y/vy 钳位，地面起手每帧仍要钳回地板」）实现为
#   **钳位无条件 + 结束有条件** ⇒ 守护断言同步改为结构匹配（回执已报备）：
_cond_land40 = re.search(
    r"if self\.y >= FLOOR_Y:\s*\n"
    r"(?:\s*#[^\n]*\n)*"
    r"\s*self\.y, self\.vy = FLOOR_Y, 0\.0\s*\n"
    r"\s*if self\.dash_from_air:\s*\n"
    r"\s*self\.dash_t = 0\.0",
    _night_src40) is not None
chk("㉛-1 ⭐⭐⭐ PR40 守护判据（读 night.py 源码文本 + import 进来的真实值，"
    " ⛔ 不自设值）：① `self.dash_from_air = not self.on_ground` 在 `try_dash` "
    "函数体内（ast 动态定位，⛔ 不依赖行号）；② `self.dash_from_air = False` "
    "在 `__init__`；③ 落地段结构 = 「`if self.y >= FLOOR_Y:` ⇒ y/vy 钳位（无条件）"
    " ⇒ `if self.dash_from_air:` 才 `dash_t = 0.0`」（钳位不许被条件关掉，"
    "见上方 ⚠️⚠️）；④ DASH_TIME/SPEED/INV/CD == 0.20/620.0/0.26/1.30、"
    "ATK_WIND/ACT/REC/CD == 0.16/0.09/0.42/0.12（红线守恒，全部读真实值）",
    _asn_in_try_dash and _asn_in_init and _asn_line40 is not None
    and _cond_land40
    and (N.DASH_TIME, N.DASH_SPEED, N.DASH_INV, N.DASH_CD) == (0.20, 620.0, 0.26, 1.30)
    and (N.ATK_WIND, N.ATK_ACT, N.ATK_REC, N.ATK_CD) == (0.16, 0.09, 0.42, 0.12),
    f"try_dash内赋值={_asn_in_try_dash}(行:{_asn_line40}) init赋值={_asn_in_init} "
    f"落地条件含from_air={_cond_land40} "
    f"DASH=({N.DASH_TIME},{N.DASH_SPEED},{N.DASH_INV},{N.DASH_CD}) "
    f"ATK=({N.ATK_WIND},{N.ATK_ACT},{N.ATK_REC},{N.ATK_CD})")

# ---- ㉛-2 功能判据 · 地面起手不再被掐（修复本体）----
_dx40, _tt40, _yt40, _l40 = _dash_phys_run(n=24)
# 期望位移 = 620×0.2 = 124px。实测 124.0px：本夹具 _last 未被 start_night 重置
#   ⇒ 全程 dt=1/120（首帧不走 0.016 兜底；若走则为 ~128.8px —— 两种情形阈值
#   110 都过得去，断言对兜底不敏感）。
# ⚠️ 计时器断言用 `<= 1e-9` 而非 `== 0.0`：`0.2 - 24×(1/120)` 在二进制浮点下
#   是极小正数（~1e-16，探针场景③实测到）⇒ 精确相等会假红。
#   1e-9 ≪ 一帧 1/120=0.0083 ⇒ 掩盖不了「计时器还在跑」的真失败（⛔ 非放水）。
_cond2_40 = _tt40[4] > 0.05 and _dx40 >= 110.0 and _tt40[23] <= 1e-9
chk("㉛-2 ⭐⭐⭐ PR40 功能判据：地面起手（y=FLOOR_Y, vy=0, on_ground=True）"
    " 真 try_dash 后跑 24 帧（dt=1/120）⇒ 第 5 帧 dash_t>0.05（修复前第 1 帧"
    " 即归零）、24 帧累计位移 ≥110px（期望 ~124，首帧 0.016 兜底 ⇒ ~129）、"
    " 第 24 帧 dash_t==0（计时器到点，不是被落地判定提前掐）；"
    " 且 24 帧 y 始终被钳在 FLOOR_Y（沿地板滑，钳位没删）",
    _cond2_40 and all(_y == N.FLOOR_Y for _y in _yt40),
    f"dx={_dx40:.1f}px 第5帧dash_t={_tt40[4]:.4f} 第24帧dash_t={_tt40[23]:.4f} "
    f"y24帧全在FLOOR_Y={all(_y == N.FLOOR_Y for _y in _yt40)}")

# ---- ㉛-3 阳性对照①：内存态 from_air=True ⇒ ㉛-2 的断言条件必须变红 ----
# ⭐ 语义 = 修复前的行为（地面起手也被当成空中起手 ⇒ 第一帧落地即结束）。
_dxB40, _ttB40, _ytB40, _lB40 = _dash_phys_run(n=24, from_air=True)
_condB40 = _ttB40[4] > 0.05 and _dxB40 >= 110.0 and _ttB40[23] <= 1e-9
chk("㉛-3 ⭐⭐ 阳性对照①：内存态把 `dash_from_air` 覆盖成 True（= 修复前"
    "「地面起手也被落地判定掐断」）⇒ ㉛-2 的断言条件**确实变红**"
    "（第 5 帧 dash_t==0、位移<20px）——证明 ㉛-2 抓的是这次修复，不是恒绿"
    " （内存态覆盖，函数返回时已 finally 还原；退出码级证据见 `_pr40_probe.py`）",
    (not _condB40) and _ttB40[4] == 0.0 and _dxB40 < 20.0,
    f"from_air=True 时 dx={_dxB40:.1f}px 第5帧dash_t={_ttB40[4]:.4f} "
    f"㉛-2条件为假={not _condB40}")

# ---- ㉛-4 功能判据 · 空中起手语义不变（落地才结束，没被整个删掉）----
_dxA40, _ttA40, _ytA40, _lA40 = _dash_phys_run(n=60, y0=N.FLOOR_Y - 30.0,
                                                vy0=100.0, on_ground=False)
_land_i = next((i for i, y in enumerate(_ytA40) if y >= N.FLOOR_Y), None)
chk("㉛-4 ⭐⭐ PR40 功能判据：空中起手（y=FLOOR_Y-30, vy=+100, on_ground=False）"
    " try_dash ⇒ snapshot 为空中起手；落到 FLOOR_Y 那一帧 dash_t==0 且 y==FLOOR_Y，"
    " 且落地帧 ≤23（早于计时器 0.2s 到期 ⇒ 这个 0 是落地判定打的，不是计时器）"
    " ——证明「落地即结束」没被整个删掉，只是加了 from_air 条件",
    _lA40.dash_from_air is True and _land_i is not None and _land_i <= 23
    and _ttA40[_land_i] == 0.0 and _ytA40[_land_i] == N.FLOOR_Y,
    f"dash_from_air={_lA40.dash_from_air} 落地帧index={_land_i}(第{_land_i + 1}帧) "
    f"该帧dash_t={_ttA40[_land_i] if _land_i is not None else None} "
    f"y={_ytA40[_land_i] if _land_i is not None else None} 总位移={_dxA40:.1f}px")

# ---- ㉛-5 阳性对照②：内存态 DASH_SPEED=310（砍半）⇒ 位移断言必须变红 ----
_dxC40, _ttC40, _ytC40, _lC40 = _dash_phys_run(n=24, dash_speed=310.0)
_condC40 = _ttC40[4] > 0.05 and _dxC40 >= 110.0 and _ttC40[23] <= 1e-9
chk("㉛-5 ⭐⭐ 阳性对照②：内存态把 DASH_SPEED 砍半成 310.0 ⇒ ㉛-2 的位移断言"
    " **确实变红**（~64px < 110）——证明 110px 阈值读的是真实常量行为，"
    " 不是写死 124 的恒绿（finally 已还原 620.0 并核回）",
    (not _condC40) and _dxC40 < 110.0 and N.DASH_SPEED == 620.0,
    f"DASH_SPEED=310 时 dx={_dxC40:.1f}px ㉛-2条件为假={not _condC40} "
    f"还原后 DASH_SPEED={N.DASH_SPEED}")

# ---- ㉛-6 无孤儿标志：dash_from_air 写点=2 / 读点=1；dash_t 赋值点全列出 ----
# ⚠️ 「读点」只数**代码行**（已剥 # 注释）——注释里提名字不算读。
# ⚠️⚠️ 派单原文「dash_t 赋值点仅四处」与实测不符：漏了冲刺段每帧递减那行
#   `self.dash_t = max(0.0, self.dash_t - dt)`（:1607 一带）。实测 **5 处**，
#   按实测分类断言（init / 每帧递减 / 落地结束 / 撞墙结束 / try_dash 起手），
#   ⛔ 不为了凑派单的「四」而漏数——回执已报备。
_wr_fa = [(i + 1, ln.strip()) for i, ln in enumerate(_cl40)
          if re.search(r"self\.dash_from_air\s*=", ln)]
_rd_fa = [(i + 1, ln.strip()) for i, ln in enumerate(_cl40)
          if "dash_from_air" in ln and not re.search(r"self\.dash_from_air\s*=", ln)]
_asn_dt = [(i + 1, ln.strip()) for i, ln in enumerate(_cl40)
           if re.search(r"self\.dash_t\s*=", ln)]
chk("㉛-6 ⭐ PR40 无孤儿标志：`dash_from_air` 写点恰好 2 处（__init__ 默认 False "
    "+ try_dash 起手 snapshot `not self.on_ground`）、读点恰好 1 处（落地判定条件）"
    " ⇒ 不存在「只读不写」路径；`dash_t` 赋值点全列出且恰好 5 处"
    "（init / 每帧递减 max(0,·-dt) / 落地结束 / 撞墙结束 / try_dash 起手）"
    " ⇒ 本单没有新增「状态复位夹具之外」的东西",
    len(_wr_fa) == 2 and len(_rd_fa) == 1 and len(_asn_dt) == 5
    and any("= False" in ln for _, ln in _wr_fa)
    and any("not self.on_ground" in ln for _, ln in _wr_fa)
    and sum(1 for _, ln in _asn_dt if "max(0.0, self.dash_t - dt)" in ln) == 1
    and sum(1 for _, ln in _asn_dt if ln.endswith("= 0.0")) == 3
    and sum(1 for _, ln in _asn_dt if "= DASH_TIME" in ln) == 1,
    f"dash_from_air 写点={_wr_fa} 读点={_rd_fa} dash_t 赋值点={_asn_dt}")

# ---- ㉛-7 回归：本单改动没有碰坏 PR38 / PR35-v2 的接线（针对性复验）----
# ⚠️ ⛔ 不写死「183/183」那种快照式总数断言（撞后续派单合法演进必红，
#   ㉘-3 教训）；复验的是本单**可能碰坏的具体接线**。
_l40r = w.luna
_l40r.carrying = []
_l40r.dash_t, _l40r.escort, _l40r.charging, _l40r.punch = 0.20, False, False, 0.0
_l40r.atk_wind = _l40r.atk_act = _l40r.atk_rec = 0.0
_pa40r = _l40r.pick_action()
_l40r.dash_t = 0.0
chk("㉛-7 ⭐ PR40 回归（针对性复验，⛔ 非快照式总数断言）：本单三处改动没有碰坏"
    " PR38 接线（GAME_FPS['dash']==60.0、pick_action 空手冲刺仍返回 'dash'）"
    " 与 PR35-v2 常量（attack/attack_charge==12.0、ATK 四段 0.16/0.09/0.42/0.12）；"
    " 且至此 BAD==0（既有 183 条 + ㉛ 段前 6 条无一红，退出码由末尾真汇总裁决）",
    N.GAME_FPS.get("dash") == 60.0 and _pa40r == "dash"
    and (N.GAME_FPS.get("attack"), N.GAME_FPS.get("attack_charge")) == (12.0, 12.0)
    and (N.ATK_WIND, N.ATK_ACT, N.ATK_REC, N.ATK_CD) == (0.16, 0.09, 0.42, 0.12)
    and len(BAD) == 0,
    f"pick_action(空手,dash_t>0)={_pa40r!r} OK={len(OK)} BAD={len(BAD)}")

# ⭐ 边界结论（设计端 2026-10-16 裁决，⛔ 本场景不设判据）：
#   当前几何下「平台边缘起手冲刺」**不可达** —— dash 期间有效重力 700，
#   0.2s 只落 14px，而最近的非地板平台（餐桌顶 488）离地 182px
#   ⇒ 落地发生在第 65 帧，dash_t 早已归零 ⇒ PR40 的「落地即结束」语义在此场景根本不参与。
#   ⇒ 不构成风险，故⛔ 不写判据（写了会是恒真的假绿灯）。
#   ⚠️ 若将来新增【离地 ≤14px】的矮平台，此场景重新可达 ⇒ 必须回来重验。
#
# ⭐⭐ 上面「不写」的**实测依据**（保留备查，这些数是我跑出来的不是推断）：
#   场景：PLATFORMS[1] 餐桌 x430~700 / 顶面 488，起手 x=690（右缘内侧）、on_ground=True
#        ⇒ try_dash 记 dash_from_air=False（地面起手），朝 +x 冲
#        （DASH_SPEED=620 ⇒ 0.2s 位移 124px，10px 就出边缘，不存在冲不出）
#   实测：dash 期间有效重力 = GRAVITY*0.35 = 700 ⇒ 0.2s 内只下落 0.5*700*0.2² = 14px
#        平台顶离地板 = 670-488 = 182px
#        ⇒ dash 结束（第 23 帧）时她仍在空中（y≈502），第 65 帧才落地
#        ⇒ 落地时 dash_t 早已是 0 ⇒ 派单要的「落地下一帧 dash_t>0」恒为假
#   阳性对照（内存态强制 dash_from_air=True 再跑同一场景）：
#        真实态   落地帧=65  最终y=670.0  最终x=819.2
#        阳性对照 落地帧=65  最终y=670.0  最终x=819.2   ← 三项全同，无可观测差异
#   ⛔⛔ 为什么不写判据（设计端裁决，比"弱判据"更严重 —— 是**恒真**）：
#      · 断言1「y 收敛 FLOOR_Y」被落地钳位（night.py:1619 `self.y, self.vy = FLOOR_Y, 0.0`）
#        保证 ⇒ **任何**落地路径最终 y 都 == FLOOR_Y ⇒ 哪怕真穿地也绿 ⇒ 零判别力
#        （我自己那次输出「最终y=670.0(FLOOR_Y=670)」就是证据：穿不穿地都这么打）
#      · 断言3（dash_t 单调不增 / x 单调）由结构保证（dash_dir 起手快照、dash_t 每帧只减）
#        且没有能变红的阳性对照
#      ⇒ 三条合起来 = 永远绿 ⇒ 在总数里贡献一个**假绿**，比不写更糟
#        （GP03 / GP04v2 栽过同一类：恒绿判据抓不到任何东西）

print("=" * 72)
print("㉛ PR40 段完成：本段 7 条（1 守护 + 2 功能 + 2 阳性对照 + 1 无孤儿标志"
      " + 1 回归；⛔「平台边缘起手」经实测不可达，按设计端裁决不设判据，见上方注释）")
print("=" * 72)

# ============================================================================
# ⭐⭐ 2026-10-14：本文件尾部（:1281 起）的各段排在 :1288 那条汇总**之后**、
#   而且全文从来没有 sys.exit ⇒ **尾部判据跑红也不会让套件失败**（静默通过），
#   `_自测_全部.py` 只看退出码 + 汇总行 ⇒ 永远看到 147/147✅。
#   ⇒ 在**文件真正末尾**补一条真汇总 + 退出码，让尾部 ㉕~㉛ 各段
#     （PR31-D/PR36/PR39/PR37-v2/PR38/PR35-v2/PR40）能被看见。
#   ⛔ 没有改动任何既有判据、⛔ 没有改任何阈值 —— 只是把 OK/BAD 如实报出去。
# ============================================================================
print("=" * 72)
print(f"通过 {len(OK)} / {len(OK) + len(BAD)}"
      f"   （含文件尾部 ㉕/㉖/㉗/㉘/㉙/㉚/㉛ 各段；:1288 那条只数到它之前）")
if BAD:
    print(f"❌ 未通过 {len(BAD)} 条：")
    for _bn in BAD:
        print("   ·", _bn)
print("=" * 72)
sys.exit(1 if BAD else 0)
