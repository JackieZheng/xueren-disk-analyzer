# 雪人老师·磁盘空间分析器

交互式磁盘空间分析工具：给定磁盘（C/D/E/F 任选、多选或全盘）或任意目录，把「空间被谁吃掉」用图表讲清楚。纯 Python，零 CDN，离线可用。

![界面预览 · 虚拟数据](https://raw.githubusercontent.com/JackieZheng/xueren-disk-analyzer/main/assets/screenshot.png)

## 两种用法

**1. 命令行静态报告**：一次性输出自包含 HTML（三张可视化 + 可排序明细表）。

```bash
python scripts/disk_analyzer.py --disk E --depth 2 --top 15 --out disk_report_E.html
python scripts/disk_analyzer.py --disk C E --depth 1         # 多盘
python scripts/disk_analyzer.py --disk all --top 20          # 全盘
python scripts/disk_analyzer.py --dir "D:\Projects"          # 任意目录
```

**2. 网页交互版（推荐）**：本地 HTTP 服务，实时进度、可停止、点击打开目录。

```bash
python scripts/disk_analyzer_ctl.py start --no-browser   # 起服务（端口 8780，无 cmd 黑窗）
```

浏览器打开 `http://127.0.0.1:8780/`：

- **盘符下拉**（C/D/E/F）+ **📁 选择目录**（系统对话框选文件夹）
- **▶ 开始分析**（不自动扫）→ **实时进度卡片**（进度条 + 当前扫描目录 + 耗时/完成项）
- **⏹ 停止**：随时中断，返回已扫到的部分结果
- **📋 明细表**：点表头排序，点目录行直接打开所在位置
- **属性标签**：🛡️系统 / 👁️隐藏 / 🔥快增；路径超长中间省略号单行

## 依赖

Python 3 + `matplotlib` + `squarify`（缺失时 `python -m pip install matplotlib squarify`）

## 说明

- **只读工具**：只统计体积，**不删除/移动任何文件**；清理建议请确认后再执行
- 服务启动后页面才可用；服务停止后需重启再刷新页面
- 跨盘对比时，对每个盘各跑一次即可
