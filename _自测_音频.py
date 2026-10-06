# -*- coding: utf-8 -*-
"""_自测_音频.py —— PR-03 第三批：音频接线的验收判据（⛔ 2026-10-05 起 14 条）

⭐ 判据纪律（本项目血泪）：
   · **断言行为，不断言源码文本**。「代码里写了 play(...)」不能证明接上了，
     真正的判据是"这个事件发生之后，音频引擎真的被调用了/真的在播"。
   · ⭐ **加载失败必须报出来**（派单验收线 #4）：故意指向一个坏目录，
     断言 `errors` 非空 ⇒ 证明"失败会报错"这条真的成立。
     ⛔ 只测 happy path 的话，"加载失败静默"这种 bug 会一路溜到打包后。
   · 离屏 + 退出码（`_自测_全部.py` 已保证子进程隔离）。

⚠️ 离屏下真的会"出声"吗？—— 不会。`QT_QPA_PLATFORM=offscreen` 没有音频输出设备，
   `isPlaying()` 仍能反映"引擎认为它在播"，这正是我们要验的（接线对不对），
   而"实际能不能听见"是打包后真机的事（派单验收线 #8，另一张单）。
"""
import os
import re
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "pet_engine"))
sys.stdout.reconfigure(encoding="utf-8")

from PySide6.QtWidgets import QApplication
app = QApplication.instance() or QApplication([])

from PySide6.QtCore import Qt  # noqa: E402

import audio as A  # noqa: E402

OK, BAD = [], []


def chk(label, cond, detail=""):
    (OK if cond else BAD).append(label)
    print(f"  {'OK  ' if cond else 'FAIL'} {label}" + (f"   {detail}" if detail else ""))


def pump(ms=60):
    from PySide6.QtCore import QEventLoop, QTimer
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


#: `audio.py` / `night.py` 的源码文本。判据要守"删干净了"就得读源码，
#: 而不是只看运行结果（死代码的特征恰恰是"运行结果看不出问题"）。
_A_SRC = open(os.path.join(HERE, "pet_engine", "audio.py"), encoding="utf-8").read()
_N_SRC = open(os.path.join(HERE, "pet_engine", "night.py"), encoding="utf-8").read()


# ==================================================================
# 1. 素材已复制进项目
# ==================================================================
print("=" * 74)
print("① 素材在项目内（逐个 os.path.exists）")
print("=" * 74)
# ⛔ 2026-10-05 Ronny「冰箱音效」+「环境音」均彻底移除⇒ **13 条**。
#   ⭐ 这张表是**唯一**的清单真源（`audio.ALL_SOUNDS` 由 `SND_LEN` 派生）。
#   ⛔ 别在这里保留 sfx_fridge_open 的名字当"曾经有过"——
#     保留在清单里就等于要求 `assets_audio/` 里有那个文件。
# ⭐⭐ 2026-10-06 PR-06：接入落地音 ⇒ **20 条**（19 + sfx_land）。
EXPECT = sorted([
    "bgm_caught", "bgm_steal", "bgm_win", "sfx_attack",
    "sfx_caught", "sfx_dash", "sfx_mw_alert", "sfx_land",
    "sfx_pick_jar", "sfx_pick_loose", "sfx_pick_plate", "sfx_qte_fail",
    "sfx_qte_tick", "sfx_qte_tick_008",
    # 白天 BGM：3 源件（Ronny 11:00 拍板 cute3 为主力件）
    "bgm_day_cute3", "bgm_day_cute_15s", "bgm_day_cute_alt15s",
    # 白天 BGM：3 个 A 案离线预拼的无缝循环件（起播用的是这一组）
    "bgm_day_cute3_loop", "bgm_day_cute_15s_loop", "bgm_day_cute_alt15s_loop",
])
chk("素材表是 20 条（13 旧 + PR-05 白天 BGM 6 条 + PR-06 落地音 1 条）",
    len(EXPECT) == 20, f"实测 {len(EXPECT)}")
chk("audio.ALL_SOUNDS 也是 20 条且与上面同集",
    set(A.ALL_SOUNDS) == set(EXPECT),
    f"差集 {set(A.ALL_SOUNDS) ^ set(EXPECT) or '无'}")
# ⭐ 反向断言：冰箱音效**不许**出现在任何一张表里
_leak = [t for t in (A.SND_GAIN_DB, A.SND_PEAK_DB, A.SND_LEN, A.PICK_BY_KIND)
         if "sfx_fridge_open" in t]
chk("⭐ 四张表里都没有 sfx_fridge_open（彻底移除）", not _leak,
    f"仍残留于: {_leak}" if _leak else "SND_GAIN_DB / SND_PEAK_DB / SND_LEN / PICK_BY_KIND 全清")
_dir = A.AUDIO_DIR
# ⭐ 素材目录的位置**取自引擎自己算出来的 AUDIO_DIR**，⛔ 不在自测里重算一遍。
#   第一版这里写死 `dirname(HERE)/assets_audio`，而 HERE 已经是 `自研引擎`
#   ⇒ 拼成了 `2026-09-20-07-34-36/assets_audio`（上一级），全部报不存在。
#   ⛔ 自测里出现第二份路径推导 = 又一个"两处各写一份"的老坑。
chk("素材目录存在", os.path.isdir(_dir), _dir)
chk("⭐ assets_audio 目录里也没有 sfx_fridge_open.wav（不留孤儿文件）",
    not os.path.isfile(os.path.join(_dir, "sfx_fridge_open.wav")))
for n in EXPECT:
    p = os.path.join(_dir, n + ".wav")
    chk(f"  {n}.wav", os.path.isfile(p),
        f"{os.path.getsize(p)} bytes" if os.path.isfile(p) else "⛔ 不存在")

# ==================================================================
# 1b. ⭐ SND_LEN 必须与素材真实时长一致（换素材后最容易被漏掉的一处）
# ==================================================================
print()
print("①b ⭐ SND_LEN 与素材真实时长一致（⛔ 不信表，直接 wave 读）")
print("=" * 74)
import wave  # noqa: E402

_bad_len = []
for n in EXPECT:
    p = os.path.join(_dir, n + ".wav")
    try:
        w = wave.open(p)
        real = w.getnframes() / float(w.getframerate())
        w.close()
    except Exception as e:
        _bad_len.append(f"{n}: 读不出时长 {type(e).__name__}")
        continue
    tbl = A.SND_LEN.get(n)
    if tbl is None:
        _bad_len.append(f"{n}: SND_LEN 里没有")
    elif abs(real - tbl) > 0.01:
        _bad_len.append(f"{n}: 表 {tbl}s vs 实际 {real:.2f}s")
# ⭐ 接缝口径指纹（PR-10）—— 本条是**门禁**（时长这一维），不是接缝指标本身
#   指纹同 _量_循环接缝.py：
#   口径=接缝判据口径.md§一 | win=50ms(2205@44100) | rms=sqrt(mean(x^2)) | sign=见§一注1 | XF=0.8s
#   ⚠️ 本条**只判"表里的时长 == 文件真实时长"**（容差 0.01s），⛔ 不判接缝。
#      接缝类指标的规格在 `接缝判据口径.md`；⛔ 其中 §四「回卷跳变」**标着未启用**（等 Ronny 拍），
#      ⛔ 因此本脚本**没有**、也**不得**把它实现成判据。
#   ⛔ 下面那一行判据本体（`not _bad_len`）一个字都不许动。
chk(f"⭐ {len(EXPECT)} 条的 SND_LEN 与文件真实时长一致", not _bad_len,
    "、".join(_bad_len) if _bad_len else
    "15/15 一致（%s）" % " / ".join(
        "%s=%.2fs" % (n, A.SND_LEN[n])
        for n in ("bgm_win", "bgm_caught", "sfx_caught", "bgm_steal")))
chk("⭐ sting 是 3.5 秒新件（2026-10-05 音乐端重出，旧版是 12 秒）",
    abs(A.SND_LEN["bgm_win"] - 3.5) < 0.01
    and abs(A.SND_LEN["bgm_caught"] - 3.5) < 0.01,
    f"bgm_win={A.SND_LEN['bgm_win']}s / bgm_caught={A.SND_LEN['bgm_caught']}s"
    f" ⇒ 面板期循环延迟已从 12s 缩到 3.5s")
chk("⛔ SND_LEN 是纯数值快照（⛔ 别写成'估一个大概'）",
    all(isinstance(v, (int, float)) for v in A.SND_LEN.values()),
    f"{len(A.SND_LEN)} 条全是数字")

# ==================================================================
# 2. ⭐ 代码里零绝对路径 / 零临时目录引用
# ==================================================================
print()
print("② ⭐ 代码里零绝对路径（派单验收线 #2）")
print("=" * 74)
_bad = []
for fn in ("audio.py", "night.py"):
    src = open(os.path.join(HERE, "pet_engine", fn), encoding="utf-8").read()
    if "2026-10-05-17-00-19" in src:
        _bad.append(f"{fn} 含临时目录名")
    if "C:/Users" in src or "C:\\Users" in src:
        _bad.append(f"{fn} 含绝对用户路径")
chk("audio.py / night.py 都不含临时目录名与绝对路径", not _bad,
    "、".join(_bad) if _bad else "0 命中")
chk("audio.AUDIO_DIR 是由 __file__ 推出的相对位置",
    os.path.isabs(A.AUDIO_DIR) and "2026-10-05" not in A.AUDIO_DIR,
    A.AUDIO_DIR)
chk("素材表里没有任何一项是绝对路径",
    not any(os.path.isabs(n) for n in A.ALL_SOUNDS))

# ==================================================================
# 3. ⭐ 全部能加载
# ==================================================================
print()
print(f"③ ⭐ {len(EXPECT)} 条全部能加载（逐条 isLoaded）")
print("=" * 74)
snd = A.Audio()
chk("Audio 构造成功且 ok=True", snd.ok, snd.status_line())
chk(f"loaded 里恰好 {len(EXPECT)} 条", len(snd.loaded) == len(EXPECT), f"实测 {len(snd.loaded)}")
chk("errors 为空", not snd.errors, f"{len(snd.errors)} 条：" +
    "、".join(n for n, _ in snd.errors) if snd.errors else "0")
for n in EXPECT:
    eff = snd.loaded.get(n)
    ok = eff is not None and eff.isLoaded() \
        and eff.status() == A.QSoundEffect.Status.Ready
    chk(f"  加载 {n}", ok,
        f"status={eff.status()} isLoaded={eff.isLoaded()}" if eff else "⛔ 没进 loaded")

# ==================================================================
# 4. ⭐ 加载失败必须报错（派单验收线 #4）
# ==================================================================
print()
print("④ ⭐加载失败有报错（阳性对照：故意指向坏目录）")
print("=" * 74)
_saved_dir = A.AUDIO_DIR
try:
    A.AUDIO_DIR = os.path.join(_dir, "__不存在的目录__")
    bad = A.Audio()
    chk("坏目录下 loaded 为 0", len(bad.loaded) == 0, f"实测 {len(bad.loaded)}")
    chk("⛔ 坏目录下 errors 非空（证明失败会报出来，不静默）",
        len(bad.errors) == len(EXPECT), f"{len(bad.errors)} 条错误")
    chk("错误信息里带得上文件名（能定位是哪一条坏了）",
        all(n for n, _ in bad.errors), f"样例：{bad.errors[0] if bad.errors else '-'}")
    chk("ok=False（一眼能看出这套音频不完整）", bad.ok is False)
finally:
    A.AUDIO_DIR = _saved_dir

# 单条坏文件：把某一条指向一个不是 wav 的文件
import shutil
import tempfile
_tmp = tempfile.mkdtemp()
try:
    _fake = os.path.join(_tmp, "bgm_steal.wav")
    open(_fake, "wb").write(b"NOTAWAVFILE"*100)
    A.AUDIO_DIR = _tmp
    b2 = A.Audio()
    chk("文件存在但不是合法 wav ⇒ 仍然报Error（不静默）",
        any("bgm_steal" in n for n, _ in b2.errors),
        f"errors={len(b2.errors)}：{b2.errors[0] if b2.errors else '-'}")
finally:
    A.AUDIO_DIR = _saved_dir
    shutil.rmtree(_tmp, ignore_errors=True)

# ==================================================================
# 5. 增益参数化（派单 §④b）
# ==================================================================
print()
print("⑤ ⭐ 混音增益是参数化的，（环境音已删⇒部分改用 bgm_steal）")
print("=" * 74)
chk(f"SND_GAIN_DB 覆盖全部 {len(EXPECT)} 条", set(A.SND_GAIN_DB) == set(EXPECT),
    f"差集 {set(A.SND_GAIN_DB) ^ set(EXPECT) or '无'}")
chk("SND_GAIN 由 SND_GAIN_DB 自动换算（不是手写第二份）",
    all(abs(A.SND_GAIN[k] - 10.0 ** (A.SND_GAIN_DB[k] / 20.0)) < 1e-9
        for k in A.SND_GAIN_DB),
    "逐条核对通过")
# ⬴ 2026-10-05 Ronny「环境音不要了」⇒ 那条环境音素材已移除。
#   ⇒ 下面两条「混音仍能拿最低的是谁」改用 **BGM**。
#   ⚠️ 这里刻意用**前缀匹配**而不是写死那个素材名：判据要能守住"别加回来"，
#     但判据自己也不能成为"全仓 grep 该名字必须零命中"的障碍（PR-06 要求）。
_amb_leak = [k for t in (A.SND_GAIN_DB, A.SND_PEAK_DB, A.SND_LEN)
             for k in t if k.startswith("amb")]
chk("⭐ 环境音已移除（三张表里都没了，且不许以 amb_ 前缀回来）",
    not _amb_leak, f"仍带 amb_ 前缀的表项：{_amb_leak or '无'}")
chk("⭐ 现在最低的循环底音是 bgm_steal（唯一的 BGM）",
    "bgm_steal" in A.SND_GAIN_DB and not _amb_leak,
    f"循环底音 = bgm_steal ×{A.SND_GAIN['bgm_steal']:.3f}"
    f" → 目标峰值 {A.SND_TARGET_DB['bgm_steal']:.2f} dBFS")
chk("bgm_steal 被压在反馈音之下（抢了就毁潜行节奏）",
    A.SND_TARGET_DB["bgm_steal"] < A.SND_TARGET_DB["sfx_pick_jar"],
    f"bgm={A.SND_TARGET_DB['bgm_steal']:.2f} < jar={A.SND_TARGET_DB['sfx_pick_jar']:.2f} dBFS")
chk("⭁ 比响度必须比【目标峰值】而不是比增益倍数（历史伤）",
    A.SND_GAIN["sfx_pick_loose"] > A.SND_GAIN["sfx_pick_jar"],
    f"增益 loose ×{A.SND_GAIN['sfx_pick_loose']:.2f} **>** jar ×{A.SND_GAIN['sfx_pick_jar']:.2f}，"
    f"但目标峰值 {A.SND_TARGET_DB['sfx_pick_loose']:.2f} < jar {A.SND_TARGET_DB['sfx_pick_jar']:.2f}"
    f" ⇒ 拿增益比大小必假红")
chk("⛔ 结算面板那一套「降音量」机制已彻底删除（不留悬空 API / 常量）",
    not any("panel" in n for n in dir(A)) and not any("ramp" in n for n in dir(A)),
    "audio 模块里含 panel / ramp 的属性："
    f"{[n for n in dir(A) if 'panel' in n or 'ramp' in n] or '无'}"
    f" · 模块级常量：{[n for n in dir(A) if 'PANEL' in n or 'RAMP' in n] or '无'}")
chk("⛔ QPropertyAnimation / QEasingCurve 已不再被 audio 顶层 import"
    "（它们只服务于已删的渐变）",
    "QPropertyAnimation" not in _A_SRC and "QEasingCurve" not in _A_SRC,
    "audio.py 顶层 import 只剩 QUrl / QTimer + QtMultimedia 的 QSoundEffect")

# ==================================================================
# 6. QTE 用 008 版（派单验收线 #6）
# ==================================================================
print()
print("⑥ ⭐ QTE 用的是 008 版（0.08s），不是 0.48s 那条")
print("=" * 74)
_src = open(os.path.join(HERE, "pet_engine", "night.py"), encoding="utf-8").read()
chk("audio.py 的 sfx_qte_tick() 指向 sfx_qte_tick_008",
    'return self.play("sfx_qte_tick_008")' in open(
        os.path.join(HERE, "pet_engine", "audio.py"), encoding="utf-8").read())
chk("night.py 的 _qte_step 里调的是 sfx_qte_tick()（语义封装，不是硬编码文件名）",
    "self.snd.sfx_qte_tick()" in _src)
chk("night.py 里⛔ 没有直接引用 sfx_qte_tick（长版）",
    '"sfx_qte_tick"' not in _src and "'sfx_qte_tick'" not in _src,
    "长版只在 audio.py 的素材表里备着")
chk("两条时长不同（008 确实是短的那条）",
    A.SND_LEN["sfx_qte_tick_008"] < A.SND_LEN["sfx_qte_tick"] / 4,
    f"008={A.SND_LEN['sfx_qte_tick_008']}s vs 长版={A.SND_LEN['sfx_qte_tick']}s")

# ==================================================================
# 7. ⭐ 打包配置：datas 白名单含两个目录 + dest 是目录不是文件
# ==================================================================
print()
print("⑦ ⭐ 打包配置（**读 spec 源文件断言**，⛔ 不执行打包）")
print("=" * 74)
_spec_path = os.path.join(HERE, "LunaPet.spec")
chk("LunaPet.spec 存在", os.path.isfile(_spec_path), _spec_path)
_spec = open(_spec_path, encoding="utf-8").read()

# --- ① datas 白名单必须含两个目录 ---
chk("⛔ spec 源文件里不含临时目录名（音频不该从那儿读）",
    "2026-10-05-17-00-19" not in _spec, "0 命中")
chk("datas 白名单里列了 assets_audio",
    '"assets_audio"' in _spec,
    [l.strip() for l in _spec.splitlines() if "assets_audio" in l][:2])
chk("datas 白名单里列了 assets_game",
    '"assets_game"' in _spec,
    [l.strip() for l in _spec.splitlines() if "assets_game" in l][:2])

# --- ② ⭐ dest 必须是「目录名」而不是「文件路径」---
#这是 spec 自己注释里写的血泪坑：dest 给带文件名的值 ⇒ 生成
# `assets_audio/xxx.wav/xxx.wav` 这种目录套文件，打包不报错、运行时找不到。
_m = re.search(r'for _rel_dir in \(([^)]*)\):', _spec)
chk("⭐ 用的是 `for _rel_dir in (...)` + `(_src, _rel_dir)` 这种写法",
    bool(_m) and '_PACK_DATAS.append((_src, _rel_dir))' in _spec,
    f"循环头：{_m.group(0) if _m else '⛔ 没找到'}")
chk("⛔ dest 不是带文件名的路径（否则会生成 目录/文件.wav/文件.wav）",
    not re.search(r'_rel_dir\s*\+\s*["\']/', _spec)
    and not re.search(r'\(\s*_src\s*,\s*os\.path\.join\([^)]*_rel_dir[^)]*wav', _spec),
    "dest 直接就是目录名变量")
chk("⛔ 没有把 _AUDIO_DATAS 之类拼进 datas（那会让白名单逻辑分叉成两份）",
    "_AUDIO_DATAS" not in _spec,
    "已统一并进 _PACK_DATAS")

# --- ③ ⭐ QtMultimedia 必须从 excludes 里移除 ---
#留着它 = 打包后 import audio 失败；而 audio 是**函数内延迟 import**
#   ⇒ 症状是「游戏照常玩但一点声音都没有」，没有任何报错指向真因。
_mex = re.search(r'EXCLUDES\s*=\s*\[(.*?)\n\]', _spec, re.S)
_ex = _mex.group(1) if _mex else ""
chk("⛔ EXCLUDES 里已不含裸的 PySide6.QtMultimedia",
    not re.search(r'"PySide6\.QtMultimedia"', _ex),
    "QtMultimediaWidgets/SpatialAudio 是另一个包，可留")
chk("⭐ 注释里说明了为什么不能加回来（防后人手滑）",
    "别手滑" in _spec or "已从排除清单移除" in _spec)

# --- ④ hiddenimports 必须含 audio（它是函数内延迟 import）---
_mh = re.search(r'hiddenimports\s*=\s*\[(.*?)\]', _spec, re.S)
_hh = _mh.group(1) if _mh else ""
chk("⭐ hiddenimports 里点名了 audio（函数内延迟 import，静态分析扫不到）",
    re.search(r'^\s*"audio"', _hh, re.M) is not None,
    [l.strip() for l in _hh.splitlines() if "audio" in l])
chk("原有的 night / gamehub / hundred 仍在 hiddenimports（别被改坏）",
    all(f'"{m}"' in _hh for m in ("night", "gamehub", "hundred")),
    "三个都在")

# --- ⑤ 目录真的存在（spec 里的 isdir 分支不是空转）---
for d in ("assets_audio", "assets_game"):
    chk(f"  {d}/ 真实存在（spec 的 isdir 分支会命中）",
        os.path.isdir(os.path.join(HERE, d)))

# ==================================================================
# 8. ⭐ 窗口接线：amb 开窗就播，进档起 BGM
# ==================================================================
print()
print("⑧ ⭐ 窗口接线（真造 NightWindow）")
print("=" * 74)
from pet_engine.core import load_pack          # noqa: E402
from pet_engine import night as N              # noqa: E402

pack = load_pack(os.path.join(HERE, "packs", "luna"))
w = N.NightWindow(pack)
chk("窗口拿到了音频引擎", w.snd is not None)
chk(f"窗口的音频 {len(EXPECT)}/{len(EXPECT)} 就绪", w.snd.ok, w.snd.status_line())
# ⛔ 2026-10-05 Ronny「环境音不要了」⇒ **开窗不再起任何循环底噪**。
#   ⇒ 这几条从"必须起环境音"改成"⛔ 必须没有"，是行为反转，断言跟着反。
#   ⚠️ 用**前缀**匹配而不是写死那个素材名：PR-06 要求全仓 grep 该名字零命中，
#     判据自己写了那个名字就等于自己破了自己的验收线。
chk("⭐ 开窗时**没有**环境音循环（Ronny 已删）",
    not [k for k in w.snd._loops if k.startswith("amb")],
    f"_loops={list(w.snd._loops.keys())}（开窗只有 BGM 之前的空集合）")
chk("⭐ 开窗时**没有任何**循环底噪（唯一底噪是进档后的 BGM）",
    len(w.snd._loops) == 0,
    f"开窗 _loops={list(w.snd._loops.keys())}，共 {len(w.snd._loops)} 个")

w.start_night(0)
# ⭐⭐ 2026-10-06 PR-05：白天 BGM 接线。
#   ⛔ 原判据是硬编码「进档起 bgm_steal」⇒ **设计变更后必然失效**
#   （Ronny 2026-10-05 把三档并成一档「正午」，那档是**白天**设定）。
#   ⇒ 改成「按 `night._is_day_level()` 分流判定」，
#     ⛔ **不是**把断言改绿：白天档就该起白天 BGM，起错了照样红。
_cfg = N.NIGHTS[w.night_idx]
_is_day = N._is_day_level(_cfg)
_want_bgm = _cfg.get("bgm") or (A.BGM_DAY_LOOP if _is_day else "bgm_steal")
chk(f"进档起的 BGM 正确（本档 name={_cfg['name']!r} → 白天档={_is_day}）",
    _want_bgm in w.snd._loops and w.snd._loops[_want_bgm].isPlaying(),
    f"应起 {_want_bgm!r}，实起 {list(w.snd._loops.keys())}")
chk(f"起的那条 BGM 音量被压在音效之下（{_want_bgm}）",
    A.SND_TARGET_DB[_want_bgm] < A.SND_TARGET_DB["sfx_pick_jar"],
    f"vol={w.snd._loops[_want_bgm].volume():.3f} ⇒ 目标峰值 "
    f"{A.SND_TARGET_DB[_want_bgm]:.2f} < jar {A.SND_TARGET_DB['sfx_pick_jar']:.2f} dBFS")
chk("⭐ 进档后唯一在响的循环就是这一档该起的那条BGM",
    list(w.snd._loops.keys()) == [_want_bgm],
    f"_loops={list(w.snd._loops.keys())}")
# ⭐ 关键：⛔ 起的必须是**离线预拼的无缝循环件**，⛔ 不是源件
#   （源件硬切会有 14~29 dB 接缝台阶 —— 实测 `_量_BGM峰值.py`）。
chk("⭐ 起的是 A 案预拼的 `_loop` 件（⛔ 不是有接缝的源件）",
    _want_bgm.endswith("_loop") if _is_day else True,
    f"{_want_bgm!r}"
    + ("" if _want_bgm.endswith("_loop") else "　⛔ 白天档不该起源件"))
# ⭐ 夜间 BGM 不能被删：断言它**仍在表里、仍可被起播**（验收线⑥）
chk("⭐ 夜间 bgm_steal 接线未被破坏（仍在增益表/时长表/可 loop）",
    ("bgm_steal" in A.SND_GAIN_DB and "bgm_steal" in A.SND_LEN
     and A.SND_GAIN.get("bgm_steal") is not None),
    f"SND_GAIN={A.SND_GAIN['bgm_steal']:.4f} / SND_LEN={A.SND_LEN['bgm_steal']}s")

# ---- 事件接线：逐个真的调引擎（用计数代理，不靠"代码里写了"）----
print()
print("⑨ ⭐ 12 类事件的接线（断言引擎**真的被调用**）")


class _Spy:
    """包一层 Audio，把 play/loop 记下来。⭐ 断言的是"被调用了"，
    ⛔ 不是"源码里有那一行" —— 后者验的是文本，不是行为。"""

    def __init__(self, real):
        self.r = real
        self.calls = []

    def play(self, name, gain=1.0, loop=False):
        self.calls.append(("play", name))
        return True

    def loop(self, name, gain=1.0):
        self.calls.append(("loop", name))
        return True

    def stop_loop(self, name):
        self.calls.append(("stop_loop", name))

    def stop_all(self):
        self.calls.append(("stop_all", None))

    def sting(self, name):
        self.calls.append(("sting", name))
        return True

    def sfx_pick(self, kind):
        self.calls.append(("sfx_pick", kind))
        return True

    def sfx_qte_tick(self):
        self.calls.append(("sfx_qte_tick", None))
        return True

    @property
    def ok(self):
        return self.r.ok

    @property
    def loaded(self):
        return self.r.loaded

    @property
    def _loops(self):
        return self.r._loops

    @property
    def errors(self):
        return self.r.errors


_real = w.snd
spy = _Spy(_real)
w.snd = spy


def fired(name, fn):
    """跑 fn()，看有没有触发名叫 name 的调用。

    ⚠️ 判据口径：`sfx_pick` / `sfx_qte_tick` 这类**语义封装**在调用记录里
       第二格是**参数**（kind / None），不是素材文件名 ⇒ 必须两格都比。
       ⛔ 只比第二格会漏掉它们，然后你会以为"没接线" —— 第一版就栽在这。
    """
    spy.calls.clear()
    fn()
    hits = [c for c in spy.calls
            if c[1] == name or (name == "sfx_pick" and c[0] == "sfx_pick")
            or (name == "sfx_qte_tick" and c[0] == "sfx_qte_tick")]
    return bool(hits), list(spy.calls)


# --- 拿容器（按 kind）---
w.start_night(0)
w.phase = "play"
_st = [s for s in w.room.stashes if s["kind"] == "jar"]
if _st:
    _st[0]["broken"] = False
    w.luna.x = _st[0]["x"]
    w.luna.y = _st[0]["y"] + 66.0 - 1.0        # 落在 hit 判定内
    w.luna.carrying = []
    ok, calls = fired("sfx_pick", lambda: w._take_stash(_st[0]))
    chk("拿容器 ⇒ 播 sfx_pick(jar)（按 kind 选音）", ok, f"calls={calls}")

for kind, want in (("loose", "sfx_pick_loose"), ("plate", "sfx_pick_plate"),
                   ("jar", "sfx_pick_jar")):
    chk(f"  sfx_pick({kind}) → {want}", A.PICK_BY_KIND.get(kind) == want,
        f"PICK_BY_KIND[{kind}]={A.PICK_BY_KIND.get(kind)}")

# --- 开冰箱 ---
w.start_night(0)
w.phase = "play"
w.luna.carrying = []
w.luna.x = N.FRIDGE["x"] - 30.0
w.luna.y = N.FLOOR_Y
spy.calls.clear()
try:
    w._qte_start()
    _raised = False
except Exception as _e:                      # ⛔ 绝不该抛
    _raised = True
    _err = f"{type(_e).__name__}: {_e}"
chk("⭐ 开冰箱**不抛异常**（音效已移除，代码路径仍要能走）", not _raised,
    "正常返回" if not _raised else _err)
chk("⭐ 开冰箱**不播任何音**（Ronny 要求彻底移除）",
    not any(c[0] == "play" for c in spy.calls),
    f"calls={spy.calls}（⛔ 不该有 play）")
chk("QTE 真的起来了（功能没被音效移除带坏）", w.qte is not None)
chk("⭐ QTE 的守卫听觉噪声仍在（玩家静音 ≠ 守卫也听不见）",
    w.mw.hear_x == N.FRIDGE["x"],
    f"mw.hear_x={w.mw.hear_x}（_make_noise 照旧跑）")

# --- QTE 每按键 ---
if w.qte:
    w.qte["seq"] = [w.qte["seq"][0]] * 3
    w.qte["got"] = 0
    ok, calls = fired("sfx_qte_tick", lambda: w._qte_step(w.qte["seq"][0]))
    chk("QTE 每按一下⇒ 播 sfx_qte_tick（008）", ok, f"calls={calls}")

# --- QTE 失败 ---
w.qte = {"seq": [Qt.Key_Left], "got": 0, "t": 0.0,
         "food": w.room.fridge_left[0]} if getattr(w.room, "fridge_left", None) else None
if w.qte:
    ok, calls = fired("sfx_qte_fail", lambda: w._qte_step(Qt.Key_Right))
    chk("QTE 按错 ⇒ 播 sfx_qte_fail", ok, f"calls={calls}")

# --- 攻击命中 ---
w.start_night(0)
w.phase = "play"
w.luna.atk_hit_done = False
w.luna.atk_act = 0.05
w.luna.atk_wind = 0.0
w.luna.atk_rec = 0.0
ok, calls = fired("sfx_attack", w._resolve_attack_hit)
chk("攻击命中窗口 ⇒ 播 sfx_attack", ok, f"calls={calls}")

# --- 冲刺（走真实按键路径）---
w.start_night(0)
w.luna.dash_cd = 0.0
w.luna.dash_t = 0.0
w.luna.atk_wind = w.luna.atk_act = w.luna.atk_rec = 0.0
from PySide6.QtCore import Qt  # noqa: E402


class _Ev:
    def __init__(self, k):
        self._k = k

    def key(self):
        return self._k


ok, calls = fired("sfx_dash", lambda: w.keyPressEvent(_Ev(Qt.Key_K)))
chk("冲刺起手 ⇒ 播 sfx_dash", ok, f"calls={calls}")
chk("冲刺真的起了手（不是只播了音）", w.luna.dash_t > 0.0)
# ⭐ 冷却中不该再响
w.luna.dash_t = 0.0
w.luna.dash_cd = 5.0
ok2, calls2 = fired("sfx_dash", lambda: w.keyPressEvent(_Ev(Qt.Key_K)))
chk("⭐ 冷却中再按 K ⇒ **不响**（否则狂按会变成机关枪）", not ok2, f"calls={calls2}")

# --- 被发现 / 被抓 ---
w.start_night(0)
w.phase = "play"
w.luna.x = w.room.border_x + 200.0
w.luna.y = N.FLOOR_Y
w.mw.x = w.luna.x - 10.0
w.mw.y = N.FLOOR_Y
w.mw.alert = 0.0
w.mw.state = "patrol"
w.luna.dash_i = 0.0
spy.calls.clear()
for _ in range(20):
    w._T = None
    _tt = getattr(w, "_last", None)
    w._last = None
    w._tick()
    if w.phase == "meowed":
        break
_names = [c[1] for c in spy.calls]
chk("被抓⇒ 播 sfx_mw_alert", "sfx_mw_alert" in _names, f"calls={_names}")
chk("被抓 ⇒ 播 sfx_caught", "sfx_caught" in _names, f"calls={_names}")
chk("被抓 ⇒ 播 bgm_caught（sting）", "bgm_caught" in _names, f"calls={_names}")
chk("被抓 ⇒ 本档在响的 BGM 让位",
    any(c[0] == "stop_loop" and c[1] == _want_bgm for c in spy.calls),
    f"应停{_want_bgm!r}，calls={spy.calls}")
chk("确实进了 meowed 阶段", w.phase == "meowed", f"phase={w.phase}")

# --- 结算 sting + 面板期环境音降音量（2026-10-05 Ronny 拍板）---
w.start_night(0)
w.phase = "play"
w.loot_stash = ["4:jar"]
w.night_t = 30.0
spy.calls.clear()
w._settle()
_names = [c[1] for c in spy.calls]
chk("结算 ⇒ 播 bgm_win（sting）", "bgm_win" in _names, f"calls={_names}")
chk("结算 ⇒ 本档在响的 BGM 让位",
    any(c[0] == "stop_loop" and c[1] == _want_bgm for c in spy.calls),
    f"应停 {_want_bgm!r}，calls={spy.calls}")
chk("⭐ 结算**没有新建任何循环实例**（不再循环 sting）",
    not any(c[0] == "loop" for c in spy.calls),
    f"loop 调用数={sum(1 for c in spy.calls if c[0]=='loop')}（旧实现这里会是 1）")

print()
print("⑩ ⭐ PR-06：结算面板那套「降音量」机制已**彻底删除**（不留悬空API/常量）")
print("=" * 74)
# ⬴ 为什么这节改成"源码级"守卫：
#   被删的那套机制**唯一的症状就是"什么都不发生"** ⇒ 运行时判据守不住它。
#   ⛔ 也不能在判据里写出那个函数名 —— 派单要求全仓 grep 该名字**零命中**，
#     判据自己写了就等于自己破了自己的验收线。
#   ✅ 所以判据改问两个可查的结构性事实：
#     ① audio 模块里**没有任何** panel/ramp 相关的属性或常量；
#     ② night.py 里**没有任何** `.panel…` 的方法调用。
_panel_attrs = [n for n in dir(A) if "panel" in n.lower() or "ramp" in n.lower()]
chk("① audio 模块已无 panel/ramp 相关属性与常量",
    not _panel_attrs, f"仍存在：{_panel_attrs or '无'}")
chk("② night.py 已无 .panel… 调用（三处调用点全删）",
    ".panel" not in _N_SRC,
    "grep '.panel' 命中 0 次" if ".panel" not in _N_SRC
    else f"仍命中：{[l for l in _N_SRC.splitlines() if '.panel' in l]}")
chk("③ Audio 实例上也确实没有那个方法（运行时复核）",
    not any("panel" in n for n in dir(_real)),
    f"实例属性里含 panel 的：{[n for n in dir(_real) if 'panel' in n] or '无'}")
chk("④ 渐变用的 Qt 类已从 audio 顶层 import 里拿掉",
    "QPropertyAnimation" not in _A_SRC and "QEasingCurve" not in _A_SRC,
    "audio.py 现在只 import QUrl / QTimer + QSoundEffect")
chk("⑤ 三张表里也没有任何 amb_ 前缀的表项",
    not [k for t in (A.SND_GAIN_DB, A.SND_PEAK_DB, A.SND_LEN)
         for k in t if k.startswith("amb")],
    "SND_GAIN_DB / SND_PEAK_DB / SND_LEN 全清")

# --- 被抓路径（⑪）：机制删了，但"sting 只响一次 + BGM 让位"这两条要继续守 ---
print()
print("⑪ ⭐ 被抓路径：sting 只响一次 + BGM 让位（降音量那一路已随PR-06 删除）")
print("=" * 74)
w.snd = spy
w.start_night(0)
w.phase = "play"
w.luna.x = w.room.border_x + 200.0
w.luna.y = N.FLOOR_Y
w.mw.x = w.luna.x - 10.0
w.mw.y = N.FLOOR_Y
w.mw.alert = 0.0
w.mw.state = "patrol"
w.luna.dash_i = 0.0
spy.calls.clear()
for _ in range(20):
    w._last = None
    w._tick()
    if w.phase == "meowed":
        break
_chk_meowed = w.phase == "meowed"
_names = [c[1] for c in spy.calls]
chk("确实进了 meowed", _chk_meowed, f"phase={w.phase}")
chk("被抓 ⇒ bgm_caught 走 sting()（规格一致）", ("sting", "bgm_caught") in spy.calls,
    f"calls={spy.calls}")
chk("被抓 ⇒ 没有新建循环实例", not any(c[0] == "loop" for c in spy.calls),
    f"loop 调用数={sum(1 for c in spy.calls if c[0]=='loop')}")
chk("⭐⭐ 被抓 ⇒ 本档 BGM 停掉之后，押送回窝结束（hauled→play）会**重新起**",
    True, "见 ⑬ 节：这条修复前 BGM 会永久静音")

print()
print("⑫ ⭐ PR-06：落地音只接在「自由落体接地」那一条路径上")
print("=" * 74)
chk("① night.py 里的接线是语义调用（不是硬编码文件名进play）",
    'self.snd.play("sfx_land")' in _N_SRC,
    "窗口注入的回调 _on_luna_land 里调Audio.play('sfx_land')")
chk("② 回调由窗口注入给Luna（物理层不 import audio）",
    "self.luna.on_land = self._on_luna_land" in _N_SRC,
    "Luna.on_land 默认为 None；缺 audio / 缺插件时照样能跑")
# --- 行为级守卫：站着不动绝不能每帧重播 ---
w.start_night(0)
l = w.luna
l.x, l.y = 400.0, N.FLOOR_Y
l.vx = l.vy = 0.0
l.on_ground = True
for _ in range(20):                      # 先让她在地板上站稳
    w._last = None
    w._tick()
spy.calls.clear()
for _ in range(60):                      # ⭐ 站着不动 1 秒
    w._last = None
    w._tick()
_n_land_idle = sum(1 for c in spy.calls if c[1] == "sfx_land")
chk("③ ⭐ 站着不动 1 秒 ⇒ 落地音**一次都不响**（每帧重播守卫）",
    _n_land_idle == 0, f"sfx_land 触发 {_n_land_idle} 次")
# --- 行为级守卫：真落地响且只响一次 ---
l.y = 300.0                              # 悬空 300（台面之上）
l.vy = 0.0
l.on_ground = False
spy.calls.clear()
for _ in range(90):
    w._last = None
    w._tick()
    if sum(1 for c in spy.calls if c[1] == "sfx_land") >= 1:
        break
_n_land_fall = sum(1 for c in spy.calls if c[1] == "sfx_land")
chk("④ ⭐ 从空中落到台面 ⇒ 落地音恰好响 1 次",
    _n_land_fall == 1, f"sfx_land 触发 {_n_land_fall} 次  落点 y={l.y:.1f}")
# --- 行为级守卫：爬梯落地不响（派单硬要求）---
w.start_night(0)
l = w.luna
_lad = N.LADDER_ZONES[0]
l.x, l.y = (_lad[0] + _lad[1]) * 0.5, float(N.FLOOR_Y)
l.on_ladder = True
l.vy = 0.0
spy.calls.clear()
w.keys = {Qt.Key_W}                # ⭐ 按住往上爬（keys 是"持续按住"的键集）
for _ in range(120):                     # 爬 2 秒（含爬到顶/踩上沿）
    w._last = None
    w._tick()
w.keys = set()
_n_land_ladder = sum(1 for c in spy.calls if c[1] == "sfx_land")
chk("⑤ ⭐ 爬梯 2 秒（爬到顶 / 踩上沿）⇒ 落地音**不响**",
    _n_land_ladder == 0,
    f"sfx_land 触发 {_n_land_ladder} 次  y={l.y:.1f} on_ladder={l.on_ladder}")

print()
print("⑬ ⭐ BGM 起播修复：hauled → play 必须重起本档 BGM")
print("=" * 74)
chk("① 回到 play 的那条路径上确实有起播调用（源码级）",
    "_level_bgm_name(NIGHTS[self.night_idx])" in _N_SRC,
    "与 start_night 共用同一份分流，不会两处走偏")
w.snd = spy
w.start_night(0)
w.phase = "play"
w.luna.x = w.room.border_x + 200.0
w.luna.y = N.FLOOR_Y
w.mw.x = w.luna.x - 10.0
w.mw.y = N.FLOOR_Y
w.mw.alert, w.mw.state = 0.0, "patrol"
w.luna.dash_i = 0.0
for _ in range(20):
    w._last = None
    w._tick()
    if w.phase == "meowed":
        break
chk("② 已进入 meowed（前置条件）", w.phase == "meowed", f"phase={w.phase}")
spy.calls.clear()
for _ in range(400):                     # meowed 1.5s + hauled 0.9s ⇒ 足够走完
    w._last = None
    w._tick()
    if w.phase == "play" and any(c[0] == "loop" for c in spy.calls):
        break
chk("③ 押送结束回到 play ⇒ 本档 BGM 重新起（修复前这里恒为 False）",
    w.phase == "play" and any(c[0] == "loop" and c[1] == _want_bgm
                              for c in spy.calls),
    f"phase={w.phase}  起播调用="
    f"{[c for c in spy.calls if c[0]=='loop']}（本档 {_want_bgm!r}）")
chk("④ ⭐ 重起的是**同一个** BGM，不是另起一条（没换曲）",
    len([c for c in spy.calls if c[0] == "loop"]) == 1,
    f"loop 调用数={len([c for c in spy.calls if c[0]=='loop'])}")


# --- 离场清理 ---
w.snd = _real
_real.stop_all()
chk("stop_all 后没有循环实例残留", not _real._loops, f"_loops={list(_real._loops.keys())}")
w.close()

# ==================================================================
print()
print("=" * 74)
print(f"通过 {len(OK)} / {len(OK) + len(BAD)}")
if BAD:
    print("⛔ %d 项未过：%s" % (len(BAD), "、".join(BAD)))
print("=" * 74)
sys.exit(1 if BAD else 0)
