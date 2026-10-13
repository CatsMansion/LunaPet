> ⛔ 本文件是**脱敏公仓版**：所有本机绝对路径已替换为占位符
> （`<SRC_ROOT>` / `<SRC_PARENT>` / `<VENV_PY>` / `<TOKEN_FILE>` / `<TOOLS_DIR>` ...），
> 不含任何 `C:/Users/<user>` 路径，也不含任何凭据。
> 含真实路径、命令可直接复制执行的**完整版保存在本地工作区，不进公仓**；
> 改流程时两边要同步更新。

# LunaPet 白名单发布工作流 SOP（定时任务执行端交接包）

> 本文档是 Ronny 手工每轮发布的「完整决策 + 机械步骤」打包版。定时任务执行端（AI Agent）
> 读本文档 + 调用 `<TOOLS_DIR>/lp_round.py`，即可在无人值守下自主跑发布轮次，
> 并对「能否自动带红灯推送」做出与 Ronny 一致的裁定。
>
> **核心哲学（来自 Ronny 的硬规则）：** 发布面默认拒绝一切，只发明确的引擎/测试/资产；
> 任何「疑似新回归 / 新合同绕过 / 核对失败」都**停下来上报 Ronny**，绝不自行猜判或静默跳过。

---

## 0. 一句话流程

```
scan → stage(白名单排除+md5复检) → selftest(venv python) → verify(pre) → audit → triage
   └─ DECISION=PUSH  → github-publish.py(注入token) → verify(post) → 写日志
   └─ DECISION=ESCALATE → 不上推，输出原因，等 Ronny 拍板
```

助手脚本 `lp_round.py` 已封装全部机械步骤；下面每节都给出「脚本命令」与「脚本在做什么 / 为什么」。

---

## 1. 先决条件（环境）

| 项 | 值 | 说明 |
|---|---|---|
| 仓库 | `CatsMansion/LunaPet`@`main` | REST 发布，从不 `git add .`，从不删除远端文件 |
| 发布脚本 | `<TOOLS_DIR>/github-publish.py` | blob→tree→commit→ref |
| 差异扫描 | `<SRC_PARENT>/_cmp_luna.py` | **必须从 `自研引擎` 的父目录运行**（它按 `cwd/自研引擎` 算 ROOT）；token 硬编码读 `gh_tok` |
| 源码根 | `<SRC_ROOT>` | 引擎在 `pet_engine/`，自测是顶层 `_自测_*.py` |
| venv python | `<VENV_PY>` | **带 PySide6 6.11.2** —— 跑自测必须用这个，裸托管 python 会 `ModuleNotFoundError: PySide6` 崩出假红灯 |
| Token 文件 | `<TOKEN_FILE>` | 不含换行；`github-publish.py` 回退 `git credential fill` 会超时 25s，必须内联注入 |
| 暂存目录 | `<STAGE_DIR>` | 由脚本重建 |
| 提交信息 | `<MSG_FILE>` | **必须用 `--message-file`（newline=""）**，直接拼命令行会被 shell 吃掉 |

> ⚠️ 若工作目录/路径变更（如新会话换了 `2026-MM-DD-HH-MM-SS` 目录），用同名环境变量覆盖：
> `LP_SRC_PARENT` / `LP_ROOT` / `LP_CMP` / `LP_PUBLISHER` / `LP_VENV_PY` / `LP_TOK_FILE` / `LP_STAGE` / `LP_MSG` / `LP_MEM`。

---

## 2. 发布面（白名单合同）—— 默认拒绝

**只发以下两类，其余一律不发：**
1. **已在远端**的文件（改动后重新上传；远端保留未改动文件）。
2. **新文件**仅限严格模式：
   - `pet_engine/<纯ascii标识符>.py`（真实引擎模块；排除 `.bak*`、含中文的旧快照如 `_夜night_before_*.py`）
   - 顶层 `_自测_*.py`（排除指路牌 `_自测_QTE.py`）
   - 顶层资产/文档：`app_icon.ico`、`build.md`、`引擎设计-自研桌面宠物.md`

**永不发（脚本已硬拒）：** `启动*.bat` / `直接开玩.bat`（含硬编码 `<HOME>`）、
`LunaPet_v*.zip`、`.spec`、`assets_game/`（含 `custom_terrain.json`）、`tools/`、`_work/`、
`_pr32_shots/`、以及一切 `_dbg_*`/`_t_*`/`_做*`/`_对比*`/`_诊断*`/`_验*`/`_测*`/`_量*`/`_看*`/`_v_*`/`_核验*`/`_patch_*`/`_pr*_probe*` 等本地一次性脚本与调试产物。

> 这正是手工轮次的实际行为：round-8/9/10 每轮只发了 3~5 个文件。
> 自动轮次会顺带把「还没发过的新引擎/测试/资产」补齐进仓库，属于预期内的发布面扩张。

---

## 3. 逐步操作（每轮）

### 3.1 扫描差异
```
python lp_round.py scan
```
- 跑 `_cmp_luna.py --scan`：列出「已发布文件差异（已改）」+「本地未跟踪候选」。
- 解析结果写入 `_lp_scan.json`。
- **判定：** 若「已改」为空且「未跟踪候选」里没有任何白名单新模式文件 → 本轮无内容可发，直接报告「无变更」并结束（不要空推）。

### 3.2 暂存（白名单排除 + md5 复检）
```
python lp_round.py stage
```
- 依据白名单合同（第 2 节）把文件拷到 `lp_stage`，保留相对路径（`pet_engine/x.py` 与 `_自测_x.py` 同构）。
- **md5 复检：** 拷完比源文件 md5；任何一项源≠暂存 → 说明「scan 之后源被编辑过」，立即 STOP（编辑中风险）。
- 落盘 `_lp_stage.json`（keep/dropped）。

### 3.3 全量自测（必须用 venv python）
```
python lp_round.py selftest            # 全量，约 10~20 分钟
# 或限定： python lp_round.py selftest 夜间 冰箱
```
- 脚本内部用 `VENV_PY` 调 `_自测_全部.py`，逐测解析 `(ok, total, status)`。
- **环境必须：** `QT_QPA_PLATFORM=offscreen`（无头不弹窗）、`PYTHONIOENCODING=utf-8`（中文汇总行不被乱码）。
- 解析结果写入 `_lp_selftest.json`。
- ⚠️ 若用错解释器（裸托管 python）→ 大量 `ModuleNotFoundError: PySide6` 假红灯，结果作废。

### 3.4 推送前字节核对（pre）
```
python lp_round.py verify              # 不带 commit 参数 = pre
```
- 比对暂存文件 vs 当前远端 HEAD：已改→sha 差异（预期）、新增→远端缺失（预期）。确认无异常。

### 3.5 远端全量复核（audit）
```
python lp_round.py audit
```
- 拉全量远端 tree（53+ 文件），检查：① 排除类泄漏 0；② `C:/Users` 硬编码 0，且**阳性对照先过**（正则必须能命中已知 `<HOME>` 串，否则 0 命中不可信）。
- 必须 `PASS` 才能推。

### 3.6 裁定（triage）
```
python lp_round.py triage
```
- 读 `_lp_selftest.json`，套第 4 节矩阵，输出 `DECISION: PUSH` 或 `ESCALATE` + 原因。

### 3.7 推送（仅当 PUSH）
```
python lp_round.py run --push --yes     # 等价于 3.1~3.6 串联 + 真正推送
```
或直接手动：
```
export GITHUB_TOKEN="$(cat <TOKEN_FILE> | tr -d '\n\r')"
python <TOOLS_DIR>/github-publish.py \
  --owner CatsMansion --repo LunaPet --dir <STAGE_DIR> \
  --message-file <MSG_FILE>
```
- **成功信号 = 打印 `done : ... commit=<40位sha>` 行**，不是退出码。
- 推送后自动 `verify(commit_sha)` 做**字节级 post 核对**：逐 blob 取 `/git/blobs/{sha}` 解码比对源文件，`ALL BYTE-EXACT: True` 才算真成功。

---

## 4. 裁决矩阵（执行端拍板规则）

### 4.1 允许自动「带红灯」推送（PUSH）当且仅当**全部**满足：
- 红灯测试集合 ⊆ 基线 `{_自测_编辑视角.py, _自测_PR04判据.py, _自测_音频.py}`；
- 且每个基线红灯的 `(ok, total)` **完全等于**基线值（见下）；
- 且无任何 `NORESULT / NOGROUP / TIMEOUT`（状态不明 = 按红灯处理 → 升级）；
- 且 3.2 md5 复检全过、3.4/3.5 全过、3.7 `done:` 行出现且 post 核对 `ALL BYTE-EXACT: True`。

**基线红灯（round-10, commit `6a016967`）：**
| 测试 | 基线 (ok,total) | 性质（Ronny 已拍板） |
|---|---|---|
| `_自测_编辑视角.py` | 143 / 144 | ⑳-8 禁碰核对（PR30 白天档改了冻结函数 `_draw_bg`，本应走 `_draw_bg_slices`，Ronny 2026-10-12 拍板直接推带红灯） |
| `_自测_PR04判据.py` | 5 / 8 | 赃物清空设计变更（容器/冰箱删除） |
| `_自测_音频.py` | 129 / 131 | 历史遗留 2 项（QTE） |

> 绿灯变多（基线红灯转绿）是好事，仍允许 PUSH。

### 4.2 必须 STOP 并上报 Ronny（ESCALATE，绝不自动推）：
- **出现基线外的红灯测试名**（疑似新回归 / 新合同绕过）；
- **基线红灯的 `(ok,total)` 变差**（如 `_自测_编辑视角` 从 143/144 变成 140/144 → 多出失败）；
- **状态不明** `NORESULT / NOGROUP / TIMEOUT`（无法确认绿，保守升级；上报前可对该单测重试一次 `--keep-going` 再判定）；
- **md5 复检失败**（源在 scan 后被编辑）；
- **verify / audit 任何一项不过**（泄漏 / 硬编码命中 / 字节不等）；
- **缺少 `done : commit=` 行**（推送本身失败）；
- **scan 报告 0 变更**（无事可发，报告即可，不要空推）。

> 上报格式（给 Ronny）：列出触发了哪条规则 + 相关测试名/(ok,total) + 是否真推了（应否）。
> Ronny 拍板后，若允许带新红灯推，再**同步更新脚本顶部 `BASELINE_REDS`**（把新 (ok,total) 写进去），下次同型即可自动。

---

## 5. 固化坑（执行端必读，每条都踩过）

1. **自测必须用 venv python**：裸托管 python 缺 PySide6 → 假红灯。验证方法：先看打印的 `python:` 路径是否含 `envs/default`，再看首个自测是不是 `ModuleNotFoundError`。
2. **`GITHUB_TOKEN` 不在环境**：每 Bash 是新 shell，`github-publish.py` 回退 `git credential fill` 超时 25s。必须内联 `export GITHUB_TOKEN="$(cat gh_tok | tr -d '\n\r')"`。
3. **提交信息用 `--message-file` + `newline=""`**：直接 `--message "..."` 含引号/中文会被 shell 吃掉，发不出去且无报错。
4. **核对用全 SHA**：先 `/git/refs/heads/main` 取全 40 位 sha，再递归 `?recursive=1` walk tree（`pet_engine/` 是子树，根 tree 只列它为一个 tree 项）；短 SHA 调 `/git/commits/{sha}` 会 404。
5. **远端字节核对走 `/git/blobs/{sha}`（base64 解码）**，不要 `raw.githubusercontent.com` —— 中文文件名会 `UnicodeEncodeError`。
6. **硬编码扫描必须阳性对照**：先确认正则能命中已知 `<HOME>` 串，0 命中才可信。否则「扫不到」可能是正则坏了，不是真干净。
7. **成功看 `done : commit=` 行**，不是退出码。
8. **提交时区**：脚本显式带本地 `+11:00` 偏移（AEST/AEDT），GitHub 日历按提交自带时区算天。本地早上 10 点前推 → UTC 仍是前一天 → 格子亮到昨天；傍晚推才重合当天。**不要靠脚本打印的 `+11:00` 判断点亮哪格，要看 本地→UTC 日期。**
9. **`_cmp_luna.py --scan` 的「未跟踪」列表极宽**（含所有本地一次性脚本/调试产物），**绝不能直接全量暂存**——必须过第 2 节白名单合同（脚本已默认拒绝）。

---

## 6. 日志（每轮结束必须落盘）

追加到 `<MEM_DIR>/YYYY-MM-DD.md`：
```
## round 自动发布 <日期>
- commit = <sha>（短 <8位>），head 前 = <prev>
- 发布 N 文件：<列表>
- 自检：<DECISION>；红灯 <集合/基线比对结论>
- 验证：md5 源=暂存 N/N；pre/post 字节级 ALL BYTE-EXACT: True；audit PASS（M 文件 / 泄漏 0 / 硬编码 0）
- 备注：<时区点亮日期 / 任何偏离>
```
> 用 `LP_MEM` 可覆盖日志目录。若「今日」日志文件不存在先新建。

---

## 7. 异常/降级

- **网络/API 不可达**：`api()` 自带 3 次重试；仍失败则 STOP 上报，不要反复重试烧时间。
- **自测某组 TIMEOUT**：先对该组 `selftest <关键字> --keep-going` 重试一次；仍超时 → ESCALATE（慢≠红，但无法确认绿）。
- **post 核对 `ALL BYTE-EXACT: False`**：说明发出去的内容和源不一致（极罕见，可能是 API 截断）→ STOP 上报，不要报告成功。

---

## 8. 交付物清单

- 本 SOP：`LunaPet发布工作流SOP.md`
- 助手脚本：`<TOOLS_DIR>/lp_round.py`（已实测 scan/stage/verify/audit 全过；selftest 解析已用 `技能` 单测验证；全量套件由执行端实跑）
- 实测基线：round-10 `commit 6a016967`，远端 53 文件，3 个基线红灯（见 §4.1）
