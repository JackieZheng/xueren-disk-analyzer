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


# ---------------------------------------------------------------------------
# 扫描数据 → 响应 JSON
# ---------------------------------------------------------------------------

def build_response(disk=None, path=None, depth=2, top=15, progress=None):
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
        total, children, files_size = da.scan_top(path, progress)
        nodes = []
        for sub, sz in children.items():
            nodes.append({"name": sub, "label": sub, "size": sz, "children": [],
                          "is_file": False, "path": os.path.join(path, sub)})
        if files_size > 0:
            nodes.append({"name": "（该层文件）", "label": "（该层文件）",
                          "size": files_size, "children": [], "is_file": True, "path": None})
        nodes.sort(key=lambda x: x["size"], reverse=True)
        data = {"drive": path, "depth": depth, "scan_time": 0,
                "total_bytes": None, "free_bytes": None, "scanned_bytes": total,
                "nodes": nodes, "top": top}
        capacity = None
        scanned = total

    if progress is not None:
        progress["phase"] = "正在生成图表…"
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
        })

    return {
        "drive": data["drive"],
        "drives": da.list_fixed_drives(),
        "depth": depth, "top": top, "scan_time": data["scan_time"],
        "capacity": capacity, "scanned": scanned,
        "charts": {"treemap": ct, "bar": cb, "donut": cd},
        "nodes": tnodes,
    }


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


# ---------------------------------------------------------------------------
# 网页（实时进度面板风格，深色 + 绿/橙主题）
# ---------------------------------------------------------------------------

PAGE = r"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>磁盘空间分析器</title>
<style>
:root{--bg:#0f1720;--card:#16212c;--line:#27384a;--tx:#e8eef5;--sub:#93a7bb;
--acc:#3fb27f;--acc2:#e0a13a;--bad:#d9534f;--ink:#111a23}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--tx);font:14px/1.6 "Microsoft YaHei",system-ui,-apple-system,sans-serif;padding:clamp(10px,2.6vw,20px)}
.topbar{background:linear-gradient(135deg,#13202b,#1b2b38);border-bottom:1px solid var(--line);padding:14px clamp(12px,2.2vw,22px)}
.topbar h1{margin:0;font-size:19px;display:flex;align-items:center;gap:9px}
.topbar .hicon{font-size:20px}
.sub{color:var(--sub);font-size:12px;margin-top:5px;word-break:break-word}
.wrap{max-width:1200px;margin:0 auto;padding:0 clamp(4px,1vw,8px)}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:14px;margin-top:14px;overflow:hidden}
.pin{border-color:#3a5a48;background:linear-gradient(135deg,#16241d,#172a22)}
.pin b{color:var(--acc)}
.toolbar{display:flex;flex-wrap:wrap;align-items:center;gap:10px;margin-top:14px}
.toolbar .lbl{color:var(--sub);font-size:13px}
select,input,button{font-family:inherit}
#driveSel{background:var(--ink);border:1px solid var(--line);border-radius:10px;color:var(--tx);padding:7px 11px;font-size:13px}
#dirpath{flex:1 1 240px;min-width:180px;background:var(--ink);border:1px solid var(--line);border-radius:10px;color:var(--tx);padding:7px 11px;font-size:13px}
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
.stat{background:var(--ink);border:1px solid var(--line);border-radius:10px;padding:9px 14px;min-width:120px;flex:1 1 120px}
.stat .k{color:var(--sub);font-size:11px}
.stat .v{font-size:19px;font-weight:700;margin-top:3px;color:var(--tx);font-variant-numeric:tabular-nums}
.stat .v.warn{color:var(--acc2)}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:14px;margin-top:14px}
.ct{font-size:14px;color:var(--tx);font-weight:600;margin-bottom:9px}
.ct .hint{color:var(--sub);font-weight:400;font-size:12px}
.chart{width:100%;height:auto;display:block;border-radius:10px;background:var(--ink)}
table{width:100%;border-collapse:collapse;background:var(--card);border:1px solid var(--line);border-radius:12px;overflow:hidden;margin-top:8px}
th,td{padding:10px 12px;text-align:left;border-bottom:1px solid var(--line);font-size:13px}
th{background:#1b2a36;color:var(--sub);cursor:pointer;user-select:none;white-space:nowrap}
th:hover{color:var(--tx)}
th.asc::after{content:" ▲";color:var(--acc)}
th.desc::after{content:" ▼";color:var(--acc)}
td.num{text-align:right;font-variant-numeric:tabular-nums}
td.nm{max-width:440px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
tbody tr{cursor:pointer;transition:.12s}
tbody tr:hover{background:#1c2c38}
.tag{background:var(--acc2);color:#2a1c05;font-size:11px;padding:1px 6px;border-radius:6px;margin-left:4px}
.actbtn{border:1px solid var(--line);background:var(--ink);color:var(--sub);border-radius:8px;padding:2px 9px;cursor:pointer;font-size:13px}
.actbtn:hover{color:var(--acc);border-color:var(--acc)}
.area{display:none}
.area.show{display:block}
.empty{text-align:center;color:var(--sub);padding:34px 12px}
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
</style></head>
<body>
<div class="topbar"><div class="wrap">
  <h1><span class="hicon">📊</span> 磁盘空间分析器</h1>
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
    <select id="driveSel"></select>
    <span class="lbl">目录：</span>
    <input id="dirpath" placeholder="或点右侧「选择目录」自动填入绝对路径" />
    <button id="pickBtn" class="btn">📁 选择目录</button>
    <input id="pickdir" type="file" webkitdirectory directory multiple style="display:none">
    <button id="goBtn" class="btn go">▶ 开始分析</button>
    <button id="stopBtn" class="btn stop" style="display:none">⏹ 停止</button>
    <span class="grow"></span>
  </div>
  <div class="hintbar">提示：先选盘符（C/D/E/F），再点「选择目录」用系统对话框选文件夹，路径会自动拼好；也可直接手填。点「开始分析」即扫描。</div>

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
      <div class="card"><div class="ct">① 矩形树图 Treemap（面积=体积）</div><img id="imgtm" class="chart" alt="treemap"></div>
      <div class="card"><div class="ct">② Top N 横向条形图</div><img id="imgbar" class="chart" alt="bar"></div>
      <div class="card"><div class="ct">③ 环形占比图</div><img id="imgdonut" class="chart" alt="donut"></div>
    </div>
  </div>

  <div id="tablewrap" class="area">
    <div class="card">
      <div class="ct">📋 目录明细 <span class="hint">（点击表头排序 · 点击行打开所在目录）</span></div>
      <table id="tbl"><thead><tr>
        <th data-k="idx">#</th><th data-k="name">目录</th>
        <th data-k="size">大小</th><th data-k="pct">占磁盘%</th>
        <th data-k="cnt">子项</th><th data-k="act">操作</th>
      </tr></thead><tbody id="tbody"></tbody></table>
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

function buildDrives(){
  // 盘符下拉：先用常见盘符占位，/scan 首次返回后刷新真实列表
  var opts=['C:\\','D:\\','E:\\','F:\\'];
  var sel=$('driveSel'); sel.innerHTML='';
  opts.forEach(function(d){var o=document.createElement('option');o.value=d;o.textContent=d.charAt(0)+':';sel.appendChild(o);});
}
function refreshDrives(drives){
  if(!drives||!drives.length) return;
  var sel=$('driveSel');
  var cur=sel.value;
  sel.innerHTML='';
  drives.forEach(function(d){var o=document.createElement('option');o.value=d;o.textContent=d.charAt(0)+':';sel.appendChild(o);});
  if(cur) sel.value=cur;
}

function startScan(){
  var drive=$('driveSel').value;
  var dir=$('dirpath').value.trim();
  var q = dir ? ('dir='+encodeURIComponent(dir)) : ('disk='+encodeURIComponent(drive));
  if(state.es) state.es.close();
  // 先确认服务在线：否则明确提示，避免「开始」静默失效
  fetch('/ping',{cache:'no-store'}).then(function(r){return r.ok?r.json():Promise.reject();})
    .then(function(){ enterScanUI(); openSSE(q); })
    .catch(function(){ setConn(false); toast('服务未连接，请先启动服务（见上方提示）'); });
}
function enterScanUI(){
  $('empty').classList.remove('show');
  $('charts').classList.remove('show');
  $('tablewrap').classList.remove('show');
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
    st.innerHTML=statCard('总容量',human(c.total))+statCard('已用',human(c.used))
      +statCard('剩余',human(c.free))+statCard('使用率',(c.pct!=null?c.pct.toFixed(1):'—')+'%',pctcls);
  } else { st.innerHTML=statCard('扫描合计',human(d.scanned)); }
  $('imgtm').src='data:image/png;base64,'+d.charts.treemap;
  $('imgbar').src='data:image/png;base64,'+d.charts.bar;
  $('imgdonut').src='data:image/png;base64,'+d.charts.donut;
  var tb=$('tbody'); tb.innerHTML='';
  d.nodes.forEach(function(n,i){
    var tr=document.createElement('tr');
    tr.dataset.idx=i+1; tr.dataset.name=n.label; tr.dataset.size=n.size;
    tr.dataset.pct=n.pct; tr.dataset.cnt=n.cnt; tr.dataset.path=n.path||'';
    var tag=n.is_file?' <span class="tag">文件</span>':'';
    var act=n.path?'<button class="actbtn" title="打开目录">📂</button>':'';
    tr.innerHTML='<td>'+ (i+1) +'</td><td class="nm" title="'+esc(n.path||n.label)+'">'+esc(midEllipsis(n.label, 46))+tag+'</td>'
      +'<td class="num">'+n.size_human+'</td><td class="num">'+n.pct.toFixed(1)+'%</td>'
      +'<td class="num">'+n.cnt+'</td><td class="num act">'+act+'</td>';
    tr.onclick=function(e){ if(e.target.closest('.actbtn'))return; if(n.path) openFolder(n.path); };
    var ab=tr.querySelector('.actbtn'); if(ab) ab.onclick=function(e){e.stopPropagation(); if(n.path) openFolder(n.path);};
    tb.appendChild(tr);
  });
  applySort();
}
function statCard(k,v,cls){return '<div class="stat"><div class="k">'+k+'</div><div class="v '+(cls||'')+'">'+v+'</div></div>';}

function applySort(){
  var tb=$('tbody'); var rows=[].slice.call(tb.querySelectorAll('tr'));
  var k=state.sortKey, asc=state.sortAsc;
  rows.sort(function(a,b){
    var va,vb;
    if(k==='name'){va=a.dataset.name;vb=b.dataset.name;return asc?va.localeCompare(vb,'zh'):vb.localeCompare(va,'zh');}
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

$('goBtn').onclick=startScan;
$('stopBtn').onclick=stopScan;
$('pickBtn').onclick=function(){ $('pickdir').click(); };
$('pickdir').onchange=function(){
  var f=this.files; if(!f||!f.length) return;
  var rel=f[0].webkitRelativePath||f[0].name;
  var root=rel.split('/')[0].split('\\')[0];
  var drv=$('driveSel').value; // 已选盘符
  $('dirpath').value = drv + root;
  toast('已选择目录：'+drv+root);
};

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

buildDrives();
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
            body = PAGE.replace("__START_CMD__", start_cmd)
            self._send(200, body, "text/html; charset=utf-8")
        elif u.path == "/favicon.ico":
            self._send(204, b"")
        elif u.path == "/ping":
            self._send(200, json.dumps({"ok": True}, ensure_ascii=False))
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
                    resp = build_response(path=path, depth=depth, top=top, progress=progress)
                else:
                    resp = build_response(disk=disk, depth=depth, top=top, progress=progress)
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
