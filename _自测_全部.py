# -*- coding: utf-8 -*-
"""统一自测入口 —— 逐个跑全部 _自测_*.py，汇总表格，任一红则非零退出。

⛔ 为什么需要它（10-05 建）
   22 个自测没有统一入口 ⇒ 想看"现在到底几个红"只能手工 for 一遍，
   而手工 for 恰好会踩三个已知的坑：
     ① exit 139 段错误 ⇒ 后面所有组静默消失，表面看"没跑"（不是没跑，是崩了）
     ② 各自测退出码不一致 —— 6个脚本压根没有 sys.exit ⇒ 失败也返回 0
     ③ 各自测汇总行格式不统一（4 种）⇒ 只认一种会漏判

⭐ 设计要点
   · **每个自测跑在独立子进程里**（subprocess，不共用解释器）
     —— 这样 139/无输出/挂起 都只会影响那一个，不会连坐后面的组。
     这正是 10-05 踩的坑：残留未析构 + 又 new 重资源窗口 ⇒ exit 139。
   · **结果判定以「退出码 OR 解析失败」二者取严**
     绝不信"只有退出码"（6 个脚本失败也返回 0），也绝不信"只有文本"（可能截断）。
   · **解析不出结果行 ⇒ 判为"无结果"并单独标出**，不混进通过里。
     「没读到数」和「读到 0 项」是两件事，混起来就是假绿。

用法
    python _自测_全部.py            # 跑全部
    python _自测_全部.py 夜间 冰箱   # 只跑名字里含这些关键字的
    python _自测_全部.py --keep-going  # 忽略超时限制，逐个跑到完（默认也是不中断）
"""

import os
import re
import sys
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable

# ⛔ 超时上限（秒）。选300 的理由：这些自测在offscreen 下跑真实的 200~400 帧循环，
#    _自测_夜间.py / _自测_一百层v5.py 实测能到 2~4 分钟。
#    超时**不算失败**，单列为 TIMEOUT —— 因为"慢"和"红"是两种问题，
#    混在一起报就会出现"原来是慢，现在变成坏了"的误判。
TIMEOUT = 300

# ⛔ 手动排除：不是自测，或者会弹真窗口 / 改磁盘状态
SKIP = {
    "_自测_全部.py",     # 自己
    # ⛔ _自测_QTE.py 已经被内容迁移了 —— 它现在只是个指路牌：
    #   跑起来只会打印「"一局能不能打完"已移到_自测_可达性.py」然后 exit 0。
    #   留着它进汇总表只会污染「通过 N/22」这个数（它没有断言，纯装饰）。
    #   ⛔ 要恢复它的内容得设计端拍板：QTE 本体另有_自测_QTE 的历史版本？
    "_自测_QTE.py",
}

# ---------------------------------------------------------------
# ⭐ 解析器：把「脚本自己打印的汇总」解析成 (通过, 总数)
# ---------------------------------------------------------------
# 实测项目里有 4 种汇总格式，全部要认：
#   A"通过 47 / 47"            （_自测_一百层 / _自测_夜间 / 可达性 / 潜行 / 冰箱...）
#   B  "通过 17 / 17 项，全绿✅"（_自测_core）
#   C  "=== 结果：15 通过 / 2 失败 ==="（GUI睡眠 / 地形 / 点击唤醒 / 睡眠 / 转身接线）
#   D  "✅ 通过 29 / 29"        （游戏主界面 / 卡顿定位）
#   E  "⛔ 6 项未过（通过 3）"  （同上，失败分支）
#   F  "❌ 未通过 2 项："        （一百层v5，失败分支）
# ✅ 统一策略：**只找 "通过N / M" 这个形状**（N、M 可以被别的字包着），
#    找不到就返回 None（= 无结果），由上层报"无结果"而不是报"通过"。

_RE_FRAC = re.compile(r"通过\s*(\d+)\s*/\s*(\d+)")
# ⛔ 第二种形状：「15 通过 / 2 失败」（数在前，GUI睡眠/地形/点击唤醒/睡眠/转身接线 用这个）
#    我第一版只写了上面那一种 ⇒ 被自测的阳性对照当场抓到。
#    这里 total取 通过+失败（而不是 M），语义才对得上"共几项"。
_RE_FRAC2 = re.compile(r"(\d+)\s*通过\s*/\s*(\d+)\s*(?:项)?\s*(?:失败|未过)")
# ⛔ 第三种形状：「✅ 全部通过」/「✅ 冰箱三项 + 顶平台 + 三档巡逻 全部通过」
#    （draghang / 一百层v5 / 冰箱 用这个）—— 没有分母，但语义明确是全过。
_RE_ALL = re.compile(r"全部通过|全绿")
# ⛔ 第四种形状：「通过 12 组检查」—— **分母缺失，且"组"是分组标签不是分数**
#    （core.py 当年就栽过这个：写死的 8 被误读成"15 通过 / 8 失败"）。
#    ⇒ 只用来报个数，PASS 判定仍以退出码 + 有无失败字样为准，绝不当成"N/N"。
_RE_GROUPS = re.compile(r"通过\s*(\d+)\s*组检查")


def parse_summary(text):
    """从输出文本里抽 (通过, 总数)。抽不到分数但明确说全过 ⇒ (None, None) + all_pass=True。

    ⛔ 取**最后一个**匹配，不是第一个。
       原因：_自测_技能.py 这类脚本中途会打"已通过 N 项"的中间进度，
       取第一个会把中间态误当最终态（这正是「取错行导致整组静默全绿」的同类坑）。
    """
    hits = _RE_FRAC.findall(text)
    if hits:
        ok, total = hits[-1]
        return int(ok), int(total), False
    hits2 = _RE_FRAC2.findall(text)
    if hits2:
        ok, bad_n = hits2[-1]
        return int(ok), int(ok) + int(bad_n), False
    if _RE_ALL.search(text):
        return None, None, True
    return None, None, False


def parse_groups(text):
    """「通过 N 组检查」里的 N。⛔ 这是分组数，**不是分数**，只用于展示。"""
    hits = _RE_GROUPS.findall(text)
    return int(hits[-1]) if hits else None


# ⛔ 阳性对照：解析器必须能被"已知一定存在的形状"命中。
#   项目里栽过"判据静默失效 → 全假通过"的坑（grep 在 5MB+ 日志上、
#   `next(...)` 取错行导致 findall 返回 []）。所以解析器本身要先自证。
#
# ⭐⭐ 而它当场抓到了我的两个真bug（这是建这个自测的唯一理由）：
#   ① 只认「通过 N / M」，漏了「N 通过 / M 失败」⇒ 5 个真过的被判NORESULT
#   ② 拿「文本含'失败'字样」当红判据 ⇒ 「10 通过 / 0 **失败**」被当成红了
#      ⇒ 地形/点击唤醒/睡眠/转身接线 4 个**满分被误判FAIL**。
#   第②条正是 MEMORY 里那条「⛔ 扫全量统计≠ 判据对 / 判据在制造证据」的复现。
def _selftest_parser():
    cases = [
        # (文本, 期望 (ok,total,all_pass))
        ("通过 47 / 47", (47, 47, False)),
        ("  通过 17 / 17 项，全绿 ✅", (17, 17, False)),
        ("=== 结果：15 通过 / 2 失败 ===", (15, 17, False)),
        ("=== 结果：10 通过 / 0 失败 ===", (10, 10, False)),   # ⭐ 假红回归样本
        ("✅ 通过 29 / 29", (29, 29, False)),
        ("✅ 全部通过", (None, None, True)),
        ("✅ 冰箱三项 + 顶平台 + 三档巡逻 全部通过", (None, None, True)),
        ("⛔ “一局能不能打完”已移到 _自测_可达性.py", (None, None, False)),
        ("通过 12 组检查", (None, None, False)),               # ⭐ 分组数≠分数
        ("全程没有结论的一句话", (None, None, False)),
    ]
    for src, want in cases:
        got = parse_summary(src)
        assert got == want, "解析器自测失败: %r ⇒ %r，期望 %r" % (src, got, want)

    # ⛔ 阳性对照第二重：取最后一个，不能取第一个（中间态会骗人）
    txt = "已通过 3 / 10\n继续...\n通过 9 / 10\n"
    assert parse_summary(txt) == (9, 10, False), "解析器取了中间态而非最终态"

    # ⛔ 阳性对照第三重：「0 失败」绝不能被当成有失败
    ok, total, allp = parse_summary("=== 结果：23 通过 / 0 失败 ===")
    assert (ok, total, allp) == (23, 23, False), "「0 失败」被误判"
    assert not has_failure_text("=== 结果：23 通过 / 0 失败 ==="), "「0 失败」被判成红"

    # ⛔ 阳性对照第四重：「通过 12 组检查」不能被当成 N/N（core.py 当年的坑）
    assert parse_groups("通过 12 组检查") == 12
    assert parse_summary("通过 12 组检查") == (None, None, False), \
        "分组数被误当成分数"
    return True


# ⛔ 「输出里有没有失败」—— 只认**真的列出了失败项**，不认"0 失败"这种汇总行。
#   ⛔⛔ 第一版直接grep"失败"两个字，结果「10 通过 / 0 失败」全被判红（4 个假红）。
#   ⇒ 现在必须满足：出现了"失败/未过" **且** 后面跟的是非零个数或清单。
_RE_FAIL_N = re.compile(r"(?:未通过|未过|失败)\s*[：:]?\s*(\d+)\s*(?:项|组)")
_RE_FAIL_LIST = re.compile(r"(?:未通过|未过|失败)\s*[：:]\s*[^\n=]{2,}")


def has_failure_text(text):
    """文本里是否有**真失败**。⛔ 「0 失败」必须返回 False。"""
    for m in _RE_FAIL_N.findall(text):
        if int(m) > 0:
            return True
    # 「未通过：xxx、yyy」这种清单形态
    for m in _RE_FAIL_LIST.findall(text):
        tail = m.split("：", 1)[-1] if "：" in m else m.split(":", 1)[-1]
        t = tail.strip()
        if t and not re.match(r"^0\s*(项|组)?", t) and "0 失败" not in t:
            return True
    return False


# ---------------------------------------------------------------
# 跑一个自测
# ---------------------------------------------------------------
def run_one(fname, timeout=TIMEOUT):
    """⇒ dict(name, rc, ok, total, secs, out, status)

    status ∈ PASS / FAIL / NORESULT / TIMEOUT / CRASH
    """
    import time
    env = dict(os.environ)
    env["QT_QPA_PLATFORM"] = "offscreen"      # ⛔ 必须：无头环境下不能弹真窗口
    env["PYTHONIOENCODING"] = "utf-8"         # ⛔ 必须：中文汇总行否则乱码，解析不到
    path = os.path.join(HERE, fname)
    t0 = time.perf_counter()
    try:
        cp = subprocess.run(
            [PY, "-u", path],
            cwd=HERE, env=env, timeout=timeout,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        )
        out = cp.stdout.decode("utf-8", "replace")
        rc = cp.returncode
    except subprocess.TimeoutExpired as e:
        out = (e.stdout or b"").decode("utf-8", "replace") if isinstance(e.stdout, bytes) else (e.stdout or "")
        return dict(name=fname, rc=None, ok=None, total=None,
                    secs=time.perf_counter() - t0, out=out, status="TIMEOUT")
    except Exception as e:                     # 启动失败等
        return dict(name=fname, rc=None, ok=None, total=None,
                    secs=time.perf_counter() - t0,
                    out="%s: %s" % (type(e).__name__, e), status="CRASH")

    secs = time.perf_counter() - t0
    ok, total, all_pass = parse_summary(out)
    groups = parse_groups(out)

    # ⛔⛔ 判定优先级（第一版把这条写错了，4 个满分自测被判红）：
    #   1) 段错误 ⇒ CRASH（无论文本说什么）
    #   2) 退出码非 0 ⇒ FAIL
    #   3) **分数优先**：解析出 (ok,total) 且 ok<total ⇒ FAIL
    #      ⛔ 这一步必须排在"文本含失败"之前 —— 「10 通过 / 0 失败」里
    #         "失败"两个字是**汇总行的组成部分**，不是失败项。
    #   4) has_failure_text（真失败清单 / 非零失败数）⇒ FAIL
    #   5) 明确说「全部通过」⇒ PASS
    #   6) 什么都没有 ⇒ NORESULT（**不算通过**：没读到数 ≠ 读到满分）
    if rc != 0:
        # 139 = 段错误，Windows 上对应 -1073741819 / 3221225477
        if rc in (139, -1073741819, 3221225477, 0xC0000005):
            return dict(name=fname, rc=rc, ok=ok, total=total, secs=secs,
                        out=out, status="CRASH")
        return dict(name=fname, rc=rc, ok=ok, total=total, secs=secs, out=out, status="FAIL")
    if ok is not None and total is not None:
        if ok < total:
            return dict(name=fname, rc=rc, ok=ok, total=total, secs=secs, out=out, status="FAIL")
        return dict(name=fname, rc=rc, ok=ok, total=total, secs=secs, out=out, status="PASS")
    if has_failure_text(out):
        return dict(name=fname, rc=rc, ok=ok, total=total, secs=secs, out=out, status="FAIL")
    if all_pass:
        return dict(name=fname, rc=rc, ok=None, total=None, secs=secs, out=out,
                    status="PASS", note=("%d 组检查" % groups) if groups else "全部通过")
    if groups is not None:
        # 有"通过 N 组检查"但无分母 —— ⛔ 不敢判 PASS（分组数不是分数），
        #   单列出来让人决定。这正是 core.py 当年把写死的 8 误读成"8 失败"的教训。
        return dict(name=fname, rc=rc, ok=None, total=None, secs=secs, out=out,
                    status="NOGROUP", note="%d 组检查" % groups)
    return dict(name=fname, rc=rc, ok=None, total=None, secs=secs, out=out, status="NORESULT")


# ---------------------------------------------------------------
def discover(filters):
    names = [f for f in sorted(os.listdir(HERE))
             if f.startswith("_自测_") and f.endswith(".py") and f not in SKIP]
    if filters:
        names = [f for f in names if any(k in f for k in filters)]
    return names


BAD_STATUS = ("FAIL", "CRASH", "NORESULT", "TIMEOUT", "NOGROUP")


def main():
    argv = sys.argv[1:]
    filters = [a for a in argv if not a.startswith("-")]

    print("=" * 78)
    print("  猫猫公寓 · 统一自测入口")
    print("  python: %s" % PY)
    print("=" * 78)

    try:
        _selftest_parser()
        print("解析器自测 ✅（含阳性对照：确认能取到已知形状、取的是末个而非首个）\n")
    except AssertionError as e:
        print("⛔⛔ 解析器自测失败 —— 判据不可信，后面的结果一律不作数：%s\n" % e)
        return 2

    names = discover(filters)
    if not names:
        print("⛔ 没找到匹配的自测（关键字：%s）" % (filters or "无"))
        return 2
    print("共 %d 个自测待跑\n" % len(names))

    results = []
    for i, f in enumerate(names, 1):
        print("[%2d/%2d] %-30s " % (i, len(names), f), end="", flush=True)
        r = run_one(f)
        results.append(r)
        if r["status"] == "PASS":
            note = r.get("note") or ""
            frac = "%d / %d" % (r["ok"], r["total"]) if r["ok"] is not None else note
            print("✅ %s  (%.1fs)" % (frac, r["secs"]))
        elif r["status"] == "FAIL":
            frac = "%d / %d" % (r["ok"], r["total"]) if r["ok"] is not None else "无分数"
            print("⛔ FAIL  %s  rc=%s  (%.1fs)" % (frac, r["rc"], r["secs"]))
        elif r["status"] == "TIMEOUT":
            print("⏱ TIMEOUT  >%ds" % TIMEOUT)
        elif r["status"] == "CRASH":
            print("💥 CRASH rc=%s  (%.1fs)" % (r["rc"], r["secs"]))
        elif r["status"] == "NOGROUP":
            print("❓ NOGROUP —— %s，但没分母，不敢判过" % r.get("note"))
        else:
            print("❓ NORESULT —— 跑完了但没解析到结论行（**不算通过**）  rc=%s" % r["rc"])

    # ---------------- 汇总表 ----------------
    print()
    print("=" * 78)
    print("  汇总")
    print("=" * 78)
    print("  %-30s %-9s %-12s %8s" % ("自测", "状态", "结果", "耗时"))
    print("  " + "-" * 74)
    for r in results:
        st = r["status"]
        mark = {"PASS": "✅", "FAIL": "⛔", "CRASH": "💥",
                "TIMEOUT": "⏱", "NORESULT": "❓", "NOGROUP": "❓"}[st]
        if r["ok"] is not None:
            res = "%d / %d" % (r["ok"], r["total"])
        else:
            res = r.get("note") or "-"
        print("  %-30s %s %-13s %6.1fs" % (r["name"], mark, res, r["secs"]))

    bad = [r for r in results if r["status"] in BAD_STATUS]
    npass = sum(1 for r in results if r["status"] == "PASS")

    print("  " + "-" * 74)
    print("  通过 %d / %d" % (npass, len(results)))
    if bad:
        print("  ⛔ 未过 %d 个：" % len(bad))
        for r in bad:
            extra = ""
            if r["status"] == "FAIL":
                # 把失败项名字捞出来（各自测格式不一，这里只做尽力提取）
                m = re.findall(r"(?:未通过|未过|失败)\s*[：:]\s*([^\n]{2,300})", r["out"])
                cand = [x for x in m if x.strip() and not re.match(r"^0\s*(项|组)", x.strip())]
                if cand:
                    extra = "← " + cand[-1][:160]
                else:
                    extra = "⛔输出里有失败字样但清单解析不到（见该文件尾部）"
            elif r["status"] == "NORESULT":
                extra = "⛔ 无机器可读结果行 —— 判据没法进 CI 契约"
            elif r["status"] == "NOGROUP":
                extra = "⛔ 只有分组数没分母 —— 分数/分组数混淆过，不判过"
            elif r["status"] == "CRASH":
                extra = "⛔ 进程崩了（段错误）⇒ 后续组不会再有输出"
            elif r["status"] == "TIMEOUT":
                extra = "⏱ 超时 —— 「慢」不等于「红」，单独查"
            print("    · %-28s %-9s %s" % (r["name"], r["status"], extra))

        # ⛔ 把失败组的输出尾部落到文件，方便点开看（不看就等于没报）
        logdir = os.path.join(HERE, "_work", "_selftest_logs")
        os.makedirs(logdir, exist_ok=True)
        for r in bad:
            p = os.path.join(logdir, r["name"].replace(".py", ".log"))
            with open(p, "w", encoding="utf-8") as f:
                f.write("status=%s rc=%s ok=%s total=%s\n\n" % (
                    r["status"], r["rc"], r["ok"], r["total"]))
                f.write(r["out"])
        print("\n  失败组完整输出已落盘：%s" % logdir)
    print("=" * 78)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())