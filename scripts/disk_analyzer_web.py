#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
disk_analyzer_web.py —— 磁盘分析「网页版」（实时进度面板风格）
============================================================
在浏览器里交互式分析磁盘：
  · 盘符下拉选择（C/D/E/F）
  · 目录选择器（浏览器原生选目录，自动拼成绝对路径）
  · 实时进度卡片（显示当前正在扫描的目录/文件、已完成项、耗时）
  · 可随时「停止」扫描
  · 点击目录行 → 调用资源管理器打开所在位置

本地 HTTP 服务（默认 127.0.0.1:8780），复用 disk_analyzer 的扫描与图表函数。
用法：
  python disk_analyzer_web.py                 # 默认 8780
  python disk_analyzer_web.py --port 8781     # 指定端口
浏览器打开 http://127.0.0.1:8780/
"""

import os
import sys
import json
import time
import uuid
import threading
import subprocess
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import disk_analyzer as da  # 复用：analyze_disk / scan_top / make_* / human 等

# scan_id -> progress 字典（跨线程共享，便于前端轮询/取消）
SCANS = {}

# 服务启动配置（main 中填充），供「/」路由动态生成启动命令——绝不写死脚本路径
_SERVER_HOST = "127.0.0.1"
_SERVER_PORT = 8780

# 版本号：与 SKILL.md / meta.json 保持一致。
# 页面 <title> 与顶部 <h1> 统一取此处（模板占位符 __VERSION__），避免多处硬编码漂移。
VERSION = "1.0.5"

# ---------------------------------------------------------------------------
# 扫描历史（本地快照，用于计算「较上次扫描的体积变化 / 增长预警」）
# ---------------------------------------------------------------------------
HISTORY_PATH = os.path.join(os.path.expanduser("~"), ".workbuddy", "disk_analyzer_history.json")
# 上次完整扫描结果的本地缓存（用于页面打开时直接还原上次快照：图表+明细+报告）
LAST_RESULT_PATH = os.path.join(os.path.expanduser("~"), ".workbuddy", "disk_analyzer_last_result.json")


def _load_history():
    try:
        with open(HISTORY_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_history(hist):
    try:
        os.makedirs(os.path.dirname(HISTORY_PATH), exist_ok=True)
        with open(HISTORY_PATH, "w", encoding="utf-8") as f:
            json.dump(hist, f, ensure_ascii=False)
    except Exception:
        pass


def _history_key(disk, path):
    return (disk or path or "").rstrip("\\/").upper()


def _apply_growth(nodes, disk, path):
    """给 nodes 补 prev_size / delta_size / days_gap（基于本地历史快照）。"""
    hist = _load_history()
    slot = hist.get(_history_key(disk, path), {})
    prev = slot.get("nodes", {})
    prev_ts = slot.get("ts")
    now = time.time()
    for n in nodes:
        ps = prev.get(n.get("label"))
        if ps is not None and prev_ts:
            n["prev_size"] = ps
            n["delta_size"] = n["size"] - ps
            n["days_gap"] = round((now - prev_ts) / 86400.0, 1)
        else:
            n["prev_size"] = None
            n["delta_size"] = None
            n["days_gap"] = None
    return nodes


def _record_history(nodes, disk, path):
    hist = _load_history()
    hist[_history_key(disk, path)] = {
        "ts": time.time(),
        "nodes": {n.get("label"): n.get("size") for n in nodes},
    }
    # 记住最近一次扫描目标（磁盘或目录），供页面默认回填
    hist["__last__"] = {"disk": disk, "path": path, "ts": time.time()}
    _save_history(hist)


def _load_last():
    return _load_history().get("__last__")


# ---------------------------------------------------------------------------
# 扫描数据 → 响应 JSON
# ---------------------------------------------------------------------------

def build_response(disk=None, path=None, depth=2, top=15, progress=None, record=True):
    if disk:
        if progress is not None:
            progress["phase"] = f"开始扫描磁盘 {disk}"
        data = da.analyze_disk(disk, depth=depth, top=top, progress=progress)
        cap = data["total_bytes"]
        free = data["free_bytes"]
        used = (cap - free) if (cap and free is not None) else None
        capacity = ({
            "total": cap, "free": free, "used": used,
            "pct": round(used / cap * 100, 1) if (cap and used is not None) else None,
        } if cap else None)
        scanned = data["scanned_bytes"]
    else:
        # 单目录模式
        if progress is not None:
            progress["phase"] = f"开始扫描目录 {path}"
        (total, children, children_flags, files_size,
         children_mtime, files_mtime, files_has_hidden, files_list) = da.scan_top(path, progress)
        nodes = []
        for sub, sz in children.items():
            _f = children_flags.get(sub) or {}
            nodes.append({"name": sub, "label": sub, "size": sz, "children": [],
                          "is_file": False, "path": os.path.join(path, sub),
                          "mtime": children_mtime.get(sub),
                          "is_protected": _f.get("protected", False),
                          "hidden": _f.get("hidden", False)})
        # 该目录下的每一个文件逐条列出（不再聚合成「（该层文件）」）
        for f in files_list:
            nodes.append({"name": f["name"], "label": f["name"], "size": f["size"],
                          "children": [], "is_file": True,
                          "path": f["path"], "mtime": f["mtime"],
                          "is_protected": f["is_protected"],
                          "hidden": f.get("hidden", False)})
        nodes.sort(key=lambda x: x["size"], reverse=True)
        data = {"drive": path, "depth": depth, "scan_time": 0,
                "total_bytes": None, "free_bytes": None, "scanned_bytes": total,
                "nodes": nodes, "top": top, "has_hidden_any": files_has_hidden}
        capacity = None
        scanned = total

    if progress is not None:
        progress["phase"] = "正在生成图表…"
    _apply_growth(data["nodes"], disk, path)
    ct = da.make_treemap(data, depth)
    cb = da.make_bar(data)
    cd = da.make_donut(data)

    denom = (data["total_bytes"] or scanned) or 1
    tnodes = []
    for n in data["nodes"]:
        tnodes.append({
            "name": n["name"], "label": n["label"], "size": n["size"],
            "size_human": da.human(n["size"]),
            "pct": round(n["size"] / denom * 100, 1),
            "cnt": len(n.get("children") or []),
            "is_file": n.get("is_file", False),
            "path": n.get("path"),
            "prev_size": n.get("prev_size"),
            "delta_size": n.get("delta_size"),
            "days_gap": n.get("days_gap"),
            "mtime": n.get("mtime"),
            "mtime_human": da.fmt_mtime(n.get("mtime")),
            "is_protected": n.get("is_protected", False),
            "hidden": n.get("hidden", False),
        })

    if record:
        _record_history(data["nodes"], disk, path)

    # 文字分析报告（沿用「E 盘空间诊断」模板，精减版）
    report_blocks = da.build_report_blocks(data, capacity, scanned, denom)
    report_md = da.blocks_to_md(report_blocks)
    report_html = da.blocks_to_html(report_blocks)

    result = {
        "drive": data["drive"],
        "drives": da.list_fixed_drives(),
        "depth": depth, "top": top, "scan_time": data["scan_time"],
        "capacity": capacity, "scanned": scanned,
        "charts": {"treemap": ct, "bar": cb, "donut": cd},
        "has_hidden_any": data.get("has_hidden_any", False),
        "nodes": tnodes,
        "report_md": report_md,
        "report_html": report_html,
    }
    # 持久化完整结果，供页面打开时还原「上次扫描快照」
    try:
        with open(LAST_RESULT_PATH, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False)
    except Exception:
        pass
    return result


def open_folder(path):
    """仅允许打开本机已存在的固定盘路径，调用资源管理器打开/选中。"""
    try:
        path = urllib.parse.unquote(path)
        if not os.path.exists(path):
            return False
        ab = os.path.abspath(path)
        drives = [d.upper() for d in da.list_fixed_drives()]
        if not any(ab.upper().startswith(d.upper()) for d in drives):
            return False
        # explorer 路径不写死：优先用 %SystemRoot%（Windows 必设），回退 PATH 中的 explorer.exe
        explorer = os.path.join(os.environ.get("SystemRoot", ""), "explorer.exe") or "explorer.exe"
        if os.path.isfile(ab):
            subprocess.Popen([explorer, "/select,", ab])
        else:
            subprocess.Popen([explorer, ab])
        return True
    except Exception:
        return False


def handle_suggest(handler, qs):
    """路径自动补全：返回指定盘符+部分路径下的子目录列表（最多 12 个）。"""
    drive = qs.get("drive", [""])[0]
    partial = qs.get("partial", [""])[0]
    drives = [d.upper() for d in da.list_fixed_drives()]
    # 仅允许本机固定盘，防越权/遍历
    if not drive or not any(drive.upper().startswith(d.upper()) for d in drives):
        handler._send(200, json.dumps({"items": []}, ensure_ascii=False))
        return
    if ":" in drive and not drive.endswith("\\"):
        drive += "\\"
    rel = partial.replace("/", "\\").lstrip("\\")
    if rel == "" or rel.endswith("\\"):
        parent_rel, prefix = rel, ""
    else:
        i = rel.rfind("\\")
        if i >= 0:
            parent_rel, prefix = rel[:i + 1], rel[i + 1:]
        else:
            parent_rel, prefix = "", rel
    parent_full = os.path.join(drive, parent_rel) if parent_rel else drive
    try:
        entries = os.listdir(parent_full)
    except Exception:
        handler._send(200, json.dumps({"items": []}, ensure_ascii=False))
        return
    pl = prefix.lower()
    items = []
    for e in entries:
        if len(items) >= 12:
            break
        if os.path.isdir(os.path.join(parent_full, e)) and e.lower().startswith(pl):
            items.append(e)
    handler._send(200, json.dumps({"items": items}, ensure_ascii=False))


def handle_browse(handler, qs):
    """自建目录浏览器：列出指定盘符+相对路径下的子目录（不用系统上传控件）。
    返回 {drive, rel, full, parent, dirs:[{name,protected,hidden}], ok, err}"""
    drive = qs.get("drive", [""])[0]
    rel = qs.get("rel", [""])[0]
    drives = [d.upper() for d in da.list_fixed_drives()]
    if not drive or not any(drive.upper().startswith(d.upper()) for d in drives):
        handler._send(200, json.dumps({"ok": False, "err": "盘符不可用"}, ensure_ascii=False))
        return
    if ":" in drive and not drive.endswith("\\"):
        drive += "\\"
    rel = (rel or "").replace("/", "\\").strip("\\")
    full = os.path.join(drive, rel) if rel else drive
    full = os.path.abspath(full)
    # 安全校验：必须落在该盘符内
    if not full.upper().startswith(drive.upper()):
        handler._send(200, json.dumps({"ok": False, "err": "路径越界"}, ensure_ascii=False))
        return
    if not os.path.isdir(full):
        handler._send(200, json.dumps({"ok": False, "err": "目录不存在或无权限",
                                       "drive": drive, "rel": rel, "full": full},
                                      ensure_ascii=False))
        return
    dirs = []
    try:
        with os.scandir(full) as it:
            for entry in it:
                try:
                    if not entry.is_dir(follow_symlinks=False):
                        continue
                    dirs.append({
                        "name": entry.name,
                        "protected": da.is_protected(entry.name, entry.path),
                        "hidden": da.is_hidden_attr(entry.path),
                        "mtime": da.fmt_mtime(entry.stat(follow_symlinks=False).st_mtime),
                    })
                except OSError:
                    continue
    except (PermissionError, OSError) as e:
        handler._send(200, json.dumps({"ok": False, "err": "无权限读取：%s" % e,
                                       "drive": drive, "rel": rel, "full": full},
                                      ensure_ascii=False))
        return
    dirs.sort(key=lambda d: d["name"].lower())
    parent = ""
    if rel:
        i = rel.rfind("\\")
        parent = rel[:i] if i >= 0 else ""
    handler._send(200, json.dumps({
        "ok": True, "drive": drive, "rel": rel, "full": full, "parent": parent,
        "dirs": dirs,
    }, ensure_ascii=False))


# ---------------------------------------------------------------------------
# 网页（实时进度面板风格，深色 + 绿/橙主题）
# ---------------------------------------------------------------------------

PAGE = r"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>磁盘空间分析器 Ver：__VERSION__</title>
<link rel="icon" type="image/svg+xml" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Crect x='3' y='3' width='26' height='26' rx='7' fill='%2316212c' stroke='%233fb27f' stroke-width='2'/%3E%3Ccircle cx='16' cy='16' r='7' fill='none' stroke='%233fb27f' stroke-width='2'/%3E%3Ccircle cx='16' cy='16' r='1.8' fill='%23e0a13a'/%3E%3Cline x1='16' y1='16' x2='21' y2='11' stroke='%23e0a13a' stroke-width='2' stroke-linecap='round'/%3E%3C/svg%3E">
<style>
:root{--bg:#0f1720;--card:#16212c;--line:#27384a;--tx:#e8eef5;--sub:#93a7bb;
--acc:#3fb27f;--acc2:#e0a13a;--bad:#d9534f;--ink:#111a23}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--tx);font:14px/1.6 "Microsoft YaHei",system-ui,-apple-system,sans-serif;padding:clamp(10px,2.6vw,20px)}
.topbar{background:linear-gradient(135deg,#13202b,#1b2b38);border-bottom:1px solid var(--line);padding:14px clamp(12px,2.2vw,22px)}
.topbar h1{margin:0;font-size:19px;display:flex;align-items:center;gap:9px}
.topbar .hicon{display:inline-flex;align-items:center;justify-content:center;width:24px;height:24px;line-height:1}
.sub{color:var(--sub);font-size:12px;margin-top:5px;word-break:break-word}
.wrap{max-width:1200px;margin:0 auto;padding:0 clamp(4px,1vw,8px)}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:14px;margin-top:14px;overflow:hidden}
.pin{border-color:#3a5a48;background:linear-gradient(135deg,#16241d,#172a22)}
.pin b{color:var(--acc)}
.toolbar{display:flex;flex-wrap:wrap;align-items:center;gap:10px;margin-top:14px}
.toolbar .lbl{color:var(--sub);font-size:13px}
select,input,button{font-family:inherit}
/* 下拉框：与 .btn 统一的高度/圆角/描边，去掉系统默认箭头、自绘三角，选项底色与页面一致 */
.sel{appearance:none;-webkit-appearance:none;-moz-appearance:none;background-color:var(--ink);border:1px solid var(--line);border-radius:10px;color:var(--tx);padding:7px 30px 7px 12px;font-size:13px;line-height:1.2;cursor:pointer;transition:border-color .15s,box-shadow .15s;background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='11' height='7' viewBox='0 0 11 7'%3E%3Cpath d='M1.5 1.5l4 4 4-4' fill='none' stroke='%237d8fa3' stroke-width='1.6' stroke-linecap='round' stroke-linejoin='round'/%3E%3C/svg%3E");background-repeat:no-repeat;background-position:right 11px center;background-size:11px 7px}
.sel:hover{border-color:var(--acc)}
.sel:focus{outline:none;border-color:var(--acc);box-shadow:0 0 0 2px rgba(211,75,58,.18)}
.sel option{background-color:#121e29;color:var(--tx);padding:4px 8px;border:0}
.sel::-ms-expand{display:none}
.sel.sm{padding:4px 24px 4px 8px;font-size:12px;border-radius:8px;background-position:right 7px center}
/* 隐藏的原生 select 仅作值源，视觉上由自绘下拉层代替 */
.sel-mirror{position:absolute;width:0;height:0;opacity:0;padding:0;margin:0;border:0;background:none;pointer-events:none;overflow:hidden}
/* 自绘下拉层：与 .suggest 完全同一套卡面/圆角/描边/滚动条，彻底替代系统弹出层 */
.dd{position:relative;display:inline-flex}
.ddbtn{display:inline-flex;align-items:center;gap:8px;background:var(--ink);border:1px solid var(--line);border-radius:10px;color:var(--tx);padding:7px 11px;font-size:13px;line-height:1.2;cursor:pointer;transition:border-color .15s,box-shadow .15s;font-weight:600;min-width:64px}
.ddbtn:hover{border-color:var(--acc)}
.ddbtn:focus{outline:none;border-color:var(--acc);box-shadow:0 0 0 2px rgba(211,75,58,.18)}
.dd.open .ddbtn{border-color:var(--acc);box-shadow:0 0 0 2px rgba(211,75,58,.18)}
.ddcaret{font-size:9px;color:var(--sub);transition:transform .15s}
.dd.open .ddcaret{transform:rotate(180deg)}
.ddlist{display:none;position:absolute;top:100%;left:0;width:max-content;min-width:100%;margin:5px 0 0 0;padding:5px;background:var(--card);border:1px solid var(--line);border-radius:10px;max-height:320px;overflow:auto;z-index:90;box-shadow:0 10px 26px rgba(0,0,0,.5);list-style:none}
.dd.open .ddlist{display:block}
.ddlist li{display:flex;align-items:center;gap:8px;padding:7px 11px;font-size:13px;color:var(--tx);cursor:pointer;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;border-radius:7px;margin:1px 0}
.ddlist li:hover{background:#16283a;color:var(--tx)}
.ddlist li.on{background:#1b3346;color:var(--tx);box-shadow:inset 2px 0 0 var(--acc2)}
.ddlist .ddic{font-size:12px;opacity:.85;flex:0 0 auto}
.ddlist::-webkit-scrollbar{width:8px}
.ddlist::-webkit-scrollbar-track{background:#0d1620;border-radius:8px}
.ddlist::-webkit-scrollbar-thumb{background:#31465c;border-radius:8px;border:2px solid #0d1620}
.ddlist::-webkit-scrollbar-thumb:hover{background:#43607c}
.ddlist{scrollbar-width:thin;scrollbar-color:#31465c #0d1620}
.ddbtn.sm{padding:4px 9px;font-size:12px;border-radius:8px;gap:6px;min-width:52px}
.dirwrap{position:relative;flex:1 1 240px;min-width:180px;display:flex;align-items:center}
#dirpath{flex:1 1 auto;width:100%;background:var(--ink);border:1px solid var(--line);border-radius:10px;color:var(--tx);padding:7px 30px 7px 11px;font-size:13px}
.clr{position:absolute;right:5px;top:50%;transform:translateY(-50%);width:20px;height:22px;border:none;background:transparent;color:var(--sub);cursor:pointer;font-size:13px;line-height:1;display:none;align-items:center;justify-content:center;border-radius:6px;padding:0}
.clr:hover{color:var(--bad);background:rgba(217,83,79,.12)}
.dirwrap.has-val .clr{display:flex}
/* 路径自动补全下拉：与卡片/弹层统一的深色主题 + 统一滚动条 */
.suggest{display:none;position:absolute;top:100%;left:0;right:0;margin-top:5px;background:var(--card);border:1px solid var(--line);border-radius:10px;max-height:240px;overflow:auto;z-index:80;box-shadow:0 10px 26px rgba(0,0,0,.5);padding:5px}
.suggest li{list-style:none;padding:7px 11px;font-size:13px;color:var(--tx);cursor:pointer;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;border-radius:7px;margin:1px 0}
.suggest li:hover,.suggest li.sel{background:#1c2c38;color:var(--acc)}
.suggest li .sg-ico{margin-right:6px;opacity:.85}
.btn{border:1px solid var(--line);border-radius:10px;background:var(--ink);color:var(--tx);padding:7px 14px;cursor:pointer;font-size:13px}
.btn:hover{border-color:var(--acc);color:var(--acc)}
.btn.go{background:var(--acc);color:#06231a;border-color:var(--acc);font-weight:700}
.btn.go:hover{filter:brightness(1.07);color:#06231a}
.btn.stop{border-color:var(--bad);color:var(--bad)}
.btn.stop:hover{background:var(--bad);color:#fff}
.grow{flex:1 1 auto}
.hintbar{color:var(--sub);font-size:12px;margin-top:8px}
/* 进度卡片（实时进度面板风） */
.prog{display:none;border-color:#33543f;background:linear-gradient(135deg,#15231c,#172a22)}
.prog.show{display:block}
.pctitle{font-size:14px;font-weight:700;display:flex;align-items:center;gap:8px}
.spin{width:15px;height:15px;border:2px solid var(--line);border-top-color:var(--acc);border-radius:50%;animation:sp 1s linear infinite;flex:none}
@keyframes sp{to{transform:rotate(360deg)}}
.pbar{position:relative;height:10px;border-radius:999px;background:var(--ink);border:1px solid var(--line);margin-top:11px;overflow:hidden}
.pfill{position:absolute;left:0;top:0;bottom:0;width:0%;background:linear-gradient(90deg,var(--acc),var(--acc2));transition:width .25s}
.pshim{position:absolute;top:0;bottom:0;width:40%;background:linear-gradient(90deg,transparent,rgba(255,255,255,.25),transparent);animation:sh 1.4s linear infinite}
@keyframes sh{0%{left:-40%}100%{left:100%}}
.pmeta{font-size:12px;color:var(--sub);margin-top:9px}
.pcur{font-size:13px;color:var(--tx);margin-top:5px;background:var(--ink);border:1px solid var(--line);border-radius:8px;padding:6px 10px;white-space:nowrap;overflow:hidden;text-overflow:clip}
.pstat{font-size:12px;color:var(--sub);margin-top:7px;font-variant-numeric:tabular-nums}
.stats{display:flex;flex-wrap:wrap;gap:12px;margin-top:14px}
.stat{background:var(--ink);border:1px solid var(--line);border-left:3px solid var(--line);border-radius:10px;padding:9px 14px 9px 12px;min-width:120px;flex:1 1 120px;transition:box-shadow .15s}
.stat .k{color:var(--sub);font-size:11px}
.stat .v{font-size:19px;font-weight:700;margin-top:3px;color:var(--tx);font-variant-numeric:tabular-nums}
/* 四个数据块用不同主题色区分：总容量蓝 / 已用橙 / 剩余绿 / 使用率红 */
.stat.total{border-left-color:#4a90d9}
.stat.total .v{color:#7fb0ea}
.stat.used{border-left-color:#e0a13a}
.stat.used .v{color:#f0bc5b}
.stat.free{border-left-color:#3fb27f}
.stat.free .v{color:#5dc99a}
.stat.pct{border-left-color:#d9534f}
.stat.pct .v{color:#e87370}
.stat .v.warn{color:var(--acc2)}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:14px;margin-top:14px}
.ct{font-size:14px;color:var(--tx);font-weight:600;margin-bottom:9px}
.ct .hint{color:var(--sub);font-weight:400;font-size:12px}
.chart{width:100%;height:auto;display:block;border-radius:10px;background:var(--ink);cursor:zoom-in}
table{width:100%;border-collapse:collapse;background:var(--card);border:1px solid var(--line);border-radius:12px;overflow:hidden;margin-top:8px;table-layout:fixed;min-width:720px}
.tbl-wrap{overflow-x:auto;margin-top:8px;border-radius:12px}
.tbl-wrap table{margin-top:0}
.tbl-wrap::-webkit-scrollbar{height:8px}
.tbl-wrap::-webkit-scrollbar-track{background:#0d1620;border-radius:8px}
.tbl-wrap::-webkit-scrollbar-thumb{background:#31465c;border-radius:8px;border:2px solid #0d1620}
.tbl-wrap::-webkit-scrollbar-thumb:hover{background:#43607c}
.tbl-wrap{scrollbar-width:thin;scrollbar-color:#31465c #0d1620}
th,td{padding:10px 12px;text-align:left;border-bottom:1px solid var(--line);font-size:13px;vertical-align:middle}
th{background:#1b2a36;color:var(--sub);cursor:pointer;user-select:none;white-space:nowrap}
th:hover{color:var(--tx)}
th.asc::after{content:" ▲";color:var(--acc)}
th.desc::after{content:" ▼";color:var(--acc)}
td.num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap;padding-left:4px;padding-right:9px}
td.nm{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;word-break:break-all}
tbody tr{cursor:pointer;transition:.12s}
tbody tr:hover{background:#1c2c38}
.tag{background:var(--acc2);color:#2a1c05;font-size:11px;padding:1px 6px;border-radius:6px;margin-left:4px}
.nmname{display:inline}
.nmname.dim{color:#7d8fa3}
.nmname.dim + .tag{opacity:.85}
td.nm .badge{margin-left:4px}
.actbtn{border:1px solid var(--line);background:var(--ink);color:var(--sub);border-radius:8px;padding:2px 9px;cursor:pointer;font-size:13px}
.actbtn:hover{color:var(--acc);border-color:var(--acc)}
.actbtn:disabled{opacity:.28;cursor:not-allowed;border-color:var(--line);color:var(--sub)}
.actbtn:disabled:hover{color:var(--sub);border-color:var(--line)}
.area{display:none}
.area.show{display:block}
.empty{text-align:center;color:var(--sub);padding:34px 12px;display:none}
.empty.show{display:block}
.empty b{display:block;color:var(--tx);font-size:16px;margin-bottom:8px}
.toast{position:fixed;left:50%;bottom:30px;transform:translateX(-50%);background:var(--ink);border:1px solid var(--acc);color:var(--tx);padding:9px 16px;border-radius:10px;font-size:13px;opacity:0;transition:.25s;z-index:60;max-width:80vw;word-break:break-all}
.toast.show{opacity:1}
.conn{display:inline-block;margin-left:10px;font-size:12px;padding:2px 9px;border-radius:999px;border:1px solid var(--line);vertical-align:middle}
.conn.ok{color:var(--acc);border-color:#33543f;background:#15231c}
.conn.bad{color:var(--bad);border-color:var(--bad);background:#2a1715}
.down{border-color:var(--bad);background:linear-gradient(135deg,#241715,#2a1c19);display:none;margin-top:14px}
.down.show{display:block}
.down .dtitle{font-weight:700;display:flex;align-items:center;gap:8px}
.down .dmsg{color:var(--sub);font-size:13px;margin-top:6px}
.down code{display:block;background:var(--ink);border:1px solid var(--line);border-radius:8px;padding:8px 11px;margin:9px 0;color:var(--acc2);font-size:12px;word-break:break-all;white-space:pre-wrap}
.down .btn{background:var(--ink);border:1px solid var(--line);color:var(--tx);border-radius:9px;padding:6px 12px;cursor:pointer;font-size:12px}
.down .btn:hover{border-color:var(--acc);color:var(--acc)}
/* 数值列表头右对齐，与数值单元格对齐（修复表头/值错位） */
th.num{text-align:right}
/* 图表点击放大（lightbox） */
.lightbox{position:fixed;inset:0;background:rgba(6,11,16,.93);display:none;align-items:center;justify-content:center;z-index:90;padding:22px;flex-direction:column;overflow:hidden}
.lightbox.show{display:flex}
.lightbox img{max-width:94vw;max-height:86vh;width:auto;height:auto;border-radius:10px;box-shadow:0 10px 50px rgba(0,0,0,.65);background:#fff;cursor:grab;transform-origin:0 0;user-select:none;-webkit-user-drag:none;touch-action:none}
.lightbox .lbclose{position:fixed;top:16px;right:20px;background:var(--ink);border:1px solid var(--line);color:var(--tx);border-radius:10px;padding:8px 15px;cursor:pointer;font-size:14px;z-index:91}
.lightbox .lbclose:hover{border-color:var(--acc);color:var(--acc)}
.lightbox .lbhint{position:fixed;bottom:16px;left:50%;transform:translateX(-50%);color:var(--sub);font-size:12px}
/* 列表预警 / 增长标识 */
tbody tr.row-warn{background:rgba(217,83,79,.16)}
tbody tr.row-alert{background:rgba(224,161,58,.14)}
tbody tr.row-fast{background:rgba(224,114,26,.10)}
.badge{display:inline-block;font-size:11px;padding:1px 7px;border-radius:6px;margin-left:4px;font-weight:700;white-space:nowrap;vertical-align:middle}
.badge.warn{background:#d9534f;color:#fff}
.badge.alert{background:#e0a13a;color:#2a1c05}
.badge.fast{background:#e0721a;color:#fff}
.badge.down{background:#3fb27f;color:#06231a}
.badge.sys{background:#5b7a99;color:#fff}
.badge.hid{background:#4a5b6e;color:#dbe7f2}
.delta{font-variant-numeric:tabular-nums;font-size:12px;white-space:nowrap}
.delta.up{color:#d9534f}
.delta.down{color:#3fb27f}
.delta.flat{color:var(--sub)}
.legend{font-size:12px;color:var(--sub);margin:8px 0 0;line-height:1.7}
.legend b{color:var(--tx)}
/* 统一说明块（关于隐藏/系统文件） */
.note{font-size:12px;color:var(--sub);margin:8px 0 0;line-height:1.8;
  background:rgba(91,122,153,.1);border-left:3px solid #5b7a99;padding:9px 12px;border-radius:0 8px 8px 0}
.note b{color:var(--tx)}
.report .rnote{background:rgba(91,122,153,.12);border-left:3px solid #5b7a99;padding:9px 12px;border-radius:6px;font-size:12.5px;color:var(--sub);margin:10px 0;line-height:1.7}
/* 自建目录选择器（不用系统上传控件，避免误以为是上传） */
.modal{display:none;position:fixed;inset:0;z-index:120;align-items:center;justify-content:center;background:rgba(6,12,18,.62)}
.modal.show{display:flex}
.mpanel{width:min(680px,94vw);max-height:82vh;display:flex;flex-direction:column;background:var(--card);border:1px solid var(--line);border-radius:14px;box-shadow:0 18px 48px rgba(0,0,0,.5);overflow:hidden}
.mhead{display:flex;align-items:center;gap:10px;padding:12px 14px;border-bottom:1px solid var(--line);background:#152231}
.mhead b{font-size:14px}
.mhead .grow{flex:1}
.mcrumbs{display:flex;flex-wrap:wrap;gap:5px;align-items:center;padding:9px 14px;border-bottom:1px solid var(--line);font-size:12px;color:var(--sub);background:#132030;max-height:72px;overflow:auto}
.mcrumb{background:var(--ink);border:1px solid var(--line);border-radius:7px;padding:3px 9px;cursor:pointer;color:var(--tx);font-size:12px}
.mcrumb:hover{border-color:var(--acc);color:var(--acc)}
.mcrumb.cur{cursor:default;color:var(--acc);border-color:#3a5a48}
.mlist{flex:1 1 auto;min-height:180px;max-height:52vh;overflow:auto;padding:6px 8px}
.mrow{display:flex;align-items:center;gap:8px;padding:7px 10px;border-radius:8px;cursor:pointer;font-size:13px;color:var(--tx)}
.mrow:hover{background:#1c2c38}
.mrow.sel{background:#1e3a2c;color:var(--acc)}
.mrow .mico{flex:0 0 auto}
.mrow .mname{flex:1 1 auto;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.mrow .mname.dim{color:#7d8fa3}
.mrow .mtag+.mtag{margin-left:6px}
.mrow .mtag{font-size:11px;padding:1px 7px;border-radius:6px;background:#5b7a99;color:#fff;flex:0 0 auto}
.mrow .mtag.hid{background:#4a5b6e;color:#dbe7f2}
.mrow .mmtime{font-size:11px;color:var(--sub);flex:0 0 auto}
.mempty{padding:22px;text-align:center;color:var(--sub);font-size:13px}
.mfoot{display:flex;align-items:center;gap:10px;padding:11px 14px;border-top:1px solid var(--line);background:#152231;font-size:12px;color:var(--sub)}
.mfoot .mpath{flex:1 1 auto;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;direction:rtl;text-align:left}
/* 统一滚动条（下拉框/目录列表通用） */
.suggest::-webkit-scrollbar,.mlist::-webkit-scrollbar,.mcrumbs::-webkit-scrollbar{width:10px;height:10px}
.suggest::-webkit-scrollbar-track,.mlist::-webkit-scrollbar-track,.mcrumbs::-webkit-scrollbar-track{background:#0d1620;border-radius:8px}
.suggest::-webkit-scrollbar-thumb,.mlist::-webkit-scrollbar-thumb,.mcrumbs::-webkit-scrollbar-thumb{background:#31465c;border-radius:8px;border:2px solid #0d1620}
.suggest::-webkit-scrollbar-thumb:hover,.mlist::-webkit-scrollbar-thumb:hover,.mcrumbs::-webkit-scrollbar-thumb:hover{background:#43607c}
.suggest,.mlist,.mcrumbs{scrollbar-width:thin;scrollbar-color:#31465c #0d1620}
/* 分析报告（沿用 E 盘空间诊断模板） */
.report .rh1{font-size:18px;color:var(--tx);margin:0 0 8px;font-weight:700}
.report .rh2{font-size:15px;color:var(--acc);margin:16px 0 8px;font-weight:700;border-left:3px solid var(--acc);padding-left:9px}
.report .rp{font-size:13px;color:var(--sub);margin:7px 0;line-height:1.7}
.report .rquote{background:rgba(224,161,58,.1);border-left:3px solid var(--acc2);padding:9px 12px;border-radius:6px;font-size:12.5px;color:var(--sub);margin:10px 0;line-height:1.6}
.report .rul{margin:8px 0;padding-left:20px;font-size:13px;color:var(--sub);line-height:1.85}
.report .rul li{margin:3px 0}
.report .rul li b{color:var(--tx)}
.report table{margin:8px 0;table-layout:auto;min-width:100%}
.report table th{background:#1b2a36;color:var(--sub);font-size:12px;padding:7px 10px;text-align:left;border-bottom:1px solid var(--line);white-space:nowrap}
.report table td{font-size:12.5px;padding:7px 10px;border-bottom:1px solid var(--line);color:var(--tx)}
.report table td.cnum{white-space:nowrap;width:1%;padding-left:6px;padding-right:9px}
.report table td .nmcell{display:inline-block;max-width:560px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;vertical-align:bottom}
/* v1.0.3 响应式：窄屏时收紧卡片/表头/统计表，防止布局撑破 */
@media (max-width: 960px){
  .wrap{max-width:none;padding:0 10px}
  .card{padding:12px}
  .stat{min-width:104px;flex:1 1 104px;padding:8px 10px 8px 9px}
  .stat .v{font-size:16px}
  .grid{grid-template-columns:1fr;gap:10px}
  .toolbar{gap:8px}
  th,td{padding:8px 9px}
  .ddbtn{min-width:56px}
}
@media (max-width: 640px){
  body{padding:8px}
  .topbar{padding:12px 10px}
  .topbar h1{font-size:17px;flex-wrap:wrap}
  .sub{font-size:11px}
  .card{padding:10px}
  .ct{font-size:13px}
  .ct .hint{font-size:11px}
  .stat{min-width:0;flex:1 1 calc(50% - 6px);padding:7px 9px}
  .stat .v{font-size:14px}
  .stat .k{font-size:10px}
  th,td{padding:7px 8px;font-size:12px}
  .btn{padding:6px 11px;font-size:12px}
  .actbtn{padding:2px 7px;font-size:12px}
  .tag{font-size:10px;padding:1px 5px}
  .legend,.note{font-size:11.5px;line-height:1.55}
  .dirwrap{min-width:130px}
  .mpanel{width:96vw;max-height:88vh}
}
</style></head>
<body>
<div class="topbar"><div class="wrap">
  <h1><span class="hicon"><svg width="24" height="24" viewBox="0 0 32 32" xmlns="http://www.w3.org/2000/svg" aria-hidden="true"><rect x="3" y="3" width="26" height="26" rx="7" fill="none" stroke="#3fb27f" stroke-width="2"/><circle cx="16" cy="16" r="7" fill="none" stroke="#3fb27f" stroke-width="2"/><circle cx="16" cy="16" r="1.8" fill="#e0a13a"/><line x1="16" y1="16" x2="21" y2="11" stroke="#e0a13a" stroke-width="2" stroke-linecap="round"/></svg></span> 磁盘空间分析器 Ver：__VERSION__</h1>
  <div class="sub" id="hdr">选择盘符或目录后开始分析 —— 实时显示当前扫描位置，可随时停止。<span id="conn" class="conn">● 连接中…</span></div>
</div></div>
<div class="wrap">
  <div class="card pin">📌 <b>置顶任务</b> · 磁盘空间分析器 —— 可选盘符 C/D/E/F 实时扫描并以图表展示占用；点击目录行可直接打开所在位置。</div>

  <div id="downBanner" class="card down">
    <div class="dtitle"><span>🔴 服务未连接</span></div>
    <div class="dmsg">磁盘分析需要本地服务在运行。服务已停止或被关闭时，页面仍可打开但「开始」无法扫描。请在本机终端重新启动服务（重启后刷新本页即可）：</div>
    <code id="cmdLine">__START_CMD__</code>
    <button class="btn" id="copyCmd">📋 复制启动命令</button>
  </div>

  <div class="toolbar">
    <span class="lbl">盘符：</span>
    <select id="driveSel" class="sel-mirror" tabindex="-1" aria-hidden="true"></select>
    <div class="dd" id="ddWrap">
      <button type="button" class="ddbtn" id="ddBtn"><span id="ddLabel">C:</span><span class="ddcaret">▾</span></button>
      <ul class="ddlist" id="ddList"></ul>
    </div>
    <span class="lbl">目录：</span>
    <span class="dirwrap">
      <input id="dirpath" placeholder="相对路径，如 Users\yourname（盘符见左侧）" />
      <button id="clearBtn" class="clr" type="button" title="清空" aria-label="清空">✕</button>
    </span>
    <button id="pickBtn" class="btn">📁 选择目录</button>
    <button id="goBtn" class="btn go">▶ 开始分析</button>
    <button id="stopBtn" class="btn stop" style="display:none">⏹ 停止</button>
    <span class="grow"></span>
  </div>
  <div class="hintbar">提示：盘符与路径为强关联——<b>切换盘符会清空路径</b>，路径框填的是「相对当前盘符」的路径（无需带盘符）。直接手填时会自动补全同级目录（↑↓选择、回车/Tab 确认、Esc 关闭）；若手填了「X:\…」也会自动切到对应盘符。「选择目录」可逐层浏览点选。</div>

  <div id="prog" class="card prog">
    <div class="pctitle"><span class="spin" id="pspin"></span><span id="pstatus">扫描中…</span></div>
    <div class="pbar"><div class="pfill" id="pfill"></div><div class="pshim" id="pshim"></div></div>
    <div class="pmeta" id="pmeta">—</div>
    <div class="pcur" id="pcur">—</div>
    <div class="pstat" id="pstat">—</div>
  </div>

  <div id="empty" class="card empty show"><b>📂 选择盘符或目录，点「开始分析」</b>完成后将显示 treemap、条形图、环形图与明细表；扫描时上方进度卡片会实时显示当前正在扫描的目录。</div>

  <div id="stats" class="stats"></div>

  <div id="charts" class="area">
    <div class="grid">
      <div class="card"><div class="ct">① 矩形树图 Treemap（面积=体积）<span class="hint">· 点击放大</span></div><img id="imgtm" class="chart" alt="treemap"></div>
      <div class="card"><div class="ct">② Top N 横向条形图<span class="hint">· 点击放大</span></div><img id="imgbar" class="chart" alt="bar"></div>
      <div class="card"><div class="ct">③ 环形占比图<span class="hint">· 点击放大</span></div><img id="imgdonut" class="chart" alt="donut"></div>
    </div>
  </div>

  <div id="tablewrap" class="area">
    <div class="card">
      <div class="ct">📋 目录与文件明细 <span class="hint">（点击表头排序 · 点击行打开所在目录 · 变化列按上次扫描快照计算）</span></div>
      <div class="tbl-wrap">
      <table id="tbl">
      <colgroup>
        <col style="width:40px">
        <col style="width:auto">
        <col style="width:82px">
        <col style="width:66px">
        <col style="width:112px">
        <col style="width:122px">
        <col style="width:46px">
        <col style="width:90px">
      </colgroup>
      <thead><tr>
        <th data-k="idx">#</th><th data-k="name">名称</th>
        <th data-k="size" class="num">大小</th><th data-k="pct" class="num" title="占「本次扫描目标（当前盘符或当前目录）总量」的百分比，不是占整块磁盘容量">占目标%</th>
        <th data-k="delta" class="num">变化(较上次)</th><th data-k="mtime" class="num">最后修改</th><th data-k="cnt" class="num">子项</th><th data-k="act" class="num">操作</th>
      </tr></thead><tbody id="tbody"></tbody></table>
      </div>
      <div class="legend">🎨 标识：<b style="color:#d9534f">红底</b>=占用≥15% 占比大 · <b style="color:#e0a13a">橙底</b>=5%~15% 占比中 · <b style="color:#e0721a">🔥快增</b>=较上次扫描增≥5GB · <b style="color:#3fb27f">▼绿</b>=体积下降 · <b style="color:#5b7a99">🛡️系统</b>=Windows 系统保留项，<b>切勿删除或移动</b> · 👁️隐藏=该条目带隐藏属性，资源管理器默认不显示（<b style="color:#7d8fa3">名称显示为灰色</b>）。<b>占目标%</b>=占本次扫描目标（当前盘符或当前目录）总量的百分比，非整块磁盘容量。变化列 “—”=无历史/几乎无变化；基于本地扫描历史（首次扫描后开始记录，用于发现“吃空间”的目录/文件）。操作列 📂=打开（文件为「打开并选中」）、🔍=下钻分析（文件行置灰不可用，仅为保持布局一致）。</div>
      <div class="note">ℹ️ <b>关于体积与隐藏文件</b>：目录体积为其<b>整棵子树</b>合计，文件为单个文件实际大小，两者都<b>包含隐藏文件与系统文件</b>（如 pagefile.sys 虚拟内存、hiberfil.sys 休眠文件、System Volume Information 还原点等），它们在资源管理器中默认不显示，所以某些目录的合计会明显大于你在资源管理器里看到的大小——这是正常的，不是重复计算、也不是 bug。条目按<b>自身属性</b>分别标注：<b>🛡️系统</b>=系统保留项（切勿删除）；<b>👁️隐藏</b>=带隐藏属性（资源管理器默认不显示，多为配置/缓存，删除前先确认用途）。两个标签<b>可同时出现</b>（如 pagefile.sys 既是系统文件也是隐藏文件），带隐藏属性的条目名称统一以灰色显示。</div>
    </div>
  </div>

  <div id="reportwrap" class="area">
    <div class="card report">
      <div class="ct">📝 空间分析报告 <span class="hint">（沿用 E 盘空间诊断模板 · 自动生成）</span>
        <button id="dlReport" class="btn" style="float:right;margin-top:-4px">📥 下载报告(.md)</button></div>
      <div id="reportBody"></div>
    </div>
  </div>
</div>

<div class="lightbox" id="lb">
  <button class="lbclose" id="lbClose">✕ 关闭 (Esc)</button>
  <img id="lbImg" src="" alt="放大查看">
  <div class="lbhint">滚轮缩放 · 拖拽平移 · 点击空白处或按 Esc 关闭</div>
</div>
<!-- 自建目录选择器：不用系统上传控件，避免误以为是上传文件 -->
<div class="modal" id="dirModal">
  <div class="mpanel">
    <div class="mhead">
      <span>📁</span><b>选择目录</b>
      <span class="grow"></span>
      <select id="mDrive" class="sel-mirror" tabindex="-1" aria-hidden="true"></select>
      <div class="dd" id="mDD"><button type="button" class="ddbtn sm" id="mDDBtn"><span id="mDDLabel">C:</span><span class="ddcaret">▾</span></button><ul class="ddlist" id="mDDList"></ul></div>
      <button class="btn" id="mClose">✕ 关闭</button>
    </div>
    <div class="mcrumbs" id="mCrumbs"></div>
    <div class="mlist" id="mList"></div>
    <div class="mfoot">
      <span>当前：<b id="mPath" style="color:var(--tx)">—</b></span>
      <span class="grow"></span>
      <button class="btn" id="mUp">↑ 上一级</button>
      <button class="btn" id="mRefresh">↻ 刷新</button>
      <button class="btn go" id="mPick">✔ 选择此目录</button>
    </div>
  </div>
</div>
<div class="toast" id="toast"></div>

<script>
var state={drive:null, sortKey:'size', sortAsc:false, sid:null, es:null};
function $(id){return document.getElementById(id);}
function esc(s){return String(s).replace(/[&<>]/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;'}[c];});}
function human(n){ if(n==null) return '—'; var u=['B','KB','MB','GB','TB'],i=0; n=+n; while(n>=1024&&i<u.length-1){n/=1024;i++;} return n.toFixed(1)+' '+u[i]; }
// 中间省略号：超长路径保留首尾，中间用 … 替代，并保证单行显示
function midEllipsis(s, max){
  s = String(s==null?'':s); max = max||46;
  if(s.length <= max) return s;
  var sep='…', keep=max-sep.length;
  if(keep<2) return s.slice(0, max);
  var head=Math.ceil(keep/2), tail=keep-head;
  return s.slice(0,head)+sep+s.slice(s.length-tail);
}
function toast(msg){var t=$('toast');t.textContent=msg;t.classList.add('show');clearTimeout(t._t);t._t=setTimeout(function(){t.classList.remove('show');},2600);}

/* ===== 自绘下拉层：覆盖隐藏的原生 select（值源不变），弹出层样式与 .suggest 统一 ===== */
var DD_RENDER={};
function mountDD(selId, wrapId, btnId, labelId, listId){
  var sel=$(selId), wrap=$(wrapId), btn=$(btnId), label=$(labelId), list=$(listId);
  function items(){ return [].slice.call(sel.options).map(function(o){return {value:o.value,text:o.textContent};}); }
  function render(){
    var cur=sel.value, curText='—';
    items().forEach(function(o){ if(o.value===cur) curText=o.text; });
    if(!curText && cur) curText=cur.charAt(0)+':';
    label.textContent=curText;
    list.innerHTML=items().map(function(o){
      return '<li data-v="'+esc(o.value)+'"'+(o.value===cur?' class="on"':'')+'><span class="ddic">💽</span>'+esc(o.text)+'</li>';
    }).join('');
  }
  DD_RENDER[selId]=render;
  function close(){ wrap.classList.remove('open'); }
  btn.onclick=function(e){ e.stopPropagation(); e.preventDefault(); wrap.classList.toggle('open'); if(wrap.classList.contains('open')) render(); };
  list.onclick=function(e){
    var li=e.target.closest('li'); if(!li||!li.dataset.v) return;
    if(sel.value!==li.dataset.v) sel.value=li.dataset.v;
    close(); render();
    sel.dispatchEvent(new Event('change',{bubbles:true}));
  };
  document.addEventListener('click',function(e){ if(!wrap.contains(e.target)) close(); });
  render();
}
function ddRender(selId){ if(DD_RENDER[selId]) DD_RENDER[selId](); }

function buildDrives(){
  // 盘符下拉：先用常见盘符占位，/scan 首次返回后刷新真实列表
  var opts=['C:\\','D:\\','E:\\','F:\\'];
  var sel=$('driveSel'); sel.innerHTML='';
  opts.forEach(function(d){var o=document.createElement('option');o.value=d;o.textContent=d.charAt(0)+':';sel.appendChild(o);});
  ddRender('driveSel');
}
function refreshDrives(drives){
  if(!drives||!drives.length) return;
  var sel=$('driveSel');
  var cur=sel.value;
  sel.innerHTML='';
  drives.forEach(function(d){var o=document.createElement('option');o.value=d;o.textContent=d.charAt(0)+':';sel.appendChild(o);});
  if(cur && [].slice.call(sel.options).some(function(o){return o.value===cur;})) sel.value=cur;
  ddRender('driveSel');
}

function startScan(){
  normalizePathInput();
  var drive=$('driveSel').value;
  // 输入框路径为“相对当前盘符”的路径，与左侧盘符共同构成完整路径
  var rel=$('dirpath').value.trim().replace(/\//g,'\\').replace(/\\+/g,'\\').replace(/^\\+/,'');
  var q, mode;
  if(rel){ var dir=drive+rel; q='dir='+encodeURIComponent(dir); mode='dir'; }
  else { q='disk='+encodeURIComponent(drive); mode='disk'; }
  if(state.es) state.es.close();
  // 先确认服务在线：否则明确提示，避免「开始」静默失效
  fetch('/ping',{cache:'no-store'}).then(function(r){return r.ok?r.json():Promise.reject();})
    .then(function(){ enterScanUI(); openSSE(q); })
    .catch(function(){ setConn(false); toast('服务未连接，请先启动服务（见上方提示）'); });
}
// 规范化路径输入：若手填了“X:\...”盘符前缀，自动切换左侧盘符并取相对路径
function normalizePathInput(){
  var v=$('dirpath').value.trim().replace(/\//g,'\\');
  var m=v.match(/^([A-Za-z]):\\?/);
  if(m){
    var drv=m[1].toUpperCase()+':\\';
    var sel=$('driveSel');
    var has=[].slice.call(sel.options).some(function(o){return o.value===drv;});
    if(has) sel.value=drv;
    v=v.slice(2).replace(/^\\+/,'');
    $('dirpath').value=v;
  }
  toggleClear();
}
function enterScanUI(){
  $('empty').classList.remove('show');
  $('charts').classList.remove('show');
  $('tablewrap').classList.remove('show');
  $('reportwrap').classList.remove('show');
  $('stats').innerHTML='';
  $('prog').classList.add('show');
  $('goBtn').style.display='none';
  $('stopBtn').style.display='inline-block';
  setProgress(0,'准备中…','—','—');
}
function openSSE(q){
  state.es = new EventSource('/scan?'+q);
  state.es.addEventListener('progress', function(e){
    var d=JSON.parse(e.data);
    if(d.sid) state.sid=d.sid;
    var pct = (d.total>0)? Math.round(d.done/d.total*100): 0;
    setProgress(pct, d.phase||'扫描中…', d.current||'—', d.elapsed!=null?('已用 '+d.elapsed+'s'+(d.done>0?(' · '+d.done+'/'+d.total+' 目录'):'')):'—');
  });
  state.es.addEventListener('done', function(e){
    var d=JSON.parse(e.data);
    state.es.close();
    finishScanUI(d.cancelled);
    if(d.drives) refreshDrives(d.drives);
    render(d);
  });
  state.es.addEventListener('error', function(){
    state.es.close();
    finishScanUI(false);
    setConn(false);
    toast('扫描中断或出错（服务可能已断开）');
  });
}

function setProgress(pct, status, cur, stat){
  $('pfill').style.width = pct+'%';
  $('pstatus').textContent = status;
  $('pmeta').textContent = (pct>0? ('进度 '+pct+'%') : '进度：计算中…');
  $('pcur').textContent = '📍 当前：'+midEllipsis(cur, 46);
  $('pstat').textContent = stat;
}

function finishScanUI(cancelled){
  $('prog').classList.remove('show');
  $('goBtn').style.display='inline-block';
  $('stopBtn').style.display='none';
  $('pspin').style.display='none';
  $('pstatus').textContent = cancelled? '⏹ 已停止（部分结果）' : '✅ 扫描完成';
  $('pfill').style.width='100%';
  $('pcur').textContent = cancelled? '已停止扫描' : '扫描完成';
}

function stopScan(){
  if(state.sid){
    fetch('/cancel?id='+encodeURIComponent(state.sid)).then(function(){toast('正在停止…');});
  }
}

function render(d){
  state.drive=d.drive;
  $('hdr').textContent='磁盘 '+d.drive+' · 扫描 '+d.scan_time+'s · depth='+d.depth+' · 生成 '+new Date().toLocaleString('zh-CN');
  $('empty').classList.remove('show');
  $('charts').classList.add('show');
  $('tablewrap').classList.add('show');
  refreshDrives(d.drives);
  var st=$('stats');
  if(d.capacity){var c=d.capacity;
    var pctcls=(c.pct!=null&&c.pct>=90)?'warn':'';
    st.innerHTML=statCard('总容量',human(c.total),'total')+statCard('已用',human(c.used),'used')
      +statCard('剩余',human(c.free),'free')+statCard('使用率',(c.pct!=null?c.pct.toFixed(1):'—')+'%','pct'+(pctcls?' '+pctcls:''));
  } else { st.innerHTML=statCard('扫描合计',human(d.scanned)); }
  $('imgtm').src='data:image/png;base64,'+d.charts.treemap;
  $('imgbar').src='data:image/png;base64,'+d.charts.bar;
  $('imgdonut').src='data:image/png;base64,'+d.charts.donut;
  var tb=$('tbody'); tb.innerHTML='';
  d.nodes.forEach(function(n,i){
    // 大小预警
    var pctCls = n.pct>=15?'warn':(n.pct>=5?'alert':'');
    var sizeBadge = pctCls?('<span class="badge '+pctCls+'">'+(pctCls==='warn'?'⚠大':'⚠中')+'</span>'):'';
    // 增长（较上次扫描）
    var delta=n.delta_size, deltaHtml='', growthBadge='', rowCls='';
    if(delta===null||delta===undefined){
      deltaHtml='<span class="delta flat">—</span>';
    } else if(delta>0){
      deltaHtml='<span class="delta up">▲ +'+human(Math.abs(delta))+'</span>';
      if(delta>=5*1024*1024*1024){ growthBadge=' <span class="badge fast">🔥快增</span>'; rowCls='row-fast'; }
    } else if(delta<0){
      deltaHtml='<span class="delta down">▼ -'+human(Math.abs(delta))+'</span>';
      growthBadge=' <span class="badge down">↓</span>';
    } else {
      deltaHtml='<span class="delta flat">—</span>';
    }
    if(pctCls==='warn') rowCls='row-warn'; else if(pctCls==='alert') rowCls='row-alert';
    var tr=document.createElement('tr');
    tr.className=rowCls;
    tr.dataset.idx=i+1; tr.dataset.name=n.label; tr.dataset.size=n.size;
    tr.dataset.pct=n.pct; tr.dataset.cnt=n.cnt; tr.dataset.path=n.path||'';
    tr.dataset.delta=(delta===null||delta===undefined)?'':delta;
    var tag=n.is_file?' <span class="tag">文件</span>':'';
    // 两个独立属性标签：系统保留项 / 隐藏属性 —— 可共存（如 pagefile.sys 既是系统也是隐藏）
    var prodb='';
    if(n.is_protected)
      prodb += ' <span class="badge sys" title="Windows 系统保留目录/文件（如 Windows、Program Files、$Recycle.Bin、System Volume Information、pagefile.sys 等）。删除或移动会导致系统损坏，请勿动。">🛡️系统</span>';
    if(n.hidden)
      prodb += ' <span class="badge hid" title="该条目带「隐藏」属性，资源管理器默认不显示（需在“查看”中勾选“隐藏的项目”）。多为程序配置/缓存目录，删除前先确认用途。">👁️隐藏</span>';
    // 操作列：📂 永远可用；🔍 仅目录可下钻，文件行保留按钮但置灰禁用（布局不变）
    var act = n.path ? (
        '<button class="actbtn b-open" title="'+(n.is_file?'在资源管理器中打开并选中该文件':'打开该目录')+'">📂</button>'
        +'<button class="actbtn b-drill" title="'+(n.is_file?'该条目是文件，无法作为目录下钻分析（可用 📂 打开并选中）':'分析此目录')+'"'+(n.is_file?' disabled':'')+'>🔍</button>'
      ) : '';
    // v1.0.3：主表格去掉 JS 中间省略，交给 CSS 单点截断；title 悬浮看全名。
  // 旧版 midEllipsis(label,36) 与 td.nm 的 text-overflow:ellipsis 叠加，中文长名会出现 A…B… 双省略。
  var nmCell='<span class="nmname'+(n.hidden?' dim':'')+'">'+esc(n.label)+'</span>'+sizeBadge+tag+prodb;
    tr.dataset.mtime = (n.mtime==null?'':n.mtime);
    tr.innerHTML='<td>'+ (i+1) +'</td><td class="nm" title="'+esc(n.path||n.label)+'">'+nmCell+'</td>'
      +'<td class="num">'+n.size_human+'</td><td class="num">'+n.pct.toFixed(1)+'%</td>'
      +'<td class="num">'+deltaHtml+growthBadge+'</td>'
      +'<td class="num">'+n.mtime_human+'</td>'
      +'<td class="num">'+(n.is_file?'—':n.cnt)+'</td><td class="num act">'+act+'</td>';
    tr.onclick=function(e){
      var t=e.target;
      if(t.closest('.b-open')){ if(n.path) openFolder(n.path); return; }
      if(t.closest('.b-drill')){ drillInto(n.path); return; }
      if(n.path) openFolder(n.path);
    };
    tb.appendChild(tr);
  });
  $('reportBody').innerHTML = d.report_html || '';
  $('reportwrap').classList.add('show');
  state.reportMd = d.report_md || '';
  applySort();
}
function statCard(k,v,cls){
  // cls 里可含 'total|used|free|pct' 语义色（挂到 .stat 上，控制左边条与数值色）
  // 也可含 'warn'（挂到 .v 上，覆盖数值颜色为橙色）
  cls=cls||'';
  var parts=cls.split(/\s+/).filter(Boolean);
  var statCls='stat', vCls='v';
  parts.forEach(function(p){
    if(p==='warn'){ vCls+=' warn'; }
    else { statCls+=' '+p; }
  });
  return '<div class="'+statCls+'"><div class="k">'+k+'</div><div class="'+vCls+'">'+v+'</div></div>';
}

function applySort(){
  var tb=$('tbody'); var rows=[].slice.call(tb.querySelectorAll('tr'));
  var k=state.sortKey, asc=state.sortAsc;
  rows.sort(function(a,b){
    var va,vb;
    if(k==='name'){va=a.dataset.name;vb=b.dataset.name;return asc?va.localeCompare(vb,'zh'):vb.localeCompare(va,'zh');}
    if(k==='delta'){va=a.dataset.delta===''?-Infinity:+a.dataset.delta; vb=b.dataset.delta===''?-Infinity:+b.dataset.delta; return asc?va-vb:vb-va;}
    if(k==='mtime'){va=a.dataset.mtime===''?-Infinity:+a.dataset.mtime; vb=b.dataset.mtime===''?-Infinity:+b.dataset.mtime; return asc?va-vb:vb-va;}
    va=+a.dataset[k]; vb=+b.dataset[k];
    return asc?va-vb:vb-va;
  });
  rows.forEach(function(r){tb.appendChild(r);});
  [].slice.call(document.querySelectorAll('#tbl th')).forEach(function(th){
    th.classList.remove('asc','desc'); if(th.dataset.k===k) th.classList.add(asc?'asc':'desc');
  });
}
[].slice.call(document.querySelectorAll('#tbl th')).forEach(function(th){
  th.onclick=function(){
    var k=th.dataset.k;
    if(state.sortKey===k) state.sortAsc=!state.sortAsc;
    else {state.sortKey=k; state.sortAsc=(k==='name');}
    applySort();
  };
});

function openFolder(p){
  fetch('/open?path='+encodeURIComponent(p)).then(function(r){return r.json();}).then(function(j){
    toast(j.ok?('已打开：'+midEllipsis(p,52)):('无法打开：'+midEllipsis(p,52)));
  }).catch(function(){toast('打开失败');});
}

function drillInto(p){
  if(!p) return;
  var v=p.replace(/\//g,'\\');
  var m=v.match(/^([A-Za-z]):\\?/);
  if(m){ var drv=m[1].toUpperCase()+':\\'; var sel=$('driveSel'); var has=[].slice.call(sel.options).some(function(o){return o.value===drv;}); if(has) sel.value=drv; v=v.slice(2).replace(/^\\+/,''); }
  $('dirpath').value=v;
  toggleClear(); hideSuggest();
  var full=$('driveSel').value+v;
  toast('开始分析：'+midEllipsis(full,52));
  startScan();
}

$('dlReport').onclick=function(){
  if(!state.reportMd){toast('暂无可下载报告');return;}
  var blob=new Blob([state.reportMd],{type:'text/markdown;charset=utf-8'});
  var a=document.createElement('a'); a.href=URL.createObjectURL(blob);
  a.download='磁盘分析报告_'+state.drive+'.md'; a.click();
  setTimeout(function(){URL.revokeObjectURL(a.href);},1000);
};
$('goBtn').onclick=startScan;
$('stopBtn').onclick=stopScan;
/* ===== 自建目录选择器（弹层，非系统上传控件） ===== */
var mState={drive:'', rel:''};
function syncMDrive(){
  var s=$('mDrive');
  var cur=mState.drive||s.value||'';
  s.innerHTML='';
  [].slice.call($('driveSel').options).forEach(function(o){
    var op=document.createElement('option'); op.value=o.value; op.textContent=o.textContent; s.appendChild(op);
  });
  if(cur && [].slice.call(s.options).some(function(o){return o.value===cur;})) s.value=cur;
  ddRender('mDrive');
}
function openDirPicker(){
  syncMDrive();
  mState.drive=$('driveSel').value;
  // 以当前输入框内容为起点（若已填），否则从盘符根开始
  var v=$('dirpath').value.replace(/\//g,'\\').replace(/\\+$/,'');
  mState.rel = v.replace(/^[A-Za-z]:\\?/,'').replace(/^\\+/,'');
  $('mDrive').value=mState.drive;
  ddRender('mDrive');
  $('dirModal').classList.add('show');
  browseTo(mState.rel);
}
function closeDirPicker(){ $('dirModal').classList.remove('show'); }
function browseTo(rel){
  mState.rel=rel||'';
  $('mList').innerHTML='<div class="mempty">读取中…</div>';
  fetch('/browse?drive='+encodeURIComponent(mState.drive)+'&rel='+encodeURIComponent(mState.rel),{cache:'no-store'})
    .then(function(r){return r.json();})
    .then(function(d){
      if(!d.ok){ $('mList').innerHTML='<div class="mempty">⚠ '+(d.err||'无法读取')+'</div>'; return; }
      mState.rel=d.rel||'';
      $('mPath').textContent=d.full;
      // 面包屑
      var parts=mState.rel? mState.rel.split('\\'):[];
      var html='<span class="mcrumb" data-rel="">'+esc(mState.drive)+'</span>';
      var acc=[];
      parts.forEach(function(p,i){
        acc.push(p);
        var isLast=(i===parts.length-1);
        html+='<span style="opacity:.5">›</span><span class="mcrumb'+(isLast?' cur':'')+'" data-rel="'+esc(acc.join('\\'))+'">'+esc(p)+'</span>';
      });
      $('mCrumbs').innerHTML=html;
      [].slice.call($('mCrumbs').querySelectorAll('.mcrumb')).forEach(function(c){
        if(c.classList.contains('cur')) return;
        c.onclick=function(){ browseTo(c.dataset.rel); };
      });
      // 目录列表
      if(!d.dirs.length){ $('mList').innerHTML='<div class="mempty">（该目录下没有子目录）</div>'; return; }
      $('mList').innerHTML=d.dirs.map(function(x){
        // 与明细表一致：系统/隐藏可同时出现，隐藏条目名称置灰
        var tg='';
        if(x.protected) tg+='<span class="mtag">🛡️系统</span>';
        if(x.hidden) tg+='<span class="mtag hid">👁️隐藏</span>';
        return '<div class="mrow" data-name="'+esc(x.name)+'">'
             + '<span class="mico">📁</span><span class="mname'+(x.hidden?' dim':'')+'">'+esc(x.name)+'</span>'+tg
             + '<span class="mmtime">'+esc(x.mtime||'')+'</span></div>';
      }).join('');
      [].slice.call($('mList').querySelectorAll('.mrow')).forEach(function(r){
        r.onclick=function(){
          var nx=mState.rel? (mState.rel+'\\'+r.dataset.name) : r.dataset.name;
          browseTo(nx);
        };
      });
    })
    .catch(function(){ $('mList').innerHTML='<div class="mempty">⚠ 读取失败，请确认服务在运行</div>'; });
}
$('pickBtn').onclick=openDirPicker;
$('mClose').onclick=closeDirPicker;
$('dirModal').addEventListener('click',function(e){ if(e.target===this) closeDirPicker(); });
$('mUp').onclick=function(){
  var i=mState.rel.lastIndexOf('\\');
  browseTo(i>=0? mState.rel.slice(0,i): '');
};
$('mRefresh').onclick=function(){ browseTo(mState.rel); };
$('mDrive').onchange=function(){ mState.drive=this.value; browseTo(''); };
$('mPick').onclick=function(){
  // 盘符与路径强绑定：选择目录后同步左侧盘符，路径框只填相对路径
  var sel=$('driveSel'); var has=[].slice.call(sel.options).some(function(o){return o.value===mState.drive;});
  if(has) sel.value=mState.drive;
  $('dirpath').value=mState.rel;
  toggleClear(); hideSuggest(); closeDirPicker();
  toast('已选择：'+midEllipsis(mState.drive+mState.rel,52));
};
// 路径输入框「清空」按钮：有内容时自动出现，点击即清空
function toggleClear(){ var w=document.querySelector('.dirwrap'); if($('dirpath').value.trim()) w.classList.add('has-val'); else w.classList.remove('has-val'); }
$('dirpath').addEventListener('input', toggleClear);
$('clearBtn').onclick=function(){ $('dirpath').value=''; toggleClear(); $('dirpath').focus(); };

// 盘符与路径是强关系：切换盘符时清空路径（原路径属于旧盘符）
$('driveSel').addEventListener('change', function(){
  $('dirpath').value=''; toggleClear(); hideSuggest();
  toast('已切换盘符，路径已清空（路径随盘符变化）');
});

// 路径自动补全：输入框为“相对当前盘符”的路径，输入时下拉提示同层子目录
var sugBox=null, sugItems=[], sugIdx=-1, sugTimer=null;
function dirPartOf(s){ var i=s.lastIndexOf('\\'); return i>=0? s.slice(0,i+1):''; }
function ensureSugBox(){
  if(sugBox) return sugBox;
  sugBox=document.createElement('div'); sugBox.id='suggestBox'; sugBox.className='suggest';
  document.querySelector('.dirwrap').appendChild(sugBox);
  sugBox.addEventListener('mousedown', function(e){ var li=e.target.closest('li'); if(!li) return; e.preventDefault(); pickSug(li.dataset.name); });
  return sugBox;
}
function hideSuggest(){ if(sugBox) sugBox.style.display='none'; sugIdx=-1; }
function showSuggest(items){
  var box=ensureSugBox(); sugItems=items||[]; sugIdx=-1;
  if(!sugItems.length){ box.style.display='none'; return; }
  box.innerHTML=sugItems.map(function(n){ return '<li data-name="'+esc(n)+'"><span class="sg-ico">📁</span>'+esc(midEllipsis(n,42))+'</li>'; }).join('');
  box.style.display='block';
}
function moveSug(d){
  if(!sugItems.length) return;
  sugIdx=(sugIdx+d+sugItems.length)%sugItems.length;
  [].slice.call(sugBox.querySelectorAll('li')).forEach(function(li,i){ li.className=(i===sugIdx?'sel':''); });
}
function pickSug(name){
  var v=$('dirpath').value.replace(/\//g,'\\');
  $('dirpath').value=dirPartOf(v)+name+'\\';
  hideSuggest(); toggleClear(); $('dirpath').focus();
  scheduleSuggest();
}
function scheduleSuggest(){ clearTimeout(sugTimer); sugTimer=setTimeout(runSuggest,160); }
function runSuggest(){
  var v=$('dirpath').value.replace(/\//g,'\\').replace(/\\+/g,'\\').replace(/^\\+/,'');
  fetch('/suggest?drive='+encodeURIComponent($('driveSel').value)+'&partial='+encodeURIComponent(v),{cache:'no-store'})
    .then(function(r){return r.json();})
    .then(function(d){ showSuggest(d.items); })
    .catch(function(){ hideSuggest(); });
}
$('dirpath').addEventListener('input', function(){ scheduleSuggest(); });
$('dirpath').addEventListener('focus', function(){ scheduleSuggest(); });
$('dirpath').addEventListener('blur', function(){ setTimeout(hideSuggest,150); });
$('dirpath').addEventListener('keydown', function(e){
  if(sugBox && sugBox.style.display==='block'){
    if(e.key==='ArrowDown'){ e.preventDefault(); moveSug(1); return; }
    if(e.key==='ArrowUp'){ e.preventDefault(); moveSug(-1); return; }
    if(e.key==='Enter' && sugIdx>=0){ e.preventDefault(); pickSug(sugItems[sugIdx]); return; }
    if(e.key==='Tab' && sugIdx>=0){ e.preventDefault(); pickSug(sugItems[sugIdx]); return; }
    if(e.key==='Escape'){ hideSuggest(); return; }
  }
});

// 服务连接状态：实时指示 + 断开时显示启动指引
function setConn(ok){
  var c=$('conn');
  if(ok){ c.textContent='● 已连接'; c.className='conn ok'; $('downBanner').classList.remove('show'); }
  else { c.textContent='● 未连接'; c.className='conn bad'; $('downBanner').classList.add('show'); }
}
function checkConn(){
  fetch('/ping',{cache:'no-store'}).then(function(r){return r.ok?r.json():Promise.reject();})
    .then(function(){ setConn(true); }).catch(function(){ setConn(false); });
}
$('copyCmd').onclick=function(){
  var t=$('cmdLine').textContent;
  if(navigator.clipboard&&navigator.clipboard.writeText){
    navigator.clipboard.writeText(t).then(function(){toast('已复制启动命令');},function(){toast('复制失败，请手动复制');});
  } else { toast('复制失败，请手动复制'); }
};

// 图表点击放大（lightbox，支持滚轮缩放 + 拖拽平移 + 双击还原，地图模式）
var lbScale=1, lbX=0, lbY=0, lbDrag=false, lbSX=0, lbSY=0, lbMoved=false, lbPID=null;
function applyLb(){ $('lbImg').style.transform='translate('+lbX+'px,'+lbY+'px) scale('+lbScale+')'; }
function resetLb(){ lbScale=1; lbX=0; lbY=0; lbMoved=false; applyLb(); }
function openLb(src){ var im=$('lbImg'); im.src=src; resetLb(); $('lb').classList.add('show'); }
function closeLb(){ $('lb').classList.remove('show'); }
$('lb').addEventListener('click', function(e){ if(e.target.id!=='lbImg') closeLb(); });
document.addEventListener('keydown', function(e){
  if(e.key!=='Escape') return;
  if($('dirModal').classList.contains('show')){ closeDirPicker(); return; }
  closeLb();
});
document.querySelectorAll('img.chart').forEach(function(im){ im.onclick=function(){ openLb(im.src); }; });
var lbImg=$('lbImg');
lbImg.draggable=false;
// 用 Pointer 事件 + 指针捕获，彻底避免与浏览器原生拖拽/选中冲突；指针捕获保证即便在窗口外松开也能可靠结束拖拽
lbImg.addEventListener('pointerdown', function(e){
  lbDrag=true; lbMoved=false; lbSX=e.clientX-lbX; lbSY=e.clientY-lbY; lbPID=e.pointerId;
  try{ lbImg.setPointerCapture(lbPID); }catch(_){}
  lbImg.style.cursor='grabbing'; e.preventDefault();
});
lbImg.addEventListener('pointermove', function(e){
  if(!lbDrag) return;
  var dx=e.clientX-lbSX, dy=e.clientY-lbSY;
  if(Math.abs(dx)>3||Math.abs(dy)>3) lbMoved=true;
  lbX=dx; lbY=dy; applyLb();
});
function lbEndDrag(){ if(!lbDrag) return; lbDrag=false; lbImg.style.cursor='grab'; try{ lbImg.releasePointerCapture(lbPID); }catch(_){} }
lbImg.addEventListener('pointerup', lbEndDrag);
lbImg.addEventListener('pointercancel', lbEndDrag);
lbImg.addEventListener('dblclick', function(e){ e.preventDefault(); resetLb(); });
lbImg.addEventListener('wheel', function(e){
  e.preventDefault();
  var factor = e.deltaY<0 ? 1.12 : 1/1.12;
  var rect=lbImg.getBoundingClientRect();
  var cx=e.clientX-rect.left, cy=e.clientY-rect.top;
  var newScale=Math.min(8, Math.max(0.5, lbScale*factor));
  lbX = cx - (cx - lbX) * (newScale/lbScale);
  lbY = cy - (cy - lbY) * (newScale/lbScale);
  lbScale=newScale; applyLb();
}, {passive:false});

// 记忆上次扫描目标：页面打开默认回填（磁盘/目录快照）
var LAST_TARGET = __LAST_TARGET__;
function applyLast(){
  if(!LAST_TARGET) return;
  if(LAST_TARGET.disk){ var sel=$('driveSel'); var has=[].slice.call(sel.options).some(function(o){return o.value===LAST_TARGET.disk;}); if(has) sel.value=LAST_TARGET.disk; }
  if(LAST_TARGET.path){
    var p=LAST_TARGET.path.replace(/\//g,'\\');
    var m=p.match(/^([A-Za-z]):\\?/);
    if(m){ var drv=m[1].toUpperCase()+':\\'; var sel2=$('driveSel'); var has2=[].slice.call(sel2.options).some(function(o){return o.value===drv;}); if(has2) sel2.value=drv; p=p.slice(2).replace(/^\\+/,''); }
    $('dirpath').value=p;
  }
  toggleClear(); hideSuggest();
}

buildDrives();
mountDD('driveSel','ddWrap','ddBtn','ddLabel','ddList');
mountDD('mDrive','mDD','mDDBtn','mDDLabel','mDDList');
applyLast();
// 打开页面即还原「上次扫描完整快照」（图表+明细+报告），无需重新扫描
fetch('/last',{cache:'no-store'}).then(function(r){return r.ok?r.json():null;})
  .then(function(d){ if(d && d.nodes && d.nodes.length){ render(d); setConn(true); } })
  .catch(function(){});
checkConn();
setInterval(checkConn, 5000);

</script>
</body></html>"""


# ---------------------------------------------------------------------------
# HTTP 服务
# ---------------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # 静默
        pass

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(u.query)
        if u.path in ("/", "/index.html"):
            # 动态生成启动命令：脚本真实路径 + 当前端口，避免写死用户绝对路径
            start_cmd = 'python "%s" --port %d' % (os.path.abspath(__file__), _SERVER_PORT)
            last = _load_last() or {}
            body = PAGE.replace("__START_CMD__", start_cmd).replace(
                "__LAST_TARGET__", json.dumps(last, ensure_ascii=False)).replace(
                "__VERSION__", VERSION)
            self._send(200, body, "text/html; charset=utf-8")
        elif u.path == "/favicon.ico":
            self._send(204, b"")
        elif u.path == "/ping":
            self._send(200, json.dumps({"ok": True}, ensure_ascii=False))
        elif u.path == "/last":
            try:
                with open(LAST_RESULT_PATH, "r", encoding="utf-8") as f:
                    body = f.read()
                self._send(200, body, "application/json; charset=utf-8")
            except Exception:
                self._send(204, b"")
        elif u.path == "/scan":
            self.handle_scan(qs)
        elif u.path == "/cancel":
            sid = qs.get("id", [""])[0]
            p = SCANS.get(sid)
            if p:
                p["cancel"] = True
            self._send(200, json.dumps({"ok": bool(p)}, ensure_ascii=False))
        elif u.path == "/open":
            p = qs.get("path", [""])[0]
            ok = open_folder(p)
            self._send(200, json.dumps({"ok": ok, "path": p}, ensure_ascii=False))
        elif u.path == "/suggest":
            handle_suggest(self, qs)
        elif u.path == "/browse":
            handle_browse(self, qs)
        else:
            self._send(404, json.dumps({"error": "not found"}, ensure_ascii=False))

    def handle_scan(self, qs):
        disk = qs.get("disk", [None])[0]
        path = qs.get("dir", [None])[0]
        depth = int(qs.get("depth", ["2"])[0])
        top = int(qs.get("top", ["15"])[0])
        if path:
            if not path.endswith("\\"):
                path += "\\"
        elif disk:
            if not disk.endswith("\\"):
                disk += "\\"

        sid = uuid.uuid4().hex
        progress = {
            "sid": sid, "phase": "准备中…", "current": "", "done": 0, "total": 0,
            "cancel": False, "done_flag": False, "start": time.time(), "error": None,
        }
        SCANS[sid] = progress

        def worker():
            try:
                if path:
                    resp = build_response(path=path, depth=depth, top=top, progress=progress, record=not progress["cancel"])
                else:
                    resp = build_response(disk=disk, depth=depth, top=top, progress=progress, record=not progress["cancel"])
                if progress["cancel"]:
                    resp["cancelled"] = True
                progress["result"] = resp
            except Exception as e:
                progress["error"] = str(e)
            progress["done_flag"] = True

        threading.Thread(target=worker, daemon=True).start()

        # SSE 流式推送进度
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        try:
            while True:
                if progress["done_flag"]:
                    if progress["error"]:
                        payload = json.dumps({"error": progress["error"]}, ensure_ascii=False)
                        self.wfile.write(("event: error\ndata: " + payload + "\n\n").encode("utf-8"))
                    else:
                        payload = json.dumps(progress["result"], ensure_ascii=False)
                        self.wfile.write(("event: done\ndata: " + payload + "\n\n").encode("utf-8"))
                    break
                snap = {
                    "sid": progress["sid"], "phase": progress.get("phase", ""),
                    "current": progress.get("current", ""), "done": progress.get("done", 0),
                    "total": progress.get("total", 0), "elapsed": round(time.time() - progress["start"], 1),
                }
                self.wfile.write(("event: progress\ndata: " + json.dumps(snap, ensure_ascii=False) + "\n\n").encode("utf-8"))
                self.wfile.flush()
                time.sleep(0.25)
        except (BrokenPipeError, ConnectionResetError):
            progress["cancel"] = True
        finally:
            SCANS.pop(sid, None)


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8780)
    ap.add_argument("--host", default="127.0.0.1")
    args = ap.parse_args()
    global _SERVER_HOST, _SERVER_PORT
    _SERVER_HOST, _SERVER_PORT = args.host, args.port
    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"[disk_analyzer_web] 已启动：http://{args.host}:{args.port}/")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[退出]")
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
