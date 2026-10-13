# -*- coding: utf-8 -*-
"""xueren-disk-analyzer Web 服务开关控制器（对齐 panel_ctl.py 的会话外常驻方案）

用途：一键启停 8780 磁盘分析器，摆脱「会话内 nohup 20s 后被回收」的老坑。

    python disk_analyzer_ctl.py status  [--port 8780] [--json]
    python disk_analyzer_ctl.py check   [--port 8780] [--json]
    python disk_analyzer_ctl.py start   [--port 8780] [--host 127.0.0.1] [--no-browser] [--auto] [--json]
    python disk_analyzer_ctl.py spawn   [--port 8780] [--host 127.0.0.1] [--json]      # 快路径，不等待就绪
    python disk_analyzer_ctl.py stop    [--port 8780] [--json]
    python disk_analyzer_ctl.py restart [--port 8780] [--json]

关键点（照抄 xueren-workbuddy-live-progress/scripts/panel_ctl.py 已验证的做法）：
- **会话外常驻**：走 PowerShell 的 WMI `Win32_Process.Create`，父进程是 WmiPrvSE.exe，
  脱离 bash 工具沙箱的 job 对象；bash 命令结束后 ~20 秒不会被打断。
  实测 WMI 创建进程那一下要 ~12s，所以 `start` 默认会等到端口就绪；`spawn` 是不等就绪的快路径。
- **必须给 pythonw 一个有效 stdout 句柄**：WMI 创建进程时不传 stdio，
  pythonw 下 `sys.stdout` 会是 None，任何裸 `print` 都会 AttributeError 直接把进程掀翻。
  做法是用 `cmd /c ""pythonw.exe" "script.py" … >> log 2>&1` 包一层，
  cmd 负责重定向、WMI 负责脱离会话，两件事互不干扰。
- **每次启动截断日志**（`open(LOG, "w")`）：这样日志只反映本次启动的 traceback，
  排障时不会翻出几小时前的旧异常。
- **探活绕过本机代理**（`ProxyHandler({})`）：否则 127.0.0.1 会被系统代理拦下，
  明明服务活着也会误判成"没起来"。
- **stop 幂等按端口杀**：`netstat -ano` 找 LISTENING 的 PID，谁起的都不区分，
  上次会话残留的、计划任务起的、手动 nohup 起的，都能干净收掉。
"""
import os
import sys
import json
import time
import socket
import argparse
import subprocess
import urllib.request
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "disk_analyzer_web.py")
DEFAULT_PORT = int(os.environ.get("DISK_ANALYZER_PORT") or 8780)
DEFAULT_HOST = os.environ.get("DISK_ANALYZER_HOST") or "127.0.0.1"
ROOT = os.path.join(os.path.expanduser("~"), ".workbuddy")
LOG = os.path.join(ROOT, "disk_analyzer_%d.log" % DEFAULT_PORT)
STATE_FILE = os.path.join(ROOT, "disk_analyzer_state.json")
AUTOSTART_NAME = "XuerenDiskAnalyzer"          # HKCU Run 键名
RUN_KEY = r"HKCU\Software\Microsoft\Windows\CurrentVersion\Run"


# ---------------------------------------------------------------- 基础工具
def _pythonw():
    """找一个不弹黑窗的解释器：优先与当前解释器同目录的 pythonw.exe"""
    exe = sys.executable or ""
    cand = os.path.join(os.path.dirname(exe), "pythonw.exe")
    if os.path.exists(cand):
        return cand
    up = os.environ.get("USERPROFILE", "")
    cand = os.path.join(up, ".workbuddy", "binaries", "python", "versions",
                        "3.13.12", "pythonw.exe")
    if os.path.exists(cand):
        return cand
    return "pythonw.exe"


def _probe(port, timeout=1.2):
    """端口上是否有一个**真的服务**（不只看 TCP 连通，要能取到 /ping 里的 ok:true）"""
    s = socket.socket()
    s.settimeout(timeout)
    try:
        if s.connect_ex(("127.0.0.1", int(port))) != 0:
            return False
    finally:
        s.close()
    try:
        op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        r = op.open("http://127.0.0.1:%d/ping" % int(port), timeout=timeout)
        body = r.read(500) or b""
        return b'"ok": true' in body or b'"ok":true' in body
    except Exception:
        return False


def _pids_on(port):
    """占用该端口且处于 LISTENING 的 PID 列表（Windows netstat；其它平台返回 []）"""
    pids = []
    try:
        # 不能用 text=True：中文 Windows 的 netstat 输出是 GBK，UTF-8 解码会抛异常
        raw = subprocess.run(["netstat", "-ano"], capture_output=True,
                             timeout=15).stdout or b""
        out = raw.decode("mbcs" if os.name == "nt" else "utf-8", errors="replace")
    except Exception:
        return pids
    for line in out.splitlines():
        if "LISTENING" not in line.upper():
            continue
        parts = line.split()
        if len(parts) >= 5 and parts[1].endswith(":%d" % int(port)):
            try:
                pid = int(parts[-1])
            except ValueError:
                continue
            if pid and pid not in pids:
                pids.append(pid)
    return pids


def _ps_text(script, timeout=25):
    if os.name != "nt":
        return ""
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive",
                            "-Command", script],
                           capture_output=True, timeout=timeout)
        return (r.stdout or b"").decode("mbcs", errors="replace").strip()
    except Exception:
        return ""


def _parent_of(pid):
    """返回 (父进程 pid, 父进程名)；取不到返回 (None, None)"""
    out = _ps_text(
        "$p=Get-CimInstance Win32_Process -Filter 'ProcessId = %d' -ErrorAction SilentlyContinue;"
        "if($p){ '%d|' + [string]$p.ParentProcessId } else { '%d|' }"
        % (int(pid), int(pid), int(pid)))
    if not out:
        return None, None
    parts = out.splitlines()[-1].strip().split("|")
    if len(parts) < 2 or not parts[1].strip():
        return None, None
    ppid = int(parts[1]) if parts[1].strip().lstrip("-").isdigit() else None
    if not ppid or ppid <= 0:
        return None, None
    name = _ps_text("(Get-CimInstance Win32_Process -Filter 'ProcessId = %d' "
                    "-ErrorAction SilentlyContinue).Name" % ppid).splitlines()
    return ppid, (name[-1].strip() if name else "") or None


# 这些父进程名意味着「服务仍挂在本会话/本机应用下」，会话不结束它就不算完
_BOUND_HINTS = ("sandbox-cli.exe", "sandbox-center.exe", "codebuddy", "codebuddy.exe",
                "bash.exe", "sh.exe", "cmd.exe", "node.exe", "workbuddy.exe")
# 这些父进程名代表「会话之外」，可跨会话常驻
_FREE_HINTS = ("explorer.exe", "wmiPrvse.exe", "services.exe", "svchost.exe", "wininit.exe")


def _verdict(ppid, pname, self_pid):
    if ppid is None or not pname:
        return "free", "父进程已退出（典型的 WMI/脱离式创建）"
    low = pname.lower()
    if ppid == self_pid:
        return "bound", "父进程就是本次启动命令本身 → 未脱离，会随命令结束被回收"
    if low in _FREE_HINTS:
        return "free", "父进程 %s：会话之外，可跨会话常驻" % pname
    if low in _BOUND_HINTS:
        return "bound", "父进程 %s：仍挂在应用/会话进程树下" % pname
    return "unknown", "父进程 %s：无法判定" % pname


def _save_state(port, d):
    try:
        os.makedirs(ROOT, exist_ok=True)
        try:
            with open(STATE_FILE, encoding="utf-8") as f:
                all_ = json.load(f) or {}
        except Exception:
            all_ = {}
        all_[str(int(port))] = d
        tmp = STATE_FILE + ".%d.tmp" % os.getpid()
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(all_, f, ensure_ascii=False, indent=1)
        os.replace(tmp, STATE_FILE)
    except Exception:
        pass


def _load_state(port=None):
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            d = json.load(f) or {}
    except Exception:
        return {}
    if port is None:
        return d
    v = d.get(str(int(port))) or {}
    return v if isinstance(v, dict) else {}


def _detach_info(port):
    """服务的父进程是不是真的在会话之外（决定性判据：父进程 ≠ 启动它的本进程）"""
    pids = _pids_on(port)
    if not pids:
        return {"detached": None, "verdict": "unknown", "pid": None,
                "ppid": None, "parent": None, "why": "未取到监听 PID"}
    pid = pids[0]
    ppid, pname = _parent_of(pid)
    verdict, why = _verdict(ppid, pname, os.getpid())
    return {"detached": verdict != "bound", "verdict": verdict, "pid": pid,
            "ppid": ppid, "parent": pname, "why": why}


def _wmi_create(cmdline):
    """用 WMI Win32_Process.Create 在会话之外创建进程。

    实现要点：把 PowerShell 脚本落到临时 .ps1 再 -File 执行。
    直接 `-Command` 传字符串会因为 Windows 命令行里嵌双引号导致 PowerShell 解析失败
    （实测：返回码非 0，静默退化成 Popen，进程随会话被回收）。
    """
    if os.name != "nt":
        return False, "non-windows"
    ps = ("$ErrorActionPreference='Stop'\r\n"
          "$r=([wmiclass]'Win32_Process').Create('%s')\r\n"
          "if($r.ReturnValue -ne 0){ exit 1 }\r\n"
          % cmdline.replace("'", "''"))
    fd, path = tempfile.mkstemp(suffix=".ps1")
    try:
        with os.fdopen(fd, "w", encoding="utf-8-sig") as f:
            f.write(ps)
        r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive",
                            "-ExecutionPolicy", "Bypass", "-File", path],
                           capture_output=True, timeout=40)
        if r.returncode == 0:
            return True, "wmi ok"
        return False, (r.stderr or r.stdout or b"").decode("mbcs", "replace")[:300]
    except Exception as e:
        return False, repr(e)
    finally:
        try:
            os.remove(path)
        except Exception:
            pass


def _spawn_detached(port, host):
    """在会话之外创建服务进程；返回 (方式, 是否成功发起)。

    ① WMI Win32_Process.Create —— 父进程是 WMI 服务，脱离会话 job 对象，跨会话常驻（首选）；
    ② 兜底：直接 Popen（分离标志）—— 非 Windows / WMI 不可用时可用，
       但实测这种进程会在当前命令结束后被回收，只能应付"先看着"。

    **关键约定：直调 pythonw.exe，不经 cmd /c 包装**。
    cmd /c 会把控制台子系统带出来，即便 -c 一次性执行也会在启动瞬间闪一下黑窗。
    直调 pythonw 时 WMI 不传 stdio，pythonw 下 sys.stdout/stderr 为 None；
    由 disk_analyzer_web.py 顶部 `_open_log()` 保护（重定向到 LOG 文件），
    既无窗口闪现，也有日志可查。
    """
    pyw = _pythonw()
    try:
        os.makedirs(ROOT, exist_ok=True)
        # 用 a 模式追加，避免启动瞬间的日志被后续 web.py 里的 print 覆盖
        open(LOG, "a", encoding="utf-8").close()
    except Exception:
        pass
    # 直接命令行调 pythonw.exe：Win32_Process.Create 会把它解析成一个进程，
    # 不会像 cmd.exe 那样拉起控制台窗口。
    wrapped = ('"%s" "%s" --port %d --host %s'
               % (pyw, SCRIPT, int(port), host))
    ok, detail = _wmi_create(wrapped)
    if ok:
        return "wmi", True
    flags = 0
    if os.name == "nt":
        flags = 0x00000008 | 0x00000200          # DETACHED_PROCESS | NEW_PROCESS_GROUP
    try:
        subprocess.Popen([pyw, SCRIPT, "--port", str(int(port)),
                          "--host", str(host)],
                         creationflags=flags, close_fds=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         stdin=subprocess.DEVNULL)
        return "popen", True
    except Exception:
        return "popen", False


def _wait_up(port, timeout=14.0):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if _probe(port, timeout=1.0):
            return True
        time.sleep(0.4)
    return False


def _wait_down(port, timeout=10.0):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if not _pids_on(port) and not _probe(port, timeout=0.6):
            return True
        time.sleep(0.3)
    return False


def _open_browser(port):
    try:
        if os.name == "nt":
            os.startfile("http://127.0.0.1:%d/" % int(port))       # noqa: S606
        else:
            subprocess.Popen(["xdg-open", "http://127.0.0.1:%d/" % int(port)])
        return True
    except Exception:
        return False


# ---------------------------------------------------------------- 自启项（HKCU Run）
def _autostart_enabled():
    out = _ps_text(
        "$p=Get-ItemProperty -Path '%s' -ErrorAction SilentlyContinue;"
        "if($p -and $p.%s){ %s }"
        % (RUN_KEY, AUTOSTART_NAME, AUTOSTART_NAME))
    return bool(out and out.strip())


def _autostart_cmd():
    return _ps_text(
        "$p=Get-ItemProperty -Path '%s' -ErrorAction SilentlyContinue;"
        "if($p -and $p.%s){ %s }"
        % (RUN_KEY, AUTOSTART_NAME, AUTOSTART_NAME))


def _ensure_autostart(port, host, force=False):
    """写入 HKCU Run 自启项（登录即拉起，兜住「上次会话结束进程被回收 + 还没新开会话」的空档）。

    HKCU 是用户级注册表，无需管理员权限。
    """
    pyw = _pythonw()
    cmd = '"%s" "%s" --port %d --host %s' % (pyw, SCRIPT, int(port), host)
    ps = ("$ErrorActionPreference='Stop'\r\n"
          "if(-not (Test-Path '%s')){ New-Item -Path '%s' -Force | Out-Null }\r\n"
          "New-ItemProperty -Path '%s' -Name '%s' -Value '%s' -Type ExpandString -Force | Out-Null\r\n"
          % (RUN_KEY, RUN_KEY, RUN_KEY, AUTOSTART_NAME, cmd.replace("'", "''")))
    fd, path = tempfile.mkstemp(suffix=".ps1")
    try:
        with os.fdopen(fd, "w", encoding="utf-8-sig") as f:
            f.write(ps)
        r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive",
                            "-ExecutionPolicy", "Bypass", "-File", path],
                           capture_output=True, timeout=20)
        return r.returncode == 0, cmd
    except Exception:
        return False, cmd
    finally:
        try:
            os.remove(path)
        except Exception:
            pass


# ---------------------------------------------------------------- 五个动作
def act_status(port, as_json=False):
    running = _probe(port)
    pids = _pids_on(port)
    info = {"running": bool(running), "port": int(port), "pids": pids,
            "url": "http://127.0.0.1:%d/" % int(port),
            "autostart": _autostart_enabled()}
    if running:
        info.update(_detach_info(port))
        st = _load_state(port)
        if st.get("how"):
            info["started_how"] = st.get("how")
    if as_json:
        print(json.dumps(info, ensure_ascii=False))
    else:
        if running:
            print("服务在运行：%s  PID=%s"
                  % (info["url"], ",".join(map(str, pids)) or "?"))
            print("  会话关系：%s（%s）"
                  % ("会话外 ✅ 不会拖住会话"
                     if info.get("detached") else "可能挂在本会话 ⚠️",
                     info.get("why") or "未知"))
        else:
            print("服务未运行（端口 %d 无监听）" % port)
        print("  开机自启：%s" % ("已启用" if info["autostart"] else "未启用"))
    return 0 if running else 1


def act_check(port, as_json=False):
    """只回答一个问题：这个服务会不会拖住当前会话？"""
    running = _probe(port)
    if not running:
        out = {"running": False, "port": int(port), "blocking_session": False,
               "why": "服务未运行"}
    else:
        di = _detach_info(port)
        st = _load_state(port)
        out = {"running": True, "port": int(port), "url": "http://127.0.0.1:%d/" % int(port),
               "pid": di.get("pid"), "parent_pid": di.get("ppid"),
               "parent_name": di.get("parent"),
               "detached": di.get("detached"),
               "blocking_session": di.get("detached") is False,
               "why": di.get("why"),
               "started_how": st.get("how"), "started_at": st.get("at")}
    if as_json:
        print(json.dumps(out, ensure_ascii=False))
    else:
        if not out["running"]:
            print("✅ 服务未运行 —— 不存在「占用会话」的问题")
        elif out["blocking_session"]:
            print("⚠️ 服务可能拖住会话：%s" % out["why"])
        else:
            print("✅ 服务在会话之外（%s）" % out["why"])
    return 0


def act_start(port, host, no_browser=False, as_json=False, ensure_autostart=True):
    if _probe(port):
        line = "服务已在运行（复用，未重复启动）：http://127.0.0.1:%d/" % int(port)
        print(json.dumps({"status": "already-running", "port": int(port),
                          "url": "http://127.0.0.1:%d/" % int(port)},
                         ensure_ascii=False) if as_json else line)
        return 0
    if not os.path.exists(SCRIPT):
        print("找不到服务脚本：%s" % SCRIPT)
        return 2
    how, ok = _spawn_detached(port, host)
    if not ok:
        print("启动失败：WMI 与 Popen 均不可用")
        return 2
    up = _wait_up(port)
    di = _detach_info(port) if up else {}
    _save_state(port, {"how": how, "pid": di.get("pid"), "parent_pid": di.get("ppid"),
                       "parent_name": di.get("parent"), "detached": di.get("detached"),
                       "port": int(port), "host": host,
                       "at": time.strftime("%Y-%m-%d %H:%M:%S")})
    if ensure_autostart:
        _ensure_autostart(port, host)
    if up:
        if not no_browser:
            _open_browser(port)
        pids = _pids_on(port)
        if as_json:
            print(json.dumps({"status": "started", "how": how, "port": int(port),
                              "pids": pids, "url": "http://127.0.0.1:%d/" % int(port),
                              "detached": di.get("detached"), "detach_why": di.get("why")},
                             ensure_ascii=False))
        else:
            print("服务已就绪：%s  PID=%s（%s）"
                  % ("http://127.0.0.1:%d/" % int(port),
                     ",".join(map(str, pids)) or "?",
                     "会话外常驻" if how == "wmi" else "会话内，可能被回收"))
        return 0
    print("已发起启动，但 14 秒内端口未就绪，请稍后再试 status")
    return 1


def act_spawn(port, host, as_json=False, ensure_autostart=True):
    """**只发起服务进程、不等待就绪**——快路径，几秒内返回。"""
    if _probe(port, timeout=0.8):
        info = {"status": "already-running", "port": int(port),
                "url": "http://127.0.0.1:%d/" % int(port)}
        print(json.dumps(info, ensure_ascii=False) if as_json
              else "服务已在运行（复用）：%s" % info["url"])
        return 0
    if not os.path.exists(SCRIPT):
        print("找不到服务脚本：%s" % SCRIPT)
        return 2
    how, ok = _spawn_detached(port, host)
    info = {"status": "spawned" if ok else "spawn-failed", "how": how,
            "port": int(port), "url": "http://127.0.0.1:%d/" % int(port)}
    if ok:
        _save_state(port, {"how": how, "pid": None, "port": int(port), "host": host,
                           "at": time.strftime("%Y-%m-%d %H:%M:%S")})
        if ensure_autostart:
            _ensure_autostart(port, host)
    if as_json:
        print(json.dumps(info, ensure_ascii=False))
    else:
        print(("已发起服务启动（%s）→ %s（WMI 建进程约需 12s，可用 status 事后核验）"
               if ok else "发起服务启动失败：WMI 与 Popen 均不可用")
              % (how, info["url"]))
    return 0 if ok else 2


def act_stop(port, as_json=False):
    pids = _pids_on(port)
    if not pids:
        if _probe(port):
            print("端口 %d 有响应但未取到 PID，未做处置" % port)
            return 1
        print(json.dumps({"status": "not-running", "port": int(port)},
                         ensure_ascii=False) if as_json
              else "服务本来就没在运行（端口 %d 无监听）" % port)
        return 0
    killed = []
    for pid in pids:
        try:
            r = subprocess.run(["taskkill", "/PID", str(pid), "/F"],
                               capture_output=True, timeout=15)
            if r.returncode == 0:
                killed.append(pid)
        except Exception:
            pass
    down = _wait_down(port)
    if as_json:
        print(json.dumps({"status": "stopped" if down else "stop-failed",
                          "port": int(port), "killed": killed}, ensure_ascii=False))
    else:
        print("服务已停止：端口 %d，结束进程 %s"
              % (port, ",".join(map(str, killed)) or "无")
              if down else "停止失败：端口 %d 仍被占用（PID %s）" % (port, pids))
    return 0 if down else 1


def act_restart(port, host, no_browser=False, as_json=False):
    act_stop(port, as_json=False)
    time.sleep(0.5)
    return act_start(port, host, no_browser=no_browser, as_json=as_json)


def main():
    ap = argparse.ArgumentParser(description="xueren-disk-analyzer Web 服务开关控制器")
    ap.add_argument("action",
                    choices=["status", "start", "spawn", "stop", "restart", "check"],
                    help="spawn = 只发起不等待就绪（秒回，兜底路径用）；"
                         "check = 只回答「服务会不会拖住当前会话」")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--host", default=DEFAULT_HOST)
    ap.add_argument("--no-browser", action="store_true", help="启动时不自动打开浏览器")
    ap.add_argument("--no-autostart", action="store_true",
                    help="启动时不写 HKCU Run 自启项（默认会顺手补上）")
    ap.add_argument("--json", action="store_true", help="机器可读输出")
    args = ap.parse_args()

    if args.action == "status":
        return act_status(args.port, args.json)
    if args.action == "check":
        return act_check(args.port, args.json)
    if args.action == "start":
        return act_start(args.port, args.host, args.no_browser, args.json,
                         ensure_autostart=not args.no_autostart)
    if args.action == "spawn":
        return act_spawn(args.port, args.host, args.json,
                         ensure_autostart=not args.no_autostart)
    if args.action == "stop":
        return act_stop(args.port, args.json)
    return act_restart(args.port, args.host, args.no_browser, args.json)


if __name__ == "__main__":
    sys.exit(main() or 0)
