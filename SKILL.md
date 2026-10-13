---
id: xueren-disk-analyzer
name: 雪人老师·磁盘空间分析器
title: 雪人老师·磁盘空间分析器
description: 交互式磁盘空间分析工具（可选 C/D/E/F 或任意目录），命令行静态报告 + 网页交互版（实时进度、可停止、点击打开目录、占比口径准确、系统/隐藏属性标签共存、使用率分级预警、消耗速度预警）。纯 Python，依赖 matplotlib + squarify，零 CDN 离线自包含。当用户说"分析 C 盘""磁盘空间分析""哪个目录占空间""E 盘空间分析""做个磁盘分析工具"等意图时触发。
slug: xueren-disk-analyzer
displayName: 雪人老师·磁盘空间分析器
summary: 交互式磁盘空间分析（可选 C/D/E/F 或目录），图表展示占用，网页版带实时进度/可停止/点击打开目录。
version: 1.2.23
author: 雪人
license: MIT
display_name: xueren-disk-analyzer
trigger: ["分析 C 盘", "磁盘空间分析", "哪个目录占空间", "E 盘空间分析", "做个磁盘分析工具", "磁盘占用分析", "查看磁盘剩余空间"]
examples: "用户：做个磁盘分析工具，能选盘符出图表 → python scripts/disk_analyzer.py --disk E 出静态 HTML 报告；或 python scripts/disk_analyzer_ctl.py start 起本地服务在浏览器交互分析。"
platforms: [ima, WorkBuddy, QClaw]
github: https://github.com/JackieZheng/xueren-disk-analyzer
skillhub: https://skillhub.cn/skills/indiv-xueren/xueren-disk-analyzer
metadata:
  author: 雪人
  category: 工具
---

# 雪人老师·磁盘空间分析器

交互式磁盘空间分析工具。命令行出静态 HTML 报告；网页版起本地服务交互分析（实时进度 / 可停止 / 点击打开目录）。纯 Python，零 CDN。

## 快速开始

```bash
# 命令行：静态 HTML 报告
python scripts/disk_analyzer.py --disk E --depth 2 --top 15 --out disk_report.html

# 网页版：本地服务（端口 8780，无 cmd 黑窗）
python scripts/disk_analyzer_ctl.py start --no-browser
# → http://127.0.0.1:8780/
```

## 参数

- `--disk <盘符>`（可多值 `C E` / `all`）｜`--dir <路径>`（二选一）
- `--depth N`（默认 2）｜`--top N`（默认 15）｜`--workers N`（默认按 CPU）
- `--out <path>`（默认 `disk_report.html`）｜`--port / --host`（仅网页版，默认 8780 / 127.0.0.1）
- `disk_analyzer_ctl.py`：`status / check / start / stop / restart / spawn`

## 关键约定

- **只读**：仅统计体积，不删除/移动文件；清理建议须用户确认
- **占比分母** = 当前扫描目标（盘符或文件夹），不是整盘容量；表头统一「占比(%)」
- **网页版不自动扫描**：加载空状态，用户点「开始分析」才扫
- **依赖**：`matplotlib + squarify`，缺失则 `python -m pip install matplotlib squarify`
