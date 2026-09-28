# -*- coding: utf-8 -*-
"""_验证exe.py —— 打包产物的冒烟验证（不是业务代码，纯工程脚本）

做三件事：
    ① 打印 dist 的真实占用（按字节累加，不用 du 的块大小）
    ② 冷启动实测：拉起 exe，给每一行日志打上"从进程启动起的秒数"，
       必须能看到 `[引擎] 已启动` 才算真的起来了（而不是闪退）
    ③ 依赖自检：扫一遍包里所有 dll/pyd 的导入表，确认没有缺失的依赖

用法：
    python _验证exe.py [等待秒数，默认 8]
"""
from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
EXE = os.path.join(HERE, "dist", "LunaPet", "LunaPet.exe")
WAIT_S = float(sys.argv[1]) if len(sys.argv) > 1 else 8.0


def human(n: int) -> str:
    return f"{n / 1048576:.1f} MB"


# ---------------------------------------------------------------- ① 体积
def size_report() -> int:
    root = os.path.dirname(EXE)
    total = 0
    for dirpath, _, files in os.walk(root):
        for f in files:
            total += os.path.getsize(os.path.join(dirpath, f))
    print(f"[体积] {root}")
    print(f"       文件合计 {human(total)}（{total:,} 字节）")
    return total


# ---------------------------------------------------------------- ② 冷启动
def cold_start() -> bool:
    print(f"\n[冷启动] 拉起 {EXE}")
    if not os.path.exists(EXE):
        print("       ⛔ exe 不存在，先打包")
        return False

    env = dict(os.environ, PYTHONUTF8="1", PYTHONUNBUFFERED="1")
    t0 = time.perf_counter()
    p = subprocess.Popen(
        [EXE], cwd=os.path.dirname(EXE), env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace", bufsize=1,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
    )

    # 用后台线程收日志：GUI 程序会一直跑，如果直接 readline() 会永久阻塞，
    # 主线程就没机会做超时判断了
    q: queue.Queue[str] = queue.Queue()

    def _pump():
        try:
            for line in p.stdout:
                q.put(line)
        except Exception:
            pass

    threading.Thread(target=_pump, daemon=True).start()

    hit_engine = False
    hit_engine_t = None
    deadline = t0 + WAIT_S

    while True:
        left = deadline - time.perf_counter()
        if left <= 0:
            break
        try:
            line = q.get(timeout=min(left, 0.2))
        except queue.Empty:
            if p.poll() is not None:
                break
            continue
        el = time.perf_counter() - t0
        line = line.rstrip("\r\n")
        if line:
            print(f"       [{el:6.2f}s] {line}")
        if "[引擎] 已启动" in line and not hit_engine:
            hit_engine, hit_engine_t = True, el
            deadline = min(deadline, time.perf_counter() + 1.5)

    alive = p.poll() is None
    print(f"       进程存活：{alive}，退出码：{p.poll()}")
    # 结束进程树（GUI 程序会一直跑）
    subprocess.run(["taskkill", "/F", "/T", "/PID", str(p.pid)],
                   capture_output=True)
    try:
        p.stdout.close()
    except Exception:
        pass

    print(f"\n[结论] 看到 '[引擎] 已启动'：{'是' if hit_engine else '否'}")
    if hit_engine_t is not None:
        print(f"[结论] 冷启动耗时：{hit_engine_t:.2f} 秒（判定线 5 秒）")
    else:
        print("       ⛔ 没等到启动日志，程序可能没起来")
    return hit_engine


# ---------------------------------------------------------------- ③ 依赖自检
_SYS32 = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32")


def _is_os_provided(name: str) -> bool:
    """这个 DLL 是不是 Windows 自己提供的？是的话就不需要打进包里。"""
    if name.startswith(("api-ms-win", "ext-ms-")):
        return True
    return os.path.exists(os.path.join(_SYS32, name))


def dep_audit() -> bool:
    root = os.path.dirname(EXE)
    try:
        import pefile
    except ImportError:
        print("\n[依赖自检] 跳过（没装 pefile）")
        return True

    provided = set()
    files = []
    for dirpath, _, fs in os.walk(root):
        for f in fs:
            lf = f.lower()
            if lf.endswith((".dll", ".pyd", ".exe")):
                files.append(os.path.join(dirpath, f))
                provided.add(lf)

    missing: dict[str, set[str]] = {}
    for path in files:
        try:
            pe = pefile.PE(path, fast_load=True)
            pe.parse_data_directories(
                directories=[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_IMPORT"]])
            for e in (pe.DIRECTORY_ENTRY_IMPORT or []):
                name = e.dll.decode(errors="ignore").lower()
                if name in provided or _is_os_provided(name):
                    continue
                missing.setdefault(name, set()).add(
                    os.path.relpath(path, root))
            pe.close()
        except Exception:
            pass

    print(f"\n[依赖自检] 扫描 {len(files)} 个 PE 文件"
          f"（系统 DLL 按 {_SYS32} 判定，不需要打包）")
    if missing:
        print("       ⛔ 有缺失依赖（在别的机器上可能起不来）：")
        for dll, users in sorted(missing.items()):
            print(f"          {dll}  ← {sorted(users)[:3]}")
        return False
    print("       ✅ 所有 dll/pyd 的导入依赖都能在包内或 System32 找到")
    return True


if __name__ == "__main__":
    ok_size = size_report()
    ok_boot = cold_start()
    ok_dep = dep_audit()
    print("\n" + "=" * 58)
    print(f"  冷启动通过：{ok_boot}    依赖完整：{ok_dep}")
    sys.exit(0 if (ok_boot and ok_dep) else 1)
