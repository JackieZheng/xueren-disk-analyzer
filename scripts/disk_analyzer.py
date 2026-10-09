#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
disk_analyzer.py —— 磁盘空间分析工具（可多选磁盘 C/D/E/F）
========================================================
功能：
  1. 选择磁盘（--disk C D E F / all），并行扫描各顶层目录体积。
  2. 用 matplotlib 生成三类图表（嵌套矩形树图 treemap / 横向条形图 / 环形图），
     全部 base64 内嵌进一份自包含 HTML 报告，离线可用、无需 CDN。
  3. 报告含容量概览卡片 + 可排序明细表。

用法：
  python disk_analyzer.py --disk E                 # 分析 E 盘（depth=2）
  python disk_analyzer.py --disk C E --depth 1     # 分析 C、E 两盘，仅顶层
  python disk_analyzer.py --disk all --top 20      # 分析全部固定盘，Top20
  python disk_analyzer.py --disk E --out my.html   # 指定输出文件名

仅依赖：Python 标准库 + matplotlib + squarify（均已安装）。
"""

import argparse
import base64
import ctypes
import io
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
from matplotlib import font_manager as fm
import squarify

# ---------------------------------------------------------------------------
# 通用工具
# ---------------------------------------------------------------------------

def human(n):
    """字节 -> 人类可读字符串。"""
    if n is None:
        return "—"
    n = float(n)
    for unit in ["B", "KB", "MB", "GB", "TB", "PB"]:
        if n < 1024.0:
            return f"{n:.1f} {unit}"
        n /= 1024.0
    return f"{n:.1f} PB"


def setup_cjk_font():
    """在 Windows 上注册中文字体，避免图表中文变方块。"""
    font_dir = r"C:\Windows\Fonts"
    if not os.path.isdir(font_dir):
        return None
    prefs = ["msyh.ttc", "msyhbd.ttc", "simhei.ttf", "simsun.ttc", "yahei"]
    chosen = None
    try:
        files = os.listdir(font_dir)
    except OSError:
        files = []
    for f in files:
        fl = f.lower()
        if fl in prefs:
            chosen = os.path.join(font_dir, f)
            break
    if chosen is None:
        for f in files:
            fl = f.lower()
            if any(p in fl for p in ["msyh", "simhei", "simsun", "yahei"]):
                chosen = os.path.join(font_dir, f)
                break
    if chosen:
        try:
            fm.fontManager.addfont(chosen)
            name = fm.FontProperties(fname=chosen).get_name()
            plt.rcParams["font.sans-serif"] = [name]
            plt.rcParams["axes.unicode_minus"] = False
            return name
        except Exception:
            pass
    return None


def disk_capacity(path):
    """返回 (total_bytes, free_bytes)，失败返回 (None, None)。"""
    avail = ctypes.c_ulonglong(0)
    total = ctypes.c_ulonglong(0)
    free = ctypes.c_ulonglong(0)
    try:
        ok = ctypes.windll.kernel32.GetDiskFreeSpaceExW(
            ctypes.c_wchar_p(path),
            ctypes.byref(avail),
            ctypes.byref(total),
            ctypes.byref(free),
        )
        if ok:
            return total.value, free.value
    except Exception:
        pass
    return None, None


def list_fixed_drives():
    """返回本机所有盘符列表，如 ['C:\\', 'D:\\', ...]。"""
    try:
        buf = ctypes.create_unicode_buffer(256)
        n = ctypes.windll.kernel32.GetLogicalDriveStringsW(256, buf)
        raw = buf[:n].split("\x00")[:-1]
        return raw
    except Exception:
        return []


# ---------------------------------------------------------------------------
# 扫描（多进程并行累加各顶层目录体积）
# ---------------------------------------------------------------------------

def scan_top(top, progress=None):
    """
    累加单个目录的总体积，并按下一级（immediate children）分组。
    返回 (total, children_dict, files_size)
      - total: 该目录子树总字节
      - children_dict: {下级子目录名: 子树字节}
      - files_size: 直接位于该目录下的文件总字节
    用 os.scandir + 缓存 entry.stat() 提升效率；跳过符号链接与无权限目录。
    progress: 可选共享字典（线程安全），用于实时上报：
      progress['current'] = 当前正在遍历的目录路径
      progress['cancel']  = True 时中途停止（返回已累加的部分结果）
    """
    total = 0
    children = {}
    files_size = 0
    stack = [top]
    while stack:
        if progress and progress.get("cancel"):
            break
        cur = stack.pop()
        if progress is not None:
            progress["current"] = cur
        try:
            with os.scandir(cur) as it:
                for entry in it:
                    if progress and progress.get("cancel"):
                        break
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(entry.path)
                        else:
                            sz = entry.stat(follow_symlinks=False).st_size
                            total += sz
                            if cur == top:
                                files_size += sz
                            else:
                                key = os.path.relpath(cur, top).split(os.sep)[0]
                                children[key] = children.get(key, 0) + sz
                    except OSError:
                        continue
        except (PermissionError, OSError):
            continue
    return total, children, files_size


def analyze_disk(drive, depth=2, top=15, workers=0, progress=None):
    """
    分析单个磁盘。返回 dict：
      {
        'drive', 'depth', 'scan_time', 'total_bytes'(容量), 'free_bytes'(容量),
        'scanned_bytes'(扫描合计), 'nodes': [顶层节点...],
      }
    节点结构：{'name','label','size','children':[...],'is_file':bool}
    progress: 可选共享字典，实时上报 phase/current/done/total/cancel。
    """
    root = os.path.join(drive, os.sep)
    t0 = time.time()
    total_cap, free_cap = disk_capacity(root)

    if progress is not None:
        progress["phase"] = f"列举 {drive} 顶层目录…"

    # 列出顶层条目
    top_dirs = []
    root_files_size = 0
    try:
        with os.scandir(root) as it:
            for entry in it:
                try:
                    if entry.is_dir(follow_symlinks=False):
                        top_dirs.append(entry.name)
                    else:
                        root_files_size += entry.stat(follow_symlinks=False).st_size
                except OSError:
                    continue
    except (PermissionError, OSError) as e:
        print(f"  [!] 无法列举 {root}: {e}", file=sys.stderr)

    if progress is not None:
        progress["phase"] = f"并行扫描 {len(top_dirs)} 个顶层目录"
        progress["total"] = len(top_dirs)
        progress["done"] = 0

    print(f"  [+] {drive} 顶层目录 {len(top_dirs)} 个，开始并行扫描…")
    nodes = []
    if workers <= 0:
        workers = min(max(len(top_dirs), 1), (os.cpu_count() or 4) * 2)
    # 目录遍历是 IO 密集（stat 释放 GIL），用线程池即可并行且便于共享进度/取消
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(scan_top, os.path.join(root, d), progress): d for d in top_dirs}
        done = 0
        for fut in futs:
            d = futs[fut]
            if progress is not None:
                progress["phase"] = f"正在处理 {d}（已完成 {done}/{len(futs)}）"
            try:
                dtotal, dchildren, dfiles = fut.result()
            except Exception as e:
                print(f"  [!] 扫描 {d} 失败: {e}", file=sys.stderr)
                dtotal, dchildren, dfiles = 0, {}, 0
            done += 1
            if progress is not None:
                progress["done"] = done
            children_nodes = []
            if depth >= 2:
                for sub, sz in dchildren.items():
                    children_nodes.append({
                        "name": sub, "label": sub, "size": sz,
                        "children": [], "is_file": False,
                        "path": os.path.join(root, d, sub),
                    })
                if dfiles > 0:
                    children_nodes.append({
                        "name": "（该层文件）", "label": "（该层文件）",
                        "size": dfiles, "children": [], "is_file": True,
                        "path": None,
                    })
                children_nodes.sort(key=lambda x: x["size"], reverse=True)
            nodes.append({
                "name": d, "label": d, "size": dtotal,
                "children": children_nodes, "is_file": False,
                "path": os.path.join(root, d),
            })

    if root_files_size > 0:
        nodes.append({
            "name": "（根目录文件）", "label": "（根目录文件）",
            "size": root_files_size, "children": [], "is_file": True,
            "path": None,
        })

    nodes.sort(key=lambda x: x["size"], reverse=True)
    scanned = sum(n["size"] for n in nodes)

    return {
        "drive": drive,
        "depth": depth,
        "scan_time": round(time.time() - t0, 1),
        "total_bytes": total_cap,
        "free_bytes": free_cap,
        "scanned_bytes": scanned,
        "nodes": nodes,
        "top": top,
    }


# ---------------------------------------------------------------------------
# 图表
# ---------------------------------------------------------------------------

PALETTE = [
    "#2e7d32", "#43a047", "#66bb6a", "#1b5e20", "#81c784",
    "#a5d6a7", "#388e3c", "#558b2f", "#7cb342", "#9ccc65",
    "#2e7d32", "#43a047", "#66bb6a", "#1b5e20", "#81c784",
]
ACCENT = "#ef6c00"   # 金橙强调色（最大项）
OTHER = "#bdbdbd"    # “其他”灰


def _lighten(hexc, amt=0.3):
    """把颜色按比例向白色混合，amt∈[0,1]。"""
    hexc = hexc.lstrip("#")
    r, g, b = (int(hexc[i:i + 2], 16) for i in (0, 2, 4))
    r = int(r + (255 - r) * amt)
    g = int(g + (255 - g) * amt)
    b = int(b + (255 - b) * amt)
    return f"#{r:02x}{g:02x}{b:02x}"


def _fmt_png(fig):
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=110, bbox_inches="tight",
                facecolor="white")
    plt.close(fig)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def make_treemap(data, max_depth):
    """嵌套矩形树图（treemap）。depth=1 只画顶层；depth=2 顶层+下级。"""
    fig, ax = plt.subplots(figsize=(13, 8))
    ax.set_axis_off()
    W, H = 13, 8
    total_area = W * H

    # 顶层节点（cap 到 30 个，其余并入“其他”）
    nodes = data["nodes"]
    if len(nodes) > 30:
        kept = nodes[:30]
        other_sz = sum(n["size"] for n in nodes[30:])
        nodes = kept + [{"name": "(其他)", "label": "(其他)", "size": other_sz,
                        "children": [], "is_file": True}]

    vals = [max(n["size"], 1) for n in nodes]
    vals = squarify.normalize_sizes(vals, W, H)
    rects = squarify.squarify(vals, 0, 0, W, H)

    def draw_leaf(node, x, y, w, h, color):
        ax.add_patch(Rectangle((x, y), w, h, facecolor=color,
                               edgecolor="white", linewidth=1.2))
        frac = (w * h) / total_area
        if frac > 0.006 and h > 0.25:
            fs = max(7, min(15, int((w * h) ** 0.32)))
            label = node["label"]
            if len(label) > 22:
                label = label[:21] + "…"
            ax.text(x + w / 2, y + h / 2, label, color="white",
                    ha="center", va="center", fontsize=fs, fontweight="bold")

    def rec(node, x, y, w, h, depth, base):
        ch = node.get("children") or []
        if not ch or depth + 1 >= max_depth:
            draw_leaf(node, x, y, w, h, base)
            return
        # 子节点 cap 到 20
        if len(ch) > 20:
            ch = ch[:20] + [{"name": "(其他)", "label": "(其他)",
                             "size": sum(c["size"] for c in ch[20:]),
                             "children": [], "is_file": True}]
        cvals = [max(c["size"], 1) for c in ch]
        cvals = squarify.normalize_sizes(cvals, w, h)
        crects = squarify.squarify(cvals, x, y, w, h)
        for rect, child in zip(crects, ch):
            child_color = _lighten(base, 0.28) if child.get("children") else base
            rec(child, rect["x"], rect["y"], rect["dx"], rect["dy"],
                depth + 1, child_color)

    for rect, node, i in zip(rects, nodes, range(len(nodes))):
        base = PALETTE[i % len(PALETTE)]
        if i == 0:
            base = ACCENT  # 最大项用金橙强调
        rec(node, rect["x"], rect["y"], rect["dx"], rect["dy"], 0, base)

    ax.set_xlim(0, W)
    ax.set_ylim(0, H)
    ax.invert_yaxis()
    ax.set_title(f"{data['drive']} 磁盘空间分布（矩形面积=体积，depth={data['depth']}）",
                 fontsize=14, fontweight="bold", color="#1b5e20", pad=10)
    return _fmt_png(fig)


def make_bar(data):
    """横向条形图：Top N 目录。"""
    nodes = data["nodes"][:data["top"]]
    labels = [n["label"] for n in nodes][::-1]
    sizes = [n["size"] / 1024 ** 3 for n in nodes][::-1]  # GB
    fig, ax = plt.subplots(figsize=(10, max(4, 0.42 * len(labels) + 1.5)))
    colors = [ACCENT] + [PALETTE[i % len(PALETTE)] for i in range(len(sizes) - 1)]
    bars = ax.barh(labels, sizes, color=colors, edgecolor="white")
    ax.set_xlabel("体积 (GB)", fontsize=11)
    ax.set_title(f"{data['drive']} 体积 Top {len(labels)} 目录",
                 fontsize=13, fontweight="bold", color="#1b5e20")
    ax.tick_params(axis="y", labelsize=10)
    mx = max(sizes) if sizes else 1
    for b, v in zip(bars, sizes):
        ax.text(b.get_width() + mx * 0.01, b.get_y() + b.get_height() / 2,
                f"{v:.1f} GB", va="center", fontsize=9, color="#333")
    ax.set_xlim(0, mx * 1.12)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    return _fmt_png(fig)


def make_donut(data):
    """环形图：Top N + 其他。"""
    nodes = data["nodes"]
    n = data["top"]
    top_nodes = nodes[:n]
    other_sz = sum(x["size"] for x in nodes[n:])
    sizes = [x["size"] for x in top_nodes]
    labels = [x["label"] for x in top_nodes]
    if other_sz > 0:
        sizes.append(other_sz)
        labels.append("其他")
    # 配色：最大项金橙，其余绿色梯度，其他灰
    colors = [ACCENT]
    for i in range(1, len(sizes) - 1):
        colors.append(PALETTE[i % len(PALETTE)])
    if other_sz > 0:
        colors.append(OTHER)
    fig, ax = plt.subplots(figsize=(9, 9))
    wedges, texts, autotexts = ax.pie(
        sizes, labels=None, autopct=lambda p: f"{p:.1f}%",
        pctdistance=0.78, startangle=90,
        wedgeprops=dict(width=0.42, edgecolor="white", linewidth=1.5),
        colors=colors,
    )
    for t in autotexts:
        t.set_fontsize(9)
        t.set_color("#222")
    ax.legend(wedges, labels, loc="center left", bbox_to_anchor=(1.0, 0.5),
              fontsize=9, frameon=False)
    ax.set_title(f"{data['drive']} 体积占比（Top {min(n, len(nodes))}）",
                 fontsize=13, fontweight="bold", color="#1b5e20")
    return _fmt_png(fig)


# ---------------------------------------------------------------------------
# HTML 报告
# ---------------------------------------------------------------------------

def build_html(data, chart_treemap, chart_bar, chart_donut, font_name):
    drive = data["drive"]
    total = data["total_bytes"]
    free = data["free_bytes"]
    scanned = data["scanned_bytes"]
    used = (total - free) if (total and free is not None) else None
    pct = (used / total * 100) if (total and used is not None) else None

    # 概览卡片
    cap_card = ""
    if total:
        cap_card = f"""
        <div class="card"><div class="k">总容量</div><div class="v">{human(total)}</div></div>
        <div class="card"><div class="k">已用</div><div class="v">{human(used)}</div></div>
        <div class="card"><div class="k">剩余</div><div class="v">{human(free)}</div></div>
        <div class="card"><div class="k">使用率</div><div class="v" style="color:#ef6c00">{pct:.1f}%</div></div>
        """
    else:
        cap_card = f'<div class="card"><div class="k">扫描合计</div><div class="v">{human(scanned)}</div></div>'

    # 明细表行
    rows = []
    for i, n in enumerate(data["nodes"], 1):
        share = (n["size"] / total * 100) if total else (n["size"] / scanned * 100 if scanned else 0)
        rows.append(
            f"<tr><td class='num'>{i}</td><td class='name'>{_esc(n['label'])}"
            f"{' <span class=tag>文件</span>' if n['is_file'] else ''}</td>"
            f"<td class='num'>{human(n['size'])}</td>"
            f"<td class='num'>{share:.1f}%</td>"
            f"<td class='num'>{len(n['children'])}</td></tr>"
        )
    rows_html = "\n".join(rows)

    html = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>磁盘分析 · {drive}</title>
<style>
  * {{ box-sizing: border-box; }}
  body {{ font-family: 'Microsoft YaHei','PingFang SC','Segoe UI',sans-serif;
         margin:0; background:#f3f8f4; color:#1f2d27; }}
  header {{ background:linear-gradient(135deg,#1b5e20,#43a047); color:#fff;
           padding:22px 28px; }}
  header h1 {{ margin:0; font-size:22px; }}
  header p {{ margin:6px 0 0; opacity:.9; font-size:13px; }}
  .wrap {{ max-width:1180px; margin:0 auto; padding:20px; }}
  .cards {{ display:flex; flex-wrap:wrap; gap:14px; margin:18px 0; }}
  .card {{ background:#fff; border-radius:12px; padding:14px 18px; min-width:140px;
          box-shadow:0 2px 8px rgba(0,0,0,.06); flex:1; }}
  .card .k {{ font-size:12px; color:#6b7c74; }}
  .card .v {{ font-size:20px; font-weight:700; margin-top:4px; color:#1b5e20; }}
  .chart {{ background:#fff; border-radius:12px; padding:16px; margin:16px 0;
           box-shadow:0 2px 8px rgba(0,0,0,.06); }}
  .chart h2 {{ font-size:16px; color:#1b5e20; margin:0 0 10px; }}
  .chart img {{ width:100%; height:auto; display:block; border-radius:8px; }}
  table {{ width:100%; border-collapse:collapse; background:#fff; border-radius:12px;
          overflow:hidden; box-shadow:0 2px 8px rgba(0,0,0,.06); }}
  th,td {{ padding:10px 12px; text-align:left; border-bottom:1px solid #eef3f0; font-size:13px; }}
  th {{ background:#e8f3ec; color:#1b5e20; cursor:pointer; user-select:none; }}
  th:hover {{ background:#d7ecdf; }}
  td.num {{ text-align:right; font-variant-numeric:tabular-nums; }}
  td.name {{ max-width:420px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }}
  .tag {{ background:#ef6c00; color:#fff; font-size:11px; padding:1px 6px; border-radius:6px; }}
  footer {{ text-align:center; color:#8a9a92; font-size:12px; padding:20px; }}
  .note {{ background:#fff8e1; border-left:4px solid #ef6c00; padding:10px 14px;
          border-radius:6px; font-size:13px; margin:10px 0; }}
</style></head>
<body>
<header><h1>📊 磁盘空间分析报告 · {drive}</h1>
<p>扫描耗时 {data['scan_time']}s · 采集层级 depth={data['depth']} · 生成时间 {_now()}
{'· 中文字体: '+font_name if font_name else ''}</p></header>
<div class="wrap">
  <div class="cards">{cap_card}</div>
  {'' if total else ''}
  <div class="note">说明：图表与表格体积来自实际文件扫描（已排除无权限/符号链接目录）。
  系统“已用”含回收站、页面文件等不可枚举项，故“扫描合计 {human(scanned)}”通常略小于系统“已用”。</div>

  <div class="chart"><h2>① 矩形树图（Treemap）—— 面积越大占用越多</h2>
    <img src="data:image/png;base64,{chart_treemap}"></div>

  <div class="chart"><h2>② 横向条形图 —— Top {data['top']} 目录</h2>
    <img src="data:image/png;base64,{chart_bar}"></div>

  <div class="chart"><h2>③ 环形图 —— 体积占比</h2>
    <img src="data:image/png;base64,{chart_donut}"></div>

  <h2 style="color:#1b5e20;margin-top:24px">📋 目录明细（点击表头排序）</h2>
  <table id="t"><thead><tr>
    <th data-k="idx">#</th><th data-k="name">目录</th>
    <th data-k="size">大小 ▼</th><th data-k="pct">占磁盘%</th><th data-k="cnt">子项</th>
  </tr></thead><tbody>{rows_html}</tbody></table>
</div>
<footer>disk_analyzer · 离线自包含报告 · 由 WorkBuddy 生成</footer>
<script>
var t=document.getElementById('t');var tb=t.tBodies[0];var asc={{}};
t.querySelectorAll('th').forEach(function(th){{
  th.onclick=function(){{
    var k=th.dataset.k;var a=asc[k]=!asc[k];
    var r=[].slice.call(tb.rows);
    r.sort(function(x,y){{
      var vx,vy;
      if(k=='idx'){{vx=+x.cells[0].textContent;vy=+y.cells[0].textContent;}}
      else if(k=='name'){{vx=x.cells[1].textContent;vy=y.cells[1].textContent;return a?vx.localeCompare(vy):vy.localeCompare(vx);}}
      else if(k=='size'){{vx=x.cells[2].textContent;vy=y.cells[2].textContent;}}
      else if(k=='pct'){{vx=parseFloat(x.cells[3].textContent);vy=parseFloat(y.cells[3].textContent);}}
      else if(k=='cnt'){{vx=+x.cells[4].textContent;vy=+y.cells[4].textContent;}}
      if(k!='name'){{return a?vx-vy:vy-vx;}}
    }});
    r.forEach(function(row){{tb.appendChild(row);}});
  }};
}});
</script>
</body></html>"""
    return html


def _esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;"))


def _now():
    return time.strftime("%Y-%m-%d %H:%M:%S")


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def parse_drives(arg):
    if arg.lower() == "all":
        return [d for d in list_fixed_drives()]
    out = []
    for part in arg.replace(",", " ").split():
        part = part.strip().upper()
        if not part:
            continue
        if not part.endswith(":"):
            part += ":"
        if not part.endswith("\\"):
            part += "\\"
        out.append(part)
    return out


# 模块加载即注册中文字体（供 CLI 与 import 复用，避免图表中文变方块）
setup_cjk_font()


def main():
    from multiprocessing import freeze_support
    freeze_support()

    ap = argparse.ArgumentParser(description="磁盘空间分析工具（可多选 C/D/E/F）")
    ap.add_argument("--disk", default="all",
                    help="磁盘盘符，如 'E' 或 'C E' 或 'all'（默认 all）")
    ap.add_argument("--depth", type=int, default=2, choices=[1, 2],
                    help="采集层级：1=仅顶层，2=顶层+下级（默认 2）")
    ap.add_argument("--top", type=int, default=15, help="Top N 目录（默认 15）")
    ap.add_argument("--workers", type=int, default=0, help="扫描并行进程数（默认自动）")
    ap.add_argument("--out", default=None, help="输出 HTML 文件名（默认 disk_report_<盘>.html）")
    ap.add_argument("--dir", default=None, help="分析单个目录而非整盘（覆盖 --disk）")
    args = ap.parse_args()

    font_name = setup_cjk_font()

    reports = []
    if args.dir:
        # 单目录模式：构造一个伪“磁盘”数据
        print(f"[*] 分析目录：{args.dir}")
        t0 = time.time()
        total, children, files_size = scan_top(args.dir)
        nodes = []
        for sub, sz in children.items():
            nodes.append({"name": sub, "label": sub, "size": sz,
                          "children": [], "is_file": False,
                          "path": os.path.join(args.dir, sub)})
        if files_size > 0:
            nodes.append({"name": "（该层文件）", "label": "（该层文件）",
                          "size": files_size, "children": [], "is_file": True,
                          "path": None})
        nodes.sort(key=lambda x: x["size"], reverse=True)
        data = {
            "drive": args.dir, "depth": 1, "scan_time": round(time.time() - t0, 1),
            "total_bytes": None, "free_bytes": None,
            "scanned_bytes": total, "nodes": nodes, "top": args.top,
        }
        ct = make_treemap(data, 1)
        cb = make_bar(data)
        cd = make_donut(data)
        out = args.out or ("disk_report_dir.html")
        with open(out, "w", encoding="utf-8") as f:
            f.write(build_html(data, ct, cb, cd, font_name))
        print(f"[✓] 已生成：{os.path.abspath(out)}")
        reports.append(os.path.abspath(out))
    else:
        drives = parse_drives(args.disk)
        if not drives:
            print("[!] 未找到可用磁盘，退出。")
            return
        print(f"[*] 待分析磁盘：{', '.join(d.split(':')[0] for d in drives)}")
        for d in drives:
            print(f"\n===== 分析 {d} =====")
            data = analyze_disk(d, depth=args.depth, top=args.top,
                                workers=args.workers)
            print(f"  [✓] 扫描合计 {human(data['scanned_bytes'])}，"
                  f"耗时 {data['scan_time']}s，顶层 {len(data['nodes'])} 项")
            ct = make_treemap(data, args.depth)
            cb = make_bar(data)
            cd = make_donut(data)
            out = args.out or f"disk_report_{d[0]}.html"
            if len(drives) > 1:
                out = f"disk_report_{d[0]}.html"
            with open(out, "w", encoding="utf-8") as f:
                f.write(build_html(data, ct, cb, cd, font_name))
            apath = os.path.abspath(out)
            print(f"  [✓] 报告已生成：{apath}")
            reports.append(apath)

    print("\n[完成] 生成的报告：")
    for r in reports:
        print("  -", r)


if __name__ == "__main__":
    main()
