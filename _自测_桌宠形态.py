# -*- coding: utf-8 -*-
"""_自测_桌宠形态.py —— SJ02 · 产品形态四件（4-2/4-4/4-5/4-7）的自测

⛔⛔ 纪律（照 GP04v3 的教训）：
    **S-1 / S-2 是本文件最前面两条 chk**，且必须**读真实运行态** ——
    做法是开**子进程 + 受控 env** 去跑真实 ui.py（不是本进程里给 env 赋个值再断言）。
    ⇒ 谁把 4-7 的开关改掉（或干脆删了条件、或干脆删了功能），这两条立刻报红。

阳性对照（每条都必须能"被故意破坏后报红"）：
    S-1 双向：默认无 ⭐ / 开开关有 ⭐
    S-2 双向：默认零输出 / 开开关有输出
    S-3：清掉持久化标记 ⇒ 引导必须再出现
    S-4：外部占住锁 ⇒ 获取必须失败且不崩
    S-5：删掉设置文件 ⇒ 必须回落默认值
    S-6：默认态顺序快照 / 开发态顺序快照（双向）
"""
import os
import subprocess
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = HERE
PROBE = os.path.join(HERE, "_work", "_sj02", "_probe.py")
sys.path.insert(0, os.path.join(HERE, "pet_engine"))

from PySide6.QtCore import Qt                       # noqa: E402
from PySide6.QtWidgets import QApplication          # noqa: E402
import ui as U                                      # noqa: E402

app = QApplication.instance() or QApplication([])

OK, BAD = [], []


def chk(name, cond, info=""):
    (OK if cond else BAD).append(name)
    print(f"{'  OK ' if cond else ' FAIL'}  {name}   {info}")


PY = sys.executable


def run_probe(mode, debug=False):
    """在**受控 env** 里跑真实探针；返回 (stdout, stderr, rc)。

    ⛔ debug=False 时**明确从 env 里 pop 掉** LUNAPET_DEBUG
      ⇒ 保证「默认态」可复现（不受运行者本机会话影响）。
    """
    env = dict(os.environ)
    env["QT_QPA_PLATFORM"] = "offscreen"
    if debug:
        env["LUNAPET_DEBUG"] = "1"
    else:
        env.pop("LUNAPET_DEBUG", None)
    p = subprocess.run([PY, PROBE, mode], capture_output=True, text=True,
                       env=env, timeout=300)
    return p.stdout, p.stderr, p.returncode


def titles_of(out):
    return [ln[2:] for ln in out.splitlines() if ln.startswith("T:")]


# ============================================================================
# S-1（⛔ 本文件第一条断言 · 读真实运行态）
# ============================================================================
_out1, _err1, _rc1 = run_probe("menu", debug=False)
_t1 = titles_of(_out1)
_vis1 = [t for t in _t1 if t != "---"]
chk("S-1 ⭐⭐ SJ02 4-7 守护（默认启动 / 无 LUNAPET_DEBUG，子进程真实运行态）："
    " 托盘菜单**不含**两个 ⭐ 开发期项，且含「显示 / 隐藏」与「设置…」",
    _rc1 == 0 and _vis1 and not any("⭐" in t for t in _t1)
    and "显示 / 隐藏" in _vis1 and "设置…" in _vis1,
    f"rc={_rc1} 菜单={_t1}")

# ---- S-1 阳性对照：开开关 ⇒ 两个 ⭐ 必须重新出现（证明不是把菜单项删了）----
_out1p, _err1p, _rc1p = run_probe("menu", debug=True)
_t1p = titles_of(_out1p)
_n_star = sum(1 for t in _t1p if "⭐" in t)
chk("S-1 阳性对照：设 `LUNAPET_DEBUG=1` 重跑 ⇒ 两个 ⭐ 项**必须回来**"
    "（证明 4-7 是条件显示，⛔ 不是删功能）",
    _rc1p == 0 and _n_star == 2,
    f"rc={_rc1p} ⭐项数={_n_star} 菜单={_t1p}")

# ============================================================================
# S-2（⛔ 本文件第二条断言 · 读真实运行态）
# ============================================================================
_out2, _err2, _rc2 = run_probe("banner", debug=False)
_all2 = (_out2 or "") + (_err2 or "")
chk("S-2 ⭐⭐ SJ02 4-7 守护（默认启动 / 无 LUNAPET_DEBUG，子进程真实运行态）："
    " 控制台**零输出**（启动横幅不打印）",
    _rc2 == 0 and _all2.strip() == "",
    f"rc={_rc2} stdout+stderr={_all2!r}")

# ---- S-2 阳性对照：开开关 ⇒ 必须有输出（证明 print 是被条件化，不是被删掉）----
_out2p, _err2p, _rc2p = run_probe("banner", debug=True)
_all2p = (_out2p or "") + (_err2p or "")
chk("S-2 阳性对照：设 `LUNAPET_DEBUG=1` 重跑 ⇒ 必须打印启动横幅"
    "（证明 4-7 是把 print 条件化，⛔ 不是把 print 删了）",
    _rc2p == 0 and "[引擎] 已启动" in _all2p,
    f"rc={_rc2p} 含横幅={'[引擎] 已启动' in _all2p} 输出={_all2p.strip()[:60]!r}")

# ============================================================================
# S-3 · 首次启动引导（4-2）
# ============================================================================
_orig_settings = U.load_settings()          # 跑完要还原，别动 Ronny 的真设置
_st = U.load_settings()
_st["guided"] = False
U.save_settings(_st)
_g1 = U.maybe_first_run_guide(None)         # 第一次 ⇒ 应该有
_g2 = U.maybe_first_run_guide(None)         # 第二次 ⇒ 应该是 None
_no_focus = bool(_g1 is not None
                 and (_g1.windowFlags() & Qt.WindowDoesNotAcceptFocus))
chk("S-3 ⭐ SJ02 4-2：首次运行给出引导卡片、第二次运行**不再出现**；"
    " 且卡片带 `WindowDoesNotAcceptFocus`（⛔ 4-6 不抢焦点，系统层面就不收焦点）",
    _g1 is not None and _g2 is None and _no_focus,
    f"第一次={type(_g1).__name__ if _g1 is not None else None} "
    f"第二次={type(_g2).__name__ if _g2 is not None else None} "
    f"不收焦点={_no_focus}")
if _g1 is not None:
    _g1.close()

# ---- S-3 阳性对照：删掉持久化标记 ⇒ 必须再出现 ----
_st = U.load_settings()
_st["guided"] = False
U.save_settings(_st)
_g3 = U.maybe_first_run_guide(None)
chk("S-3 阳性对照：把持久化标记清掉 ⇒ 引导卡片**必须再出现**"
    "（证明 4-2 是持久化判定，⛔ 不是写死跳过）",
    _g3 is not None,
    f"清标记后={type(_g3).__name__ if _g3 is not None else None}")
if _g3 is not None:
    _g3.close()

# ============================================================================
# S-4 · 单实例（4-5）
# ============================================================================
_si1 = U._acquire_single_instance()
_ok1 = _si1 is not None
_si2 = U._acquire_single_instance()         # 第二次 ⇒ 必须 None（不叠第二个窗口）
if _si1 is not None:
    _si1[0].unlock()                        # 释放，别污染后面
chk("S-4 ⭐ SJ02 4-5：第一次拿到单实例锁（主实例）、第二次**拿不到**"
    " ⇒ 第二次会走「激活已有实例后退出」，不产生第二个窗口",
    _ok1 and _si2 is None,
    f"第一次获取={_ok1} 第二次获取={_si2 is not None}")

# ---- S-4 阳性对照：外部占住锁 ⇒ 第一次也必须拿不到，且不崩 ----
from PySide6.QtCore import QLockFile        # noqa: E402
_ext = QLockFile(U._single_lock_path())
_ext.setStaleLockTime(30 * 1000)
_ext_ok = _ext.tryLock(0)
_si3 = U._acquire_single_instance()
_notified = U._notify_existing_instance()   # 喊不到也只返回 False，不许崩
if _ext_ok:
    _ext.unlock()
chk("S-4 阳性对照：外部把锁文件占住 ⇒ `_acquire_single_instance()` 必须返回 None，"
    " 且 `_notify_existing_instance()` 不崩（返回 bool）",
    _ext_ok and _si3 is None and isinstance(_notified, bool),
    f"外部占锁={_ext_ok} 获取结果={_si3 is not None} 喊话返回={_notified}")

# ============================================================================
# S-5 · 设置项四项可读写并落盘（4-4）
# ============================================================================
U.save_settings({"scale": 130, "speed": 1.4, "opacity": 80,
                 "autostart": False, "guided": True})
_a5 = U.load_settings()
chk("S-5 ⭐ SJ02 4-4：设置四项（缩放/速度/透明度/开机自启）写入后重新读取，值一致",
    _a5["scale"] == 130 and abs(_a5["speed"] - 1.4) < 1e-6
    and _a5["opacity"] == 80 and _a5["autostart"] is False and _a5["guided"] is True,
    f"读回={_a5}")

# ---- S-5 阳性对照：删掉设置文件 ⇒ 必须回落默认值（不是崩、不是留旧值）----
try:
    if os.path.exists(U._settings_path()):
        os.remove(U._settings_path())
    _removed = True
except Exception as e:
    _removed = False
    print(f"[S-5] 删文件失败：{e}")
_d5 = U.load_settings()
chk("S-5 阳性对照：删掉设置文件 ⇒ `load_settings()` 必须回落**默认值**"
    "（证明读的是盘上真实文件，不是读一个常量/缓存）",
    _removed and _d5 == U.DEFAULT_SETTINGS,
    f"删掉={_removed} 读回={_d5}")

# ============================================================================
# S-6 · 托盘顺序快照（4-4 要求「显示/隐藏 与 退出」相对顺序不变）
# ============================================================================
_EXPECT_DEFAULT = ["显示 / 隐藏", "设置…", "---", "退出"]
chk("S-6 ⭐ SJ02 4-4/4-7：默认启动的托盘顺序**逐位**等于快照"
    f" {_EXPECT_DEFAULT}（「显示/隐藏」「退出」相对顺序未变，「设置…」在分隔符之前）",
    _t1 == _EXPECT_DEFAULT,
    f"实际={_t1} 期望={_EXPECT_DEFAULT}")

# ---- S-6 阳性对照：开发态的快照是另一串 ⇒ 证明这是真比对，不是恒等 ----
_EXPECT_DEBUG = ["显示 / 隐藏", "⭐ 重新加载素材（不用重启）", "⭐ 手感调试面板",
                 "设置…", "---", "退出"]
chk("S-6 阳性对照：开发态（LUNAPET_DEBUG=1）的托盘顺序是**另一串**更长快照"
    " ⇒ 证明 S-6 比的是真实菜单内容，不是拿常量糊弄",
    _t1p == _EXPECT_DEBUG,
    f"实际={_t1p} 期望={_EXPECT_DEBUG}")

# ---- 收尾：还原 Ronny 真实设置 ----
U.save_settings(_orig_settings)
print("=" * 72)
print(f"通过 {len(OK)} / {len(OK) + len(BAD)}")
if BAD:
    print(f"❌ 未通过 {len(BAD)} 条：")
    for _b in BAD:
        print("   ·", _b)
print("=" * 72)
sys.exit(1 if BAD else 0)
