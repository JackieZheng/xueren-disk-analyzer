---
id: xueren-disk-analyzer
name: 雪人老师·磁盘空间分析器
title: 雪人老师·磁盘空间分析器
description: 给定磁盘（C/D/E/F 任选、多选或全盘）或任意目录，交互式分析空间占用并以图表展示。命令行静态报告 + 网页交互版（深色「任务实时进度面板」风：盘符下拉、目录选择、实时扫描进度卡片、可停止、各盘符使用率速览卡（按使用率分级配色预警、点击卡片切换盘符、近期消耗速度较快预警）、点击目录打开所在位置、路径太长中间省略号单行显示；明细表「占比(%)」占比口径准确、🛡️系统/👁️隐藏双属性标签可共存且隐藏项名灰色显示、文件行操作图标保留但灰置、盘符下拉自绘弹层与整体风格统一）。纯 Python，依赖 matplotlib + squarify（已装），零 CDN、离线自包含。当用户说"分析 C 盘""磁盘空间分析""哪个目录占空间""E 盘空间分析""做个磁盘分析工具"等意图时触发。
slug: xueren-disk-analyzer
displayName: 雪人老师·磁盘空间分析器
summary: 交互式磁盘空间分析（可选 C/D/E/F 或目录），图表展示占用，网页版带实时进度/可停止/点击打开目录。
description_zh: 给定磁盘（C/D/E/F 任选、多选或全盘）或任意目录，交互式分析空间占用并以图表展示。命令行静态报告 + 网页交互版（深色「任务实时进度面板」风），纯 Python，零 CDN 离线自包含。
description_en: Interactive disk space analyzer (choose C/D/E/F or a folder), visualize usage with charts; web UI with live progress card, stoppable scan, click-to-open folder.
version: 1.2.20
author: 雪人
license: MIT
allowed-tools: ""
display_name: xueren-disk-analyzer
display_name_zh: 雪人老师·磁盘空间分析器
trigger: ["分析 C 盘", "磁盘空间分析", "哪个目录占空间", "E 盘空间分析", "做个磁盘分析工具", "磁盘占用分析", "查看磁盘剩余空间"]
examples: "用户：做个磁盘分析工具，能选盘符出图表 → 跑 scripts/disk_analyzer.py --disk E 出静态 HTML 报告，或 scripts/disk_analyzer_web.py 起本地服务在浏览器交互分析（盘符下拉 + 实时进度 + 可停止 + 点击打开目录）。"
platforms: [ima, WorkBuddy, QClaw]
github: https://github.com/JackieZheng/xueren-disk-analyzer
skillhub: https://skillhub.cn/skills/indiv-xueren/xueren-disk-analyzer
metadata:
  author: 雪人
  category: 工具
---

# 雪人老师·磁盘空间分析器

## 概述

一个**交互式磁盘空间分析工具**，回答「我的磁盘空间被谁吃掉了」。两种用法：

1. **命令行静态报告**（`disk_analyzer.py`）—— 扫描指定磁盘/目录，输出一份**离线自包含 HTML 报告**：容量概览卡片 + 三张图表（①嵌套矩形树图 Treemap，面积=体积 ②Top N 横向条形图 ③环形占比图）+ 可点击表头排序的明细表。
2. **网页交互版**（`disk_analyzer_web.py`）—— 本地 HTTP 服务 + 深色「任务实时进度面板」风 SPA，支持：盘符下拉（C/D/E/F）、目录选择器（系统对话框选文件夹）、**实时进度卡片**（显示当前正在扫描的目录/文件 + 百分比 + 流动光带）、**可随时停止**、**点击目录行打开所在位置**、**路径太长时中间省略号单行显示**。

**硬指标**：纯 Python；依赖 matplotlib + squarify（本机 `D:\Python\Python312` 已装，通用解释器，跨 skill 共用）；图表 base64 内嵌、**零 CDN、离线可用**；Windows 下自动注册微软雅黑中文字体，图表中文不方块。

## 你的工作方式

1. **确认目标** —— 用户要分析哪个盘/目录：
   - 给**盘符** → 用 `disk_analyzer.py --disk <盘符>`（可 `C E` 多选、`all` 全盘）；
   - 给**目录** → 用 `--dir <绝对路径>`，或直接起网页版让用户自己点选。
2. **选形态** —— 想要一次性静态报告 → 命令行；想要交互（切换盘符/中途停止/点开目录）→ 网页版。
3. **跑扫描** —— 命令行直接出 HTML；网页版起服务后用户在浏览器操作，扫描经 SSE 实时推送进度。
4. **交付** —— 用 `present_files` 提供 HTML 报告，或打开网页地址 `http://127.0.0.1:<port>/` 预览。
5. **解读** —— 帮用户指出占用最大的目录（Top N），定位「元凶」（如微信缓存、自产视频等），给出清理/迁移建议（只读诊断，不擅自删改）。

## 执行流程

### Phase 1：准备与口径确认
- 确认分析的盘符/目录；跨盘对比时逐个跑 `--disk`。
- 依赖核验：`D:/Python/Python312/python.exe -c "import matplotlib, squarify"`；缺失则装到同一个通用解释器：`D:/Python/Python312/python.exe -m pip install matplotlib squarify`。**禁止 `pip install --user`、禁止往 managed venv 装**（会导致跨 skill 环境割裂，每个 skill 各自装一份）。
- **只读原则**：本工具只统计体积，**不删除/移动任何文件**；清理建议必须等用户确认再执行。

### Phase 2：执行扫描
- **统一用 `D:/Python/Python312/python.exe`**（本机通用 Python，已装 matplotlib/squarify 等常用库，跨 skill 共用，禁止另起 venv）
- 命令行：`D:/Python/Python312/python.exe scripts/disk_analyzer.py --disk E --depth 2 --top 15 --out disk_report_E.html`
  - `--depth 1` 仅顶层、`2` 顶层+下一级（默认 2）；`--top N` 条形图/明细表取前 N；
  - `--workers` 并行度（默认按 CPU 自适应）；`--dir <路径>` 替代 `--disk` 分析单目录。
- 网页版：`D:/Python/Python312/pythonw.exe scripts/disk_analyzer_web.py --port 8780` → 浏览器开 `http://127.0.0.1:8780/`（用 pythonw.exe 后台无窗口运行）
  - 加载后**不自动扫描**，显示空状态；用户选盘符/选目录后点「▶ 开始分析」。
  - 扫描中进度卡片实时显示「📍 当前：<目录>」与百分比；点「⏹ 停止」可中断（返回部分结果）。
  - 点目录行 / 行尾 📂 → 调资源管理器打开所在位置（仅本机已存在路径，防越权）。

### Phase 3：生成与交付
- 命令行产出 HTML（base64 内嵌三图），`present_files` 交付并预览。
- 网页版结果页即渲染完成，把网页地址交给用户即可。
- **强制校验**：打开产物目检——三张图均显示、明细表排序正确、容量卡片数值合理、长路径为中间省略号单行。

## 配置与参数

`scripts/disk_analyzer.py` 参数：

| 参数 | 必填 | 说明 |
|------|------|------|
| `--disk` | 二选一 | 盘符，可多值如 `E` / `C E` / `all` |
| `--dir` | 二选一 | 任意目录的绝对路径（分析单目录） |
| `--depth` | 否 | 扫描深度，1=仅顶层、2=顶层+下一级（默认 2） |
| `--top` | 否 | Top N 目录（条形图与明细表，默认 15） |
| `--workers` | 否 | 并行进程数，默认按 CPU 自适应 |
| `--out` | 否 | 输出 HTML 路径（默认 `disk_report.html`） |

`scripts/disk_analyzer_web.py` 参数：
- `--port`：本地服务端口（默认 8780）；`--host`：监听地址（默认 127.0.0.1）。

## 资源目录

### scripts/
- `disk_analyzer.py`：扫描内核 + 静态 HTML 报告生成（matplotlib 出 treemap/bar/donut 三图 + 明细表）。`analyze_disk`/`scan_top` 支持进度回调与取消标记；`setup_cjk_font()` 在模块加载时注册微软雅黑。
- `disk_analyzer_web.py`：本地 HTTP 服务（ThreadingHTTPServer）+ 实时进度面板风 SPA。`/scan` 用 SSE 流式推送进度（progress/done 事件），`/cancel` 中断扫描，`/open` 调资源管理器打开目录。复用 `disk_analyzer` 的扫描与绘图函数。

### references/
- `deps.md`：依赖与安装说明（matplotlib + squarify；Windows 字体处理）。

### assets/
无（图表运行时生成，无静态资源）

### data/
无

### log/
无（扫描不落日志）

## 更新记录

- **v1.2.20**（2026-10-13）—— **空间曲线横轴时间格式改为「MM-DD HH:MM」+ 30° 倾斜**：用户反馈「空间曲线横坐标内容叠加了」。
  - **原样式**：每个 tick 两行「第 N 次 / 完整时间戳（YYYY-MM-DD HH:MM）」，水平排布，标签过宽时相互重叠。
  - **新样式**：
    - 去掉「第 N 次」前缀（用户明确要求）
    - 时间格式改为 `MM-DD HH:MM`（如 `10-13 15:09`），紧凑一行
    - 标签 `rotation=30, ha="right", va="top"`（30° 上翘倾斜，右锚点对齐刻度）
    - x 轴标题从「扫描次序」改为「扫描时间」
  - **首尾裁切保护**：`fig.tight_layout()` 已在末尾兜底，无需额外调整
  - 文件：`scripts/disk_analyzer.py` `make_size_curve` 函数（约 18 行改动）

- **v1.2.19**（2026-10-12）—— **减少情形去掉冗余的绿色↓徽标**：用户反馈「变化列减少不显示值，显示个绿色↓图标」。
  - **根因**：`deltaHtml` 其实已经在输出 `▼ -X.X GB`（delta<0 分支），但同一行又追加了 `growthBadge='<span class="badge down">↓</span>'`。两个视觉元素叠在一起，右侧绿色 ↓ 徽标在视觉上抢占了「▼ -X.X GB」的位置，用户第一眼看到 ↓ 徽标，误以为没显示值。
  - **修复**：去掉 `delta<0` 分支的 `growthBadge` 赋值。
  - **变化列最终样式**：
    - 增加：`▲ +X.X GB`（红色），≥5GB 追加 🔥 快增徽标
    - 减少：`▼ -X.X GB`（绿色），无徽标，与 ▲ 对称
    - 平/空：`—`（灰色）
  - 符号（▲/▼）+ 数值 + 颜色，三层信息完整；再挂 ↓ emoji 徽标属冗余。

- **v1.2.18**（2026-10-12）—— **变化列 tip 只保留 4 项核心字段**：用户反馈 v1.2.17 三行排版仍嫌啰嗦，希望简化为「本次 / 上次 / 变化 / 间隔」四项。移除 v1.2.17 的 delta_note split 分流逻辑（复杂且冗余），delta_note 里的「上次快照 X / 含 N 节点 / Y 前」「本次扫描 Z / 含 M 节点」等扫描元信息尾巴全部从 tooltip 去掉（这些已在页面其它地方可看）。
  - 4 行输出：`本次：X` / `上次：Y` / `变化：±Z` / `间隔：T`（每项一行，用 `\n` 换行）
  - 空值兜底：无上次→`上次：—`；无 delta→`变化：—`；无 days_gap→`间隔：—`
  - 保留 tip CSS 已有的 `white-space:pre-wrap`，自动多行显示
  - 变化字段的符号逻辑：增加前面加 `+`，减少前面加 `-`（负数时 `Math.abs` 后拼接，保证 `-` 号在数字前）

- **v1.2.17**（2026-10-12）—— **变化列 tip 分三行排版**：用户反馈"变化列悬浮提示一行到底，读起来看不明白"。改 `deltaTooltip` 输出 `\n` 分行（配合 tip CSS 已有的 `white-space:pre-wrap`）：
  - **行 1**：本次 / 上次 / 变化（大小三元组，快速判断增减幅）
  - **行 2**：间隔 / 上次快照信息（时间差 + 基准快照容量与节点数）
  - **行 3**：本次扫描信息 + 备注（本次扫描总量/节点数、"本次新增条目"等特殊标注）
  - 后端 `delta_note` 用 `  ·  ` 拼接，前端 split 后按语义分流：以 `上次快照` / `首次扫描` 开头的段归入第 2 行，其余归入第 3 行
  - 兼容三种边界：首次扫描（无上次）、新增条目（`本次新增条目（上次快照无此条目）`）、正常有 delta
  - `max-width: 300px` 不变，单行过长仍 wrap

- **v1.2.16**（2026-10-12）—— **tip 箭头加描边（双层 clip-path 叠加）+ 图标语义更贴切**：
  - **箭头**：用户反馈 v1.2.15 单层 clip-path 纯色三角无描边、与 tip 主体（1px #43607c 边框）轮廓不连续。改为**双层叠加**：外层 #43607c（描边色）+ 内层 #0d1620（填充色），内层比外层小 2×borderWidth 并沿三角指向方向贴齐。4 方向 polygon 保持 v1.2.15 定义（top 朝下 / bottom 朝上 / right 朝左 / left 朝右），宽高按 s=5 + bw=1 计算。arrowSize=5、鼠标跟随、4 方向自适应逻辑全部保留。
  - **图标**：用户反馈文件列表操作列 🔍（下钻分析）和 💡（百度搜索）语义不明确。
    - 🔍 → **📊**（表格图标，语义更贴「下钻分析/查看层级」）
    - 💡 → **🌐**（网络图标，语义更贴「外部搜索」）
    - 📂（打开）保留不变
    - 同步更新页面底部图例说明文字与 tip 悬浮文本
- **v1.2.15**（2026-10-12）—— **tip 箭头去描边**：v1.2.14 用 `border-left/right/bottom/top: Xpx solid transparent + Ypx solid 颜色` 的 CSS border-trick 生成三角箭头，透明 border 在部分浏览器仍残留可见描边（用户反馈"要么不有，要么有但没有描边"）。改用 `clip-path: polygon()` + `background` 生成纯色三角：`top` 朝下 `polygon(0 0, 100% 0, 50% 100%)`、`bottom` 朝上 `polygon(0 100%, 100% 100%, 50% 0)`、`right` 朝左 `polygon(100% 0, 100% 100%, 0 50%)`、`left` 朝右 `polygon(0 0, 0 100%, 100% 50%)`。宽高按方向：`top/bottom` = `2s × s`，`left/right` = `s × 2s`。arrowSize=5 不变，位置偏移逻辑（`bottom:-s` / `top:-s` / `left:-s` / `right:-s`）不变，鼠标跟随不变。clip-path 剪一刀就是纯三角，无 border 概念，天然无描边。
- **v1.2.14**（2026-10-12）—— **tip 气泡箭头对齐鼠标（参考 `title2tip.js`）**：v1.2.12 自研版把箭头固定指向 element center、只支持 above/below 两方向、鼠标在元素内移动气泡不跟随，用户反馈"箭头效果不对，参考 tooltip"。按 `E:\MiniCode\imageview&title2tip\title2tip-js\src\title2tip.js` 的思路重写：① `calcPos(el, mx, my, tipW, tipH)` **4 方向自适应**（top/bottom 以鼠标水平居中，left/right 以 target 垂直居中，视口空间不足时自动翻转）；② `setArrow(dir, offX, offY)` 内联 cssText 生成三角（不用 CSS 变量、直接由 JS 计算），arrowSize=5；③ 鼠标坐标驱动 `offX = mx - left`，clamp 到 `[margin, tipW - margin]`——**箭头跟随鼠标**而非 target center；④ `mousemove` 里对 activeEl 实时更新位置；⑤ `mouseover`/`mouseout`（判断 `relatedTarget.contains()` 决定要不要隐藏）事件委托；⑥ `MutationObserver` 自动把遗留 `title` 迁移为 `tip`（属性新增/变更都覆盖）；⑦ **safe parent 检测**：position:fixed 会被祖先 `transform/perspective/filter/backdropFilter/zoom` 破坏，向上扫找无这些属性的父节点挂载；⑧ offset=16px / edgeThreshold=16 / max-width=300 / fontSize=12 / padding 5px 9px / borderRadius 6，全对齐 title2tip.js 默认。删掉旧 CSS 里 `.tip.below`/`.tip.above .arrow`/`.tip.below .arrow`（箭头改由 JS 生成）。13 处 `tip=` 属性无需改动，自动走新系统。
- **v1.2.13**（2026-10-12）—— **启动无 cmd 黑窗**：`disk_analyzer_ctl.py` 的 `_spawn_detached` 去掉 `cmd /c ""pythonw.exe" ...` 包装层，改为 `WMI Win32_Process.Create` 直接创建 `pythonw.exe` 进程（pythonw 是 GUI 子系统 exe，无控制台，不会创建 cmd 窗口）。原来包 cmd 是为了给 pythonw 一个有效 stdout 句柄（避免 WMI 不传 stdio 时 `sys.stdout is None` 让 print 崩）；这个坑改由 `disk_analyzer_web.py` 顶部提前保护：import 后立即检测 `sys.stdout / sys.stderr / sys.stdin` 是否为 None，是的话用 `_open_log()` 重定向到 `~/.workbuddy/disk_analyzer_<port>.log`（追加模式），stdin 指向 `os.devnull`。这样既无窗口闪现、又有 traceback 可查。ctl.py status 显示"会话外 ✅"、日志能捕获启动 print（`[disk_analyzer_web] 已启动：http://127.0.0.1:8780/`）、HTTP 返回 `Version: 1.2.13` 三项均通过。**此约定今后推广到所有本地常驻服务**（用户 2026-10-12 明确要求）。
- **v1.2.12**（2026-10-12）—— **title 全部换成自定义 tip，带指示 target 的箭头**：原生 `title` 悬浮灰气泡无样式、无箭头、位置固定、样式粗糙，12 处 `title=` 全部替换为自定义属性 `tip=`（保留按钮的 `aria-label` 无障碍）。新增全局 tooltip 系统：`.tip` 深色气泡（`#0d1620` 底 + `#43607c` 边 + 8px 圆角 + 阴影 + 220ms 淡入 + `pre-wrap` 保留换行）+ `.arrow` 6px CSS 三角箭头（`above` 朝下指 target / `below` 朝上指 target，用 `--arrow-x` 变量动态偏移让箭头始终指向被 hover 元素中心，视口 8px 内边距 clamp）。JS 全局 mouseover/mouseout 事件委托捕获任何带 `tip` 属性的元素（120ms 显示延迟、60ms 隐藏延迟，避免快速划过闪断），视口空间不足时自动切到元素下方；`mouseleave`/`scroll`/`resize` 触发即时隐藏避免残影。13 处 `title=` 全量替换（清空按钮、占比表头、快增徽章、隐藏/系统徽章、📂🔍💡 三个操作按钮、路径列、变化列 delta 悬浮、占比警示徽章、消耗较快徽章）。有 tip 的按钮 hover 加 1px 虚线外框作为「此元素可悬停」提示。
- **v1.2.11**（2026-10-12）—— **占比悬浮提示加上分母上下文**：明细表「⚠」占比标签的 `title` 悬浮提示由「占比大：本条占本次扫描总量 ≥15%，建议优先排查」升级为「占比大：本条占本次扫描总量 ≥15%，建议优先排查 · 本次扫描总量 X.X GB」，把"占比"的分母（本次扫描总量）直接暴露给鼠标 hover 的用户，消除「27.9 GB 只占 38.2% 感觉不对」这类直觉困惑（27.9/73=38.2%，但用户直觉分母是 E:\ 已用 131.5 GB 会算出 21.2%，两者都是"对的"，只是分母不同）。分母为 0 或空扫描时不加尾巴，保持文案干净。
- **v1.2.10**（2026-10-12）—— **增量数据准确性根治**：新增 `~/.workbuddy/data/disk_analyzer/snapshots/{key}/*.json` 快照存储（每次扫描落一份完整节点快照，含 `ts / scanned_bytes / capacity / nodes[]`，每 key 保留最近 30 份自动清理）；`_apply_growth` 改为读取最新一份快照作为"上次"，替换掉原「单一 slot 覆盖式」的 `disk_analyzer_history.json`（该文件仅保留 `__last__` 供页面默认回填）。每节点独立算 delta（保留可信 delta，不再整批置 None），并在 `delta_note` 里附带"上次快照 X / 含 N 节点 / M 前 · 本次扫描 Y / 含 N 节点"完整上下文；前端明细表「变化」列 `<td>` 加 `title` 属性鼠标悬停显示「本次 / 上次 / 变化 / 间隔 / 备注」，用户可自行判断"上次扫描是否完整"（如"上次 25 GB / 本次 46 GB"一眼可辨上次不完整）。表格内两个属性标签也简化：`⚠大/⚠中` → 单图标 `⚠`（红色/黄色区分），`🔥快增` → 单图标 `🔥`，`title` 悬浮显示完整文字，大幅收缩表格宽度。附 7 场景单元测试（首次扫描 / 正常 delta / 上次差异大 / 新增条目 / 快照落盘 / 快照清理 / 路径安全化）+ 端到端验证（两次真实扫描确认快照持久化与 delta 回填正确）。
- **v1.2.9**（2026-10-12）—— 走势曲线横坐标改等间隔：`make_size_curve` 的 x 轴由「按真实时间戳分布」改为「按扫描序号等间隔」（`xs = list(range(n))`），彻底消除早期密集扫描把曲线挤成一根斜线、后期稀疏点又拉开长段空白的问题；每个 tick 显示两行「第 N 次 / YYYY-MM-DD HH:MM」保留时序信息但不参与定位，首尾标签分别左/右对齐避免被裁；`set_xlim(-0.5, n-0.5)` 给首末点留出标记半径空间，`tight_layout` 让两行 x 标签完整可见。同步配套：新增 `scripts/disk_analyzer_ctl.py`（对齐 `xueren-workbuddy-live-progress` 的 WMI 会话外常驻方案，提供 `status/check/start/spawn/stop/restart` 六个子命令，取代此前依赖会话内 nohup 的不稳定启停）。
- **v1.2.8**（2026-10-11）—— 图表单位自适应：走势曲线（`make_size_curve`）与条形图（`make_bar`）纵轴原硬编码 GB，扫小目录时出现 `0.0 GB` 不可读。新增共用 helper `_pick_unit()`，按数据最大值自动落档 B/KB/MB/GB（小数位 0/1/2/1），轴标题、数值标注、条尾标签全部跟随单位自适应。treemap/donut 本就用 `human()` 自适应，无需改。
- **v1.2.7**（2026-10-11）—— 明细表占比表头统一：原网页版「占目标%」与静态报告「占磁盘%」两处口径不一，现**统一重命名为「占比(%)」**（仍保留 `title` 悬浮说明分母是当前扫描目标而非整盘容量）；同步图例、说明块、README/SKILL/meta 描述文案，历史 changelog 保留原措辞不回溯。
- **v1.2.6**（2026-10-11）—— 图表区排列按用户标注口径修正：**4×1 = 四个一行**（4 列 1 行）、**2×2 = 两行两列**。即默认（宽屏）`#charts .grid{repeat(4,minmax(0,1fr))}`（四张一行），窄屏（≤960px）`repeat(2,...)`（2×2），与上方「盘符统计四卡片」看齐；撤销 v1.2.5 误把 4×1 当成竖排的改法。
- **v1.2.5**（2026-10-11）—— 图表区排列**对齐盘符卡片**：撤销 1×4 宽屏单行，改为**默认 2×2**（`#charts .grid{grid-template-columns:repeat(2,minmax(0,1fr))}`）+ **窄屏 4×1**（`@media (max-width:960px){#charts .grid{1fr}}`）。即与「各盘符使用情况」四张卡片同样的 2×2 / 4×1 两档响应式行为，去掉中间 1280 断点。
- **v1.2.4**（2026-10-11）—— 图表区**响应式自动排列**：宽屏 `1×4`（默认 `repeat(4,minmax(0,1fr))`）→ 中屏 `2×2`（`@media (max-width:1280px)` 改 `repeat(2,...)`）→ 窄屏 `4×1`（`@media (max-width:960px)` 用 `#charts .grid{1fr}`，注意须用 `#charts .grid` 而非 `.grid` 才能覆盖基础规则，否则因选择器优先级更高仍维持 4 列）。`minmax(0,1fr)` 全程防止图片固有宽度撑破网格。
- **v1.2.3**（2026-10-11）—— 图表卡片标题对齐与精简：① `.ct` 标题区**固定两行高度**（`line-height:1.35;height:38px` + `-webkit-line-clamp:2` 溢出省略），消除单行四列布局下各卡标题换行行数不一导致图片起始位置参差不齐的问题；② 四张图表标题精简字数——「① 矩形树图 Treemap（面积=体积）」→「① 矩形树图 Treemap」、「② Top N 横向条形图」→「② Top N 条形图」、「④ 空间大小走势曲线 · 最近30次」→「④ 空间走势曲线 · 点击放大」，全部单行放得下。
- **v1.2.2**（2026-10-11）—— 图表区两项视觉优化：① 布局由 2×2 改为**单行四列**（`#charts .grid{grid-template-columns:repeat(4,minmax(0,1fr))}`），4 张图一行铺满更紧凑；② **空间大小走势曲线横轴由扫描次数改为扫描时间**（时间戳按真实间隔分布，稀疏抽点显示 `YYYY-MM-DD HH:MM` 标签、旋转 30° 防重叠，标题标注首末时间）。`minmax(0,1fr)` 防止图片固有宽度撑破网格；移动端媒体查询仍为单列。
- **v1.2.1**（2026-10-11）—— 图表区布局优化：4 张图由 `auto-fit` 自适应改为**固定 2×2 布局**（`#charts .grid{grid-template-columns:repeat(2,minmax(0,1fr))}`），消除最后一行单张图被拉伸/留白的尴尬；`minmax(0,1fr)` 防止图片固有宽度撑破网格。移动端媒体查询仍为单列。
- **v1.2.0**（2026-10-11）—— **新增第四张图表：空间大小走势曲线**。每次扫描完成自动记录目标空间大小（盘符→盘容量 / 目录→目录总占用），按目标键保留最近 **30 次**扫描记录（独立文件 `~/.workbuddy/disk_analyzer_size_curve.json`，跨会话持久、自包含）；结果页新增第 ④ 张卡片，matplotlib 绘制**面积+折线走势图**（x=扫描次数 1..N、y=GB，标注首末时间与末值），与 treemap/条形/环形同为 12×8 等大风格、支持点击放大；历史不足 2 次时卡片显示「📈 数据采集中」提示。与 v1.1.0 的盘符级空闲采样（用于消耗速度预警）口径不同，本曲线聚焦**扫描目标自身的空间增长轨迹**。
- **v1.1.1**（2026-10-11）—— 各盘符概览卡片的鼠标悬停提示由原生 `title` 升级为**自定义富信息 tooltip**：hover 卡片弹出深色详情卡，展示盘符、总容量、已用、剩余、使用率与分级预警，并附近期消耗速度（近N天 +X GB ≈Y GB/天，或「监测采集中…」）；底部加「点击卡片切换并扫描」引导。通用 tooltip 引擎（事件委托 + 边界翻转 + 跟随光标）复用，后续任意元素加 `data-tip` 索引即可。
- **v1.1.0**（2026-10-11）—— 「各盘符当前使用情况」卡片新增**近期消耗速度较快预警**：
  1. **时间序列采样**：新增独立轻量采样文件 `~/.workbuddy/disk_analyzer_drive_speed.json`，每次 `/drives` 调用时记录各盘 free 字节 + 时间戳（仅空闲量变化或距上次采样 ≥60s 才记，避免刷新刷屏；每盘保留最近 7 天/最多 120 个样本）。
  2. **速率与预警**：取最近 7 天窗口算日消耗速率（GB/天）；采集不足 6 小时显示「消耗监测采集中…」；日耗 ≥2GB 判为「**消耗较快**」，卡片加橙色脉冲徽标 `⚡ 消耗较快`，副行显示「近N天 +X GB ≈Y GB/天」；空间下降/平稳显示「释放/平稳」。
  3. **图例同步**：底部分级图例补一枚 `⚡消耗较快` 芯片（橙色圆点）说明该预警态。只读、自包含、跨会话持久。
- **v1.0.9**（2026-10-10）—— 明细表对齐优化：①「最后修改 / 子项 / 操作」三列的表头与内容由右对齐改为**居中对齐**（新增 `th.ctr,td.ctr` 样式，单元格保留等宽数字）；②「操作」列右侧加 22px 留白（`#tbl :last-child{padding-right:22px}`），按钮不再紧贴卡片右边缘，列宽同步 112px→134px。其余数值列（大小 / 占目标% / 变化）保持右对齐不变。
- **v1.0.8**（2026-10-10）—— 明细表「操作」列新增 💡 问百度：遇到不认识的文件或目录，点击图标直接新标签页打开百度搜索「它是什么、干什么用的」（按类型组织问句：文件→「是什么文件 有什么用」/ 目录→「是什么文件夹 干什么用的」），免登录、公开免费。操作列宽同步由 90px 加宽到 112px 容纳第三枚按钮；底部图例同步补充 💡 说明。
- **v1.0.7**（2026-10-10）—— 「各盘符当前使用情况」标题补分级图例：四个状态词（充足 / 偏高 / 紧张 / 告急）前各加一枚对应颜色的圆形色块（`.drvlegend` / `.drvlg` / `.drvlg i`），颜色与卡片左侧分级色条一致，一眼看清「颜色 ↔ 等级」的对应关系。功能无变更。

- **v1.0.6**（2026-10-10）—— 新增「各盘符当前使用情况」速览模块（置顶任务与盘符选择之间）：
  1. **新增模块**：网页版顶部「置顶任务」卡与盘符工具条之间插入「💽 各盘符当前使用情况」卡，风格沿用「当前选择目录使用情况」的统计卡（深色底 + 左侧语义色条 + 数值 + 进度条）；**点击卡片即切换盘符**（复用「切盘符清空路径」逻辑，并同步刷新下拉与选中态）。
  2. **四级预警配色**：按使用率分级——充足 <70%（绿）/ 偏高 70~85%（黄橙）/ 紧张 85~95%（橙红）/ 告急 ≥95%（红）；容量读不到的盘（空光驱、网络盘）显示「未知」灰态。左侧色条、百分比数值、进度条填充三处同色，当前盘带「当前」徽标。
  3. **数据来源**：新增后端接口 `GET /drives`（`drives_usage()` = `list_fixed_drives()` + `disk_capacity()` 取 total/free/used/pct）；页面加载与每次扫描完成后各刷新一次使用率。
  4. 小屏（≤640px）卡片两列排布。

- **v1.0.5**（2026-10-10）—— 图表长名全实测动态收缩 + 表格列宽优化：
  1. **条形图**：`_fit_left_margin` 升级为 `_shrink_ylabels`——实测全部标签所需左边距动态加宽（上限 34% 画布宽，防吃掉绘图区），到上限仍被画布左缘削掉的标签逐条中间收缩直到放进画布；初始 cap 22→40 字。**不再有固定字数假设，全程渲染器实测**。
  2. **环形图**：图例初始 cap 16→24 字；右缘越界先左移饼图腾空间，仍越界则**迭代收缩最宽图例项**（`rpartition("  ")` 保住尾部百分比）。
  3. **明细表列宽压缩**（网页版）：`td.num` 加 `nowrap` + 紧凑 padding（左 4 右 9），colgroup 44/90/88/120/130/56/104 → 40/82/66/112/122/46/90，固定列合计 632→558px，名称列多拿 ~74px。
  4. **报告表格列宽修正**：根源是全局 `table{table-layout:fixed;min-width:720px}` 令报告表各列**均分**、名称列只拿 1/6——`.report table` 覆盖为 `table-layout:auto;min-width:100%`，非名称列加 `td.cnum`（`width:1%+nowrap`）压缩到内容宽，`nmcell` 上限 300→560px；表格外包 `.tbl-wrap`（超宽时横向滚动，与明细表一致）。
  5. **旧缓存陷阱（重要）**：网页版打开时还原「上次扫描快照」（`disk_analyzer_last_result.json`），快照里的图表是**生成时的 base64**——改绘图代码后必须重新扫描才能看到新效果；用户报「图表还没修好」时先分辨是缓存旧图还是真回归。本次已清除旧快照。

- **v1.0.4**（2026-10-10）—— 报告表格长名显示修复 + 标题统一：
  1. **报告三张表长名处理**：诊断报告（`build_report_blocks` → `blocks_to_html`）的「顶层目录体积排行（降序）」「占用最大目录下钻」「较上次扫描增长最快」三张表，名称列改内层 `span.nmcell`（定宽 300px 省略）+ `title` 悬浮看全名——旧版原样输出完整长名且网页端无宽度约束，超长名溢出/显示不全。截断交给 CSS 单点负责（与明细表口径一致），HTML 仍输出全名供 `title` 与页面内查找。
  2. **网页标题与顶部标题统一**：`<title>` 与顶部 `<h1>` 统一为「磁盘空间分析器 Ver：{版本}」（全角冒号），h1 保留 SVG 图标；版本号改为单一来源——新增 `VERSION` 常量 + 模板占位符 `__VERSION__`（复用 `__START_CMD__` 替换链），消除 title/h1 两处硬编码漂移；删除已废弃的 `.topbar .ver` 样式与 `<span class="ver">· Ver:x.y.z</span>`。
  3. CLI 报告（`build_html`）明细表名称列补 `title` 悬浮看全名。

- **v1.0.3**（2026-10-10）—— 三张图表长名显示修复 + 网页版窄屏优化：
  1. **排行图（条形图）**：y 轴长名中间省略（`_mid_ellipsis`，保留首尾与扩展名），并用渲染器实测标签宽度**动态加宽左边距**（`_fit_left_margin`）——旧版直接用原始长名，超出默认左边距被画布左缘削掉一截。
  2. **环形图**：图例名称中间省略到 16 字、**百分比并入图例文案**；小切片（<2.5%）不再往扇区上叠百分比文字（避免互相糊成一团）；实测图例右缘越界时**自动左移饼图坐标区**——旧版图例长名伸出画布右缘被截断。
  3. **树图（Treemap）**：标签按矩形**实测像素宽自动收缩**（`shrink_to_fit`：用 `ax.transData` 求每数据单位真实像素 + 渲染器实测文字宽，超宽逐步中间收缩）——旧版「头部截断+尾部省略」既丢扩展名（.pptx 等）也不随矩形宽度自适应，长名还会溢出压到邻格。**注意勿改回估算公式**：坐标区默认只占画布 77.5%，按「数据单位=fig.dpi 像素」估算会系统性偏宽 ~29%。
  4. 三图标题的目标名（--dir 模式为完整路径）过长时中间省略（上限 48 字）。
  5. **网页版明细表窄屏优化**：表格加横向滚动容器（`.tbl-wrap` + `colgroup` 定列宽），新增 ≤960px / ≤640px 两档响应式媒体查询；名称列去掉 JS 中间省略改 CSS 单行尾部省略（`title` 悬浮看全名），修复中文长名 `A…B…` 双省略号叠加。

- **v1.0.2**（2026-10-09）—— 修 SkillHub 图裂：README 中的截图引用由本地相对路径 `assets/screenshot.png` 改为 GitHub raw 外链 `https://raw.githubusercontent.com/JackieZheng/xueren-disk-analyzer/main/assets/screenshot.png`（SkillHub 拒收 png 附件，需走外链）。功能无变更。

- **v1.0.1**（2026-10-09）—— 详情页 4 项 UX/口径修正：
  1. 占比口径：**「占磁盘%」→「占目标%」**（`title` 悬浮说明"占当前扫描目标 = 所选盘符 / 文件夹"），避免用户扫描单个文件夹时误以为分母是整盘容量；表格、树形、图例、说明块四处文案同步。
  2. 文件行操作列：🔍 扫描图标**不再隐藏，改为禁用态**（`opacity:.28`、`cursor:not-allowed`、`title="文件无法展开子项"`），保持所有行按钮位置一致、列表纵向对齐不再抖动。
  3. 属性标签双独立：内核新增 `is_hidden_attr()` 用 `GetFileAttributesW` 读 `FILE_ATTRIBUTE_HIDDEN`，与原有 `is_protected()`（🛡️系统白名单 + `FILE_ATTRIBUTE_SYSTEM`）**不再互斥**——同一条目可同时挂 🛡️ + 👁️；`pagefile.sys` / `$Recycle.Bin` 等 Windows 隐藏条目自动打 👁️ 标签，隐藏条目名加 `.nmname.dim` 灰色显示，方便一眼识别。
  4. 盘符下拉：原 `<select>` 原生弹层无法与页面深色主题协调，改为**自绘下拉层**（`.dd/.ddbtn/.ddlist/.dditem` + `mountDD(selId, opts, onChange)`），原生 `<select>` 保留为隐藏值源以维持兼容性；盘符与根目录选择器共用同一渲染逻辑，视觉统一。

- **v1.0.0**（2026-10-09）—— 首版发布：CLI + Web 双形态；Web 版含盘符下拉、目录选择、SSE 实时进度卡片、可停止扫描、点击目录打开资源管理器、断连自愈提示、路径中间省略号单行显示、长路径 hover 完整路径。

## 资源固化与自包含（强制）

1. **判断口径**：没有 `disk_analyzer.py` / `disk_analyzer_web.py` 就产不出报告 → 强相关，必须固化进 `scripts/`。
2. **放置位置**：两个脚本 → `scripts/`；依赖说明 → `references/`。
3. **取资源顺序**：skill 内 `scripts/` 优先；系统字体（微软雅黑 `C:\Windows\Fonts`）回退，不固化。
4. **不固化例外**：系统字体、凭据/API Key（绝不入 skill）、`__pycache__`、`_test_`/`_selftest_` 前缀临时文件。
5. **更新即备份**：每次修改本 skill 后，跑 `xueren-skill-backup` 同步到本机 WB Skill 备份目录下的同名子目录（排除 `__pycache__`）。
6. **交付前自检**：假设 `scripts/` 被删，本 skill 还能跑通吗？能（脚本零外部资源依赖，仅 matplotlib + squarify）。

## 注意事项

- **只读诊断（最高优先级）**：工具只统计体积，绝不删除/移动文件；清理建议须用户确认再执行。
- **依赖**：需 matplotlib + squarify；本机通用解释器 `D:/Python/Python312/python.exe` 已装（跨 skill 共用，不重复安装）。换环境先 `D:/Python/Python312/python.exe -m pip install matplotlib squarify`。**禁止 pip install --user 或往 managed venv 装**——会导致跨会话/跨 skill 各自装一份。
- **中文字体**：`setup_cjk_font()` 在模块加载时注册微软雅黑，CLI 与网页版通用；未注册会导致图表中文变方块（tofu）。
- **网页版不自动扫描**：加载只显示空状态，用户主动点「开始分析」才扫；避免一进来就长时间阻塞。
- **服务连接状态（断连不再静默失效）**：网页版依赖本地 HTTP 服务（`disk_analyzer_web.py`）。若服务被关闭，页面顶部连接指示变「● 未连接」并显示红色「🔴 服务未连接」横幅（含一键复制启动命令）；此时点「开始分析」会明确提示「先启动服务」，而非静默失效。交付/修复时务必先确认服务在监听：`curl --noproxy 127.0.0.1 http://127.0.0.1:8780/ping` 返回 `{"ok":true}`。
- **可停止**：`/cancel` 接口置取消标记，`scan_top`/`analyze_disk` 检查后中途返回部分结果。
- **路径中间省略号**：长路径（进度卡片、明细表、toast）用 JS `midEllipsis` 保留首尾、中间 `…`，CSS 原生只支持尾部省略号故用 JS 截断；明细表单元格 `title` 保留完整路径供悬停。
- **安全**：`/open` 仅允许打开本机已存在的固定盘路径，防止越权打开网络共享/系统目录。
- **squarify 坑**：treemap 面积必须先用 `normalize_sizes(sizes, dx, dy)` 归一化到总面积，否则大体积磁盘会让矩形宽达 1e11 像素致渲染崩溃（已在代码内修好，勿改回传原始字节）。
- **属性标签口径**：🛡️系统 = 系统白名单（`pagefile.sys`/`$Recycle.Bin`/`Windows.old` 等）或 `FILE_ATTRIBUTE_SYSTEM`；👁️隐藏 = `FILE_ATTRIBUTE_HIDDEN`。文件行两者独立、可共存；目录行仍按"系统优先"只挂一个标签以保持视觉简洁。隐藏条目名统一 `.nmname.dim` 灰色显示。
- **占比(%)**：占比分母永远是**用户当前扫描的目标**（盘符或文件夹），不是整盘容量。表头统一为「占比(%)」，文案不得写"占磁盘%"/"占目标%"。
- **图表长名防溢出（v1.0.3）**：三张图均做实测收敛——条形图 y 轴标签中间省略 + 实测宽度动态左边距；环形图图例省略到 16 字并左移防出界；树图标签按 `ax.transData` 实测矩形像素宽逐步收缩。勿改回固定截断或估算公式（实测过会溢出/丢扩展名）。
- **版本**：每次修改 SKILL.md，`version` +1 并重新备份。
