import os
import time
import glob
import subprocess
import ctypes
from datetime import datetime
#==============配置=============================================================
BOT_DIR = r"D:\zhenxun_bot-2026"#真寻Bot 主目录的绝对路径
START_BAT = os.path.join(BOT_DIR, "启动与管理.bat")#Bot 启动脚本路径
LOG_DIR = os.path.join(BOT_DIR, "log")#监控的日志目录
LOG_PATTERN = "*.log"#文件
CHECK_INTERVAL = 300 #间隔（s)
FREEZE_THRESHOLD = 1800 #阈值(S)

WATCHDOG_LOG = os.path.join(BOT_DIR, "log", "watchdog_freeze.log")#日志
MY_PID = os.getpid()
PROJECT_MARKER = "zhenxun_bot-2026"


def log(msg):
    t = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{t}] {msg}"
    print(line)
    try:
        os.makedirs(os.path.dirname(WATCHDOG_LOG), exist_ok=True)
        with open(WATCHDOG_LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception as e:
        print(f"  [日志失败: {e}]")


def get_all_pids():
    try:
        r = subprocess.run(
            ["tasklist", "/fo", "csv", "/nh"],
            capture_output=True, text=True, encoding="utf-8", errors="ignore",
            timeout=10
        )
        procs = []
        for line in r.stdout.strip().splitlines():
            line = line.strip()
            if not line:
                continue
            parts = line.split('","')
            if len(parts) >= 2:
                name = parts[0].strip('"')
                pid_str = parts[1].strip('"')
                if pid_str.isdigit():
                    procs.append((int(pid_str), name))
        return procs
    except Exception as e:
        log(f"[ERROR] tasklist 失败: {e}")
        return []


def get_exe_path(pid):
    try:
        kernel32 = ctypes.windll.kernel32
        psapi = ctypes.windll.psapi
        PROCESS_QUERY_INFORMATION = 0x0400
        PROCESS_VM_READ = 0x0010
        h = kernel32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid)
        if not h:
            return None
        buf = ctypes.create_unicode_buffer(1024)
        psapi.GetModuleFileNameExW(h, None, buf, 1024)
        kernel32.CloseHandle(h)
        return buf.value
    except Exception:
        return None


def get_targets():
    procs = get_all_pids()
    targets = []
    for pid, name in procs:
        if pid == MY_PID:
            continue
        path = get_exe_path(pid)
        if path and PROJECT_MARKER in path.lower():
            targets.append(pid)
            log(f"[DEBUG] 目标: {name} PID={pid} 路径={path}")
    return targets


def kill_consoles():
    # 安全替代：不要直接按窗口标题 mass-kill，改为解析 tasklist /v，按 PID 精确关闭
    titles = [
        "真寻Bot 综合管理控制台",
        "选择 真寻Bot 综合管理控制台",
        "Watchdog",
        "选择 Watchdog"
    ]
    try:
        r = subprocess.run(
            ["tasklist", "/v", "/fo", "csv", "/nh"],
            capture_output=True, text=True, encoding="utf-8", errors="ignore", timeout=10
        )
        if r.returncode != 0:
            log(f"[WARN] tasklist /v 返回非0: {r.returncode}")
            return
        for line in r.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            parts = line.split('","')
            if len(parts) < 2:
                continue
            # parts 格式: [Image Name, PID, SessionName, Session#, MemUsage, Status, Username, CPU Time, Window Title]
            try:
                pid_str = parts[1].strip('"')
                pid = int(pid_str)
            except Exception:
                continue
            # 跳过自身
            if pid == MY_PID:
                continue
            window_title = parts[-1].strip('"')
            if window_title in titles:
                # 仅对实际属于项目的可执行文件进行关闭，避免误杀其他程序
                path = get_exe_path(pid)
                if not path:
                    log(f"[SKIP] 窗口匹配但无法获取路径，跳过 PID={pid} 标题={window_title}")
                    continue
                if PROJECT_MARKER in path.lower():
                    try:
                        subprocess.run(["taskkill", "/f", "/t", "/pid", str(pid)], capture_output=True, timeout=10)
                        log(f"[KILL] 已关闭窗口 PID={pid} 标题={window_title} 路径={path}")
                    except Exception as e:
                        log(f"[WARN] 关闭窗口失败 PID={pid}: {e}")
                else:
                    log(f"[SKIP] 窗口标题匹配但 exe 不属于项目，跳过 PID={pid} 路径={path}")
    except Exception as e:
        log(f"[WARN] 解析 tasklist /v 失败: {e}")


def is_alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def kill_all():
    log("[KILL] 开始清理...")
    
    targets = get_targets()
    if targets:
        log(f"[KILL] 发现 {len(targets)} 个进程: {targets}")
        for pid in targets:
            try:
                subprocess.run(
                    ["taskkill", "/f", "/t", "/pid", str(pid)],
                    capture_output=True, timeout=10
                )
            except Exception as e:
                log(f"[KILL] taskkill 失败 PID={pid}: {e}")
        time.sleep(3)
    
    kill_consoles()
    time.sleep(2)
    
    survivors = get_targets()
    if survivors:
        log(f"[KILL] 仍有残留: {survivors}，二次强制...")
        for pid in survivors:
            try:
                subprocess.run(
                    ["taskkill", "/f", "/t", "/pid", str(pid)],
                    capture_output=True, timeout=10
                )
            except Exception as e:
                log(f"[KILL] 二次失败 PID={pid}: {e}")
        time.sleep(2)
        survivors = get_targets()
        if survivors:
            log(f"[CRITICAL] 无法终止: {survivors}")
            return False
    
    log("[KILL] 清理完成")
    return True


def wait_until_clean(max_wait=30):
    """循环等待直到确认完全干净，解决Windows进程回收延迟"""
    start = time.time()
    while time.time() - start < max_wait:
        targets = get_targets()
        if not targets:
            return True
        log(f"[WAIT] 等待清理，仍有: {targets}")
        time.sleep(2)
    return False


def start_bot():
    # 1. 严格验尸：循环确认，不是只检查一次
    if not wait_until_clean(max_wait=30):
        log("[BLOCK] 30秒内仍有残留，跳过启动")
        return
    
    log(f"[START] 启动: {START_BAT}")
    
    # 2. 双保险启动
    try:
        os.startfile(START_BAT)
        log("[START] 已发送 os.startfile")
    except Exception as e:
        log(f"[START] os.startfile 失败: {e}，尝试备用方式...")
        try:
            subprocess.Popen(
                START_BAT,
                shell=True,
                creationflags=subprocess.CREATE_NEW_CONSOLE
            )
            log("[START] 已使用 subprocess.Popen 启动")
        except Exception as e2:
            log(f"[START] 备用方式也失败: {e2}")
            return
    
    # 3. 给足启动时间，多次验证
    log("[START] 等待 20 秒...")
    time.sleep(20)
    
    for attempt in range(1, 4):
        new_targets = get_targets()
        if new_targets:
            log(f"[START] 启动成功，第{attempt}次检测到进程: {new_targets}")
            return
        log(f"[START] 第{attempt}次检测未找到进程，继续等待...")
        time.sleep(5)
    
    log("[WARN] 启动命令已执行，但始终未检测到新进程")


def get_latest_log_time():
    if not os.path.exists(LOG_DIR):
        return None
    files = glob.glob(os.path.join(LOG_DIR, LOG_PATTERN))
    if not files:
        files = glob.glob(os.path.join(BOT_DIR, LOG_PATTERN))
    if not files:
        return None
    return os.path.getmtime(max(files, key=os.path.getmtime))


def is_frozen():
    targets = get_targets()
    if not targets:
        log("[INFO] 未找到 Bot 进程，判定为未运行")
        return False, "not_running"
    
    latest = get_latest_log_time()
    if latest is None:
        log("[WARN] 未找到日志文件")
        return False, "no_log"
    
    idle = time.time() - latest
    if idle > FREEZE_THRESHOLD:
        log(f"[ALERT] 僵死！日志已 {int(idle)} 秒未更新 (PIDs={targets})")
        return True, "timeout"
    
    log(f"[INFO] 正常，日志 {int(idle)} 秒前更新 (PIDs={targets})")
    return False, "ok"


def main():
    log("=" * 50)
    log("真寻Bot防僵死守护 [v8.0-重启强化版]")
    log(f"守护PID: {MY_PID}")
    log("=" * 50)
    
    while True:
        try:
            frozen, reason = is_frozen()
            if reason == "not_running":
                start_bot()
            elif frozen:
                if kill_all():
                    start_bot()
                else:
                    log("[SKIP] 清理失败，暂不启动")
        except Exception as e:
            log(f"[CRITICAL] {e}")
        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()