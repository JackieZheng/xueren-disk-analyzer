# 依赖与安装说明（xueren-disk-analyzer）

## 运行时依赖

| 包 | 用途 | 是否必需 |
|----|------|----------|
| `matplotlib` | 绘制 treemap / 条形图 / 环形图（Agg 后端，离线无 CDN） | 必需 |
| `squarify` | treemap 矩形布局 | 必需 |
| `Pillow` | 无需（图表全用 matplotlib 生成） | — |

## 安装

本机 managed python（`~/.workbuddy/binaries/python/versions/3.13.12/python.exe`）已预装 matplotlib + squarify。

换环境 / 缺失时：

```bash
python -m pip install matplotlib squarify
```

## 字体处理（Windows）

脚本在**模块加载时**调用 `setup_cjk_font()`：

- 扫描 `C:\Windows\Fonts` 与用户字体目录，载入微软雅黑（`msyh.ttc` / `msyhbd.ttc`）。
- 注册进 matplotlib 的 `font.family`，使图表中文不乱码（否则退回 DejaVu Sans 出现 tofu 方块）。
- CLI（`disk_analyzer.py`）与网页版（`disk_analyzer_web.py` 经 `import disk_analyzer`）共用同一注册逻辑。

## 安全边界

- `/open`（网页版打开目录）仅允许打开本机已存在的**固定盘**路径，拒绝网络共享与系统目录越权访问。
- 工具整体只读，不写、不删、不移任何用户文件。
