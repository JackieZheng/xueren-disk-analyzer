---
id: xueren-disk-analyzer
name: 雪人老师·磁盘空间分析器
title: 雪人老师·磁盘空间分析器
description: 交互式磁盘空间分析工具（可选 C/D/E/F 或任意目录），命令行静态报告 + 网页交互版（盘符下拉、目录选择、实时进度卡片、可停止、点击目录打开所在位置、长路径中间省略号、明细表占比口径准确、🛡️系统/👁️隐藏双属性标签可共存、盘符使用率分级配色预警、近期消耗速度预警）。纯 Python，依赖 matplotlib + squarify，零 CDN 离线自包含。当用户说"分析 C 盘""磁盘空间分析""哪个目录占空间""E 盘空间分析""做个磁盘分析工具"等意图时触发。
slug: xueren-disk-analyzer
displayName: 雪人老师·磁盘空间分析器
summary: 交互式磁盘空间分析（可选 C/D/E/F 或目录），图表展示占用，网页版带实时进度/可停止/点击打开目录。
description_zh: 交互式磁盘空间分析工具，命令行静态报告 + 网页交互版（实时进度/可停止/点击打开目录），纯 Python 零 CDN。
description_en: Interactive disk space analyzer (choose C/D/E/F or a folder), visualize usage with charts; web UI with live progress card, stoppable scan, click-to-open folder.
version: 1.2.21
author: 雪人
license: MIT
allowed-tools: ""
display_name: xueren-disk-analyzer
display_name_zh: 雪人老师·磁盘空间分析器
trigger: ["分析 C 盘", "磁盘空间分析", "哪个目录占空间", "E 盘空间分析", "做个磁盘分析工具", "磁盘占用分析", "查看磁盘剩余空间"]
examples: "用户：做个磁盘分析工具，能选盘符出图表 → 跑 scripts/disk_analyzer.py --disk E 出静态 HTML 报告，或 scripts/disk_analyzer_ctl.py start 起本地服务在浏览器交互分析。"
platforms: [ima, WorkBuddy, QClaw]
github: https://github.com/JackieZheng/xueren-disk-analyzer
skillhub: https://skillhub.cn/skills/indiv-xueren/xueren-disk-analyzer
metadata:
  author: 雪人
  category: 工具
---

# 雪人老师·磁盘空间分析器

交互式磁盘空间分析工具，回答「我的磁盘空间被谁吃掉了」。**两种用法**：命令行出静态 HTML 报告；网页版起本地 HTTP 服务交互分析（盘符下拉、目录选择、实时进度、可停止、点击打开目录）。纯 Python，依赖 `matplotlib + squarify`，图表 base64 内嵌，零 CDN 离线自包含。

## 快速开始

```bash
# 命令行（静态 HTML 报告）
python scripts/disk_analyzer.py --disk E --depth 2 --top 15 --out disk_report.html

# 网页版（本地服务，端口 8780）
python scripts/disk_analyzer_ctl.py start --no-browser
# → 打开 http://127.0.0.1:8780/
```

## 参数

`disk_analyzer.py`：

| 参数 | 必填 | 说明 |
|------|------|------|
| `--disk` | 二选一 | 盘符，可多值如 `E` / `C E` / `all` |
| `--dir` | 二选一 | 任意目录的绝对路径 |
| `--depth` | 否 | 扫描深度（1=顶层，2=顶层+下一级，默认 2） |
| `--top` | 否 | Top N 目录（默认 15） |
| `--workers` | 否 | 并行进程数（默认按 CPU 自适应） |
| `--out` | 否 | 输出 HTML 路径（默认 `disk_report.html`） |

`disk_analyzer_web.py`：`--port`（默认 8780）/ `--host`（默认 127.0.0.1）。

`disk_analyzer_ctl.py`：`status / check / start / stop / restart / spawn`（WMI 会话外常驻，start 可加 `--no-browser`）。

## 工作方式

1. 确认用户要分析的盘符/目录（跨盘对比时逐个跑 `--disk`）
2. 选形态：一次性报告 → 命令行；交互分析 → 网页版
3. 跑扫描 → 交付 HTML / 打开网页地址
4. 帮用户指出 Top N 占用目录，定位元凶（缓存、视频等），给清理建议（**只读诊断，不擅自删改**）

## 依赖与环境

- 依赖：`matplotlib + squarify`，缺失则 `python -m pip install matplotlib squarify`
- 装到统一解释器，**禁止 `pip install --user` 或往 managed venv 装**（会导致跨 skill 环境割裂）
- 中文字体：`setup_cjk_font()` 在模块加载时自动注册微软雅黑，未注册会导致图表中文变方块

## 关键约定

- **只读**：工具只统计体积，绝不删除/移动文件；清理建议须用户确认
- **只读探测**：`/open` 仅允许打开本机已存在的固定盘路径
- **可停止**：`/cancel` 置取消标记，扫描中途返回部分结果
- **占比分母**：永远是「用户当前扫描的目标」（盘符或文件夹），不是整盘容量；表头统一为「占比(%)」
- **网页版不自动扫描**：加载只显示空状态，用户主动点「开始分析」才扫
- **服务健康检查**：`curl --noproxy 127.0.0.1 http://127.0.0.1:8780/ping` 返回 `{"ok":true}`；页面顶部有「● 未连接」红色横幅提示断连
- **依赖核验（交付前）**：三张图均显示、明细表排序正确、容量卡片数值合理、长路径为中间省略号单行

## 资源目录

- `scripts/disk_analyzer.py`：扫描内核 + 静态 HTML 报告（treemap/bar/donut + 走势曲线 + 明细表）
- `scripts/disk_analyzer_web.py`：本地 HTTP 服务 + 深色实时进度面板 SPA（SSE 推送进度，`/cancel` 中断，`/open` 打开目录）
- `scripts/disk_analyzer_ctl.py`：WMI 会话外常驻启动器（无 cmd 黑窗）
- `references/deps.md`：依赖与安装说明

## 常见问题

- **服务没启动**：先跑 `python scripts/disk_analyzer_ctl.py start --no-browser`，`curl /ping` 验活
- **端口占用**：`netstat -ano | grep :8780` 找 PID → `Stop-Process -Id <PID> -Force` → 重新 start
- **图表中文方块**：脚本启动时未注册字体，确认 `setup_cjk_font()` 未被跳过
- **squarify 崩溃**：treemap 面积必须用 `normalize_sizes(sizes, dx, dy)` 归一化，勿直接传原始字节

## 版本演进

各版本详细变更记录见 `docs/DEVLOG.md`（当前 v1.2.21，覆盖 v1.0.0 起共 26 次迭代）。每次修改 SKILL.md 后 `version` +1 并重新备份。
