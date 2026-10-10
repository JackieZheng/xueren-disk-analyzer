---
id: xueren-disk-analyzer
name: 雪人老师·磁盘空间分析器
title: 雪人老师·磁盘空间分析器
description: 给定磁盘（C/D/E/F 任选、多选或全盘）或任意目录，交互式分析空间占用并以图表展示。命令行静态报告 + 网页交互版（深色「任务实时进度面板」风：盘符下拉、目录选择、实时扫描进度卡片、可停止、点击目录打开所在位置、路径太长中间省略号单行显示；明细表「占目标%」占比口径准确、🛡️系统/👁️隐藏双属性标签可共存且隐藏项名灰色显示、文件行操作图标保留但灰置、盘符下拉自绘弹层与整体风格统一）。纯 Python，依赖 matplotlib + squarify（已装），零 CDN、离线自包含。当用户说"分析 C 盘""磁盘空间分析""哪个目录占空间""E 盘空间分析""做个磁盘分析工具"等意图时触发。
slug: xueren-disk-analyzer
displayName: 雪人老师·磁盘空间分析器
summary: 交互式磁盘空间分析（可选 C/D/E/F 或目录），图表展示占用，网页版带实时进度/可停止/点击打开目录。
description_zh: 给定磁盘（C/D/E/F 任选、多选或全盘）或任意目录，交互式分析空间占用并以图表展示。命令行静态报告 + 网页交互版（深色「任务实时进度面板」风），纯 Python，零 CDN 离线自包含。
description_en: Interactive disk space analyzer (choose C/D/E/F or a folder), visualize usage with charts; web UI with live progress card, stoppable scan, click-to-open folder.
version: 1.0.5
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

**硬指标**：纯 Python；依赖 matplotlib + squarify（本机 managed python 已装）；图表 base64 内嵌、**零 CDN、离线可用**；Windows 下自动注册微软雅黑中文字体，图表中文不方块。

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
- 依赖核验：`python -c "import matplotlib, squarify"`；缺失则 `pip install matplotlib squarify`。
- **只读原则**：本工具只统计体积，**不删除/移动任何文件**；清理建议必须等用户确认再执行。

### Phase 2：执行扫描
- 命令行：`python scripts/disk_analyzer.py --disk E --depth 2 --top 15 --out disk_report_E.html`
  - `--depth 1` 仅顶层、`2` 顶层+下一级（默认 2）；`--top N` 条形图/明细表取前 N；
  - `--workers` 并行度（默认按 CPU 自适应）；`--dir <路径>` 替代 `--disk` 分析单目录。
- 网页版：`python scripts/disk_analyzer_web.py --port 8780` → 浏览器开 `http://127.0.0.1:8780/`
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
- **依赖**：需 matplotlib + squarify；本机 managed python（`~/.workbuddy/binaries/python/versions/3.13.12/python.exe`）已装。换环境先 `pip install matplotlib squarify`。
- **中文字体**：`setup_cjk_font()` 在模块加载时注册微软雅黑，CLI 与网页版通用；未注册会导致图表中文变方块（tofu）。
- **网页版不自动扫描**：加载只显示空状态，用户主动点「开始分析」才扫；避免一进来就长时间阻塞。
- **服务连接状态（断连不再静默失效）**：网页版依赖本地 HTTP 服务（`disk_analyzer_web.py`）。若服务被关闭，页面顶部连接指示变「● 未连接」并显示红色「🔴 服务未连接」横幅（含一键复制启动命令）；此时点「开始分析」会明确提示「先启动服务」，而非静默失效。交付/修复时务必先确认服务在监听：`curl --noproxy 127.0.0.1 http://127.0.0.1:8780/ping` 返回 `{"ok":true}`。
- **可停止**：`/cancel` 接口置取消标记，`scan_top`/`analyze_disk` 检查后中途返回部分结果。
- **路径中间省略号**：长路径（进度卡片、明细表、toast）用 JS `midEllipsis` 保留首尾、中间 `…`，CSS 原生只支持尾部省略号故用 JS 截断；明细表单元格 `title` 保留完整路径供悬停。
- **安全**：`/open` 仅允许打开本机已存在的固定盘路径，防止越权打开网络共享/系统目录。
- **squarify 坑**：treemap 面积必须先用 `normalize_sizes(sizes, dx, dy)` 归一化到总面积，否则大体积磁盘会让矩形宽达 1e11 像素致渲染崩溃（已在代码内修好，勿改回传原始字节）。
- **属性标签口径**：🛡️系统 = 系统白名单（`pagefile.sys`/`$Recycle.Bin`/`Windows.old` 等）或 `FILE_ATTRIBUTE_SYSTEM`；👁️隐藏 = `FILE_ATTRIBUTE_HIDDEN`。文件行两者独立、可共存；目录行仍按"系统优先"只挂一个标签以保持视觉简洁。隐藏条目名统一 `.nmname.dim` 灰色显示。
- **占目标%**：占比分母永远是**用户当前扫描的目标**（盘符或文件夹），不是整盘容量。文案不得写"占磁盘%"。
- **图表长名防溢出（v1.0.3）**：三张图均做实测收敛——条形图 y 轴标签中间省略 + 实测宽度动态左边距；环形图图例省略到 16 字并左移防出界；树图标签按 `ax.transData` 实测矩形像素宽逐步收缩。勿改回固定截断或估算公式（实测过会溢出/丢扩展名）。
- **版本**：每次修改 SKILL.md，`version` +1 并重新备份。
